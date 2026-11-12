# Agent knowledge cards

These markdown files are the desk's reviewed memory. They are loaded into
SQLite (`knowledge_cards` + FTS5) at startup and selected by scope for each
agent skill. The model never chooses a card; the selector is deterministic.

## Format

```yaml
---
id: risk.example            # lowercase, stable, unique
title: One-line rule
scope: risk_manager         # risk_manager | market_analyst | fundamentals_desk | desk_analyst
layer: L1                   # L1 desk rule | L2 market knowledge | L3 computed memory
version: 1
status: reviewed            # draft cards are never sent to a model
reviewed_by: user48
priority: 50                # higher is selected first
tags: [risk, sizing]
facts: [risk.risk_pct]      # every placeholder must be declared here
applies_to: [analysis_narrative]
max_words: 180
---
```

The body is plain markdown. Live values use `{{fact.name}}` placeholders from
`backend/ignite/knowledge/facts.py`; a number must never be typed into a card
if the engine owns it.

## Rules

- `status: reviewed` requires `reviewed_by`. Draft cards stay out of prompts.
- Every placeholder must be declared in `facts` and must exist in the fact
  registry. Unused declarations are errors too.
- `applies_to` must name at least one known skill.
- The body must stay inside `max_words`.
- Editing a reviewed card means bumping `version` and reviewing it again.

## Commands

```powershell
python -m backend.ignite.cli knowledge lint
python -m backend.ignite.cli knowledge list
python -m backend.ignite.cli knowledge show risk.drift-guard
python -m backend.ignite.cli knowledge reload
```

`reload` refuses to write a directory with any lint issue. The previous
catalogue stays in place, and `/api/health` reports the failure.
