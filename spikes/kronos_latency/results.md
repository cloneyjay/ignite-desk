# Kronos CPU latency — results

Target machine: i5-5300U (2C/4T), 12 GB RAM, no CUDA, torch 2.15.0+cpu.
Harness: `bench.py`. Synthetic OHLCV (latency depends on tensor shape, not price values).
Lookback 288 bars, horizon 12 bars, `T=1.0`, `top_p=0.9`, torch default threads (2).

| Model | TF | Load (cached) | Per sample | 25-path analysis | RSS |
|---|---|---|---|---|---|
| **Kronos-mini** (4.1M) | M15 | 36.5 s cold / 1.7–3.0 s warm | **0.56 s** | **14.3 s** | 306 MB |
| **Kronos-mini** (4.1M) | M5 | 1.7 s | 0.61 s | 14.8 s | 292 MB |
| Kronos-small (24.7M) | M15 | 2.7 s | 2.81 s | 69.0 s | 371 MB |
| Kronos-base (102M) | M15 | not completed | — | — | — |

## Conclusion

Use **Kronos-mini** (decision D-009). It is 4.8× faster than small at an identical input
shape and stays well inside a 5-minute bar. Small is viable but leaves less headroom and
buys unproven quality. Base was not benchmarked to completion and is not quoted.

## Reproduce

```powershell
.\.venv\Scripts\python.exe spikes\kronos_latency\bench.py --model mini --tf M5 --lookback 288 --horizon 12
```

Raw JSON lands in `spikes/kronos_latency/out/`.
