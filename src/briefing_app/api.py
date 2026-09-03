from datetime import UTC, date, datetime
import os

from fastapi import Body, FastAPI, Header, HTTPException, Query, status

from briefing_app import __version__
from briefing_app.config import ConfigError, load_config
from briefing_app.delivery import DeliveryError, publish_static_artifacts
from briefing_app.pipeline import run_daily as run_daily_pipeline
from briefing_app.pipeline import run_weekly as run_weekly_pipeline
from briefing_app.preflight import PreflightRunner


app = FastAPI(title="Options Briefing Pipeline", version=__version__)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _require_run_token(authorization: str | None) -> None:
    expected = os.getenv("APP_RUN_TOKEN")
    if not expected:
        return

    if authorization != f"Bearer {expected}":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing run token.",
        )


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
