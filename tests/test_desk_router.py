"""Tests for the DeskRouter: chat intent routing to trading capabilities."""

from __future__ import annotations

from backend.ignite.agent.desk_router import DeskRouter, DeskRoute


def test_desk_router_exists():
    assert DeskRouter is not None
    assert DeskRoute is not None


def test_classify_identity(rt):
    router = DeskRouter(rt)
    route = router._classify("who are you?")
    assert route.intent == "identity"


def test_classify_decline_non_trading(rt):
    router = DeskRouter(rt)
    route = router._classify("write me a python script to scrape a website")
    assert route.intent == "decline"


def test_classify_analyze(rt):
    router = DeskRouter(rt)
    route = router._classify("analyse XAUUSD M15")
    assert route.intent == "analyze"
    assert route.symbol == "XAUUSD"
    assert route.timeframe == "M15"


def test_classify_brief(rt):
    router = DeskRouter(rt)
    route = router._classify("brief me on XAUUSD price action")
    assert route.intent == "brief"
    assert route.symbol == "XAUUSD"


def test_classify_close_ticket(rt):
    router = DeskRouter(rt)
    route = router._classify("close position 12345")
    assert route.intent == "manage"
    assert route.ticket == "12345"
    assert route.action == "close"


def test_respond_identity(rt):
    router = DeskRouter(rt)
    response = router.route("who are you?", [])
    assert "Aegus" in response.narrative
    assert response.route.intent == "identity"


def test_respond_decline(rt):
    router = DeskRouter(rt)
    response = router.route("what's the weather like today", [])
    assert "trading-only" in response.narrative.lower()
    assert response.route.intent == "decline"


def test_respond_brief(rt):
    router = DeskRouter(rt)
    response = router.route("brief me on XAUUSD", [])
    assert isinstance(response.narrative, str)
    assert len(response.narrative) > 0
    assert response.route.intent == "brief"


def test_session_guard(rt):
    from backend.ignite.agent.session import SessionGuard
    guard = SessionGuard(rt)
    state = guard.evaluate()
    assert isinstance(state.tradable, bool)
    assert isinstance(state.reasons, list)
