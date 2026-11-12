---
id: risk.drift-guard
title: Do not chase a forecast that already happened
scope: risk_manager
layer: L1
version: 1
status: reviewed
reviewed_by: user48
priority: 92
tags: [drift, entry, discipline]
facts: [risk.max_drift_atr]
applies_to: [analysis_narrative, draft_review, postmortem]
max_words: 180
---

## Rule

Block a draft when live price has moved more than {{risk.max_drift_atr}} from the last closed bar. The forecast is anchored on that close; the entry is not.

## Why

A signal that the market has already run past is no longer the same trade. Chasing turns a planned 1.5 ATR stop into a much wider effective risk and puts the target closer than the model assumed.

## In practice

If the draft is blocked by drift, wait for the next closed bar and re-run the analysis. Do not refresh repeatedly until a draft happens to pass. The block is information: the setup moved without you.
