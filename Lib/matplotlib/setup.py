from __future__ import annotations

import os
import re
from pathlib import Path

from libs import pypi_library, source_path, write_source_text
from tools import download_first_available, extract_source_archive


MATPLOTLIB_RELEASE_VERSION = "3.10.9"
FREETYPE_VERSION = "2.6.1"
QHULL_VERSION = "8.0.2"

MATPLOTLIB_AGG_PROJECT_GUID = "{44B16CB8-02F2-4C8A-9949-66E0434F643E}"
MATPLOTLIB_FREETYPE_PROJECT_GUID = "{8EEDC81D-B835-4F59-A539-3871C33B1871}"
MATPLOTLIB_QHULL_PROJECT_GUID = "{9C48D991-EB14-4E73-A466-6E676E26E2EE}"
MATPLOTLIB_BACKEND_AGG_PROJECT_GUID = "{12F9D102-207B-4D9A-8650-80F67146540E}"
MATPLOTLIB_C_INTERNAL_UTILS_PROJECT_GUID = "{26B4DF8B-9E6E-40B8-A1AC-213F785EB5F4}"
MATPLOTLIB_FT2FONT_PROJECT_GUID = "{BC40F20D-9547-442A-AF93-7418B01D38F1}"
MATPLOTLIB_IMAGE_PROJECT_GUID = "{020159B8-5505-4D42-95E2-C7B7500A08E6}"
MATPLOTLIB_PATH_PROJECT_GUID = "{172784DA-856C-4E97-9298-A3670D8551C4}"
MATPLOTLIB_QHULL_EXT_PROJECT_GUID = "{22BE9CC4-4264-4D9E-B2F7-845641C5978D}"
MATPLOTLIB_TRI_PROJECT_GUID = "{1B68B5E7-6EFD-448E-AB7E-008B4E83B1F9}"

MATPLOTLIB_AGG_SOURCES = [
    "agg_bezier_arc.cpp",
    "agg_curves.cpp",
    "agg_image_filters.cpp",
    "agg_trans_affine.cpp",
    "agg_vcgen_contour.cpp",
    "agg_vcgen_dash.cpp",
    "agg_vcgen_stroke.cpp",
    "agg_vpgen_segmentator.cpp",
]

MATPLOTLIB_FREETYPE_SOURCES = [
    "src/autofit/autofit.c",
    "src/base/ftbase.c",
    "src/base/ftbbox.c",
    "src/base/ftbdf.c",
    "src/base/ftbitmap.c",
    "src/base/ftcid.c",
    "src/base/ftfntfmt.c",
    "src/base/ftfstype.c",
    "src/base/ftgasp.c",
    "src/base/ftglyph.c",
    "src/base/ftgxval.c",
    "src/base/ftinit.c",
    "src/base/ftlcdfil.c",
    "src/base/ftmm.c",
    "src/base/ftotval.c",
    "src/base/ftpatent.c",
    "src/base/ftpfr.c",
    "src/base/ftstroke.c",
    "src/base/ftsynth.c",
    "src/base/ftsystem.c",
    "src/base/fttype1.c",
    "src/base/ftwinfnt.c",
    "src/bdf/bdf.c",
    "src/cache/ftcache.c",
    "src/cff/cff.c",
    "src/cid/type1cid.c",
    "src/gzip/ftgzip.c",
    "src/lzw/ftlzw.c",
    "src/pcf/pcf.c",
    "src/pfr/pfr.c",
    "src/psaux/psaux.c",
    "src/pshinter/pshinter.c",
    "src/psnames/psnames.c",
    "src/raster/raster.c",
    "src/sfnt/sfnt.c",
    "src/smooth/smooth.c",
    "src/truetype/truetype.c",
    "src/type1/type1.c",
    "src/type42/type42.c",
    "src/winfonts/winfnt.c",
    "builds/windows/ftdebug.c",
]

MATPLOTLIB_QHULL_SOURCES = [
    "src/libqhull_r/geom2_r.c",
    "src/libqhull_r/geom_r.c",
    "src/libqhull_r/global_r.c",
    "src/libqhull_r/io_r.c",
    "src/libqhull_r/libqhull_r.c",
    "src/libqhull_r/mem_r.c",
    "src/libqhull_r/merge_r.c",
    "src/libqhull_r/poly2_r.c",
    "src/libqhull_r/poly_r.c",
    "src/libqhull_r/qset_r.c",
    "src/libqhull_r/random_r.c",
    "src/libqhull_r/rboxlib_r.c",
    "src/libqhull_r/stat_r.c",
    "src/libqhull_r/usermem_r.c",
    "src/libqhull_r/userprintf_rbox_r.c",
    "src/libqhull_r/userprintf_r.c",
    "src/libqhull_r/user_r.c",
]

