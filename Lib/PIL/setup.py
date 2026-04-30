from __future__ import annotations

import ast
from pathlib import Path

from libs import inline_verification_step, pypi_library, source_path, write_source_text


PIL_IMAGING_PROJECT_GUID = "{0AC7C2D2-056F-464A-9297-0BF67EC9499A}"
PIL_IMAGINGMATH_PROJECT_GUID = "{B7A8FF28-707A-4F50-A0C1-D50E30E6BC6B}"
PIL_IMAGINGMORPH_PROJECT_GUID = "{E2259EA5-4DA5-4128-A2E6-2649577C51A9}"

PIL_TOP_LEVEL_IMAGING_SOURCES = [
    "_imaging.c",
    "decode.c",
    "encode.c",
    "map.c",
    "display.c",
    "outline.c",
    "path.c",
]


def _project_configurations() -> str:
    return """  <ItemGroup Label="ProjectConfigurations">
    <ProjectConfiguration Include="Release|x64">
      <Configuration>Release</Configuration>
      <Platform>x64</Platform>
    </ProjectConfiguration>
  </ItemGroup>
"""


def _object_file_name(source_file: str) -> str:
    stem = source_file.replace("/", "_").replace("\\", "_")
    return f"$(IntDir){stem}.obj"


def _compile_items(source_files: list[str]) -> str:
    items = []
    for name in source_files:
        windows_name = name.replace("/", "\\")
        include_path = f"..\\pillow_builtin\\src\\{windows_name}"
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


def _render_pil_project(
    *,
    project_guid: str,
    root_namespace: str,
    target_name: str,
    source_files: list[str],
    extra_definitions: list[str],
    include_zlib: bool = False,
) -> str:
    include_dirs = [
        r"..\pillow_builtin\src",
        r"..\pillow_builtin\src\libImaging",
    ]
    if include_zlib:
        include_dirs.append(r"$(zlibDir)")
    include_text = ";".join([*include_dirs, "%(AdditionalIncludeDirectories)"])
    definitions = ";".join([*extra_definitions, "Py_NO_ENABLE_SHARED", "_CRT_SECURE_NO_WARNINGS", "%(PreprocessorDefinitions)"])
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
      <PreprocessorDefinitions>{definitions}</PreprocessorDefinitions>
      <DisableSpecificWarnings>4244;4267;4996;%(DisableSpecificWarnings)</DisableSpecificWarnings>
      <AdditionalOptions>/bigobj %(AdditionalOptions)</AdditionalOptions>
      <RuntimeLibrary Condition="'$(Configuration)|$(Platform)'=='Release|x64'">MultiThreaded</RuntimeLibrary>
    </ClCompile>
  </ItemDefinitionGroup>
  <ItemGroup>
{_compile_items(source_files)}
  </ItemGroup>
  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.targets" />
