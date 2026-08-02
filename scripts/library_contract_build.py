from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from zipfile import ZipFile


SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
DLL_LINE_PATTERN = re.compile(r"^\s*([A-Za-z0-9_.+-]+\.dll)\s*$", re.IGNORECASE)
ALLOWED_SOURCE_HOST_SUFFIXES = (".pythonhosted.org", ".pypi.org")
FORBIDDEN_DLL_PREFIXES = ("python", "vcruntime", "msvcp")


def normalized_project_name(project_name: str) -> str:
    normalized = re.sub(r"[-_.]+", "-", project_name).lower()
    if not normalized or normalized in {".", ".."}:
        raise ValueError(f"invalid PyPI project name: {project_name!r}")
    return normalized


def safe_leaf(value: str, description: str) -> str:
    if not value or Path(value).name != value or value in {".", ".."}:
        raise ValueError(f"invalid {description}: {value!r}")
    return value


def checked_sha256(value: str) -> str:
    if not SHA256_PATTERN.fullmatch(value):
        raise ValueError(f"invalid SHA-256: {value!r}")
    return value.lower()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_archive_path(
    download_root: Path,
    project_name: str,
    release_version: str,
    filename: str,
) -> Path:
    return (
        download_root
        / "pypi"
        / normalized_project_name(project_name)
        / safe_leaf(release_version, "release version")
        / safe_leaf(filename, "source filename")
    )


def _validate_source_url(url: str) -> None:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not any(
        hostname == suffix[1:] or hostname.endswith(suffix)
        for suffix in ALLOWED_SOURCE_HOST_SUFFIXES
    ):
        raise ValueError(f"source URL is not an approved HTTPS PyPI host: {url!r}")


def _ensure_only_expected_archive(destination: Path) -> None:
    unexpected = sorted(
        path.name
        for path in destination.parent.iterdir()
        if path != destination
    )
    if unexpected:
        raise RuntimeError(
            f"source cache contains artifacts outside the locked contract: {unexpected}"
        )


