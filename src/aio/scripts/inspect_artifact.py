from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import ZipFile


SERVICE_ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_TOP_LEVEL = {"config", "docs", "runbooks", "scripts", "tests"}
FORBIDDEN_RUNTIME_FILES = {"aiops/collectors/static.py"}


def inspect(wheel_path: Path) -> list[str]:
    errors: list[str] = []
    with ZipFile(wheel_path) as wheel:
        names = set(wheel.namelist())
    for name in sorted(names):
        top_level = name.split("/", 1)[0]
        if top_level in FORBIDDEN_TOP_LEVEL:
            errors.append(f"forbidden top-level artifact content: {name}")
        if name in FORBIDDEN_RUNTIME_FILES:
            errors.append(f"test adapter included in runtime artifact: {name}")
    if not any(name.startswith("aiops/") for name in names):
        errors.append("artifact does not contain the aiops package")
    return errors


def _build_wheel(output: Path) -> Path:
    source = output / "source"
    source.mkdir()
    shutil.copy2(SERVICE_ROOT / "pyproject.toml", source / "pyproject.toml")
    shutil.copy2(SERVICE_ROOT / "README.md", source / "README.md")
    shutil.copytree(SERVICE_ROOT / "aiops", source / "aiops", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", str(output), str(source)],
        check=True,
    )
    wheels = sorted(output.glob("tf2_aiops-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"expected one tf2-aiops wheel, found {len(wheels)}")
    return wheels[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and inspect the production AIOps wheel")
    parser.add_argument("wheel", nargs="?", type=Path)
    args = parser.parse_args()

    if args.wheel:
        wheel_path = args.wheel
        temporary = None
    else:
        temporary = tempfile.TemporaryDirectory(prefix="tf2-aiops-wheel-")
        wheel_path = _build_wheel(Path(temporary.name))

    try:
        errors = inspect(wheel_path)
        if errors:
            for error in errors:
                print(f"ERROR: {error}")
            return 1
        print(f"Artifact boundary valid: {wheel_path}")
        return 0
    finally:
        if temporary is not None:
            temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
