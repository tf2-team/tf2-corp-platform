from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml


CONFIG_ROOT = Path(__file__).resolve().parents[1] / "config"
REQUIRED_FILES = (
    "environments/tf2.yaml",
    "queries/official_slos.yaml",
    "queries/checkout.yaml",
    "queries/postgresql.yaml",
    "queries/kafka.yaml",
    "queries/llm.yaml",
    "signals/official_slos.yaml",
    "signals/checkout.yaml",
    "signals/postgresql.yaml",
    "signals/runtime.yaml",
    "signals/kafka.yaml",
    "signals/llm.yaml",
    "detectors/official_slos.yaml",
    "detectors/no_data.yaml",
    "detectors/checkout_dependency.yaml",
    "detectors/db_pressure.yaml",
    "detectors/anomalies.yaml",
    "detectors/flag_signatures.yaml",
    "detectors/kafka.yaml",
    "detectors/llm.yaml",
    "topology/services.yaml",
    "policies/actions.yaml",
    "notification/routes.yaml",
)
PLACEHOLDER_PATTERN = re.compile(r"(<[^>]+>|\bTODO\b|\bTBD\b|REPLACE_ME|CHANGE_ME)", re.IGNORECASE)
FORBIDDEN_RUNTIME_REFERENCES = ("tests/", "tests\\", "docs/aiops", "docs\\aiops")
IDENTITY_KEYS = {"signal_id", "detector_id", "query_id", "route_id", "policy_id"}


def _load(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(text)
    return yaml.safe_load(text)


def _walk(value: Any, location: str, errors: list[str], identities: dict[tuple[str, str], str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{location}.{key}"
            if key in IDENTITY_KEYS and isinstance(item, str):
                identity = (key, item)
                previous = identities.get(identity)
                if previous is not None:
                    errors.append(f"duplicate {key}={item!r}: {previous} and {child}")
                else:
                    identities[identity] = child
            _walk(item, child, errors, identities)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _walk(item, f"{location}[{index}]", errors, identities)
        return
    if not isinstance(value, str):
        return

    if PLACEHOLDER_PATTERN.search(value):
        errors.append(f"placeholder value at {location}: {value!r}")
    lowered = value.lower()
    if "localhost" in lowered or ".example" in lowered:
        errors.append(f"non-production endpoint at {location}: {value!r}")
    if any(fragment in lowered for fragment in FORBIDDEN_RUNTIME_REFERENCES):
        errors.append(f"forbidden runtime reference at {location}: {value!r}")


def validate(config_root: Path = CONFIG_ROOT) -> list[str]:
    errors: list[str] = []
    identities: dict[tuple[str, str], str] = {}

    for relative in REQUIRED_FILES:
        if not (config_root / relative).is_file():
            errors.append(f"missing required configuration file: {relative}")

    for path in sorted((*config_root.rglob("*.yaml"), *config_root.rglob("*.json"))):
        try:
            document = _load(path)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            errors.append(f"cannot parse {path.relative_to(config_root)}: {exc}")
            continue
        if document is None:
            errors.append(f"empty configuration document: {path.relative_to(config_root)}")
            continue
        _walk(document, str(path.relative_to(config_root)), errors, identities)

    action_policy = config_root / "policies" / "actions.yaml"
    if action_policy.is_file():
        actions = _load(action_policy)
        if actions.get("runtime_mode") != "dry-run":
            errors.append("policies/actions.yaml must keep the P0 runtime_mode set to dry-run")
        if actions.get("live_actions"):
            errors.append("policies/actions.yaml must not enable live actions in the P0 scaffold")

    return errors


def main() -> int:
    errors = validate()
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"Configuration scaffold valid: {CONFIG_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
