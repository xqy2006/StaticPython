from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import build
import libs


DEFAULT_TAGS = ("v3.11.15", "v3.12.13", "v3.13.13", "v3.14.4", "v3.15.0a8")


@dataclass
class PhaseResult:
    name: str
    status: str
    detail: str = ""


def run_git(cpython_repo: Path, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cpython_repo), *args],
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def safe_name(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]+", "-", value).strip("-")


def remove_tree(path: Path, work_root: Path) -> None:
    resolved = path.resolve()
    root = work_root.resolve()
    if resolved == root or root not in resolved.parents:
        raise RuntimeError(f"refusing to remove path outside work root: {resolved}")
    if path.exists():
        shutil.rmtree(path)


def remove_worktree(cpython_repo: Path, path: Path, work_root: Path) -> None:
    if not path.exists():
        return
    run_git(cpython_repo, ["worktree", "remove", "--force", str(path)], check=False)
    remove_tree(path, work_root)


def assert_contains(path: Path, needle: str) -> None:
    text = path.read_text(encoding="utf-8")
    if needle not in text:
        raise AssertionError(f"{path.relative_to(path.parents[1])} does not contain {needle!r}")


def assert_not_contains(path: Path, needle: str) -> None:
    text = path.read_text(encoding="utf-8")
    if needle in text:
        raise AssertionError(f"{path.relative_to(path.parents[1])} unexpectedly contains {needle!r}")


def assert_file(path: Path) -> None:
    if not path.is_file():
        raise AssertionError(f"expected file missing: {path}")


def frozen_struct_has_get_code(source_root: Path) -> bool:
    import_h = source_root / "Include" / "cpython" / "import.h"
    text = import_h.read_text(encoding="utf-8")
    match = re.search(r"struct\s+_frozen\s*\{(?P<body>.*?)\};", text, flags=re.DOTALL)
    return match is not None and "get_code" in match.group("body")


def symbol_from_frozen_include(include_name: str) -> str:
    module_name = include_name[:-2]
    return "_Py_M__" + re.sub(r"[^0-9A-Za-z]", "_", module_name)


def synthesize_frozen_headers(source_root: Path) -> int:
    frozen_c = source_root / "Python" / "frozen.c"
    text = frozen_c.read_text(encoding="utf-8")
    includes = re.findall(r'^#include "frozen_modules/([^"\r\n]+\.h)"\r?$', text, re.MULTILINE)
    frozen_modules = source_root / "Python" / "frozen_modules"
    frozen_modules.mkdir(parents=True, exist_ok=True)
    for index, include_name in enumerate(includes):
        target = frozen_modules / include_name
        target.parent.mkdir(parents=True, exist_ok=True)
        symbol = symbol_from_frozen_include(include_name)
        target.write_text(
            f"const unsigned char {symbol}[] = {{\n"
            f"    {index % 251},\n"
            f"    {(index + 1) % 251},\n"
            "};\n",
            encoding="utf-8",
            newline="\n",
        )
    return len(includes)


def run_phase(results: list[PhaseResult], name: str, func) -> bool:
    try:
        func()
    except Exception as exc:
        results.append(PhaseResult(name, "FAIL", f"{type(exc).__name__}: {exc}"))
        return False
    results.append(PhaseResult(name, "OK"))
    return True


