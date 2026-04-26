from __future__ import annotations

import argparse
from pathlib import Path

from patch import iter_patch_files, normalize_patch_target, unified_diff_for_paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh unified diff patches stored under the project Lib directory.")
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=Path(".vendor-stage"),
        help="Directory containing the unpatched upstream library files.",
    )
    parser.add_argument(
        "--modified-dir",
        type=Path,
        help="Directory containing the modified library files to diff against upstream.",
    )
    parser.add_argument(
        "--patch-root",
        type=Path,
        default=Path("Lib"),
        help="Directory where .patch files are stored.",
    )
    parser.add_argument(
        "targets",
        nargs="*",
        help="Optional relative library paths to refresh, e.g. click/_winconsole.py",
    )
    return parser.parse_args()


def resolve_targets(args: argparse.Namespace) -> list[Path]:
    if args.targets:
        return [Path(target) for target in args.targets]
    return [normalize_patch_target(args.patch_root.resolve(), patch_path) for patch_path in iter_patch_files(args.patch_root.resolve())]


def main() -> int:
    args = parse_args()
    base_dir = args.base_dir.resolve()
    if args.modified_dir is None:
        raise SystemExit("--modified-dir is required now that library source is no longer stored under assets/overlay/Lib")
    modified_dir = args.modified_dir.resolve()
    patch_root = args.patch_root.resolve()
    patch_root.mkdir(parents=True, exist_ok=True)

    targets = resolve_targets(args)
    if not targets:
        raise SystemExit("no targets provided and no existing patch files found")

    for relative in targets:
        old_path = base_dir / relative
        new_path = modified_dir / relative
        patch_path = patch_root / relative
        patch_path = patch_path.with_name(patch_path.name + ".patch")
        patch_path.parent.mkdir(parents=True, exist_ok=True)
        patch_text = unified_diff_for_paths(relative.as_posix(), old_path, new_path)
        if patch_text:
            patch_path.write_text(patch_text, encoding="utf-8", newline="\n")
            print(f"wrote {patch_path}")
        elif patch_path.exists():
            patch_path.unlink()
            print(f"removed empty patch {patch_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
