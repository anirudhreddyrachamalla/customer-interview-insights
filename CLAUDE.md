# interview-insights

A web app that analyses customer interview audio recordings and extracts pain points.
Built using Claude Code Agent Teams as the development process.

## High-level architecture

Two services in one repository:

- **`frontend/`** — Next.js 16 (App Router) + TypeScript + Tailwind. SPA-style usage, calls the backend over REST. Runs at http://localhost:3000.
- **`backend/`** — Python 3.12 + FastAPI + SQLAlchemy + Alembic. Owns the database, audio storage, AssemblyAI integration, Claude integration. Runs at http://localhost:8000.

Postgres runs locally on the host (installed via Homebrew). The user has already created the `interview_insights` database and configured `DATABASE_URL` in `.env`. **Do NOT generate a `docker-compose.yml` for Postgres** — connect to the host's Postgres using the credentials in `DATABASE_URL`.

## Module boundaries (do not cross)

- **Frontend never talks to AssemblyAI or Anthropic directly.** All transcription + LLM calls go through the backend.
- **Frontend never reads from Postgres directly.** All data access via backend REST API.
- **Backend never returns audio file paths to the frontend.** Stream audio via signed URLs or a dedicated `/audio/{id}` endpoint.
- **Tests do not call live APIs.** Mock AssemblyAI and Anthropic in unit tests. A small set of integration tests may hit live APIs but must be marked `@pytest.mark.live` and skipped by default.

## Tech choices (locked for v0)

| Concern | Choice |
|---|---|
| Frontend framework | Next.js 16 (App Router) |
| UI styling | Tailwind v4 |
| Frontend testing | Vitest + React Testing Library |
| Backend framework | FastAPI |
| Backend testing | pytest + pytest-asyncio + httpx |
| ORM | SQLAlchemy 2.x async + Alembic |
| Database | Postgres 16 |
| Transcription | AssemblyAI Universal model (with speaker diarization) |
| LLM | Anthropic Claude Sonnet 4.6 (`claude-sonnet-4-6`) via official `anthropic` SDK |
| Audio storage (v0) | Local filesystem under `backend/storage/audio/` |
| Audio storage (later) | S3 |
| Auth (v0) | None |
| Package manager (frontend) | npm |
| Package manager (backend) | uv |

## Verification commands

Teammates run these to verify their work before marking a task complete.

```bash
# Backend
cd backend
uv run pytest                       # unit tests
uv run pytest -m live               # integration tests (require API keys)
uv run mypy app/                    # type check
uv run ruff check .                 # lint
uv run alembic upgrade head         # apply migrations

# Frontend
cd frontend
npm test                            # vitest
npm run typecheck                   # tsc --noEmit
npm run lint                        # eslint
npm run build                       # next build

# E2E (Docker required)
docker compose up -d db
cd backend && uv run uvicorn app.main:app &
cd frontend && npm run dev &
# Manual smoke: upload a sample audio file, confirm pain points appear
```

## Conventions

- **Backend**: Pydantic v2 schemas for all request/response models. Service layer for business logic — endpoints stay thin. Async everywhere.
- **Frontend**: Server components only for static layout. Client components for forms and interactive pieces. TanStack Query for server state. No global state library — TanStack Query + URL state is enough.
- **Commits**: Conventional commits. Each teammate commits their own scope (`feat(backend):`, `feat(frontend):`, `test:`).
- **Type sharing**: Backend Pydantic schemas are the source of truth. Frontend regenerates TS types from `/openapi.json` using `openapi-typescript`.

## Spec & data model

See `SPEC.md` for the v0 product spec, API contracts, and v1 roadmap.

## Out of scope for v0

- Authentication / multi-tenancy
- Transcript upload (audio only)
- Embedding-based semantic search
- Cross-interview analytics / chat agent
- AWS deployment (planned via a deployer teammate after v0 ships locally)
- E2E browser tests (planned via an e2e teammate)
