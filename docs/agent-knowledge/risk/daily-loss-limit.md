---
id: risk.daily-loss-limit
title: End the day before the account does
scope: risk_manager
layer: L1
version: 1
status: reviewed
reviewed_by: user48
priority: 82
tags: [daily-loss, kill-switch, discipline]
facts: []
applies_to: [analysis_narrative, draft_review, postmortem]
max_words: 180
---

## Rule

Stop for the day after a fixed loss limit or a run of losers, whichever comes first. The kill switch is manual, absolute, and never reset by the model.

## Why

Loss limits protect the account from the trader, not from the market. The hours after a sharp loss are when size creeps up and rules get reinterpreted. A hard stop converts an emotional afternoon into a flat evening.

## In practice

Use realised plus open risk, not just closed P/L. Once the limit is hit, close the platform, write the postmortem, and leave the kill switch on until the next session. No just-one-more trade.
