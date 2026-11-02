"use client";

import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import {
  forgetFolder,
  getSavedFolder,
  hasWritePermission,
  isFolderSavingSupported,
  pickFolder,
  reauthorize,
  type FsDirHandle,
} from "@/lib/local-folder";

export interface LocalFolderState {
  /** Browser can write to a user-chosen folder (Chrome / Edge). */
  supported: boolean;
  /** Finished reading any previously chosen folder from the browser. */
  ready: boolean;
  handle: FsDirHandle | null;
  /** Write permission is currently granted for `handle`. */
  granted: boolean;
  /** Opens the browser's folder picker. Call only from a click/keypress. */
  choose: () => Promise<FsDirHandle | null>;
  /** Re-asks permission for the remembered folder. Click/keypress only. */
  regrant: () => Promise<boolean>;
  forget: () => Promise<void>;
}

const subscribeNever = () => () => {};

export function useLocalFolder(): LocalFolderState {
  // Browser capability can't be known during SSR; useSyncExternalStore gives
  // a stable `false` there and the real answer right after hydration.
  const supported = useSyncExternalStore(subscribeNever, isFolderSavingSupported, () => false);
  const [ready, setReady] = useState(false);
  const [handle, setHandle] = useState<FsDirHandle | null>(null);
  const [granted, setGranted] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const saved = await getSavedFolder(); // null when unsupported
      const ok = saved ? await hasWritePermission(saved) : false;
      if (cancelled) return;
      setHandle(saved);
      setGranted(ok);
      setReady(true);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const choose = useCallback(async () => {
    const picked = await pickFolder();
    if (picked) {
      setHandle(picked);
      setGranted(await hasWritePermission(picked));
    }
    return picked;
  }, []);

  const regrant = useCallback(async () => {
    if (!handle) return false;
    const ok = await reauthorize(handle);
    setGranted(ok);
    return ok;
  }, [handle]);

  const forget = useCallback(async () => {
    await forgetFolder();
    setHandle(null);
    setGranted(false);
  }, []);

  return { supported, ready, handle, granted, choose, regrant, forget };
}
