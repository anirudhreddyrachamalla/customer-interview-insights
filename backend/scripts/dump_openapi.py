"""Dump the FastAPI app's OpenAPI spec to a file.

Useful for the frontend's OpenAPI type generator when you don't want to
boot a long-running uvicorn process. Pair with::

    uv run python backend/scripts/dump_openapi.py /tmp/openapi.json
    cd frontend
    npx openapi-typescript /tmp/openapi.json -o lib/api/openapi-schema.ts

Or use the ``frontend/package.json`` ``gen:api`` script if you already
have ``uvicorn`` running on ``localhost:8000``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow ``uv run python backend/scripts/dump_openapi.py`` from the repo
# root as well as ``uv run python scripts/dump_openapi.py`` from
# ``backend/``.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.main import app  # noqa: E402  (sys.path tweak above)


def main(out_path: str = "openapi.json") -> None:
    spec = app.openapi()
    Path(out_path).write_text(json.dumps(spec, indent=2))
    print(f"wrote {len(json.dumps(spec))} bytes to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "openapi.json")
