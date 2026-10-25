
import json
import uuid
from pathlib import Path

from fastembed import TextEmbedding
from qdrant_client import QdrantClient, models

CHUNKS_FILE = Path("data/chunks.jsonl")
DB_PATH = Path("qdrant_storage")
COLLECTION = "supreme_court_2023"
MODEL_NAME = "BAAI/bge-small-en-v1.5"

# Small batches keep memory usage manageable.
BATCH_SIZE = 32


def load_batch(file, size):
    """Read chunks incrementally instead of loading all text into RAM."""
    batch = []

    for line in file:
        if line.strip():
            batch.append(json.loads(line))

        if len(batch) >= size:
            yield batch
            batch = []

    if batch:
        yield batch


def main():
    if not CHUNKS_FILE.exists():
        raise FileNotFoundError(
            f"Chunks file not found: {CHUNKS_FILE}"
        )

    DB_PATH.mkdir(parents=True, exist_ok=True)

    # Count expected records.
    with CHUNKS_FILE.open(encoding="utf-8") as file:
        expected_count = sum(
            1 for line in file if line.strip()
        )

    print("Chunks to index:", expected_count)
    print("Loading embedding model:", MODEL_NAME)
    print("The first run may download the model.")

    embedding_model = TextEmbedding(
        model_name=MODEL_NAME
    )

    # Qdrant local mode: database persists on disk.
    client = QdrantClient(path=str(DB_PATH.resolve()))

    try:
        if client.collection_exists(COLLECTION):
            current_count = client.count(
                collection_name=COLLECTION,
                exact=True,
            ).count

            if current_count == expected_count:
                print(
                    f"Collection already has {current_count} "
                    "points. Nothing to do."
                )
                return

            print(
                "Existing incomplete collection found. "
                "Rebuilding it from scratch."
            )
            client.delete_collection(COLLECTION)

        client.create_collection(
            collection_name=COLLECTION,
            vectors_config=models.VectorParams(
                size=384,
                distance=models.Distance.COSINE,
            ),
        )

        processed = 0

        with CHUNKS_FILE.open(
            encoding="utf-8"
        ) as file:
            for batch in load_batch(file, BATCH_SIZE):
                texts = [record["text"] for record in batch]

                embeddings = list(
                    embedding_model.embed(
                        texts,
                        batch_size=BATCH_SIZE,
                    )
                )

                points = []

                for record, vector in zip(batch, embeddings):
                    # Stable ID makes re-indexing deterministic.
                    point_id = str(
                        uuid.uuid5(
                            uuid.NAMESPACE_URL,
                            record["chunk_id"],
                        )
                    )

                    points.append(
                        models.PointStruct(
                            id=point_id,
                            vector=vector.tolist(),
                            payload=record,
                        )
                    )

                client.upsert(
                    collection_name=COLLECTION,
                    points=points,
                    wait=True,
                )

                processed += len(batch)

                if processed % 320 < len(batch):
                    print(
                        f"Indexed {processed}/"
                        f"{expected_count} chunks"
                    )

        final_count = client.count(
            collection_name=COLLECTION,
            exact=True,
        ).count

        print("\n--- INDEXING REPORT ---")
        print("Expected chunks:", expected_count)
        print("Stored Qdrant points:", final_count)
        print("Collection:", COLLECTION)
        print("Embedding model:", MODEL_NAME)
        print("Database folder:", DB_PATH.resolve())

        if final_count != expected_count:
            raise RuntimeError(
                "Point count does not match chunk count."
            )

        print("\nSUCCESS: All chunks indexed!")

    finally:
        client.close()


if __name__ == "__main__":
    main()
