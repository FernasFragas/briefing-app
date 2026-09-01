CREATE TABLE IF NOT EXISTS daily_snapshot (
  ticker TEXT NOT NULL,
  snap_date DATE NOT NULL,
  spot NUMERIC,
  iv_atm NUMERIC,
  iv_rank NUMERIC,
  expected_move_1w NUMERIC,
  expected_move_1m NUMERIC,
  pc_ratio_vol NUMERIC,
  pc_ratio_oi NUMERIC,
  rr_25d NUMERIC,
  realized_vol_20d NUMERIC,
  raw JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (ticker, snap_date)
);

CREATE INDEX IF NOT EXISTS idx_daily_snapshot_date
  ON daily_snapshot (snap_date);

CREATE TABLE IF NOT EXISTS briefing_run (
  id BIGSERIAL PRIMARY KEY,
  run_date DATE NOT NULL,
  status TEXT NOT NULL,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ,
  output_html_path TEXT,
  output_json_path TEXT,
  error JSONB
);

CREATE INDEX IF NOT EXISTS idx_briefing_run_date
  ON briefing_run (run_date);

CREATE TABLE IF NOT EXISTS call_log (
  id BIGSERIAL PRIMARY KEY,
  ticker TEXT NOT NULL,
  made_on DATE NOT NULL,
  horizon TEXT NOT NULL,
  predicted_low NUMERIC,
  predicted_high NUMERIC,
  confidence NUMERIC,
  setup_type TEXT,
  actual_close NUMERIC,
  inside_range BOOLEAN,
  resolved_on DATE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_call_log_unresolved
  ON call_log (resolved_on)
  WHERE resolved_on IS NULL;
