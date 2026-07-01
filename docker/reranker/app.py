# pyright: reportMissingImports=false

from __future__ import annotations

import os
from typing import Any

import torch
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from transformers import AutoModelForSequenceClassification, AutoTokenizer

MODEL_ID = os.getenv("RERANK_MODEL_ID", "BAAI/bge-reranker-base")
BATCH_SIZE = int(os.getenv("RERANK_BATCH_SIZE", "8"))
MAX_LENGTH = int(os.getenv("RERANK_MAX_LENGTH", "512"))
HOST = os.getenv("RERANK_HOST", "0.0.0.0")
PORT = int(os.getenv("RERANK_PORT", "8081"))

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


def _resolve_device() -> object:
    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


DEVICE = _resolve_device()

print(f"Loading rerank model {MODEL_ID} on {DEVICE}...", flush=True)
tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
model = AutoModelForSequenceClassification.from_pretrained(MODEL_ID)
model.to(DEVICE)
model.eval()
print(f"Rerank model ready: {MODEL_ID} on {DEVICE}", flush=True)

app = FastAPI(title="MemStack Dev Reranker", version="0.1.0")


class RerankDocument(BaseModel):
    text: str


class RerankRequest(BaseModel):
    query: str
    documents: list[str | RerankDocument] = Field(min_length=1)
    top_n: int | None = None
    return_documents: bool = True


class RerankResult(BaseModel):
    index: int
    score: float
    relevance_score: float
    document: dict[str, str] | None = None


class RerankResponse(BaseModel):
    model: str
    results: list[RerankResult]


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "model": MODEL_ID, "device": str(DEVICE)}


def _document_text(document: str | RerankDocument) -> str:
    if isinstance(document, str):
        return document
    return document.text


def _score_pairs(query: str, documents: list[str]) -> list[float]:
    scores: list[float] = []
    with torch.inference_mode():
        for start in range(0, len(documents), BATCH_SIZE):
            batch_docs = documents[start : start + BATCH_SIZE]
            encoded = tokenizer(
                [(query, doc) for doc in batch_docs],
                padding=True,
                truncation=True,
                max_length=MAX_LENGTH,
                return_tensors="pt",
            )
            encoded = {key: value.to(DEVICE) for key, value in encoded.items()}
            logits = model(**encoded).logits.squeeze(-1).detach().cpu().float().tolist()
            if isinstance(logits, float):
                scores.append(logits)
            else:
                scores.extend(float(score) for score in logits)
    return scores


@app.post("/rerank", response_model=RerankResponse)
@app.post("/v1/rerank", response_model=RerankResponse)
def rerank(payload: RerankRequest) -> RerankResponse:
    if not payload.query.strip():
        raise HTTPException(status_code=400, detail="query must not be empty")

    documents = [_document_text(document) for document in payload.documents]
    top_n = payload.top_n if payload.top_n is not None else len(documents)
    top_n = max(0, min(top_n, len(documents)))

    scores = _score_pairs(payload.query, documents)
    ranked = sorted(enumerate(scores), key=lambda item: item[1], reverse=True)[:top_n]

    results: list[RerankResult] = []
    for idx, score in ranked:
        document = {"text": documents[idx]} if payload.return_documents else None
        results.append(
            RerankResult(
                index=idx,
                score=score,
                relevance_score=score,
                document=document,
            )
        )
    return RerankResponse(model=MODEL_ID, results=results)


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT, log_level=os.getenv("LOG_LEVEL", "info").lower())