def run_patch_phases(source_root: Path, manifest: dict, version_info: tuple[int, int, int], version_mm: str, version_full: str) -> list[PhaseResult]:
    integrations: list = []
    results: list[PhaseResult] = []
    phases = [
        ("copy_overlay_entries", lambda: build.copy_overlay_entries(source_root, build.ASSET_ROOT, manifest, integrations, version_info)),
        ("patch_site_py", lambda: build.patch_site_py(source_root, version_mm)),
        ("patch_modules_getpath_py", lambda: build.patch_modules_getpath_py(source_root)),
        ("patch_generate_sbom_py", lambda: build.patch_generate_sbom_py(source_root)),
        ("patch_pc_config_minimal_c", lambda: build.patch_pc_config_minimal_c(source_root)),
        ("patch_pc_dl_nt_c", lambda: build.patch_pc_dl_nt_c(source_root)),
        ("patch_python_sysmodule_c", lambda: build.patch_python_sysmodule_c(source_root, version_mm)),
        ("patch_pyproject_props", lambda: build.patch_pyproject_props(source_root)),
        ("patch_pythoncore_vcxproj", lambda: build.patch_pythoncore_vcxproj(source_root)),
        ("patch_freeze_module_vcxproj", lambda: build.patch_freeze_module_vcxproj(source_root)),
        ("patch_python_vcxproj", lambda: build.patch_python_vcxproj(source_root, manifest, integrations)),
        ("patch_static_library_projects", lambda: build.patch_static_library_projects(source_root, manifest, integrations)),
        ("patch_pc_config", lambda: build.patch_pc_config(source_root, manifest, integrations)),
        ("write_runtime_resource_module", lambda: build.write_runtime_resource_module(source_root, integrations)),
    ]
    for pass_name in ("first", "second"):
        for phase_name, phase in phases:
            if not run_phase(results, f"{pass_name}:{phase_name}", phase):
                return results
    return results


def validate_patched_tree(source_root: Path, version_info: tuple[int, int, int], version_mm: str) -> None:
    site_py = source_root / "Lib" / "site.py"
    assert_contains(site_py, f'ver_nodot = "{version_mm}".replace(\'.\', \'\')')
    assert_contains(site_py, "def _staticpython_install_runtime_resources():")

    assert_file(source_root / "Lib" / "_staticpython_runtime.py")
    assert_file(source_root / "Tools" / "build" / "freeze_modules.py")
    pyrepl_overlay = source_root / "Lib" / "_pyrepl" / "__main__.py"
    if version_info >= build.PYREPL_MIN_VERSION:
        assert_file(pyrepl_overlay)

    runtime_resources = source_root / "Lib" / "_staticpython_runtime_resources.py"
    assert_file(runtime_resources)
    assert_contains(runtime_resources, 'RESOURCE_PAYLOAD_ENCODING = "zlib+b85"')
    assert_contains(runtime_resources, "RESOURCE_GROUPS")
    assert_file(source_root / "Python" / "staticpython_resource_store.c")

    sysmodule_c = source_root / "Python" / "sysmodule.c"
    assert_contains(sysmodule_c, "GetModuleHandle(NULL)")
    assert_contains(sysmodule_c, f'SET_SYS_FROM_STRING("winver", "{version_mm}")')

    pythoncore = source_root / "PCbuild" / "pythoncore.vcxproj"
    assert_contains(pythoncore, "<ConfigurationType>StaticLibrary</ConfigurationType>")
    assert_contains(pythoncore, "..\\Python\\staticpython_resource_store.c")
    assert_contains(pythoncore, "Py_NO_ENABLE_SHARED")
    assert_contains(pythoncore, "<VcpkgEnabled>false</VcpkgEnabled>")
    assert_contains(pythoncore, "<AdditionalOptions Condition=\"'$(Configuration)|$(Platform)'=='Release|x64'\">/bigobj /GL- %(AdditionalOptions)</AdditionalOptions>")
    assert_not_contains(pythoncore, "<MultiProcessorCompilation")
    assert_not_contains(pythoncore, "..\\Modules\\challenge.c")
    assert_not_contains(pythoncore, "..\\Modules\\sandbox.c")

    freeze_project = source_root / "PCbuild" / "_freeze_module.vcxproj"
    assert_contains(freeze_project, "StaticPythonSkipRebuildFrozen")
    assert_contains(freeze_project, "<VcpkgEnabled>false</VcpkgEnabled>")

    python_project = source_root / "PCbuild" / "python.vcxproj"
    assert_contains(python_project, "Py_NO_ENABLE_SHARED")
    assert_contains(python_project, "%(AdditionalDependencies)")
    assert_contains(python_project, "%(AdditionalOptions)")
    if (source_root / "PCbuild" / "zlib-ng.vcxproj").exists():
        assert_contains(python_project, "zlib-ng$(PyDebugExt).lib")
    else:
        assert_not_contains(python_project, "zlib-ng$(PyDebugExt).lib")

    pc_config = source_root / "PC" / "config.c"
    assert_contains(pc_config, "PyInit__staticpython_resource_store")
    assert_contains(pc_config, '{"_staticpython_resource_store", PyInit__staticpython_resource_store},')
    assert_not_contains(pc_config, "PyInit_challenge")
    assert_not_contains(pc_config, "PyInit_sandbox")
    for builtin in build.iter_builtin_module_registrations(source_root, build.load_manifest(), []):
        assert_contains(pc_config, f'extern PyObject* {builtin["pyinit"]}(void);')
        assert_contains(pc_config, f'{{"{builtin["name"]}", {builtin["pyinit"]}}},')


