import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'node:path';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    // jsdom 27 pulls in `@asamuzakjp/css-color`, whose CJS entry
    // `require()`s ESM-only `@csstools/css-calc`. On Node ≤ 22.11 that
    // throws ERR_REQUIRE_ESM; Node enables it under
    // `--experimental-require-module` until it becomes the default in
    // 22.12+. In Vitest 4 `execArgv` is a top-level worker option.
    pool: 'forks',
    execArgv: ['--experimental-require-module'],
    globals: true,
    setupFiles: ['./tests/setup.ts'],
    css: false,
  },
  resolve: {
    alias: { '@': path.resolve(__dirname, '.') },
  },
});
