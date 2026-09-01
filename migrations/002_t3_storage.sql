ALTER TABLE briefing_run
  ADD COLUMN IF NOT EXISTS run_type TEXT NOT NULL DEFAULT 'daily';

ALTER TABLE briefing_run
  ADD COLUMN IF NOT EXISTS details JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE briefing_run
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE UNIQUE INDEX IF NOT EXISTS ux_briefing_run_date_type
  ON briefing_run (run_date, run_type);

ALTER TABLE daily_snapshot
  ADD COLUMN IF NOT EXISTS run_id BIGINT REFERENCES briefing_run (id) ON DELETE SET NULL;

ALTER TABLE daily_snapshot
  ADD COLUMN IF NOT EXISTS geography TEXT;

ALTER TABLE daily_snapshot
  ADD COLUMN IF NOT EXISTS component_scores JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE daily_snapshot
  ADD COLUMN IF NOT EXISTS cte_score NUMERIC;

ALTER TABLE daily_snapshot
  ADD COLUMN IF NOT EXISTS confidence_tier TEXT;

ALTER TABLE daily_snapshot
  ADD COLUMN IF NOT EXISTS expression_class TEXT;

CREATE INDEX IF NOT EXISTS idx_daily_snapshot_ticker_date
  ON daily_snapshot (ticker, snap_date DESC);

CREATE INDEX IF NOT EXISTS idx_daily_snapshot_run
  ON daily_snapshot (run_id);

