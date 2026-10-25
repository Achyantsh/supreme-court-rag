
from pathlib import Path

import pandas as pd
import requests

url = (
    "https://indian-supreme-court-judgments.s3.amazonaws.com/"
    "metadata/parquet/year=2023/metadata.parquet"
)

output = Path("data/metadata_2023.parquet")
output.parent.mkdir(parents=True, exist_ok=True)

if not output.exists():
    print("Downloading 2023 metadata...")

    with requests.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()

        with output.open("wb") as file:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    file.write(chunk)

    print("Download complete!")

df = pd.read_parquet(output)

print("\nTotal records:", len(df))
print("\nColumns:")
print(df.columns.tolist())

for column in [
    "title",
    "citation",
    "decision_date",
    "available_languages",
    "path",
    "raw_html",
]:
    if column in df.columns:
        values = df[column].dropna()
        print(f"\n{column}:")
        if not values.empty:
            sample = str(values.iloc[0])
            print(sample[:300])
        else:
            print("No non-empty values")
