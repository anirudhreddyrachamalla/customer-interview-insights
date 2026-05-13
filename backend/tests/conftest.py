"""Shared pytest fixtures for the interview-insights backend test suite.

Conventions (see .claude/agents/tester.md):

- ``pytest-asyncio`` with ``asyncio_mode = "auto"`` (configured in
  ``backend/pyproject.toml`` by the backend teammate).
- Every test runs against the host Postgres database that the backend's
  own ``app.config.Settings`` loads from ``DATABASE_URL``. The
  ``db_session`` fixture wraps each test in an outer transaction and rolls
  it back on teardown, so tests stay isolated without truncating tables.
- ``client`` is an ``httpx.AsyncClient`` wired to the FastAPI app via ASGI
  transport, with the ``get_db`` dependency overridden to use the
  transactional ``db_session``.
- ``mock_transcription`` patches ``app.services.transcription.transcribe``
  to return the canned AssemblyAI-shaped fixture in
  ``tests/fixtures/sample_transcript.json``. No live AssemblyAI traffic.
- ``mock_extraction`` patches ``app.services.extraction.extract_pain_points``
  to return the canned Claude fixture in
  ``tests/fixtures/sample_pain_points.json``. No live Anthropic traffic.
- ``@pytest.mark.live`` opts a test into hitting real AssemblyAI / Anthropic.
  Skipped by default; enable with ``uv run pytest -m live``.

NOTE: All ``app.*`` imports are wrapped in try/except so test collection
still works if the backend scaffold hasn't landed yet. Once
``app/main.py``, ``app/db.py``, ``app/services/transcription.py``, and
``app/services/extraction.py`` exist, the affected fixtures stop skipping.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# NOTE: SPEC.md allows mp3/wav/m4a. The team lead committed an .m4a clip at
# 18.5 MB. We point the live-mode integration smoke test at the .m4a file.
# If a smaller (<1 MB) clip is committed later, update this constant.
SAMPLE_AUDIO_PATH = FIXTURES_DIR / "sample_interview.m4a"

SAMPLE_TRANSCRIPT_PATH = FIXTURES_DIR / "sample_transcript.json"
SAMPLE_PAIN_POINTS_PATH = FIXTURES_DIR / "sample_pain_points.json"
SAMPLE_DEMOGRAPHICS_PATH = FIXTURES_DIR / "sample_demographics.json"


def _load_json(path: Path) -> Any:
    with path.open() as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Canned data fixtures (session-scoped, immutable)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def sample_transcript() -> dict[str, Any]:
    """Canned AssemblyAI-shaped transcript used by mocked tests.

    Shape (matches what ``app.services.transcription.transcribe`` returns):

    ``{
        "text": str,
        "segments": [
            {"speaker": "A"|"B"|...,
             "start": float,
             "end": float,
             "text": str},
            ...
        ],
        "language_code": str,
        "duration_sec": float,
    }``
    """
    return _load_json(SAMPLE_TRANSCRIPT_PATH)


@pytest.fixture(scope="session")
def sample_pain_points() -> list[dict[str, Any]]:
    """Canned Claude pain-point output.

    Each ``supporting_quote`` is present verbatim in ``sample_transcript.text``
    so the quote-in-transcript validator passes.
    """
    return _load_json(SAMPLE_PAIN_POINTS_PATH)


@pytest.fixture(scope="session")
def sample_demographics() -> dict[str, Any]:
    """Valid demographics payload covering every required enum/field."""
    return _load_json(SAMPLE_DEMOGRAPHICS_PATH)


@pytest.fixture(scope="session")
def sample_audio_path() -> Path:
    """Absolute path to the committed sample interview audio file."""
    if not SAMPLE_AUDIO_PATH.exists():
        pytest.skip(f"sample audio fixture not present at {SAMPLE_AUDIO_PATH}")
    return SAMPLE_AUDIO_PATH


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session")
async def _engine():
    """Session-scoped async engine, reused from the app's own session factory.

    We deliberately import from ``app.db`` rather than reading ``.env``
    directly — the backend teammate owns DATABASE_URL loading via
    ``pydantic-settings`` in ``app.config.Settings``. This keeps the test
    harness honest about the app's actual connection logic.
    """
    try:
        from app.db import engine  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:  # pragma: no cover - scaffold gap
        pytest.skip(f"app.db not scaffolded yet ({exc}); tester is waiting on backend")
    yield engine
    # NOTE: do not dispose here — ``app.db`` owns the engine lifecycle.


@pytest_asyncio.fixture
async def db_session(_engine) -> AsyncIterator[Any]:
    """Per-test transactional session.

    Wraps each test in an outer transaction and a re-spawning SAVEPOINT so
    service-layer code that calls ``session.commit()`` still works while
    the outer transaction stays rollback-only. On teardown the outer
    transaction is rolled back, so no state leaks between tests.
    """
    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import AsyncSession

    connection = await _engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)

    # Open a SAVEPOINT and re-open one every time the inner transaction
    # ends, so app code can call ``session.commit()`` without breaking the
    # outer rollback. See SQLAlchemy docs: "Joining a Session into an
    # External Transaction (such as for test suites)".
    await connection.begin_nested()

    @event.listens_for(session.sync_session, "after_transaction_end")
    def _restart_savepoint(sess, trans) -> None:  # pragma: no cover - SQLA event
        if trans.nested and not trans._parent.nested:
            sess.begin_nested()

    try:
        yield session
    finally:
        await session.close()
        if transaction.is_active:
            await transaction.rollback()
        await connection.close()


# ---------------------------------------------------------------------------
# HTTP client fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(db_session) -> AsyncIterator[Any]:
    """Async httpx client wired to the FastAPI app via ASGI transport.

    Overrides the ``get_db`` dependency so endpoints reuse the
    transactional ``db_session`` instead of opening a fresh connection.
    """
    import httpx

    try:
        from app.db import get_db  # type: ignore[import-not-found]
        from app.main import app  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:  # pragma: no cover - scaffold gap
        pytest.skip(f"app.main / app.db not scaffolded yet ({exc}); tester is waiting on backend")

    async def _override_get_db() -> AsyncIterator[Any]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Mock fixtures for external APIs
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_transcription(monkeypatch, sample_transcript) -> AsyncMock:
    """Patch the transcription service so no live AssemblyAI calls happen.

    Returns the ``AsyncMock`` that replaces
    ``app.services.transcription.transcribe`` so individual tests can:

    - assert it was called once with the expected audio path
    - override ``side_effect`` to simulate an AssemblyAI failure
    """
    mock = AsyncMock(return_value=sample_transcript)
    try:
        import app.services.transcription as transcription_mod  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:  # pragma: no cover - scaffold gap
        pytest.skip(
            f"app.services.transcription not scaffolded yet ({exc}); tester is waiting on backend"
        )
    monkeypatch.setattr(transcription_mod, "transcribe", mock)
    return mock


@pytest.fixture
def mock_extraction(monkeypatch, sample_pain_points) -> AsyncMock:
    """Patch the Claude extraction service so no live Anthropic calls happen.

    Returns the ``AsyncMock`` that replaces
    ``app.services.extraction.extract_pain_points``.
    """
    mock = AsyncMock(return_value=sample_pain_points)
    try:
        import app.services.extraction as extraction_mod  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:  # pragma: no cover - scaffold gap
        pytest.skip(
            f"app.services.extraction not scaffolded yet ({exc}); tester is waiting on backend"
        )
    monkeypatch.setattr(extraction_mod, "extract_pain_points", mock)
    return mock


# ---------------------------------------------------------------------------
# Marker registration / live-mode gating
# ---------------------------------------------------------------------------


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers so ``--strict-markers`` doesn't complain."""
    config.addinivalue_line(
        "markers",
        "live: hits real AssemblyAI + Anthropic APIs. Skipped by default; "
        "enable with `uv run pytest -m live`.",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip ``@pytest.mark.live`` tests unless ``-m live`` was passed."""
    marker_expr = config.getoption("-m") or ""
    if "live" in marker_expr:
        return
    skip_live = pytest.mark.skip(reason="live API test; run with `-m live`")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