CREATE TABLE IF NOT EXISTS evidence_ledger (
  id BIGSERIAL PRIMARY KEY,
  run_id BIGINT NOT NULL REFERENCES briefing_run (id) ON DELETE CASCADE,
  ticker TEXT NOT NULL DEFAULT '*',
  component TEXT NOT NULL,
  field_name TEXT NOT NULL,
  field_value TEXT NOT NULL,
  source TEXT NOT NULL,
  venue TEXT NOT NULL DEFAULT '*',
  as_of TIMESTAMPTZ NOT NULL,
  endpoint_or_file TEXT NOT NULL DEFAULT '',
  validation_status TEXT NOT NULL,
  note TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_evidence_ledger_natural
  ON evidence_ledger (
    run_id,
    ticker,
    component,
    field_name,
    source,
    venue,
    as_of,
    endpoint_or_file
  );

CREATE INDEX IF NOT EXISTS idx_evidence_ledger_run_ticker
  ON evidence_ledger (run_id, ticker);

CREATE INDEX IF NOT EXISTS idx_evidence_ledger_component
  ON evidence_ledger (component);

CREATE TABLE IF NOT EXISTS candidate_gate (
  run_id BIGINT NOT NULL REFERENCES briefing_run (id) ON DELETE CASCADE,
  ticker TEXT NOT NULL,
  decision TEXT NOT NULL,
  reason TEXT,
  catalyst_name TEXT,
  catalyst_date DATE,
  catalyst_status TEXT,
  expression_class TEXT,
  details JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (run_id, ticker)
);

CREATE INDEX IF NOT EXISTS idx_candidate_gate_decision
  ON candidate_gate (run_id, decision);

CREATE TABLE IF NOT EXISTS component_score (
  run_id BIGINT NOT NULL REFERENCES briefing_run (id) ON DELETE CASCADE,
  ticker TEXT NOT NULL,
  component TEXT NOT NULL,
  score NUMERIC,
  original_weight NUMERIC,
  weight_used NUMERIC,
  validation_status TEXT NOT NULL,
  source_quality TEXT,
  required BOOLEAN NOT NULL DEFAULT false,
  missing_reason TEXT,
  details JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (run_id, ticker, component)
);

CREATE INDEX IF NOT EXISTS idx_component_score_component
  ON component_score (component);

CREATE INDEX IF NOT EXISTS idx_component_score_ticker_component
  ON component_score (ticker, component);

CREATE TABLE IF NOT EXISTS setup_signal (
  id BIGSERIAL PRIMARY KEY,
  run_id BIGINT NOT NULL REFERENCES briefing_run (id) ON DELETE CASCADE,
  ticker TEXT NOT NULL,
  setup_type TEXT NOT NULL,
  horizon TEXT NOT NULL,
  expression_class TEXT NOT NULL,
  direction TEXT,
  confidence_tier TEXT,
  cte_score NUMERIC,
  instrument TEXT,
  invalidation TEXT,
  catalyst_date DATE,
  range_low NUMERIC,
  range_high NUMERIC,
  scenario_probabilities JSONB NOT NULL DEFAULT '{}'::jsonb,
  decision TEXT NOT NULL DEFAULT 'candidate',
  rationale TEXT,
  details JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (run_id, ticker, setup_type, horizon)
);

CREATE INDEX IF NOT EXISTS idx_setup_signal_run_decision
  ON setup_signal (run_id, decision);

CREATE INDEX IF NOT EXISTS idx_setup_signal_ticker
  ON setup_signal (ticker);

ALTER TABLE call_log
  ADD COLUMN IF NOT EXISTS run_id BIGINT REFERENCES briefing_run (id) ON DELETE SET NULL;

ALTER TABLE call_log
  ADD COLUMN IF NOT EXISTS expression_class TEXT NOT NULL DEFAULT 'UNKNOWN';

ALTER TABLE call_log
  ADD COLUMN IF NOT EXISTS invalidation TEXT;

ALTER TABLE call_log
  ADD COLUMN IF NOT EXISTS catalyst_date DATE;

ALTER TABLE call_log
  ADD COLUMN IF NOT EXISTS details JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE call_log
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE UNIQUE INDEX IF NOT EXISTS ux_call_log_natural
  ON call_log (ticker, made_on, horizon, expression_class, setup_type);

CREATE INDEX IF NOT EXISTS idx_call_log_ticker_made_on
  ON call_log (ticker, made_on DESC);

CREATE TABLE IF NOT EXISTS source_preflight (
  run_id BIGINT NOT NULL REFERENCES briefing_run (id) ON DELETE CASCADE,
  source TEXT NOT NULL,
  endpoint TEXT NOT NULL,
  target TEXT NOT NULL DEFAULT '*',
  status TEXT NOT NULL,
  entitlement_status TEXT,
  venue TEXT,
  checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  as_of TIMESTAMPTZ,
  latency_ms NUMERIC,
  validation_status TEXT,
  note TEXT,
  details JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (run_id, source, endpoint, target)
);

CREATE INDEX IF NOT EXISTS idx_source_preflight_status
  ON source_preflight (run_id, status);

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS set_briefing_run_updated_at ON briefing_run;
CREATE TRIGGER set_briefing_run_updated_at
  BEFORE UPDATE ON briefing_run
  FOR EACH ROW
  EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS set_daily_snapshot_updated_at ON daily_snapshot;
CREATE TRIGGER set_daily_snapshot_updated_at
  BEFORE UPDATE ON daily_snapshot
  FOR EACH ROW
  EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS set_evidence_ledger_updated_at ON evidence_ledger;
CREATE TRIGGER set_evidence_ledger_updated_at
  BEFORE UPDATE ON evidence_ledger
  FOR EACH ROW
  EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS set_candidate_gate_updated_at ON candidate_gate;
CREATE TRIGGER set_candidate_gate_updated_at
  BEFORE UPDATE ON candidate_gate
  FOR EACH ROW
  EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS set_component_score_updated_at ON component_score;
CREATE TRIGGER set_component_score_updated_at
  BEFORE UPDATE ON component_score
  FOR EACH ROW
  EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS set_setup_signal_updated_at ON setup_signal;
CREATE TRIGGER set_setup_signal_updated_at
  BEFORE UPDATE ON setup_signal
  FOR EACH ROW
  EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS set_call_log_updated_at ON call_log;
CREATE TRIGGER set_call_log_updated_at
  BEFORE UPDATE ON call_log
  FOR EACH ROW
  EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS set_source_preflight_updated_at ON source_preflight;
CREATE TRIGGER set_source_preflight_updated_at
  BEFORE UPDATE ON source_preflight
  FOR EACH ROW
  EXECUTE FUNCTION set_updated_at();
