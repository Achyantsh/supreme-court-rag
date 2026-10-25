
import json
import shutil
import tarfile
from pathlib import Path

import pandas as pd
import requests

BASE_URL = (
    "https://indian-supreme-court-judgments.s3.amazonaws.com"
)

DATA_DIR = Path("data")
INDEX_FILE = DATA_DIR / "english_2023_index.json"
METADATA_FILE = DATA_DIR / "metadata_2023.parquet"
ARCHIVE_FILE = DATA_DIR / "english_2023.tar"
PDF_DIR = DATA_DIR / "pdfs"

DATA_DIR.mkdir(exist_ok=True)
PDF_DIR.mkdir(exist_ok=True)

# 1. Load the previously downloaded index and metadata.
with INDEX_FILE.open(encoding="utf-8") as f:
    index = json.load(f)

df = pd.read_parquet(METADATA_FILE)

pdf_names = [
    filename
    for part in index["parts"]
    for filename in part["files"]
]

# Convert PDF filenames to the metadata path format.
pdf_by_path = {
    Path(name).stem.removesuffix("_EN"): name
    for name in pdf_names
}

matched = df[
    df["path"].fillna("").astype(str).isin(pdf_by_path)
].copy()

selected = matched.sample(
    n=min(800, len(matched)),
    random_state=42,
)

print("Matched judgments:", len(matched))
print("Selected judgments:", len(selected))

# 2. Download the 382 MB archive only once.
if not ARCHIVE_FILE.exists():
    url = (
        f"{BASE_URL}/data/tar/year=2023/"
        "english/english.tar"
    )

    temp_file = ARCHIVE_FILE.with_suffix(".tar.part")
    temp_file.unlink(missing_ok=True)

    print("\nDownloading English judgments archive...")

    downloaded = 0

    try:
        with requests.get(
            url, stream=True, timeout=(30, 120)
        ) as response:
            response.raise_for_status()

            with temp_file.open("wb") as f:
                for chunk in response.iter_content(
                    chunk_size=1024 * 1024
                ):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

                        if downloaded % (20 * 1024 * 1024) < len(chunk):
                            print(
                                f"Downloaded "
                                f"{downloaded / (1024**2):.0f} MB"
                            )

        temp_file.replace(ARCHIVE_FILE)

    except Exception:
        temp_file.unlink(missing_ok=True)
        raise

    print("Archive download complete!")
else:
    print("\nArchive already exists; skipping download.")

# 3. Extract only the selected PDFs.
print("\nOpening archive...")

with tarfile.open(ARCHIVE_FILE, mode="r:") as archive:
    members_by_name = {
        Path(member.name).name: member
        for member in archive.getmembers()
        if member.isfile()
    }

    selected_names = [
        pdf_by_path[str(path)]
        for path in selected["path"]
    ]

    missing = [
        name for name in selected_names
        if name not in members_by_name
    ]

    if missing:
        raise RuntimeError(
            f"{len(missing)} selected PDFs were not found "
            f"in the archive. Example: {missing[:3]}"
        )

    for i, filename in enumerate(selected_names, start=1):
        output = PDF_DIR / filename

        if output.exists() and output.stat().st_size > 0:
            continue

        source = archive.extractfile(
            members_by_name[filename]
        )

        if source is None:
            raise RuntimeError(f"Could not read {filename}")

        with source, output.open("wb") as dest:
            shutil.copyfileobj(source, dest)

        if i % 100 == 0:
            print(f"Processed {i}/{len(selected_names)} PDFs")

# Save the exact metadata selection so the next step uses
# these same 800 judgments.
selected.to_parquet(
    DATA_DIR / "selected_metadata.parquet",
    index=False,
)

print("\nSUCCESS!")
print("PDF folder:", PDF_DIR.resolve())
print("PDF count:", len(list(PDF_DIR.glob("*.pdf"))))
print("Metadata: data/selected_metadata.parquet")
