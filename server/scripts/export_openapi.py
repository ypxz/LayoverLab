"""Export the FastAPI OpenAPI schema to <repo root>/openapi.json (run from anywhere)."""

import json
from pathlib import Path

from layoverlab.api.app import app

REPO_ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    schema = app.openapi()
    out = REPO_ROOT / "openapi.json"
    out.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
