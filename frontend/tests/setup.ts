/**
 * Vitest setup file. Auto-loaded once per worker via `setupFiles` in
 * `vitest.config.ts`.
 *
 * Responsibilities:
 *
 * - Boot the MSW node server before all tests so every fetch in tests goes
 *   through our handlers instead of the real backend.
 * - Reset handlers between tests so a test that locally overrides a
 *   handler (e.g. to simulate an error) doesn't leak to the next test.
 * - Close the server after all tests so the process exits cleanly.
 * - Wire up `@testing-library/jest-dom` matchers so `expect(...).toBeInTheDocument()`
 *   and friends are available.
 *
 * NOTE: Until the frontend teammate adds `vitest`, `@testing-library/*`,
 * `msw`, and `jsdom` to devDependencies in `frontend/package.json`, this
 * file won't actually run — it's the scaffold waiting for the install.
 */

import '@testing-library/jest-dom/vitest';
import { afterAll, afterEach, beforeAll } from 'vitest';
import { server } from './msw/server';

beforeAll(() => {
  // `error` so any unhandled request shows up loud during development. If
  // an existing test starts spuriously failing here, add the missing
  // endpoint to `tests/msw/handlers.ts` rather than downgrading to `warn`.
  server.listen({ onUnhandledRequest: 'error' });
});

afterEach(() => {
  server.resetHandlers();
});

afterAll(() => {
  server.close();
});
