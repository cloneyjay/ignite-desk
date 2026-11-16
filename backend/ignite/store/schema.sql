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

CREATE TABLE IF NOT EXISTS agent_sessions (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS agent_messages (
    id             TEXT PRIMARY KEY,
    session_id     TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    role           TEXT NOT NULL,
    content        TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'ok',
    tool_name      TEXT,
    tool_args_json TEXT,
    tool_result_json TEXT,
    latency_ms     INTEGER,
    links_json     TEXT,
    FOREIGN KEY(session_id) REFERENCES agent_sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_agent_messages_session_time
    ON agent_messages (session_id, created_at);

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

-- ---------------------------------------------------------------------------
-- Agent autonomous trading: configuration, decisions, positions, symbol config
-- ---------------------------------------------------------------------------

-- Agent configuration (single row, key = 'global')
CREATE TABLE IF NOT EXISTS agent_config (
    key       TEXT PRIMARY KEY,
    enabled   INTEGER NOT NULL DEFAULT 0,
    config_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version   INTEGER NOT NULL DEFAULT 1
);

-- Append-only agent audit trail. Every tool call, guard, order and lifecycle
-- transition writes one row. The UI projects tool activity from this table.
CREATE TABLE IF NOT EXISTS agent_events (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    id           TEXT NOT NULL UNIQUE,
    created_at   TEXT NOT NULL,
    kind         TEXT NOT NULL,
    severity     TEXT NOT NULL DEFAULT 'info',
    symbol       TEXT,
    decision_id  TEXT,
    payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_events_decision
    ON agent_events (decision_id, seq);

CREATE INDEX IF NOT EXISTS idx_agent_events_created
    ON agent_events (created_at);

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
    r_multiple      REAL,
    status          TEXT NOT NULL DEFAULT 'open',
    decision_id     TEXT,
    entry_deal      TEXT,
    initial_risk_usd REAL,
    initial_sl      REAL,
    mfe             REAL,
    mae             REAL,
    last_synced_at  TEXT,
    broker_snapshot_json TEXT
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

-- Scratchpad: TTL-based key-value store for agent working memory
CREATE TABLE IF NOT EXISTS scratchpad (
    key         TEXT PRIMARY KEY,
    value_json  TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    expires_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_scratchpad_expires
    ON scratchpad (expires_at);

-- Episodic memory: append-only episodes (trades, analyses, decisions)
CREATE TABLE IF NOT EXISTS episodic_memory (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    type        TEXT NOT NULL,           -- trade, analysis, decision, reflection
    symbol      TEXT,
    timeframe   TEXT,
    payload_json TEXT NOT NULL,
    outcome     TEXT,                    -- profit, loss, neutral
    tags_json   TEXT,                    -- JSON array of tags
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_episodic_symbol
    ON episodic_memory (symbol);

CREATE INDEX IF NOT EXISTS idx_episodic_type
    ON episodic_memory (type);

CREATE INDEX IF NOT EXISTS idx_episodic_created
    ON episodic_memory (created_at);

-- Semantic memory: pattern/knowledge store with tags
CREATE TABLE IF NOT EXISTS semantic_memory (
    key         TEXT PRIMARY KEY,
    value_json  TEXT NOT NULL,
    tags_json   TEXT,                    -- JSON array of tags
    confidence  REAL DEFAULT 1.0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_semantic_tags
    ON semantic_memory (tags_json);

-- Procedural memory: condition-action rules with confidence
CREATE TABLE IF NOT EXISTS procedural_memory (
    trigger     TEXT PRIMARY KEY,
    action      TEXT NOT NULL,
    condition_json TEXT NOT NULL,
    confidence  REAL DEFAULT 1.0,
    use_count   INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- Agent auto-memory: capped index with two-step save
CREATE TABLE IF NOT EXISTS agent_memory (
    id TEXT PRIMARY KEY,
    key TEXT NOT NULL,
    content_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    access_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_agent_memory_key ON agent_memory (key);
CREATE INDEX IF NOT EXISTS idx_agent_memory_access ON agent_memory (access_count DESC, created_at DESC);

-- ---------------------------------------------------------------------------
-- Strategy development: MQL5 Expert Advisors and backtest results
-- ---------------------------------------------------------------------------

-- Strategy definitions (one row per strategy, latest version)
CREATE TABLE IF NOT EXISTS strategies (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT,
    symbol          TEXT NOT NULL,
    timeframe       TEXT NOT NULL,
    mql5_code       TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'draft',  -- draft, compiled, backtested, shadow, demo, live, archived
    version         INTEGER NOT NULL DEFAULT 1,
    p_up            REAL,
    edge_atr        REAL,
    total_trades    INTEGER,
    winning_trades  INTEGER,
    losing_trades   INTEGER,
    win_rate        REAL,
    profit_factor   REAL,
    max_drawdown    REAL,
    sharpe_ratio    REAL,
    initial_balance REAL,
    final_balance   REAL,
    parameters_json TEXT,          -- input parameters for the EA
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    backtest_id     TEXT           -- reference to latest backtest
);

CREATE INDEX IF NOT EXISTS idx_strategies_symbol ON strategies (symbol, timeframe);
CREATE INDEX IF NOT EXISTS idx_strategies_status ON strategies (status);

-- Strategy versions (immutable history of code changes)
CREATE TABLE IF NOT EXISTS strategy_versions (
    id              TEXT PRIMARY KEY,
    strategy_id     TEXT NOT NULL REFERENCES strategies(id) ON DELETE CASCADE,
    version         INTEGER NOT NULL,
    mql5_code       TEXT NOT NULL,
    change_note     TEXT,
    compiled        INTEGER NOT NULL DEFAULT 0,
    compile_errors  TEXT,
    compiled_at     TEXT,
    created_at      TEXT NOT NULL,
    UNIQUE(strategy_id, version)
);

CREATE INDEX IF NOT EXISTS idx_strategy_versions_strategy ON strategy_versions (strategy_id, version);

-- Backtest results from MT5 Strategy Tester
CREATE TABLE IF NOT EXISTS strategy_backtests (
    id              TEXT PRIMARY KEY,
    strategy_id     TEXT NOT NULL REFERENCES strategies(id) ON DELETE CASCADE,
    version         INTEGER NOT NULL,
    start_date      TEXT NOT NULL,
    end_date        TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    timeframe       TEXT NOT NULL,
    initial_balance REAL NOT NULL,
    final_balance   REAL,
    gross_profit    REAL,
    gross_loss      REAL,
    net_profit      REAL,
    profit_factor   REAL,
    total_trades    INTEGER,
    winning_trades  INTEGER,
    losing_trades   INTEGER,
    win_rate        REAL,
    max_drawdown    REAL,
    max_drawdown_pct REAL,
    sharpe_ratio    REAL,
    recovery_factor REAL,
    expectancy      REAL,
    equity_curve_json TEXT,        -- array of {ts, balance, equity}
    trades_json     TEXT,          -- array of trade objects
    parameters_json TEXT,          -- input parameters used
    tester_report_json TEXT,       -- raw MT5 tester report
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_strategy_backtests_strategy ON strategy_backtests (strategy_id, created_at);
