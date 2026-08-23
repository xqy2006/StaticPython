from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

from libs import pypi_library, source_path, write_source_text


RPDS_VERSION = "2026.6.3"
RPDS_SDIST_SHA256 = "1cebd1337c242e4ec2293e541f712b2da849b29f48f0c293684b71c0632625d4"
RUST_TOOLCHAIN = "1.88.0"
RUST_TARGET = "x86_64-pc-windows-msvc"
RUST_TARGET_ROOT = "PCbuild/rpds_rust_target"
RUST_LIBRARY_NAME = "rpds.lib"
PYO3_STATIC_LIB_DIR_SENTINEL = "C:/staticpython/no-python-import-library"
RUST_SYSTEM_LIBRARIES = [
    "advapi32.lib",
    "bcrypt.lib",
    "kernel32.lib",
    "ntdll.lib",
    "userenv.lib",
    "ws2_32.lib",
]
RPDS_LICENSE_EXPRESSION = "(Apache-2.0 WITH LLVM-exception) AND MIT AND Unicode-3.0"
RUST_SELECTED_LICENSES = {
    "(MIT OR Apache-2.0) AND Unicode-3.0": "MIT AND Unicode-3.0",
    "Apache-2.0 OR MIT": "MIT",
    "Apache-2.0 WITH LLVM-exception": "Apache-2.0 WITH LLVM-exception",
    "MIT": "MIT",
    "MIT OR Apache-2.0": "MIT",
}
RUST_LICENSE_FILE_PATTERN = re.compile(
    r"^(?:LICENSE|COPYING|NOTICE|UNLICENSE|COPYRIGHT)",
    re.IGNORECASE,
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _cargo_lock_records(path: Path) -> dict[tuple[str, str, str | None], str | None]:
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    records: dict[tuple[str, str, str | None], str | None] = {}
    for raw in payload.get("package", []):
        if not isinstance(raw, dict):
            raise RuntimeError("rpds Cargo.lock contains an invalid package record")
        name = raw.get("name")
        version = raw.get("version")
        source = raw.get("source")
        checksum = raw.get("checksum")
        if not isinstance(name, str) or not isinstance(version, str):
            raise RuntimeError("rpds Cargo.lock contains an unnamed package")
        if source is not None and not isinstance(source, str):
            raise RuntimeError(
                f"rpds Cargo.lock has an invalid source for {name} {version}"
            )
        if checksum is not None and (
            not isinstance(checksum, str)
            or re.fullmatch(r"[0-9a-f]{64}", checksum) is None
        ):
            raise RuntimeError(
                f"rpds Cargo.lock has an invalid checksum for {name} {version}"
            )
        key = (name, version, source)
        if key in records:
            raise RuntimeError(f"rpds Cargo.lock repeats {name} {version}")
        records[key] = checksum
    if not records:
        raise RuntimeError("rpds Cargo.lock contains no packages")
    return records


def _rust_license_candidates(package_root: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in package_root.iterdir()
            if path.is_file()
            and RUST_LICENSE_FILE_PATTERN.match(path.name)
            and path.stat().st_size <= 2 * 1024 * 1024
        ),
        key=lambda path: path.name.casefold(),
    )


