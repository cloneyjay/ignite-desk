"""Kronos inference worker.

Runs as its own process so multi-second CPU inference never blocks the API.

  .\\.venv\\Scripts\\python.exe -m backend.ignite.forecasting.worker

POST /forecast  -> sampled close paths
GET  /health    -> model id, ready state, timing
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "vendor" / "kronos"))

from model import Kronos, KronosPredictor, KronosTokenizer  # noqa: E402

TOKENIZERS = {
    "NeoQuasar/Kronos-mini": ("NeoQuasar/Kronos-Tokenizer-2k", 2048),
    "NeoQuasar/Kronos-small": ("NeoQuasar/Kronos-Tokenizer-base", 512),
    "NeoQuasar/Kronos-base": ("NeoQuasar/Kronos-Tokenizer-base", 512),
}

STATE: dict[str, Any] = {"ready": False, "model": None, "predictor": None, "load_s": None}
LOCK = asyncio.Lock()


class Bar(BaseModel):
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    amount: float | None = None


class ForecastRequest(BaseModel):
    bars: list[Bar] = Field(min_length=16)
    future_timestamps: list[str] = Field(min_length=1)
    samples: int = Field(default=25, ge=1, le=100)
    temperature: float = Field(default=1.0, gt=0.0, le=5.0)
    top_p: float = Field(default=0.9, gt=0.0, le=1.0)
    lookback: int = Field(default=288, ge=16, le=2048)


class ForecastResponse(BaseModel):
    model_id: str
    paths: list[list[float]]
    timestamps: list[str]
    samples: int
    horizon: int
    infer_s: float


@asynccontextmanager
async def lifespan(app: FastAPI):
    model_id = os.getenv("KRONOS_MODEL", "NeoQuasar/Kronos-mini")
    if model_id not in TOKENIZERS:
        raise RuntimeError(f"unsupported model {model_id}")
    tokenizer_id, max_context = TOKENIZERS[model_id]

    if os.getenv("KRONOS_THREADS"):
        torch.set_num_threads(int(os.environ["KRONOS_THREADS"]))

    started = time.perf_counter()
    tokenizer = KronosTokenizer.from_pretrained(tokenizer_id)
    model = Kronos.from_pretrained(model_id)
    model.eval()
    predictor = KronosPredictor(model, tokenizer, device="cpu", max_context=max_context)

    STATE.update(
        ready=True,
        model=model_id,
        predictor=predictor,
        load_s=round(time.perf_counter() - started, 2),
        max_context=max_context,
        threads=torch.get_num_threads(),
    )
    yield
    STATE["ready"] = False


app = FastAPI(title="ignite-desk kronos worker", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ready": STATE["ready"],
        "model": STATE["model"],
        "load_s": STATE["load_s"],
        "threads": STATE.get("threads"),
        "max_context": STATE.get("max_context"),
    }


def _infer(req: ForecastRequest) -> tuple[np.ndarray, list[str], float]:
    predictor: KronosPredictor = STATE["predictor"]
    df = pd.DataFrame([b.model_dump() for b in req.bars])
    df["time"] = pd.to_datetime(df["time"])
    df["volume"] = df["volume"].astype(float)
    if "amount" not in df or df["amount"].isna().any():
        df["amount"] = df["volume"] * df["close"]

    x = df.tail(req.lookback).reset_index(drop=True)
    y_ts = pd.Series(pd.to_datetime(req.future_timestamps))

    started = time.perf_counter()
    paths = []
    for _ in range(req.samples):
        pred = predictor.predict(
            df=x[["open", "high", "low", "close", "volume", "amount"]],
            x_timestamp=x["time"],
            y_timestamp=y_ts,
            pred_len=len(y_ts),
            T=req.temperature,
            top_p=req.top_p,
            sample_count=1,
            verbose=False,
        )
        paths.append(pred["close"].to_numpy(dtype=float))
    return np.vstack(paths), [str(t) for t in y_ts], time.perf_counter() - started


@app.post("/forecast", response_model=ForecastResponse)
async def forecast(req: ForecastRequest) -> ForecastResponse:
    if not STATE["ready"]:
        raise HTTPException(status_code=503, detail="model not loaded")

    async with LOCK:
        try:
            paths, timestamps, infer_s = await asyncio.to_thread(_infer, req)
        except Exception as exc:  # noqa: BLE001 - surface the real error to the caller
            raise HTTPException(status_code=500, detail=f"inference failed: {exc}") from exc

    return ForecastResponse(
        model_id=STATE["model"],
        paths=paths.round(6).tolist(),
        timestamps=timestamps,
        samples=len(paths),
        horizon=len(timestamps),
        infer_s=round(infer_s, 3),
    )


def main() -> None:
    uvicorn.run(
        "backend.ignite.forecasting.worker:app",
        host=os.getenv("KRONOS_BIND_HOST", "127.0.0.1"),
        port=8765,
        log_level="info",
    )


if __name__ == "__main__":
    main()