MATPLOTLIB_EXTENSION_MODULES = {
    "matplotlib.backends._backend_agg": {
        "guid": MATPLOTLIB_BACKEND_AGG_PROJECT_GUID,
        "target": "matplotlib.backends._backend_agg",
        "pyinit": "PyInit__backend_agg",
        "sources": [
            "src/_backend_agg.cpp",
            "src/_backend_agg_wrapper.cpp",
        ],
        "include_dirs": [
            r"..\matplotlib_builtin\source\src",
            r"..\matplotlib_builtin\source\extern\agg24-svn\include",
            r"..\matplotlib_builtin\freetype-2.6.1\include",
            r"..\pybind11_builtin\include",
        ],
        "link_libs": [
            "matplotlib_agg.lib",
            "matplotlib_freetype.lib",
        ],
    },
    "matplotlib._c_internal_utils": {
        "guid": MATPLOTLIB_C_INTERNAL_UTILS_PROJECT_GUID,
        "target": "matplotlib._c_internal_utils",
        "pyinit": "PyInit__c_internal_utils",
        "sources": [
            "src/_c_internal_utils.cpp",
        ],
        "include_dirs": [
            r"..\matplotlib_builtin\source\src",
            r"..\pybind11_builtin\include",
        ],
        "link_libs": [
            "ole32.lib",
            "shell32.lib",
            "user32.lib",
        ],
    },
    "matplotlib.ft2font": {
        "guid": MATPLOTLIB_FT2FONT_PROJECT_GUID,
        "target": "matplotlib.ft2font",
        "pyinit": "PyInit_ft2font",
        "sources": [
            "src/ft2font.cpp",
            "src/ft2font_wrapper.cpp",
        ],
        "include_dirs": [
            r"..\matplotlib_builtin\source\src",
            r"..\matplotlib_builtin\source\extern\agg24-svn\include",
            r"..\matplotlib_builtin\freetype-2.6.1\include",
            r"..\pybind11_builtin\include",
        ],
        "definitions": [
            'FREETYPE_BUILD_TYPE=&quot;local&quot;',
        ],
        "link_libs": [
            "matplotlib_agg.lib",
            "matplotlib_freetype.lib",
        ],
    },
    "matplotlib._image": {
        "guid": MATPLOTLIB_IMAGE_PROJECT_GUID,
        "target": "matplotlib._image",
        "pyinit": "PyInit__image",
        "sources": [
            "src/_image_wrapper.cpp",
            "src/py_converters.cpp",
        ],
        "include_dirs": [
            r"..\matplotlib_builtin\source\src",
            r"..\matplotlib_builtin\source\extern\agg24-svn\include",
            r"..\pybind11_builtin\include",
        ],
        "link_libs": [
            "matplotlib_agg.lib",
        ],
    },
    "matplotlib._path": {
        "guid": MATPLOTLIB_PATH_PROJECT_GUID,
        "target": "matplotlib._path",
        "pyinit": "PyInit__path",
        "sources": [
            "src/_path_wrapper.cpp",
        ],
        "include_dirs": [
            r"..\matplotlib_builtin\source\src",
            r"..\matplotlib_builtin\source\extern\agg24-svn\include",
            r"..\pybind11_builtin\include",
        ],
        "link_libs": [
            "matplotlib_agg.lib",
        ],
    },
    "matplotlib._qhull": {
        "guid": MATPLOTLIB_QHULL_EXT_PROJECT_GUID,
        "target": "matplotlib._qhull",
        "pyinit": "PyInit__qhull",
        "sources": [
            "src/_qhull_wrapper.cpp",
        ],
        "include_dirs": [
            r"..\matplotlib_builtin\source\src",
            r"..\matplotlib_builtin\qhull-8.0.2\src",
            r"..\pybind11_builtin\include",
        ],
        "definitions": [
            "MPL_DEVNULL=NUL",
        ],
        "link_libs": [
            "matplotlib_qhull.lib",
        ],
    },
    "matplotlib._tri": {
        "guid": MATPLOTLIB_TRI_PROJECT_GUID,
        "target": "matplotlib._tri",
        "pyinit": "PyInit__tri",
        "sources": [
            "src/tri/_tri.cpp",
            "src/tri/_tri_wrapper.cpp",
        ],
        "include_dirs": [
            r"..\matplotlib_builtin\source\src",
            r"..\pybind11_builtin\include",
        ],
    },
}

