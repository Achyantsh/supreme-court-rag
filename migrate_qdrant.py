"""Offline-copy export and conservative, resumable Qdrant server migration.

No models are loaded. Export opens ONLY a temporary copy of local storage.
Stop all local users before export, and all destination writers before import
(or verification). Qdrant has no atomic insert-if-absent API: the operator must
keep writers stopped throughout migration. Interrupted imports are resumable;
divergence requires investigation, never deletion or automatic repair.

Count, IDs and canonical JSON payloads must match exactly. Vector verification
allows float32 COSINE normalization roundoff, NOT bit-exact equality: every
coordinate must satisfy math.isclose(rel_tol=1e-6, abs_tol=1e-7), AND the vector
L2 difference must be <= 1e-6. Vectors are never renormalized by this tool; unit
norm is not required. Material drift is refused, never automatically repaired.
JSONL files contain sensitive judgment text/payloads: protect their permissions.
"""

import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import uuid

from qdrant_client import QdrantClient, models

COLLECTION = "supreme_court_2023"
DIMENSIONS = 384
EXPECTED_COUNT = 21451
MAX_BATCH_SIZE = 256
# Both coordinate and whole-vector bounds apply; these are not CLI-adjustable.
VECTOR_REL_TOL = 1e-6
VECTOR_ABS_TOL = 1e-7
VECTOR_L2_TOL = 1e-6


class MigrationError(RuntimeError):
    """Unsafe or inconsistent migration input/state."""


def require(condition, message):
    if not condition:
        raise MigrationError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":"))


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_constant(value):
    raise MigrationError(f"Non-finite JSON number: {value}")


def json_records(path):
    with Path(path).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line, object_pairs_hook=unique_object,
                                    parse_constant=reject_constant)
                require(isinstance(record, dict), "Record must be an object")
                canonical(record)  # Also rejects overflowing floats such as 1e999.
            except (ValueError, TypeError, MigrationError) as error:
                raise MigrationError(f"{path}:{line_number}: {error}") from error
            yield record


def validate_options(expect_count, batch_size):
    require(expect_count > 0, "Expected count must be positive")
    require(1 <= batch_size <= MAX_BATCH_SIZE,
            f"Batch size must be between 1 and {MAX_BATCH_SIZE}")


def load_chunks(path, expect_count):
    chunks = {}
    for payload in json_records(path):
        chunk_id = payload.get("chunk_id")
        require(isinstance(chunk_id, str) and bool(chunk_id),
                "Every chunk needs a nonempty string chunk_id")
        point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))
        require(point_id not in chunks, f"Duplicate chunk/ID: {chunk_id}")
        chunks[point_id] = payload
    require(len(chunks) == expect_count,
            f"Chunks count {len(chunks)} != expected {expect_count}")
    return chunks


def validate_point(point, chunks):
    require(set(point) == {"id", "payload", "vector"},
            "Point must contain exactly id, payload, vector")
    point_id = point["id"]
    require(isinstance(point_id, str) and point_id in chunks,
            f"Unexpected or noncanonical point ID: {point_id}")
    require(canonical(point["payload"]) == canonical(chunks[point_id]),
            f"Payload mismatch for {point_id}")
    vector = point["vector"]
    require(isinstance(vector, list) and len(vector) == DIMENSIONS,
            f"Vector for {point_id} must have {DIMENSIONS} dimensions")
    require(all(type(value) in (int, float) and math.isfinite(value)
                for value in vector), f"Invalid/non-finite vector for {point_id}")
    return point


def load_export(path, chunks):
    points = {}
    for point in json_records(path):
        validate_point(point, chunks)
        require(point["id"] not in points, f"Duplicate point ID: {point['id']}")
        points[point["id"]] = point
    require(points.keys() == chunks.keys(), "Export IDs/count do not match all chunks")
    return points


def record_dict(record):
    # Qdrant may expose UUID objects, but never accept integer IDs as UUIDs.
    point_id = str(record.id) if isinstance(record.id, uuid.UUID) else record.id
    return {"id": point_id, "payload": record.payload, "vector": record.vector}


def check_collection(client, collection):
    info = client.get_collection(collection_name=collection)
    vectors = info.config.params.vectors
    require(isinstance(vectors, models.VectorParams),
            "Collection must have one unnamed dense vector")
    require(vectors.size == DIMENSIONS and vectors.distance == models.Distance.COSINE,
            "Collection must use 384-dimensional COSINE vectors")
    require(vectors.datatype in (None, models.Datatype.FLOAT32),
            "Collection must store float32 vectors without datatype conversion")


def scroll_points(client, collection, batch_size):
    offset = None
    cursors = set()
    while True:
        records, next_offset = client.scroll(
            collection_name=collection, limit=batch_size, offset=offset,
            with_payload=True, with_vectors=True)
        for record in records:
            yield record_dict(record)
        if next_offset is None:
            break
        token = str(next_offset)
        require(token not in cursors and bool(records), "Invalid/repeating scroll cursor")
        cursors.add(token)
        offset = next_offset


