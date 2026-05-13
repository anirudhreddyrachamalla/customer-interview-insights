/**
 * MSW node server, shared across all Vitest tests.
 *
 * Tests can import this and call `server.use(...customHandlers)` to add
 * one-off overrides; `afterEach` in `tests/setup.ts` calls
 * `server.resetHandlers()` so overrides never leak.
 */

import { setupServer } from 'msw/node';
import { handlers } from './handlers';

export const server = setupServer(...handlers);
