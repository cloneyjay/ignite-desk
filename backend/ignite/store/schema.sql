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
    blocked         INTEGER NOT NULL DEFAULT 0,
    block_reason    TEXT,
    idempotency_key TEXT NOT NULL UNIQUE
);

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
    state           TEXT NOT NULL,
    broker_json     TEXT
);

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