</Project>
"""


def _parse_literal_module_attribute(path: Path, attribute_name: str) -> str | None:
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == attribute_name for target in node.targets):
            continue
        try:
            value = ast.literal_eval(node.value)
        except (SyntaxError, ValueError):
            return None
        if isinstance(value, str):
            return value
        return None
    return None


def _parse_pillow_version(context) -> str:
    for candidate in ("Lib/PIL/_version.py", "Lib/PIL/__init__.py"):
        path = source_path(context, candidate)
        if not path.exists():
            continue
        version = _parse_literal_module_attribute(path, "__version__")
        if version:
            return version
    raise RuntimeError("could not find a literal Pillow __version__ in Lib/PIL/_version.py or Lib/PIL/__init__.py")


def _discover_imaging_sources(context) -> list[str]:
    root = source_path(context, "pillow_builtin/src")
    source_files = [name for name in PIL_TOP_LEVEL_IMAGING_SOURCES if (root / name).exists()]
    source_files.extend(
        f"libImaging/{path.name}"
        for path in sorted((root / "libImaging").glob("*.c"))
    )
    missing = [name for name in source_files if not (root / name).exists()]
    if missing:
        raise RuntimeError("Pillow _imaging source files are missing: " + ", ".join(missing))
    return source_files


def prepare_pillow_projects(context) -> None:
    version = _parse_pillow_version(context)
    common_definitions = [f'PILLOW_VERSION=&quot;{version}&quot;']
    write_source_text(
        context,
        "PCbuild/PIL._imaging.vcxproj",
        _render_pil_project(
            project_guid=PIL_IMAGING_PROJECT_GUID,
            root_namespace="PIL__imaging",
            target_name="PIL._imaging",
            source_files=_discover_imaging_sources(context),
            extra_definitions=[*common_definitions, "HAVE_LIBZ"],
            include_zlib=True,
        ),
    )
    write_source_text(
        context,
        "PCbuild/PIL._imagingmath.vcxproj",
        _render_pil_project(
            project_guid=PIL_IMAGINGMATH_PROJECT_GUID,
            root_namespace="PIL__imagingmath",
            target_name="PIL._imagingmath",
            source_files=["_imagingmath.c"],
            extra_definitions=common_definitions,
        ),
    )
    write_source_text(
        context,
        "PCbuild/PIL._imagingmorph.vcxproj",
        _render_pil_project(
            project_guid=PIL_IMAGINGMORPH_PROJECT_GUID,
            root_namespace="PIL__imagingmorph",
            target_name="PIL._imagingmorph",
            source_files=["_imagingmorph.c"],
            extra_definitions=common_definitions,
        ),
    )


LIBRARY_INTEGRATION = pypi_library(
    name="PIL",
    project_name="pillow",
    source_mapping={
        "src/PIL": "Lib/PIL",
        "src": "pillow_builtin/src",
    },
    materialized_paths=[
        "Lib/PIL/__init__.py",
        "Lib/PIL/_version.py",
        "Lib/PIL/Image.py",
        "Lib/PIL/ImageFile.py",
        "Lib/PIL/BmpImagePlugin.py",
        "Lib/PIL/PngImagePlugin.py",
        "pillow_builtin/src/_imaging.c",
        "pillow_builtin/src/_imagingmath.c",
        "pillow_builtin/src/_imagingmorph.c",
        "pillow_builtin/src/libImaging/Access.c",
        "pillow_builtin/src/libImaging/Storage.c",
    ],
    python_packages=["PIL"],
    verification_imports=["PIL.Image", "PIL._imaging", "PIL._imagingmath", "PIL._imagingmorph"],
    static_library_projects_release_x64=[
        "PIL._imaging.vcxproj",
        "PIL._imagingmath.vcxproj",
        "PIL._imagingmorph.vcxproj",
    ],
    native_static_projects=[
        {"project": "PIL._imaging.vcxproj", "guid": PIL_IMAGING_PROJECT_GUID},
        {"project": "PIL._imagingmath.vcxproj", "guid": PIL_IMAGINGMATH_PROJECT_GUID},
        {"project": "PIL._imagingmorph.vcxproj", "guid": PIL_IMAGINGMORPH_PROJECT_GUID},
    ],
    builtin_module_registrations=[
        {"name": "PIL._imaging", "pyinit": "PyInit__imaging"},
        {"name": "PIL._imagingmath", "pyinit": "PyInit__imagingmath"},
        {"name": "PIL._imagingmorph", "pyinit": "PyInit__imagingmorph"},
    ],
    python_link_dependencies_release_x64=[
        "PIL._imaging.lib",
        "PIL._imagingmath.lib",
        "PIL._imagingmorph.lib",
        "user32.lib",
        "gdi32.lib",
    ],
    prepare_source_hooks=[prepare_pillow_projects],
    verification_steps=[
        inline_verification_step(
            "pillow-smoke",
            """
import importlib.util
from io import BytesIO

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageMath, ImageMorph, ImageOps, ImageStat

assert importlib.util.find_spec("PIL._imaging").origin == "built-in"
assert importlib.util.find_spec("PIL._imagingmath").origin == "built-in"
assert importlib.util.find_spec("PIL._imagingmorph").origin == "built-in"

Image.preinit()
Image.init()
registered = Image.registered_extensions()
assert registered[".bmp"] == "BMP"
assert registered[".png"] == "PNG"

image = Image.new("RGB", (6, 6), "navy")
draw = ImageDraw.Draw(image)
draw.rectangle((1, 1, 4, 4), fill=(255, 0, 0))

assert image.getpixel((1, 1)) == (255, 0, 0)
assert image.crop((1, 1, 5, 5)).size == (4, 4)
assert image.resize((2, 2)).size == (2, 2)
assert image.convert("L").mode == "L"
assert ImageOps.mirror(image).size == image.size
assert ImageChops.difference(image, image).getbbox() is None
assert image.filter(ImageFilter.BLUR).size == image.size
assert ImageStat.Stat(image).sum[0] > 0

thumbnail = image.copy()
thumbnail.thumbnail((3, 3))
assert thumbnail.size == (3, 3)

alpha = Image.new("RGBA", (2, 2), (10, 20, 30, 128))
composited = Image.alpha_composite(Image.new("RGBA", (2, 2), (0, 0, 0, 255)), alpha)
assert composited.mode == "RGBA"

math_result = ImageMath.lambda_eval(lambda args: args["a"] + 1, a=Image.new("L", (1, 1), 41))
assert math_result.getpixel((0, 0)) == 42

morph = ImageMorph.MorphOp(op_name="dilation4")
assert morph.get_on_pixels(Image.new("L", (3, 3), 0)) == []

for image_format in ("BMP", "PNG"):
    buffer = BytesIO()
    image.save(buffer, format=image_format)
    buffer.seek(0)
    loaded = Image.open(buffer)
    loaded.load()
    assert loaded.size == (6, 6)
    assert loaded.mode == "RGB"
""",
            timeout=300,
        )
    ],
)
