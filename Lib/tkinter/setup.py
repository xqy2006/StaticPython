from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

from libs import LibraryIntegration, inline_verification_step, source_path, write_source_text
from tools import (
    download_first_available,
    ensure_tool,
    extract_source_archive,
    find_direct_child,
    find_direct_children,
    get_pcbuild_output_dir,
    load_msbuild_project,
    merge_msbuild_semicolon_list,
    msbuild_tag,
    remove_msbuild_items,
    remove_msbuild_targets,
    run,
    save_msbuild_project,
    set_or_create_property,
)


def _load_zipfs_writer():
    helper_path = Path(__file__).resolve().parents[2] / "scripts" / "tcltk_zipfs.py"
    spec = importlib.util.spec_from_file_location("_staticpython_tcltk_zipfs", helper_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load Tcl/Tk ZipFS helper: {helper_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.write_tcltk_zipfs_artifacts


write_tcltk_zipfs_artifacts = _load_zipfs_writer()


TCLTK_RELEASE = "9.0.4"
TCLTK_ABI = "9.0"
TCL_COMMIT = "c655b4770b1d6d32a8cbffd6cef59db6029fe19e"
TK_COMMIT = "584f8fcf62c320d7c341e77171188cb4d79c3725"
TCL_ARCHIVE_SHA256 = "b7765cfb10c747c22f32f54668eded51b2d29d386e302274911038c6a609be9f"
TK_ARCHIVE_SHA256 = "9d1a731333424682d7980c3469aeefadd01886a516bb53860d3772bd6b184ff7"
TCL_SOURCE_NAME = f"staticpython-tcl-{TCLTK_RELEASE}"
TK_SOURCE_NAME = f"staticpython-tk-{TCLTK_RELEASE}"
TCL_STAGED_LIBRARY = "staticpython_tcl.lib"
TK_STAGED_LIBRARY = "staticpython_tk.lib"
OPTIONAL_FREEZE_MARKER = "PCbuild/staticpython_optional_frozen_trees.txt"
ZIP_RESOURCE = "Lib/tkinter/_staticpython/tcltk-library.zip"
ZIPFS_SOURCE = "tkinter_builtin/staticpython_tkinter_zipfs.c"
PROVENANCE_FILE = "tkinter_builtin/staticpython_tcltk_provenance.json"
TCL_LICENSE = "licenses/tkinter/tcl-license.terms"
TK_LICENSE = "licenses/tkinter/tk-license.terms"
CPYTHON_LICENSE = "LICENSE"

TCLTK_SYSTEM_LIBRARIES = [
    "kernel32.lib",
    "advapi32.lib",
    "netapi32.lib",
    "user32.lib",
    "userenv.lib",
    "ws2_32.lib",
    "gdi32.lib",
    "uxtheme.lib",
    "winspool.lib",
    "shell32.lib",
    "ole32.lib",
    "oleaut32.lib",
    "uuid.lib",
    "oleacc.lib",
    "comdlg32.lib",
    "comctl32.lib",
    "imm32.lib",
]


def _tcl_source(context) -> Path:
    return source_path(context, f"externals/{TCL_SOURCE_NAME}")


def _tk_source(context) -> Path:
    return source_path(context, f"externals/{TK_SOURCE_NAME}")


def _verify_archive_hash(path: Path, expected: str, *, component: str) -> None:
    observed = hashlib.sha256(path.read_bytes()).hexdigest()
    if observed != expected:
        raise RuntimeError(
            f"{component} {TCLTK_RELEASE} source archive hash mismatch: "
            f"expected {expected}, observed {observed}"
        )


def _ensure_source_tree(
    context,
    *,
    component: str,
    repository: str,
    commit: str,
    archive_sha256: str,
    destination: Path,
    required: tuple[str, ...],
) -> Path:
    if all((destination / relative).is_file() for relative in required):
        return destination

    archive = (
        context.download_cache_root
        / "tcltk"
        / TCLTK_RELEASE
        / f"{component.lower()}-{commit}.zip"
    )
    used_source = download_first_available(
        context.log,
        [f"https://codeload.github.com/{repository}/zip/{commit}"],
        archive,
    )
    _verify_archive_hash(archive, archive_sha256, component=component)
    extract_source_archive(
        context.log,
        archive,
        destination.parent,
        final_name=destination.name,
    )
    missing = [relative for relative in required if not (destination / relative).is_file()]
    if missing:
        raise RuntimeError(
            f"{component} {TCLTK_RELEASE} source is incomplete: " + ", ".join(missing)
        )
    context.log(f"materialized {component} {TCLTK_RELEASE} from {used_source}")
    return destination


def _require_supported_cpython(context) -> None:
    if context.version_info < (3, 12, 0):
        raise RuntimeError(
            "experimental tkinter ZipFS currently requires CPython 3.12 or newer; "
            "the CPython 3.11 _tkinter Tcl 9 compatibility port is not complete"
        )
    source = source_path(context, "Modules/_tkinter.c").read_text(
        encoding="utf-8",
        errors="strict",
    )
    missing = [marker for marker in ("Tcl_Size", "TCL_SIZE_MAX") if marker not in source]
    if missing:
        raise RuntimeError(
            "CPython _tkinter is missing required Tcl 9 compatibility markers: "
            + ", ".join(missing)
        )


def _write_archive_manifest_uuid(source_root: Path, commit: str, *, component: str) -> None:
    template = source_root / "win" / "gitmanifest.in"
    prefix = template.read_text(encoding="ascii")
    if prefix not in {"git-", "git-\n", "git-\r\n"}:
        raise RuntimeError(
            f"{component} gitmanifest.in drifted from the expected 'git-' prefix"
        )
    (source_root / "manifest.uuid").write_text(
        f"git-{commit}\n",
        encoding="ascii",
        newline="\n",
    )


def prepare_tcltk_sources(context) -> None:
    _require_supported_cpython(context)
    tcl_source = _ensure_source_tree(
        context,
        component="Tcl",
        repository="tcltk/tcl",
        commit=TCL_COMMIT,
        archive_sha256=TCL_ARCHIVE_SHA256,
        destination=_tcl_source(context),
        required=(
            "generic/tcl.h",
            "generic/tclZipfs.c",
            "library/init.tcl",
            "library/encoding/cp1252.enc",
            "library/tzdata/UTC",
            "win/makefile.vc",
            "win/gitmanifest.in",
            "license.terms",
        ),
    )
    tk_source = _ensure_source_tree(
        context,
        component="Tk",
        repository="tcltk/tk",
        commit=TK_COMMIT,
        archive_sha256=TK_ARCHIVE_SHA256,
        destination=_tk_source(context),
        required=(
            "generic/tk.h",
            "library/tk.tcl",
            "library/ttk/ttk.tcl",
            "library/ttk/clamTheme.tcl",
            "library/ttk/vistaTheme.tcl",
            "library/ttk/xpTheme.tcl",
            "win/makefile.vc",
            "win/gitmanifest.in",
            "license.terms",
        ),
    )
    # Tcl/Tk's nmake rules call `git rev-parse` whenever manifest.uuid is
    # absent. Immutable GitHub source archives intentionally have no .git
    # directory, so materialize the exact pinned commit before nmake runs.
    _write_archive_manifest_uuid(tcl_source, TCL_COMMIT, component="Tcl")
    _write_archive_manifest_uuid(tk_source, TK_COMMIT, component="Tk")

    write_tcltk_zipfs_artifacts(
        tcl_source / "library",
        tk_source / "library",
        zip_path=source_path(context, ZIP_RESOURCE),
        c_path=source_path(context, ZIPFS_SOURCE),
        release_version=TCLTK_RELEASE,
        tcl_version=TCLTK_ABI,
        tk_version=TCLTK_ABI,
    )
    write_source_text(
        context,
        OPTIONAL_FREEZE_MARKER,
        "# Optional stdlib trees selected by StaticPython integrations.\ntkinter\n",
    )

    source_path(context, TCL_LICENSE).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(tcl_source / "license.terms", source_path(context, TCL_LICENSE))
    shutil.copy2(tk_source / "license.terms", source_path(context, TK_LICENSE))
    provenance = {
        "schema_version": 1,
        "release": TCLTK_RELEASE,
        "tcl": {
            "repository": "tcltk/tcl",
            "commit": TCL_COMMIT,
            "archive_sha256": TCL_ARCHIVE_SHA256,
        },
        "tk": {
            "repository": "tcltk/tk",
            "commit": TK_COMMIT,
            "archive_sha256": TK_ARCHIVE_SHA256,
        },
        "zipfs": {
            "mount": f"//zipfs:/staticpython/tcltk-{TCLTK_RELEASE}",
            "tcl_library": f"tcl{TCLTK_ABI}",
            "tk_library": f"tk{TCLTK_ABI}",
            "runtime_extraction": False,
        },
    }
    write_source_text(
        context,
        PROVENANCE_FILE,
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
    )


def _remove_c_function(text: str, function_name: str) -> tuple[str, bool]:
    pattern = re.compile(
        rf"(?m)^static\s+PyObject\s*\*\s*\r?\n{re.escape(function_name)}\(void\)\s*\r?\n\{{"
    )
    matches = list(pattern.finditer(text))
    if not matches:
        return text, False
    if len(matches) != 1:
        raise RuntimeError(f"expected one {function_name} definition, found {len(matches)}")
    start = matches[0].start()
    brace = text.find("{", matches[0].start(), matches[0].end())
    depth = 0
    end = None
    for index in range(brace, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                end = index + 1
                break
    if end is None:
        raise RuntimeError(f"could not find the end of {function_name}")
    while end < len(text) and text[end] in "\r\n":
        end += 1
    return text[:start] + text[end:], True


def _preprocessor_block_containing(text: str, token_index: int) -> tuple[int, int]:
    lines = text.splitlines(keepends=True)
    offsets: list[int] = []
    offset = 0
    token_line = None
    for index, line in enumerate(lines):
        offsets.append(offset)
        if offset <= token_index < offset + len(line):
            token_line = index
        offset += len(line)
    if token_line is None:
        raise RuntimeError("could not locate TCL_LIBRARY preprocessor line")

    stack: list[int] = []
    candidate = None
    for index, line in enumerate(lines[: token_line + 1]):
        directive = line.lstrip()
        if re.match(r"#\s*(?:if|ifdef|ifndef)\b", directive):
            stack.append(index)
        elif re.match(r"#\s*endif\b", directive):
            if not stack:
                raise RuntimeError("unbalanced preprocessor directives around TCL_LIBRARY")
            stack.pop()
    for index in reversed(stack):
        if re.match(r"#\s*ifdef\s+MS_WINDOWS\b", lines[index].lstrip()):
            candidate = index
            break
    if candidate is None:
        raise RuntimeError("TCL_LIBRARY lookup is not guarded by #ifdef MS_WINDOWS")

    depth = 0
    end_line = None
    for index in range(candidate, len(lines)):
        directive = lines[index].lstrip()
        if re.match(r"#\s*(?:if|ifdef|ifndef)\b", directive):
            depth += 1
        elif re.match(r"#\s*endif\b", directive):
            depth -= 1
            if depth == 0:
                end_line = index
                break
    if end_line is None:
        raise RuntimeError("unterminated #ifdef MS_WINDOWS around TCL_LIBRARY")
    start_offset = offsets[candidate]
    end_offset = offsets[end_line] + len(lines[end_line])
    return start_offset, end_offset


def _remove_tcl_library_environment_blocks(text: str) -> tuple[str, int]:
    token = 'GetEnvironmentVariableW(L"TCL_LIBRARY"'
    removed = 0
    while token in text:
        token_index = text.index(token)
        start, end = _preprocessor_block_containing(text, token_index)
        block = text[start:end]
        find_executable = "Tcl_FindExecutable(PyBytes_AS_STRING(cexe));"
        if find_executable in block:
            if block.count(find_executable) != 2:
                raise RuntimeError(
                    "unexpected Tcl_FindExecutable layout in TCL_LIBRARY environment block"
                )
            indent = re.search(
                r"(?m)^(\s*)Tcl_FindExecutable\(PyBytes_AS_STRING\(cexe\)\);",
                block,
            )
            if indent is None:
                raise RuntimeError("could not preserve Tcl_FindExecutable indentation")
            replacement = (
                f"{indent.group(1)}/* StaticPython never injects an external Tcl script path. */\n"
                f"{indent.group(1)}{find_executable}\n"
            )
        else:
            replacement = "    /* StaticPython resolves Tcl scripts only from the mounted ZipFS. */\n"
        text = text[:start] + replacement + text[end:]
        removed += 1
    return text, removed


def _patch_tkinter_text(text: str) -> str:
    marker = "StaticPython resolves Tcl scripts only from the mounted ZipFS"
    if marker in text and "TCL_LIBRARY" not in text and "_get_tcl_lib_path" not in text:
        return text
    text, removed_function = _remove_c_function(text, "_get_tcl_lib_path")
    text, removed_blocks = _remove_tcl_library_environment_blocks(text)
    if not removed_function:
        raise RuntimeError("CPython _tkinter.c no longer contains the expected _get_tcl_lib_path helper")
    if removed_blocks < 1:
        raise RuntimeError("CPython _tkinter.c has no guarded TCL_LIBRARY lookup to remove")
    if "TCL_LIBRARY" in text or "_get_tcl_lib_path" in text:
        raise RuntimeError("CPython _tkinter.c still contains external Tcl library discovery")
    return text


def _patch_tkappinit_text(text: str) -> str:
    declaration = "extern int StaticPython_TkinterZipfsMount(Tcl_Interp *interp);"
    restrict_declaration = (
        "extern int StaticPython_TkinterZipfsRestrictAutoPath(Tcl_Interp *interp);"
    )
    if declaration in text:
        if (
            restrict_declaration not in text
            or text.count("StaticPython_TkinterZipfsMount(interp)") != 1
            or text.count("StaticPython_TkinterZipfsRestrictAutoPath(interp)") != 1
        ):
            raise RuntimeError("tkappinit.c contains an invalid StaticPython ZipFS mount patch")
        return text
    include_anchor = '#include "tkinter.h"'
    if text.count(include_anchor) != 1:
        raise RuntimeError("tkappinit.c tkinter.h include anchor did not match exactly once")
    text = text.replace(
        include_anchor,
        include_anchor + "\n\n" + declaration + "\n" + restrict_declaration,
        1,
    )
    pattern = re.compile(r"(?m)^(\s*)if \(Tcl_Init\s*\(interp\) == TCL_ERROR\)")
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise RuntimeError(
            f"tkappinit.c Tcl_Init anchor expected once, found {len(matches)}"
        )
    indent = matches[0].group(1)
    mount = (
        f"{indent}if (StaticPython_TkinterZipfsMount(interp) == TCL_ERROR)\n"
        f"{indent}    return TCL_ERROR;\n\n"
    )
    text = text[: matches[0].start()] + mount + text[matches[0].start() :]
    init_pattern = re.compile(
        r"(?m)^(\s*)if \(Tcl_Init\s*\(interp\) == TCL_ERROR\)\r?\n"
        r"\1    return TCL_ERROR;"
    )
    init_matches = list(init_pattern.finditer(text))
    if len(init_matches) != 1:
        raise RuntimeError(
            f"tkappinit.c completed Tcl_Init block expected once, found {len(init_matches)}"
        )
    init_match = init_matches[0]
    restrict = (
        f"\n\n{init_match.group(1)}if (StaticPython_TkinterZipfsRestrictAutoPath(interp) == TCL_ERROR)\n"
        f"{init_match.group(1)}    return TCL_ERROR;"
    )
    return text[: init_match.end()] + restrict + text[init_match.end() :]


def patch_tkinter_sources(context) -> None:
    targets = (
        ("Modules/_tkinter.c", _patch_tkinter_text),
        ("Modules/tkappinit.c", _patch_tkappinit_text),
    )
    for relative, transform in targets:
        path = source_path(context, relative)
        original = path.read_text(encoding="utf-8")
        updated = transform(original)
        if updated != original:
            path.write_text(updated, encoding="utf-8", newline="\n")
            context.log(f"strictly patched {relative} for in-memory Tcl/Tk ZipFS")


def _replace_tcltk_props_import(root: ET.Element) -> None:
    replaced = 0
    for parent in root.iter():
        for child in list(parent):
            if child.tag != msbuild_tag("Import"):
                continue
            project = (child.get("Project") or "").replace("/", "\\").casefold()
            if project.endswith("tcltk.props"):
                # tcltk.props also imports pyproject.props, which supplies the
                # CPython Include/, PC/, and generated pyconfig.h paths.  Keep
                # that generic project wiring while dropping all dynamic
                # Tcl/Tk configuration from the property sheet.
                child.set("Project", "pyproject.props")
                child.set("Condition", "$(__PyProject_Props_Imported) != 'true'")
                replaced += 1
    if replaced != 1:
        raise RuntimeError(
            f"_tkinter.vcxproj tcltk.props import expected once, found {replaced}"
        )


def patch_tkinter_project(context) -> None:
    project = source_path(context, "PCbuild/_tkinter.vcxproj")
    tree, root = load_msbuild_project(project)
    _replace_tcltk_props_import(root)
    set_or_create_property(root, "ConfigurationType", "StaticLibrary")
    set_or_create_property(root, "TargetExt", ".lib")
    set_or_create_property(root, "TargetName", "_tkinter")

    includes = [
        rf"..\externals\{TCL_SOURCE_NAME}\generic",
        rf"..\externals\{TCL_SOURCE_NAME}\win",
        rf"..\externals\{TK_SOURCE_NAME}\generic",
        rf"..\externals\{TK_SOURCE_NAME}\win",
        rf"..\externals\{TK_SOURCE_NAME}\xlib",
    ]
    definitions = [
        "WITH_APPINIT",
        "STATIC_BUILD",
        "TCL_THREADS",
        "Py_NO_ENABLE_SHARED",
        "UNICODE",
        "_UNICODE",
    ]
    compile_nodes = []
    for group in root.iter(msbuild_tag("ItemDefinitionGroup")):
        compile_node = find_direct_child(group, "ClCompile")
        if compile_node is None:
            continue
        compile_nodes.append(compile_node)
        include_node = find_direct_child(compile_node, "AdditionalIncludeDirectories")
        if include_node is None:
            include_node = ET.SubElement(compile_node, msbuild_tag("AdditionalIncludeDirectories"))
        current_includes = (include_node.text or "").replace(
            "$(tcltkDir)include;",
            "",
        )
        include_node.text = merge_msbuild_semicolon_list(
            current_includes,
            includes,
            "%(AdditionalIncludeDirectories)",
        )
        for child in list(compile_node):
            if child.tag == msbuild_tag("PreprocessorDefinitions") and "Py_TCLTK_DIR" in (child.text or ""):
                compile_node.remove(child)
        definitions_node = find_direct_child(compile_node, "PreprocessorDefinitions")
        if definitions_node is None:
            definitions_node = ET.SubElement(compile_node, msbuild_tag("PreprocessorDefinitions"))
        definitions_node.text = merge_msbuild_semicolon_list(
            definitions_node.text,
            definitions,
            "%(PreprocessorDefinitions)",
        )
        runtime_node = find_direct_child(compile_node, "RuntimeLibrary")
        if runtime_node is None:
            runtime_node = ET.SubElement(compile_node, msbuild_tag("RuntimeLibrary"))
        runtime_node.text = "MultiThreaded"
    if not compile_nodes:
        raise RuntimeError("_tkinter.vcxproj has no ClCompile definition group")

    for link_node in root.iter(msbuild_tag("Link")):
        dependencies = find_direct_child(link_node, "AdditionalDependencies")
        if dependencies is not None:
            dependencies.text = "%(AdditionalDependencies)"

    compile_items = [
        child
        for group in find_direct_children(root, "ItemGroup")
        for child in group
        if child.tag == msbuild_tag("ClCompile")
    ]
    generated_include = r"..\tkinter_builtin\staticpython_tkinter_zipfs.c"
    if not any((item.get("Include") or "").casefold() == generated_include.casefold() for item in compile_items):
        group = next(
            group
            for group in find_direct_children(root, "ItemGroup")
            if any(child.tag == msbuild_tag("ClCompile") for child in group)
        )
        item = ET.SubElement(group, msbuild_tag("ClCompile"))
        item.set("Include", generated_include)

    remove_msbuild_items(root, "ResourceCompile")
    remove_msbuild_items(root, "_TclTkDLL")
    remove_msbuild_targets(
        root,
        {"_CopyTclTkDLL", "_CleanTclTkDLL", "_WriteTCL_LIBRARY", "_CleanTCL_LIBRARY"},
    )
    save_msbuild_project(project, tree)

    rendered = project.read_text(encoding="utf-8")
    forbidden = (
        "tcltk.props",
        "$(tcltkLib)",
        "_TclTkDLL",
        "TCL_LIBRARY.env",
        "DynamicLibrary",
        ".pyd",
    )
    remaining = [value for value in forbidden if value in rendered]
    if remaining:
        raise RuntimeError(
            "_tkinter.vcxproj still contains dynamic Tcl/Tk wiring: " + ", ".join(remaining)
        )
    context.log("patched PCbuild/_tkinter.vcxproj as a /MT static Tcl/Tk extension")


def _find_built_library(root: Path, pattern: str, *, excluded: tuple[str, ...]) -> Path:
    candidates = [
        path
        for path in root.rglob(pattern)
        if path.is_file() and not any(token in path.name.casefold() for token in excluded)
    ]
    if len(candidates) != 1:
        rendered = ", ".join(str(path) for path in candidates) or "<none>"
        raise RuntimeError(
            f"expected exactly one Tcl/Tk static library matching {pattern}, found: {rendered}"
        )
    return candidates[0]


def prepare_tcltk_artifacts(context) -> None:
    if context.configuration != "Release" or context.platform != "x64":
        raise RuntimeError("experimental tkinter static pack currently supports Release|x64 only")
    staged_dir = source_path(context, "tkinter_builtin/lib")
    staged_tcl = staged_dir / TCL_STAGED_LIBRARY
    staged_tk = staged_dir / TK_STAGED_LIBRARY
    if staged_tcl.is_file() and staged_tk.is_file():
        context.log("using already built Tcl/Tk static archives")
        return

    ensure_tool("cl")
    ensure_tool("nmake")
    tcl_source = _tcl_source(context)
    tk_source = _tk_source(context)
    common = [
        "nmake",
        "/nologo",
        "/f",
        "makefile.vc",
        "core",
        "OPTS=static,nomsvcrt,noembed",
        "MACHINE=AMD64",
    ]
    run(context.log, common, cwd=tcl_source / "win", timeout=60 * 45)
    run(
        context.log,
        [*common, f"TCLDIR={tcl_source}"],
        cwd=tk_source / "win",
        timeout=60 * 45,
    )

    tcl_library = _find_built_library(
        tcl_source / "win",
        "tcl90*.lib",
        excluded=("stub", "reg", "dde", "tcl9tk"),
    )
    tk_library = _find_built_library(
        tk_source / "win",
        "tcl9tk90*.lib",
        excluded=("stub",),
    )
    staged_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(tcl_library, staged_tcl)
    shutil.copy2(tk_library, staged_tk)
    context.log(
        f"staged Tcl/Tk static archives from {tcl_library.name} and {tk_library.name}"
    )


LIBRARY_INTEGRATION = LibraryIntegration(
    name="tkinter",
    source_provider="github",
    project_name="tcltk/tcl+tcltk/tk",
    release_version=TCLTK_RELEASE,
    source_resolver="github-immutable-commit-pair+sha256",
    materialized_paths=[
        OPTIONAL_FREEZE_MARKER,
        ZIP_RESOURCE,
        ZIPFS_SOURCE,
        PROVENANCE_FILE,
        TCL_LICENSE,
        TK_LICENSE,
    ],
    cleanup_paths=[
        f"externals/{TCL_SOURCE_NAME}",
        f"externals/{TK_SOURCE_NAME}",
        "tkinter_builtin",
        ZIP_RESOURCE,
        OPTIONAL_FREEZE_MARKER,
        "licenses/tkinter",
    ],
    python_packages=["tkinter"],
    static_library_projects_release_x64=["_tkinter.vcxproj"],
    builtin_module_registrations=[
        {
            "name": "_tkinter",
            "pyinit": "PyInit__tkinter",
        }
    ],
    staged_static_libraries_release_x64=[
        {
            "source_glob": f"tkinter_builtin/lib/{TK_STAGED_LIBRARY}",
            "target_name": TK_STAGED_LIBRARY,
        },
        {
            "source_glob": f"tkinter_builtin/lib/{TCL_STAGED_LIBRARY}",
            "target_name": TCL_STAGED_LIBRARY,
        },
    ],
    python_link_dependencies_release_x64=[
        "_tkinter.lib",
        TK_STAGED_LIBRARY,
        TCL_STAGED_LIBRARY,
        *TCLTK_SYSTEM_LIBRARIES,
    ],
    top_level_import_names=["tkinter"],
    resource_rules=[
        {
            "action": "include",
            "path": ZIP_RESOURCE,
        }
    ],
    license_expression="Python-2.0 AND TCL",
    license_files=[CPYTHON_LICENSE, TCL_LICENSE, TK_LICENSE],
    smoke_tests=[
        inline_verification_step(
            "tcl-zipfs-no-extraction",
            """import tkinter
interp = tkinter.Tcl()
assert interp.eval("info patchlevel") == "9.0.4"
mount = interp.getvar("staticpython_tkinter_zipfs")
assert mount == "//zipfs:/staticpython/tcltk-9.0.4"
assert interp.getvar("tcl_library") == mount + "/tcl9.0"
assert interp.getvar("tk_library") == mount + "/tk9.0"
auto_path = interp.tk.splitlist(interp.getvar("auto_path"))
assert auto_path and all(path.startswith(mount + "/") for path in auto_path), auto_path
assert interp.eval("::tcl::tm::path list") == ""
assert interp.eval("file exists [file join $tcl_library encoding cp1252.enc]") == "1"
assert "cp1252" in interp.tk.splitlist(interp.eval("encoding names"))
""",
        ),
        inline_verification_step(
            "tk-ttk-themes",
            """import tkinter
from tkinter import ttk
root = tkinter.Tk()
try:
    root.withdraw()
    mount = root.tk.getvar("staticpython_tkinter_zipfs")
    assert root.tk.getvar("tk_library") == mount + "/tk9.0"
    auto_path = root.tk.splitlist(root.tk.getvar("auto_path"))
    assert auto_path and all(path.startswith(mount + "/") for path in auto_path), auto_path
    assert root.tk.eval("::tcl::tm::path list") == ""
    themes = set(ttk.Style(root).theme_names())
    assert {"clam", "vista", "xpnative"} & themes
    root.update_idletasks()
finally:
    root.destroy()
""",
        ),
    ],
    prepare_source_hooks=[prepare_tcltk_sources],
    pre_patch_hooks=[patch_tkinter_sources],
    post_patch_hooks=[patch_tkinter_project],
    pre_build_hooks=[prepare_tcltk_artifacts],
)
