---
id: xauusd.contract-and-tick
title: "Gold arithmetic: lots, ounces and dollars"
scope: market_analyst
layer: L2
version: 1
status: reviewed
reviewed_by: user48
priority: 90
tags: [contract, tick, sizing]
facts: [instrument.contract_size]
applies_to: [analysis_narrative, news_bias, daily_brief]
max_words: 180
---

## Rule

XAUUSD is quoted in US dollars per troy ounce to two decimals. One lot is {{instrument.contract_size}} ounces; 0.01 lots is one ounce, so $1 of gold movement is $1 of P/L. A 0.01 lot is not an abstract small unit — it is one ounce.

## Why

Most sizing mistakes on gold come from treating a lot like a share. At 100 ounces per lot, a $10 move on 0.10 lots is $100, and a $40 stop on 0.50 lots is $2,000. The arithmetic must be done before the order, not after.

## In practice

Convert every idea into dollars per lot before comparing it with the account. Check digits, point and contract size from the broker spec rather than memory. Gold's two-decimal quote means a single point is one cent per ounce.
