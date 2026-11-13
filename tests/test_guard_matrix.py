"""Every guard must reject and persist a reason when its input is unavailable."""

from __future__ import annotations

from backend.ignite.services.ledger import Ledger
from backend.ignite.store.db import Store


class FakeRt:
    def __init__(self, tmp_path, realised, equity=10000.0, floating=0.0, fail=False):
        self.store = Store(tmp_path / "guard.db")
        self._realised = realised
        self._equity = equity
        self._floating = floating
        self._fail = fail

    def realised_today(self):
        if self._fail:
            raise RuntimeError("broker down")
        return {"realised_usd": self._realised}

    def account(self):
        return {"equity": self._equity, "profit": self._floating}

    def positions(self):
        return []

    def config(self):
        from backend.ignite.agent.config import AgentConfig

        return AgentConfig(daily_loss_limit_pct=0.06)


def test_daily_loss_blocks_entries(tmp_path):
    pnl = Ledger(FakeRt(tmp_path, realised=-700.0)).daily()
    assert pnl.total_usd == -700.0
    assert pnl.blocked is True


def test_daily_loss_below_limit_allows(tmp_path):
    pnl = Ledger(FakeRt(tmp_path, realised=-200.0)).daily()
    assert pnl.blocked is False


def test_floating_loss_counts_towards_the_limit(tmp_path):
    pnl = Ledger(FakeRt(tmp_path, realised=-200.0, floating=-450.0)).daily()
    assert pnl.total_usd == -650.0
    assert pnl.blocked is True


def test_missing_pnl_source_fails_closed(tmp_path):
    rt = FakeRt(tmp_path, realised=0.0, fail=True)
    pnl = Ledger(rt).daily()
    assert pnl.available is False
    assert pnl.blocked is True
    assert rt.store.agent_events()[-1]["kind"] == "guard.daily_loss_unavailable"


def test_technical_context_reads_features_json(tmp_path):
    from backend.ignite.agent.synthesis import build_technical_context

    store = Store(tmp_path / "t.db")
    store._conn.execute(
        """INSERT INTO analyses (id, created_at, symbol, timeframe, last_bar_time,
        lookback, horizon, samples, model_id, infer_s, atr, p_up, edge, edge_atr,
        dispersion, signal, signal_version, risk_version, features_json, reasons_json)
        VALUES ('a','2026-01-01T00:00:00+00:00','XAUUSD','M15','t',1,1,1,'m',0.1,
        2.5,0.6,1.0,0.5,0.1,'LONG','v1','v1',
        '{"trend":"up","atr":2.5,"last_close":3930.0}','[]')"""
    )
    store._conn.commit()

    class Rt:
        def __init__(self):
            self.store = store

    ctx = build_technical_context(Rt(), "XAUUSD", "M15")
    assert ctx.trend == "up"
    assert ctx.atr == 2.5
    assert ctx.volatility_regime == "compression"
