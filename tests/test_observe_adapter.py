from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

import observe


class ObserveAdapterTestCase(unittest.TestCase):
    def test_stop_event_uses_codex_adapter_translation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch.object(observe, "resolve_data_dir", return_value=Path(temp)):
                with mock.patch.object(observe.CodexAdapter, "translate_hook", wraps=observe.CodexAdapter().translate_hook) as translated:
                    observe.observe({"hook_event_name": "Stop", "last_assistant_message": "done"})
            self.assertEqual(translated.call_count, 1)


if __name__ == "__main__":
    unittest.main()