MATPLOTLIB_SUPPORT_PROJECTS = {
    "matplotlib_agg": {
        "project": "matplotlib_agg.vcxproj",
        "guid": MATPLOTLIB_AGG_PROJECT_GUID,
    },
    "matplotlib_freetype": {
        "project": "matplotlib_freetype.vcxproj",
        "guid": MATPLOTLIB_FREETYPE_PROJECT_GUID,
    },
    "matplotlib_qhull": {
        "project": "matplotlib_qhull.vcxproj",
        "guid": MATPLOTLIB_QHULL_PROJECT_GUID,
    },
}

MATPLOTLIB_PROJECT_FILTER_ENV = "STATICPYTHON_MPL_PROJECT_FILTER"

PATCHED_MATPLOTLIB_ENUMS_HEADER = """#ifndef MPL_ENUMS_H
#define MPL_ENUMS_H

#include <string>
#include <type_traits>
#include <unordered_map>
#include <utility>
#include <vector>

#include <pybind11/pybind11.h>

// Extension for pybind11: Pythonic enums.
// This allows creating classes based on ``enum.*`` types.
// This code was copied from mplcairo, with some slight tweaks.
// The API is:
//
// - P11X_DECLARE_ENUM(py_name: str, py_base_cls: str, ...: {str, enum value}):
//   py_name: The name to expose in the module.
//   py_base_cls: The name of the enum base class to use.
//   ...: The enum name/value pairs to expose.
//
//   Use this macro to declare an enum and its values.
//
// - py11x::bind_enums(m: pybind11::module):
//   m: The module to use to register the enum classes.
//
//   Place this in PYBIND11_MODULE to register the enums declared by P11X_DECLARE_ENUM.

// a1 includes the opening brace and a2 the closing brace.
// This definition is compatible with older compiler versions compared to
// #define P11X_ENUM_TYPE(...) decltype(std::map{std::pair __VA_ARGS__})::mapped_type
#define P11X_ENUM_TYPE(a1, a2, ...) decltype(std::pair a1, a2)::second_type

#define P11X_CAT2(a, b) a##b
#define P11X_CAT(a, b) P11X_CAT2(a, b)

namespace p11x {
  namespace {
    namespace py = pybind11;

    struct enum_spec {
      std::string py_base_cls;
      std::vector<std::pair<std::string, long long>> pairs;
      py::object cls;

      decltype(auto) attr(char const* name)
      {
        if (!cls) {
          throw std::runtime_error("enum class is not bound yet");
        }
        return cls.attr(name);
      }
    };

    auto enums = std::unordered_map<std::string, enum_spec>{};

    auto bind_enums(py::module_ mod) -> void
    {
      auto enum_module = py::module_::import("enum");
      for (auto& [py_name, spec]: enums) {
        auto py_pairs = py::list();
        for (auto const& [name, value]: spec.pairs) {
          py_pairs.append(py::make_tuple(name, value));
        }
        spec.cls = enum_module.attr(spec.py_base_cls.c_str())(
          py_name, py_pairs, py::arg("module") = mod.attr("__name__"));
        mod.attr(py_name.c_str()) = spec.cls;
      }
    }
  }
}

// Immediately converting the args to a vector outside of the lambda avoids
// name collisions.
#define P11X_DECLARE_ENUM(py_name, py_base_cls, ...) \\
  namespace p11x { \\
    namespace { \\
      [[maybe_unused]] auto const P11X_CAT(enum_placeholder_, __COUNTER__) = \\
        [](auto args) { \\
          auto pairs = std::vector<std::pair<std::string, long long>>{}; \\
          for (auto& [k, v]: args) { \\
            pairs.emplace_back(k, static_cast<long long>(v)); \\
          } \\
          p11x::enums.emplace(py_name, p11x::enum_spec{py_base_cls, std::move(pairs), {}}); \\
          return 0; \\
        } (std::vector{std::pair __VA_ARGS__}); \\
    } \\
  } \\
  namespace pybind11::detail { \\
    template<> struct type_caster<P11X_ENUM_TYPE(__VA_ARGS__)> { \\
      using type = P11X_ENUM_TYPE(__VA_ARGS__); \\
      static_assert(std::is_enum_v<type>, "Not an enum"); \\
      PYBIND11_TYPE_CASTER(type, _(py_name)); \\
      bool load(handle src, bool) { \\
        auto& spec = p11x::enums.at(py_name); \\
        if (!spec.cls || !pybind11::isinstance(src, spec.cls)) { \\
          return false; \\
        } \\
        PyObject* tmp = nullptr; \\
        if ((tmp = PyNumber_Index(src.attr("value").ptr()))) { \\
          auto ival = PyLong_AsLong(tmp); \\
          value = decltype(value)(ival); \\
          Py_DECREF(tmp); \\
          return !(ival == -1 && PyErr_Occurred()); \\
        } \\
        return false; \\
      } \\
      static handle cast(decltype(value) obj, return_value_policy, handle) { \\
        auto& spec = p11x::enums.at(py_name); \\
        if (!spec.cls) { \\
          throw std::runtime_error("enum class is not bound yet"); \\
        } \\
        return spec.cls(std::underlying_type_t<type>(obj)).inc_ref(); \\
      } \\
    }; \\
  }

#endif /* MPL_ENUMS_H */
"""


