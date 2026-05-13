# Backend tests

pytest suite for the interview-insights FastAPI service. Owned by the tester teammate.

## Running

From `backend/`:

```bash
# Unit + integration tests (mocked AssemblyAI + Anthropic, host Postgres)
uv run pytest -q

# Verbose, with print/log output
uv run pytest -vv -s

# A single test file or test
uv run pytest tests/test_pipeline.py::test_full_pipeline_smoke -vv

# Opt-in live API tests (hits real AssemblyAI + Anthropic — costs money)
uv run pytest -m live
```

Live tests are auto-skipped unless `-m live` is on the command line. The
mechanism lives in `pytest_collection_modifyitems` in `conftest.py`.

## Database

Tests share the host Postgres instance configured by the backend's own
`app.config.Settings` (which reads `DATABASE_URL` from the repo-root `.env`
via `pydantic-settings`). The conftest does **not** read `.env` directly —
it imports `engine` from `app.db`, so whatever the production code thinks
the database is, that's what the tests use.

Each test gets a fresh `db_session` wrapped in an outer transaction with a
re-spawning SAVEPOINT. On teardown the outer transaction is rolled back,
so:

- service code can call `session.commit()` inside a test without breaking isolation
- no truncation step is needed between tests
- no test-specific database is needed — point `DATABASE_URL` at
  `interview_insights` (the dev DB) and you're fine

If you ever want a dedicated test database, set `DATABASE_URL_TEST` in
`.env` and have the backend teammate wire it through `app.config.Settings`
(currently not done — the dev DB is reused).

## Fixtures

| Fixture | Scope | What it gives you |
|---|---|---|
| `sample_transcript` | session | dict with `text`, `segments[]`, `language_code`, `duration_sec` — AssemblyAI shape |
| `sample_pain_points` | session | list of 4 pain-point dicts; quotes appear verbatim in the transcript |
| `sample_demographics` | session | one valid demographics dict (all required fields, valid enums) |
| `sample_audio_path` | session | absolute `Path` to `sample_interview.m4a` |
| `db_session` | function | `AsyncSession` wrapped in rollback-only outer transaction |
| `client` | function | `httpx.AsyncClient` against the FastAPI app, with `get_db` overridden |
| `mock_transcription` | function | `AsyncMock` replacing `app.services.transcription.transcribe`; returns `sample_transcript` |
| `mock_extraction` | function | `AsyncMock` replacing `app.services.extraction.extract_pain_points`; returns `sample_pain_points` |

### Importing the fixtures

```python
async def test_creates_interview(client, sample_demographics, mock_transcription, mock_extraction):
    ...
```

Anything you list as a fixture argument auto-resolves — no additional
imports needed.

### Mock targets

`mock_transcription` and `mock_extraction` patch the module-level functions
the backend pipeline calls. Coordinate with the backend teammate to keep
these import paths stable:

- `app.services.transcription.transcribe(audio_path: pathlib.Path) -> TranscriptDict`
- `app.services.extraction.extract_pain_points(transcript: TranscriptDict) -> list[PainPointDict]`

If the backend renames either symbol, update the `monkeypatch.setattr`
calls in `conftest.py` to match.

## Sample audio fixture

`tests/fixtures/sample_interview.m4a` is a real short interview clip used
by the live-mode integration smoke test.

- **Current size: 18.5 MB.** That's larger than the <1 MB target in
  `tester.md`. It's kept as-is by team-lead decision (see task #8 notes).
  May be shortened later — when that happens, only the file changes, no
  code update required (`SAMPLE_AUDIO_PATH` already points at `.m4a`).
- Format: `.m4a` (not `.mp3`). SPEC.md accepts `mp3|wav|m4a`.
- Not used by any non-live test. Mocked tests use
  `sample_transcript.json` and never load the audio bytes.

## Coverage targets (v0)

Per `.claude/agents/tester.md`, the suite must cover:

- Demographics Pydantic validation — every enum value, every range bound,
  every missing-field case. Use `sample_demographics` as the base payload
  and mutate one field at a time.
- Pain-point extraction JSON parsing — valid response, malformed JSON,
  quote-not-in-transcript validation failure. Use `sample_pain_points` as
  the valid baseline.
- Status state machine — every valid transition
  (`uploaded → transcribing → analyzing → completed`, `* → failed`) and
  every disallowed transition.
- Project + Interview repository methods — create, get, list, cascade delete.
- One end-to-end pipeline smoke test using `mock_transcription` +
  `mock_extraction`, asserting status transitions and persisted pain points.
- One `@pytest.mark.live` integration test running the real pipeline on
  `sample_interview.m4a`. Skipped by default.
- `test_meeting_notes_pipeline.py::test_pipeline_never_passes_meeting_notes_to_external_services` — pins the contract that `Interview.meeting_notes` is pure storage and is never forwarded to AssemblyAI or Anthropic.

The conftest provides the harness. The test files themselves
(`test_demographics.py`, `test_extraction.py`, `test_state_machine.py`,
`test_repositories.py`, `test_pipeline.py`) land in a follow-up task — see
the project task board.

## Notes to other teammates

Since this repo doesn't run the agent-teams coordination tools, drop notes
here instead of using `SendMessage`. The team-lead will relay.

### To backend

The conftest expects these module-level symbols:

- `app.db.engine` — module-level `AsyncEngine`
- `app.db.get_db` — FastAPI dependency yielding `AsyncSession`
- `app.main.app` — `FastAPI` instance
- `app.services.transcription.transcribe(audio_path) -> dict`
- `app.services.extraction.extract_pain_points(transcript) -> list[dict]`

Until those exist, fixtures that need them call `pytest.skip(...)` with a
clear message so collection stays green. Please:

1. Add `pytest-asyncio` (`asyncio_mode = "auto"`), `pytest`, `httpx`,
   `pytest-mock`, `python-dotenv` (optional — only if you want `.env`
   loaded outside of `app.config.Settings`), and `asyncpg` to the
   backend dev dependencies in `pyproject.toml`.
2. Configure pytest in `pyproject.toml`:
   ```toml
   [tool.pytest.ini_options]
   asyncio_mode = "auto"
   asyncio_default_fixture_loop_scope = "session"
   testpaths = ["tests"]
   markers = ["live: hits real AssemblyAI + Anthropic APIs"]
   ```
   The `asyncio_default_fixture_loop_scope` line silences a deprecation
   warning from `pytest-asyncio>=0.23` and makes our session-scoped
   async `_engine` fixture share one event loop across the run.
3. When you change a Pydantic schema or pain-point JSON shape, ping the
   tester so `sample_demographics.json` and `sample_pain_points.json`
   stay in sync.

### To tester (self)

Follow-up tasks:

- Write `test_demographics.py`, `test_extraction.py`,
  `test_state_machine.py`, `test_repositories.py`, `test_pipeline.py`
  once the backend scaffold lands.
- Add the `@pytest.mark.live` integration test in `test_pipeline_live.py`
  using `sample_audio_path` against the real services.
