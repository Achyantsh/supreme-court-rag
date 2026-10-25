"""RAG Answer Generation Engine over Indian Supreme Court Judgments

Features:
- Hybrid RRF retrieval + Cross-Encoder reranking via QueryEngine
- LLM answer synthesis using Google Gemini (gemini-3.8-flash)
- Strict legal citation grounding ([Case Name, Citation])
- Evidence abstention when context is insufficient
- Streaming and non-streaming support
"""

import os
from pathlib import Path
from typing import Dict, Any, Generator, List

from google import genai
from google.genai import types

from query_pipeline import QueryEngine

DEFAULT_MODEL = "gemini-2.5-flash"

SYSTEM_INSTRUCTION = """You are a senior Indian constitutional and criminal law research assistant.
Your task is to answer legal inquiries strictly using the provided Supreme Court of India judgment extracts.

RULES:
1. Grounding: Answer ONLY based on the provided judgment extracts. Do not use ungrounded external knowledge.
2. Citation Format: For every principle or ratio cited, clearly reference the case name and SCR citation, e.g.: [Priya Indoria v. State of Karnataka, (2023) 15 SCR 525].
3. Direct Ratio: Highlight the key ratio decidendi or legal test established by the Court.
4. Abstention: If the provided judgment excerpts do not contain sufficient evidence to answer the question, clearly state:
   "Based on the provided 2023 Supreme Court judgments, there is insufficient evidence to conclusively address this question."
5. Neutrality: Maintain objective, precise judicial analysis. Do not speculate.
"""


def load_env_file():
    """Load GEMINI_API_KEY from .env if present."""
    env_file = Path(".env")
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip().strip("'\"")


class RAGEngine:
    def __init__(self, query_engine: QueryEngine = None, api_key: str = None, model: str = DEFAULT_MODEL):
        load_env_file()
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model = model

        if not self.api_key:
            print("WARNING: GEMINI_API_KEY not found in environment or .env file.")
            print("Set GEMINI_API_KEY to enable LLM answer generation.")

        self.client = genai.Client(api_key=self.api_key) if self.api_key else None
        self.query_engine = query_engine or QueryEngine()

    def build_prompt(self, query: str, contexts: List[Dict[str, Any]]) -> str:
        prompt_parts = [
            f"LEGAL INQUIRY:\n{query}\n",
            "RELEVANT JUDGMENT EXTRACTS FROM CORPUS:\n",
        ]

        for i, doc in enumerate(contexts, 1):
            case_name = doc.get("case_name", "Unknown Case")
            citation = doc.get("citation", "N/A")
            date = doc.get("decision_date", "N/A")
            text = doc.get("text", "").strip()

            prompt_parts.append(
                f"--- [Extract {i}] ---\n"
                f"Case: {case_name}\n"
                f"Citation: {citation}\n"
                f"Decision Date: {date}\n"
                f"Content:\n{text}\n"
            )

        prompt_parts.append(
            "\nSYNTHESIS TASK:\n"
            "Provide a clear, well-structured legal answer addressing the inquiry based strictly on the extracts above. "
            "Cite the corresponding case name for each point. If the context does not address the question, state that clearly."
        )

        return "\n".join(prompt_parts)

    def generate_answer(self, query: str, top_k: int = 5, mode: str = "hybrid_reranked") -> Dict[str, Any]:
        """Generate grounded answer with retrieved citations."""
        contexts = self.query_engine.retrieve(query, mode=mode, top_k=top_k)

        citations = [
            {
                "case_name": c.get("case_name"),
                "citation": c.get("citation"),
                "decision_date": c.get("decision_date"),
                "source_pdf": c.get("source_pdf"),
                "score": c.get("rerank_score", c.get("score")),
                "excerpt": c.get("text", "")[:350] + "...",
            }
            for c in contexts
        ]

        if not self.client:
            return {
                "query": query,
                "answer": (
                    "[GEMINI_API_KEY MISSING] Retrieved evidence passages successfully, "
                    "but an API key is required to synthesize the grounded answer. "
                    "Please set GEMINI_API_KEY in your .env file."
                ),
                "citations": citations,
                "retrieval_mode": mode,
                "model": self.model,
            }

        prompt = self.build_prompt(query, contexts)

        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=0.2,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            max_output_tokens=3000,
        )

        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=config,
        )

        return {
            "query": query,
            "answer": response.text,
            "citations": citations,
            "retrieval_mode": mode,
            "model": self.model,
        }

    def generate_stream(self, query: str, top_k: int = 5, mode: str = "hybrid_reranked") -> Generator[str, None, None]:
        """Stream generated answer tokens via generator (for SSE)."""
        contexts = self.query_engine.retrieve(query, mode=mode, top_k=top_k)

        if not self.client:
            yield "GEMINI_API_KEY not configured. Set GEMINI_API_KEY in .env."
            return

        prompt = self.build_prompt(query, contexts)
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=0.2,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            max_output_tokens=3000,
        )

        stream = self.client.models.generate_content_stream(
            model=self.model,
            contents=prompt,
            config=config,
        )

        for chunk in stream:
            if chunk.text:
                yield chunk.text

    def close(self):
        if self.query_engine:
            self.query_engine.close()


if __name__ == "__main__":
    engine = RAGEngine()
    try:
        sample_query = "What principles govern the grant of anticipatory bail under Section 438 CrPC?"
        print(f"\nUser Query: {sample_query}\n")
        result = engine.generate_answer(sample_query, top_k=5)
        print("=== GENERATED ANSWER ===")
        print(result["answer"])
        print("\n=== CITATIONS ===")
        for i, cit in enumerate(result["citations"], 1):
            print(f"[{i}] {cit['case_name']} ({cit['citation']}) - Score: {cit['score']:.4f}")
    finally:
        engine.close()
