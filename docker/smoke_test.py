"""Live stack checks. No generation unless --generate is explicitly supplied.

Baseline output is a new operational artifact, never an evaluation artifact.
Compare local embedded retrieval to Docker and repeat after container restarts.
"""

import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen

QUESTION = "What principles govern anticipatory bail under Section 438 CrPC?"
MODES = ("dense", "bm25", "hybrid_rrf", "hybrid_reranked")


def request_json(base, path, payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    request = Request(base.rstrip("/") + path, data=body,
                      headers={"Content-Type": "application/json"} if body else {})
    with urlopen(request, timeout=300) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--streamlit", default="http://127.0.0.1:8501")
    parser.add_argument("--skip-streamlit", action="store_true",
                        help="For capturing a local API-only baseline")
    baseline = parser.add_mutually_exclusive_group()
    baseline.add_argument("--write-baseline", type=Path)
    baseline.add_argument("--compare-baseline", type=Path)
    parser.add_argument("--generate", action="store_true",
                        help="One real Gemini request; consumes provider quota and may incur cost")
    args = parser.parse_args()
    if args.write_baseline and args.write_baseline.exists():
        parser.error("Baseline exists; use a new path, never overwrite it")
    health = request_json(args.api, "/health")
    if health.get("ready") is not True:
        raise RuntimeError("API is not ready")
    if not args.skip_streamlit:
        with urlopen(args.streamlit.rstrip("/") + "/_stcore/health", timeout=10) as response:
            if response.status != 200 or response.read().strip() != b"ok":
                raise RuntimeError("Streamlit health failed")
        with urlopen(args.streamlit, timeout=10) as response:
            if response.status != 200:
                raise RuntimeError("Streamlit root page failed")
    observed = {"question": QUESTION, "results": {}}
    fields = ("rank", "doc_id", "case_name", "citation", "decision_date",
              "source_pdf", "chunk_id", "excerpt")
    for mode in MODES:
        result = request_json(args.api, "/api/retrieve", {
            "question": QUESTION, "retrieval_mode": mode, "top_k": 5})
        records = result["results"]
        if result["count"] != 5 or len(records) != 5:
            raise RuntimeError(f"{mode}: expected five evidence records")
        if len({r["doc_id"] for r in records}) != 5:
            raise RuntimeError(f"{mode}: duplicate judgment IDs")
        if any(not r.get("chunk_id") or not r.get("excerpt") or not r.get("citation")
               for r in records):
            raise RuntimeError(f"{mode}: missing source traceability")
        observed["results"][mode] = [{k: r.get(k) for k in fields} for r in records]
        print(f"PASS: {mode}, five unique judgments with citations and excerpts")
    if args.compare_baseline:
        expected = json.loads(args.compare_baseline.read_text(encoding="utf-8"))
        if expected != observed:
            raise RuntimeError("Retrieval IDs/order/payloads differ from baseline; investigate, do not tune frozen benchmarks")
        print("PASS: all retrieved IDs, ranks and evidence metadata match baseline")
    if args.write_baseline:
        with args.write_baseline.open("x", encoding="utf-8") as stream:
            json.dump(observed, stream, indent=2, ensure_ascii=False)
        print("Saved new operational retrieval baseline")
    if args.generate:
        result = request_json(args.api, "/api/query", {"question": QUESTION})
        if not result.get("answer", "").strip() or not result.get("citations"):
            raise RuntimeError("Gemini response lacks answer or sources")
        print("PASS: real answer-generation endpoint returned nonempty answer and citations")
        print("This checks transport/output, not legal correctness or semantic support.")
    print("PASS: requested smoke checks completed; browser interaction is a separate manual check")


if __name__ == "__main__":
    main()
