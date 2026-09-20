from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from darwin_core.storage import RuntimeStore


class CoreStorageTestCase(unittest.TestCase):
    def test_store_writes_and_reads_jsonl_under_explicit_runtime_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = RuntimeStore(Path(temp) / "darwin-data", runtime_id="codex")
            store.append_jsonl("events.jsonl", {"event": "observed"})
            self.assertEqual(store.read_jsonl("events.jsonl"), [{"event": "observed"}])


if __name__ == "__main__":
    unittest.main()
