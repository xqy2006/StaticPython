from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from publish_release_assets import AssetSpec, build_release_specs, chunk_assets


class PublishReleaseAssetTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, str]:
        import hashlib

        commit = "a" * 40
        pack = root / "pack.zip"
        runtime = root / "runtime.zip"
        pack.write_bytes(b"pack")
        runtime.write_bytes(b"runtime")

        def record(path: Path) -> dict:
            return {
                "filename": path.name,
                "size": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }

        index = {
            "schema_version": 1,
            "kind": "staticpython-runtime-index",
            "status": "verified",
            "staticpython_repository": "xqy2006/StaticPython",
            "staticpython_commit": commit,
            "release_families": {
                "a-f": {"tag": "packs-a-f", "asset_count": 1},
            },
            "packs": {
                "demo": {
                    "1": {
                        "cp311": {**record(pack), "release_family": "a-f"},
                    }
                }
            },
            "runtime_release_tag": "runtime",
            "runtimes": {"cp311": record(runtime)},
        }
        index_path = root / "runtime-index.v1.json"
        index_path.write_text(json.dumps(index), encoding="utf-8")
        return index_path, commit

    def test_build_release_specs_validates_and_orders_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index, commit = self._fixture(root)
            specs = build_release_specs(root, index, "xqy2006/StaticPython", commit)
            self.assertEqual([spec.tag for spec in specs], ["packs-a-f", "runtime"])
            self.assertEqual([asset.name for asset in specs[0].assets], ["pack.zip"])
            self.assertEqual(
                [asset.name for asset in specs[1].assets],
                ["runtime-index.v1.json", "runtime.zip"],
            )

    def test_build_release_specs_rejects_modified_asset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index, commit = self._fixture(root)
            (root / "pack.zip").write_bytes(b"modified")
            with self.assertRaisesRegex(RuntimeError, "size mismatch"):
                build_release_specs(root, index, "xqy2006/StaticPython", commit)

    def test_chunk_assets_stays_below_safe_command_length(self) -> None:
        assets = tuple(
            AssetSpec(Path("C:/assets") / ("x" * 40 + str(index)), f"{index}.zip", 1, "0" * 64)
            for index in range(10)
        )
        chunks = chunk_assets(assets, base_command_chars=60, max_command_chars=220)
        self.assertGreater(len(chunks), 1)
        self.assertEqual([asset for chunk in chunks for asset in chunk], list(assets))
        for chunk in chunks:
            size = 60 + sum(len(str(asset.path)) + 3 for asset in chunk)
            self.assertLessEqual(size, 220)


if __name__ == "__main__":
    unittest.main()
