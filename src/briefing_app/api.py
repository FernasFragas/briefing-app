from datetime import UTC, date, datetime
import hmac
import os
from pathlib import Path
import secrets

from fastapi import Body, FastAPI, Header, HTTPException, Query, status

from briefing_app import __version__
from briefing_app.config import ConfigError, load_config
from briefing_app.delivery import DeliveryError, publish_static_artifacts
from briefing_app.pipeline import run_daily as run_daily_pipeline
from briefing_app.pipeline import run_weekly as run_weekly_pipeline
from briefing_app.preflight import PreflightRunner


app = FastAPI(title="Options Briefing Pipeline", version=__version__)


DEFAULT_RUN_TOKEN_FILENAME = "run-token"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def run_token_path() -> Path:
    """Return the local persisted run-token path used when APP_RUN_TOKEN is unset."""

    configured = os.getenv("APP_RUN_TOKEN_FILE")
    if configured and configured.strip():
        return Path(configured).expanduser()

    data_dir = Path(os.getenv("BRIEFING_DATA_DIR") or "data")
    return data_dir.expanduser() / "ops" / DEFAULT_RUN_TOKEN_FILENAME


def resolve_run_token() -> str:
    """Resolve the bearer token, generating a local persisted token if needed."""

    configured = _clean_token(os.getenv("APP_RUN_TOKEN"))
    if configured:
        return configured

    path = run_token_path()
    existing = _read_persisted_run_token(path)
    if existing:
        return existing

    token = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{token}\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return token


def _require_run_token(authorization: str | None) -> None:
    expected = resolve_run_token()

    supplied = authorization or ""
    if not hmac.compare_digest(supplied, f"Bearer {expected}"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing run token.",
        )


def _read_persisted_run_token(path: Path) -> str | None:
    try:
        return _clean_token(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def _clean_token(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "briefing-app",
        "version": __version__,
        "time": _now_iso(),
    }


@app.post("/run/daily")
def run_daily(
    run_date: date | None = Query(default=None),
    force: bool = Query(default=False),
    max_tickers: int | None = Query(default=None, ge=1),
    authorization: str | None = Header(default=None),
) -> dict:
    _require_run_token(authorization)
    try:
        config = load_config()
        output = run_daily_pipeline(
            config,
            run_date=run_date,
            force=force or not config.pipeline.skip_non_market_days,
            max_tickers=max_tickers if max_tickers is not None else config.pipeline.max_tickers,
            data_mode=config.pipeline.data_mode,
        )
    except ConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return output.to_dict()


@app.post("/run/weekly")
def run_weekly(
    run_date: date | None = Query(default=None),
    force: bool = Query(default=False),
    max_tickers: int | None = Query(default=None, ge=1),
    authorization: str | None = Header(default=None),
) -> dict:
    _require_run_token(authorization)
    try:
        config = load_config()
        output = run_weekly_pipeline(
            config,
            run_date=run_date,
            force=force or not config.pipeline.skip_non_market_days,
            max_tickers=max_tickers if max_tickers is not None else config.pipeline.max_tickers,
            data_mode=config.pipeline.data_mode,
        )
    except ConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return output.to_dict()


@app.post("/delivery/static")
def publish_static_delivery(
    payload: dict = Body(...),
    authorization: str | None = Header(default=None),
) -> dict:
    _require_run_token(authorization)
    try:
        return publish_static_artifacts(
            payload,
            output_root=os.getenv("BRIEFING_OUTPUT_DIR") or "output",
        ).to_dict()
    except DeliveryError as exc:
        raise HTTPException(status_code=500, detail=exc.to_dict()) from exc


@app.post("/score/open-calls")
def score_open_calls(authorization: str | None = Header(default=None)) -> dict[str, str]:
    _require_run_token(authorization)
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Open-call scoring is not implemented yet. Complete task T12.",
    )


@app.post("/preflight")
def run_preflight(
    cache_only: bool = Query(default=False),
    authorization: str | None = Header(default=None),
) -> dict:
    _require_run_token(authorization)
    report = PreflightRunner().run(cache_only=cache_only)
    return report.to_dict()