def _project_aliases(name: str) -> set[str]:
    aliases = {name.casefold()}
    if name.endswith(".vcxproj"):
        aliases.add(Path(name).stem.casefold())
    else:
        aliases.add(f"{name}.vcxproj".casefold())
    if name.endswith(".lib"):
        aliases.add(name[:-4].casefold())
    else:
        aliases.add(f"{name}.lib".casefold())
    return aliases


def _filtered_matplotlib_projects() -> tuple[list[str], list[str], str | None]:
    raw_filter = os.environ.get(MATPLOTLIB_PROJECT_FILTER_ENV)
    if not raw_filter:
        return list(MATPLOTLIB_SUPPORT_PROJECTS), list(MATPLOTLIB_EXTENSION_MODULES), None

    requested = {
        token.casefold()
        for token in re.split(r"[\s,;]+", raw_filter)
        if token.strip()
    }
    if not requested or {"*", "all"} & requested:
        return list(MATPLOTLIB_SUPPORT_PROJECTS), list(MATPLOTLIB_EXTENSION_MODULES), raw_filter

    selected_support = [
        support_name
        for support_name, support in MATPLOTLIB_SUPPORT_PROJECTS.items()
        if requested & (
            _project_aliases(support_name)
            | _project_aliases(support["project"])
        )
    ]
    selected_extensions = [
        module_name
        for module_name, spec in MATPLOTLIB_EXTENSION_MODULES.items()
        if requested & (
            _project_aliases(module_name)
            | _project_aliases(f"{module_name}.vcxproj")
            | _project_aliases(spec["target"])
        )
    ]

    for module_name in selected_extensions:
        for link_lib in MATPLOTLIB_EXTENSION_MODULES[module_name].get("link_libs", []):
            support_name = Path(link_lib).stem
            if support_name in MATPLOTLIB_SUPPORT_PROJECTS and support_name not in selected_support:
                selected_support.append(support_name)

    return selected_support, selected_extensions, raw_filter


SELECTED_MATPLOTLIB_SUPPORT, SELECTED_MATPLOTLIB_EXTENSIONS, SELECTED_MATPLOTLIB_FILTER = (
    _filtered_matplotlib_projects()
)


def _selected_support_project_items() -> list[tuple[str, str]]:
    return [
        (
            MATPLOTLIB_SUPPORT_PROJECTS[name]["project"],
            MATPLOTLIB_SUPPORT_PROJECTS[name]["guid"],
        )
        for name in SELECTED_MATPLOTLIB_SUPPORT
    ]


def _selected_extension_project_items() -> list[tuple[str, str]]:
    return [
        (
            f"{module_name}.vcxproj",
            MATPLOTLIB_EXTENSION_MODULES[module_name]["guid"],
        )
        for module_name in SELECTED_MATPLOTLIB_EXTENSIONS
    ]


def _selected_builtin_module_registrations() -> list[dict[str, str]]:
    return [
        {
            "name": module_name,
            "pyinit": MATPLOTLIB_EXTENSION_MODULES[module_name]["pyinit"],
        }
        for module_name in SELECTED_MATPLOTLIB_EXTENSIONS
    ]


