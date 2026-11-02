"""Generate a fixed Hybrid RRF answer-quality review set through the local API."""

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import openpyxl
import requests
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

METHOD = "hybrid_rrf"
DEFAULT_MODEL = "gemini-2.5-flash"
SDK_VERSION = "2.33.0"
MAX_ATTEMPTS = 3
RETRYABLE_STATUS_CODES = {500, 502, 503, 504}
REVIEW_COLUMNS = [
    "Question ID", "Topic", "Question", "Generated answer", "Model",
    "Retrieved judgment IDs", "Cited case names/citations", "Evidence excerpts",
    "Generation status", "Generation error",
    "Citation validation",
    "Answer correctness (0/1/2)", "Citation support (0/1/2)",
    "Answer completeness (0/1/2)", "Review notes",
]
DEFAULT_OUTPUT = Path("reports/answer_evaluation_v1.jsonl")
DEFAULT_WORKBOOK = Path("reports/answer_review_v1.xlsx")


def create_review_workbook(records: list[dict], output: Path) -> None:
    workbook = Workbook()
    instructions = workbook.active
    instructions.title = "Instructions"
    instructions.append(["ANSWER QUALITY REVIEW — HELD-OUT QUESTIONS"])
    instructions.append(["All human-review columns are intentionally blank. An LLM output is not ground truth."])
    instructions.append(["Answer correctness: 0 = materially wrong/unsupported; 1 = partly correct or incomplete; 2 = correct and grounded."])
    instructions.append(["Citation support: 0 = cited case is not supported by its retrieved excerpt; 1 = partially supported/ambiguous; 2 = directly supported."])
    instructions.append(["Answer completeness: 0 = fails to address the question; 1 = addresses some issues; 2 = sufficiently addresses the question from evidence."])
    instructions.append(["Review every cited proposition against the exact evidence excerpt and the original judgment when needed."])
    sheet = workbook.create_sheet("Answer Review")
    sheet.append(REVIEW_COLUMNS)
    for record in records:
        citations = record["answer_response"].get("citations") or []
        generation_error = record.get("generation_error", "")
        if isinstance(generation_error, (dict, list)):
            generation_error = json.dumps(generation_error, ensure_ascii=False)
        cited = [
            {"case_name": citation.get("case_name"), "citation": citation.get("citation")}
            for citation in citations
        ]
        evidence = [
            {
                "doc_id": item.get("doc_id"),
                "case_name": item.get("case_name"),
                "citation": item.get("citation"),
                "excerpt": item.get("excerpt"),
            }
            for item in record["retrieval_response"].get("results", [])
        ]
        sheet.append([
            record["question_id"], record["topic"], record["question"],
            record["answer_response"].get("answer", ""),
            record.get("model") or record["answer_response"].get("model") or DEFAULT_MODEL,
            json.dumps([item.get("doc_id") for item in evidence], ensure_ascii=False),
            json.dumps(cited, ensure_ascii=False),
            json.dumps(evidence, ensure_ascii=False),
            record.get("generation_status", ""),
            generation_error,
            json.dumps(
                record["answer_response"].get("grounding_validation"),
                ensure_ascii=False,
            ) if record["answer_response"].get("grounding_validation") else "",
            "", "", "", "",
        ])
    for cell in sheet[1]:
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = PatternFill("solid", fgColor="1F497D")
        cell.alignment = Alignment(wrap_text=True)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for row in sheet.iter_rows():
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    widths = {"A": 12, "B": 24, "C": 48, "D": 75, "E": 22, "F": 40, "G": 55, "H": 100, "I": 18, "J": 55, "K": 24, "L": 24, "M": 22, "N": 26, "O": 40}
    for column, width in widths.items():
        sheet.column_dimensions[column].width = width
    output.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output)


