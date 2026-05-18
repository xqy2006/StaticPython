from __future__ import annotations

import os
import re
from pathlib import Path
import xml.etree.ElementTree as ET

from libs import pypi_library, source_path, write_source_text
from tools import download_first_available, extract_source_archive


MATPLOTLIB_RELEASE_VERSION = "3.10.9"
FREETYPE_VERSION = "2.6.1"
QHULL_VERSION = "8.0.2"
SDL2_VERSION = "2.32.10"
FREETYPE_TAG = f"VER-{FREETYPE_VERSION.replace('.', '-')}"

MATPLOTLIB_AGG_PROJECT_GUID = "{44B16CB8-02F2-4C8A-9949-66E0434F643E}"
MATPLOTLIB_FREETYPE_PROJECT_GUID = "{8EEDC81D-B835-4F59-A539-3871C33B1871}"
MATPLOTLIB_QHULL_PROJECT_GUID = "{9C48D991-EB14-4E73-A466-6E676E26E2EE}"
MATPLOTLIB_BACKEND_AGG_PROJECT_GUID = "{12F9D102-207B-4D9A-8650-80F67146540E}"
MATPLOTLIB_BACKEND_SDL_PROJECT_GUID = "{6D3550EE-5C94-44C8-9A44-3A66B35A6C61}"
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
            fr"..\matplotlib_builtin\freetype-{FREETYPE_VERSION}\include",
            r"..\pybind11_builtin\include",
        ],
        "link_libs": [
            "matplotlib_agg.lib",
            "matplotlib_freetype.lib",
        ],
    },
    "matplotlib.backends._backend_sdl": {
        "guid": MATPLOTLIB_BACKEND_SDL_PROJECT_GUID,
        "target": "matplotlib.backends._backend_sdl",
        "pyinit": "PyInit__backend_sdl",
        "sources": [
            "src/_backend_sdl.cpp",
        ],
        "include_dirs": [
            r"..\matplotlib_builtin\source\src",
            fr"..\matplotlib_builtin\SDL-{SDL2_VERSION}\include",
            r"..\pybind11_builtin\include",
        ],
        "definitions": [
            "SDL_MAIN_HANDLED",
        ],
        "link_libs": [
            "matplotlib_sdl2.lib",
            "user32.lib",
            "gdi32.lib",
            "winmm.lib",
            "imm32.lib",
            "ole32.lib",
            "oleaut32.lib",
            "version.lib",
            "uuid.lib",
            "shell32.lib",
            "setupapi.lib",
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
            fr"..\matplotlib_builtin\freetype-{FREETYPE_VERSION}\include",
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
            fr"..\matplotlib_builtin\qhull-{QHULL_VERSION}\src",
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
    "matplotlib_sdl2": {
        "project": "matplotlib_sdl2.vcxproj",
        "guid": "{68D0E0E2-65A1-41A8-B0BF-52B60A412B90}",
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
            f"https://gitlab.freedesktop.org/freetype/freetype/-/archive/{FREETYPE_TAG}/freetype-{FREETYPE_TAG}.tar.gz",
            f"https://github.com/freetype/freetype/archive/refs/tags/{FREETYPE_TAG}.tar.gz",
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


def ensure_sdl2_source(context) -> Path:
    version = SDL2_VERSION
    source_dir = source_path(context, f"matplotlib_builtin/SDL-{version}")
    if (source_dir / "include" / "SDL.h").exists():
        return source_dir

    archive_path = _downloaded_archive_path(
        context,
        "SDL2",
        version,
        f"SDL-{version}.zip",
    )
    used_source = download_first_available(
        context.log,
        [
            f"https://github.com/libsdl-org/SDL/archive/refs/tags/release-{version}.zip",
        ],
        archive_path,
    )
    extracted_root = _extract_archive_if_needed(
        context,
        archive_path,
        source_dir,
        final_name=f"SDL-{version}",
    )
    context.log(f"materialized SDL {version} from {used_source}")
    return extracted_root


def _sdl_source_files(context) -> list[str]:
    project_path = source_path(context, f"matplotlib_builtin/SDL-{SDL2_VERSION}/VisualC/SDL/SDL.vcxproj")
    root = ET.fromstring(project_path.read_text(encoding="utf-8"))
    namespace = {"msbuild": "http://schemas.microsoft.com/developer/msbuild/2003"}
    source_files: list[str] = []
    for element in root.findall(".//msbuild:ClCompile", namespace):
        include = element.get("Include")
        if not include:
            continue
        normalized = include.replace("\\", "/")
        if not normalized.startswith("../../"):
            continue
        source_files.append(normalized[6:])
    if not source_files:
        raise RuntimeError(f"could not discover SDL source files from {project_path}")
    return list(dict.fromkeys(source_files))


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


def _write_mpl_toolkits_package_init(context) -> None:
    write_source_text(
        context,
        "Lib/mpl_toolkits/__init__.py",
        '"""StaticPython bootstrap for mpl_toolkits."""\n'
        "from pkgutil import extend_path\n\n"
        "__path__ = extend_path(__path__, __name__)\n",
    )


def _patch_matplotlib_backend_registry(context) -> None:
    path = source_path(context, "Lib/matplotlib/backends/registry.py")
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")

    builtin_anchor = '        "template": "headless",\n'
    if '"sdl2": "sdl2"' not in text:
        text = text.replace(
            builtin_anchor,
            builtin_anchor + '        "sdl2": "sdl2",\n',
            1,
        )
        gui_anchor = '        "wx": "wxagg",\n'
        text = text.replace(
            gui_anchor,
            gui_anchor + '        "sdl2": "sdl2",\n',
            1,
        )
        write_source_text(context, "Lib/matplotlib/backends/registry.py", text)


def _patch_matplotlib_pyplot_autobackend(context) -> None:
    path = source_path(context, "Lib/matplotlib/pyplot.py")
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    old = '            "macosx", "qtagg", "gtk4agg", "gtk3agg", "tkagg", "wxagg"]\n'
    new = '            "macosx", "qtagg", "gtk4agg", "gtk3agg", "sdl2", "tkagg", "wxagg"]\n'
    patched = text.replace(old, new, 1)
    if patched != text:
        write_source_text(context, "Lib/matplotlib/pyplot.py", patched)


def _write_backend_sdl_module(context) -> None:
    write_source_text(
        context,
        "Lib/matplotlib/backends/backend_sdl2.py",
        """from __future__ import annotations

import time

from matplotlib import _api
from matplotlib._pylab_helpers import Gcf
from matplotlib.backend_bases import CloseEvent, FigureManagerBase, ResizeEvent, TimerBase, _Backend
from matplotlib.backends.backend_agg import FigureCanvasAgg

from matplotlib.backends import _backend_sdl


class TimerSDL(TimerBase):
    def __init__(self, *args, **kwargs):
        self._timer = None
        super().__init__(*args, **kwargs)

    def _timer_start(self):
        self._timer_stop()
        self._timer = _backend_sdl.Timer(self._on_timer, self.interval, self.single_shot)
        self._timer.start()

    def _timer_stop(self):
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def _timer_set_interval(self):
        if self._timer is not None:
            self._timer.set_interval(self.interval)

    def _timer_set_single_shot(self):
        if self._timer is not None:
            self._timer.set_single_shot(self.single_shot)


class FigureCanvasSDL(FigureCanvasAgg):
    required_interactive_framework = "sdl2"
    manager_class = _api.classproperty(lambda cls: FigureManagerSDL)
    _timer_cls = TimerSDL
    supports_blit = False

    def __init__(self, figure=None):
        super().__init__(figure=figure)
        self._window = None
        self._closed = False

    def _ensure_window(self):
        if self._closed and self._window is None:
            raise RuntimeError("the SDL figure window has already been closed")
        if self._window is None:
            width, height = [int(value) for value in self.get_width_height()]
            self._window = _backend_sdl.Window(self.manager.get_window_title(), width, height, self)
        return self._window

    def draw(self):
        super().draw()
        if self._closed or self._window is None:
            return
        width, height = [int(value) for value in self.get_width_height()]
        self._window.present(memoryview(self.buffer_rgba()), width, height)

    def draw_idle(self):
        if self._closed:
            return
        self._ensure_window().request_redraw()

    def flush_events(self):
        _backend_sdl.process_events()

    def start_event_loop(self, timeout=0):
        if self._closed:
            return
        self._looping = True
        deadline = None if timeout <= 0 else time.monotonic() + timeout
        while self._looping and not self._closed:
            _backend_sdl.process_events()
            if deadline is not None and time.monotonic() >= deadline:
                break
            time.sleep(0.01)

    def _handle_redraw(self):
        if not self._closed:
            self.draw()

    def _handle_resize(self, width, height):
        if self._closed:
            return
        if width <= 0 or height <= 0:
            return
        dpi = self.figure.dpi
        self.figure.set_size_inches(width / dpi, height / dpi, forward=False)
        ResizeEvent("resize_event", self)._process()
        self.draw()

    def _handle_close(self):
        if self._closed:
            return
        self._closed = True
        self.stop_event_loop()
        CloseEvent("close_event", self)._process()
        manager = getattr(self, "manager", None)
        if manager is not None:
            try:
                Gcf.destroy(manager)
            except Exception:
                manager.destroy()


class FigureManagerSDL(FigureManagerBase):
    @classmethod
    def start_main_loop(cls):
        windows = []
        for manager in Gcf.get_all_fig_managers():
            manager.show()
            window = getattr(manager.canvas, "_window", None)
            if window is not None:
                windows.append(window)
        if windows:
            _backend_sdl.run_event_loop(windows)

    def show(self):
        if self.canvas._closed and self.canvas._window is None:
            return
        window = self.canvas._ensure_window()
        window.show()
        self.canvas.draw()

    def destroy(self):
        if getattr(self, "_destroying", False):
            return
        self._destroying = True
        try:
            self.canvas.stop_event_loop()
            self.canvas._closed = True
            window = self.canvas._window
            if window is not None:
                self.canvas._window = None
                window.close()
        finally:
            self._destroying = False

    def set_window_title(self, title):
        super().set_window_title(title)
        if self.canvas._window is not None:
            self.canvas._window.set_title(title)

    def resize(self, w, h):
        if self.canvas._window is not None:
            self.canvas._window.resize(int(w), int(h))


@_Backend.export
class _BackendSDL2(_Backend):
    backend_version = "SDL2"
    FigureCanvas = FigureCanvasSDL
    FigureManager = FigureManagerSDL
    mainloop = FigureManagerSDL.start_main_loop
""",
    )
    write_source_text(
        context,
        "matplotlib_builtin/source/src/_backend_sdl.cpp",
        """#include <SDL.h>
#include <pybind11/pybind11.h>

#include <algorithm>
#include <atomic>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

namespace py = pybind11;

namespace {

constexpr int SDL_EVENT_REDRAW = 1;
constexpr int SDL_EVENT_TIMER = 2;

Uint32 g_sdl_event_type = 0;
std::unordered_map<Uint32, class Window*> g_windows;

std::string sdl_error(const char* prefix)
{
    return std::string(prefix) + ": " + SDL_GetError();
}

void ensure_sdl_ready()
{
    if ((SDL_WasInit(SDL_INIT_VIDEO) == 0 || SDL_WasInit(SDL_INIT_TIMER) == 0) &&
        SDL_Init(SDL_INIT_VIDEO | SDL_INIT_TIMER) != 0) {
        SDL_SetMainReady();
        if (SDL_Init(SDL_INIT_VIDEO | SDL_INIT_TIMER) != 0) {
            throw std::runtime_error(sdl_error("failed to initialize SDL"));
        }
    } else {
        SDL_SetMainReady();
    }
    if (g_sdl_event_type == 0) {
        g_sdl_event_type = SDL_RegisterEvents(1);
        if (g_sdl_event_type == static_cast<Uint32>(-1)) {
            throw std::runtime_error(sdl_error("failed to reserve SDL user event"));
        }
        SDL_SetHint(SDL_HINT_RENDER_DRIVER, "software");
    }
}

Uint32 sdl_event_type()
{
    ensure_sdl_ready();
    return g_sdl_event_type;
}

class Timer {
  public:
    Timer(py::object callback, int interval, bool single_shot)
        : callback_(std::move(callback)),
          interval_(std::max(interval, 1)),
          single_shot_(single_shot)
    {
    }

    ~Timer()
    {
        stop();
    }

    void start()
    {
        stop();
        ensure_sdl_ready();
        generation_.fetch_add(1);
        SDL_TimerID id = SDL_AddTimer(static_cast<Uint32>(interval_), &Timer::timer_callback, this);
        if (id == 0) {
            throw std::runtime_error(sdl_error("failed to start SDL timer"));
        }
        timer_id_.store(id);
    }

    void stop()
    {
        generation_.fetch_add(1);
        SDL_TimerID id = timer_id_.exchange(0);
        if (id != 0) {
            SDL_RemoveTimer(id);
        }
    }

    void set_interval(int interval)
    {
        interval_ = std::max(interval, 1);
        if (timer_id_.load() != 0) {
            start();
        }
    }

    void set_single_shot(bool single_shot)
    {
        single_shot_ = single_shot;
    }

    void dispatch(std::uint64_t generation)
    {
        if (generation != generation_.load()) {
            return;
        }
        if (single_shot_) {
            timer_id_.store(0);
        }
        try {
            callback_();
        } catch (py::error_already_set& error) {
            PyErr_WriteUnraisable(error.value().ptr());
        }
    }

  private:
    static Uint32 SDLCALL timer_callback(Uint32 interval, void* userdata)
    {
        auto* self = static_cast<Timer*>(userdata);
        SDL_Event event{};
        event.type = sdl_event_type();
        event.user.code = SDL_EVENT_TIMER;
        event.user.data1 = self;
        event.user.data2 = reinterpret_cast<void*>(static_cast<uintptr_t>(self->generation_.load()));
        SDL_PushEvent(&event);
        return self->single_shot_ ? 0 : interval;
    }

    py::object callback_;
    std::atomic<std::uint64_t> generation_{0};
    std::atomic<SDL_TimerID> timer_id_{0};
    int interval_;
    bool single_shot_;
};

class Window {
  public:
    Window(const std::string& title, int width, int height, py::object canvas)
        : canvas_(std::move(canvas)),
          width_(std::max(width, 1)),
          height_(std::max(height, 1))
    {
        ensure_sdl_ready();
        window_ = SDL_CreateWindow(
            title.c_str(),
            SDL_WINDOWPOS_UNDEFINED,
            SDL_WINDOWPOS_UNDEFINED,
            width_,
            height_,
            SDL_WINDOW_HIDDEN | SDL_WINDOW_RESIZABLE
        );
        if (window_ == nullptr) {
            throw std::runtime_error(sdl_error("failed to create SDL window"));
        }
        renderer_ = SDL_CreateRenderer(window_, -1, SDL_RENDERER_SOFTWARE);
        if (renderer_ == nullptr) {
            SDL_DestroyWindow(window_);
            window_ = nullptr;
            throw std::runtime_error(sdl_error("failed to create SDL renderer"));
        }
        SDL_SetRenderDrawColor(renderer_, 0, 0, 0, 255);
        window_id_ = SDL_GetWindowID(window_);
        g_windows[window_id_] = this;
    }

    ~Window()
    {
        close();
    }

    void show()
    {
        if (!is_open()) {
            return;
        }
        SDL_ShowWindow(window_);
        request_redraw();
    }

    void set_title(const std::string& title)
    {
        if (is_open()) {
            SDL_SetWindowTitle(window_, title.c_str());
        }
    }

    void resize(int width, int height)
    {
        if (!is_open()) {
            return;
        }
        SDL_SetWindowSize(window_, std::max(width, 1), std::max(height, 1));
    }

    void request_redraw()
    {
        if (!is_open() || redraw_pending_) {
            return;
        }
        SDL_Event event{};
        event.type = sdl_event_type();
        event.user.code = SDL_EVENT_REDRAW;
        event.user.data1 = this;
        redraw_pending_ = true;
        if (SDL_PushEvent(&event) < 0) {
            redraw_pending_ = false;
            throw std::runtime_error(sdl_error("failed to queue redraw request"));
        }
    }

    void process_events();

    void present(py::buffer rgba, int width, int height)
    {
        ensure_open();
        py::buffer_info info = rgba.request();
        if (width <= 0 || height <= 0) {
            return;
        }
        auto expected = static_cast<size_t>(width) * static_cast<size_t>(height) * 4;
        if (info.itemsize != 1 || static_cast<size_t>(info.size) < expected) {
            throw std::runtime_error("expected a contiguous RGBA byte buffer");
        }
        ensure_texture(width, height);
        if (SDL_UpdateTexture(texture_, nullptr, info.ptr, width * 4) != 0) {
            throw std::runtime_error(sdl_error("failed to update SDL texture"));
        }
        if (SDL_RenderClear(renderer_) != 0) {
            throw std::runtime_error(sdl_error("failed to clear SDL renderer"));
        }
        if (SDL_RenderCopy(renderer_, texture_, nullptr, nullptr) != 0) {
            throw std::runtime_error(sdl_error("failed to copy SDL texture"));
        }
        SDL_RenderPresent(renderer_);
    }

    void close()
    {
        if (closed_) {
            return;
        }
        closed_ = true;
        redraw_pending_ = false;
        if (window_id_ != 0) {
            g_windows.erase(window_id_);
            window_id_ = 0;
        }
        if (texture_ != nullptr) {
            SDL_DestroyTexture(texture_);
            texture_ = nullptr;
        }
        if (renderer_ != nullptr) {
            SDL_DestroyRenderer(renderer_);
            renderer_ = nullptr;
        }
        if (window_ != nullptr) {
            SDL_DestroyWindow(window_);
            window_ = nullptr;
        }
        canvas_ = py::none();
    }

    bool is_open() const
    {
        return !closed_ && window_ != nullptr && renderer_ != nullptr;
    }

    Uint32 window_id() const
    {
        return window_id_;
    }

    void dispatch_redraw()
    {
        if (!is_open()) {
            return;
        }
        redraw_pending_ = false;
        call_canvas("_handle_redraw");
    }

    void dispatch_resize(int width, int height)
    {
        if (!is_open()) {
            return;
        }
        width_ = std::max(width, 1);
        height_ = std::max(height, 1);
        call_canvas("_handle_resize", width_, height_);
    }

    void dispatch_close()
    {
        if (closed_) {
            return;
        }
        call_canvas("_handle_close");
    }

  private:
    void ensure_open() const
    {
        if (!is_open()) {
            throw std::runtime_error("the SDL figure window is closed");
        }
    }

    void ensure_texture(int width, int height)
    {
        if (texture_ != nullptr && texture_width_ == width && texture_height_ == height) {
            return;
        }
        if (texture_ != nullptr) {
            SDL_DestroyTexture(texture_);
            texture_ = nullptr;
        }
        texture_ = SDL_CreateTexture(
            renderer_,
            SDL_PIXELFORMAT_RGBA32,
            SDL_TEXTUREACCESS_STREAMING,
            width,
            height
        );
        if (texture_ == nullptr) {
            throw std::runtime_error(sdl_error("failed to create SDL texture"));
        }
        texture_width_ = width;
        texture_height_ = height;
    }

    template <typename... Args>
    void call_canvas(const char* method_name, Args&&... args)
    {
        if (canvas_.is_none()) {
            return;
        }
        try {
            canvas_.attr(method_name)(std::forward<Args>(args)...);
        } catch (py::error_already_set& error) {
            PyErr_WriteUnraisable(error.value().ptr());
        }
    }

    py::object canvas_;
    SDL_Window* window_ = nullptr;
    SDL_Renderer* renderer_ = nullptr;
    SDL_Texture* texture_ = nullptr;
    Uint32 window_id_ = 0;
    int width_ = 0;
    int height_ = 0;
    int texture_width_ = 0;
    int texture_height_ = 0;
    bool closed_ = false;
    bool redraw_pending_ = false;
};

Window* lookup_window(Uint32 window_id)
{
    auto it = g_windows.find(window_id);
    return it == g_windows.end() ? nullptr : it->second;
}

void dispatch_event(const SDL_Event& event)
{
    if (event.type == SDL_WINDOWEVENT) {
        auto* window = lookup_window(event.window.windowID);
        if (window == nullptr) {
            return;
        }
        switch (event.window.event) {
        case SDL_WINDOWEVENT_EXPOSED:
        case SDL_WINDOWEVENT_SHOWN:
        case SDL_WINDOWEVENT_RESTORED:
            window->dispatch_redraw();
            break;
        case SDL_WINDOWEVENT_SIZE_CHANGED:
        case SDL_WINDOWEVENT_RESIZED:
            window->dispatch_resize(event.window.data1, event.window.data2);
            break;
        case SDL_WINDOWEVENT_CLOSE:
            window->dispatch_close();
            break;
        default:
            break;
        }
        return;
    }

    if (event.type == SDL_QUIT) {
        std::vector<Window*> snapshot;
        snapshot.reserve(g_windows.size());
        for (const auto& item : g_windows) {
            snapshot.push_back(item.second);
        }
        for (auto* window : snapshot) {
            if (window != nullptr) {
                window->dispatch_close();
            }
        }
        return;
    }

    if (event.type == sdl_event_type()) {
        if (event.user.code == SDL_EVENT_REDRAW) {
            auto* window = static_cast<Window*>(event.user.data1);
            if (window != nullptr) {
                window->dispatch_redraw();
            }
        } else if (event.user.code == SDL_EVENT_TIMER) {
            auto* timer = static_cast<Timer*>(event.user.data1);
            if (timer != nullptr) {
                auto generation = static_cast<std::uint64_t>(reinterpret_cast<uintptr_t>(event.user.data2));
                timer->dispatch(generation);
            }
        }
    }
}

void process_events_impl()
{
    ensure_sdl_ready();
    SDL_Event event{};
    while (SDL_PollEvent(&event) != 0) {
        dispatch_event(event);
    }
}

bool any_open(const std::vector<Window*>& windows)
{
    for (auto* window : windows) {
        if (window != nullptr && window->is_open()) {
            return true;
        }
    }
    return false;
}

}  // namespace

void Window::process_events()
{
    process_events_impl();
}

PYBIND11_MODULE(_backend_sdl, m)
{
    py::class_<Timer>(m, "Timer")
        .def(py::init<py::object, int, bool>(), py::arg("callback"), py::arg("interval"), py::arg("single_shot"))
        .def("start", &Timer::start)
        .def("stop", &Timer::stop)
        .def("set_interval", &Timer::set_interval)
        .def("set_single_shot", &Timer::set_single_shot);

    py::class_<Window>(m, "Window")
        .def(py::init<const std::string&, int, int, py::object>(), py::arg("title"), py::arg("width"), py::arg("height"), py::arg("canvas"))
        .def("show", &Window::show)
        .def("set_title", &Window::set_title)
        .def("resize", &Window::resize)
        .def("request_redraw", &Window::request_redraw)
        .def("process_events", &Window::process_events)
        .def("present", &Window::present, py::arg("rgba"), py::arg("width"), py::arg("height"))
        .def("close", &Window::close);

    m.def("process_events", &process_events_impl);
    m.def("run_event_loop", [](py::iterable windows) {
        ensure_sdl_ready();
        std::vector<Window*> tracked;
        for (py::handle item : windows) {
            tracked.push_back(item.cast<Window*>());
        }
        SDL_Event event{};
        while (any_open(tracked)) {
            if (SDL_WaitEventTimeout(&event, 50) != 0) {
                dispatch_event(event);
            }
            process_events_impl();
        }
    });
}
""",
    )



def _patch_matplotlib_sources(context) -> None:
    path = source_path(context, "matplotlib_builtin/source/src/_c_internal_utils.cpp")
    if path.exists():
        text = path.read_text(encoding="utf-8")
        patched = text.replace('LoadLibrary("user32.dll")', 'LoadLibraryA("user32.dll")')
        if patched != text:
            write_source_text(context, "matplotlib_builtin/source/src/_c_internal_utils.cpp", patched)
    enums_path = source_path(context, "matplotlib_builtin/source/src")
    if enums_path.exists():
        write_source_text(context, "matplotlib_builtin/source/src/_enums.h", PATCHED_MATPLOTLIB_ENUMS_HEADER)
    _patch_matplotlib_backend_registry(context)
    _patch_matplotlib_pyplot_autobackend(context)


def _ensure_required_files(context, files: list[str]) -> None:
    missing = [path for path in files if not source_path(context, path).exists()]
    if missing:
        raise RuntimeError("matplotlib source files are missing: " + ", ".join(missing))


def _set_matplotlib_materialized_paths(context) -> None:
    integration = LIBRARY_INTEGRATION
    paths = [
        "Lib/matplotlib/__init__.py",
        "Lib/matplotlib/_version.py",
        "Lib/pylab.py",
        "matplotlib_builtin/source/PKG-INFO",
    ]

    optional_if_exists = [
        "Lib/mpl_toolkits",
        "Lib/mpl_toolkits/__init__.py",
        "Lib/matplotlib/backends/backend_sdl2.py",
        "Lib/matplotlib/pyplot.py",
        "Lib/matplotlib/backends/registry.py",
        "matplotlib_builtin/source/extern/agg24-svn/include/agg_basics.h",
        "matplotlib_builtin/source/src/ft2font_wrapper.cpp",
        "matplotlib_builtin/source/src/_backend_agg_wrapper.cpp",
        "matplotlib_builtin/source/src/_image_wrapper.cpp",
        "matplotlib_builtin/source/src/_path_wrapper.cpp",
        "matplotlib_builtin/source/src/_qhull_wrapper.cpp",
        "matplotlib_builtin/source/src/_c_internal_utils.cpp",
        "matplotlib_builtin/source/src/tri/_tri.cpp",
        "matplotlib_builtin/source/src/tri/_tri_wrapper.cpp",
        f"matplotlib_builtin/SDL-{SDL2_VERSION}/include/SDL.h",
        f"matplotlib_builtin/freetype-{FREETYPE_VERSION}/include/ft2build.h",
        f"matplotlib_builtin/qhull-{QHULL_VERSION}/src/libqhull_r/qhull_ra.h",
        "PCbuild/matplotlib_agg.vcxproj",
        "PCbuild/matplotlib_freetype.vcxproj",
        "PCbuild/matplotlib_qhull.vcxproj",
        "PCbuild/matplotlib_sdl2.vcxproj",
        "PCbuild/matplotlib.backends._backend_agg.vcxproj",
        "PCbuild/matplotlib.backends._backend_sdl.vcxproj",
        "PCbuild/matplotlib._c_internal_utils.vcxproj",
        "PCbuild/matplotlib.ft2font.vcxproj",
        "PCbuild/matplotlib._image.vcxproj",
        "PCbuild/matplotlib._path.vcxproj",
        "PCbuild/matplotlib._qhull.vcxproj",
        "PCbuild/matplotlib._tri.vcxproj",
    ]
    paths.extend(path for path in optional_if_exists if source_path(context, path).exists())
    integration.materialized_paths = list(dict.fromkeys(paths))


def prepare_matplotlib_project(context) -> None:
    if context.platform != "x64":
        raise RuntimeError(f"matplotlib builtin integration currently supports only x64, not {context.platform}")

    matplotlib_root = source_path(context, "Lib/matplotlib")
    if not matplotlib_root.exists():
        raise RuntimeError("matplotlib package source was not materialized")

    ensure_freetype_source(context)
    ensure_sdl2_source(context)
    ensure_qhull_source(context)
    _write_matplotlib_version_module(context)
    if source_path(context, "Lib/mpl_toolkits").exists():
        _write_mpl_toolkits_package_init(context)
    _write_backend_sdl_module(context)
    _patch_matplotlib_sources(context)

    required_files = [
        "Lib/matplotlib/__init__.py",
        "Lib/matplotlib/backends/backend_sdl2.py",
        "Lib/pylab.py",
        "matplotlib_builtin/source/src/_backend_sdl.cpp",
        f"matplotlib_builtin/SDL-{SDL2_VERSION}/include/SDL.h",
        f"matplotlib_builtin/SDL-{SDL2_VERSION}/src/SDL.c",
        f"matplotlib_builtin/freetype-{FREETYPE_VERSION}/include/ft2build.h",
        f"matplotlib_builtin/qhull-{QHULL_VERSION}/src/libqhull_r/qhull_ra.h",
        "pybind11_builtin/include/pybind11/pybind11.h",
    ]
    optional_required_if_present = [
        "Lib/mpl_toolkits",
        "Lib/mpl_toolkits/__init__.py",
        "matplotlib_builtin/source/src/ft2font_wrapper.cpp",
        "matplotlib_builtin/source/extern/agg24-svn/include/agg_basics.h",
    ]
    for relative in optional_required_if_present:
        if source_path(context, relative).exists():
            required_files.append(relative)
    _ensure_required_files(context, required_files)

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
    write_source_text(
        context,
        "PCbuild/matplotlib_sdl2.vcxproj",
        _render_static_library_project(
            project_guid=MATPLOTLIB_SUPPORT_PROJECTS["matplotlib_sdl2"]["guid"],
            root_namespace="matplotlib_sdl2",
            target_name="matplotlib_sdl2",
            source_files=_sdl_source_files(context),
            source_root=fr"..\matplotlib_builtin\SDL-{SDL2_VERSION}",
            include_dirs=[fr"..\matplotlib_builtin\SDL-{SDL2_VERSION}\include"],
            definitions=[
                "SDL_STATIC_LIB",
                "SDL_MAIN_HANDLED",
            ],
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
    _set_matplotlib_materialized_paths(context)


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
        "?lib/mpl_toolkits": "Lib/mpl_toolkits",
        "lib/pylab.py": "Lib/pylab.py",
        "src": "matplotlib_builtin/source/src",
        "?extern/agg24-svn||?agg24||?agg23": "matplotlib_builtin/source/extern/agg24-svn",
        "PKG-INFO": "matplotlib_builtin/source/PKG-INFO",
    },
    source_ignore_patterns=[
        "tests",
    ],
    materialized_paths=[
        "Lib/matplotlib/__init__.py",
        "Lib/matplotlib/_version.py",
        "Lib/matplotlib/backends/backend_sdl2.py",
        "Lib/matplotlib/mpl-data/matplotlibrc",
        "Lib/mpl_toolkits",
        "Lib/mpl_toolkits/__init__.py",
        "Lib/pylab.py",
        "matplotlib_builtin/source/src/_backend_sdl.cpp",
        "matplotlib_builtin/source/src/ft2font_wrapper.cpp",
        "matplotlib_builtin/source/extern/agg24-svn/include/agg_basics.h",
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
