CREATE TABLE IF NOT EXISTS symbols (
    symbol          TEXT PRIMARY KEY,
    digits          INTEGER NOT NULL,
    point           REAL NOT NULL,
    contract_size   REAL NOT NULL,
    tick_value      REAL NOT NULL DEFAULT 0,
    volume_min      REAL NOT NULL,
    volume_max      REAL NOT NULL,
    volume_step     REAL NOT NULL,
    stops_level     INTEGER NOT NULL DEFAULT 0,
    added_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analyses (
    id              TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    timeframe       TEXT NOT NULL,
    last_bar_time   TEXT NOT NULL,
    lookback        INTEGER NOT NULL,
    horizon         INTEGER NOT NULL,
    samples         INTEGER NOT NULL,
    model_id        TEXT NOT NULL,
    infer_s         REAL,
    atr             REAL,
    p_up            REAL,
    edge            REAL,
    edge_atr        REAL,
    dispersion      REAL,
    signal          TEXT NOT NULL,
    signal_version  TEXT NOT NULL,
    risk_version    TEXT NOT NULL,
    features_json   TEXT NOT NULL,
    reasons_json    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_analyses_lookup
    ON analyses (symbol, timeframe, last_bar_time);

CREATE TABLE IF NOT EXISTS forecast_paths (
    analysis_id     TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    sample_idx      INTEGER NOT NULL,
    path_json       TEXT NOT NULL,
    PRIMARY KEY (analysis_id, sample_idx)
);

CREATE TABLE IF NOT EXISTS drafts (
    id              TEXT PRIMARY KEY,
    analysis_id     TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    created_at      TEXT NOT NULL,
    expires_at      TEXT NOT NULL,
    state           TEXT NOT NULL,
    side            TEXT NOT NULL,
    lots            REAL NOT NULL,
    reference_price REAL,
    sl              REAL,
    tp              REAL,
    risk_usd        REAL,
    risk_pct        REAL,
    rr              REAL,
    margin          REAL,
    worst_case_usd  REAL,
    blocked         INTEGER NOT NULL DEFAULT 0,
    block_reason    TEXT,
    idempotency_key TEXT NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_drafts_analysis ON drafts (analysis_id);

CREATE TABLE IF NOT EXISTS orders (
    id              TEXT PRIMARY KEY,
    draft_id        TEXT REFERENCES drafts(id),
    created_at      TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    lots            REAL NOT NULL,
    requested_price REAL,
    filled_price    REAL,
    sl              REAL,
    tp              REAL,
    ticket          TEXT,
    position_id     TEXT,
    state           TEXT NOT NULL,
    comment         TEXT,
    error           TEXT,
    broker_json     TEXT
);

CREATE INDEX IF NOT EXISTS idx_orders_draft ON orders (draft_id);

CREATE TABLE IF NOT EXISTS equity_snapshots (
    ts          TEXT PRIMARY KEY,
    balance     REAL NOT NULL,
    equity      REAL NOT NULL,
    margin      REAL,
    free_margin REAL
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL,
    payload     TEXT,
    result      TEXT
);

-- ---------------------------------------------------------------------------
-- Agent knowledge: reviewed markdown cards + a full-text index, and one row
-- per LLM run so every sentence shown in the UI can be reconstructed.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS knowledge_cards (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    scope           TEXT NOT NULL,
    layer           TEXT NOT NULL,
    version         INTEGER NOT NULL,
    status          TEXT NOT NULL,
    reviewed_by     TEXT,
    priority        INTEGER NOT NULL DEFAULT 50,
    tags_json       TEXT NOT NULL,
    facts_json      TEXT NOT NULL,
    applies_to_json TEXT NOT NULL,
    max_words       INTEGER NOT NULL DEFAULT 180,
    body            TEXT NOT NULL,
    source_path     TEXT NOT NULL,
    checksum        TEXT NOT NULL,
    loaded_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_knowledge_scope
    ON knowledge_cards (scope, status, priority);

CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_cards_fts
    USING fts5(id UNINDEXED, title, tags, body);

CREATE TABLE IF NOT EXISTS agent_runs (
    id              TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL,
    skill           TEXT NOT NULL,
    subject         TEXT,
    provider        TEXT NOT NULL,
    model           TEXT,
    status          TEXT NOT NULL,
    fallback        INTEGER NOT NULL DEFAULT 0,
    latency_ms      INTEGER,
    prompt_tokens   INTEGER,
    completion_tokens INTEGER,
    cards_json      TEXT NOT NULL,
    checks_json     TEXT NOT NULL,
    input_json      TEXT NOT NULL,
    output_json     TEXT,
    narrative       TEXT,
    error           TEXT
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_subject
    ON agent_runs (skill, subject, created_at);