def _selected_python_link_dependencies() -> list[str]:
    dependencies: list[str] = []
    for module_name in SELECTED_MATPLOTLIB_EXTENSIONS:
        dependencies.append(f"{MATPLOTLIB_EXTENSION_MODULES[module_name]['target']}.lib")
    for support_name in SELECTED_MATPLOTLIB_SUPPORT:
        dependencies.append(f"{support_name}.lib")
    for module_name in SELECTED_MATPLOTLIB_EXTENSIONS:
        for link_lib in MATPLOTLIB_EXTENSION_MODULES[module_name].get("link_libs", []):
            support_name = Path(link_lib).stem
            if support_name in MATPLOTLIB_SUPPORT_PROJECTS:
                continue
            if link_lib not in dependencies:
                dependencies.append(link_lib)
    return dependencies


def _project_configurations() -> str:
    return """  <ItemGroup Label="ProjectConfigurations">
    <ProjectConfiguration Include="Release|x64">
      <Configuration>Release</Configuration>
      <Platform>x64</Platform>
    </ProjectConfiguration>
  </ItemGroup>
"""


def _msbuild_path(path: str) -> str:
    return "..\\" + path.replace("/", "\\")


def _object_file_name(source_file: str) -> str:
    stem = source_file.replace("/", "_").replace("\\", "_")
    return f"$(IntDir){stem}.obj"


def _compile_items(source_files: list[str], *, root: str) -> str:
    items = []
    for name in source_files:
        windows_name = name.replace("/", "\\")
        include_path = f"{root}\\{windows_name}"
        items.append(
            "\n".join(
                [
                    f'    <ClCompile Include="{include_path}">',
                    f"      <ObjectFileName>{_object_file_name(name)}</ObjectFileName>",
                    "    </ClCompile>",
                ]
            )
        )
    return "\n".join(items)


def _render_static_library_project(
    *,
    project_guid: str,
    root_namespace: str,
    target_name: str,
    source_files: list[str],
    source_root: str,
    include_dirs: list[str],
    definitions: list[str] | None = None,
    language_standard: str | None = None,
    extra_options: list[str] | None = None,
) -> str:
    include_text = ";".join([*include_dirs, "%(AdditionalIncludeDirectories)"])
    definition_text = ";".join(
        [
            *(definitions or []),
            "Py_NO_ENABLE_SHARED",
            "_CRT_SECURE_NO_WARNINGS",
            "%(PreprocessorDefinitions)",
        ]
    )
    language_standard_text = "" if language_standard is None else f"\n      <LanguageStandard>{language_standard}</LanguageStandard>"
    extra_options_text = " ".join([*(extra_options or []), "%(AdditionalOptions)"])
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Project DefaultTargets="Build" ToolsVersion="4.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
{_project_configurations()}  <PropertyGroup Label="Globals">
    <ProjectGuid>{project_guid}</ProjectGuid>
    <RootNamespace>{root_namespace}</RootNamespace>
    <Keyword>Win32Proj</Keyword>
    <SupportPGO>false</SupportPGO>
    <WindowsTargetPlatformVersion>$(DefaultWindowsSDKVersion)</WindowsTargetPlatformVersion>
  </PropertyGroup>
  <Import Project="python.props" />
  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.Default.props" />
  <PropertyGroup Label="Configuration">
    <ConfigurationType>StaticLibrary</ConfigurationType>
    <CharacterSet>Unicode</CharacterSet>
    <PlatformToolset>$(DefaultPlatformToolset)</PlatformToolset>
  </PropertyGroup>
  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.props" />
  <ImportGroup Label="PropertySheets">
    <Import Project="$(UserRootDir)\\Microsoft.Cpp.$(Platform).user.props" Condition="exists('$(UserRootDir)\\Microsoft.Cpp.$(Platform).user.props')" Label="LocalAppDataPlatform" />
    <Import Project="pyproject.props" />
  </ImportGroup>
  <PropertyGroup Label="UserMacros" />
  <PropertyGroup>
    <TargetName>{target_name}</TargetName>
    <TargetExt>.lib</TargetExt>
  </PropertyGroup>
  <ItemDefinitionGroup>
    <ClCompile>
      <AdditionalIncludeDirectories>{include_text}</AdditionalIncludeDirectories>
      <PreprocessorDefinitions>{definition_text}</PreprocessorDefinitions>
      <DisableSpecificWarnings>4244;4267;4996;%(DisableSpecificWarnings)</DisableSpecificWarnings>{language_standard_text}
      <AdditionalOptions>{extra_options_text}</AdditionalOptions>
      <RuntimeLibrary Condition="'$(Configuration)|$(Platform)'=='Release|x64'">MultiThreaded</RuntimeLibrary>
    </ClCompile>
  </ItemDefinitionGroup>
  <ItemGroup>
{_compile_items(source_files, root=source_root)}
  </ItemGroup>
  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.targets" />
