---
id: risk.spread-and-slippage
title: The spread is a cost, not a detail
scope: risk_manager
layer: L1
version: 1
status: reviewed
reviewed_by: user48
priority: 84
tags: [spread, execution, liquidity]
facts: [risk.max_spread_points]
applies_to: [analysis_narrative, draft_review, postmortem]
max_words: 180
---

## Rule

Refuse entries when the spread is wider than {{risk.max_spread_points}}. Spread is paid on entry and again on exit, and it is charged in the same units as the stop.

## Why

Gold spreads widen at rollover, around high-impact releases and when liquidity thins. A 30-point cap on a 400-point stop is 7.5% of the risk budget before slippage; at 100 points it is a quarter of the trade's edge.

## In practice

Check the live spread at execution, not the spread printed on the closed bar. If the spread is wide because news is imminent, wait for the window to pass. Never widen the stop to pay for the spread.
