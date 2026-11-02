"""Synthetic migration tests: no real database, network, models or artifacts."""

from copy import deepcopy
import io
import json
import math
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid
from contextlib import redirect_stderr, redirect_stdout

from qdrant_client import models

import migrate_qdrant as migration


def record(point):
    return SimpleNamespace(**deepcopy(point))


class FakeClient:
    """Only allow listed APIs; destructive methods are intentionally absent."""

    def __init__(self, points=(), exists=True):
        self.points = {point["id"]: deepcopy(point) for point in points}
        self.exists = exists
        self.vectors = models.VectorParams(size=384, distance=models.Distance.COSINE)
        self.calls = []
        self.closed = False
        self.fail_on_batch = None
        self.normalize = False
        self.normalization_noise = 1e-7
        self.late_point = None

    def collection_exists(self, **kwargs):
        return self.exists

    def get_collection(self, **kwargs):
        return SimpleNamespace(config=SimpleNamespace(params=SimpleNamespace(vectors=self.vectors)))

    def count(self, *, exact, **kwargs):
        assert exact is True
        return SimpleNamespace(count=len(self.points))

    def scroll(self, *, limit, offset, with_payload, with_vectors, **kwargs):
        assert with_payload is True and with_vectors is True
        assert 1 <= limit <= migration.MAX_BATCH_SIZE
        ids = sorted(self.points)
        start = 0 if offset is None else ids.index(offset)
        page = ids[start:start + limit]
        next_offset = ids[start + limit] if start + limit < len(ids) else None
        return [record(self.points[point_id]) for point_id in page], next_offset

    def create_collection(self, *, collection_name, vectors_config):
        assert not self.exists
        self.calls.append(("create", collection_name))
        self.exists = True
        self.vectors = vectors_config

    def retrieve(self, *, ids, with_payload, with_vectors, **kwargs):
        assert with_payload is True and with_vectors is True
        if self.late_point is not None:
            self.points[self.late_point["id"]] = deepcopy(self.late_point)
            self.late_point = None
        return [record(self.points[point_id]) for point_id in ids if point_id in self.points]

    def upsert(self, *, collection_name, points, wait):
        assert wait is True
        assert 1 <= len(points) <= migration.MAX_BATCH_SIZE
        self.calls.append(("upsert", [point.id for point in points]))
        if self.fail_on_batch == sum(call[0] == "upsert" for call in self.calls):
            raise RuntimeError("Synthetic interrupted request")
        for point in points:
            assert point.id not in self.points, "Must never overwrite an existing point"
            value = point.model_dump(include={"id", "payload", "vector"})
            if self.normalize:
                value["vector"][0] += self.normalization_noise
            self.points[point.id] = value

    def close(self):
        self.closed = True


class MigrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="synthetic-qdrant-migration-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.source = self.directory / "storage"
        self.source.mkdir()
        (self.source / "meta.json").write_text('{"synthetic": true}', encoding="utf-8")
        (self.source / ".lock").write_bytes(b"synthetic lock")
        nested = self.source / "collection"
        nested.mkdir()
        (nested / "storage.sqlite").write_bytes(b"NOT A REAL DATABASE")
        self.chunks_path = self.directory / "chunks.jsonl"
        self.export_path = self.directory / "points.jsonl"
        self.chunks = {}
        self.points = {}
        for index in range(3):
            payload = {"chunk_id": f"synthetic-{index}", "text": f"FAKE judgment {index}",
                       "metadata": {"page": index, "unicode": "न्याय", "empty": None}}
            point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, payload["chunk_id"]))
            self.chunks[point_id] = payload
            vector = [0.0] * 384
            vector[index] = 1.0
            self.points[point_id] = {"id": point_id, "payload": payload, "vector": vector}
        self.write_jsonl(self.chunks_path, self.chunks.values())
        self.write_jsonl(self.export_path, self.points.values())
        self.output = self.directory / "new-export.jsonl"

    def write_jsonl(self, path, records):
        path.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records),
                        encoding="utf-8")

    def run_export(self, client=None, **kwargs):
        client = client or FakeClient(self.points.values())
        factory = kwargs.pop("client_factory", lambda **options: client)
        return migration.export_local(self.source, self.chunks_path, self.output,
                                      expect_count=3, batch_size=2,
                                      client_factory=factory, **kwargs)

    def run_remote(self, client, **kwargs):
        return migration.remote_migration(client, self.points, self.chunks,
                                          batch_size=2, **kwargs)

    def test_export_uses_only_copy_ignores_lock_and_preserves_original_hashes(self):
        original = migration.source_hashes(self.source)
        client = FakeClient(self.points.values())
        copies = []

        def factory(*, path):
            copy = Path(path)
            copies.append(copy)
            self.assertNotEqual(copy.resolve(), self.source.resolve())
            self.assertFalse((copy / ".lock").exists())
            self.assertEqual((copy / "collection" / "storage.sqlite").read_bytes(),
                             b"NOT A REAL DATABASE")
            # Simulate a local client changing its own copied files.
            (copy / "meta.json").write_text("changed copy", encoding="utf-8")
            return client

        self.assertEqual(self.run_export(local_backend_stopped=True, client_factory=factory), 3)
        self.assertEqual(migration.source_hashes(self.source), original)
        self.assertEqual(migration.load_export(self.output, self.chunks), self.points)
        self.assertTrue(client.closed)
        self.assertFalse(copies[0].exists())
        self.assertEqual(list(self.directory.glob(".qdrant-export-*")), [])

    def test_export_requires_stopped_confirmation_before_opening_client(self):
        with patch.object(migration, "source_hashes") as hashes:
            with self.assertRaisesRegex(migration.MigrationError, "local-backend-stopped"):
                self.run_export()
            hashes.assert_not_called()

    def test_export_refuses_active_local_lock(self):
        import portalocker

        with patch.object(portalocker, "lock", side_effect=portalocker.exceptions.LockException()):
            with self.assertRaisesRegex(migration.MigrationError, "active/locked"):
                self.run_export(local_backend_stopped=True)
        self.assertFalse(self.output.exists())

    def test_export_refuses_existing_output_without_modification(self):
        self.output.write_bytes(b"preserve me")
        with self.assertRaisesRegex(migration.MigrationError, "already exists"):
            self.run_export(local_backend_stopped=True)
        self.assertEqual(self.output.read_bytes(), b"preserve me")

    def test_export_refuses_output_inside_original(self):
        self.output = self.source / "bad.jsonl"
        with self.assertRaisesRegex(migration.MigrationError, "outside source"):
            self.run_export(local_backend_stopped=True)
        self.assertFalse(self.output.exists())

    def test_missing_source_lock_is_not_created(self):
        (self.source / ".lock").unlink()
        with self.assertRaisesRegex(migration.MigrationError, "meta.json and .lock"):
            self.run_export(local_backend_stopped=True)
        self.assertFalse((self.source / ".lock").exists())

    def test_changed_original_refuses_publication(self):
        client = FakeClient(self.points.values())

        def close():
            (self.source / "meta.json").write_bytes(b"synthetic external change")
            client.closed = True

        client.close = close
        with self.assertRaisesRegex(migration.MigrationError, "Original source files changed"):
            self.run_export(client, local_backend_stopped=True)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.directory.glob(".qdrant-export-*")), [])

    def test_export_refuses_bad_source_count_and_payload(self):
        missing = FakeClient(list(self.points.values())[:2])
        wrong = deepcopy(list(self.points.values()))
        wrong[0]["payload"]["text"] = "divergent"
        for client in (missing, FakeClient(wrong)):
            with self.subTest(client=client):
                with self.assertRaises(migration.MigrationError):
                    self.run_export(client, local_backend_stopped=True)
                self.assertTrue(client.closed)
                self.assertFalse(self.output.exists())

    def test_source_links_are_refused_before_copy_or_client_open(self):
        def linked(path):
            return path.name == "storage.sqlite"

        with patch.object(migration, "is_storage_link", side_effect=linked), \
                patch.object(migration.shutil, "copytree") as copy:
            with self.assertRaisesRegex(migration.MigrationError, "Links/junctions"):
                self.run_export(local_backend_stopped=True)
            copy.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_client_open_failure_still_checks_source_hashes_and_cleans_copy(self):
        original = migration.source_hashes(self.source)
        copies = []

        def factory(*, path):
            copies.append(Path(path))
            raise RuntimeError("Synthetic copy-open failure")

        with patch.object(migration, "source_hashes", wraps=migration.source_hashes) as hashes:
            with self.assertRaisesRegex(RuntimeError, "copy-open failure"):
                self.run_export(local_backend_stopped=True, client_factory=factory)
            self.assertEqual(hashes.call_count, 2)
        self.assertEqual(migration.source_hashes(self.source), original)
        self.assertFalse(copies[0].exists())
        self.assertFalse(self.output.exists())

    def test_duplicate_scroll_records_and_changing_counts_refuse_import(self):
        for failure in ("duplicate", "count"):
            with self.subTest(failure=failure):
                client = FakeClient(list(self.points.values())[:1])
                if failure == "duplicate":
                    point = record(next(iter(client.points.values())))
                    client.scroll = lambda **kwargs: ([point, point], None)
                else:
                    counts = iter((1, 2))
                    client.count = lambda **kwargs: SimpleNamespace(count=next(counts))
                with self.assertRaises(migration.MigrationError):
                    self.run_remote(client)
                self.assertEqual(client.calls, [])

    def test_atomic_publication_does_not_clobber_late_output(self):
        real_link = migration.os.link

        def raced_link(source, destination):
            Path(destination).write_bytes(b"other process")
            return real_link(source, destination)

        with patch.object(migration.os, "link", side_effect=raced_link):
            with self.assertRaises(FileExistsError):
                self.run_export(local_backend_stopped=True)
        self.assertEqual(self.output.read_bytes(), b"other process")
        self.assertEqual(list(self.directory.glob(".qdrant-export-*")), [])

    def test_chunks_exact_uuid5_and_payload(self):
        self.assertEqual(migration.load_chunks(self.chunks_path, 3), self.chunks)
        self.assertEqual(migration.load_export(self.export_path, self.chunks), self.points)
        with self.assertRaisesRegex(migration.MigrationError, "Chunks count"):
            migration.load_chunks(self.chunks_path, migration.EXPECTED_COUNT)

    def test_duplicate_or_invalid_chunks(self):
        payload = next(iter(self.chunks.values()))
        for records in ([payload, payload], [{"chunk_id": 3}], [{"text": "missing ID"}]):
            with self.subTest(records=records):
                self.write_jsonl(self.chunks_path, records)
                with self.assertRaises(migration.MigrationError):
                    migration.load_chunks(self.chunks_path, 3)

    def test_malformed_json_and_duplicate_keys(self):
        for text in ('{bad json}\n', '[]\n', '{"chunk_id":"a","chunk_id":"b"}\n',
                     '{"chunk_id":"a","extra":NaN}\n',
                     '{"chunk_id":"a","extra":1e999}\n'):
            with self.subTest(text=text):
                self.chunks_path.write_text(text, encoding="utf-8")
                with self.assertRaises(migration.MigrationError):
                    migration.load_chunks(self.chunks_path, 1)

    def test_export_file_duplicate_missing_and_unknown_points(self):
        original = list(self.points.values())
        unknown = deepcopy(original[0])
        unknown["id"] = str(uuid.uuid4())
        for values in (original + [original[0]], original[:2], [unknown] + original[1:]):
            with self.subTest(values=len(values)):
                self.write_jsonl(self.export_path, values)
                with self.assertRaises(migration.MigrationError):
                    migration.load_export(self.export_path, self.chunks)

    def test_strict_payload_and_vector_validation(self):
        base = next(iter(self.points.values()))
        mutations = [lambda p: p["payload"].update(extra="unexpected"),
                     lambda p: p["payload"]["metadata"].update(page=False),
                     lambda p: p.update(vector=[0.0] * 383),
                     lambda p: p["vector"].__setitem__(0, float("nan")),
                     lambda p: p["vector"].__setitem__(0, float("inf")),
                     lambda p: p["vector"].__setitem__(0, True),
                     lambda p: p["vector"].__setitem__(0, "0.0"),
                     lambda p: p.update(id=p["id"].upper()),
                     lambda p: p.update(id=123),
                     lambda p: p.update(vector={"named": p["vector"]}),
                     lambda p: p.update(extra="unsupported")]
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                point = deepcopy(base)
                mutate(point)
                with self.assertRaises(migration.MigrationError):
                    migration.validate_point(point, self.chunks)

    def test_import_creates_only_absent_collection_and_verifies_all_points(self):
        client = FakeClient(exists=False)
        self.assertEqual(self.run_remote(client), 3)
        self.assertEqual(client.points, self.points)
        self.assertEqual([call[0] for call in client.calls], ["create", "upsert", "upsert"])
        self.assertEqual(client.vectors.size, 384)
        self.assertEqual(client.vectors.distance, models.Distance.COSINE)

    def test_resume_only_inserts_missing_and_complete_import_is_noop(self):
        client = FakeClient(list(self.points.values())[:1])
        self.run_remote(client)
        self.assertEqual(client.points, self.points)
        self.assertEqual([call[0] for call in client.calls], ["upsert"])
        client.calls.clear()
        self.run_remote(client)
        self.assertEqual(client.calls, [])

    def test_interrupted_import_can_resume_without_overwriting(self):
        client = FakeClient(exists=False)
        client.fail_on_batch = 2
        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            self.run_remote(client)
        self.assertEqual(len(client.points), 2)
        client.fail_on_batch = None
        self.run_remote(client)
        self.assertEqual(client.points, self.points)

    def test_divergent_destination_never_gets_any_write(self):
        original = list(self.points.values())
        for mutation in ("payload", "vector", "id", "extra"):
            with self.subTest(mutation=mutation):
                values = deepcopy(original[:2])
                if mutation == "payload":
                    values[-1]["payload"]["text"] = "different"
                elif mutation == "vector":
                    values[-1]["vector"][0] = 0.5
                else:
                    extra = deepcopy(original[-1])
                    extra["id"] = str(uuid.uuid4())
                    if mutation == "id":
                        values[-1] = extra
                    else:
                        values = deepcopy(original) + [extra]
                client = FakeClient(values)
                before = deepcopy(client.points)
                with self.assertRaises(migration.MigrationError):
                    self.run_remote(client)
                self.assertEqual(client.calls, [])
                self.assertEqual(client.points, before)

    def test_incompatible_vector_configuration_refused_before_write(self):
        configurations = [models.VectorParams(size=12, distance=models.Distance.COSINE),
                          models.VectorParams(size=384, distance=models.Distance.DOT),
                          {"named": models.VectorParams(size=384, distance=models.Distance.COSINE)},
                          models.VectorParams(size=384, distance=models.Distance.COSINE,
                                              datatype=models.Datatype.FLOAT16)]
        for vectors in configurations:
            with self.subTest(vectors=vectors):
                client = FakeClient()
                client.vectors = vectors
                with self.assertRaises(migration.MigrationError):
                    self.run_remote(client)
                self.assertEqual(client.calls, [])

    def test_batch_recheck_refuses_new_divergent_point(self):
        client = FakeClient()
        client.late_point = deepcopy(next(iter(self.points.values())))
        client.late_point["vector"][0] = 0.25
        with self.assertRaisesRegex(migration.MigrationError, "Vector mismatch"):
            self.run_remote(client)
        self.assertEqual(client.calls, [])

    def test_final_vector_verification_accepts_tiny_normalization_noise(self):
        client = FakeClient()
        client.normalize = True
        self.assertEqual(self.run_remote(client), 3)
        self.assertNotEqual(client.points, self.points)
        self.assertEqual(len(client.points), 3)
        self.assertTrue(all(call[0] == "upsert" for call in client.calls))

    def test_final_vector_verification_rejects_material_server_drift(self):
        client = FakeClient()
        client.normalize = True
        client.normalization_noise = 1e-4
        with self.assertRaisesRegex(migration.MigrationError, "Vector mismatch") as raised:
            self.run_remote(client)
        self.assertIn("L2 difference=", str(raised.exception))
        self.assertIn("Inspect the export", str(raised.exception))
        self.assertIn("no points were deleted or automatically repaired", str(raised.exception))
        # Failure leaves data untouched for diagnosis; there is no rollback/delete API.
        self.assertEqual(len(client.points), 3)
        self.assertTrue(all(call[0] == "upsert" for call in client.calls))

    def test_float32_noise_is_accepted_during_resume_and_read_only_verify(self):
        changed = deepcopy(list(self.points.values()))
        for point in changed:
            for index, value in enumerate(point["vector"]):
                # Round the perturbation to an actual IEEE float32 representation.
                noise = 5e-7 if value else 2e-8
                point["vector"][index] = struct.unpack("f", struct.pack("f", value + noise))[0]
        client = FakeClient(changed)
        before = deepcopy(client.points)
        self.assertEqual(self.run_remote(client, verify_only=True), 3)
        self.assertEqual(self.run_remote(client), 3)
        self.assertEqual(client.calls, [])
        self.assertEqual(client.points, before)

    def test_coordinate_bound_rejects_drift_even_when_l2_bound_passes(self):
        point = deepcopy(next(iter(self.points.values())))
        point["vector"][1] = 2e-7  # Zero coordinate: fails abs_tol, but L2 is < 1e-6.
        self.assertLess(math.dist(point["vector"], self.points[point["id"]]["vector"]), 1e-6)
        with self.assertRaisesRegex(migration.MigrationError, "first failing coordinate=1"):
            migration.match_point(point, self.points, self.chunks)

    def test_l2_bound_rejects_accumulated_drift_even_when_all_coordinates_pass(self):
        point = deepcopy(next(iter(self.points.values())))
        reference = self.points[point["id"]]["vector"]
        point["vector"][1:] = [7.5e-8] * 383
        self.assertTrue(all(math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-7)
                            for a, b in zip(point["vector"], reference)))
        self.assertGreater(math.dist(point["vector"], reference), 1e-6)
        client = FakeClient([point])
        with self.assertRaisesRegex(migration.MigrationError, "first failing coordinate=None"):
            self.run_remote(client)
        self.assertEqual(client.calls, [])

    def test_tolerance_does_not_relax_canonical_payload_or_id_equality(self):
        point = deepcopy(next(iter(self.points.values())))
        point["vector"][1] = 5e-8
        for field in ("id", "payload"):
            with self.subTest(field=field):
                changed = deepcopy(point)
                if field == "id":
                    changed["id"] = changed["id"].upper()
                else:
                    changed["payload"]["metadata"]["page"] = 0.0  # Not canonical integer 0.
                client = FakeClient([changed])
                with self.assertRaises(migration.MigrationError):
                    self.run_remote(client, verify_only=True)
                self.assertEqual(client.calls, [])

    def test_non_unit_vectors_are_not_rejected_or_renormalized(self):
        points = deepcopy(self.points)
        for point in points.values():
            point["vector"] = [value * 2 for value in point["vector"]]
        client = FakeClient(points.values())
        self.assertEqual(migration.remote_migration(client, points, self.chunks,
                                                   verify_only=True), 3)
        self.assertEqual(client.points, points)
        self.assertEqual(client.calls, [])

    def test_verify_is_read_only_and_requires_complete_matching_data(self):
        client = FakeClient(self.points.values())
        self.assertEqual(self.run_remote(client, verify_only=True), 3)
        self.assertEqual(client.calls, [])
        for client in (FakeClient(exists=False), FakeClient(list(self.points.values())[:2])):
            with self.assertRaises(migration.MigrationError):
                self.run_remote(client, verify_only=True)
            self.assertEqual(client.calls, [])
        changed = deepcopy(list(self.points.values()))
        changed[1]["vector"][1] += 1e-4
        client = FakeClient(changed)
        with self.assertRaisesRegex(migration.MigrationError, "Vector mismatch"):
            self.run_remote(client, verify_only=True)
        self.assertEqual(client.calls, [])

    def test_bad_input_is_rejected_before_remote_connect(self):
        self.export_path.write_text("not json\n", encoding="utf-8")
        with patch.object(migration, "QdrantClient") as factory, redirect_stderr(io.StringIO()):
            result = migration.main(["import", "--url", "http://qdrant:6333",
                                     "--file", str(self.export_path), "--chunks", str(self.chunks_path),
                                     "--expect-count", "3", "--destination-writes-stopped"])
        self.assertEqual(result, 1)
        factory.assert_not_called()

    def test_cli_remote_url_api_key_and_close(self):
        client = FakeClient(self.points.values())
        with patch.object(migration, "QdrantClient", return_value=client) as factory, \
                patch.dict(migration.os.environ, {"QDRANT_API_KEY": "synthetic-secret"}), \
                redirect_stdout(io.StringIO()) as output:
            result = migration.main(["verify", "--url", "http://qdrant:6333",
                                     "--file", str(self.export_path), "--chunks", str(self.chunks_path),
                                     "--expect-count", "3", "--destination-writes-stopped"])
        self.assertEqual(result, 0)
        self.assertIn("exact count/IDs/payload", output.getvalue())
        self.assertIn("bounded tolerance, not bit-exact", output.getvalue())
        self.assertIn("coordinate rel_tol=1e-06, abs_tol=1e-07; L2 difference <= 1e-06",
                      output.getvalue())
        self.assertNotIn("exact points", output.getvalue())
        factory.assert_called_once_with(url="http://qdrant:6333", api_key="synthetic-secret", timeout=60)
        self.assertTrue(client.closed)
        self.assertEqual(client.calls, [])

    def test_cli_requires_explicit_safety_flags_and_valid_batch_sizes(self):
        with redirect_stderr(io.StringIO()):
            for arguments in (["export"], ["import", "--url", "http://qdrant:6333"],
                              ["verify", "--url", "http://qdrant:6333"]):
                with self.assertRaises(SystemExit):
                    migration.parser().parse_args(arguments)
        for count, size in ((0, 64), (3, 0), (3, 257)):
            with self.assertRaises(migration.MigrationError):
                migration.validate_options(count, size)


if __name__ == "__main__":
    unittest.main()