def exact_count(client, collection):
    return client.count(collection_name=collection, exact=True).count


def match_point(point, expected, chunks):
    validate_point(point, chunks)
    reference = expected[point["id"]]
    vector = point["vector"]
    source_vector = reference["vector"]
    mismatch = next((index for index, (actual, source) in enumerate(zip(vector, source_vector))
                     if not math.isclose(actual, source, rel_tol=VECTOR_REL_TOL,
                                         abs_tol=VECTOR_ABS_TOL)), None)
    l2_difference = math.dist(vector, source_vector)
    require(mismatch is None and l2_difference <= VECTOR_L2_TOL,
            f"Vector mismatch for {point['id']}: first failing coordinate={mismatch}; "
            f"L2 difference={l2_difference:.9g}. Required: every coordinate "
            f"math.isclose(rel_tol={VECTOR_REL_TOL:g}, abs_tol={VECTOR_ABS_TOL:g}) "
            f"AND L2 difference <= {VECTOR_L2_TOL:g}. Inspect the export, destination "
            "vector configuration and concurrent writers before retrying; "
            "no points were deleted or automatically repaired.")


def inspect_destination(client, collection, points, chunks, batch_size, complete):
    check_collection(client, collection)
    before = exact_count(client, collection)
    require(before <= len(points), "Destination contains too many points")
    seen = set()
    for point in scroll_points(client, collection, batch_size):
        match_point(point, points, chunks)
        require(point["id"] not in seen, f"Duplicate destination ID: {point['id']}")
        seen.add(point["id"])
    after = exact_count(client, collection)
    require(before == after == len(seen), "Destination changed during inspection/count mismatch")
    if complete:
        require(seen == points.keys(), "Destination is incomplete: IDs/count mismatch")
    return seen


def remote_migration(client, points, chunks, collection=COLLECTION, batch_size=64,
                     verify_only=False):
    """Caller must exclusively control destination writes for the whole call."""
    validate_options(len(chunks), batch_size)
    require(points.keys() == chunks.keys(), "Export IDs/count do not match all chunks")
    for point in points.values():
        validate_point(point, chunks)
    exists = client.collection_exists(collection_name=collection)
    if verify_only:
        require(exists, "Destination collection is absent")
        inspect_destination(client, collection, points, chunks, batch_size, complete=True)
        return len(points)
    if exists:
        # Check the ENTIRE existing dataset before issuing any write.
        seen = inspect_destination(client, collection, points, chunks, batch_size,
                                   complete=False)
    else:
        client.create_collection(
            collection_name=collection,
            vectors_config=models.VectorParams(size=DIMENSIONS, distance=models.Distance.COSINE))
        check_collection(client, collection)
        seen = set()
    missing = [point_id for point_id in points if point_id not in seen]
    for start in range(0, len(missing), batch_size):
        ids = missing[start:start + batch_size]
        existing = client.retrieve(collection_name=collection, ids=ids,
                                   with_payload=True, with_vectors=True)
        found = set()
        for record in existing:
            point = record_dict(record)
            require(point["id"] in ids, "Retrieve returned an unrequested ID")
            match_point(point, points, chunks)
            require(point["id"] not in found, "Retrieve returned a duplicate ID")
            found.add(point["id"])
        batch = [models.PointStruct(**points[point_id]) for point_id in ids
                 if point_id not in found]
        if batch:
            client.upsert(collection_name=collection, points=batch, wait=True)
    inspect_destination(client, collection, points, chunks, batch_size, complete=True)
    return len(points)


