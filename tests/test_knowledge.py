"""Knowledge cards: parsing, lint, placeholder rendering and SQLite loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.ignite.knowledge import (
    FACT_SPECS,
    CardError,
    desk_facts,
    lint_cards,
    load_cards,
    parse_card,
    render_card,
    sync_cards,
)
from backend.ignite.analysis.risk import RiskConfig
from backend.ignite.config import ROOT
from backend.ignite.store.db import Store

VALID = """---
id: risk.example-card
title: An example rule
scope: risk_manager
layer: L1
version: 2
status: reviewed
reviewed_by: reviewer
priority: 70
tags: [risk, example]
facts: [risk.risk_pct]
applies_to: [analysis_narrative]
max_words: 80
---

## Rule

Risk {{risk.risk_pct}} of equity per trade.
"""


def write(directory: Path, name: str, text: str) -> Path:
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_parse_valid_card():
    card = parse_card(VALID, "example.md")
    assert card.id == "risk.example-card"
    assert card.version == 2
    assert card.priority == 70
    assert card.applies_to == ("analysis_narrative",)
    assert card.words > 0


def test_reviewed_without_reviewer_is_rejected():
    text = VALID.replace("reviewed_by: reviewer\n", "")
    with pytest.raises(CardError) as exc:
        parse_card(text, "example.md")
    assert any("reviewed_by" in issue for issue in exc.value.issues)


def test_unknown_placeholder_is_rejected():
    text = VALID.replace("facts: [risk.risk_pct]", "facts: [risk.nope]").replace(
        "{{risk.risk_pct}}", "{{risk.nope}}"
    )
    with pytest.raises(CardError) as exc:
        parse_card(text, "example.md")
    assert any("unknown placeholder" in issue for issue in exc.value.issues)


def test_declared_fact_must_be_used():
    text = VALID.replace(
        "facts: [risk.risk_pct]", "facts: [risk.risk_pct, risk.min_rr]"
    )
    with pytest.raises(CardError) as exc:
        parse_card(text, "example.md")
    assert any("never used" in issue for issue in exc.value.issues)


def test_duplicate_ids_are_lint_errors(tmp_path):
    write(tmp_path, "a.md", VALID)
    write(tmp_path, "b.md", VALID)
    result = load_cards(tmp_path)
    assert len(result.cards) == 1
    assert any(issue.code == "duplicate_id" for issue in result.issues)


def test_render_uses_formatted_desk_facts():
    card = parse_card(VALID, "example.md")
    facts = desk_facts(
        type("S", (), {"draft_ttl_s": 90, "news_pre_minutes": 30, "news_post_minutes": 15})(),
        RiskConfig(),
    )
    assert "0.50%" in render_card(card, facts)
    with pytest.raises(ValueError):
        render_card(card, {})


def test_sync_stores_cards_and_searches(tmp_path):
    write(tmp_path, "a.md", VALID)
    store = Store(tmp_path / "test.db")
    try:
        result = sync_cards(store, tmp_path)
        assert result.ok and result.written and result.loaded == 1
        stored = store.knowledge_cards(scope="risk_manager")
        assert stored[0]["id"] == "risk.example-card"
        assert store.knowledge_card("risk.example-card")["tags"] == ["risk", "example"]
        hits = store.search_knowledge("equity")
        assert [hit["id"] for hit in hits] == ["risk.example-card"]
    finally:
        store.close()


def test_lint_failure_keeps_the_previous_catalogue(tmp_path):
    write(tmp_path, "a.md", VALID)
    store = Store(tmp_path / "test.db")
    try:
        assert sync_cards(store, tmp_path).written
        write(tmp_path, "bad.md", VALID.replace("{{risk.risk_pct}}", "{{risk.nope}}"))
        result = sync_cards(store, tmp_path)
        assert not result.ok and not result.written
        assert len(store.knowledge_cards()) == 1
    finally:
        store.close()


def test_the_real_card_directory_is_clean():
    directory = ROOT / "docs" / "agent-knowledge"
    result = load_cards(directory)
    assert lint_cards(directory) == []
    assert len(result.cards) >= 13
    assert {card.scope for card in result.cards} >= {
        "risk_manager",
        "market_analyst",
        "fundamentals_desk",
    }
    assert all(card.status == "reviewed" for card in result.cards)
    assert set(FACT_SPECS) >= {
        "risk.risk_pct",
        "risk.max_drift_atr",
        "instrument.contract_size",
    }
