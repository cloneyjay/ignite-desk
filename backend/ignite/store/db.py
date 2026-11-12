"""SQLite persistence. Single user, local file, WAL."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA = Path(__file__).with_name("schema.sql")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------ analysis

    def save_analysis(self, result: Any, draft_ttl_s: int = 90) -> str:
        analysis_id = result.analysis_id
        features = result.features
        signal = result.signal
        draft = result.draft

        self._conn.execute(
            """
            INSERT INTO analyses (
                id, created_at, symbol, timeframe, last_bar_time, lookback, horizon,
                samples, model_id, infer_s, atr, p_up, edge, edge_atr, dispersion,
                signal, signal_version, risk_version, features_json, reasons_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                analysis_id,
                result.created_at,
                result.symbol,
                result.timeframe,
                str(result.last_bar_time),
                result.lookback,
                result.horizon,
                result.samples,
                result.model_id,
                result.infer_s,
                features.atr,
                signal.p_up,
                signal.edge,
                signal.edge_atr,
                signal.dispersion,
                signal.side,
                signal.version,
                result.risk_version,
                json.dumps(features.__dict__, default=str),
                json.dumps(list(signal.reasons)),
            ),
        )

        self._conn.executemany(
            "INSERT INTO forecast_paths (analysis_id, sample_idx, path_json) VALUES (?,?,?)",
            [
                (analysis_id, idx, json.dumps([round(float(v), 6) for v in path]))
                for idx, path in enumerate(result.paths)
            ],
        )

        if draft is not None:
            draft_id = result.draft_id
            created = datetime.fromisoformat(result.created_at)
            expires = created + timedelta(seconds=draft_ttl_s)
            self._conn.execute(
                """
                INSERT INTO drafts (
                    id, analysis_id, created_at, expires_at, state, side, lots,
                    reference_price, sl, tp, risk_usd, risk_pct, rr, blocked,
                    block_reason, idempotency_key
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    draft_id,
                    analysis_id,
                    result.created_at,
                    expires.isoformat(),
                    "blocked" if draft.blocked else "draft",
                    draft.side,
                    draft.lots,
                    draft.reference_price,
                    draft.sl,
                    draft.tp,
                    draft.risk_usd,
                    draft.risk_pct,
                    draft.rr,
                    int(draft.blocked),
                    draft.block_reason,
                    f"{analysis_id}:{draft.side}:{draft.lots}",
                ),
            )

        self._conn.commit()
        return analysis_id

    def latest_analysis(self, symbol: str, timeframe: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM analyses WHERE symbol=? AND timeframe=? ORDER BY created_at DESC LIMIT 1",
            (symbol, timeframe),
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def snapshot_equity(self, balance: float, equity: float, margin: float, free: float) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO equity_snapshots (ts, balance, equity, margin, free_margin)"
            " VALUES (?,?,?,?,?)",
            (utc_now(), balance, equity, margin, free),
        )
        self._conn.commit()

    def setting(self, key: str, default: str | None = None) -> str | None:
        row = self._conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO settings (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=?",
            (key, value, value),
        )
        self._conn.commit()
