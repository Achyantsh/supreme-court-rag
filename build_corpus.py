
import json
import re
from pathlib import Path

import pandas as pd
from pypdf import PdfReader

DATA_DIR = Path("data")
PDF_DIR = DATA_DIR / "pdfs"
INDEX_FILE = DATA_DIR / "english_2023_index.json"
METADATA_FILE = DATA_DIR / "selected_metadata.parquet"
OUTPUT_FILE = DATA_DIR / "judgments.jsonl"


def clean_text(text):
    """Clean extracted PDF text without removing paragraph breaks."""
    text = text.replace("\x00", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", text)
    return text.strip()


def safe_string(value):
    """Convert missing metadata values to empty strings."""
    if pd.isna(value):
        return ""
    return str(value).strip()


# Map metadata paths to their exact PDF filenames.
with INDEX_FILE.open(encoding="utf-8") as f:
    index = json.load(f)

pdf_by_path = {}

for part in index["parts"]:
    for filename in part["files"]:
        stem = Path(filename).stem
        if stem.endswith("_EN"):
            stem = stem[:-3]
        pdf_by_path[stem] = filename

metadata = pd.read_parquet(METADATA_FILE)

written = 0
skipped = []
total_chars = 0

# Write one JSON object per line.
with OUTPUT_FILE.open("w", encoding="utf-8") as output:
    for i, (_, row) in enumerate(metadata.iterrows(), start=1):
        path = safe_string(row.get("path", ""))
        filename = pdf_by_path.get(path)

        if not filename:
            skipped.append((path, "No matching PDF in index"))
            continue

        pdf_path = PDF_DIR / filename

        if not pdf_path.exists():
            skipped.append((path, "PDF file missing"))
            continue

        try:
            reader = PdfReader(str(pdf_path))

            text = "\n\n".join(
                page.extract_text() or ""
                for page in reader.pages
            )
            text = clean_text(text)

            # Avoid indexing empty or badly extracted documents.
            if len(text) < 500:
                skipped.append((path, f"Too little text: {len(text)} chars"))
                continue

            record = {
                "doc_id": path,
                "case_name": safe_string(row.get("title", "")),
                "citation": safe_string(row.get("citation", "")),
                "year": safe_string(row.get("year", "")),
                "decision_date": safe_string(
                    row.get("decision_date", "")
                ),
                "petitioner": safe_string(row.get("petitioner", "")),
                "respondent": safe_string(row.get("respondent", "")),
                "judges": safe_string(row.get("judge", "")),
                "text": text,
                "source_pdf": filename,
            }

            output.write(
                json.dumps(record, ensure_ascii=False) + "\n"
            )

            written += 1
            total_chars += len(text)

        except Exception as exc:
            skipped.append((path, f"PDF read error: {exc}"))

        if i % 100 == 0:
            print(f"Processed metadata records: {i}/{len(metadata)}")

print("\n--- Corpus extraction report ---")
print("Metadata records:", len(metadata))
print("Judgments extracted:", written)
print("Judgments skipped:", len(skipped))
print("Total text characters:", total_chars)
print("Output:", OUTPUT_FILE.resolve())

if written:
    print("Average characters per judgment:", total_chars // written)

if skipped:
    print("\nFirst 10 skipped records:")
    for item in skipped[:10]:
        print(item)
