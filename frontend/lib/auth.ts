// Access-token handling for deployments where the backend is protected by
// ACCESS_TOKEN. The token is typed in by the user and kept only in this
// browser's localStorage — it is never baked into the frontend bundle
// (a NEXT_PUBLIC_ value would be readable by anyone who loads the site).

const STORAGE_KEY = "locopilot.accessToken";
export const UNAUTHORIZED_EVENT = "locopilot:unauthorized";

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setAccessToken(token: string): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, token);
  } catch {
    // storage unavailable (private mode) — the token just won't persist
  }
}

export function clearAccessToken(): void {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // nothing to clear
  }
}

export function authHeaders(): Record<string, string> {
  const token = getAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export function notifyUnauthorized(): void {
  if (typeof window !== "undefined") window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
}
