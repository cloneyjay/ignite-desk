"""HTTP client for the Kronos worker."""

from __future__ import annotations

import httpx
import numpy as np
import pandas as pd


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
    ) -> tuple[np.ndarray, list[pd.Timestamp], dict]:
        payload = {
            "bars": [
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
            ],
            "future_timestamps": [pd.Timestamp(t).isoformat() for t in future_timestamps],
            "samples": samples,
            "lookback": lookback,
            "temperature": temperature,
            "top_p": top_p,
        }
        try:
            response = self._client.post(f"{self._base}/forecast", json=payload)
        except httpx.HTTPError as exc:
            raise ForecastError(f"forecast request failed: {exc}") from exc
        if response.status_code != 200:
            raise ForecastError(f"worker returned {response.status_code}: {response.text[:500]}")

        body = response.json()
        paths = np.asarray(body["paths"], dtype=float)
        stamps = [pd.Timestamp(t) for t in body["timestamps"]]
        meta = {
            "model_id": body["model_id"],
            "infer_s": body["infer_s"],
            "samples": body["samples"],
        }
        return paths, stamps, meta
