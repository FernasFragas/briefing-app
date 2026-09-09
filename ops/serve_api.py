from __future__ import annotations

import os

from _common import configure_environment


def main() -> int:
    configure_environment()

    import uvicorn

    from briefing_app.api import resolve_run_token, run_token_path

    resolve_run_token()
    host = os.getenv("BRIEFING_API_HOST") or "127.0.0.1"
    port = int(os.getenv("BRIEFING_API_PORT") or os.getenv("PORT") or "8000")
    print(f"Serving briefing app on http://{host}:{port}")
    print(f"Run token file: {run_token_path()}")
    uvicorn.run("briefing_app.api:app", host=host, port=port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
