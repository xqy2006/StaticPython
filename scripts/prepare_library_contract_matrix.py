from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from packaging.version import InvalidVersion, Version


MATRIX_LIMIT = 256
SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


def _matrix_slug(library: str, version: str, python_version: str, sha256: str) -> str:
    raw = f"{library}-{version}-py{python_version}-{sha256[:12]}"
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip(".-")
    if not slug:
        raise RuntimeError("could not create a safe candidate slug")
    return slug[:180]


def _smoke_candidate(contract: dict, library_name: str, python_series: str) -> dict:
    if not re.fullmatch(r"3\.(11|12|13|14|15)", python_series):
        raise RuntimeError(f"invalid smoke-test Python series: {python_series!r}")
    libraries = contract.get("libraries")
    if not isinstance(libraries, dict):
        raise RuntimeError("contract libraries must be an object")
    canonical_name = next(
        (name for name in libraries if name.casefold() == library_name.casefold()),
        None,
    )
    if canonical_name is None:
        raise RuntimeError(f"smoke-test library is missing from contract: {library_name}")
    versions = libraries[canonical_name].get("versions")
    if not isinstance(versions, dict):
        raise RuntimeError(f"smoke-test library has no versions object: {canonical_name}")
    ordered_versions: list[tuple[Version, str]] = []
    for raw_version in versions:
        try:
            ordered_versions.append((Version(raw_version), raw_version))
        except InvalidVersion:
            continue
    for _parsed, raw_version in sorted(ordered_versions, reverse=True):
        targets = versions[raw_version].get("targets", {})
        for python_version, target in sorted(targets.items()):
            if not python_version.startswith(f"{python_series}."):
                continue
            if isinstance(target, dict) and target.get("status") == "candidate":
                return {
                    "library": canonical_name,
                    "version": raw_version,
                    "python_version": python_version,
                    "status": "candidate",
                    "source": target.get("source"),
                }
    raise RuntimeError(
        f"smoke-test library {canonical_name} has no candidate for CPython {python_series}"
    )


def prepare_matrix(
    contract: dict,
    delta: dict,
    *,
    limit: int = MATRIX_LIMIT,
    smoke_library: str | None = None,
    smoke_python_series: str | None = None,
) -> dict:
    if limit < 1:
        raise RuntimeError("matrix limit must be positive")
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

    delta_candidates = delta.get("new_candidates")
    if not isinstance(delta_candidates, list):
        raise RuntimeError("delta new_candidates must be an array")
    if (smoke_library is None) != (smoke_python_series is None):
        raise RuntimeError("smoke library and Python series must be provided together")
    candidate_records = [(candidate, "new-candidate") for candidate in delta_candidates]
    if smoke_library is not None and smoke_python_series is not None:
        smoke = _smoke_candidate(contract, smoke_library, smoke_python_series)
        smoke_identity = (
            smoke["library"].casefold(),
            smoke["version"],
            smoke["python_version"],
        )
        existing_identities = {
            (
                str(candidate.get("library", "")).casefold(),
                candidate.get("version"),
                candidate.get("python_version"),
            )
            for candidate in delta_candidates
            if isinstance(candidate, dict)
        }
        if smoke_identity not in existing_identities:
            candidate_records.append((smoke, "pull-request-smoke"))
    libraries = contract.get("libraries")
    if not isinstance(libraries, dict):
        raise RuntimeError("contract libraries must be an object")
    include: list[dict] = []
    slugs: set[str] = set()
    for candidate, validation_reason in candidate_records:
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
                "validation_reason": validation_reason,
            }
        )
    if not include:
        return {"include": []}

    batch_count = min(len(include), limit)
    batches: list[list[dict]] = [[] for _ in range(batch_count)]
    for index, candidate in enumerate(include):
        batches[index % batch_count].append(candidate)

    matrix_include: list[dict] = []
    for index, candidates in enumerate(batches, start=1):
        candidates_json = json.dumps(
            candidates,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(candidates_json.encode("utf-8")).hexdigest()[:12]
        matrix_include.append(
            {
                "slug": f"batch-{index:03d}-{digest}",
                "candidate_count": len(candidates),
                "candidates_json": candidates_json,
            }
        )
    return {"include": matrix_include}


def build_summary(contract: dict, delta: dict, matrix: dict) -> str:
    counts = contract.get("status_counts", {})
    candidates = [
        candidate
        for batch in matrix.get("include", [])
        for candidate in json.loads(batch.get("candidates_json", "[]"))
    ]
    lines = [
        "## StaticPython library version contract",
        "",
        f"- Contract SHA-256: `{contract.get('contract_sha256', '<missing>')}`",
        f"- Baseline run: `{bool(delta.get('baseline'))}`",
        f"- Candidate combinations recorded: `{counts.get('candidate', 0)}`",
        f"- Configured non-PyPI combinations: `{counts.get('configured', 0)}`",
        f"- Evidence-backed unbuildable combinations: `{counts.get('unbuildable', 0)}`",
        f"- Matrix batch jobs: `{len(matrix.get('include', []))}`",
        f"- New candidate builds: `{sum(1 for item in candidates if item.get('validation_reason') == 'new-candidate')}`",
        f"- Pull-request smoke builds: `{sum(1 for item in candidates if item.get('validation_reason') == 'pull-request-smoke')}`",
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
    parser.add_argument("--smoke-library")
    parser.add_argument("--smoke-python-series")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    delta = json.loads(args.delta.read_text(encoding="utf-8"))
    matrix = prepare_matrix(
        contract,
        delta,
        limit=args.limit,
        smoke_library=args.smoke_library,
        smoke_python_series=args.smoke_python_series,
    )
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
    candidate_count = sum(
        batch.get("candidate_count", 0)
        for batch in matrix["include"]
    )
    print(
        f"[library-contract] prepared {candidate_count} candidate build(s) "
        f"in {len(matrix['include'])} matrix batch job(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
