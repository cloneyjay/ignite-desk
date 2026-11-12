import pytest

from backend.ignite.analysis.risk import RiskConfig, SymbolSpec, plan

XAU = SymbolSpec(
    symbol="XAUUSD",
    digits=2,
    point=0.01,
    contract_size=100.0,
    tick_value=0.1,
    volume_min=0.01,
    volume_max=100.0,
    volume_step=0.01,
    stops_level=0,
)


def test_sizing_matches_the_broker_arithmetic():
    draft = plan("long", 4000.0, atr=10.0, equity=3000.0, spec=XAU, spread_points=13)
    assert not draft.blocked
    assert draft.lots == pytest.approx(0.01)
    assert draft.sl == pytest.approx(3985.0)
    assert draft.tp == pytest.approx(4030.0)
    assert draft.risk_usd == pytest.approx(15.0)
    assert draft.rr == pytest.approx(2.0)


def test_bigger_account_scales_the_size():
    draft = plan("long", 4000.0, atr=10.0, equity=30000.0, spec=XAU, spread_points=13)
    assert draft.lots == pytest.approx(0.10)
    assert draft.risk_usd == pytest.approx(150.0)


def test_size_below_minimum_is_blocked_not_rounded_up():
    draft = plan("long", 4000.0, atr=10.0, equity=100.0, spec=XAU, spread_points=13)
    assert draft.blocked
    assert "below minimum" in draft.block_reason


def test_wide_spread_blocks():
    draft = plan("long", 4000.0, atr=10.0, equity=3000.0, spec=XAU, spread_points=50)
    assert draft.blocked
    assert "spread" in draft.block_reason


def test_risk_above_cap_is_refused():
    draft = plan(
        "long", 4000.0, atr=10.0, equity=3000.0, spec=XAU, spread_points=13,
        config=RiskConfig(risk_pct=0.02),
    )
    assert draft.blocked
    assert "cap" in draft.block_reason


def test_short_levels_are_ordered_correctly():
    draft = plan("short", 4000.0, atr=10.0, equity=3000.0, spec=XAU, spread_points=13)
    assert not draft.blocked
    assert draft.tp < draft.reference_price < draft.sl
    assert draft.sl == pytest.approx(4015.0)
    assert draft.tp == pytest.approx(3970.0)


def test_zero_atr_is_refused():
    draft = plan("long", 4000.0, atr=0.0, equity=3000.0, spec=XAU, spread_points=13)
    assert draft.blocked
