---
id: risk.one-position-per-symbol
title: One thesis, one position
scope: risk_manager
layer: L1
version: 1
status: reviewed
reviewed_by: user48
priority: 80
tags: [exposure, discipline]
facts: []
applies_to: [analysis_narrative, draft_review, postmortem]
max_words: 180
---

## Rule

One open position per symbol. No averaging down, no hedging the same symbol, no second entry because the first looks early.

## Why

Two positions in one symbol are one directional bet with doubled size and two stops the risk engine cannot see as a single unit. Averaging down moves the average entry and hides the original error.

## In practice

If a position is open, the desk waits. Add the next idea to the watchlist instead of adding to the trade. A new analysis can be stored without producing an executable draft; that is the correct outcome.
