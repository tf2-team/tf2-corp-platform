from __future__ import annotations

import ast
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = SERVICE_ROOT / "aiops"
FORBIDDEN_MODULES = ("tests", "docs.aiops")
FORBIDDEN_TEXT = ("tests/fixtures", "tests\\fixtures", "docs/aiops", "docs\\aiops")


def _imported_modules(tree: ast.AST) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def main() -> int:
    errors: list[str] = []
    for path in sorted(RUNTIME_ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError as exc:
            errors.append(f"{path.relative_to(SERVICE_ROOT)}: syntax error: {exc}")
            continue
        for module in _imported_modules(tree):
            if module == "tests" or module.startswith("tests.") or module == "docs.aiops" or module.startswith("docs.aiops."):
                errors.append(f"{path.relative_to(SERVICE_ROOT)} imports forbidden module {module!r}")
        lowered = text.lower()
        for fragment in FORBIDDEN_TEXT:
            if fragment in lowered:
                errors.append(f"{path.relative_to(SERVICE_ROOT)} contains forbidden runtime reference {fragment!r}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"Runtime boundary valid: {RUNTIME_ROOT} does not import tests or docs/aiops")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
