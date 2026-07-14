from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPLAY_ROOT = SERVICE_ROOT / "tests" / "replay"


def _load_scenario(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    if REPLAY_ROOT.resolve() not in resolved.parents:
        raise ValueError(f"replay scenarios must stay under {REPLAY_ROOT}")
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    for field in ("scenario_id", "description", "expected"):
        if field not in payload:
            raise ValueError(f"{resolved.name} is missing {field!r}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a synthetic AIOps replay scenario")
    parser.add_argument("scenario", nargs="?", help="scenario ID without .json")
    parser.add_argument("--all", action="store_true", help="validate every checked-in replay scenario")
    args = parser.parse_args()
    if args.all == bool(args.scenario):
        parser.error("provide exactly one scenario ID or --all")

    paths = sorted(REPLAY_ROOT.glob("*.json")) if args.all else [REPLAY_ROOT / f"{args.scenario}.json"]
    if not paths or any(not path.is_file() for path in paths):
        parser.error("requested replay scenario does not exist")

    results = []
    for path in paths:
        scenario = _load_scenario(path)
        results.append({"scenario_id": scenario["scenario_id"], "status": "fixture-valid", "path": str(path.relative_to(SERVICE_ROOT))})
    print(json.dumps({"results": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