</Project>
"""


def _render_extension_project(module_name: str, spec: dict) -> str:
    definitions = list(spec.get("definitions", []))
    include_text = ";".join([*spec["include_dirs"], "%(AdditionalIncludeDirectories)"])
    definition_text = ";".join(
        [*definitions, "Py_NO_ENABLE_SHARED", "_CRT_SECURE_NO_WARNINGS", "%(PreprocessorDefinitions)"]
    )
    compile_items = _compile_items(spec["sources"], root=r"..\matplotlib_builtin\source")
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Project DefaultTargets="Build" ToolsVersion="4.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
{_project_configurations()}  <PropertyGroup Label="Globals">
    <ProjectGuid>{spec["guid"]}</ProjectGuid>
    <RootNamespace>{module_name.replace(".", "_")}</RootNamespace>
    <Keyword>Win32Proj</Keyword>
    <SupportPGO>false</SupportPGO>
    <WindowsTargetPlatformVersion>$(DefaultWindowsSDKVersion)</WindowsTargetPlatformVersion>
  </PropertyGroup>
  <Import Project="python.props" />
  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.Default.props" />
  <PropertyGroup Label="Configuration">
    <ConfigurationType>StaticLibrary</ConfigurationType>
    <CharacterSet>Unicode</CharacterSet>
    <PlatformToolset>$(DefaultPlatformToolset)</PlatformToolset>
  </PropertyGroup>
  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.props" />
  <ImportGroup Label="PropertySheets">
    <Import Project="$(UserRootDir)\\Microsoft.Cpp.$(Platform).user.props" Condition="exists('$(UserRootDir)\\Microsoft.Cpp.$(Platform).user.props')" Label="LocalAppDataPlatform" />
    <Import Project="pyproject.props" />
  </ImportGroup>
  <PropertyGroup Label="UserMacros" />
  <PropertyGroup>
    <TargetName>{spec["target"]}</TargetName>
    <TargetExt>.lib</TargetExt>
  </PropertyGroup>
  <ItemDefinitionGroup>
    <ClCompile>
      <AdditionalIncludeDirectories>{include_text}</AdditionalIncludeDirectories>
      <PreprocessorDefinitions>{definition_text}</PreprocessorDefinitions>
      <DisableSpecificWarnings>4244;4267;4996;%(DisableSpecificWarnings)</DisableSpecificWarnings>
      <ExceptionHandling>Sync</ExceptionHandling>
      <LanguageStandard>stdcpp17</LanguageStandard>
      <AdditionalOptions>/bigobj /EHsc /Zc:preprocessor %(AdditionalOptions)</AdditionalOptions>
      <RuntimeLibrary Condition="'$(Configuration)|$(Platform)'=='Release|x64'">MultiThreaded</RuntimeLibrary>
    </ClCompile>
  </ItemDefinitionGroup>
  <ItemGroup>
{compile_items}
  </ItemGroup>
  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.targets" />
</Project>
"""


def _downloaded_archive_path(context, project: str, version: str, filename: str) -> Path:
    return context.download_cache_root / project / version / filename


def _extract_archive_if_needed(context, archive_path: Path, destination: Path, *, final_name: str) -> Path:
    if destination.exists():
        context.log(f"using existing {final_name} source at {destination.relative_to(context.source_root)}")
        return destination
    extracted_root = extract_source_archive(context.log, archive_path, destination.parent, final_name=final_name)
    return extracted_root


def ensure_freetype_source(context) -> Path:
    source_dir = source_path(context, f"matplotlib_builtin/freetype-{FREETYPE_VERSION}")
    if (source_dir / "include" / "ft2build.h").exists():
        return source_dir

    archive_path = _downloaded_archive_path(
        context,
        "freetype",
        FREETYPE_VERSION,
        f"freetype-{FREETYPE_VERSION}.tar.gz",
    )
    used_source = download_first_available(
        context.log,
        [
            f"https://download.savannah.nongnu.org/releases/freetype/freetype-old/freetype-{FREETYPE_VERSION}.tar.gz",
            f"https://downloads.sourceforge.net/project/freetype/freetype2/{FREETYPE_VERSION}/freetype-{FREETYPE_VERSION}.tar.gz",
            "https://gitlab.freedesktop.org/freetype/freetype/-/archive/VER-2-6-1/freetype-VER-2-6-1.tar.gz",
            "https://github.com/freetype/freetype/archive/refs/tags/VER-2-6-1.tar.gz",
        ],
        archive_path,
    )
    extracted_root = _extract_archive_if_needed(
        context,
        archive_path,
        source_dir,
        final_name=f"freetype-{FREETYPE_VERSION}",
    )
    context.log(f"materialized FreeType {FREETYPE_VERSION} from {used_source}")
    return extracted_root


