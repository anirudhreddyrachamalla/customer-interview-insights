# interview-insights — v0 spec

## Product summary

A tool for founders and product researchers to upload customer interview audio recordings, capture demographics, and automatically extract the pain points the interviewee mentioned. Interviews are organised under user-created projects.

## v0 user stories

1. As a researcher, I can create a project (e.g. "Onboarding research Q2") so I can group related interviews.
2. As a researcher, I can open a project and see all interviews within it.
3. As a researcher, I can create a new interview inside a project by:
   - Uploading an audio file (mp3, wav, m4a, max 100 MB, max 90 minutes)
   - Filling in demographics for the interviewee
   - Selecting the interview type (only `Problem Validation` available in v0)
4. After upload, the system transcribes the audio (with speaker diarization), extracts pain points, and presents them on the interview detail page.
5. On the interview detail page, I can:
   - Play the audio
   - Read the transcript with speaker labels
   - See pain points with: short summary, supporting quote, timestamp, severity (1-5)
   - Click a pain point to show the exact part of the transcript from which the pain point was extracted (transcript pane scrolls to the matching segment and visually highlights it)
6. If processing fails, I can see the error and click a Retry button to re-run the pipeline without re-uploading the audio.

## Data model

### Project
| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `name` | str | required, max 200 |
| `description` | str | optional, max 2000 |
| `created_at` | datetime | server-set |
| `updated_at` | datetime | server-set on any update |

### Interview
| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `project_id` | UUID | FK → Project, cascade delete |
| `audio_path` | str | server-managed path under `backend/storage/audio/` (local filesystem in v0; will move to S3 later) |
| `audio_filename` | str | original filename for display |
| `audio_duration_sec` | float | filled after upload via ffprobe |
| `type` | enum | only `problem_validation` in v0 |
| `demographics` | JSONB | see schema below |
| `transcript_text` | text | nullable, filled after processing |
| `transcript_segments` | JSONB | nullable, AssemblyAI segments — required to render the transcript with speaker labels in the UI AND to map a pain point's timestamps to the segment(s) to highlight on click |
| `status` | enum | `uploaded` → `transcribing` → `analyzing` → `completed` / `failed` |
| `error_message` | str | nullable, set if status=failed |
| `created_at` | datetime | server-set |
| `processed_at` | datetime | nullable, set when status=completed |

### Demographics JSONB schema (all required)
| Field | Type | Notes |
|---|---|---|
| `name` | str | interviewee name or pseudonym |
| `gender` | enum | `male` / `female` / `non_binary` / `prefer_not_to_say` |
| `age` | int | 13 ≤ age ≤ 120 |
| `income` | enum | `under_25k` / `25k_50k` / `50k_100k` / `100k_200k` / `over_200k` / `prefer_not_to_say` |
| `marital_status` | enum | `single` / `married` / `divorced` / `widowed` / `prefer_not_to_say` |
| `country` | str | ISO 3166-1 alpha-2 code (e.g. `US`, `IN`) |
| `job_role` | enum | `engineer` / `designer` / `product_manager` / `marketing` / `sales` / `operations` / `customer_support` / `founder_executive` / `student` / `other` |
| `industry` | enum | `saas_software` / `ecommerce_retail` / `finance_fintech` / `healthcare` / `education` / `media_entertainment` / `manufacturing` / `government_nonprofit` / `hospitality_travel` / `other` |

### PainPoint
| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `interview_id` | UUID | FK → Interview, cascade delete |
| `text` | str | one-sentence summary, max 500 |
| `supporting_quote` | text | exact quote from transcript |
| `timestamp_start_sec` | float | start of supporting quote in audio |
| `timestamp_end_sec` | float | end of supporting quote in audio |
| `severity` | int | 1-5, Claude-scored. UI sorts pain points by `severity DESC, created_at ASC`. |
| `created_at` | datetime | server-set |

## API contracts

Base URL: `http://localhost:8000/api/v1`

### Projects
- `POST /projects` — body: `{name, description?}` → 201 Project
- `GET /projects` — → 200 `{items: Project[]}`
- `GET /projects/{id}` — → 200 Project

### Interviews
- `POST /projects/{project_id}/interviews` — multipart/form-data:
  - `audio`: file (required)
  - `type`: `problem_validation` (required)
  - `demographics`: JSON string (required, schema above)
  - → 202 Interview (status=`uploaded`), processing kicked off in background
- `GET /projects/{project_id}/interviews` — → 200 `{items: Interview[]}`
- `GET /interviews/{id}` — → 200 Interview with:
  - `transcript_text` and `transcript_segments` (when available)
  - `pain_points` array embedded — each pain point includes `text`, `supporting_quote`, `timestamp_start_sec`, `timestamp_end_sec`, `severity`. Frontend uses the timestamps to find and highlight the matching transcript segment(s) on click.
- `GET /interviews/{id}/audio` — streams the audio file (Range requests supported)
- `POST /interviews/{id}/retry` — only valid when current `status` is `failed`. Clears `error_message`, sets status back to `transcribing`, re-runs the pipeline (re-uses the already-uploaded audio file). → 202 Interview. Returns 409 if status is not `failed`.

