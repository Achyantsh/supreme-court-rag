import json
from pathlib import Path

INPUT_FILE = Path("data/judgments.jsonl")
OUTPUT_FILE = Path("data/chunks.jsonl")

CHUNK_SIZE = 2200
OVERLAP = 250


def split_into_chunks(text):
    text = text.strip()
    start = 0
    chunk_index = 0

    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))

        if end < len(text):
            # Prefer natural boundaries in the latter part
            # of each chunk, if a suitable boundary exists.
            minimum_break = start + int(CHUNK_SIZE * 0.65)

            candidates = [
                text.rfind("\n\n", minimum_break, end),
                text.rfind("\n", minimum_break, end),
                text.rfind(". ", minimum_break, end),
                text.rfind("; ", minimum_break, end),
            ]

            boundary = max(candidates)

            if boundary > minimum_break:
                end = boundary + 1

        chunk_text = text[start:end].strip()

        if len(chunk_text) >= 100:
            yield chunk_index, chunk_text

        if end >= len(text):
            break

        # The overlap preserves context across adjacent chunks.
        start = max(end - OVERLAP, start + 1)
        chunk_index += 1


OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

document_count = 0
chunk_count = 0
total_chunk_chars = 0

print("Starting chunking...\n")

with INPUT_FILE.open(encoding="utf-8") as source, \
     OUTPUT_FILE.open("w", encoding="utf-8") as output:

    for line in source:
        if not line.strip():
            continue

        document = json.loads(line)
        document_count += 1

        for index, chunk_text in split_into_chunks(document["text"]):
            chunk = {
                "chunk_id": f'{document["doc_id"]}:{index}',
                "doc_id": document["doc_id"],
                "chunk_index": index,
                "case_name": document["case_name"],
                "citation": document["citation"],
                "year": document["year"],
                "decision_date": document["decision_date"],
                "source_pdf": document["source_pdf"],
                "text": chunk_text,
            }

            output.write(
                json.dumps(chunk, ensure_ascii=False) + "\n"
            )

            chunk_count += 1
            total_chunk_chars += len(chunk_text)

        if document_count % 100 == 0:
            print(
                f"Processed {document_count}/800 judgments; "
                f"chunks created: {chunk_count}"
            )

print("\n--- CHUNKING REPORT ---")
print("Judgments processed:", document_count)
print("Chunks created:", chunk_count)
print("Average chunk characters:",
      total_chunk_chars // max(chunk_count, 1))
print("Output file:", OUTPUT_FILE.resolve())
print(
    "Output size (MB):",
    round(OUTPUT_FILE.stat().st_size / (1024 * 1024), 2),
)