def ensure_qhull_source(context) -> Path:
    source_dir = source_path(context, f"matplotlib_builtin/qhull-{QHULL_VERSION}")
    if (source_dir / "src" / "libqhull_r" / "qhull_ra.h").exists():
        return source_dir

    archive_path = _downloaded_archive_path(
        context,
        "qhull",
        QHULL_VERSION,
        f"qhull-{QHULL_VERSION}.tar.gz",
    )
    used_source = download_first_available(
        context.log,
        [
            f"https://github.com/qhull/qhull/archive/v{QHULL_VERSION}/qhull-{QHULL_VERSION}.tar.gz",
        ],
        archive_path,
    )
    extracted_root = _extract_archive_if_needed(
        context,
        archive_path,
        source_dir,
        final_name=f"qhull-{QHULL_VERSION}",
    )
    context.log(f"materialized Qhull {QHULL_VERSION} from {used_source}")
    return extracted_root


def _matplotlib_pkg_info_version(context) -> str:
    path = source_path(context, "matplotlib_builtin/source/PKG-INFO")
    match = re.search(r"^Version:\s*(.+)$", path.read_text(encoding="utf-8"), re.MULTILINE)
    if match is None:
        raise RuntimeError(f"could not find Matplotlib Version in {path}")
    return match.group(1).strip()


def _write_matplotlib_version_module(context) -> None:
    version = _matplotlib_pkg_info_version(context)
    write_source_text(context, "Lib/matplotlib/_version.py", f'version = "{version}"\n')


def _patch_matplotlib_sources(context) -> None:
    path = source_path(context, "matplotlib_builtin/source/src/_c_internal_utils.cpp")
    text = path.read_text(encoding="utf-8")
    patched = text.replace('LoadLibrary("user32.dll")', 'LoadLibraryA("user32.dll")')
    if patched != text:
        write_source_text(context, "matplotlib_builtin/source/src/_c_internal_utils.cpp", patched)
    write_source_text(context, "matplotlib_builtin/source/src/_enums.h", PATCHED_MATPLOTLIB_ENUMS_HEADER)


def _ensure_required_files(context, files: list[str]) -> None:
    missing = [path for path in files if not source_path(context, path).exists()]
    if missing:
        raise RuntimeError("matplotlib source files are missing: " + ", ".join(missing))


