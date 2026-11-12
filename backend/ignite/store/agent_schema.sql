-- Agent configuration (single row, key = 'global')
CREATE TABLE IF NOT EXISTS agent_config (
    key       TEXT PRIMARY KEY,
    enabled   INTEGER NOT NULL DEFAULT 0,
    config_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Every agent decision (audit trail)
CREATE TABLE IF NOT EXISTS agent_decisions (
    id              TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    timeframe       TEXT NOT NULL,
    analysis_id     TEXT,
    signal_side     TEXT NOT NULL,
    p_up            REAL,
    edge_atr        REAL,
    decision        TEXT NOT NULL,
    confidence      REAL,
    reasoning       TEXT,
    executed        INTEGER NOT NULL DEFAULT 0,
    execution_error TEXT,
    draft_id        TEXT,
    attribution_json TEXT,
    fundamental_json TEXT,
    technical_json TEXT,
    risk_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_agent_decisions_symbol_time
    ON agent_decisions (symbol, timeframe, created_at);

CREATE INDEX IF NOT EXISTS idx_agent_decisions_analysis
    ON agent_decisions (analysis_id);

-- Agent-managed positions
CREATE TABLE IF NOT EXISTS agent_positions (
    ticket          TEXT PRIMARY KEY,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    entry_price     REAL NOT NULL,
    volume          REAL NOT NULL,
    sl              REAL,
    tp              REAL,
    opened_at       TEXT NOT NULL,
    managed_by_agent INTEGER NOT NULL DEFAULT 1,
    trail_sl        REAL,
    scale_in_count  INTEGER DEFAULT 0,
    scale_out_count INTEGER DEFAULT 0,
    max_favourable_atr REAL,
    max_adverse_atr REAL,
    last_managed_at TEXT,
    closed_at       TEXT,
    close_reason    TEXT,
    realised_pnl    REAL,
    r_multiple      REAL
);

CREATE INDEX IF NOT EXISTS idx_agent_positions_symbol
    ON agent_positions (symbol);

CREATE INDEX IF NOT EXISTS idx_agent_positions_managed
    ON agent_positions (managed_by_agent);

-- Agent config overrides per symbol (optional)
CREATE TABLE IF NOT EXISTS agent_symbol_config (
    symbol      TEXT PRIMARY KEY,
    config_json TEXT NOT NULL,
    enabled     INTEGER NOT NULL DEFAULT 1
);