def validate_verify_script_layout(source_root: Path) -> None:
    verify_script = REPO_ROOT / "scripts" / "full_profile_verify.py"
    text = verify_script.read_text(encoding="utf-8")
    if "'nest-asyncio-smoke'" in text:
        raise AssertionError("nest-asyncio smoke should not run inline in full_profile_verify.py")
    if '"name": "nest-asyncio-runtime"' not in text:
        raise AssertionError("nest-asyncio runtime subprocess smoke is missing from full_profile_verify.py")
    runtime_script = REPO_ROOT / "scripts" / "nest_asyncio_runtime.py"
    if not runtime_script.is_file():
        raise AssertionError("scripts/nest_asyncio_runtime.py is missing")
    runtime_text = runtime_script.read_text(encoding="utf-8")
    for snippet in ("import anyio", "import sniffio", "from starlette.testclient import TestClient", "anyio.run(probe)"):
        if snippet not in runtime_text:
            raise AssertionError(f"nest_asyncio runtime coverage is missing snippet: {snippet}")


def validate_nest_asyncio_patch_applied(source_root: Path) -> None:
    config = build.load_manifest()
    repo_config = build.load_config()
    integrations = libs.load_integrations(
        REPO_ROOT / "Lib",
        ["nest_asyncio"],
        target_version=build.Version("3.15.0"),
        library_catalog=repo_config["third_party_library_catalog"],
    )
    version_info, version_mm, version_full = build.parse_cpython_version(source_root)
    hook_context = build.make_library_hook_context(
        source_root,
        version_info,
        version_mm,
        version_full,
        "Release",
        "x64",
    )
    libs.run_prepare_source_hooks(integrations, hook_context)
    libs.run_post_patch_hooks(integrations, hook_context)

    target = source_root / "Lib" / "nest_asyncio.py"
    if not target.is_file():
        raise AssertionError("Lib/nest_asyncio.py is missing from patched source tree")
    text = target.read_text(encoding="utf-8")
    required_snippets = [
        "asyncio.tasks._py_register_task = asyncio.tasks._c_register_task",
        "task_current = getattr(asyncio.tasks, '_py_current_task', None)",
        "task_swap = getattr(asyncio.tasks, '_py_swap_current_task', None)",
        "if task_current is not None and task_swap is not None:",
        "task_swap(self, None)",
        "task_swap(self, curr_task)",
    ]
    for snippet in required_snippets:
        if snippet not in text:
            raise AssertionError(f"nest_asyncio patch missing snippet: {snippet}")


