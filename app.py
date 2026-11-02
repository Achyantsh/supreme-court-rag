"""FastAPI backend for the Supreme Court RAG demo.

Run from the repository root so the existing data/, qdrant_storage/, and .env
paths used by QueryEngine/RAGEngine resolve correctly:
    uvicorn app:app --host 127.0.0.1 --port 8000
"""

import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from rag_engine import RAGEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("supreme_court_rag.api")
BASE_DIR = Path(__file__).resolve().parent

RetrievalMode = Literal["dense", "bm25", "hybrid_rrf", "hybrid_reranked"]


@asynccontextmanager
async def lifespan(application: FastAPI):
    application.state.engine = None
    application.state.initialization_failed = False
    try:
        logger.info("Initializing RAG engine; models may take time on first startup.")
        application.state.engine = RAGEngine()
        logger.info("RAG engine initialized.")
    except Exception:
        application.state.initialization_failed = True
        logger.exception("RAG engine initialization failed.")
    yield
    engine = getattr(application.state, "engine", None)
    if engine is not None:
        try:
            engine.close()
        except Exception:
            logger.exception("Error while closing RAG engine.")


app = FastAPI(
    title="Supreme Court RAG API",
    description="Experimental retrieval-augmented research over an 800-judgment 2023 corpus.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8501",
        "http://localhost:8501",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class QueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=3000)
    retrieval_mode: RetrievalMode = "hybrid_reranked"
    top_k: int = Field(default=5, ge=1, le=10)
    model: Optional[str] = Field(default=None, min_length=1, max_length=100)
    evidence: Optional[list[dict]] = None
    answer_version: Literal["v1", "v2"] = "v1"

    @field_validator("question")
    @classmethod
    def strip_question(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Question must contain at least 3 non-space characters.")
        return value


class RetrieveRequest(BaseModel):
    question: str = Field(min_length=3, max_length=3000)
    retrieval_mode: RetrievalMode = "hybrid_reranked"
    top_k: int = Field(default=5, ge=1, le=10)

    @field_validator("question")
    @classmethod
    def strip_question(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Question must contain at least 3 non-space characters.")
        return value


def get_engine() -> RAGEngine:
    engine = getattr(app.state, "engine", None)
    if engine is None:
        raise HTTPException(
            status_code=503,
            detail="RAG engine is not ready. Check the backend terminal for initialization errors.",
        )
    return engine


def safe_float(value) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def serialize_passage(record: dict, rank: int) -> dict:
    score = record.get("rerank_score")
    if score is None:
        score = record.get("score", record.get("rrf_score"))
    return {
        "rank": rank,
        "doc_id": record.get("doc_id"),
        "case_name": record.get("case_name") or "Unknown case",
        "citation": record.get("citation"),
        "decision_date": record.get("decision_date"),
        "source_pdf": record.get("source_pdf"),
        "chunk_id": record.get("chunk_id"),
        "score": safe_float(score),
        "retrieval_mode": record.get("retrieval_method"),
        "excerpt": (record.get("text") or "")[:1800],
    }


@app.get("/health")
def health():
    engine = getattr(app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="Backend process is running, but RAG engine is not ready.")
    return {"status": "ok", "ready": True, "service": "supreme-court-rag-api"}


@app.post("/api/retrieve")
def retrieve(request: RetrieveRequest):
    engine = get_engine()
    try:
        results = engine.query_engine.retrieve(
            request.question,
            mode=request.retrieval_mode,
            top_k=request.top_k,
        )
        return {
            "question": request.question,
            "retrieval_mode": request.retrieval_mode,
            "count": len(results),
            "results": [serialize_passage(item, rank) for rank, item in enumerate(results, start=1)],
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Retrieval request failed.")
        raise HTTPException(status_code=500, detail="Retrieval failed. Check the backend terminal for details.") from exc


@app.post("/api/query")
def query(request: QueryRequest):
    engine = get_engine()
    if engine.client is None:
        raise HTTPException(
            status_code=503,
            detail="Gemini is not configured. Set GEMINI_API_KEY in the repository .env file and restart the API.",
        )
    started = time.perf_counter()
    requested_model = request.model or engine.model
    try:
        result = engine.generate_answer(
            request.question,
            top_k=request.top_k,
            mode=request.retrieval_mode,
            model=request.model,
            contexts=request.evidence,
            answer_version=request.answer_version,
        )
        citations = result.get("citations") or []
        # Do not present a confident generated answer when retrieval returned no evidence.
        if not citations:
            answer = (
                "The retrieval pipeline did not find judgment extracts for this question. "
                "I cannot provide a grounded answer from the available corpus."
            )
        else:
            answer = result.get("answer") or "The model returned no answer text. Please try again."
        return {
            "question": request.question,
            "answer": answer,
            "citations": citations,
            "retrieval_mode": result.get("retrieval_mode", request.retrieval_mode),
            "model": result.get("model"),
            "answer_version": result.get("answer_version", request.answer_version),
            "grounding_validation": result.get("grounding_validation"),
            "corpus_scope": "Selected English Supreme Court judgments from 2023 (800-document subset)",
            "disclaimer": "Experimental legal research aid, not a substitute for professional legal advice.",
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        status = getattr(exc, "code", None) or getattr(exc, "status_code", None)
        detail = str(exc).replace(getattr(engine, "api_key", "") or "", "[REDACTED]")[:2000]
        logger.error(
            "Answer generation request failed: model=%s status=%s elapsed_seconds=%.3f "
            "error_type=%s detail=%s",
            requested_model,
            status,
            time.perf_counter() - started,
            type(exc).__name__,
            detail,
        )
        # Do not send vendor errors or internal details to clients.
        headers = {"X-Upstream-Status": str(status)} if status is not None else None
        raise HTTPException(
            status_code=502,
            detail="Answer generation failed. Check backend logs and Gemini configuration.",
            headers=headers,
        ) from exc


@app.get("/api/metrics")
def metrics():
    metrics_file = BASE_DIR / "data" / "full_benchmark_metrics_v2.json"
    if not metrics_file.exists():
        raise HTTPException(
            status_code=404,
            detail="Full benchmark metrics are unavailable. Expected data/full_benchmark_metrics_v2.json.",
        )
    try:
        report = json.loads(metrics_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.exception("Could not load benchmark metrics.")
        raise HTTPException(status_code=500, detail="Benchmark metrics file could not be read.") from exc
    return report