def stage_source_archive(
    download_root: Path,
    project_name: str,
    release_version: str,
    filename: str,
    url: str,
    expected_sha256: str,
) -> Path:
    expected = checked_sha256(expected_sha256)
    _validate_source_url(url)
    destination = source_archive_path(
        download_root,
        project_name,
        release_version,
        filename,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    _ensure_only_expected_archive(destination)
    if destination.is_file():
        actual = sha256_file(destination)
        if actual != expected:
            raise RuntimeError(
                f"cached source archive SHA-256 mismatch: expected {expected}, got {actual}"
            )
        return destination

    request = Request(url, headers={"User-Agent": "StaticPython-library-contract/1"})
    last_error: Exception | None = None
    for attempt in range(1, 6):
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix=f".{destination.name}.",
                suffix=".tmp",
                dir=destination.parent,
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                with urlopen(request, timeout=120) as response:
                    while chunk := response.read(1024 * 1024):
                        temporary.write(chunk)
        except Exception as exc:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            last_error = exc
            if attempt < 5:
                time.sleep(min(2 ** (attempt - 1), 15))
                continue
            break
        except BaseException:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise

        assert temporary_path is not None
        actual = sha256_file(temporary_path)
        if actual != expected:
            temporary_path.unlink(missing_ok=True)
            raise RuntimeError(
                f"downloaded source archive SHA-256 mismatch: expected {expected}, got {actual}"
            )
        temporary_path.replace(destination)
        return destination

    assert last_error is not None
    raise RuntimeError(f"could not download locked PyPI source after 5 attempts: {url}") from last_error


def verify_source_archive(
    download_root: Path,
    project_name: str,
    release_version: str,
    filename: str,
    expected_sha256: str,
) -> Path:
    expected = checked_sha256(expected_sha256)
    archive = source_archive_path(
        download_root,
        project_name,
        release_version,
        filename,
    )
    if not archive.is_file():
        raise RuntimeError(f"locked source archive is missing after build: {archive}")
    _ensure_only_expected_archive(archive)
    actual = sha256_file(archive)
    if actual != expected:
        raise RuntimeError(
            f"source archive SHA-256 changed during build: expected {expected}, got {actual}"
        )
    return archive


def _pack_metadata(pack_path: Path) -> tuple[dict, list[str]]:
    with ZipFile(pack_path) as archive:
        all_names = archive.namelist()
        if len(all_names) != len(set(all_names)):
            raise RuntimeError(f"{pack_path.name} contains duplicate ZIP members")
        names = [record.filename for record in archive.infolist() if not record.is_dir()]
        if names.count("pack.json") != 1:
            raise RuntimeError(f"{pack_path.name} must contain exactly one root pack.json")
        metadata = json.loads(archive.read("pack.json"))
        if not isinstance(metadata, dict):
            raise RuntimeError(f"{pack_path.name} pack.json must be an object")

        file_records = metadata.get("files")
        if not isinstance(file_records, list):
            raise RuntimeError(f"{pack_path.name} pack.json files must be an array")
        recorded_paths: set[str] = set()
        for record in file_records:
            if not isinstance(record, dict):
                raise RuntimeError(f"{pack_path.name} contains an invalid file record")
            relative = record.get("path")
            expected_sha = record.get("sha256")
            if not isinstance(relative, str) or relative not in names:
                raise RuntimeError(f"pack file record is missing from ZIP: {relative!r}")
            if relative in recorded_paths:
                raise RuntimeError(f"pack file record is duplicated: {relative!r}")
            recorded_paths.add(relative)
            if not isinstance(expected_sha, str) or not SHA256_PATTERN.fullmatch(expected_sha):
                raise RuntimeError(f"pack file record has invalid SHA-256: {relative!r}")
            actual_sha = hashlib.sha256(archive.read(relative)).hexdigest()
            if actual_sha != expected_sha.lower():
                raise RuntimeError(f"pack file hash mismatch: {relative}")
        unrecorded = sorted(set(names) - {"pack.json"} - recorded_paths)
        if unrecorded:
            raise RuntimeError(f"pack contains files absent from its hash manifest: {unrecorded}")
    return metadata, names


def verify_pack(
    pack_dir: Path,
    library_name: str,
    release_version: str,
    python_version: str,
) -> Path:
    packs = sorted(pack_dir.glob("*.zip"))
    if len(packs) != 1:
        raise RuntimeError(f"expected exactly one exported pack, found {len(packs)}")
    pack_path = packs[0]
    metadata, names = _pack_metadata(pack_path)

    expected_abi = "cp" + "".join(python_version.split(".")[:2])
    expected_runtime_abi = f"staticpython-pack-v1-{expected_abi}"
    expected_fields = {
        "kind": "staticpython-library-pack",
        "name": library_name,
        "version": release_version,
        "source_provider": "pypi",
        "cpython_version": python_version,
        "cpython_abi": expected_abi,
        "runtime_abi": expected_runtime_abi,
        "platform": "x64",
    }
    for key, expected in expected_fields.items():
        if metadata.get(key) != expected:
            raise RuntimeError(
                f"pack metadata {key} mismatch: expected {expected!r}, got {metadata.get(key)!r}"
            )
    if not SHA256_PATTERN.fullmatch(str(metadata.get("source_tree_sha256", ""))):
        raise RuntimeError("pack metadata has no valid source_tree_sha256")
    license_record = metadata.get("license")
    if not isinstance(license_record, dict) or license_record.get("status") != "complete":
        raise RuntimeError("pack license record is not complete")
    verification = metadata.get("verification")
    if not isinstance(verification, dict) or verification.get("status") != "passed":
        raise RuntimeError("pack verification status is not passed")
    smoke_tests = verification.get("smoke_tests")
    if not isinstance(smoke_tests, list) or not smoke_tests:
        raise RuntimeError("pack contains no behavior smoke-test records")
    bad_smokes = [
        record
        for record in smoke_tests
        if not isinstance(record, dict) or record.get("status") != "passed"
    ]
    if bad_smokes:
        raise RuntimeError(f"pack contains non-passing smoke tests: {bad_smokes}")
    forbidden_members = sorted(
        name for name in names if Path(name).suffix.casefold() in {".dll", ".pyd"}
    )
    if forbidden_members:
        raise RuntimeError(f"pack contains dynamic native artifacts: {forbidden_members}")
    return pack_path


def parse_dumpbin_dependencies(output: str) -> list[str]:
    return sorted(
        {match.group(1) for line in output.splitlines() if (match := DLL_LINE_PATTERN.fullmatch(line))},
        key=str.casefold,
    )


def audit_pe_dependencies(
    executable: Path,
    *,
    dumpbin: str = "dumpbin.exe",
    system_directory: Path | None = None,
) -> list[str]:
    if not executable.is_file():
        raise RuntimeError(f"built executable is missing: {executable}")
    result = subprocess.run(
        [dumpbin, "/nologo", "/dependents", str(executable)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"dumpbin failed with exit code {result.returncode}: {result.stderr}")
    dependencies = parse_dumpbin_dependencies(result.stdout)
    if not dependencies:
        raise RuntimeError("dumpbin returned no PE dependencies; refusing an empty audit")

    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    system32 = system_directory or (system_root / "System32")
    rejected: list[str] = []
    for dependency in dependencies:
        folded = dependency.casefold()
        if folded.startswith(FORBIDDEN_DLL_PREFIXES):
            rejected.append(dependency)
            continue
        if folded.startswith(("api-ms-win-", "ext-ms-win-")):
            continue
        if not (system32 / dependency).is_file():
            rejected.append(dependency)
    if rejected:
        raise RuntimeError(f"PE imports non-system or forbidden DLLs: {sorted(rejected)}")
    return dependencies


def _common_source_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--download-root", type=Path, required=True)
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--filename", required=True)
    parser.add_argument("--sha256", required=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stage and audit one historical StaticPython library contract build."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    stage = subparsers.add_parser("stage")
    _common_source_arguments(stage)
    stage.add_argument("--url", required=True)

    verify = subparsers.add_parser("verify")
    _common_source_arguments(verify)
    verify.add_argument("--library", required=True)
    verify.add_argument("--python-version", required=True)
    verify.add_argument("--pack-dir", type=Path, required=True)
    verify.add_argument("--python-exe", type=Path, required=True)
    verify.add_argument("--report", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "stage":
        archive = stage_source_archive(
            args.download_root,
            args.project_name,
            args.version,
            args.filename,
            args.url,
            args.sha256,
        )
        print(f"[library-contract] staged {archive}")
        return 0

    source = verify_source_archive(
        args.download_root,
        args.project_name,
        args.version,
        args.filename,
        args.sha256,
    )
    pack = verify_pack(
        args.pack_dir,
        args.library,
        args.version,
        args.python_version,
    )
    dependencies = audit_pe_dependencies(args.python_exe)
    report = {
        "schema_version": 1,
        "library": args.library,
        "project_name": args.project_name,
        "version": args.version,
        "python_version": args.python_version,
        "source_archive": str(source),
        "source_archive_sha256": sha256_file(source),
        "pack": str(pack),
        "pack_sha256": sha256_file(pack),
        "python_exe": str(args.python_exe),
        "pe_dependencies": dependencies,
        "status": "passed",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        f"[library-contract] verified {args.library} {args.version} "
        f"on CPython {args.python_version}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
