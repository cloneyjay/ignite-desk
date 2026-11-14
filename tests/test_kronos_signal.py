"""Tests for Kronos probabilistic signal analysis."""

from __future__ import annotations

import numpy as np

from backend.ignite.agent.kronos_signal import analyse_paths, signal_to_narrative


def test_long_signal_from_bullish_paths():
    """Strong bullish paths produce LONG signal."""
    np.random.seed(42)
    last_close = 100.0
    atr = 2.0
    # 25 samples, horizon 12, all ending above last_close with strong edge
    paths = np.random.normal(loc=108.0, scale=2.0, size=(25, 12))
    paths[:, 0] = last_close  # start at last_close

    signal = analyse_paths(paths, last_close, atr)

    assert signal.side == "long"
    assert signal.p_up >= 0.62
    assert signal.edge_atr >= 0.60
    assert signal.confidence > 0.5
    assert len(signal.reasons) > 0


def test_short_signal_from_bearish_paths():
    """Strong bearish paths produce SHORT signal."""
    np.random.seed(42)
    last_close = 100.0
    atr = 2.0
    paths = np.random.normal(loc=92.0, scale=2.0, size=(25, 12))
    paths[:, 0] = last_close

    signal = analyse_paths(paths, last_close, atr)

    assert signal.side == "short"
    assert signal.p_up <= 0.38
    assert signal.edge_atr <= -0.60


def test_no_trade_from_neutral_paths():
    """Neutral paths produce NO TRADE."""
    np.random.seed(42)
    last_close = 100.0
    atr = 2.0
    paths = np.random.normal(loc=100.0, scale=1.0, size=(25, 12))
    paths[:, 0] = last_close

    signal = analyse_paths(paths, last_close, atr)

    assert signal.side == "none"


def test_confidence_bands_computed():
    """Confidence bands p10/p50/p90 are within path range."""
    np.random.seed(7)
    last_close = 100.0
    atr = 2.0
    paths = np.random.normal(loc=105.0, scale=3.0, size=(30, 12))
    paths[:, 0] = last_close

    signal = analyse_paths(paths, last_close, atr)

    assert signal.p10_close <= signal.p50_close <= signal.p90_close
    assert signal.p10_close >= paths.min() - 1.0  # some tolerance
    assert signal.p90_close <= paths.max() + 1.0


def test_dispersion_penalty():
    """High dispersion reduces confidence even with directional edge."""
    np.random.seed(42)
    last_close = 100.0
    atr = 2.0

    # Low dispersion: tight paths
    tight = np.random.normal(loc=106.0, scale=1.0, size=(25, 12))
    tight[:, 0] = last_close
    tight_signal = analyse_paths(tight, last_close, atr)

    # High dispersion: wide paths
    wide = np.random.normal(loc=106.0, scale=5.0, size=(25, 12))
    wide[:, 0] = last_close
    wide_signal = analyse_paths(wide, last_close, atr)

    assert tight_signal.confidence > wide_signal.confidence


def test_narrative_output():
    """Narrative includes key fields."""
    np.random.seed(42)
    last_close = 100.0
    atr = 2.0
    paths = np.random.normal(loc=106.0, scale=1.5, size=(25, 12))
    paths[:, 0] = last_close

    signal = analyse_paths(paths, last_close, atr)
    narrative = signal_to_narrative(signal, "XAUUSD", "M15", atr)

    assert "Kronos" in narrative
    assert "XAUUSD" in narrative
    assert "M15" in narrative
    assert "p_up" in narrative
    assert "edge" in narrative
    assert "regime" in narrative
    assert "confidence" in narrative


def test_invalid_paths_raise():
    """Invalid path shapes raise ValueError."""
    last_close = 100.0
    atr = 2.0

    try:
        analyse_paths(np.array([[1.0]]), last_close, atr)
        assert False, "should have raised"
    except ValueError:
        pass

    try:
        analyse_paths(np.full((3, 4), np.nan), last_close, atr)
        assert False, "should have raised"
    except ValueError:
        pass

    try:
        analyse_paths(np.ones((3, 4)), 0.0, atr)
        assert False, "should have raised"
    except ValueError:
        pass