def validate_overlay_freeze_step_one(source_root: Path, version_info: tuple[int, int, int]) -> list[PhaseResult]:
    results: list[PhaseResult] = []
    script = source_root / "Tools" / "build" / "freeze_modules.py"
    if not script.exists():
        results.append(PhaseResult("freeze_modules_step1", "SKIP", "Tools/build/freeze_modules.py missing"))
        return results

    completed = subprocess.run(
        [sys.executable, str(script), "--step=1"],
        cwd=str(source_root),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        results.append(
            PhaseResult(
                "freeze_modules_step1",
                "FAIL",
                f"exit {completed.returncode}: {completed.stderr.strip() or completed.stdout.strip()}",
            )
        )
        return results

    frozen_c = source_root / "Python" / "frozen.c"
    text = frozen_c.read_text(encoding="utf-8")
    has_get_code = frozen_struct_has_get_code(source_root)
    if has_get_code:
        if "GET_CODE(" in text:
            results.append(PhaseResult("freeze_modules_step1:shape", "OK", "_frozen has get_code and generated entries include get_code"))
        elif re.search(r'\{"[^"]+",\s*[A-Za-z0-9_]+,\s*\(int\)sizeof\([A-Za-z0-9_]+\),\s*(?:true|false),\s*NULL\}', text):
            results.append(PhaseResult("freeze_modules_step1:shape", "OK", "_frozen has get_code and generated entries include NULL get_code"))
        else:
            results.append(PhaseResult("freeze_modules_step1:shape", "FAIL", "generated _frozen entries do not include fifth get_code field"))
    else:
        if re.search(r'\{"[^"]+",\s*[A-Za-z0-9_]+,\s*\(int\)sizeof\([A-Za-z0-9_]+\),\s*(?:true|false),\s*(?:NULL|GET_CODE\()', text):
            results.append(PhaseResult("freeze_modules_step1:shape", "FAIL", "generated _frozen entries include unexpected fifth field"))
        else:
            results.append(PhaseResult("freeze_modules_step1:shape", "OK", "_frozen has four fields and generated entries match"))

    if version_info[:2] <= (3, 12) and frozen_struct_has_get_code(source_root):
        freeze_project = (source_root / "PCbuild" / "_freeze_module.vcxproj").read_text(encoding="utf-8")
        if "deepfreeze.py" not in freeze_project:
            results.append(PhaseResult("freeze_modules_step1:deepfreeze_rule", "FAIL", "3.11/3.12 project lost deepfreeze rule"))
        else:
            results.append(PhaseResult("freeze_modules_step1:deepfreeze_rule", "OK"))
    return results


def validate_split_frozen_modules(source_root: Path) -> list[PhaseResult]:
    results: list[PhaseResult] = []
    include_count = synthesize_frozen_headers(source_root)
    if include_count == 0:
        results.append(PhaseResult("split_frozen_modules", "SKIP", "no frozen module includes"))
        return results

    if not run_phase(results, "split_frozen_modules:first", lambda: build.split_frozen_modules(source_root)):
        return results
    if not run_phase(results, "split_frozen_modules:second", lambda: build.split_frozen_modules(source_root)):
        return results

    python_dir = source_root / "Python"
    shards = sorted(python_dir.glob(f"{build.FROZEN_DATA_SOURCE_PREFIX}*.c"))
    if not shards:
        raise AssertionError("split_frozen_modules did not create any staticpython_frozen_data shard")
    if any(re.search(r"_\d{3}\.c$", shard.name) for shard in shards):
        raise AssertionError("split_frozen_modules created a legacy three-digit shard name")
    if any(not re.search(r"_\d{6}\.c$", shard.name) for shard in shards):
        raise AssertionError("split_frozen_modules created a shard without six-digit numbering")

    frozen_c = source_root / "Python" / "frozen.c"
    assert_not_contains(frozen_c, '#include "frozen_modules/')
    assert_not_contains(frozen_c, "(int)sizeof(")
    assert_contains(frozen_c, "Frozen module bytecode data is compiled in StaticPython shards.")

    pythoncore = source_root / "PCbuild" / "pythoncore.vcxproj"
    assert_contains(pythoncore, f"..\\Python\\{shards[0].name}")
    legacy_deepfreeze = source_root / "Python" / "deepfreeze" / "deepfreeze.c"
    if frozen_struct_has_get_code(source_root):
        assert_contains(pythoncore, "..\\Python\\deepfreeze\\deepfreeze.c")
        assert_file(legacy_deepfreeze)
        stub_text = legacy_deepfreeze.read_text(encoding="utf-8")
        for symbol in ("_Py_Deepfreeze_Init", "_Py_Deepfreeze_Fini", "_Py_next_func_version"):
            if symbol not in stub_text:
                raise AssertionError(f"legacy deepfreeze stub does not define {symbol}")
    else:
        assert_not_contains(pythoncore, "..\\Python\\deepfreeze\\deepfreeze.c")
        if legacy_deepfreeze.exists():
            raise AssertionError("legacy deepfreeze stub was created for a non-legacy CPython tree")
    assert_not_contains(pythoncore, "<MultiProcessorCompilation")
    results.append(PhaseResult("split_frozen_modules:assertions", "OK", f"{len(shards)} shard(s), {include_count} header(s)"))
    return results


def validate_tag(cpython_repo: Path, tag: str, work_root: Path, keep_worktrees: bool) -> tuple[bool, list[PhaseResult], str]:
    worktree = work_root / safe_name(tag)
    remove_worktree(cpython_repo, worktree, work_root)
    run_git(cpython_repo, ["rev-parse", "--verify", f"{tag}^{{commit}}"])
    run_git(cpython_repo, ["worktree", "add", "--detach", str(worktree), tag])

    results: list[PhaseResult] = []
    detail = ""
    ok = False
    try:
        build.verify_source_root(worktree)
        version_info, version_mm, version_full = build.parse_cpython_version(worktree)
        manifest = build.load_manifest()
        results.extend(run_patch_phases(worktree, manifest, version_info, version_mm, version_full))
        if any(result.status == "FAIL" for result in results):
            return False, results, version_full
        run_phase(results, "validate_patched_tree", lambda: validate_patched_tree(worktree, version_info, version_mm))
        if any(result.status == "FAIL" for result in results):
            return False, results, version_full
        run_phase(results, "validate_nest_asyncio_patch_applied", lambda: validate_nest_asyncio_patch_applied(worktree))
        if any(result.status == "FAIL" for result in results):
            return False, results, version_full
        run_phase(results, "validate_verify_script_layout", lambda: validate_verify_script_layout(worktree))
        if any(result.status == "FAIL" for result in results):
            return False, results, version_full
        results.extend(validate_overlay_freeze_step_one(worktree, version_info))
        if any(result.status == "FAIL" for result in results):
            return False, results, version_full
        try:
            results.extend(validate_split_frozen_modules(worktree))
        except Exception as exc:
            results.append(PhaseResult("split_frozen_modules:assertions", "FAIL", f"{type(exc).__name__}: {exc}"))
            return False, results, version_full
        ok = not any(result.status == "FAIL" for result in results)
        return ok, results, version_full
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        results.append(PhaseResult("tag_setup_or_validation", "FAIL", detail))
        return False, results, tag
    finally:
        if keep_worktrees:
            print(f"[staticpython-patch-matrix] kept worktree for {tag}: {worktree}", flush=True)
        else:
            remove_worktree(cpython_repo, worktree, work_root)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate StaticPython CPython source patches across CPython tags.")
    parser.add_argument("--cpython-repo", type=Path, default=Path(r"D:\cpython"))
    parser.add_argument("--work-root", type=Path, default=REPO_ROOT / ".tmp" / "cpython-patch-matrix")
    parser.add_argument("--tag", action="append", dest="tags", help="CPython tag or ref to test. Repeatable.")
    parser.add_argument("--keep-worktrees", action="store_true", help="Keep temporary CPython worktrees for debugging.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cpython_repo = args.cpython_repo.resolve()
    work_root = args.work_root.resolve()
    tags = tuple(args.tags or DEFAULT_TAGS)
    work_root.mkdir(parents=True, exist_ok=True)

    failures = 0
    for tag in tags:
        print(f"[staticpython-patch-matrix] testing {tag}", flush=True)
        ok, results, version_full = validate_tag(cpython_repo, tag, work_root, args.keep_worktrees)
        status = "OK" if ok else "FAIL"
        print(f"[staticpython-patch-matrix] {tag} ({version_full}): {status}", flush=True)
        for result in results:
            suffix = f" - {result.detail}" if result.detail else ""
            print(f"[staticpython-patch-matrix]   {result.status:<4} {result.name}{suffix}", flush=True)
        if not ok:
            failures += 1

    if failures:
        print(f"[staticpython-patch-matrix] {failures} tag(s) failed", flush=True)
        return 1
    print(f"[staticpython-patch-matrix] all {len(tags)} tag(s) passed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
