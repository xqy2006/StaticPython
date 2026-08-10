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


PYDANTIC_CORE_VERSION = "2.47.0"
PYDANTIC_CORE_PYDANTIC_STABLE_VERSION = "2.46.4"
PYDANTIC_CORE_SDIST_SHA256_BY_VERSION = {
    PYDANTIC_CORE_PYDANTIC_STABLE_VERSION: (
        "62f875393d7f270851f20523dd2e29f082bcc82292d66db2b64ea71f64b6e1c1"
    ),
    PYDANTIC_CORE_VERSION: (
        "422c1797a7864b2a9a996435aba92fe571fb80190f67a31edbc1ac040c7b51fe"
    ),
}
RUST_TOOLCHAIN = "1.88.0"
RUST_TARGET = "x86_64-pc-windows-msvc"
RUST_LIBRARY_NAME = "pydantic_core._pydantic_core.lib"
RUST_TARGET_ROOT = "PCbuild/pydantic_core_rust_target"
RUST_SYSTEM_LIBRARIES = [
    "advapi32.lib",
    "bcrypt.lib",
    "kernel32.lib",
    "ntdll.lib",
    "userenv.lib",
    "ws2_32.lib",
]
PYDANTIC_CORE_LICENSE_EXPRESSION = (
    "Apache-2.0 AND (Apache-2.0 WITH LLVM-exception) AND MIT AND "
    "Unicode-3.0 AND Unicode-DFS-2016 AND Zlib"
)
RUST_LICENSE_EXPRESSIONS = {
    "(MIT OR Apache-2.0) AND Unicode-DFS-2016",
    "Apache-2.0 OR MIT",
    "Apache-2.0 WITH LLVM-exception",
    "Apache-2.0 WITH LLVM-exception OR Apache-2.0 OR MIT",
    "BSD-2-Clause OR Apache-2.0 OR MIT",
    "MIT",
    "MIT OR Apache-2.0",
    "MIT OR Apache-2.0 OR LGPL-2.1-or-later",
    "MIT/Apache-2.0",
    "Unicode-3.0",
    "Unlicense OR MIT",
    "Zlib",
}
RUST_SELECTED_LICENSES = {
    "(MIT OR Apache-2.0) AND Unicode-DFS-2016": "MIT AND Unicode-DFS-2016",
    "Apache-2.0 OR MIT": "MIT",
    "Apache-2.0 WITH LLVM-exception": "Apache-2.0 WITH LLVM-exception",
    "Apache-2.0 WITH LLVM-exception OR Apache-2.0 OR MIT": "MIT",
    "BSD-2-Clause OR Apache-2.0 OR MIT": "MIT",
    "MIT": "MIT",
    "MIT OR Apache-2.0": "MIT",
    "MIT OR Apache-2.0 OR LGPL-2.1-or-later": "MIT",
    "MIT/Apache-2.0": "MIT",
    "Unicode-3.0": "Unicode-3.0",
    "Unlicense OR MIT": "MIT",
    "Zlib": "Zlib",
}
RUST_LICENSE_FILE_PATTERN = re.compile(
    r"^(?:LICENSE|COPYING|NOTICE|UNLICENSE|COPYRIGHT)",
    re.IGNORECASE,
)
RUST_APACHE_FALLBACK_PACKAGES = {
    ("r-efi", "5.2.0"),
    ("wit-bindgen-rt", "0.39.0"),
}


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
            raise RuntimeError("pydantic-core Cargo.lock contains an invalid package record")
        name = raw.get("name")
        version = raw.get("version")
        source = raw.get("source")
        checksum = raw.get("checksum")
        if not isinstance(name, str) or not isinstance(version, str):
            raise RuntimeError("pydantic-core Cargo.lock contains an unnamed package")
        if source is not None and not isinstance(source, str):
            raise RuntimeError(f"pydantic-core Cargo.lock has an invalid source for {name} {version}")
        if checksum is not None and (
            not isinstance(checksum, str)
            or re.fullmatch(r"[0-9a-f]{64}", checksum) is None
        ):
            raise RuntimeError(f"pydantic-core Cargo.lock has an invalid checksum for {name} {version}")
        key = (name, version, source)
        if key in records:
            raise RuntimeError(f"pydantic-core Cargo.lock repeats {name} {version}")
        records[key] = checksum
    if not records:
        raise RuntimeError("pydantic-core Cargo.lock contains no packages")
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
        raise RuntimeError("cargo metadata contains no pydantic-core packages")
    lock_records = _cargo_lock_records(crate_root / "Cargo.lock")
    metadata_keys: set[tuple[str, str, str | None]] = set()
    package_records: list[dict] = []
    apache_fallback_texts: list[str] = []

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
        if not all(isinstance(value, str) and value for value in (name, version, expression, manifest_path)):
            raise RuntimeError("cargo metadata contains incomplete package license metadata")
        if source is not None and not isinstance(source, str):
            raise RuntimeError(f"cargo metadata has an invalid source for {name} {version}")
        if source is not None and source != "registry+https://github.com/rust-lang/crates.io-index":
            raise RuntimeError(f"cargo metadata has an unreviewed source for {name} {version}: {source}")
        if expression not in RUST_LICENSE_EXPRESSIONS:
            raise RuntimeError(
                f"pydantic-core Rust dependency {name} {version} has an unreviewed license: {expression}"
            )
        key = (name, version, source)
        if key in metadata_keys or key not in lock_records:
            raise RuntimeError(
                f"cargo metadata package {name} {version} does not map uniquely to Cargo.lock"
            )
        metadata_keys.add(key)
        checksum = lock_records[key]
        if source is not None and checksum is None:
            raise RuntimeError(f"registry package {name} {version} has no Cargo.lock checksum")

        package_root = Path(manifest_path).resolve().parent
        if not package_root.is_dir():
            raise RuntimeError(f"cargo package root does not exist for {name} {version}")
        if source is None and package_root != crate_root.resolve():
            raise RuntimeError(f"cargo root package {name} {version} is outside the locked crate root")
        if source is not None and package_root.name != f"{name}-{version}":
            raise RuntimeError(f"cargo registry package path does not match {name} {version}")
        authors = package.get("authors") or []
        repository = package.get("repository")
        if not isinstance(authors, list) or not all(isinstance(author, str) for author in authors):
            raise RuntimeError(f"cargo metadata has invalid authors for {name} {version}")
        if repository is not None and not isinstance(repository, str):
            raise RuntimeError(f"cargo metadata has an invalid repository for {name} {version}")
        files: list[dict] = []
        for candidate in _rust_license_candidates(package_root):
            if not candidate.resolve().is_relative_to(package_root):
                raise RuntimeError(f"Rust license file escapes package root: {candidate}")
            digest = _sha256_file(candidate)
            target = texts_root / f"{digest[:16]}-{candidate.name}"
            if target.exists():
                if _sha256_file(target) != digest:
                    raise RuntimeError(f"Rust license destination collision for {candidate.name}")
            else:
                shutil.copy2(candidate, target)
            relative = target.relative_to(destination).as_posix()
            files.append(
                {
                    "path": relative,
                    "sha256": digest,
                    "size": target.stat().st_size,
                }
            )
            if (
                candidate.name.casefold() == "license-apache"
                and "Apache-2.0" in expression
            ):
                apache_fallback_texts.append(relative)

        selected_license = RUST_SELECTED_LICENSES[expression]
        if not files:
            if (name, version) not in RUST_APACHE_FALLBACK_PACKAGES:
                raise RuntimeError(f"Rust dependency {name} {version} has no packaged license text")
            if "Apache-2.0" not in expression:
                raise RuntimeError(f"Rust dependency {name} {version} cannot use the Apache fallback")
            selected_license = "Apache-2.0"

        package_records.append(
            {
                "authors": list(package.get("authors") or []),
                "checksum": checksum,
                "license_expression": expression,
                "license_files": files,
                "name": name,
                "repository": repository,
                "selected_license": selected_license,
                "source": source,
                "version": version,
            }
        )

    if metadata_keys != set(lock_records):
        missing = sorted(set(lock_records) - metadata_keys)
        raise RuntimeError(
            f"cargo metadata omitted {len(missing)} Cargo.lock package(s): {missing[:3]}"
        )
    fallback_path = min(apache_fallback_texts, default=None)
    if fallback_path is None and any(not record["license_files"] for record in package_records):
        raise RuntimeError("pydantic-core Rust dependencies need a packaged Apache-2.0 text")
    if fallback_path is not None:
        fallback_file = destination / fallback_path
        fallback_record = {
            "path": fallback_path,
            "sha256": _sha256_file(fallback_file),
            "size": fallback_file.stat().st_size,
        }
        for record in package_records:
            if not record["license_files"]:
                record["license_files"] = [fallback_record]

    root_packages = [record for record in package_records if record["source"] is None]
    if len(root_packages) != 1 or root_packages[0]["name"] != "pydantic-core":
        raise RuntimeError("cargo metadata does not identify one pydantic-core root package")
    manifest = {
        "cargo_lock_sha256": _sha256_file(crate_root / "Cargo.lock"),
        "kind": "staticpython-rust-license-manifest",
        "license_expression": PYDANTIC_CORE_LICENSE_EXPRESSION,
        "package_count": len(package_records),
        "packages": package_records,
        "root_package": {
            "name": root_packages[0]["name"],
            "version": root_packages[0]["version"],
        },
        "schema_version": 1,
    }
    manifest_path = destination / "rust-dependencies.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
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
    config_path = source_path(context, "PCbuild/pydantic_core_pyo3_config.txt")
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


