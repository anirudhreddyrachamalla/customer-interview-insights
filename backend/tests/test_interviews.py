# ruff: noqa: I001 - phantom isort violation; layout matches conftest.py.
"""Tests for the Interview resource: schemas, repo, state machine, endpoints, audio.

Covers, per the task brief:

- Demographics validation: every enum (valid + invalid), age bounds,
  missing required fields, country code normalization.
- Upload happy path: 202, file persisted, pipeline kicked off (we patch
  ``run_pipeline`` so AssemblyAI / Claude never get hit).
- Upload too-large rejection.
- Retry: success from ``failed``; 409 when not ``failed``.
- Status state machine: every allowed + disallowed transition.
- Audio streaming: 200 without Range, 206 with Range, 416 malformed.
- Cascade delete: deleting a project removes its interviews + their
  pain points.

The conftest fixtures (``client``, ``db_session``, ``sample_demographics``,
``sample_audio_path``) come from ``backend/tests/conftest.py``.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from app.models.interview import Interview
from app.models.pain_point import PainPoint
from app.models.project import Project
from app.schemas.demographics import DemographicsSchema
from app.schemas.interview import InterviewStatus, InterviewType
from app.services import audio as audio_service
from app.services import interviews as interviews_service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_project(client, name: str = "Test project") -> str:
    """POST a project and return its id (str)."""
    resp = await client.post("/api/v1/projects", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _make_interview_row(
    db_session,
    *,
    status: InterviewStatus = InterviewStatus.uploaded,
    project_id: uuid.UUID | None = None,
    audio_path: str = "/tmp/does-not-exist.m4a",
    audio_filename: str = "fixture.m4a",
) -> Interview:
    """Insert a project + interview directly via the service layer."""
    if project_id is None:
        project = Project(name="fixture-proj")
        db_session.add(project)
        await db_session.commit()
        await db_session.refresh(project)
        project_id = project.id

    interview = Interview(
        project_id=project_id,
        audio_path=audio_path,
        audio_filename=audio_filename,
        audio_duration_sec=12.3,
        type=InterviewType.problem_validation,
        demographics={
            "name": "X",
            "gender": "male",
            "age": 30,
            "income": "50k_100k",
            "marital_status": "single",
            "country": "US",
            "job_role": "engineer",
            "industry": "saas_software",
        },
        status=status,
    )
    db_session.add(interview)
    await db_session.commit()
    await db_session.refresh(interview)
    return interview


# ---------------------------------------------------------------------------
# Demographics validation
# ---------------------------------------------------------------------------


class TestDemographicsValidation:
    """Direct Pydantic-level validation of the demographics block."""

    def test_valid_payload_passes(self, sample_demographics):
        DemographicsSchema.model_validate(sample_demographics)

    @pytest.mark.parametrize(
        "field, value",
        [
            ("gender", "not_a_gender"),
            ("income", "not_a_band"),
            ("marital_status", "not_a_status"),
            ("job_role", "not_a_role"),
            ("industry", "not_an_industry"),
        ],
    )
    def test_invalid_enum_value_rejected(self, sample_demographics, field, value):
        payload = {**sample_demographics, field: value}
        with pytest.raises(ValueError):
            DemographicsSchema.model_validate(payload)

    @pytest.mark.parametrize(
        "field, value",
        [
            ("gender", "male"),
            ("gender", "female"),
            ("gender", "non_binary"),
            ("gender", "prefer_not_to_say"),
            ("income", "under_25k"),
            ("income", "25k_50k"),
            ("income", "50k_100k"),
            ("income", "100k_200k"),
            ("income", "over_200k"),
            ("income", "prefer_not_to_say"),
            ("marital_status", "single"),
            ("marital_status", "married"),
            ("marital_status", "divorced"),
            ("marital_status", "widowed"),
            ("marital_status", "prefer_not_to_say"),
            ("job_role", "engineer"),
            ("job_role", "designer"),
            ("job_role", "product_manager"),
            ("job_role", "marketing"),
            ("job_role", "sales"),
            ("job_role", "operations"),
            ("job_role", "customer_support"),
            ("job_role", "founder_executive"),
            ("job_role", "student"),
            ("job_role", "other"),
            ("industry", "saas_software"),
            ("industry", "ecommerce_retail"),
            ("industry", "finance_fintech"),
            ("industry", "healthcare"),
            ("industry", "education"),
            ("industry", "media_entertainment"),
            ("industry", "manufacturing"),
            ("industry", "government_nonprofit"),
            ("industry", "hospitality_travel"),
            ("industry", "other"),
        ],
    )
    def test_every_valid_enum_value_accepted(self, sample_demographics, field, value):
        payload = {**sample_demographics, field: value}
        DemographicsSchema.model_validate(payload)

    def test_age_lower_bound(self, sample_demographics):
        # 12 rejected, 13 accepted.
        with pytest.raises(ValueError):
            DemographicsSchema.model_validate({**sample_demographics, "age": 12})
        DemographicsSchema.model_validate({**sample_demographics, "age": 13})

    def test_age_upper_bound(self, sample_demographics):
        DemographicsSchema.model_validate({**sample_demographics, "age": 120})
        with pytest.raises(ValueError):
            DemographicsSchema.model_validate({**sample_demographics, "age": 121})

    @pytest.mark.parametrize(
        "missing_field",
        [
            "name",
            "gender",
            "age",
            "income",
            "marital_status",
            "country",
            "job_role",
            "industry",
        ],
    )
    def test_missing_each_required_field_rejected(self, sample_demographics, missing_field):
        payload = {k: v for k, v in sample_demographics.items() if k != missing_field}
        with pytest.raises(ValueError):
            DemographicsSchema.model_validate(payload)

    def test_country_lowercase_normalized_to_upper(self, sample_demographics):
        payload = {**sample_demographics, "country": "us"}
        obj = DemographicsSchema.model_validate(payload)
        assert obj.country == "US"

    def test_country_three_letter_rejected(self, sample_demographics):
        payload = {**sample_demographics, "country": "USA"}
        with pytest.raises(ValueError):
            DemographicsSchema.model_validate(payload)

    def test_country_one_letter_rejected(self, sample_demographics):
        payload = {**sample_demographics, "country": "U"}
        with pytest.raises(ValueError):
            DemographicsSchema.model_validate(payload)

    def test_country_digit_rejected(self, sample_demographics):
        payload = {**sample_demographics, "country": "U1"}
        with pytest.raises(ValueError):
            DemographicsSchema.model_validate(payload)


# ---------------------------------------------------------------------------
# Upload endpoint
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_pipeline(monkeypatch):
    """Replace ``run_pipeline`` with a no-op tracker so background tasks
    do not try to actually call AssemblyAI / Claude."""
    calls: list[uuid.UUID] = []

    async def _noop(interview_id: uuid.UUID) -> None:
        calls.append(interview_id)

    # Patch where the endpoint imported the symbol from.
    monkeypatch.setattr("app.api.v1.interviews.run_pipeline", _noop)
    return calls


async def test_upload_happy_path(
    client, sample_demographics, sample_audio_path, mock_pipeline, tmp_path, monkeypatch
):
    # Redirect storage to a per-test tmp dir so we do not litter
    # backend/storage/audio in CI.
    monkeypatch.setattr(audio_service, "_resolved_storage_dir", lambda: tmp_path)

    proj_id = await _make_project(client)

    with sample_audio_path.open("rb") as fh:
        resp = await client.post(
            f"/api/v1/projects/{proj_id}/interviews",
            data={
                "type": "problem_validation",
                "demographics": json.dumps(sample_demographics),
            },
            files={"audio": (sample_audio_path.name, fh, "audio/x-m4a")},
        )

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "uploaded"
    assert body["audio_filename"] == sample_audio_path.name
    assert body["type"] == "problem_validation"
    assert body["pain_points"] == []
    # audio_path must NOT leak to the response.
    assert "audio_path" not in body

    # File persisted on disk under the redirected storage dir.
    saved = list(tmp_path.iterdir())
    assert len(saved) == 1
    assert saved[0].suffix == ".m4a"

    # Pipeline was scheduled exactly once with this interview id.
    assert len(mock_pipeline) == 1
    assert str(mock_pipeline[0]) == body["id"]


async def test_upload_rejects_oversized_file(client, sample_demographics, tmp_path, monkeypatch):
    monkeypatch.setattr(audio_service, "_resolved_storage_dir", lambda: tmp_path)
    # Bring the cap down to a tiny number so a small payload trips it.
    monkeypatch.setattr(audio_service, "MAX_UPLOAD_BYTES", 16)

    proj_id = await _make_project(client)

    # 32 bytes of dummy mp3-ish data; mime is allowed but size > cap.
    payload = b"\xff\xfb\x90\x00" * 8
    resp = await client.post(
        f"/api/v1/projects/{proj_id}/interviews",
        data={
            "type": "problem_validation",
            "demographics": json.dumps(sample_demographics),
        },
        files={"audio": ("tiny.mp3", payload, "audio/mpeg")},
    )

    assert resp.status_code == 413, resp.text
    body = resp.json()
    assert body["status"] == 413
    assert "exceeds" in body["detail"]


async def test_upload_rejects_bad_mime(client, sample_demographics, tmp_path, monkeypatch):
    monkeypatch.setattr(audio_service, "_resolved_storage_dir", lambda: tmp_path)
    proj_id = await _make_project(client)

    resp = await client.post(
        f"/api/v1/projects/{proj_id}/interviews",
        data={
            "type": "problem_validation",
            "demographics": json.dumps(sample_demographics),
        },
        files={"audio": ("bad.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 415, resp.text


async def test_upload_invalid_demographics_returns_422(
    client, sample_demographics, tmp_path, monkeypatch
):
    monkeypatch.setattr(audio_service, "_resolved_storage_dir", lambda: tmp_path)
    proj_id = await _make_project(client)

    bad = {**sample_demographics, "gender": "not_real"}
    resp = await client.post(
        f"/api/v1/projects/{proj_id}/interviews",
        data={
            "type": "problem_validation",
            "demographics": json.dumps(bad),
        },
        files={"audio": ("x.mp3", b"\xff\xfb\x90\x00", "audio/mpeg")},
    )
    assert resp.status_code == 422, resp.text


async def test_upload_to_missing_project_returns_404(
    client, sample_demographics, tmp_path, monkeypatch
):
    monkeypatch.setattr(audio_service, "_resolved_storage_dir", lambda: tmp_path)
    resp = await client.post(
        f"/api/v1/projects/{uuid.uuid4()}/interviews",
        data={
            "type": "problem_validation",
            "demographics": json.dumps(sample_demographics),
        },
        files={"audio": ("x.mp3", b"\xff\xfb\x90\x00", "audio/mpeg")},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET endpoints
# ---------------------------------------------------------------------------


async def test_get_interview_returns_404_when_missing(client):
    resp = await client.get(f"/api/v1/interviews/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_list_interviews_includes_created(client, db_session, sample_demographics):
    project = Project(name="list-test")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    iv = await _make_interview_row(db_session, project_id=project.id)

    resp = await client.get(f"/api/v1/projects/{project.id}/interviews")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    ids = {item["id"] for item in body["items"]}
    assert str(iv.id) in ids


async def test_get_interview_orders_pain_points_severity_desc(client, db_session):
    iv = await _make_interview_row(db_session)

    # Insert pain points out-of-order; service must sort them
    # severity DESC, created_at ASC.
    low = PainPoint(
        interview_id=iv.id,
        text="low",
        supporting_quote="q1",
        timestamp_start_sec=0,
        timestamp_end_sec=1,
        severity=2,
    )
    high = PainPoint(
        interview_id=iv.id,
        text="high",
        supporting_quote="q2",
        timestamp_start_sec=0,
        timestamp_end_sec=1,
        severity=5,
    )
    mid = PainPoint(
        interview_id=iv.id,
        text="mid",
        supporting_quote="q3",
        timestamp_start_sec=0,
        timestamp_end_sec=1,
        severity=3,
    )
    db_session.add_all([low, high, mid])
    await db_session.commit()

    resp = await client.get(f"/api/v1/interviews/{iv.id}")
    assert resp.status_code == 200, resp.text
    severities = [pp["severity"] for pp in resp.json()["pain_points"]]
    assert severities == [5, 3, 2]


# ---------------------------------------------------------------------------
# Retry endpoint
# ---------------------------------------------------------------------------


async def test_retry_from_failed_succeeds(client, db_session, mock_pipeline):
    iv = await _make_interview_row(db_session, status=InterviewStatus.failed)
    # Stamp an error message that retry should clear.
    iv.error_message = "boom"
    await db_session.commit()

    resp = await client.post(f"/api/v1/interviews/{iv.id}/retry")
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "transcribing"
    assert body["error_message"] is None
    assert mock_pipeline == [iv.id]


@pytest.mark.parametrize(
    "starting_status",
    [
        InterviewStatus.uploaded,
        InterviewStatus.transcribing,
        InterviewStatus.analyzing,
        InterviewStatus.completed,
    ],
)
async def test_retry_when_not_failed_returns_409(
    client, db_session, starting_status, mock_pipeline
):
    iv = await _make_interview_row(db_session, status=starting_status)
    resp = await client.post(f"/api/v1/interviews/{iv.id}/retry")
    assert resp.status_code == 409, resp.text
    assert "failed" in resp.json()["detail"]
    # Pipeline must NOT have been kicked off.
    assert mock_pipeline == []


async def test_retry_missing_interview_returns_404(client, mock_pipeline):
    resp = await client.post(f"/api/v1/interviews/{uuid.uuid4()}/retry")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Status state machine (service-layer direct tests)
# ---------------------------------------------------------------------------


_ALL_STATUSES = list(InterviewStatus)
_ALLOWED = {
    (InterviewStatus.uploaded, InterviewStatus.transcribing),
    (InterviewStatus.uploaded, InterviewStatus.failed),
    (InterviewStatus.transcribing, InterviewStatus.analyzing),
    (InterviewStatus.transcribing, InterviewStatus.failed),
    (InterviewStatus.analyzing, InterviewStatus.completed),
    (InterviewStatus.analyzing, InterviewStatus.failed),
    (InterviewStatus.failed, InterviewStatus.transcribing),
}


@pytest.mark.parametrize("from_status, to_status", sorted(_ALLOWED, key=str))
async def test_state_machine_allows(db_session, from_status, to_status):
    iv = await _make_interview_row(db_session, status=from_status)
    await interviews_service.transition_status(db_session, iv, to_status)
    assert iv.status is to_status


@pytest.mark.parametrize(
    "from_status, to_status",
    sorted(
        (
            (a, b)
            for a in _ALL_STATUSES
            for b in _ALL_STATUSES
            if a is not b and (a, b) not in _ALLOWED
        ),
        key=str,
    ),
)
async def test_state_machine_disallows(db_session, from_status, to_status):
    iv = await _make_interview_row(db_session, status=from_status)
    with pytest.raises(interviews_service.InvalidStatusTransitionError):
        await interviews_service.transition_status(db_session, iv, to_status)


async def test_mark_completed_sets_processed_at(db_session):
    iv = await _make_interview_row(db_session, status=InterviewStatus.analyzing)
    assert iv.processed_at is None
    await interviews_service.mark_completed(db_session, iv)
    assert iv.status is InterviewStatus.completed
    assert iv.processed_at is not None


async def test_mark_failed_sets_error_message(db_session):
    iv = await _make_interview_row(db_session, status=InterviewStatus.transcribing)
    await interviews_service.mark_failed(db_session, iv, "boom")
    assert iv.status is InterviewStatus.failed
    assert iv.error_message == "boom"


async def test_clear_error_for_retry_rejects_non_failed(db_session):
    iv = await _make_interview_row(db_session, status=InterviewStatus.uploaded)
    with pytest.raises(interviews_service.InvalidStatusTransitionError):
        await interviews_service.clear_error_for_retry(db_session, iv)


# ---------------------------------------------------------------------------
# Audio streaming
# ---------------------------------------------------------------------------


async def test_audio_stream_200_no_range(client, db_session, tmp_path):
    # Write a small file directly to disk and point the interview at it.
    audio_file = tmp_path / "stream.mp3"
    audio_file.write_bytes(b"abcdefghij" * 100)  # 1000 bytes
    iv = await _make_interview_row(db_session, audio_path=str(audio_file))

    resp = await client.get(f"/api/v1/interviews/{iv.id}/audio")
    assert resp.status_code == 200
    assert resp.headers.get("accept-ranges") == "bytes"
    assert resp.headers.get("content-type", "").startswith("audio/mpeg")
    assert len(resp.content) == 1000


async def test_audio_stream_206_with_range(client, db_session, tmp_path):
    audio_file = tmp_path / "stream.mp3"
    audio_file.write_bytes(b"abcdefghij" * 100)
    iv = await _make_interview_row(db_session, audio_path=str(audio_file))

    resp = await client.get(
        f"/api/v1/interviews/{iv.id}/audio",
        headers={"Range": "bytes=0-99"},
    )
    assert resp.status_code == 206
    assert resp.headers.get("accept-ranges") == "bytes"
    assert resp.headers["content-range"] == "bytes 0-99/1000"
    assert resp.headers["content-length"] == "100"
    assert len(resp.content) == 100


async def test_audio_stream_416_malformed_range(client, db_session, tmp_path):
    audio_file = tmp_path / "stream.mp3"
    audio_file.write_bytes(b"abcdefghij" * 100)
    iv = await _make_interview_row(db_session, audio_path=str(audio_file))

    resp = await client.get(
        f"/api/v1/interviews/{iv.id}/audio",
        headers={"Range": "not-a-range"},
    )
    assert resp.status_code == 416


async def test_audio_stream_416_unsatisfiable_range(client, db_session, tmp_path):
    audio_file = tmp_path / "stream.mp3"
    audio_file.write_bytes(b"x" * 10)
    iv = await _make_interview_row(db_session, audio_path=str(audio_file))

    resp = await client.get(
        f"/api/v1/interviews/{iv.id}/audio",
        headers={"Range": "bytes=1000-2000"},
    )
    assert resp.status_code == 416


async def test_audio_stream_404_when_file_missing(client, db_session):
    iv = await _make_interview_row(db_session, audio_path="/tmp/nope-does-not-exist.mp3")
    resp = await client.get(f"/api/v1/interviews/{iv.id}/audio")
    assert resp.status_code == 404


async def test_audio_stream_404_when_interview_missing(client):
    resp = await client.get(f"/api/v1/interviews/{uuid.uuid4()}/audio")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Cascade delete
# ---------------------------------------------------------------------------


async def test_cascade_delete_removes_interviews_and_pain_points(
    db_session,
):
    """Deleting a project removes its interviews + their pain points.

    We exercise the DB-level ``ON DELETE CASCADE`` directly so the
    contract is validated end-to-end.
    """
    iv = await _make_interview_row(db_session)
    project_id = iv.project_id

    pp = PainPoint(
        interview_id=iv.id,
        text="x",
        supporting_quote="y",
        timestamp_start_sec=0,
        timestamp_end_sec=1,
        severity=3,
    )
    db_session.add(pp)
    await db_session.commit()

    # Pre-condition: both exist.
    assert (
        await db_session.execute(select(Interview).where(Interview.id == iv.id))
    ).scalar_one_or_none() is not None
    assert (
        await db_session.execute(select(PainPoint).where(PainPoint.id == pp.id))
    ).scalar_one_or_none() is not None

    # Delete the project; cascade should sweep the rest.
    await db_session.execute(delete(Project).where(Project.id == project_id))
    await db_session.commit()

    assert (
        await db_session.execute(select(Interview).where(Interview.id == iv.id))
    ).scalar_one_or_none() is None
    assert (
        await db_session.execute(select(PainPoint).where(PainPoint.id == pp.id))
    ).scalar_one_or_none() is None


# ---------------------------------------------------------------------------
# audio service unit tests (parse_range corner cases)
# ---------------------------------------------------------------------------


def test_parse_range_suffix_form():
    start, end = audio_service._parse_range("bytes=-100", 1000)
    assert (start, end) == (900, 999)


def test_parse_range_open_ended():
    start, end = audio_service._parse_range("bytes=500-", 1000)
    assert (start, end) == (500, 999)


def test_parse_range_clamps_end_to_eof():
    start, end = audio_service._parse_range("bytes=0-9999", 1000)
    assert (start, end) == (0, 999)


@pytest.mark.parametrize(
    "header",
    [
        "bananas",
        "bytes=",
        "bytes=-",
        "bytes=abc-def",
        "bytes=10-5",  # end < start
    ],
)
def test_parse_range_rejects_malformed(header):
    with pytest.raises(ValueError):
        audio_service._parse_range(header, 1000)


def test_content_type_for_path():
    assert audio_service.content_type_for_path(Path("a.mp3")) == "audio/mpeg"
    assert audio_service.content_type_for_path(Path("a.wav")) == "audio/wav"
    assert audio_service.content_type_for_path(Path("a.m4a")) == "audio/mp4"
    assert audio_service.content_type_for_path(Path("a.bin")) == "application/octet-stream"


# ---------------------------------------------------------------------------
# meeting_notes field (v0.1 feature)
# ---------------------------------------------------------------------------


async def test_upload_with_meeting_notes_persists_and_returns(
    client, sample_demographics, sample_audio_path, mock_pipeline, tmp_path, monkeypatch
):
    """meeting_notes provided on upload -> persisted; GET returns it."""
    monkeypatch.setattr(audio_service, "_resolved_storage_dir", lambda: tmp_path)
    proj_id = await _make_project(client)

    notes = "Customer was very engaged. Mentioned a competitor twice."
    with sample_audio_path.open("rb") as fh:
        resp = await client.post(
            f"/api/v1/projects/{proj_id}/interviews",
            data={
                "type": "problem_validation",
                "demographics": json.dumps(sample_demographics),
                "meeting_notes": notes,
            },
            files={"audio": (sample_audio_path.name, fh, "audio/x-m4a")},
        )

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["meeting_notes"] == notes

    # Round-trip via GET.
    get_resp = await client.get(f"/api/v1/interviews/{body['id']}")
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["meeting_notes"] == notes


async def test_upload_without_meeting_notes_stores_null(
    client, sample_demographics, sample_audio_path, mock_pipeline, tmp_path, monkeypatch, db_session
):
    """meeting_notes omitted -> column is NULL; GET returns null."""
    monkeypatch.setattr(audio_service, "_resolved_storage_dir", lambda: tmp_path)
    proj_id = await _make_project(client)

    with sample_audio_path.open("rb") as fh:
        resp = await client.post(
            f"/api/v1/projects/{proj_id}/interviews",
            data={
                "type": "problem_validation",
                "demographics": json.dumps(sample_demographics),
            },
            files={"audio": (sample_audio_path.name, fh, "audio/x-m4a")},
        )

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["meeting_notes"] is None

    # And the DB column is genuinely NULL (not empty string).
    iv = (
        await db_session.execute(
            select(Interview).where(Interview.id == uuid.UUID(body["id"]))
        )
    ).scalar_one()
    assert iv.meeting_notes is None


async def test_upload_with_empty_string_meeting_notes_stored_as_null(
    client, sample_demographics, sample_audio_path, mock_pipeline, tmp_path, monkeypatch, db_session
):
    """meeting_notes='' -> normalized to NULL."""
    monkeypatch.setattr(audio_service, "_resolved_storage_dir", lambda: tmp_path)
    proj_id = await _make_project(client)

    with sample_audio_path.open("rb") as fh:
        resp = await client.post(
            f"/api/v1/projects/{proj_id}/interviews",
            data={
                "type": "problem_validation",
                "demographics": json.dumps(sample_demographics),
                "meeting_notes": "",
            },
            files={"audio": (sample_audio_path.name, fh, "audio/x-m4a")},
        )

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["meeting_notes"] is None

    iv = (
        await db_session.execute(
            select(Interview).where(Interview.id == uuid.UUID(body["id"]))
        )
    ).scalar_one()
    assert iv.meeting_notes is None


async def test_upload_with_whitespace_only_meeting_notes_stored_as_null(
    client, sample_demographics, sample_audio_path, mock_pipeline, tmp_path, monkeypatch, db_session
):
    """meeting_notes='   ' -> normalized to NULL."""
    monkeypatch.setattr(audio_service, "_resolved_storage_dir", lambda: tmp_path)
    proj_id = await _make_project(client)

    with sample_audio_path.open("rb") as fh:
        resp = await client.post(
            f"/api/v1/projects/{proj_id}/interviews",
            data={
                "type": "problem_validation",
                "demographics": json.dumps(sample_demographics),
                "meeting_notes": "   \t\n  ",
            },
            files={"audio": (sample_audio_path.name, fh, "audio/x-m4a")},
        )

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["meeting_notes"] is None

    iv = (
        await db_session.execute(
            select(Interview).where(Interview.id == uuid.UUID(body["id"]))
        )
    ).scalar_one()
    assert iv.meeting_notes is None


async def test_upload_with_exactly_10000_char_meeting_notes_accepted(
    client, sample_demographics, sample_audio_path, mock_pipeline, tmp_path, monkeypatch
):
    """meeting_notes at the 10,000-character boundary -> accepted."""
    monkeypatch.setattr(audio_service, "_resolved_storage_dir", lambda: tmp_path)
    proj_id = await _make_project(client)

    notes = "a" * 10_000
    with sample_audio_path.open("rb") as fh:
        resp = await client.post(
            f"/api/v1/projects/{proj_id}/interviews",
            data={
                "type": "problem_validation",
                "demographics": json.dumps(sample_demographics),
                "meeting_notes": notes,
            },
            files={"audio": (sample_audio_path.name, fh, "audio/x-m4a")},
        )

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["meeting_notes"] == notes
    assert len(body["meeting_notes"]) == 10_000


async def test_upload_with_10001_char_meeting_notes_returns_422_with_loc(
    client, sample_demographics, sample_audio_path, mock_pipeline, tmp_path, monkeypatch
):
    """meeting_notes one over the cap -> 422 RFC 7807 with errors[0].loc=['meeting_notes']."""
    monkeypatch.setattr(audio_service, "_resolved_storage_dir", lambda: tmp_path)
    proj_id = await _make_project(client)

    notes = "a" * 10_001
    with sample_audio_path.open("rb") as fh:
        resp = await client.post(
            f"/api/v1/projects/{proj_id}/interviews",
            data={
                "type": "problem_validation",
                "demographics": json.dumps(sample_demographics),
                "meeting_notes": notes,
            },
            files={"audio": (sample_audio_path.name, fh, "audio/x-m4a")},
        )

    assert resp.status_code == 422, resp.text
    body = resp.json()
    # Standard RFC 7807 members.
    assert body["status"] == 422
    assert body["title"] == "Validation Error"
    assert "type" in body
    assert "detail" in body
    # Field-level errors for inline frontend mapping.
    assert "errors" in body and len(body["errors"]) >= 1
    assert body["errors"][0]["loc"] == ["meeting_notes"]


async def test_upload_with_meeting_notes_trims_whitespace_before_persist(
    client, sample_demographics, sample_audio_path, mock_pipeline, tmp_path, monkeypatch
):
    """Surrounding whitespace is trimmed before storage."""
    monkeypatch.setattr(audio_service, "_resolved_storage_dir", lambda: tmp_path)
    proj_id = await _make_project(client)

    with sample_audio_path.open("rb") as fh:
        resp = await client.post(
            f"/api/v1/projects/{proj_id}/interviews",
            data={
                "type": "problem_validation",
                "demographics": json.dumps(sample_demographics),
                "meeting_notes": "  hello world  \n",
            },
            files={"audio": (sample_audio_path.name, fh, "audio/x-m4a")},
        )

    assert resp.status_code == 202, resp.text
    assert resp.json()["meeting_notes"] == "hello world"


async def test_retry_preserves_meeting_notes(client, db_session, mock_pipeline):
    """A retry from 'failed' must not clobber the existing meeting_notes."""
    iv = await _make_interview_row(db_session, status=InterviewStatus.failed)
    iv.error_message = "transcription died"
    iv.meeting_notes = "original notes about the customer"
    await db_session.commit()
    await db_session.refresh(iv)

    resp = await client.post(f"/api/v1/interviews/{iv.id}/retry")
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "transcribing"
    assert body["error_message"] is None
    assert body["meeting_notes"] == "original notes about the customer"

    # And re-fetched directly via the ORM.
    refreshed = (
        await db_session.execute(select(Interview).where(Interview.id == iv.id))
    ).scalar_one()
    assert refreshed.meeting_notes == "original notes about the customer"