def _collect_rust_dependency_licenses(
    crate_root: Path,
    cargo_metadata: dict,
    destination: Path,
) -> tuple[list[Path], dict]:
    packages = cargo_metadata.get("packages")
    if not isinstance(packages, list) or not packages:
        raise RuntimeError("cargo metadata contains no rpds packages")
    lock_records = _cargo_lock_records(crate_root / "Cargo.lock")
    metadata_keys: set[tuple[str, str, str | None]] = set()
    package_records: list[dict] = []

    if destination.exists():
        shutil.rmtree(destination)
    texts_root = destination / "texts"
    texts_root.mkdir(parents=True)

    for package in sorted(
        packages,
        key=lambda record: (
            str(record.get("name", "")).casefold(),
            str(record.get("version", "")),
            str(record.get("source") or ""),
        ),
    ):
        if not isinstance(package, dict):
            raise RuntimeError("cargo metadata contains an invalid package record")
        name = package.get("name")
        version = package.get("version")
        source = package.get("source")
        expression = package.get("license")
        manifest_path = package.get("manifest_path")
        if (
            not isinstance(name, str)
            or not name
            or not isinstance(version, str)
            or not version
        ):
            raise RuntimeError("cargo metadata contains an unnamed rpds package")
        if not isinstance(manifest_path, str) or not manifest_path:
            raise RuntimeError(
                f"cargo metadata has no manifest path for {name} {version}"
            )
        if source is None and name == "rpds-py" and expression is None:
            expression = "MIT"
        if not isinstance(expression, str) or expression not in RUST_SELECTED_LICENSES:
            raise RuntimeError(
                f"rpds Rust dependency {name} {version} has an unreviewed license: {expression}"
            )
        if (
            source is not None
            and source != "registry+https://github.com/rust-lang/crates.io-index"
        ):
            raise RuntimeError(
                f"cargo metadata has an unreviewed source for {name} {version}: {source}"
            )
        key = (name, version, source)
        if key in metadata_keys or key not in lock_records:
            raise RuntimeError(
                f"cargo metadata package {name} {version} does not map uniquely to Cargo.lock"
            )
        metadata_keys.add(key)
        checksum = lock_records[key]
        if source is not None and checksum is None:
            raise RuntimeError(
                f"registry package {name} {version} has no Cargo.lock checksum"
            )

        package_root = Path(manifest_path).resolve().parent
        if source is None and package_root != crate_root.resolve():
            raise RuntimeError(
                f"cargo root package {name} {version} is outside the locked crate root"
            )
        if source is not None and package_root.name != f"{name}-{version}":
            raise RuntimeError(
                f"cargo registry package path does not match {name} {version}"
            )
        authors = package.get("authors") or []
        repository = package.get("repository")
        if not isinstance(authors, list) or not all(
            isinstance(author, str) for author in authors
        ):
            raise RuntimeError(
                f"cargo metadata has invalid authors for {name} {version}"
            )
        if repository is not None and not isinstance(repository, str):
            raise RuntimeError(
                f"cargo metadata has an invalid repository for {name} {version}"
            )

        files: list[dict] = []
        for candidate in _rust_license_candidates(package_root):
            digest = _sha256_file(candidate)
            target = texts_root / f"{digest[:16]}-{candidate.name}"
            if target.exists() and _sha256_file(target) != digest:
                raise RuntimeError(
                    f"Rust license destination collision for {candidate.name}"
                )
            if not target.exists():
                shutil.copy2(candidate, target)
            files.append(
                {
                    "path": target.relative_to(destination).as_posix(),
                    "sha256": digest,
                    "size": target.stat().st_size,
                }
            )
        if not files:
            raise RuntimeError(
                f"Rust dependency {name} {version} has no packaged license text"
            )
        package_records.append(
            {
                "authors": authors,
                "checksum": checksum,
                "license_expression": expression,
                "license_files": files,
                "name": name,
                "repository": repository,
                "selected_license": RUST_SELECTED_LICENSES[expression],
                "source": source,
                "version": version,
            }
        )

    if metadata_keys != set(lock_records):
        missing = sorted(set(lock_records) - metadata_keys)
        raise RuntimeError(
            f"cargo metadata omitted {len(missing)} Cargo.lock package(s): {missing[:3]}"
        )
    roots = [record for record in package_records if record["source"] is None]
    if len(roots) != 1 or roots[0]["name"] != "rpds-py":
        raise RuntimeError("cargo metadata does not identify one rpds-py root package")
    manifest = {
        "cargo_lock_sha256": _sha256_file(crate_root / "Cargo.lock"),
        "kind": "staticpython-rust-license-manifest",
        "license_expression": RPDS_LICENSE_EXPRESSION,
        "package_count": len(package_records),
        "packages": package_records,
        "root_package": {"name": roots[0]["name"], "version": roots[0]["version"]},
        "schema_version": 1,
    }
    manifest_path = destination / "rust-dependencies.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    generated = sorted(
        (path for path in destination.rglob("*") if path.is_file()),
        key=lambda path: path.as_posix().casefold(),
    )
    return generated, manifest


def _run_captured(command: list[str], *, cwd: Path, timeout: int = 60) -> str:
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return completed.stdout.strip()