def build_pydantic_core_static_library(context) -> None:
    if (
        context.configuration.casefold() != "release"
        or context.platform.casefold() != "x64"
    ):
        raise RuntimeError("pydantic-core supports only Release|x64 static builds")

    rustup = shutil.which("rustup")
    if rustup is None:
        raise RuntimeError(
            f"pydantic-core requires rustup with the pinned Rust {RUST_TOOLCHAIN} toolchain"
        )
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
        raise RuntimeError(
            f"pydantic-core requires the installed Rust {RUST_TOOLCHAIN} toolchain"
        ) from exc

    rustc = _parse_rustc_verbose_version(rustc_output)
    if not rustc.get("version", "").startswith(f"rustc {RUST_TOOLCHAIN} "):
        raise RuntimeError(
            f"unexpected pydantic-core rustc version: {rustc.get('version')!r}"
        )
    if not cargo_output.startswith(f"cargo {RUST_TOOLCHAIN} "):
        raise RuntimeError(f"unexpected pydantic-core cargo version: {cargo_output!r}")
    if rustc.get("host") != RUST_TARGET:
        raise RuntimeError(
            f"pydantic-core Rust host must be {RUST_TARGET}, found {rustc.get('host')!r}"
        )

    crate_root = source_path(context, "pydantic_core_builtin")
    cargo_toml = crate_root / "Cargo.toml"
    cargo_lock = crate_root / "Cargo.lock"
    if not cargo_toml.is_file() or not cargo_lock.is_file():
        raise RuntimeError("pydantic-core Cargo.toml or Cargo.lock is missing")
    pyo3_config = _write_pyo3_config(context)
    target_root = source_path(context, RUST_TARGET_ROOT)
    target_root.mkdir(parents=True, exist_ok=True)

    environment = os.environ.copy()
    environment.pop("RUSTFLAGS", None)
    environment.update(
        {
            "CARGO_ENCODED_RUSTFLAGS": _cargo_encoded_rustflags(
                context.source_root,
                target_root,
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

    library_path = target_root / RUST_TARGET / "release" / "_pydantic_core.lib"
    if not library_path.is_file():
        raise RuntimeError(
            f"pydantic-core static library was not produced: {library_path}"
        )
    cargo_metadata_output = _run_captured(
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
        cargo_metadata = json.loads(cargo_metadata_output)
    except json.JSONDecodeError as exc:
        raise RuntimeError("cargo metadata returned invalid JSON") from exc
    rust_license_root = source_path(
        context,
        "licenses/pydantic_core-rust",
    )
    rust_license_files, rust_license_manifest = _collect_rust_dependency_licenses(
        crate_root,
        cargo_metadata,
        rust_license_root,
    )
    rust_license_prefix = rust_license_root.relative_to(context.source_root).as_posix() + "/"
    LIBRARY_INTEGRATION.license_files = [
        relative
        for relative in LIBRARY_INTEGRATION.license_files
        if not relative.startswith(rust_license_prefix)
    ]
    LIBRARY_INTEGRATION.license_files.extend(
        path.relative_to(context.source_root).as_posix()
        for path in rust_license_files
    )
    LIBRARY_INTEGRATION.license_expression = PYDANTIC_CORE_LICENSE_EXPRESSION
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
    name="pydantic_core",
    project_name="pydantic_core",
    release_version=PYDANTIC_CORE_VERSION,
    source_archive_sha256_by_version=PYDANTIC_CORE_SDIST_SHA256_BY_VERSION,
    dependencies=["typing_extensions"],
    dependency_constraints={"typing_extensions": ">=4.14.1"},
    source_mapping={
        "python/pydantic_core": "Lib/pydantic_core",
        "Cargo.toml": "pydantic_core_builtin/Cargo.toml",
        "Cargo.lock": "pydantic_core_builtin/Cargo.lock",
        "build.rs": "pydantic_core_builtin/build.rs",
        "src": "pydantic_core_builtin/src",
        ".cargo": "pydantic_core_builtin/.cargo",
        "pyproject.toml": "pydantic_core_builtin/pyproject.toml",
        "README.md": "pydantic_core_builtin/README.md",
        "LICENSE": "pydantic_core_builtin/LICENSE",
    },
    python_packages=["pydantic_core"],
    top_level_import_names=["pydantic_core"],
    builtin_module_registrations=[
        {
            "name": "pydantic_core._pydantic_core",
            "pyinit": "PyInit__pydantic_core",
            "library": RUST_LIBRARY_NAME,
        }
    ],
    staged_static_libraries_release_x64=[
        {
            "source_glob": (
                f"{RUST_TARGET_ROOT}/{RUST_TARGET}/release/_pydantic_core.lib"
            ),
            "target_name": RUST_LIBRARY_NAME,
        }
    ],
    python_link_dependencies_release_x64=[
        RUST_LIBRARY_NAME,
        *RUST_SYSTEM_LIBRARIES,
    ],
    patch_rules=[
        {
            "package": f"=={PYDANTIC_CORE_PYDANTIC_STABLE_VERSION}",
            "path": "pydantic_core_builtin/Cargo.toml",
            "replacements": [
                {
                    "old": 'crate-type = ["cdylib", "rlib"]',
                    "new": 'crate-type = ["staticlib", "rlib"]',
                    "count": 1,
                }
            ],
        },
        {
            "package": f"=={PYDANTIC_CORE_VERSION}",
            "path": "pydantic_core_builtin/Cargo.toml",
            "replacements": [
                {
                    "old": 'crate-type = ["cdylib", "rlib"]',
                    "new": 'crate-type = ["staticlib", "rlib"]',
                    "count": 1,
                }
            ],
        }
    ],
    source_ignore_patterns=["tests", "__pycache__", "*.so", "*.pyd", "*.dll"],
    license_expression=PYDANTIC_CORE_LICENSE_EXPRESSION,
    license_files=["pydantic_core_builtin/LICENSE"],
    smoke_tests=[
        {
            "name": "schema-validator-and-json",
            "kind": "inline",
            "code": (
                "import pydantic_core as pc; "
                "assert pc.__version__ in ('2.46.4', '2.47.0'); "
                "validator=pc.SchemaValidator({'type':'int'}); "
                "assert validator.validate_python('7') == 7; "
                "assert pc.from_json(b'{\"ok\":true}') == {'ok': True}"
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
    pre_build_hooks=[build_pydantic_core_static_library],
)
