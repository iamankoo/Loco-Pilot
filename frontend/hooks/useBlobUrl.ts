"use client";

import { useEffect, useState } from "react";

/** Fetches an authenticated resource once and exposes it as an object URL
 * (revoked on unmount/change). Needed because <img src> and <a href> cannot
 * send the access-token header. Returns null until loaded or on failure. */
export function useBlobUrl(load: (() => Promise<Blob>) | null, key: string): string | null {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!load) return;
    let cancelled = false;
    let created: string | null = null;
    load()
      .then((blob) => {
        if (cancelled) return;
        created = URL.createObjectURL(blob);
        setUrl(created);
      })
      .catch(() => {
        if (!cancelled) setUrl(null);
      });
    return () => {
      cancelled = true;
      if (created) URL.revokeObjectURL(created);
      setUrl(null);
    };
    // `load` is a fresh closure each render; `key` identifies the resource.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return url;
}