def _parse_rustc_verbose_version(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines:
        fields["version"] = lines[0]
    for line in lines[1:]:
        key, separator, value = line.partition(":")
        if separator and key and value.strip():
            fields[key.strip().replace("-", "_")] = value.strip()
    return fields


def _write_pyo3_config(context) -> Path:
    config_path = source_path(context, "PCbuild/rpds_pyo3_config.txt")
    write_source_text(
        context,
        config_path.relative_to(context.source_root).as_posix(),
        "\n".join(
            [
                "implementation=CPython",
                f"version={context.version_mm}",
                "shared=false",
                "abi3=false",
                "pointer_width=64",
                "build_flags=",
                f"lib_dir={PYO3_STATIC_LIB_DIR_SENTINEL}",
                "suppress_build_script_link_lines=true",
                "",
            ]
        ),
    )
    return config_path


def _cargo_encoded_rustflags(source_root: Path, target_root: Path) -> str:
    return "\x1f".join(
        [
            "-C",
            "target-feature=+crt-static",
            f"--remap-path-prefix={source_root.resolve()}=C:/staticpython/source",
            f"--remap-path-prefix={target_root.resolve()}=C:/staticpython/target",
        ]
    )


def build_rpds_static_library(context) -> None:
    if (
        context.configuration.casefold() != "release"
        or context.platform.casefold() != "x64"
    ):
        raise RuntimeError("rpds supports only Release|x64 static builds")
    rustup = shutil.which("rustup")
    if rustup is None:
        raise RuntimeError(f"rpds requires rustup with pinned Rust {RUST_TOOLCHAIN}")
    toolchain_command = [rustup, "run", RUST_TOOLCHAIN]
    try:
        rustc_output = _run_captured(
            [*toolchain_command, "rustc", "-Vv"],
            cwd=context.source_root,
        )
        cargo_output = _run_captured(
            [*toolchain_command, "cargo", "-V"],
            cwd=context.source_root,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"rpds requires installed Rust {RUST_TOOLCHAIN}") from exc
    rustc = _parse_rustc_verbose_version(rustc_output)
    if not rustc.get("version", "").startswith(f"rustc {RUST_TOOLCHAIN} "):
        raise RuntimeError(f"unexpected rpds rustc version: {rustc.get('version')!r}")
    if not cargo_output.startswith(f"cargo {RUST_TOOLCHAIN} "):
        raise RuntimeError(f"unexpected rpds cargo version: {cargo_output!r}")
    if rustc.get("host") != RUST_TARGET:
        raise RuntimeError(
            f"rpds Rust host must be {RUST_TARGET}, found {rustc.get('host')!r}"
        )

    crate_root = source_path(context, "rpds_builtin")
    cargo_toml = crate_root / "Cargo.toml"
    cargo_lock = crate_root / "Cargo.lock"
    if not cargo_toml.is_file() or not cargo_lock.is_file():
        raise RuntimeError("rpds Cargo.toml or Cargo.lock is missing")
    pyo3_config = _write_pyo3_config(context)
    target_root = source_path(context, RUST_TARGET_ROOT)
    target_root.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.pop("RUSTFLAGS", None)
    environment.update(
        {
            "CARGO_ENCODED_RUSTFLAGS": _cargo_encoded_rustflags(
                context.source_root, target_root
            ),
            "CARGO_INCREMENTAL": "0",
            "CARGO_TARGET_DIR": str(target_root),
            "PYO3_BUILD_EXTENSION_MODULE": "1",
            "PYO3_CONFIG_FILE": str(pyo3_config.resolve()),
            "PYO3_USE_RAW_DYLIB": "0",
            "SOURCE_DATE_EPOCH": "0",
        }
    )
    command = [
        *toolchain_command,
        "cargo",
        "build",
        "--locked",
        "--release",
        "--target",
        RUST_TARGET,
    ]
    context.log("RUN " + subprocess.list2cmdline(command))
    subprocess.run(
        command,
        cwd=str(crate_root),
        check=True,
        env=environment,
        timeout=60 * 45,
    )
    library_path = target_root / RUST_TARGET / "release" / "rpds.lib"
    if not library_path.is_file():
        raise RuntimeError(f"rpds static library was not produced: {library_path}")

    metadata_output = _run_captured(
        [
            *toolchain_command,
            "cargo",
            "metadata",
            "--locked",
            "--format-version",
            "1",
            "--manifest-path",
            str(cargo_toml),
        ],
        cwd=crate_root,
        timeout=60 * 10,
    )
    try:
        cargo_metadata = json.loads(metadata_output)
    except json.JSONDecodeError as exc:
        raise RuntimeError("rpds cargo metadata returned invalid JSON") from exc
    rust_license_root = source_path(context, "licenses/rpds-rust")
    rust_license_files, rust_license_manifest = _collect_rust_dependency_licenses(
        crate_root,
        cargo_metadata,
        rust_license_root,
    )
    rust_license_prefix = (
        rust_license_root.relative_to(context.source_root).as_posix() + "/"
    )
    LIBRARY_INTEGRATION.license_files = [
        relative
        for relative in LIBRARY_INTEGRATION.license_files
        if not relative.startswith(rust_license_prefix)
    ]
    LIBRARY_INTEGRATION.license_files.extend(
        path.relative_to(context.source_root).as_posix() for path in rust_license_files
    )
    LIBRARY_INTEGRATION.toolchain_metadata["rust"] = {
        "cargo_version": cargo_output,
        "cargo_lock_sha256": rust_license_manifest["cargo_lock_sha256"],
        "crt_static": True,
        "license_manifest_sha256": _sha256_file(
            rust_license_root / "rust-dependencies.json"
        ),
        "locked": True,
        "package_count": rust_license_manifest["package_count"],
        "profile": "release",
        "rustc_commit_hash": rustc.get("commit_hash"),
        "rustc_version": rustc["version"],
        "target": RUST_TARGET,
        "toolchain": RUST_TOOLCHAIN,
    }
    context.log(
        f"built {library_path.relative_to(context.source_root)} with {rustc['version']}"
    )


LIBRARY_INTEGRATION = pypi_library(
    name="rpds",
    project_name="rpds-py",
    release_version=RPDS_VERSION,
    source_archive_sha256_by_version={RPDS_VERSION: RPDS_SDIST_SHA256},
    source_mapping={
        "Cargo.toml": "rpds_builtin/Cargo.toml",
        "Cargo.lock": "rpds_builtin/Cargo.lock",
        "build.rs": "rpds_builtin/build.rs",
        "src": "rpds_builtin/src",
        "rpds.pyi": "Lib/rpds.pyi",
        "pyproject.toml": "rpds_builtin/pyproject.toml",
        "README.rst": "rpds_builtin/README.rst",
        "LICENSE": "rpds_builtin/LICENSE",
    },
    python_packages=["rpds"],
    top_level_import_names=["rpds"],
    builtin_module_registrations=[
        {
            "name": "rpds",
            "pyinit": "PyInit_rpds",
            "library": RUST_LIBRARY_NAME,
        }
    ],
    staged_static_libraries_release_x64=[
        {
            "source_glob": f"{RUST_TARGET_ROOT}/{RUST_TARGET}/release/rpds.lib",
            "target_name": RUST_LIBRARY_NAME,
        }
    ],
    python_link_dependencies_release_x64=[RUST_LIBRARY_NAME, *RUST_SYSTEM_LIBRARIES],
    patch_rules=[
        {
            "package": f"=={RPDS_VERSION}",
            "path": "rpds_builtin/Cargo.toml",
            "replacements": [
                {
                    "old": 'crate-type = ["cdylib"]',
                    "new": 'crate-type = ["staticlib"]',
                    "count": 1,
                }
            ],
        }
    ],
    source_ignore_patterns=["tests", "__pycache__", "*.so", "*.pyd", "*.dll"],
    license_expression=RPDS_LICENSE_EXPRESSION,
    license_files=["rpds_builtin/LICENSE"],
    smoke_tests=[
        {
            "name": "persistent-map-list",
            "kind": "inline",
            "code": (
                "from rpds import HashTrieMap, List; "
                "mapping=HashTrieMap({'answer': 42}); "
                "assert mapping['answer'] == 42; "
                "assert list(List([1, 2])) == [1, 2]"
            ),
        }
    ],
    toolchain_metadata={
        "rust": {
            "crt_static": True,
            "locked": True,
            "profile": "release",
            "target": RUST_TARGET,
            "toolchain": RUST_TOOLCHAIN,
        }
    },
    pre_build_hooks=[build_rpds_static_library],
)