def prepare_matplotlib_project(context) -> None:
    if context.platform != "x64":
        raise RuntimeError(f"matplotlib builtin integration currently supports only x64, not {context.platform}")

    ensure_freetype_source(context)
    ensure_qhull_source(context)
    _write_matplotlib_version_module(context)
    _patch_matplotlib_sources(context)

    _ensure_required_files(
        context,
        [
            "Lib/matplotlib/__init__.py",
            "Lib/mpl_toolkits",
            "Lib/pylab.py",
            "matplotlib_builtin/source/src/ft2font_wrapper.cpp",
            "matplotlib_builtin/source/extern/agg24-svn/include/agg_basics.h",
            f"matplotlib_builtin/freetype-{FREETYPE_VERSION}/include/ft2build.h",
            f"matplotlib_builtin/qhull-{QHULL_VERSION}/src/libqhull_r/qhull_ra.h",
            "pybind11_builtin/include/pybind11/pybind11.h",
        ],
    )

    write_source_text(
        context,
        "PCbuild/matplotlib_agg.vcxproj",
        _render_static_library_project(
            project_guid=MATPLOTLIB_AGG_PROJECT_GUID,
            root_namespace="matplotlib_agg",
            target_name="matplotlib_agg",
            source_files=MATPLOTLIB_AGG_SOURCES,
            source_root=r"..\matplotlib_builtin\source\extern\agg24-svn\src",
            include_dirs=[r"..\matplotlib_builtin\source\extern\agg24-svn\include"],
            language_standard="stdcpp17",
            extra_options=["/bigobj", "/EHsc"],
        ),
    )
    write_source_text(
        context,
        "PCbuild/matplotlib_freetype.vcxproj",
        _render_static_library_project(
            project_guid=MATPLOTLIB_FREETYPE_PROJECT_GUID,
            root_namespace="matplotlib_freetype",
            target_name="matplotlib_freetype",
            source_files=MATPLOTLIB_FREETYPE_SOURCES,
            source_root=fr"..\matplotlib_builtin\freetype-{FREETYPE_VERSION}",
            include_dirs=[fr"..\matplotlib_builtin\freetype-{FREETYPE_VERSION}\include"],
            definitions=[
                "FT2_BUILD_LIBRARY",
            ],
            extra_options=["/bigobj"],
        ),
    )
    write_source_text(
        context,
        "PCbuild/matplotlib_qhull.vcxproj",
        _render_static_library_project(
            project_guid=MATPLOTLIB_QHULL_PROJECT_GUID,
            root_namespace="matplotlib_qhull",
            target_name="matplotlib_qhull",
            source_files=MATPLOTLIB_QHULL_SOURCES,
            source_root=fr"..\matplotlib_builtin\qhull-{QHULL_VERSION}",
            include_dirs=[fr"..\matplotlib_builtin\qhull-{QHULL_VERSION}\src"],
            extra_options=["/bigobj"],
        ),
    )

    if SELECTED_MATPLOTLIB_FILTER:
        context.log(
            "filtering matplotlib native projects via "
            f"{MATPLOTLIB_PROJECT_FILTER_ENV}={SELECTED_MATPLOTLIB_FILTER!r}: "
            f"support={SELECTED_MATPLOTLIB_SUPPORT}, extensions={SELECTED_MATPLOTLIB_EXTENSIONS}"
        )

    for module_name in SELECTED_MATPLOTLIB_EXTENSIONS:
        spec = MATPLOTLIB_EXTENSION_MODULES[module_name]
        write_source_text(
            context,
            f"PCbuild/{module_name}.vcxproj",
            _render_extension_project(module_name, spec),
        )


MATPLOTLIB_SUPPORT_PROJECT_ITEMS = _selected_support_project_items()
MATPLOTLIB_EXTENSION_PROJECT_ITEMS = _selected_extension_project_items()


LIBRARY_INTEGRATION = pypi_library(
    name="matplotlib",
    release_version=MATPLOTLIB_RELEASE_VERSION,
    dependencies=[
        "contourpy",
        "cycler",
        "fontTools",
        "kiwisolver",
        "numpy",
        "packaging",
        "PIL",
        "pyparsing",
        "dateutil",
        "pybind11",
    ],
    source_mapping={
        "lib/matplotlib": "Lib/matplotlib",
        "lib/mpl_toolkits": "Lib/mpl_toolkits",
        "lib/pylab.py": "Lib/pylab.py",
        "src": "matplotlib_builtin/source/src",
        "extern/agg24-svn": "matplotlib_builtin/source/extern/agg24-svn",
        "PKG-INFO": "matplotlib_builtin/source/PKG-INFO",
    },
    materialized_paths=[
        "Lib/matplotlib/__init__.py",
        "Lib/matplotlib/_version.py",
        "Lib/matplotlib/mpl-data/matplotlibrc",
        "Lib/mpl_toolkits",
        "Lib/pylab.py",
        "matplotlib_builtin/source/src/ft2font_wrapper.cpp",
        "matplotlib_builtin/source/extern/agg24-svn/include/agg_basics.h",
        f"matplotlib_builtin/freetype-{FREETYPE_VERSION}/include/ft2build.h",
        f"matplotlib_builtin/qhull-{QHULL_VERSION}/src/libqhull_r/qhull_ra.h",
        *[f"PCbuild/{project}" for project, _guid in [*MATPLOTLIB_SUPPORT_PROJECT_ITEMS, *MATPLOTLIB_EXTENSION_PROJECT_ITEMS]],
    ],
    python_packages=["matplotlib", "mpl_toolkits"],
    static_library_projects_release_x64=[
        *[project for project, _guid in MATPLOTLIB_SUPPORT_PROJECT_ITEMS],
        *[project for project, _guid in MATPLOTLIB_EXTENSION_PROJECT_ITEMS],
    ],
    native_static_projects=[
        {"project": project, "guid": guid}
        for project, guid in [*MATPLOTLIB_SUPPORT_PROJECT_ITEMS, *MATPLOTLIB_EXTENSION_PROJECT_ITEMS]
    ],
    builtin_module_registrations=_selected_builtin_module_registrations(),
    python_link_dependencies_release_x64=_selected_python_link_dependencies(),
    prepare_source_hooks=[prepare_matplotlib_project],
)
