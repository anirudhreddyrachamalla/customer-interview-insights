# Frontend tests

Vitest + React Testing Library suite for the interview-insights Next.js
frontend. Owned by the tester teammate.

## Running

From `frontend/`:

```bash
# Watch mode (default for local dev)
npm test

# Single run, CI-style
npx vitest run

# A specific file
npx vitest run tests/UploadForm.test.tsx
```

`npm test` resolves to `vitest` once the frontend teammate adds the
`test` script (see "Setup needed" below).

## Setup needed before this suite runs

The frontend scaffold is in place (Next 16, React 19, Tailwind 4) but the
test toolchain has **not** been installed yet. To unblock these tests:

1. From `frontend/`, install the test dev dependencies with the project's
   ignore-scripts policy:

   ```bash
   npm install --ignore-scripts --save-dev \
     vitest \
     @vitest/coverage-v8 \
     @vitejs/plugin-react \
     jsdom \
     @testing-library/react \
     @testing-library/jest-dom \
     @testing-library/user-event \
     msw
   ```

2. Add scripts to `frontend/package.json`:

   ```json
   {
     "scripts": {
       "test": "vitest",
       "test:run": "vitest run",
       "typecheck": "tsc --noEmit"
     }
   }
   ```

3. Create `frontend/vitest.config.ts`:

   ```ts
   import { defineConfig } from 'vitest/config';
   import react from '@vitejs/plugin-react';
   import path from 'node:path';

   export default defineConfig({
     plugins: [react()],
     test: {
       environment: 'jsdom',
       globals: true,
       setupFiles: ['./tests/setup.ts'],
       css: false,
     },
     resolve: {
       alias: { '@': path.resolve(__dirname, '.') },
     },
   });
   ```

The tester teammate hasn't written `vitest.config.ts` because it lives at
the project root (not under `tests/`) and would conflict with the
"production code only by frontend teammate" boundary. Frontend teammate:
please commit the config above verbatim, or message tester if you want a
different shape.

## Architecture

```
frontend/tests/
  setup.ts                       # boots MSW server, jest-dom matchers
  msw/
    server.ts                    # setupServer(...handlers)
    handlers.ts                  # default happy-path handlers per endpoint
  fixtures/
    sampleInterview.ts           # shared TS fixtures (mirrors backend JSON)
  UploadForm.test.tsx            # (to be added — coverage target)
  PainPointsPanel.test.tsx       # (to be added — coverage target)
  StatusBadge.test.tsx           # (to be added — coverage target)
```

## MSW

We use MSW (Mock Service Worker) in node mode so every `fetch` made by a
component under test is intercepted.

- `tests/setup.ts` boots the server before all tests, resets handlers
  between tests, and closes after all tests.
- `onUnhandledRequest: 'error'` is on — any unmocked request fails the
  test loudly. If you hit one, add a handler in `tests/msw/handlers.ts`.

To override a handler for a single test:

```ts
import { http, HttpResponse } from 'msw';
import { server } from './msw/server';

it('shows the retry button on failed status', () => {
  server.use(
    http.get('*/api/v1/interviews/:id', () =>
      HttpResponse.json({ /* ...failed payload */ }),
    ),
  );
  // ...
});
```

## Fixtures

Imported from `tests/fixtures/sampleInterview.ts`:

| Export | Use |
|---|---|
| `sampleProject` | A single completed project |
| `sampleInterview` | Completed interview with transcript + pain points |
| `sampleInterviewProcessing` | Interview with `status: "transcribing"` (no transcript yet) |
| `sampleInterviewFailed` | Interview with `status: "failed"` and an `error_message` |
| `sampleTranscriptSegments` | The AssemblyAI segment array |
| `sampleTranscriptText` | Concatenated speaker-labeled transcript |
| `samplePainPoints` | 4 pain points, sorted by severity DESC, created_at ASC |
| `sampleDemographics` | Valid demographics blob covering every enum |

These mirror `backend/tests/fixtures/*.json`. Keep them in sync.

## Coverage targets (v0)

Per `.claude/agents/tester.md`:

- **`UploadForm`** — required-field validation, audio size limit
  (100 MB max per SPEC), every demographics enum dropdown renders the
  right options, submit fires a multipart POST to
  `/api/v1/projects/:id/interviews` with the expected fields. Use MSW to
  assert the request body and status.
- **`PainPointsPanel`** — renders pain points sorted by severity DESC,
  shows empty state when the list is empty, fires the click handler with
  the correct `timestamp_start_sec` when a pain point is clicked.
- **`StatusBadge`** — renders the right label and colour class for each
  of `uploaded | transcribing | analyzing | completed | failed`.
- **`MeetingNotesCard`** (`tests/MeetingNotesCard.test.tsx`) — renders the provided string with `whitespace-pre-wrap` preserved and falls back to the muted "No notes added" empty state when `meetingNotes` is `null`.

Component test files land in a follow-up task — see the project task
board. The harness is ready now.

## Notes to other teammates

Since this repo doesn't run the agent-teams coordination tools, drop notes
here instead of using `SendMessage`. The team-lead will relay.

### To frontend

- Please install the test toolchain and commit `vitest.config.ts` (see
  "Setup needed" above). Without it, `npm test` errors and the verification
  gate stays red.
- When you create `UploadForm`, `PainPointsPanel`, `StatusBadge`, please
  ping the tester so we can write the component tests against the real
  prop shapes. Until those land, the tester writes test files but they'll
  fail to import.
- If you change the structure of an API response shape returned by the
  backend, please update `tests/fixtures/sampleInterview.ts` (or ping
  tester) so MSW responses match what your components expect.

### To backend

- The MSW handlers in `tests/msw/handlers.ts` are coded against the API
  shapes in `SPEC.md`. If you change a response (new field, removed
  field, renamed enum), please ping the tester so the handler payloads
  stay in sync.

### To tester (self)

Follow-up:

- Once the OpenAPI types are generated, tighten the `unknown` shapes in
  `fixtures/sampleInterview.ts` to use the generated types.

#### `it.todo(...)` follow-ups left by task #6

None. The frontend teammate shipped task #4 (Interview detail +
PainPointsPanel) in parallel with task #6, so all coverage targets are
now real, executing tests:

- `tests/PainPointsPanel.test.tsx` — covers severity-DESC sort,
  empty-state copy on `completed`, skeleton placeholders on
  in-flight statuses, and the click handler contract. Authored
  collaboratively with the frontend agent during task #4/#6.
- `tests/RetryButton.test.tsx` — drives `InterviewDetail` directly
  since the Retry button is rendered inline there in v0. Covers the
  "failed → Retry shown", "click triggers POST", "409 → toast", and
  "completed → no Retry" branches.
