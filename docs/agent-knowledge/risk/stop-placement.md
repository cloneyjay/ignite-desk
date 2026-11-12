---
id: risk.stop-placement
title: The stop is part of the thesis
scope: risk_manager
layer: L1
version: 1
status: reviewed
reviewed_by: user48
priority: 88
tags: [stops, atr, risk]
facts: [risk.sl_atr, risk.tp_atr, risk.min_rr]
applies_to: [analysis_narrative, draft_review, postmortem]
max_words: 180
---

## Rule

The initial stop is {{risk.sl_atr}} away and the target {{risk.tp_atr}} away, giving at least {{risk.min_rr}} reward-to-risk. Both levels are sent with the order; an entry without a stop is not a trade.

## Why

ATR is the market's current unit of movement. A stop inside one ATR sits inside the noise and is taken out by spread and normal oscillation. A fixed reward-to-risk also stops a wide target from disguising a poor entry.

## In practice

Place the stop beyond the level that would prove the idea wrong, not at a round number that feels comfortable. Never widen a stop after entry. If the broker's minimum stop distance is wider than the plan, the trade is blocked, not resized.
