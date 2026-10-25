
import json
from pathlib import Path

import pandas as pd
import requests

BASE_URL = (
    "https://indian-supreme-court-judgments.s3.amazonaws.com"
)

index_url = (
    f"{BASE_URL}/data/tar/year=2023/"
    "english/english.index.json"
)

print("Downloading the small PDF index...")

response = requests.get(index_url, timeout=60)
response.raise_for_status()

index = response.json()

Path("data/english_2023_index.json").write_text(
    json.dumps(index, indent=2),
    encoding="utf-8",
)

# Read filenames listed inside the index.
filenames = []

for part in index.get("parts", []):
    filenames.extend(part.get("files", []))

if not filenames:
    filenames = index.get("files", [])

print("\nIndex keys:", list(index.keys()))
print("Indexed PDF filenames:", len(filenames))

print("\nFirst 5 PDF filenames:")
for filename in filenames[:5]:
    print(filename)

# Compare PDF filenames with the metadata paths.
df = pd.read_parquet("data/metadata_2023.parquet")

english = df[
    df["available_languages"]
    .fillna("")
    .astype(str)
    .str.contains("ENG")
]

pdf_stems = {
    Path(str(filename)).stem.removesuffix("_EN")
    for filename in filenames
}

paths = english["path"].dropna().astype(str)

print("\nMetadata records:", len(df))
print("Records with English available:", len(english))
print("Sample metadata path:", paths.iloc[0])
print(
    "Metadata paths matching PDF index:",
    sum(path in pdf_stems for path in paths),
    "/",
    len(paths),
)
