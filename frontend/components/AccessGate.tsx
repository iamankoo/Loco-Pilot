"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ApiError, api } from "@/lib/api";
import { clearAccessToken, getAccessToken, setAccessToken, UNAUTHORIZED_EVENT } from "@/lib/auth";

type GateState = "checking" | "open" | "locked" | "unreachable";

/** Blocks the app behind an access-token prompt only when the backend says
 * the token is required (HTTP 401). A backend with no ACCESS_TOKEN (local
 * development) answers 200 and the gate is invisible. */
export function AccessGate({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<GateState>("checking");
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const check = useCallback(async () => {
    try {
      await api.checkAccess();
      setState("open");
      return true;
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        setState("locked");
      } else {
        setState("unreachable");
      }
      return false;
    }
  }, []);

  useEffect(() => {
    let active = true;
    api
      .checkAccess()
      .then(() => active && setState("open"))
      .catch((e: unknown) => active && setState(e instanceof ApiError && e.status === 401 ? "locked" : "unreachable"));
    const onUnauthorized = () => {
      clearAccessToken();
      setState("locked");
    };
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => {
      active = false;
      window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    };
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!token.trim()) return;
    setBusy(true);
    setError(null);
    setAccessToken(token.trim());
    const ok = await check();
    if (!ok && getAccessToken()) {
      clearAccessToken();
      setError("That access token was not accepted.");
    }
    setBusy(false);
  }

  if (state === "open") return <>{children}</>;

  return (
    <div className="mx-auto flex min-h-[70vh] max-w-md flex-col justify-center px-6">
      {state === "checking" ? (
        <p className="text-center text-sm text-ivory-faint">Connecting to LocoPilot…</p>
      ) : state === "unreachable" ? (
        <div className="text-center">
          <h1 className="font-display text-2xl text-ivory">Can&apos;t reach the LocoPilot backend</h1>
          <p className="mt-3 text-sm text-ivory-faint">
            The server may be waking up (free hosting sleeps when idle — this can take up to a minute) or is offline.
          </p>
          <button
            type="button"
            onClick={() => {
              setState("checking");
              void check();
            }}
            className="mt-6 rounded-full bg-gold px-6 py-2.5 text-sm font-medium text-ground"
          >
            Try again
          </button>
        </div>
      ) : (
        <form onSubmit={submit} className="rounded-xl border border-gold/25 bg-black/20 p-6">
          <p className="text-xs uppercase tracking-widest2 text-gold/80">Private</p>
          <h1 className="mt-2 font-display text-2xl text-ivory">Enter your access token</h1>
          <p className="mt-2 text-sm text-ivory-faint">
            This LocoPilot server is protected. The token is stored only in this browser.
          </p>
          <label htmlFor="access-token" className="sr-only">
            Access token
          </label>
          <input
            id="access-token"
            type="password"
            autoComplete="off"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            disabled={busy}
            className="mt-5 w-full rounded-md border border-line-strong bg-black/20 px-3 py-2.5 font-mono text-sm text-ivory focus-visible:border-gold/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gold/30"
          />
          {error ? <p className="mt-3 text-sm text-status-error">{error}</p> : null}
          <button
            type="submit"
            disabled={busy || !token.trim()}
            className="mt-5 w-full rounded-full bg-gold px-6 py-2.5 text-sm font-medium text-ground disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy ? "Checking…" : "Unlock"}
          </button>
        </form>
      )}
    </div>
  );
}