### Health
- `GET /health` — → 200 `{status: "ok", db: "ok"}`

## Processing pipeline

Triggered when a POST to `/projects/{id}/interviews` succeeds. Runs as a FastAPI BackgroundTask in v0 (no Celery / queue — keep it simple).

1. Set interview.status = `transcribing`
2. Submit audio to AssemblyAI with `speaker_labels=true`, `language_detection=true`
3. Poll AssemblyAI until done (or webhook in a later iteration)
4. Save `transcript_text` and `transcript_segments` (segments include speaker labels + start/end timestamps)
5. Set status = `analyzing`
6. Call Claude with the extraction prompt (see below). Response is structured JSON.
7. Persist pain points (UI orders them by `severity DESC, created_at ASC`)
8. Set status = `completed`, processed_at = now

On error at any step: set status = `failed`, store the message in `error_message`. The frontend should poll `GET /interviews/{id}` every 3s while status is in `[uploaded, transcribing, analyzing]`. When status = `failed`, the frontend shows the error and a Retry button which calls `POST /interviews/{id}/retry` to re-run the pipeline against the existing audio file.

### Claude extraction prompt (sketch — backend teammate to finalize)

```
System: You analyse customer interview transcripts for product research.
You extract pain points the customer mentioned.

User: <transcript with speaker labels>

Return a JSON array of pain points. Each object has:
- text: one-sentence summary (≤ 500 chars)
- supporting_quote: exact quote from the customer (NOT the interviewer)
- timestamp_start_sec, timestamp_end_sec: from the transcript segment containing the supporting_quote
- severity: 1 (mild) to 5 (severe / blocking)

Constraints:
- Only extract pain points spoken by the customer, not the interviewer's questions.
- Each pain point must have a verbatim supporting_quote present in the transcript.
- Timestamps must come from the segment(s) containing the supporting_quote so the UI can highlight that exact part of the transcript.
- 3-10 pain points is the typical range.
```

Use Anthropic SDK's structured outputs / tool-use to force JSON shape. Use prompt caching on the system prompt.

## UI pages

| Route | Description |
|---|---|
| `/` | Projects list. Empty state: "Create your first project". Each project card shows name, interview count, last activity. |
| `/projects/new` | Form: name, description. Submit → redirect to `/projects/{id}`. |
| `/projects/{id}` | Project header (name, description). Interview list with status badges. "New Interview" CTA. |
| `/projects/{id}/interviews/new` | Form: audio file picker, demographics fields (all required, enums rendered as Select inputs), type dropdown. Submit → redirect to `/interviews/{id}`. |
| `/interviews/{id}` | Three-pane layout: left = audio player + demographics summary; center = transcript with speaker labels; right = pain points list (sorted by severity DESC). Clicking a pain point scrolls the transcript pane to the segment(s) whose `[start, end]` overlap the pain point's `[timestamp_start_sec, timestamp_end_sec]` and applies a highlight. Polls every 3s until status = `completed` or `failed`. On `failed`, shows error message + Retry button (calls `POST /interviews/{id}/retry`). |

## v0 acceptance criteria

The v0 is "done" when:

- [ ] A user can create a project from the UI
- [ ] A user can upload an audio file (test with a 5-minute sample interview) with valid demographics
- [ ] The interview moves through statuses `uploaded → transcribing → analyzing → completed` visible in the UI
- [ ] The transcript displays with speaker labels
- [ ] At least 3 pain points are extracted from a real sample interview, each with a supporting quote that exists verbatim in the transcript
- [ ] Clicking a pain point scrolls the transcript pane to the matching segment(s) and highlights them
- [ ] If the pipeline fails, the UI shows the error and the Retry button successfully re-runs processing
- [ ] Backend has unit tests for: demographics validation (including enum values), the extraction prompt's JSON parsing, the status state machine, the retry endpoint (success + 409 path)
- [ ] Frontend has component tests for: the upload form (validation, enum dropdowns), the pain points panel, the retry button behaviour
- [ ] All teammates' `verification commands` (in CLAUDE.md) pass green

## v1 roadmap (informational — do NOT build in v0)

Designed so v0 data + APIs don't paint us into a corner.

- Cross-interview queries by demographics: "what pain points are most common for married people?"
- A chat agent built on Claude with tools: `list_projects`, `list_interviews(filters)`, `search_pain_points(query)`, `get_pain_point_details(id)`, `summarize`.
- Topic / category tagging on pain points (add `category` + `topics` columns later).
- Embedding-based semantic search (add `pgvector` later).
- Multi-user auth.
- AWS deployment (S3 audio storage, RDS for Postgres, ECS Fargate for both services, CloudFront for frontend static assets).
- E2E tests via Playwright against the deployed app.

## Out of scope explicitly

- Transcript-only upload (only audio in v0)
- Manual pain point editing
- Sharing / collaboration features
- Mobile-specific UI (desktop-only design for v0)
