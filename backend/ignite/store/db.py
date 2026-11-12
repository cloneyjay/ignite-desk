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

    # ---------------------------------------------------------------- knowledge

    def sync_knowledge_cards(self, cards: list[dict[str, Any]]) -> None:
        """Replace the card catalogue with a freshly parsed directory.

        Full replace, not upsert: a card that was deleted from disk must vanish
        from prompts, and the loader is the only writer.
        """
        now = utc_now()
        with self._conn:
            self._conn.execute("DELETE FROM knowledge_cards")
            self._conn.execute("DELETE FROM knowledge_cards_fts")
            for card in cards:
                self._conn.execute(
                    """
                    INSERT INTO knowledge_cards (
                        id, title, scope, layer, version, status, reviewed_by,
                        priority, tags_json, facts_json, applies_to_json,
                        max_words, body, source_path, checksum, loaded_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        card["id"],
                        card["title"],
                        card["scope"],
                        card["layer"],
                        int(card["version"]),
                        card["status"],
                        card.get("reviewed_by"),
                        int(card["priority"]),
                        json.dumps(list(card["tags"])),
                        json.dumps(list(card["facts"])),
                        json.dumps(list(card["applies_to"])),
                        int(card["max_words"]),
                        card["body"],
                        card["source_path"],
                        card["checksum"],
                        now,
                    ),
                )
                self._conn.execute(
                    "INSERT INTO knowledge_cards_fts (id, title, tags, body)"
                    " VALUES (?,?,?,?)",
                    (
                        card["id"],
                        card["title"],
                        " ".join(card["tags"]),
                        card["body"],
                    ),
                )

    @staticmethod
    def _knowledge_row(row: sqlite3.Row) -> dict[str, Any]:
        card = dict(row)
        card["tags"] = json.loads(card.pop("tags_json"))
        card["facts"] = json.loads(card.pop("facts_json"))
        card["applies_to"] = json.loads(card.pop("applies_to_json"))
        return card

    def knowledge_cards(
        self,
        *,
        scope: str | None = None,
        status: str | None = None,
        skill: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[Any] = []
        if scope:
            clauses.append("scope=?")
            values.append(scope)
        if status:
            clauses.append("status=?")
            values.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM knowledge_cards {where}"
            " ORDER BY priority DESC, id ASC",
            tuple(values),
        ).fetchall()
        cards = [self._knowledge_row(row) for row in rows]
        if skill:
            cards = [card for card in cards if skill in card["applies_to"]]
        return cards

    def knowledge_card(self, card_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM knowledge_cards WHERE id=?", (card_id,)
        ).fetchone()
        return self._knowledge_row(row) if row else None

    def search_knowledge(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        import re

        tokens = re.findall(r"[A-Za-z0-9_]+", query)
        if not tokens:
            return []
        match = " ".join(f'"{token}"' for token in tokens)
        try:
            rows = self._conn.execute(
                """
                SELECT c.* FROM knowledge_cards_fts f
                JOIN knowledge_cards c ON c.id = f.id
                WHERE knowledge_cards_fts MATCH ?
                ORDER BY rank LIMIT ?
                """,
                (match, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [self._knowledge_row(row) for row in rows]

    # ---------------------------------------------------------------- agent runs

    def insert_agent_run(self, run: dict[str, Any]) -> None:
        self._conn.execute(
            """
            INSERT INTO agent_runs (
                id, created_at, skill, subject, provider, model, status, fallback,
                latency_ms, prompt_tokens, completion_tokens, cards_json,
                checks_json, input_json, output_json, narrative, error
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run["id"],
                run["created_at"],
                run["skill"],
                run.get("subject"),
                run["provider"],
                run.get("model"),
                run["status"],
                int(bool(run.get("fallback"))),
                run.get("latency_ms"),
                run.get("prompt_tokens"),
                run.get("completion_tokens"),
                json.dumps(run.get("cards", []), default=str),
                json.dumps(run.get("checks", {}), default=str),
                json.dumps(run.get("input", {}), default=str),
                json.dumps(run.get("output", {}), default=str),
                run.get("narrative"),
                run.get("error"),
            ),
        )
        self._conn.commit()

    @staticmethod
    def _agent_run_row(row: sqlite3.Row) -> dict[str, Any]:
        run = dict(row)
        for key in ("cards_json", "checks_json", "input_json", "output_json"):
            raw = run.pop(key, None)
            run[key.replace("_json", "")] = json.loads(raw) if raw else None
        run["fallback"] = bool(run["fallback"])
        return run

    def agent_run(self, run_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM agent_runs WHERE id=?", (run_id,)
        ).fetchone()
        return self._agent_run_row(row) if row else None

    def latest_agent_run(
        self, skill: str, subject: str | None, statuses: tuple[str, ...] = ("ok", "fallback")
    ) -> dict[str, Any] | None:
        placeholders = ",".join("?" for _ in statuses)
        rows = self._conn.execute(
            f"SELECT * FROM agent_runs WHERE skill=? AND subject=? AND status IN ({placeholders})"
            " ORDER BY created_at DESC LIMIT 1",
            (skill, subject, *statuses),
        ).fetchall()
        return self._agent_run_row(rows[0]) if rows else None

    def recent_agent_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM agent_runs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._agent_run_row(row) for row in rows]

    # ---------------------------------------------------------------- agent config

    def agent_config(self) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM agent_config WHERE key='global'").fetchone()
        return dict(row) if row else None

    def set_agent_config(self, enabled: bool, config_json: str) -> None:
        self._conn.execute(
            """
            INSERT INTO agent_config (key, enabled, config_json, updated_at)
            VALUES ('global', ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                enabled=excluded.enabled,
                config_json=excluded.config_json,
                updated_at=excluded.updated_at
            """,
            (int(enabled), config_json, utc_now()),
        )
        self._conn.commit()

    # ---------------------------------------------------------------- agent decisions

    def insert_agent_decision(self, decision: dict[str, Any]) -> None:
        self._conn.execute(
            """
            INSERT INTO agent_decisions (
                id, created_at, symbol, timeframe, analysis_id, signal_side,
                p_up, edge_atr, decision, confidence, reasoning, executed,
                execution_error, draft_id, attribution_json, fundamental_json,
                technical_json, risk_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                decision["id"],
                decision["created_at"],
                decision["symbol"],
                decision["timeframe"],
                decision.get("analysis_id"),
                decision["signal_side"],
                decision.get("p_up"),
                decision.get("edge_atr"),
                decision["decision"],
                decision.get("confidence"),
                decision.get("reasoning"),
                int(decision.get("executed", False)),
                decision.get("execution_error"),
                decision.get("draft_id"),
                decision.get("attribution_json"),
                decision.get("fundamental_json"),
                decision.get("technical_json"),
                decision.get("risk_json"),
            ),
        )
        self._conn.commit()

    @staticmethod
    def _agent_decision_row(row: sqlite3.Row) -> dict[str, Any]:
        decision = dict(row)
        for key in ("attribution_json", "fundamental_json", "technical_json", "risk_json"):
            raw = decision.pop(key, None)
            decision[key.replace("_json", "")] = json.loads(raw) if raw else None
        decision["executed"] = bool(decision["executed"])
        return decision

    def agent_decisions(self, limit: int = 100, symbol: str | None = None) -> list[dict[str, Any]]:
        if symbol:
            rows = self._conn.execute(
                "SELECT * FROM agent_decisions WHERE symbol=? ORDER BY created_at DESC LIMIT ?",
                (symbol, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM agent_decisions ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._agent_decision_row(row) for row in rows]

    def latest_agent_decision(self, symbol: str, timeframe: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM agent_decisions WHERE symbol=? AND timeframe=? ORDER BY created_at DESC LIMIT 1",
            (symbol, timeframe),
        ).fetchone()
        return self._agent_decision_row(row) if row else None

    # ---------------------------------------------------------------- agent positions

    def upsert_agent_position(self, pos: dict[str, Any]) -> None:
        self._conn.execute(
            """
            INSERT INTO agent_positions (
                ticket, symbol, side, entry_price, volume, sl, tp, opened_at,
                managed_by_agent, trail_sl, scale_in_count, scale_out_count,
                max_favourable_atr, max_adverse_atr, last_managed_at,
                closed_at, close_reason, realised_pnl, r_multiple
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(ticket) DO UPDATE SET
                symbol=excluded.symbol,
                side=excluded.side,
                entry_price=excluded.entry_price,
                volume=excluded.volume,
                sl=excluded.sl,
                tp=excluded.tp,
                managed_by_agent=excluded.managed_by_agent,
                trail_sl=excluded.trail_sl,
                scale_in_count=excluded.scale_in_count,
                scale_out_count=excluded.scale_out_count,
                max_favourable_atr=excluded.max_favourable_atr,
                max_adverse_atr=excluded.max_adverse_atr,
                last_managed_at=excluded.last_managed_at,
                closed_at=excluded.closed_at,
                close_reason=excluded.close_reason,
                realised_pnl=excluded.realised_pnl,
                r_multiple=excluded.r_multiple
            """,
            (
                pos["ticket"],
                pos["symbol"],
                pos["side"],
                pos["entry_price"],
                pos["volume"],
                pos.get("sl"),
                pos.get("tp"),
                pos["opened_at"],
                int(pos.get("managed_by_agent", True)),
                pos.get("trail_sl"),
                pos.get("scale_in_count", 0),
                pos.get("scale_out_count", 0),
                pos.get("max_favourable_atr"),
                pos.get("max_adverse_atr"),
                pos.get("last_managed_at"),
                pos.get("closed_at"),
                pos.get("close_reason"),
                pos.get("realised_pnl"),
                pos.get("r_multiple"),
            ),
        )
        self._conn.commit()

    def agent_positions(self, managed_only: bool = True) -> list[dict[str, Any]]:
        if managed_only:
            rows = self._conn.execute(
                "SELECT * FROM agent_positions WHERE managed_by_agent=1 AND closed_at IS NULL"
            ).fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM agent_positions").fetchall()
        return [dict(row) for row in rows]

    def agent_position(self, ticket: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM agent_positions WHERE ticket=?", (ticket,)).fetchone()
        return dict(row) if row else None

    def close_agent_position(self, ticket: str, close_reason: str, realised_pnl: float, r_multiple: float) -> None:
        self._conn.execute(
            """
            UPDATE agent_positions SET
                closed_at=?, close_reason=?, realised_pnl=?, r_multiple=?
            WHERE ticket=?
            """,
            (utc_now(), close_reason, realised_pnl, r_multiple, ticket),
        )
        self._conn.commit()

    # ---------------------------------------------------------------- agent symbol config

    def agent_symbol_config(self, symbol: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM agent_symbol_config WHERE symbol=?", (symbol,)
        ).fetchone()
        return dict(row) if row else None

    def set_agent_symbol_config(self, symbol: str, config_json: str, enabled: bool = True) -> None:
        self._conn.execute(
            """
            INSERT INTO agent_symbol_config (symbol, config_json, enabled)
            VALUES (?,?,?)
            ON CONFLICT(symbol) DO UPDATE SET
                config_json=excluded.config_json,
                enabled=excluded.enabled
            """,
            (symbol, config_json, int(enabled)),
        )
        self._conn.commit()


def uuid_suffix() -> str:
    import uuid

    return uuid.uuid4().hex[:8]
