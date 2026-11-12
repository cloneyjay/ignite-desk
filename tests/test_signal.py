import numpy as np
import pytest

from backend.ignite.analysis.signal import SignalError, evaluate


def paths_with(up: int, down: int, hi: float = 101.0, lo: float = 99.0) -> np.ndarray:
    return np.array([[hi] if i < up else [lo] for i in range(up + down)], dtype=float)


def test_long_when_direction_and_edge_agree():
    signal = evaluate(paths_with(8, 2, 101.0, 99.0), last_close=100.0, atr=1.0)
    assert signal.side == "long"
    assert signal.p_up == pytest.approx(0.8)
    assert signal.edge_atr == pytest.approx(0.6)


def test_no_trade_when_direction_is_right_but_edge_is_thin():
    signal = evaluate(paths_with(9, 1, 100.2, 99.9), last_close=100.0, atr=1.0)
    assert signal.side == "none"
    assert any("edge" in r for r in signal.reasons)


def test_no_trade_when_probability_is_neutral():
    signal = evaluate(paths_with(6, 4, 101.0, 99.0), last_close=100.0, atr=1.0)
    assert signal.side == "none"
    assert any("neutral" in r for r in signal.reasons)


def test_short_is_the_mirror():
    signal = evaluate(paths_with(2, 8, 101.0, 99.0), last_close=100.0, atr=1.0)
    assert signal.side == "short"
    assert signal.edge_atr < 0


def test_boundary_at_exactly_sixty_two_percent():
    paths = np.array([[101.0]] * 62 + [[99.0]] * 38)
    signal = evaluate(paths, last_close=100.0, atr=1.0)
    assert signal.side in ("long", "none")  # documented boundary; must not crash


def test_rejects_bad_shapes_and_non_finite():
    with pytest.raises(SignalError):
        evaluate(np.array([1.0, 2.0, 3.0]), last_close=100.0, atr=1.0)
    with pytest.raises(SignalError):
        evaluate(np.array([[np.nan], [1.0]]), last_close=100.0, atr=1.0)
    with pytest.raises(SignalError):
        evaluate(np.array([[1.0]]), last_close=100.0, atr=0.0)
