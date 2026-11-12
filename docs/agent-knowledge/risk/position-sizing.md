---
id: risk.position-sizing
title: Size from the stop, not from conviction
scope: risk_manager
layer: L1
version: 1
status: reviewed
reviewed_by: user48
priority: 90
tags: [sizing, risk, expectancy]
facts: [risk.risk_pct, risk.max_risk_pct, instrument.contract_size]
applies_to: [analysis_narrative, draft_review, postmortem]
max_words: 180
---

## Rule

Risk {{risk.risk_pct}} of account equity per trade, never more than {{risk.max_risk_pct}}. Size is derived from the stop: lots = risk in USD / (stop distance × contract size). On XAUUSD one lot is {{instrument.contract_size}} ounces, so 0.01 lots moves $1 for every $1 move in gold.

## Why

A forecast is a probability, not a promise. Fixed-fractional sizing keeps a normal losing streak survivable and makes every trade comparable in R. Sizing from conviction instead of the stop quietly turns one bad bar into an account-level event.

## In practice

Take the broker's lot step and minimum. If the arithmetic rounds to zero, the stop is too wide for the account — do not widen risk to force the trade. Report the size the engine produced; never round it up by hand.
