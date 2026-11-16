from types import SimpleNamespace

from backend.ignite.agent.decision import Decision, Entry, Links, Risk
from backend.ignite.agent.engine import AgentEngine, loss_streak_result


def _decision(action: str, draft_id: str | None) -> Decision:
    return Decision(
        symbol="XAUUSD",
        timeframe="M15",
        action=action,  # type: ignore[arg-type]
        conviction=0.6,
        thesis="t",
        evidence=[],
        failed_conditions=[],
        entry=Entry(type="market", price=0.0),
        risk=Risk(lots=0.01, sl=1.0, tp=2.0),
        expected_rr=2.0,
        invalidate_if=[],
        links=Links(analysis_id="a1", draft_id=draft_id, decision_id="d1"),
    )


def _engine(draft: dict | None) -> AgentEngine:
    rt = SimpleNamespace(store=SimpleNamespace(get_draft=lambda _id: draft))
    return AgentEngine(rt, None)  # type: ignore[arg-type]


def test_loss_streak_blocks_after_limit():
    trades = [
        {"close_time": "2026-11-16T10:00", "net": -5.0},
        {"close_time": "2026-11-16T09:00", "net": -1.0},
        {"close_time": "2026-11-16T08:00", "net": -2.0},
        {"close_time": "2026-11-16T07:00", "net": 9.0},
    ]
    assert not loss_streak_result(trades, 3).ok
    assert loss_streak_result(trades, 4).ok


def test_loss_streak_resets_on_win():
    trades = [
        {"close_time": "2026-11-16T10:00", "net": 3.0},
        {"close_time": "2026-11-16T09:00", "net": -1.0},
        {"close_time": "2026-11-16T08:00", "net": -2.0},
    ]
    assert loss_streak_result(trades, 2).ok


def test_entry_requires_draft():
    assert "no draft" in _engine(None)._validate_entry(_decision("LONG", None))


def test_entry_side_must_match_draft():
    eng = _engine({"side": "sell"})
    err = eng._validate_entry(_decision("LONG", "x"))
    assert err and "mismatch" in err


def test_entry_matching_draft_ok():
    draft = {"side": "buy", "lots": 0.01, "sl": 1.0, "tp": 2.0}
    assert _engine(draft)._validate_entry(_decision("LONG", "x")) is None
    sell_draft = {"side": "sell", "lots": 0.01, "sl": 1.0, "tp": 2.0}
    assert _engine(sell_draft)._validate_entry(_decision("SHORT", "x")) is None


def test_entry_lots_must_match_draft():
    draft = {"side": "buy", "lots": 0.5, "sl": 1.0, "tp": 2.0}
    err = _engine(draft)._validate_entry(_decision("LONG", "x"))
    assert err and "lots" in err and "mismatch" in err


def test_entry_sl_must_match_draft():
    draft = {"side": "buy", "lots": 0.01, "sl": 9.0, "tp": 2.0}
    err = _engine(draft)._validate_entry(_decision("LONG", "x"))
    assert err and "sl" in err and "mismatch" in err


def test_entry_tp_must_match_draft():
    draft = {"side": "buy", "lots": 0.01, "sl": 1.0, "tp": 9.0}
    err = _engine(draft)._validate_entry(_decision("LONG", "x"))
    assert err and "tp" in err and "mismatch" in err


def test_entry_missing_draft_risk_fails_closed():
    """A draft without risk numbers is a mismatch, never a pass (fail closed)."""
    err = _engine({"side": "buy"})._validate_entry(_decision("LONG", "x"))
    assert err and "mismatch" in err
