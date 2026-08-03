from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from libs import pypi_library, source_path, write_source_text


PYDANTIC_CORE_VERSION = "2.47.0"
PYDANTIC_CORE_SDIST_SHA256 = (
    "422c1797a7864b2a9a996435aba92fe571fb80190f67a31edbc1ac040c7b51fe"
)
RUST_TOOLCHAIN = "1.88.0"
RUST_TARGET = "x86_64-pc-windows-msvc"
RUST_LIBRARY_NAME = "pydantic_core._pydantic_core.lib"
RUST_TARGET_ROOT = "PCbuild/pydantic_core_rust_target"
RUST_SYSTEM_LIBRARIES = [
    "advapi32.lib",
    "bcrypt.lib",
    "kernel32.lib",
    "userenv.lib",
    "ws2_32.lib",
]


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

    remap_source = str(context.source_root.resolve())
    remap_target = str(target_root.resolve())
    rustflags = " ".join(
        [
            "-C target-feature=+crt-static",
            f"--remap-path-prefix={remap_source}=C:/staticpython/source",
            f"--remap-path-prefix={remap_target}=C:/staticpython/target",
        ]
    )
    environment = os.environ.copy()
    environment.update(
        {
            "CARGO_INCREMENTAL": "0",
            "CARGO_TARGET_DIR": str(target_root),
            "PYO3_BUILD_EXTENSION_MODULE": "1",
            "PYO3_CONFIG_FILE": str(pyo3_config.resolve()),
            "PYO3_USE_RAW_DYLIB": "0",
            "RUSTFLAGS": rustflags,
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
    LIBRARY_INTEGRATION.toolchain_metadata["rust"] = {
        "cargo_version": cargo_output,
        "crt_static": True,
        "locked": True,
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
    source_archive_sha256_by_version={
        PYDANTIC_CORE_VERSION: PYDANTIC_CORE_SDIST_SHA256,
    },
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
    license_expression="MIT",
    license_files=["pydantic_core_builtin/LICENSE"],
    smoke_tests=[
        {
            "name": "schema-validator-and-json",
            "kind": "inline",
            "code": (
                "import pydantic_core as pc; "
                f"assert pc.__version__ == '{PYDANTIC_CORE_VERSION}'; "
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
