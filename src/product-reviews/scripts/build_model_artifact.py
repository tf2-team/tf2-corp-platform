"""Build the immutable Hugging Face cache artifact consumed by the EKS init container."""

import argparse
import hashlib
import json
import os
import tarfile
from pathlib import Path

MODEL_ID = "protectai/deberta-v3-base-prompt-injection-v2"
MODEL_REVISION = "89b085cd330414d3e7d9dd787870f315957e1e9f"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("dist/ai-model"))
    args = parser.parse_args()

    output = args.output.resolve()
    cache = output / "huggingface"
    output.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(cache)

    from huggingface_hub import snapshot_download

    snapshot_download(
        repo_id=MODEL_ID,
        revision=MODEL_REVISION,
        cache_dir=cache / "hub",
    )

    # LLM Guard loads by repo ID (without a revision argument). Pin its offline
    # `main` resolution to the reviewed commit rather than contacting the Hub.
    repo_cache = cache / "hub" / f"models--{MODEL_ID.replace('/', '--')}"
    refs = repo_cache / "refs"
    refs.mkdir(parents=True, exist_ok=True)
    (refs / "main").write_text(MODEL_REVISION, encoding="ascii")

    # Validate the exact runtime loader before packaging the cache.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    from llm_guard.input_scanners import PromptInjection

    PromptInjection(threshold=0.5)

    manifest = {
        "model_id": MODEL_ID,
        "revision": MODEL_REVISION,
        "cache_layout": "huggingface_hub",
    }
    (cache / ".model-ready").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")

    archive = output / "model.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        for item in cache.rglob("*"):
            bundle.add(item, arcname=item.relative_to(cache), recursive=False)

    checksum = sha256(archive)
    (output / "model.tar.gz.sha256").write_text(
        f"{checksum}  model.tar.gz\n", encoding="ascii"
    )
    (output / "manifest.json").write_text(
        json.dumps({**manifest, "sha256": checksum}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Built {archive} ({checksum})")


if __name__ == "__main__":
    main()
