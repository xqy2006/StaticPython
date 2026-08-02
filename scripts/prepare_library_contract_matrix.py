from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


MATRIX_LIMIT = 256
SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


def _matrix_slug(library: str, version: str, python_version: str, sha256: str) -> str:
    raw = f"{library}-{version}-py{python_version}-{sha256[:12]}"
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip(".-")
    if not slug:
        raise RuntimeError("could not create a safe candidate slug")
    return slug[:180]


def prepare_matrix(contract: dict, delta: dict, *, limit: int = MATRIX_LIMIT) -> dict:
    if delta.get("current_contract_sha256") != contract.get("contract_sha256"):
        raise RuntimeError("delta does not describe the current contract")
    drifted = delta.get("drifted_candidates")
    regressions = delta.get("regressions")
    if not isinstance(drifted, list) or not isinstance(regressions, list):
        raise RuntimeError("delta drift/regression records must be arrays")
    if drifted or regressions:
        raise RuntimeError(
            "contract contains source drift or a previously buildable regression: "
            f"{len(drifted)} drifted, {len(regressions)} regressed"
        )

    candidates = delta.get("new_candidates")
    if not isinstance(candidates, list):
        raise RuntimeError("delta new_candidates must be an array")
    if len(candidates) > limit:
        raise RuntimeError(
            f"incremental contract contains {len(candidates)} build jobs, exceeding the "
            f"GitHub Actions matrix limit of {limit}; shard explicitly instead of skipping combinations"
        )

    libraries = contract.get("libraries")
    if not isinstance(libraries, dict):
        raise RuntimeError("contract libraries must be an object")
    include: list[dict] = []
    slugs: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise RuntimeError("candidate record must be an object")
        library = candidate.get("library")
        version = candidate.get("version")
        python_version = candidate.get("python_version")
        source = candidate.get("source")
        if not all(isinstance(value, str) and value for value in (library, version, python_version)):
            raise RuntimeError(f"candidate has invalid identity fields: {candidate!r}")
        if not isinstance(source, dict):
            raise RuntimeError(f"candidate {library} {version} has no locked source")
        filename = source.get("filename")
        url = source.get("url")
        sha256 = source.get("sha256")
        if not all(isinstance(value, str) and value for value in (filename, url, sha256)):
            raise RuntimeError(f"candidate {library} {version} has incomplete source provenance")
        if not SHA256_PATTERN.fullmatch(sha256):
            raise RuntimeError(f"candidate {library} {version} has invalid source SHA-256")
        library_record = libraries.get(library)
        if not isinstance(library_record, dict):
            raise RuntimeError(f"candidate library is missing from contract: {library}")
        project_name = library_record.get("project_name")
        if not isinstance(project_name, str) or not project_name:
            raise RuntimeError(f"candidate library has no PyPI project name: {library}")
        slug = _matrix_slug(library, version, python_version, sha256)
        if slug.casefold() in slugs:
            raise RuntimeError(f"candidate artifact slug collision: {slug}")
        slugs.add(slug.casefold())
        include.append(
            {
                "library": library,
                "project_name": project_name,
                "version": version,
                "python_version": python_version,
                "source_filename": filename,
                "source_url": url,
                "source_sha256": sha256.lower(),
                "slug": slug,
            }
        )
    return {"include": include}


def build_summary(contract: dict, delta: dict, matrix: dict) -> str:
    counts = contract.get("status_counts", {})
    lines = [
        "## StaticPython library version contract",
        "",
        f"- Contract SHA-256: `{contract.get('contract_sha256', '<missing>')}`",
        f"- Baseline run: `{bool(delta.get('baseline'))}`",
        f"- Candidate combinations recorded: `{counts.get('candidate', 0)}`",
        f"- Configured non-PyPI combinations: `{counts.get('configured', 0)}`",
        f"- Evidence-backed unbuildable combinations: `{counts.get('unbuildable', 0)}`",
        f"- New candidate build jobs: `{len(matrix.get('include', []))}`",
        f"- New unbuildable records: `{len(delta.get('new_unbuildable', []))}`",
        f"- Source drift records: `{len(delta.get('drifted_candidates', []))}`",
        f"- Candidate regressions: `{len(delta.get('regressions', []))}`",
        "",
    ]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate a library contract delta and create its GitHub Actions matrix."
    )
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--delta", type=Path, required=True)
    parser.add_argument("--matrix-output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=MATRIX_LIMIT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    delta = json.loads(args.delta.read_text(encoding="utf-8"))
    matrix = prepare_matrix(contract, delta, limit=args.limit)
    args.matrix_output.parent.mkdir(parents=True, exist_ok=True)
    args.matrix_output.write_text(
        json.dumps(matrix, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.write_text(
        build_summary(contract, delta, matrix),
        encoding="utf-8",
        newline="\n",
    )
    print(f"[library-contract] prepared {len(matrix['include'])} incremental build job(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
