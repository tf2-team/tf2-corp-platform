from __future__ import annotations

import os

def server_address(environment: dict[str, str] | None = None) -> tuple[str, int]:
    values = environment if environment is not None else os.environ
    host = values.get("AIOPS_API_BIND_HOST", "").strip()
    port_text = values.get("AIOPS_API_BIND_PORT", "").strip()
    if not host or not port_text:
        raise RuntimeError("AIOPS_API_BIND_HOST and AIOPS_API_BIND_PORT are required")
    try:
        port = int(port_text)
    except ValueError as error:
        raise RuntimeError("AIOPS_API_BIND_PORT must be an integer") from error
    if not 1 <= port <= 65535:
        raise RuntimeError("AIOPS_API_BIND_PORT must be between 1 and 65535")
    return host, port


def main() -> None:
    import uvicorn

    host, port = server_address()
    uvicorn.run("aiops.api.app:create_app", factory=True, host=host, port=port)


if __name__ == "__main__":
    main()
