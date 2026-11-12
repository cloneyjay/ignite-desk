"""SQLite persistence. Single user, local file, WAL."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA = Path(__file__).with_name("schema.sql")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Store:
    """SQLite store with one connection per thread.

    The API runs sync handlers in a thread pool and the analysis job in its own
    thread, so a single shared connection would interleave transactions.
    """

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._local = threading.local()
        self._conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        self._migrate()
        self._conn.commit()

    @property
    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._path, timeout=5.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            self._local.conn = conn
        return conn

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    def _migrate(self) -> None:
        """Add columns introduced after a database file was first created."""
        wanted = {
            "drafts": {"margin": "REAL", "worst_case_usd": "REAL"},
            "orders": {"position_id": "TEXT", "comment": "TEXT", "error": "TEXT"},
        }
        for table, columns in wanted.items():
            existing = {row["name"] for row in self._conn.execute(f"PRAGMA table_info({table})")}
            for column, sql_type in columns.items():
                if column not in existing:
                    self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")
        # Indexes on migrated columns must be created after the ALTERs.
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_orders_position ON orders (position_id)"
        )

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
            self._conn.execute(
                """
                INSERT INTO drafts (
                    id, analysis_id, created_at, expires_at, state, side, lots,
                    reference_price, sl, tp, risk_usd, risk_pct, rr, margin,
                    worst_case_usd, blocked, block_reason, idempotency_key
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    result.draft_id,
                    analysis_id,
                    result.created_at,
                    (datetime.fromisoformat(result.created_at)
                     + timedelta(seconds=draft_ttl_s)).isoformat(),
                    "blocked" if draft.blocked else "draft",
                    draft.side,
                    draft.lots,
                    draft.reference_price,
                    draft.sl,
                    draft.tp,
                    draft.risk_usd,
                    draft.risk_pct,
                    draft.rr,
                    getattr(draft, "margin", None),
                    getattr(draft, "worst_case_usd", None),
                    int(draft.blocked),
                    draft.block_reason,
                    f"{analysis_id}:{draft.side}:{draft.lots}:{uuid_suffix()}",
                ),
            )

        self._conn.commit()
        return analysis_id

    def get_analysis(self, analysis_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM analyses WHERE id=?", (analysis_id,)
        ).fetchone()
        return dict(row) if row else None

    def latest_analysis(self, symbol: str, timeframe: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM analyses WHERE symbol=? AND timeframe=?"
            " ORDER BY last_bar_time DESC, created_at DESC LIMIT 1",
            (symbol, timeframe),
        ).fetchone()
        return dict(row) if row else None

    def find_analysis_for_bar(
        self, symbol: str, timeframe: str, last_bar_time: str
    ) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM analyses WHERE symbol=? AND timeframe=? AND last_bar_time=?"
            " ORDER BY created_at DESC LIMIT 1",
            (symbol, timeframe, last_bar_time),
        ).fetchone()
        return dict(row) if row else None

    def paths(self, analysis_id: str) -> list[list[float]]:
        rows = self._conn.execute(
            "SELECT path_json FROM forecast_paths WHERE analysis_id=? ORDER BY sample_idx",
            (analysis_id,),
        ).fetchall()
        return [json.loads(row["path_json"]) for row in rows]

    def draft_for_analysis(self, analysis_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM drafts WHERE analysis_id=? ORDER BY created_at DESC LIMIT 1",
            (analysis_id,),
        ).fetchone()
        return dict(row) if row else None

    # -------------------------------------------------------------------- drafts

    def get_draft(self, draft_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM drafts WHERE id=?", (draft_id,)).fetchone()
        return dict(row) if row else None

    def insert_draft(self, draft: dict[str, Any]) -> None:
        columns = ", ".join(draft)
        placeholders = ", ".join("?" for _ in draft)
        self._conn.execute(
            f"INSERT INTO drafts ({columns}) VALUES ({placeholders})",
            tuple(draft.values()),
        )
        self._conn.commit()

    def transition_draft(
        self, draft_id: str, from_state: str, to_state: str, **fields: Any
    ) -> bool:
        """Compare-and-set draft state. False means someone else got there first."""
        assignments = ["state=?"]
        values: list[Any] = [to_state]
        for key, value in fields.items():
            assignments.append(f"{key}=?")
            values.append(value)
        values.extend([draft_id, from_state])
        cursor = self._conn.execute(
            f"UPDATE drafts SET {', '.join(assignments)} WHERE id=? AND state=?",
            tuple(values),
        )
        self._conn.commit()
        return cursor.rowcount == 1

    def expire_stale_drafts(self, now_iso: str) -> int:
        cursor = self._conn.execute(
            "UPDATE drafts SET state='expired' WHERE state='draft' AND expires_at<=?",
            (now_iso,),
        )
        self._conn.commit()
        return cursor.rowcount

    # -------------------------------------------------------------------- orders

    def insert_order(self, order: dict[str, Any]) -> None:
        columns = ", ".join(order)
        placeholders = ", ".join("?" for _ in order)
        self._conn.execute(
            f"INSERT INTO orders ({columns}) VALUES ({placeholders})",
            tuple(order.values()),
        )
        self._conn.commit()

    def orders_for_draft(self, draft_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM orders WHERE draft_id=? ORDER BY created_at", (draft_id,)
        ).fetchall()
        return [dict(row) for row in rows]

    def recent_orders(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM orders ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]

    def order_risk(self, position_id: str) -> float | None:
        row = self._conn.execute(
            """
            SELECT d.risk_usd FROM orders o
            LEFT JOIN drafts d ON d.id = o.draft_id
            WHERE o.position_id = ? ORDER BY o.created_at DESC LIMIT 1
            """,
            (position_id,),
        ).fetchone()
        return float(row["risk_usd"]) if row and row["risk_usd"] is not None else None

    # ------------------------------------------------------------------- symbols

    def add_symbol(self, spec: dict[str, Any]) -> None:
        self._conn.execute(
            """
            INSERT INTO symbols (symbol, digits, point, contract_size, tick_value,
                                 volume_min, volume_max, volume_step, stops_level, added_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(symbol) DO UPDATE SET
                digits=excluded.digits, point=excluded.point,
                contract_size=excluded.contract_size, tick_value=excluded.tick_value,
                volume_min=excluded.volume_min, volume_max=excluded.volume_max,
                volume_step=excluded.volume_step, stops_level=excluded.stops_level
            """,
            (
                spec["symbol"], spec["digits"], spec["point"], spec["contract_size"],
                spec["tick_value"], spec["volume_min"], spec["volume_max"],
                spec["volume_step"], spec["stops_level"], utc_now(),
            ),
        )
        self._conn.commit()

    def remove_symbol(self, symbol: str) -> None:
        self._conn.execute("DELETE FROM symbols WHERE symbol=?", (symbol,))
        self._conn.commit()

    def list_symbols(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM symbols ORDER BY symbol").fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------- equity

    def snapshot_equity(
        self, balance: float, equity: float, margin: float, free: float, ts: str | None = None
    ) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO equity_snapshots (ts, balance, equity, margin, free_margin)"
            " VALUES (?,?,?,?,?)",
            (ts or utc_now(), balance, equity, margin, free),
        )
        self._conn.commit()

    def equity_series(self, since: str | None = None) -> list[dict[str, Any]]:
        if since:
            rows = self._conn.execute(
                "SELECT ts, balance, equity, margin, free_margin FROM equity_snapshots"
                " WHERE ts >= ? ORDER BY ts",
                (since,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT ts, balance, equity, margin, free_margin FROM equity_snapshots"
                " ORDER BY ts"
            ).fetchall()
        return [dict(row) for row in rows]

    # ----------------------------------------------------------------- settings

    def setting(self, key: str, default: str | None = None) -> str | None:
        row = self._conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO settings (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=?",
            (key, value, value),
        )
        self._conn.commit()

    def kill_switch(self) -> bool:
        return self.setting("kill_switch", "0") == "1"

    def set_kill_switch(self, enabled: bool) -> None:
        self.set_setting("kill_switch", "1" if enabled else "0")

    # -------------------------------------------------------------------- audit

    def audit(self, actor: str, action: str, payload: Any, result: str = "ok") -> None:
        self._conn.execute(
            "INSERT INTO audit_log (ts, actor, action, payload, result) VALUES (?,?,?,?,?)",
            (utc_now(), actor, action, json.dumps(payload, default=str)[:8000], result),
        )
        self._conn.commit()


def uuid_suffix() -> str:
    import uuid

    return uuid.uuid4().hex[:8]
