---
id: risk.news-blackout
title: Stand aside around high-impact data
scope: risk_manager
layer: L1
version: 1
status: reviewed
reviewed_by: user48
priority: 85
tags: [news, blackout, execution]
facts: [news.blackout_pre_min, news.blackout_post_min]
applies_to: [analysis_narrative, draft_review, postmortem]
max_words: 180
---

## Rule

No new entry from {{news.blackout_pre_min}} before to {{news.blackout_post_min}} after a high-impact USD, EUR, CNH or JPY event. If the calendar cannot be read, the order is blocked.

## Why

Around a release, spread widens, fills slip and the first move often reverses. A stop that was outside the noise at 09:50 can be inside the spike at 10:30. The deterministic window exists so the decision is not made while the tape is moving.

## In practice

Treat the window as closed even if the draft is technically valid. Wait for the post-event bar to close, then re-analyse. Never place a pre-news trade to capture the spike.
