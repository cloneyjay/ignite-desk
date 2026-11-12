"""P0 spike: measure Kronos inference latency on this machine.

Throwaway measurement harness - not production code. Purpose: decide which
Kronos checkpoint and context length is viable for day trading on a 4-core
CPU with no CUDA.

Measures, per model:
  * cold load time (after weights are already on disk)
  * warm per-sample latency (sample_count=1) at a given lookback/horizon
  * batched latency (sample_count=25, returns the mean path)
  * resident memory after load

Usage:
  python bench.py --model mini  --lookback 288 --horizon 12
  python bench.py --model small --lookback 288 --horizon 12
  python bench.py --model base  --lookback 288 --horizon 12 --runs 2
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "vendor" / "kronos"))

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

import numpy as np
import pandas as pd
import psutil
import torch
from model import Kronos, KronosPredictor, KronosTokenizer

MODELS = {
    # name: (tokenizer, model, max_context)
    "mini": ("NeoQuasar/Kronos-Tokenizer-2k", "NeoQuasar/Kronos-mini", 2048),
    "small": ("NeoQuasar/Kronos-Tokenizer-base", "NeoQuasar/Kronos-small", 512),
    "base": ("NeoQuasar/Kronos-Tokenizer-base", "NeoQuasar/Kronos-base", 512),
}

TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}


def synth_bars(tf_minutes: int, n: int, seed: int = 7) -> pd.DataFrame:
    """Deterministic XAUUSD-like OHLCV. Latency is data-independent; shape is not."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-02", periods=max(n * 4, n + 2000), freq=f"{tf_minutes}min")
    idx = idx[idx.day_of_week < 5][:n]
    if len(idx) < n:
        raise RuntimeError(f"not enough weekday bars generated: {len(idx)} < {n}")

    scale = np.sqrt(tf_minutes / 60.0)
    ret = rng.normal(0.0, 0.0012 * scale, n)
    close = 4000.0 * np.exp(np.cumsum(ret))
    open_ = np.r_[close[0], close[:-1]]
    wick = np.abs(rng.normal(0.0, 0.0008 * scale, n)) * close
    high = np.maximum(open_, close) + wick
    low = np.minimum(open_, close) - wick
    volume = rng.integers(200, 20000, n).astype(float)

    df = pd.DataFrame(
        {
            "time": idx,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )
    df["amount"] = df["volume"] * df["close"]
    return df


def build_future_timestamps(last_time: pd.Timestamp, tf_minutes: int, horizon: int) -> pd.Series:
    out, t = [], last_time
    step = pd.Timedelta(minutes=tf_minutes)
    while len(out) < horizon:
        t = t + step
        if t.day_of_week < 5:  # skip weekends, like a real symbol
            out.append(t)
    return pd.Series(out)


def run(
    model_name: str,
    tf: str,
    lookback: int,
    horizon: int,
    runs: int,
    samples: int,
    threads: int | None = None,
) -> dict:
    tok_id, mdl_id, max_context = MODELS[model_name]
    tf_minutes = TF_MINUTES[tf]
    if threads:
        torch.set_num_threads(threads)

    print(f"[load] {mdl_id} (+ {tok_id}) ...", flush=True)
    t0 = time.perf_counter()
    tokenizer = KronosTokenizer.from_pretrained(tok_id)
    model = Kronos.from_pretrained(mdl_id)
    model.eval()
    predictor = KronosPredictor(model, tokenizer, device="cpu", max_context=max_context)
    load_s = time.perf_counter() - t0

    rss_mb = psutil.Process().memory_info().rss / 1024**2
    threads = torch.get_num_threads()

    df = synth_bars(tf_minutes, lookback + 10)
    x = df.tail(lookback).reset_index(drop=True)
    y_ts = build_future_timestamps(x["time"].iloc[-1], tf_minutes, horizon)

    cols = ["open", "high", "low", "close", "volume", "amount"]

    def one(count: int) -> float:
        t = time.perf_counter()
        predictor.predict(
            df=x[cols],
            x_timestamp=x["time"],
            y_timestamp=y_ts,
            pred_len=horizon,
            T=1.0,
            top_p=0.9,
            sample_count=count,
            verbose=False,
        )
        return time.perf_counter() - t

    print("[warmup] ...", flush=True)
    one(1)

    per_sample = [one(1) for _ in range(runs)]
    batched = one(samples)

    result = {
        "model": model_name,
        "model_id": mdl_id,
        "timeframe": tf,
        "lookback": lookback,
        "horizon": horizon,
        "load_s": round(load_s, 2),
        "rss_mb": round(rss_mb, 1),
        "torch_threads": threads,
        "per_sample_s": [round(v, 3) for v in per_sample],
        "per_sample_median_s": round(float(np.median(per_sample)), 3),
        "batched_samples": samples,
        "batched_s": round(batched, 3),
        "analysis_25x_seq_s": round(float(np.median(per_sample)) * 25, 1),
        "analysis_25x_batched_s": round(batched, 1),
    }
    print(json.dumps(result, indent=2), flush=True)
    return result


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--model", choices=sorted(MODELS), default="mini")
    p.add_argument("--tf", choices=sorted(TF_MINUTES), default="M15")
    p.add_argument("--lookback", type=int, default=288)
    p.add_argument("--horizon", type=int, default=12)
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--samples", type=int, default=25)
    p.add_argument("--threads", type=int, default=None, help="torch intra-op threads (default: torch chooses)")
    p.add_argument("--out", default=str(Path(__file__).with_name("out")))
    args = p.parse_args()

    result = run(
        args.model, args.tf, args.lookback, args.horizon, args.runs, args.samples, args.threads
    )

    out_dir = Path(args.out)
    out_dir.mkdir(exist_ok=True)
    tag = f"{args.model}_{args.tf}_lb{args.lookback}_h{args.horizon}"
    (out_dir / f"{tag}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
