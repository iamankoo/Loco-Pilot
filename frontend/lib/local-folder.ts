// Saving a finished project straight onto the user's own disk, using the
// browser File System Access API (Chrome / Edge / other Chromium browsers).
// The user picks a folder once and explicitly grants read/write permission;
// we only ever write inside that folder, under a per-project subfolder.

type PermissionMode = { mode: "readwrite" };
type PermissionState = "granted" | "denied" | "prompt";

export interface FsFileHandle {
  createWritable(): Promise<{ write(data: Blob): Promise<void>; close(): Promise<void> }>;
}

export interface FsDirHandle {
  kind: "directory";
  name: string;
  getDirectoryHandle(name: string, options?: { create?: boolean }): Promise<FsDirHandle>;
  getFileHandle(name: string, options?: { create?: boolean }): Promise<FsFileHandle>;
  queryPermission(descriptor: PermissionMode): Promise<PermissionState>;
  requestPermission(descriptor: PermissionMode): Promise<PermissionState>;
}

type PickerWindow = Window & {
  showDirectoryPicker?: (options?: { id?: string; mode?: "readwrite" }) => Promise<FsDirHandle>;
};

export function isFolderSavingSupported(): boolean {
  return typeof window !== "undefined" && typeof (window as PickerWindow).showDirectoryPicker === "function";
}

// ---- remember the chosen folder across page loads (handles are storable in IndexedDB) ----

const DB_NAME = "locopilot-local";
const STORE = "handles";
const KEY = "root-folder";

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function idbGet(): Promise<FsDirHandle | null> {
  try {
    const db = await openDb();
    return await new Promise((resolve) => {
      const req = db.transaction(STORE).objectStore(STORE).get(KEY);
      req.onsuccess = () => resolve((req.result as FsDirHandle | undefined) ?? null);
      req.onerror = () => resolve(null);
    });
  } catch {
    return null;
  }
}

async function idbSet(handle: FsDirHandle | null): Promise<void> {
  try {
    const db = await openDb();
    await new Promise<void>((resolve) => {
      const tx = db.transaction(STORE, "readwrite");
      if (handle) tx.objectStore(STORE).put(handle, KEY);
      else tx.objectStore(STORE).delete(KEY);
      tx.oncomplete = () => resolve();
      tx.onerror = () => resolve();
    });
  } catch {
    // remembering is a convenience; the picked folder still works this session
  }
}

export async function getSavedFolder(): Promise<FsDirHandle | null> {
  if (!isFolderSavingSupported()) return null;
  return idbGet();
}

export async function hasWritePermission(handle: FsDirHandle): Promise<boolean> {
  try {
    return (await handle.queryPermission({ mode: "readwrite" })) === "granted";
  } catch {
    return false;
  }
}

/** Must be called from a user gesture (click / key press). Shows the
 * browser's own folder picker, which is the permission prompt. Returns null
 * if the user cancels. */
export async function pickFolder(): Promise<FsDirHandle | null> {
  const picker = (window as PickerWindow).showDirectoryPicker;
  if (!picker) return null;
  try {
    const handle = await picker.call(window, { id: "locopilot", mode: "readwrite" });
    await idbSet(handle);
    return handle;
  } catch (error) {
    if ((error as DOMException)?.name === "AbortError") return null;
    throw error;
  }
}

/** Must be called from a user gesture when the saved folder's permission has
 * lapsed (browsers re-ask after a restart). */
export async function reauthorize(handle: FsDirHandle): Promise<boolean> {
  try {
    return (await handle.requestPermission({ mode: "readwrite" })) === "granted";
  } catch {
    return false;
  }
}

export async function forgetFolder(): Promise<void> {
  await idbSet(null);
}

// ---- writing ----

/** A single safe path segment: no traversal, separators, drive letters or
 * characters Windows forbids. Returns null to skip anything suspicious. */
function safeSegment(segment: string): string | null {
  const s = segment.trim();
  if (!s || s === "." || s === ".." || /[<>:"|?*\/\u0000-\u001f]/.test(s)) return null;
  return s;
}

export function safeProjectFolderName(name: string): string {
  const cleaned = name
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
  return safeSegment(cleaned) ?? "locopilot-project";
}

async function dirFor(root: FsDirHandle, segments: string[]): Promise<FsDirHandle> {
  let dir = root;
  for (const segment of segments) dir = await dir.getDirectoryHandle(segment, { create: true });
  return dir;
}

export interface SyncResult {
  folder: string;
  written: number;
  skipped: string[];
}

/** Writes `files` into `<root>/<projectFolder>/…`, creating subfolders as
 * needed. `loadFile` supplies each file's bytes. Existing files with the
 * same path are overwritten. */
export async function saveProjectToFolder(
  root: FsDirHandle,
  projectFolder: string,
  files: { path: string }[],
  loadFile: (path: string) => Promise<Blob>,
  onProgress?: (done: number, total: number) => void
): Promise<SyncResult> {
  const base = await root.getDirectoryHandle(safeProjectFolderName(projectFolder), { create: true });
  const skipped: string[] = [];
  let written = 0;

  for (const [index, file] of files.entries()) {
    const parts = file.path.split("/").map(safeSegment);
    if (parts.length === 0 || parts.some((p) => p === null)) {
      skipped.push(file.path);
      onProgress?.(index + 1, files.length);
      continue;
    }
    const segments = parts as string[];
    const fileName = segments[segments.length - 1] as string;
    const dir = await dirFor(base, segments.slice(0, -1));
    const handle = await dir.getFileHandle(fileName, { create: true });
    const writable = await handle.createWritable();
    await writable.write(await loadFile(file.path));
    await writable.close();
    written += 1;
    onProgress?.(index + 1, files.length);
  }
  return { folder: `${root.name}/${safeProjectFolderName(projectFolder)}`, written, skipped };
}
