"""Unit + API tests for the Project resource.

Covers:

- ``POST /api/v1/projects`` returns 201 with a valid body
- ``GET  /api/v1/projects/{id}`` after create returns the same record
- ``GET  /api/v1/projects`` lists the created project
- ``GET  /api/v1/projects/{missing}`` returns 404 with an RFC 7807 body
- Validation errors: missing name, empty name, name > 200 chars,
  description > 2000 chars
- Service-layer repository methods exercised directly via ``db_session``
"""

from __future__ import annotations

import uuid

import pytest

from app.schemas.project import ProjectCreate
from app.services import projects as projects_service

# ---------------------------------------------------------------------------
# API-level tests
# ---------------------------------------------------------------------------


async def test_create_project_returns_201_with_project_body(client) -> None:
    resp = await client.post(
        "/api/v1/projects",
        json={"name": "Onboarding research Q2", "description": "Initial cohort"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Onboarding research Q2"
    assert body["description"] == "Initial cohort"
    assert "id" in body
    uuid.UUID(body["id"])  # parses
    assert "created_at" in body
    assert "updated_at" in body


async def test_create_project_description_optional(client) -> None:
    resp = await client.post("/api/v1/projects", json={"name": "Just a name"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Just a name"
    assert body["description"] is None


async def test_create_then_get_returns_same_project(client) -> None:
    created = (
        await client.post(
            "/api/v1/projects",
            json={"name": "Round-trip"},
        )
    ).json()
    fetched = await client.get(f"/api/v1/projects/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == created["id"]
    assert fetched.json()["name"] == "Round-trip"


async def test_list_projects_includes_created(client) -> None:
    created = (
        await client.post(
            "/api/v1/projects",
            json={"name": "Visible in list"},
        )
    ).json()
    resp = await client.get("/api/v1/projects")
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    ids = [p["id"] for p in body["items"]]
    assert created["id"] in ids


async def test_get_missing_project_returns_404_rfc7807(client) -> None:
    missing_id = uuid.uuid4()
    resp = await client.get(f"/api/v1/projects/{missing_id}")
    assert resp.status_code == 404
    body = resp.json()
    assert body["status"] == 404
    assert "title" in body
    assert "type" in body
    assert "detail" in body
    assert str(missing_id) in body["detail"]


@pytest.mark.parametrize(
    "payload, missing_field",
    [
        ({}, "name"),
        ({"description": "no name"}, "name"),
    ],
)
async def test_create_project_missing_name_is_422(client, payload, missing_field) -> None:
    resp = await client.post("/api/v1/projects", json=payload)
    assert resp.status_code == 422
    body = resp.json()
    assert body["status"] == 422
    # validation errors are exposed under "errors"
    fields = {tuple(e.get("loc", [])) for e in body.get("errors", [])}
    assert any(missing_field in loc for loc in fields)


async def test_create_project_rejects_empty_name(client) -> None:
    resp = await client.post("/api/v1/projects", json={"name": ""})
    assert resp.status_code == 422


async def test_create_project_rejects_overlong_name(client) -> None:
    resp = await client.post("/api/v1/projects", json={"name": "x" * 201})
    assert resp.status_code == 422


async def test_create_project_rejects_overlong_description(client) -> None:
    resp = await client.post(
        "/api/v1/projects",
        json={"name": "ok", "description": "y" * 2001},
    )
    assert resp.status_code == 422


async def test_create_project_rejects_extra_fields(client) -> None:
    resp = await client.post(
        "/api/v1/projects",
        json={"name": "ok", "color": "blue"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Service-layer / repository tests
# ---------------------------------------------------------------------------


async def test_service_create_and_get(db_session) -> None:
    created = await projects_service.create_project(
        db_session, ProjectCreate(name="svc-create", description="x")
    )
    assert created.id is not None
    fetched = await projects_service.get_project(db_session, created.id)
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.name == "svc-create"


async def test_service_get_missing_returns_none(db_session) -> None:
    result = await projects_service.get_project(db_session, uuid.uuid4())
    assert result is None


async def test_service_list_returns_created(db_session) -> None:
    a = await projects_service.create_project(db_session, ProjectCreate(name="A"))
    b = await projects_service.create_project(db_session, ProjectCreate(name="B"))
    rows = await projects_service.list_projects(db_session)
    ids = {p.id for p in rows}
    assert a.id in ids
    assert b.id in ids
