"use client";

import { useState, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { Toaster } from "@/components/ui/sonner";

/**
 * App-wide React context providers.
 *
 * Currently just TanStack Query. The QueryClient is held in `useState`
 * so it survives the initial client mount but is created fresh per app
 * instance (avoids leaking cache across users in dev hot-reloads).
 *
 * Defaults:
 * - `staleTime: 30_000` so navigating back to a page doesn't refetch
 *   immediately; explicit invalidation handles mutations.
 * - `refetchOnWindowFocus: false` — this is an internal tool, we don't
 *   want surprise refetches while a researcher is reading a transcript.
 *
 * Per-query overrides (e.g. the interview detail page's 3s poll) live
 * in the hook for that query in `lib/api/hooks.ts`.
 */
export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            refetchOnWindowFocus: false,
            retry: 1,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={client}>
      {children}
      <Toaster richColors closeButton position="bottom-right" />
    </QueryClientProvider>
  );
}