def response_error(response: requests.Response, elapsed: float) -> dict:
    try:
        body = response.json()
    except ValueError:
        body = response.text[:2000]
    return {
        "http_status": response.status_code,
        "upstream_status": response.headers.get("X-Upstream-Status"),
        "body": body,
        "elapsed_seconds": round(elapsed, 3),
    }


def should_retry(response: requests.Response) -> bool:
    upstream_status = response.headers.get("X-Upstream-Status")
    try:
        effective_status = int(upstream_status) if upstream_status else response.status_code
    except ValueError:
        effective_status = response.status_code
    if effective_status in RETRYABLE_STATUS_CODES:
        return True
    if effective_status == 429:
        retry_after = response.headers.get("Retry-After")
        try:
            return retry_after is not None and float(retry_after) <= 30
        except ValueError:
            return False
    return False


def generate_with_retries(session: requests.Session, url: str, payload: dict) -> tuple[requests.Response | None, dict | None]:
    last_error = None
    for attempt in range(MAX_ATTEMPTS):
        started = time.perf_counter()
        try:
            response = session.post(url, json=payload, timeout=300)
        except requests.RequestException as exc:
            last_error = {
                "exception_type": type(exc).__name__,
                "message": str(exc)[:2000],
                "elapsed_seconds": round(time.perf_counter() - started, 3),
            }
            if attempt + 1 < MAX_ATTEMPTS:
                time.sleep(2**attempt)
                continue
            return None, last_error
        if response.ok:
            return response, None
        last_error = response_error(response, time.perf_counter() - started)
        if not should_retry(response) or attempt + 1 == MAX_ATTEMPTS:
            return response, last_error
        time.sleep(2**attempt)
    return None, last_error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, default=Path("data/eval_questions_heldout_approved_v1.json"))
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--answer-version", choices=("v1", "v2"), default="v1")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workbook", type=Path, default=DEFAULT_WORKBOOK)
    parser.add_argument("--evidence-source", type=Path, default=Path("reports/answer_evaluation_v1.jsonl"))
    parser.add_argument("--smoke", action="store_true", help="Run one configured-model smoke test before evaluation.")
    args = parser.parse_args()
    if args.answer_version == "v2":
        if args.output == DEFAULT_OUTPUT:
            args.output = Path("data/answer_evaluation_3_1_flash_lite_v2_dev.jsonl")
        if args.workbook == DEFAULT_WORKBOOK:
            args.workbook = Path("data/answer_review_3_1_flash_lite_v2_dev.xlsx")

    questions = json.loads(args.questions.read_text(encoding="utf-8"))
    run_started = datetime.now(timezone.utc).isoformat()
    records = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    records_by_id = {}
    if args.output.exists():
        with args.output.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    record = json.loads(line)
                    if "generation_status" not in record:
                        record["generation_status"] = "success" if record.get("answer_response", {}).get("answer") else "failed"
                        record["generation_error"] = ""
                    records_by_id[record["question_id"]] = record
    evidence_by_id = {}
    if args.evidence_source.exists() and args.evidence_source != args.output:
        with args.evidence_source.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    record = json.loads(line)
                    retrieval_response = record.get("retrieval_response")
                    if retrieval_response and retrieval_response.get("results"):
                        evidence_by_id[record["question_id"]] = retrieval_response
    session = requests.Session()
    if args.smoke:
        smoke_question = questions[0]
        smoke_payload = {
            "question": smoke_question["question"],
            "retrieval_mode": METHOD,
            "top_k": 5,
            "model": args.model,
            "evidence": evidence_by_id[smoke_question["id"]]["results"],
            "answer_version": args.answer_version,
        }
        smoke_response, smoke_error = generate_with_retries(
            session, f"{args.api.rstrip('/')}/api/query", smoke_payload
        )
        if smoke_response is None or not smoke_response.ok:
            print(f"Smoke test failed for model={args.model}: {json.dumps(smoke_error, ensure_ascii=False)}")
            return
        print(f"Smoke test succeeded for model={args.model}")
    for index, question in enumerate(questions, start=1):
        existing = records_by_id.get(question["id"])
        if (
            existing
            and existing.get("generation_status") == "success"
            and existing.get("model") == args.model
            and existing.get("answer_version", "v1") == args.answer_version
        ):
            print(f"[{index:02d}/{len(questions)}] {question['id']} already saved")
            continue
        if existing and existing.get("model") not in (None, args.model):
            existing = None
        if existing and existing.get("generation_status") == "success":
            print(f"[{index:02d}/{len(questions)}] {question['id']} already saved")
            continue
        retrieval_data = existing.get("retrieval_response") if existing else evidence_by_id.get(question["id"])
        retrieval_error = None
        if not retrieval_data or not retrieval_data.get("results"):
            retrieval_payload = {
                "question": question["question"],
                "retrieval_mode": METHOD,
                "top_k": 5,
            }
            retrieval, retrieval_error = generate_with_retries(
                session, f"{args.api.rstrip('/')}/api/retrieve", retrieval_payload
            )
            if retrieval is not None and retrieval.ok:
                retrieval_data = retrieval.json()
        payload = {
            "question": question["question"],
            "retrieval_mode": METHOD,
            "top_k": 5,
            "model": args.model,
            "evidence": retrieval_data["results"] if retrieval_data else [],
            "answer_version": args.answer_version,
        }
        if retrieval_error or not retrieval_data or not retrieval_data.get("results"):
            record = {
                "question_id": question["id"], "topic": question["topic"],
                "question": question["question"], "retrieval_mode": METHOD,
                "top_k": 5, "run_started_utc": run_started, "run_index": index,
                "sdk": {"google-genai": SDK_VERSION}, "model": args.model,
                "retrieval_response": retrieval_data or {"results": []},
                "answer_response": {}, "generation_status": "failed",
                "generation_error": {"stage": "retrieval", "error": retrieval_error},
                "answer_version": args.answer_version,
            }
        else:
            answer, answer_error = generate_with_retries(
                session, f"{args.api.rstrip('/')}/api/query", payload
            )
            if answer is not None and answer.ok:
                record = {
                    "question_id": question["id"], "topic": question["topic"],
                    "question": question["question"], "retrieval_mode": METHOD,
                    "top_k": 5, "run_started_utc": run_started, "run_index": index,
                    "sdk": {"google-genai": SDK_VERSION}, "model": args.model,
                    "retrieval_response": retrieval_data,
                    "answer_response": answer.json(), "generation_status": "success",
                    "generation_error": "",
                    "answer_version": args.answer_version,
                }
            else:
                record = {
                    "question_id": question["id"], "topic": question["topic"],
                    "question": question["question"], "retrieval_mode": METHOD,
                    "top_k": 5, "run_started_utc": run_started, "run_index": index,
                    "sdk": {"google-genai": SDK_VERSION}, "model": args.model,
                    "retrieval_response": retrieval_data,
                    "answer_response": {}, "generation_status": "failed",
                    "generation_error": {"stage": "generation", "error": answer_error},
                    "answer_version": args.answer_version,
                }
        records_by_id[question["id"]] = record
        checkpoint_records = [
            records_by_id[question_item["id"]]
            for question_item in questions
            if question_item["id"] in records_by_id
        ]
        with args.output.open("w", encoding="utf-8") as handle:
            for checkpoint_record in checkpoint_records:
                handle.write(json.dumps(checkpoint_record, ensure_ascii=False) + "\n")
        print(f"[{index:02d}/{len(questions)}] {question['id']} {record['generation_status']}")
    records = [records_by_id[question["id"]] for question in questions if question["id"] in records_by_id]
    with args.output.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    create_review_workbook(records, args.workbook)
    print(f"Wrote {len(records)} answer records to {args.output}")
    print(f"Wrote blank human-review workbook to {args.workbook}")


if __name__ == "__main__":
    main()
