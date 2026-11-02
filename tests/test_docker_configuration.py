"""Offline configuration and wiring tests: no models, sockets, or API quota."""

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from query_pipeline import QueryEngine

ROOT = Path(__file__).resolve().parents[1]


class QueryConnectionTests(unittest.TestCase):
    def make_engine(self, environment):
        with tempfile.TemporaryDirectory() as directory:
            chunks = Path(directory) / "chunks.jsonl"
            chunks.write_text(json.dumps({"text": "legal evidence"}) + "\n", encoding="utf-8")
            db = Path(directory) / "embedded"
            with patch.dict(os.environ, environment, clear=True), \
                    patch("query_pipeline.TextEmbedding") as embedding, \
                    patch("query_pipeline.TextCrossEncoder") as reranker, \
                    patch("query_pipeline.QdrantClient") as client:
                engine = QueryEngine(chunks_path=chunks, db_path=db)
                embedding.assert_called_once_with(model_name="BAAI/bge-small-en-v1.5")
                reranker.assert_called_once_with(model_name="Xenova/ms-marco-MiniLM-L-6-v2")
                return engine, client, db

    def test_local_defaults_preserved(self):
        engine, client, db = self.make_engine({})
        client.assert_called_once_with(path=str(db.resolve()))
        engine.close()
        client.return_value.close.assert_called_once()

    def test_blank_url_preserves_local_mode(self):
        _, client, db = self.make_engine({"QDRANT_URL": "  "})
        client.assert_called_once_with(path=str(db.resolve()))

    def test_remote_url_and_secret(self):
        _, client, _ = self.make_engine({"QDRANT_URL": "http://qdrant:6333", "QDRANT_API_KEY": "test-only"})
        client.assert_called_once_with(url="http://qdrant:6333", api_key="test-only", timeout=60)

    def test_remote_without_auth(self):
        _, client, _ = self.make_engine({"QDRANT_URL": "http://qdrant:6333"})
        client.assert_called_once_with(url="http://qdrant:6333", api_key=None, timeout=60)


class ContainerContractTests(unittest.TestCase):
    def test_allowlist_excludes_sensitive_artifacts(self):
        lines=(ROOT / ".dockerignore").read_text().splitlines()
        self.assertIn("**", lines)
        for line in lines:
            if line.startswith("!"):
                self.assertNotIn(".env", line)
                self.assertNotIn("data/", line)
                self.assertNotIn("qdrant_storage", line)
                self.assertNotIn(".venv", line)

    def test_dockerfile_never_copies_entire_repository(self):
        text=(ROOT / "Dockerfile").read_text()
        self.assertNotIn("COPY . .", text)
        self.assertNotIn("GEMINI_API_KEY", text)
        self.assertIn("USER rag", text)

    def test_health_requires_expected_count(self):
        spec=importlib.util.spec_from_file_location("container_health", ROOT / "docker/healthcheck.py")
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with patch.dict(os.environ, {"QDRANT_URL": "http://qdrant:6333"}, clear=True):
            with patch.object(module, "get_json", side_effect=[{"ready": True}, {"result": {"points_count": 21451}}]):
                module.check("api")
            with patch.object(module, "get_json", side_effect=[{"ready": True}, {"result": {"points_count": 0}}]):
                with self.assertRaises(RuntimeError):
                    module.check("api")

    def test_compose_private_storage_and_startup_gates(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML is optional; run docker compose config --quiet for authoritative validation")
        config=yaml.safe_load((ROOT / "compose.yaml").read_text())
        services=config["services"]
        self.assertNotIn("ports", services["qdrant"])
        self.assertIn("${QDRANT_API_KEY:?", services["qdrant"]["environment"]["QDRANT__SERVICE__API_KEY"])
        self.assertTrue(config["networks"]["storage"]["internal"])
        self.assertEqual(services["qdrant"]["networks"], ["storage"])
        self.assertIn("qdrant_data:/qdrant/storage", services["qdrant"]["volumes"])
        self.assertEqual(services["api"]["depends_on"]["migrate"]["condition"], "service_completed_successfully")
        self.assertEqual(services["streamlit"]["depends_on"]["api"]["condition"], "service_healthy")
        self.assertEqual(services["api"]["environment"]["QDRANT_URL"], "http://qdrant:6333")
        self.assertNotIn("GEMINI_API_KEY", services["streamlit"].get("environment", {}))
        for name in ("api", "streamlit"):
            self.assertTrue(all(p.startswith("127.0.0.1:") for p in services[name]["ports"]))
        for name in ("api", "migrate"):
            for mount in services[name]["volumes"]:
                if isinstance(mount, dict):
                    self.assertTrue(mount["read_only"])
                    self.assertFalse(mount["bind"]["create_host_path"])


if __name__ == "__main__":
    unittest.main()
