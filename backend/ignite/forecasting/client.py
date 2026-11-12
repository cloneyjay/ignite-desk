"""HTTP client for the Kronos worker."""

from __future__ import annotations

import httpx
import numpy as np
import pandas as pd
from typing import Callable


class ForecastError(RuntimeError):
    pass


class ForecastClient:
    def __init__(self, base_url: str, timeout_s: float = 240.0) -> None:
        self._base = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout_s)

    def close(self) -> None:
        self._client.close()

    def health(self) -> dict:
        try:
            return self._client.get(f"{self._base}/health").json()
        except httpx.HTTPError as exc:
            raise ForecastError(f"worker unreachable: {exc}") from exc

    def forecast(
        self,
        bars: pd.DataFrame,
        future_timestamps: list[pd.Timestamp],
        samples: int = 25,
        lookback: int = 288,
        temperature: float = 1.0,
        top_p: float = 0.9,
        on_progress: "Callable[[int, int], None] | None" = None,
        batch: int | None = None,
    ) -> tuple[np.ndarray, list[pd.Timestamp], dict]:
        """Sample `samples` paths in small batches so the UI can show progress.

        Inference is sequential on the worker anyway; batching costs nothing and
        turns a 15 s black box into visible steps.
        """
        step = max(1, min(batch or 5, samples))
        rows = [
            {
                "time": row.time.isoformat(),
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
                "volume": float(row.volume),
                "amount": float(row.amount),
            }
            for row in bars.tail(lookback).itertuples(index=False)
        ]

        collected: list[np.ndarray] = []
        stamps: list[pd.Timestamp] = []
        model_id = ""
        infer_total = 0.0
        done = 0
        for offset in range(0, samples, step):
            count = min(step, samples - offset)
            payload = {
                "bars": rows,
                "future_timestamps": [
                    pd.Timestamp(t).isoformat() for t in future_timestamps
                ],
                "samples": count,
                "lookback": lookback,
                "temperature": temperature,
                "top_p": top_p,
            }
            try:
                response = self._client.post(f"{self._base}/forecast", json=payload)
            except httpx.HTTPError as exc:
                raise ForecastError(f"forecast request failed: {exc}") from exc
            if response.status_code != 200:
                raise ForecastError(
                    f"worker returned {response.status_code}: {response.text[:500]}"
                )

            body = response.json()
            collected.append(np.asarray(body["paths"], dtype=float))
            stamps = [pd.Timestamp(t) for t in body["timestamps"]]
            model_id = body["model_id"]
            infer_total += float(body.get("infer_s") or 0.0)
            done += count
            if on_progress is not None:
                on_progress(done, samples)

        meta = {
            "model_id": model_id,
            "infer_s": round(infer_total, 3),
            "samples": samples,
        }
        return np.vstack(collected), stamps, meta
