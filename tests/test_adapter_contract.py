from __future__ import annotations

import unittest

from darwin_core.adapter import RuntimeAdapter
from darwin_core.models import RuntimeAsset


class FakeAdapter(RuntimeAdapter):
    runtime_id = "fake"

    def discover_assets(self):
        return [RuntimeAsset(runtime_id="fake", native_id="demo", kind="skill", path="/demo")]


class AdapterContractTestCase(unittest.TestCase):
    def test_adapter_exposes_runtime_identity_and_assets(self) -> None:
        asset = FakeAdapter().discover_assets()[0]
        self.assertEqual(asset.runtime_id, "fake")
        self.assertEqual(asset.native_id, "demo")
        self.assertEqual(asset.kind, "skill")


if __name__ == "__main__":
    unittest.main()
