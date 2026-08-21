"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

export function QueryProvider({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 5_000,
            // A retry can sit "paused" waiting for the window to regain
            // focus or come back online before it ever fires — which
            // means a real failure shows neither an error nor data until
            // that happens. For a dashboard that must surface backend
            // failures immediately, one clean attempt is better than a
            // retry that can silently stall.
            retry: false,
            refetchOnWindowFocus: false,
            networkMode: "always",
          },
          mutations: {
            networkMode: "always",
          },
        },
      })
  );

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