def is_storage_link(path):
    # st_file_attributes also covers Windows junctions on Python < 3.12.
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    return path.is_symlink() or bool(
        attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def source_hashes(source):
    """Hash every regular source file, including .lock; reject links/junctions."""
    require(source.is_dir(), f"Missing storage directory: {source}")
    hashes = {}
    for root, directories, files in os.walk(source, followlinks=False):
        for name in directories + files:
            path = Path(root) / name
            require(not is_storage_link(path),
                    f"Links/junctions are not safe migration inputs: {path}")
        for name in files:
            path = Path(root) / name
            require(path.is_file(), f"Not a regular source file: {path}")
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            hashes[str(path.relative_to(source))] = digest.hexdigest()
    require("meta.json" in hashes and ".lock" in hashes,
            "Expected existing Qdrant meta.json and .lock; will not create them")
    return hashes


@contextmanager
def stopped_source_lock(source):
    # Never open this file in append/write mode (even if it is missing).
    import portalocker

    with (source / ".lock").open("rb") as stream:
        try:
            portalocker.lock(stream, portalocker.LOCK_EX | portalocker.LOCK_NB)
        except portalocker.exceptions.LockException as error:
            raise MigrationError("Local backend is active/locked; stop it before export") from error
        try:
            yield
        finally:
            portalocker.unlock(stream)


def export_local(source, chunks_path, output, *, local_backend_stopped=False,
                 expect_count=EXPECTED_COUNT, collection=COLLECTION, batch_size=64,
                 client_factory=QdrantClient):
    validate_options(expect_count, batch_size)
    require(local_backend_stopped,
            "Stop all local backend users and pass --local-backend-stopped")
    raw_source = Path(source).absolute()
    require(not is_storage_link(raw_source),
            "Source directory must not be a link/junction")
    source = raw_source.resolve()
    output = Path(output).absolute()
    require(not output.is_symlink() and not output.exists(),
            f"Export output already exists: {output}")
    require(output.parent.is_dir(), "Export parent directory must already exist")
    require(not output.resolve().is_relative_to(source), "Export must be outside source storage")
    require(output.resolve() != Path(chunks_path).resolve(), "Export cannot replace chunks")
    chunks = load_chunks(chunks_path, expect_count)
    before = source_hashes(source)
    stage = None
    try:
        try:
            with stopped_source_lock(source):
                with tempfile.TemporaryDirectory(prefix="qdrant-migration-") as temporary:
                    copy = Path(temporary) / "storage"
                    require(not copy.resolve().is_relative_to(source),
                            "Temporary copy must be outside original storage")
                    shutil.copytree(source, copy, ignore=shutil.ignore_patterns(".lock"))
                    client = client_factory(path=str(copy))
                    try:
                        require(client.collection_exists(collection_name=collection),
                                "Source collection is absent")
                        check_collection(client, collection)
                        require(exact_count(client, collection) == expect_count,
                                "Source count does not match expected count")
                        descriptor, name = tempfile.mkstemp(prefix=".qdrant-export-",
                                                            dir=output.parent)
                        stage = Path(name)
                        seen = set()
                        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                            for point in scroll_points(client, collection, batch_size):
                                validate_point(point, chunks)
                                require(point["id"] not in seen,
                                        f"Duplicate source ID: {point['id']}")
                                seen.add(point["id"])
                                stream.write(canonical(point) + "\n")
                            stream.flush()
                            os.fsync(stream.fileno())
                        require(seen == chunks.keys(), "Source IDs/count do not match chunks")
                        require(exact_count(client, collection) == expect_count,
                                "Source copy count changed during export")
                    finally:
                        client.close()
        finally:
            # Release the source lock first: Windows denies reads through other
            # handles while an exclusive byte-range lock is held.
            require(source_hashes(source) == before,
                    "Original source files changed during export; output NOT published")
        # Atomic no-clobber publication. Unlike replace/rename, this can never
        # overwrite a destination created by another process during export.
        os.link(stage, output)
        return expect_count
    finally:
        if stage is not None:
            stage.unlink(missing_ok=True)


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    for command in ("export", "import", "verify"):
        sub = commands.add_parser(command)
        sub.add_argument("--chunks", type=Path, default=Path("data/chunks.jsonl"))
        sub.add_argument("--collection", default=COLLECTION)
        sub.add_argument("--expect-count", type=int, default=EXPECTED_COUNT)
        sub.add_argument("--batch-size", type=int, default=64)
        if command == "export":
            sub.add_argument("--source", type=Path, default=Path("qdrant_storage"))
            sub.add_argument("--output", type=Path, default=Path("data/qdrant_server_export.jsonl"))
            sub.add_argument("--local-backend-stopped", action="store_true", required=True,
                             help="Confirm all local backend users are stopped")
        else:
            sub.add_argument("--file", type=Path, default=Path("data/qdrant_server_export.jsonl"))
            sub.add_argument("--url", required=True, help="Remote Qdrant HTTP(S) URL")
            sub.add_argument("--destination-writes-stopped", action="store_true", required=True,
                             help="Confirm exclusive destination access for a stable migration")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        validate_options(args.expect_count, args.batch_size)
        if args.command == "export":
            count = export_local(args.source, args.chunks, args.output,
                                 local_backend_stopped=args.local_backend_stopped,
                                 expect_count=args.expect_count, collection=args.collection,
                                 batch_size=args.batch_size)
        else:
            from urllib.parse import urlsplit

            url = urlsplit(args.url)
            require(url.scheme in ("http", "https") and bool(url.hostname),
                    "--url must be an HTTP(S) server URL, never a local storage path")
            chunks = load_chunks(args.chunks, args.expect_count)
            points = load_export(args.file, chunks)
            client = QdrantClient(url=args.url, api_key=os.environ.get("QDRANT_API_KEY"),
                                  timeout=60)
            try:
                count = remote_migration(client, points, chunks, collection=args.collection,
                                         batch_size=args.batch_size,
                                         verify_only=args.command == "verify")
            finally:
                client.close()
        vector_status = (
            "finite 384D vectors exported unchanged" if args.command == "export" else
            "vectors verified with bounded tolerance, not bit-exact "
            f"(coordinate rel_tol={VECTOR_REL_TOL:g}, abs_tol={VECTOR_ABS_TOL:g}; "
            f"L2 difference <= {VECTOR_L2_TOL:g})")
        print(f"{args.command}: validated {count} points in {args.collection}; "
              f"exact count/IDs/payload; {vector_status}")
        return 0
    except Exception as error:
        # Network/upsert failures may leave a valid partial import. Never delete it.
        print(f"Migration refused/failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
