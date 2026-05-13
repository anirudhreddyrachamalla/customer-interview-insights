/**
 * MSW request handlers for the interview-insights backend.
 *
 * Covers every endpoint in `SPEC.md` so component tests can render real
 * data-fetching components without touching the network.
 *
 * Default responses return the "happy path" payloads from
 * `tests/fixtures/sampleInterview.ts`. Individual tests can override a
 * handler for a single test by calling:
 *
 *   import { http, HttpResponse } from 'msw';
 *   import { server } from '@/tests/msw/server';
 *
 *   server.use(
 *     http.post('*\/api/v1/projects/:projectId/interviews', () =>
 *       HttpResponse.json({ detail: 'audio too large' }, { status: 413 }),
 *     ),
 *   );
 *
 * The wildcard `*` at the start of each URL matches both
 * `http://localhost:8000` (the default `NEXT_PUBLIC_API_URL`) and any
 * other base URL the frontend client might be configured with.
 */

import { http, HttpResponse } from 'msw';
import {
  sampleInterview,
  sampleInterviewProcessing,
  sampleInterviewFailed,
  sampleProject,
  samplePainPoints,
} from '../fixtures/sampleInterview';

const API = '*/api/v1';

export const handlers = [
  // --- Health ----------------------------------------------------------
  http.get(`${API}/health`, () =>
    HttpResponse.json({ status: 'ok', db: 'ok' }),
  ),

  // --- Projects --------------------------------------------------------
  http.get(`${API}/projects`, () =>
    HttpResponse.json({ items: [sampleProject] }),
  ),

  http.post(`${API}/projects`, async ({ request }) => {
    const body = (await request.json()) as { name: string; description?: string };
    return HttpResponse.json(
      {
        ...sampleProject,
        name: body.name,
        description: body.description ?? null,
      },
      { status: 201 },
    );
  }),

  http.get(`${API}/projects/:projectId`, ({ params }) =>
    HttpResponse.json({ ...sampleProject, id: params.projectId }),
  ),

  // --- Interviews ------------------------------------------------------
  http.get(`${API}/projects/:projectId/interviews`, () =>
    HttpResponse.json({ items: [sampleInterview] }),
  ),

  http.post(`${API}/projects/:projectId/interviews`, async ({ params, request }) => {
    // Echo `meeting_notes` from the multipart body so component tests
    // can assert the upload form actually round-trips the field.
    // Missing field, empty string, or whitespace-only → respond with
    // `meeting_notes: null` (matches the backend's normalization rule).
    let meetingNotes: string | null = null;
    try {
      const form = await request.formData();
      const raw = form.get('meeting_notes');
      if (typeof raw === 'string') {
        const trimmed = raw.trim();
        meetingNotes = trimmed.length > 0 ? trimmed : null;
      }
    } catch {
      // Some tests build the request without a multipart body (e.g. a
      // bare retry). Fall through with `meetingNotes = null`.
    }
    return HttpResponse.json(
      {
        ...sampleInterviewProcessing,
        project_id: params.projectId,
        meeting_notes: meetingNotes,
      },
      { status: 202 },
    );
  }),

  http.get(`${API}/interviews/:interviewId`, ({ params }) =>
    HttpResponse.json({
      ...sampleInterview,
      id: params.interviewId,
      pain_points: samplePainPoints,
    }),
  ),

  http.get(`${API}/interviews/:interviewId/audio`, () =>
    // Minimal 1-byte body; the audio player won't actually play it in jsdom.
    new HttpResponse(new Uint8Array([0]), {
      status: 200,
      headers: { 'content-type': 'audio/m4a' },
    }),
  ),

  http.post(`${API}/interviews/:interviewId/retry`, ({ params }) =>
    HttpResponse.json(
      {
        ...sampleInterviewProcessing,
        id: params.interviewId,
      },
      { status: 202 },
    ),
  ),
];

/**
 * Convenience handler set you can splice in via `server.use(...)` to
 * simulate the "failed" status for retry-button tests.
 */
export const failedInterviewHandlers = [
  http.get(`${API}/interviews/:interviewId`, ({ params }) =>
    HttpResponse.json({
      ...sampleInterviewFailed,
      id: params.interviewId,
    }),
  ),
];
