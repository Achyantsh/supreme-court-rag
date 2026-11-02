"""RAG Answer Generation Engine over Indian Supreme Court Judgments

Features:
- Hybrid RRF retrieval + Cross-Encoder reranking via QueryEngine
- LLM answer synthesis using Google Gemini (gemini-3.8-flash)
- Strict legal citation grounding ([Case Name, Citation])
- Evidence abstention when context is insufficient
- Streaming and non-streaming support
"""

import os
import re
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

SYSTEM_INSTRUCTION_V2 = """You are a senior Indian constitutional and criminal law research assistant.
Answer only from the supplied retrieved Supreme Court judgment extracts.

V2 LEGAL-SOURCE DISCIPLINE:
1. Address the exact legal issue and elements asked in LEGAL INQUIRY. Do not answer a related or neighbouring question.
2. Every material legal proposition must cite one or more source IDs in the form [S1], [S2]. Use only source IDs supplied in the extracts.
3. Distinguish the Supreme Court's holding from counsel submissions, quoted arguments, lower-court reasoning, statutory text, headnotes, and background discussion. Do not present those materials as the Supreme Court's holding unless the extract says the Court adopted them.
4. Preserve each rule's statute, procedural posture, and exceptions. Do not generalize a PMLA-specific rule or consequence to all criminal cases.
5. Identify which requested legal-test elements are missing from the extracts. If the evidence is insufficient, abstain from a definitive conclusion and say what is missing.
6. Preserve relevant qualifications and limitations. Do not add unsupported or off-topic claims.
7. Keep the answer readable, but put [S#] immediately after each material proposition it supports.
"""

SOURCE_REFERENCE_PATTERN = re.compile(r"\[([^\]\s]+)\]")


def build_source_records(contexts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Assign stable, request-local IDs while retaining retrieved metadata."""
    sources = []
    for rank, context in enumerate(contexts, start=1):
        source_id = f"S{rank}"
        sources.append({
            "source_id": source_id,
            "doc_id": context.get("doc_id"),
            "case_name": context.get("case_name"),
            "citation": context.get("citation"),
            "decision_date": context.get("decision_date"),
            "excerpt": context.get("text", ""),
            "rank": context.get("rank", rank),
            "score": context.get("score", context.get("rerank_score", context.get("rrf_score"))),
            "source_pdf": context.get("source_pdf"),
        })
    return sources


def validate_source_references(answer: str, sources: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Validate membership only; semantic claim support still requires review."""
    source_map = {source["source_id"]: source for source in sources}
    references = SOURCE_REFERENCE_PATTERN.findall(answer or "")
    source_references = [reference for reference in references if reference.startswith("S")]
    malformed = [
        reference for reference in source_references
        if not re.fullmatch(r"S\d+", reference)
    ]
    unknown = [
        reference for reference in source_references
        if re.fullmatch(r"S\d+", reference) and reference not in source_map
    ]
    valid = [
        source_map[reference]
        for reference in source_references
        if reference in source_map and reference not in malformed
    ]
    return {
        "status": "valid" if not malformed and not unknown else "invalid",
        "source_references": source_references,
        "unknown_source_ids": sorted(set(unknown)),
        "malformed_source_references": sorted(set(malformed)),
        "resolved_sources": valid,
        "semantic_support_verified": False,
    }


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

    def build_prompt(
        self,
        query: str,
        contexts: List[Dict[str, Any]],
        answer_version: str = "v1",
    ) -> str:
        prompt_parts = [
            f"LEGAL INQUIRY:\n{query}\n",
            "RELEVANT JUDGMENT EXTRACTS FROM CORPUS:\n",
        ]

        source_records = build_source_records(contexts)
        for index, source in enumerate(source_records):
            doc = contexts[index]
            case_name = doc.get("case_name", "Unknown Case")
            citation = doc.get("citation", "N/A")
            date = doc.get("decision_date", "N/A")
            text = doc.get("text", "").strip()

            prompt_parts.append(
                f"--- [{source['source_id'] if answer_version == 'v2' else 'Extract ' + str(index + 1)}] ---\n"
                f"Case: {case_name}\n"
                f"Citation: {citation}\n"
                f"Decision Date: {date}\n"
                + (
                    f"Retrieved Rank: {source['rank']}\n"
                    f"Retrieved Score: {source['score']}\n"
                    if answer_version == "v2" else ""
                )
                + f"Content:\n{text}\n"
            )

        prompt_parts.append(
            "\nSYNTHESIS TASK:\n"
            "Provide a clear, well-structured legal answer addressing the inquiry based strictly on the extracts above. "
            + (
                "Cite the corresponding source ID for each material point. "
                if answer_version == "v2"
                else "Cite the corresponding case name for each point. "
            )
            + "If the context does not address the question, state that clearly."
        )
        if answer_version == "v2":
            prompt_parts.insert(0, SYSTEM_INSTRUCTION_V2 + "\n")

        return "\n".join(prompt_parts)

    def generate_answer(
        self,
        query: str,
        top_k: int = 5,
        mode: str = "hybrid_reranked",
        model: str | None = None,
        contexts: List[Dict[str, Any]] | None = None,
        answer_version: str = "v1",
    ) -> Dict[str, Any]:
        """Generate grounded answer with retrieved citations."""
        if answer_version not in {"v1", "v2"}:
            raise ValueError(f"Unknown answer version: {answer_version}")
        contexts = contexts if contexts is not None else self.query_engine.retrieve(query, mode=mode, top_k=top_k)
        contexts = [
            {**context, "text": context.get("text") or context.get("excerpt", "")}
            for context in contexts
        ]
        selected_model = model or self.model
        source_records = build_source_records(contexts)

        citations = [
            {
                **({"source_id": source["source_id"]} if answer_version == "v2" else {}),
                "case_name": c.get("case_name"),
                "citation": c.get("citation"),
                "decision_date": c.get("decision_date"),
                "doc_id": c.get("doc_id"),
                "rank": source["rank"],
                "source_pdf": c.get("source_pdf"),
                "score": c.get("rerank_score", c.get("score")),
                "excerpt": c.get("text", "")[:350] + "...",
            }
            for c, source in zip(contexts, source_records)
        ]

        base_response = {
            "query": query,
            "citations": citations,
            "retrieval_mode": mode,
            "model": selected_model,
            "answer_version": answer_version,
        }
        if not self.client:
            return {
                **base_response,
                "answer": (
                    "[GEMINI_API_KEY MISSING] Retrieved evidence passages successfully, "
                    "but an API key is required to synthesize the grounded answer. "
                    "Please set GEMINI_API_KEY in your .env file."
                ),
            }

        prompt = self.build_prompt(query, contexts, answer_version=answer_version)

        config_kwargs = {
            "system_instruction": SYSTEM_INSTRUCTION_V2 if answer_version == "v2" else SYSTEM_INSTRUCTION,
            "temperature": 0.2,
            "max_output_tokens": 3000,
        }
        if selected_model == self.model:
            config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
        config = types.GenerateContentConfig(**config_kwargs)

        response = self.client.models.generate_content(
            model=selected_model,
            contents=prompt,
            config=config,
        )

        return {
            **base_response,
            "answer": response.text,
            **(
                {"grounding_validation": validate_source_references(response.text, source_records)}
                if answer_version == "v2"
                else {}
            ),
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
