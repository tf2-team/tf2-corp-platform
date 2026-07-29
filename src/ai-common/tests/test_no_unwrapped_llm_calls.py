import re
from pathlib import Path


def test_no_direct_unwrapped_llm_calls():
    platform_src = Path(__file__).resolve().parents[2]  # src/
    python_files = list(platform_src.rglob("*.py"))
    assert len(python_files) > 0

    allowed_files = {
        "observability.py",
        "bedrock.py",
        "react_agent.py",
    }

    # Match .chat.completions.create(...) or .converse(...) outside allowed adapter files
    pattern_chat = re.compile(r"\.chat\.completions\.create\(")
    pattern_converse = re.compile(r"\.converse\(")

    violations = []
    for pf in python_files:
        if pf.name in allowed_files or "tests" in pf.parts:
            continue
        content = pf.read_text(encoding="utf-8")
        if pattern_chat.search(content):
            violations.append(f"{pf.relative_to(platform_src)}: direct chat.completions.create call")
        if pattern_converse.search(content):
            violations.append(f"{pf.relative_to(platform_src)}: direct converse call")

    assert not violations, f"Direct LLM calls found outside observability adapters: {violations}"


# Change trail: @hungxqt - 2026-07-29 - Regression test asserting all LLM calls route through observability adapters.
