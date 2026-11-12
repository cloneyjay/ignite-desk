---
id: risk.reward-and-expectancy
title: Judge expectancy, not the last trade
scope: risk_manager
layer: L1
version: 1
status: reviewed
reviewed_by: user48
priority: 86
tags: [expectancy, r-multiple, discipline]
facts: [risk.min_rr]
applies_to: [analysis_narrative, draft_review, postmortem]
max_words: 180
---

## Rule

Only take setups that pay at least {{risk.min_rr}} reward-to-risk. Judge the desk on expectancy, not on the last trade: expectancy = win rate × average win − loss rate × average loss.

## Why

At 2R a strategy that wins 40% of the time still makes money: 0.4 × 2R − 0.6 × 1R = +0.2R per trade. A high win rate with a poor R multiple usually means stops are too wide and one loss erases many wins.

## In practice

Record the R multiple of every closed trade. Do not move a target closer because the trade looks strong; that changes the strategy mid-sample. Three losses in a row is normal at a 40% win rate and is not a reason to increase size.
