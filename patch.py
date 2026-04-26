from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import difflib
import re


HUNK_HEADER_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? \+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@"
)


@dataclass
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[tuple[str, str]]


def normalize_patch_target(patch_root: Path, patch_path: Path) -> Path:
    relative = patch_path.relative_to(patch_root)
    if patch_path.suffix != ".patch":
        raise ValueError(f"unsupported patch extension: {patch_path}")
    return relative.with_suffix("")


def parse_unified_diff(text: str) -> list[Hunk]:
    lines = text.splitlines(keepends=True)
    hunks: list[Hunk] = []
    index = 0
    while index < len(lines):
        match = HUNK_HEADER_RE.match(lines[index])
        if not match:
            index += 1
            continue

        old_count = int(match.group("old_count") or "1")
        new_count = int(match.group("new_count") or "1")
        index += 1
        hunk_lines: list[tuple[str, str]] = []
        while index < len(lines):
            line = lines[index]
            if HUNK_HEADER_RE.match(line):
                break
            if line.startswith("\\ No newline at end of file"):
                index += 1
                continue
            if not line:
                break
            prefix = line[0]
            if prefix not in {" ", "+", "-"}:
                break
            hunk_lines.append((prefix, line[1:]))
            index += 1

        hunks.append(
            Hunk(
                old_start=int(match.group("old_start")),
                old_count=old_count,
                new_start=int(match.group("new_start")),
                new_count=new_count,
                lines=hunk_lines,
            )
        )
    return hunks


def _match_hunk_at(source_lines: list[str], start: int, hunk: Hunk) -> bool:
    source_index = start
    for prefix, payload in hunk.lines:
        if prefix == "+":
            continue
        if source_index >= len(source_lines):
            return False
        if source_lines[source_index] != payload:
            return False
        source_index += 1
    return True


def _match_patched_hunk_at(source_lines: list[str], start: int, hunk: Hunk) -> bool:
    source_index = start
    for prefix, payload in hunk.lines:
        if prefix == "-":
            continue
        if source_index >= len(source_lines):
            return False
        if source_lines[source_index] != payload:
            return False
        source_index += 1
    return True


def _candidate_positions(hint: int, upper_bound: int) -> list[int]:
    positions: list[int] = []
    seen: set[int] = set()
    for delta in range(0, 9):
        for candidate in (hint - delta, hint + delta):
            if 0 <= candidate <= upper_bound and candidate not in seen:
                seen.add(candidate)
                positions.append(candidate)
    return positions


def find_hunk_position(source_lines: list[str], hunk: Hunk, line_offset: int, matcher=_match_hunk_at) -> int:
    upper_bound = len(source_lines)
    hint = max(0, min(upper_bound, hunk.old_start - 1 + line_offset))
    for candidate in _candidate_positions(hint, upper_bound):
        if matcher(source_lines, candidate, hunk):
            return candidate
    for candidate in range(0, upper_bound + 1):
        if matcher(source_lines, candidate, hunk):
            return candidate
    raise RuntimeError(
        f"failed to apply hunk at old line {hunk.old_start}; context not found in target file"
    )


def apply_hunks(source_lines: list[str], hunks: list[Hunk]) -> list[str]:
    patched_lines = list(source_lines)
    line_offset = 0
    for hunk in hunks:
        try:
            start = find_hunk_position(patched_lines, hunk, line_offset)
        except RuntimeError:
            try:
                find_hunk_position(patched_lines, hunk, line_offset, matcher=_match_patched_hunk_at)
            except RuntimeError:
                raise
            line_offset += hunk.new_count - hunk.old_count
            continue
        prefix = patched_lines[:start]
        suffix_index = start
        replacement: list[str] = []
        for prefix_char, payload in hunk.lines:
            if prefix_char == " ":
                replacement.append(patched_lines[suffix_index])
                suffix_index += 1
            elif prefix_char == "-":
                suffix_index += 1
            elif prefix_char == "+":
                replacement.append(payload)
        patched_lines = prefix + replacement + patched_lines[suffix_index:]
        line_offset += hunk.new_count - hunk.old_count
    return patched_lines


def apply_patch_text(target_path: Path, patch_text: str) -> None:
    hunks = parse_unified_diff(patch_text)
    if not hunks:
        raise RuntimeError(f"patch has no hunks: {target_path}")

    if target_path.exists():
        source_lines = target_path.read_text(encoding="utf-8").splitlines(keepends=True)
    else:
        source_lines = []

    patched_lines = apply_hunks(source_lines, hunks)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text("".join(patched_lines), encoding="utf-8", newline="")


def apply_patch_file(target_path: Path, patch_path: Path) -> None:
    apply_patch_text(target_path, patch_path.read_text(encoding="utf-8"))


def iter_patch_files(patch_root: Path) -> list[Path]:
    if not patch_root.exists():
        return []
    return sorted(path for path in patch_root.rglob("*.patch") if path.is_file())


def apply_patch_tree(target_root: Path, patch_root: Path) -> list[Path]:
    applied: list[Path] = []
    for patch_path in iter_patch_files(patch_root):
        target_path = target_root / normalize_patch_target(patch_root, patch_path)
        apply_patch_file(target_path, patch_path)
        applied.append(target_path)
    return applied


def unified_diff_for_paths(
    relative_path: str,
    old_path: Path | None,
    new_path: Path | None,
) -> str:
    normalized_relative = relative_path.replace("\\", "/")
    if old_path is not None and old_path.exists():
        old_lines = old_path.read_text(encoding="utf-8").splitlines(keepends=True)
    else:
        old_lines = []

    if new_path is not None and new_path.exists():
        new_lines = new_path.read_text(encoding="utf-8").splitlines(keepends=True)
    else:
        new_lines = []

    return "".join(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/Lib/{normalized_relative}",
            tofile=f"b/Lib/{normalized_relative}",
            lineterm="\n",
        )
    )
