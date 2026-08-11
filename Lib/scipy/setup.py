from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from libs import pypi_library, source_path, transform_source_text, write_source_text


SCIPY_RELEASE_VERSION = "1.17.1"
SCIPY_CYTHON_REQUIREMENT = "Cython>=3.0.8,<4.0.0"

SCIPY_CCALLBACK_PROJECT_GUID = "{46A90C63-8F37-4F90-B3B4-A4DD42A08B1C}"
SCIPY_UARRAY_PROJECT_GUID = "{2B76B6C5-297C-4A7F-95F5-9724F9A388F1}"
SCIPY_POCKETFFT_PROJECT_GUID = "{7E3F5247-9B07-4D53-A0E8-D291D5E90382}"

SCIPY_CCALLBACK_MODULE = "scipy._lib._ccallback_c"
SCIPY_UARRAY_MODULE = "scipy._lib._uarray._uarray"
SCIPY_POCKETFFT_MODULE = "scipy.fft._pocketfft.pypocketfft"
SCIPY_SUPPORTED_SUBMODULES = [
    "constants",
    "fft",
    "fftpack",
    "interpolate",
    "integrate",
    "io",
    "linalg",
    "optimize",
    "signal",
    "sparse",
    "spatial",
    "special",
    "stats",
]

SCIPY_CCALLBACK_SOURCES = [
    "scipy_builtin/generated/_ccallback_c.c",
]

SCIPY_UARRAY_SOURCES = [
    "scipy_builtin/source/scipy/_lib/_uarray/_uarray_dispatch.cxx",
    "scipy_builtin/source/scipy/_lib/_uarray/vectorcall.cxx",
]

SCIPY_POCKETFFT_SOURCES = [
    "scipy_builtin/source/scipy/fft/_pocketfft/pypocketfft.cxx",
]

SCIPY_PYTHON_SOURCE_MAPPING = {
    "scipy/__init__.py": "Lib/scipy/__init__.py",
    "scipy/__config__.py.in": "scipy_builtin/source/scipy/__config__.py.in",
    "scipy/_distributor_init.py": "Lib/scipy/_distributor_init.py",
    "scipy/version.py": "Lib/scipy/version.py",
    "scipy/constants/__init__.py": "Lib/scipy/constants/__init__.py",
    "scipy/constants/_constants.py": "Lib/scipy/constants/_constants.py",
    "scipy/constants/_codata.py": "Lib/scipy/constants/_codata.py",
    "scipy/constants/constants.py": "Lib/scipy/constants/constants.py",
    "scipy/constants/codata.py": "Lib/scipy/constants/codata.py",
    "scipy/_lib/__init__.py": "Lib/scipy/_lib/__init__.py",
    "scipy/_lib/_array_api.py": "Lib/scipy/_lib/_array_api.py",
    "scipy/_lib/_array_api_compat_vendor.py": "Lib/scipy/_lib/_array_api_compat_vendor.py",
    "scipy/_lib/_array_api_docs_tables.py": "Lib/scipy/_lib/_array_api_docs_tables.py",
    "scipy/_lib/_array_api_no_0d.py": "Lib/scipy/_lib/_array_api_no_0d.py",
    "scipy/_lib/_array_api_override.py": "Lib/scipy/_lib/_array_api_override.py",
    "scipy/_lib/_bunch.py": "Lib/scipy/_lib/_bunch.py",
    "scipy/_lib/_ccallback.py": "Lib/scipy/_lib/_ccallback.py",
    "scipy/_lib/_docscrape.py": "Lib/scipy/_lib/_docscrape.py",
    "scipy/_lib/_gcutils.py": "Lib/scipy/_lib/_gcutils.py",
    "scipy/_lib/_pep440.py": "Lib/scipy/_lib/_pep440.py",
    "scipy/_lib/_public_api.py": "Lib/scipy/_lib/_public_api.py",
    "scipy/_lib/_sparse.py": "Lib/scipy/_lib/_sparse.py",
    "scipy/_lib/_testutils.py": "Lib/scipy/_lib/_testutils.py",
    "scipy/_lib/_tmpdirs.py": "Lib/scipy/_lib/_tmpdirs.py",
    "scipy/_lib/_util.py": "Lib/scipy/_lib/_util.py",
    "scipy/_lib/deprecation.py": "Lib/scipy/_lib/deprecation.py",
    "scipy/_lib/doccer.py": "Lib/scipy/_lib/doccer.py",
    "scipy/_lib/uarray.py": "Lib/scipy/_lib/uarray.py",
    "scipy/_lib/_uarray/__init__.py": "Lib/scipy/_lib/_uarray/__init__.py",
    "scipy/_lib/_uarray/_backend.py": "Lib/scipy/_lib/_uarray/_backend.py",
    "scipy/fft/__init__.py": "Lib/scipy/fft/__init__.py",
    "scipy/fft/_backend.py": "Lib/scipy/fft/_backend.py",
    "scipy/fft/_basic.py": "Lib/scipy/fft/_basic.py",
    "scipy/fft/_basic_backend.py": "Lib/scipy/fft/_basic_backend.py",
    "scipy/fft/_helper.py": "Lib/scipy/fft/_helper.py",
    "scipy/fft/_realtransforms.py": "Lib/scipy/fft/_realtransforms.py",
    "scipy/fft/_realtransforms_backend.py": "Lib/scipy/fft/_realtransforms_backend.py",
    "scipy/fft/_pocketfft/__init__.py": "Lib/scipy/fft/_pocketfft/__init__.py",
    "scipy/fft/_pocketfft/basic.py": "Lib/scipy/fft/_pocketfft/basic.py",
    "scipy/fft/_pocketfft/helper.py": "Lib/scipy/fft/_pocketfft/helper.py",
    "scipy/fft/_pocketfft/realtransforms.py": "Lib/scipy/fft/_pocketfft/realtransforms.py",
    "scipy/fftpack/_basic.py": "Lib/scipy/fftpack/_basic.py",
    "scipy/fftpack/_helper.py": "Lib/scipy/fftpack/_helper.py",
    "scipy/fftpack/_realtransforms.py": "Lib/scipy/fftpack/_realtransforms.py",
    "scipy/integrate/_quadrature.py": "Lib/scipy/integrate/_quadrature.py",
    "scipy/io/arff/__init__.py": "Lib/scipy/io/arff/__init__.py",
    "scipy/io/arff/_arffread.py": "Lib/scipy/io/arff/_arffread.py",
    "scipy/io/wavfile.py": "Lib/scipy/io/wavfile.py",
    "scipy/linalg/_special_matrices.py": "Lib/scipy/linalg/_special_matrices.py",
    "scipy/signal/_czt.py": "Lib/scipy/signal/_czt.py",
    "scipy/signal/_waveforms.py": "Lib/scipy/signal/_waveforms.py",
}

SCIPY_NATIVE_SOURCE_MAPPING = {
    "scipy/scipy_config.h.in": "scipy_builtin/source/scipy/scipy_config.h.in",
    "scipy/_lib/_ccallback_c.pyx": "scipy_builtin/source/scipy/_lib/_ccallback_c.pyx",
    "scipy/_lib/_ccallback_c.pxd": "scipy_builtin/source/scipy/_lib/_ccallback_c.pxd",
    "scipy/_lib/ccallback.pxd": "scipy_builtin/source/scipy/_lib/ccallback.pxd",
    "scipy/_lib/src/ccallback.h": "scipy_builtin/source/scipy/_lib/src/ccallback.h",
    "scipy/_lib/_uarray/_uarray_dispatch.cxx": "scipy_builtin/source/scipy/_lib/_uarray/_uarray_dispatch.cxx",
    "scipy/_lib/_uarray/vectorcall.cxx": "scipy_builtin/source/scipy/_lib/_uarray/vectorcall.cxx",
    "scipy/_lib/_uarray/vectorcall.h": "scipy_builtin/source/scipy/_lib/_uarray/vectorcall.h",
    "scipy/_lib/_uarray/small_dynamic_array.h": "scipy_builtin/source/scipy/_lib/_uarray/small_dynamic_array.h",
    "scipy/fft/_pocketfft/pypocketfft.cxx": "scipy_builtin/source/scipy/fft/_pocketfft/pypocketfft.cxx",
    "scipy/_lib/pocketfft/pocketfft_hdronly.h": "scipy_builtin/source/scipy/_lib/pocketfft/pocketfft_hdronly.h",
}

SCIPY_ARRAY_API_COMPAT_MAPPING = {
    "scipy/_lib/array_api_compat/array_api_compat": "Lib/scipy/_lib/array_api_compat",
}

SCIPY_ARRAY_API_EXTRA_MAPPING = {
    "scipy/_lib/array_api_extra/src/array_api_extra": "Lib/scipy/_lib/array_api_extra",
}


def _project_configurations() -> str:
    return """  <ItemGroup Label="ProjectConfigurations">
    <ProjectConfiguration Include="Release|x64">
      <Configuration>Release</Configuration>
      <Platform>x64</Platform>
    </ProjectConfiguration>
  </ItemGroup>
"""


def _compile_items(source_files: list[str]) -> str:
    items: list[str] = []
    for path in source_files:
        windows_path = path.replace("/", "\\")
        items.append(f'    <ClCompile Include="..\\{windows_path}" />')
    return "\n".join(items)


def _render_static_library_project(
    *,
    project_guid: str,
    root_namespace: str,
    target_name: str,
    source_files: list[str],
    include_dirs: list[str],
    definitions: list[str] | None = None,
    language_standard: str | None = None,
    additional_options: list[str] | None = None,
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
    additional_options_text = " ".join([*(additional_options or []), "%(AdditionalOptions)"])
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
      <AdditionalOptions>{additional_options_text}</AdditionalOptions>
      <RuntimeLibrary Condition="'$(Configuration)|$(Platform)'=='Release|x64'">MultiThreaded</RuntimeLibrary>
    </ClCompile>
  </ItemDefinitionGroup>
  <ItemGroup>
{_compile_items(source_files)}
  </ItemGroup>
  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.targets" />
</Project>
"""


def scipy_source_root(context) -> Path:
    return source_path(context, "scipy_builtin/source")


def scipy_generated_root(context) -> Path:
    return source_path(context, "scipy_builtin/generated")


def scipy_package_root(context) -> Path:
    return scipy_source_root(context) / "scipy"


def scipy_lib_source_root(context) -> Path:
    return scipy_package_root(context) / "_lib"


def scipy_cython_cache_dir(context) -> Path:
    version_tag = f"py{sys.version_info.major}{sys.version_info.minor}"
    return context.download_cache_root / "build-tools" / "scipy-cython" / version_tag


def scipy_cython_target_dir(context) -> Path:
    return scipy_cython_cache_dir(context) / "site"


def scipy_cython_wrapper_path(context) -> Path:
    return source_path(context, "scipy_builtin/tools/cython.cmd")


def _render_scipy_cython_wrapper(target_dir: Path) -> str:
    host_python = Path(sys.executable)
    return (
        "@echo off\n"
        "setlocal\n"
        "set \"PYTHONNOUSERSITE=1\"\n"
        f"set \"PYTHONPATH={target_dir}\"\n"
        f"\"{host_python}\" -S -m cython %*\n"
    )


def _ensure_scipy_cython(context) -> Path:
    target_dir = scipy_cython_target_dir(context)
    package_dir = target_dir / "Cython"
    if not package_dir.exists():
        cache_dir = scipy_cython_cache_dir(context)
        cache_dir.mkdir(parents=True, exist_ok=True)
        if target_dir.exists():
            shutil.rmtree(target_dir)
        context.log(f"installing local scipy build dependency {SCIPY_CYTHON_REQUIREMENT}")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-compile",
                "--target",
                str(target_dir),
                SCIPY_CYTHON_REQUIREMENT,
            ],
            check=True,
            timeout=60 * 10,
        )
    wrapper_path = scipy_cython_wrapper_path(context)
    wrapper_path.parent.mkdir(parents=True, exist_ok=True)
    wrapper_path.write_text(
        _render_scipy_cython_wrapper(target_dir),
        encoding="utf-8",
        newline="\n",
    )
    return wrapper_path


def _write_scipy_config_module(context) -> None:
    write_source_text(
        context,
        "Lib/scipy/__config__.py",
        """# This file is generated by StaticPython's SciPy phase-1 integration.
from enum import Enum

__all__ = ["show"]
_built_with_meson = False


class DisplayModes(Enum):
    stdout = "stdout"
    dicts = "dicts"


CONFIG = {
    "Compilers": {},
    "Machine Information": {},
    "Build Dependencies": {
        "pybind11": {
            "name": "pybind11",
            "version": "staticpython",
            "detection method": "staticpython",
            "include directory": "pybind11_builtin/include",
        },
    },
    "Python Information": {
        "path": "staticpython",
        "version": "staticpython",
    },
}


def show(mode=DisplayModes.stdout.value):
    if mode == DisplayModes.stdout.value:
        import json
        print(json.dumps(CONFIG, indent=2))
        return None
    if mode == DisplayModes.dicts.value:
        return CONFIG
    raise AttributeError(
        f"Invalid `mode`, use one of: {', '.join([e.value for e in DisplayModes])}"
    )
""",
    )


def _write_scipy_tls_header(context) -> None:
    write_source_text(
        context,
        "scipy_builtin/generated/scipy_config.h",
        """#define HAVE___DECLSPEC_THREAD_ 1

#ifdef __cplusplus
    #define SCIPY_TLS thread_local
#elif defined(HAVE_THREAD_LOCAL)
    #define SCIPY_TLS thread_local
#elif defined(HAVE__THREAD_LOCAL)
    #define SCIPY_TLS _Thread_local
#elif defined(HAVE___THREAD)
    #define SCIPY_TLS __thread
#elif defined(HAVE___DECLSPEC_THREAD_)
    #define SCIPY_TLS __declspec(thread)
#else
    #define SCIPY_TLS
#endif
""",
    )


def _patch_scipy_top_level(context) -> None:
    def patch(text: str) -> str:
        new = "submodules = [\n" + "".join(
            f"    '{name}',\n" for name in SCIPY_SUPPORTED_SUBMODULES
        ) + "]\n"
        if new in text:
            return text
        start = text.find("submodules = [")
        end = text.find("__all__ = submodules + [", start)
        if start < 0 or end < 0:
            raise RuntimeError("expected scipy.__init__ submodule list not found")
        return text[:start] + new + "\n" + text[end:]

    transform_source_text(context, "Lib/scipy/__init__.py", patch)


def _write_scipy_io_init(context) -> None:
    write_source_text(
        context,
        "Lib/scipy/io/__init__.py",
        '''"""Minimal scipy.io support for StaticPython's SciPy build."""

from . import arff
from . import wavfile
from .arff import loadarff
from .wavfile import WavFileWarning, read, write

__all__ = [
    "arff",
    "loadarff",
    "wavfile",
    "WavFileWarning",
    "read",
    "write",
]

from scipy._lib._testutils import PytestTester

test = PytestTester(__name__)
del PytestTester
''',
    )


def _write_scipy_special_init(context) -> None:
    write_source_text(
        context,
        "Lib/scipy/special/__init__.py",
        '''"""Minimal scipy.special support for StaticPython's SciPy build."""

from __future__ import annotations

import math
import numpy as np

__all__ = [
    "comb",
    "erf",
    "erfc",
    "expit",
    "factorial",
    "gammaln",
    "i0",
    "logit",
    "logsumexp",
    "ndtr",
    "roots_legendre",
    "xlogy",
]


def _vectorize_scalar(func, dtype=np.float64):
    def wrapped(x):
        array = np.asarray(x)
        if array.ndim == 0:
            return func(array.item())
        vectorized = np.vectorize(func, otypes=[dtype])
        return vectorized(array)

    return wrapped


def i0(x):
    return np.i0(x)


gammaln = _vectorize_scalar(lambda value: math.lgamma(float(value)))
erf = _vectorize_scalar(lambda value: math.erf(float(value)))
erfc = _vectorize_scalar(lambda value: math.erfc(float(value)))


def roots_legendre(n, mu=False):
    nodes, weights = np.polynomial.legendre.leggauss(int(n))
    if mu:
        return nodes, weights, float(np.sum(weights))
    return nodes, weights


def logsumexp(a, axis=None, b=None, keepdims=False, return_sign=False):
    values = np.asarray(a)
    if values.size == 0:
        result = np.sum(values, axis=axis, keepdims=keepdims)
        if return_sign:
            return result, np.ones_like(result)
        return result
    if b is not None:
        values = values + np.log(np.asarray(b))
    max_value = np.max(values, axis=axis, keepdims=True)
    shifted = np.exp(values - max_value)
    summed = np.sum(shifted, axis=axis, keepdims=True)
    result = np.log(summed) + max_value
    if not keepdims:
        result = np.squeeze(result, axis=axis)
    if return_sign:
        sign = np.ones_like(result)
        return result, sign
    return result


def comb(N, k, exact=False, repetition=False):
    n = np.asarray(N)
    r = np.asarray(k)
    if repetition:
        n = n + r - 1
    if exact:
        vectorized = np.vectorize(lambda nv, kv: math.comb(int(nv), int(kv)), otypes=[object])
        return vectorized(n, r)
    numerator = gammaln(n + 1)
    denominator = gammaln(r + 1) + gammaln(n - r + 1)
    return np.exp(numerator - denominator)


def factorial(n, exact=False):
    values = np.asarray(n)
    if exact:
        if values.ndim == 0:
            return math.factorial(int(values.item()))
        vectorized = np.vectorize(lambda value: math.factorial(int(value)), otypes=[object])
        return vectorized(values)
    return np.exp(gammaln(values + 1))


def expit(x):
    values = np.asarray(x, dtype=np.float64)
    return 1.0 / (1.0 + np.exp(-values))


def logit(p):
    values = np.asarray(p, dtype=np.float64)
    return np.log(values / (1.0 - values))


def xlogy(x, y):
    x_values = np.asarray(x)
    y_values = np.asarray(y)
    return np.where(x_values == 0, 0.0, x_values * np.log(y_values))


def ndtr(x):
    values = np.asarray(x, dtype=np.float64)
    return 0.5 * (1.0 + erf(values / math.sqrt(2.0)))
''',
    )


def _write_scipy_io_arff_alias(context) -> None:
    write_source_text(
        context,
        "Lib/scipy/io/arff/arffread.py",
        '''"""Compatibility alias for scipy.io.arff readers."""

from ._arffread import *  # noqa: F401,F403
''',
    )


def _write_scipy_linalg_init(context) -> None:
    write_source_text(
        context,
        "Lib/scipy/linalg/__init__.py",
        '''"""Minimal scipy.linalg support for StaticPython's SciPy build."""

from __future__ import annotations

import numpy as np
from numpy.linalg import LinAlgError

from ._special_matrices import (
    block_diag,
    companion,
    convolution_matrix,
    circulant,
    dft,
    fiedler,
    fiedler_companion,
    hadamard,
    hankel,
    helmert,
    hilbert,
    invhilbert,
    invpascal,
    leslie,
    pascal,
    toeplitz,
)

__all__ = [
    "LinAlgError",
    "LinAlgWarning",
    "block_diag",
    "cholesky",
    "companion",
    "convolution_matrix",
    "circulant",
    "det",
    "dft",
    "eig",
    "eigh",
    "eigh_tridiagonal",
    "eigvals",
    "eigvalsh",
    "fiedler",
    "fiedler_companion",
    "hadamard",
    "hankel",
    "helmert",
    "hilbert",
    "inv",
    "invhilbert",
    "invpascal",
    "ishermitian",
    "issymmetric",
    "leslie",
    "lstsq",
    "norm",
    "pascal",
    "pinv",
    "qr",
    "solve",
    "solve_triangular",
    "svd",
    "svdvals",
    "toeplitz",
]


class LinAlgWarning(RuntimeWarning):
    pass


def _asarray_chkfinite(a):
    array = np.asarray(a)
    if not np.all(np.isfinite(array)):
        raise ValueError("array must not contain infs or NaNs")
    return array


def norm(a, ord=None, axis=None, keepdims=False, check_finite=True):
    array = _asarray_chkfinite(a) if check_finite else np.asarray(a)
    return np.linalg.norm(array, ord=ord, axis=axis, keepdims=keepdims)


def det(a, overwrite_a=False, check_finite=True):
    array = _asarray_chkfinite(a) if check_finite else np.asarray(a)
    return np.linalg.det(array)


def inv(a, overwrite_a=False, check_finite=True):
    array = _asarray_chkfinite(a) if check_finite else np.asarray(a)
    return np.linalg.inv(array)


def solve(a, b, overwrite_a=False, overwrite_b=False, check_finite=True, assume_a=None, transposed=False):
    matrix = _asarray_chkfinite(a) if check_finite else np.asarray(a)
    rhs = _asarray_chkfinite(b) if check_finite else np.asarray(b)
    if transposed:
        matrix = np.swapaxes(matrix, -1, -2)
    return np.linalg.solve(matrix, rhs)


def solve_triangular(a, b, trans=0, lower=False, unit_diagonal=False, overwrite_b=False, check_finite=True):
    matrix = _asarray_chkfinite(a) if check_finite else np.asarray(a)
    rhs = _asarray_chkfinite(b) if check_finite else np.asarray(b)
    tri = np.tril(matrix) if lower else np.triu(matrix)
    if unit_diagonal:
        tri = tri.copy()
        diag = np.diag_indices_from(tri)
        tri[diag] = 1
    if trans in ("T", "t", 1):
        tri = np.swapaxes(tri, -1, -2)
    elif trans in ("C", "c", 2):
        tri = np.swapaxes(np.conjugate(tri), -1, -2)
    return np.linalg.solve(tri, rhs)


def eig(a, left=False, right=True, overwrite_a=False, check_finite=True):
    if left:
        raise NotImplementedError("minimal scipy.linalg build does not support left eigenvectors")
    array = _asarray_chkfinite(a) if check_finite else np.asarray(a)
    values, vectors = np.linalg.eig(array)
    if right:
        return values, vectors
    return values


def eigvals(a, overwrite_a=False, check_finite=True):
    array = _asarray_chkfinite(a) if check_finite else np.asarray(a)
    return np.linalg.eigvals(array)


def eigh(a, b=None, lower=True, eigvals_only=False, overwrite_a=False, overwrite_b=False, check_finite=True):
    if b is not None:
        raise NotImplementedError("minimal scipy.linalg build only supports standard Hermitian eigenproblems")
    array = _asarray_chkfinite(a) if check_finite else np.asarray(a)
    values, vectors = np.linalg.eigh(array)
    if eigvals_only:
        return values
    return values, vectors


def eigvalsh(a, b=None, lower=True, overwrite_a=False, overwrite_b=False, check_finite=True):
    return eigh(a, b=b, lower=lower, eigvals_only=True, overwrite_a=overwrite_a, overwrite_b=overwrite_b, check_finite=check_finite)


def eigh_tridiagonal(d, e, eigvals_only=False, select="a", select_range=None, check_finite=True, tol=0.0, lapack_driver="auto"):
    diagonal = _asarray_chkfinite(d) if check_finite else np.asarray(d)
    off_diagonal = _asarray_chkfinite(e) if check_finite else np.asarray(e)
    matrix = np.diag(diagonal) + np.diag(off_diagonal, 1) + np.diag(np.conjugate(off_diagonal), -1)
    values, vectors = np.linalg.eigh(matrix)
    if select == "i" and select_range is not None:
        lo, hi = select_range
        values = values[lo : hi + 1]
        vectors = vectors[:, lo : hi + 1]
    elif select not in ("a", "i"):
        raise NotImplementedError("minimal scipy.linalg build supports only select='a' and select='i'")
    if eigvals_only:
        return values
    return values, vectors


def svd(a, full_matrices=True, compute_uv=True, overwrite_a=False, check_finite=True, lapack_driver="gesdd"):
    array = _asarray_chkfinite(a) if check_finite else np.asarray(a)
    return np.linalg.svd(array, full_matrices=full_matrices, compute_uv=compute_uv)


def svdvals(a, overwrite_a=False, check_finite=True):
    array = _asarray_chkfinite(a) if check_finite else np.asarray(a)
    return np.linalg.svd(array, compute_uv=False)


def qr(a, overwrite_a=False, lwork=None, mode="full", pivoting=False, check_finite=True):
    if pivoting:
        raise NotImplementedError("minimal scipy.linalg build does not support QR pivoting")
    array = _asarray_chkfinite(a) if check_finite else np.asarray(a)
    return np.linalg.qr(array, mode=mode)


def cholesky(a, lower=False, overwrite_a=False, check_finite=True):
    array = _asarray_chkfinite(a) if check_finite else np.asarray(a)
    result = np.linalg.cholesky(array)
    return result if lower else np.swapaxes(np.conjugate(result), -1, -2)


def lstsq(a, b, cond=None, overwrite_a=False, overwrite_b=False, check_finite=True, lapack_driver=None):
    array = _asarray_chkfinite(a) if check_finite else np.asarray(a)
    rhs = _asarray_chkfinite(b) if check_finite else np.asarray(b)
    return np.linalg.lstsq(array, rhs, rcond=cond)


def pinv(a, atol=None, rtol=None, return_rank=False, check_finite=True):
    array = _asarray_chkfinite(a) if check_finite else np.asarray(a)
    singular_values = np.linalg.svd(array, compute_uv=False)
    if singular_values.size == 0:
        rank = 0
    else:
        relative = np.finfo(singular_values.dtype).eps * max(array.shape) if rtol is None else rtol
        absolute = 0.0 if atol is None else atol
        cutoff = absolute + relative * singular_values.max()
        rank = int(np.sum(singular_values > cutoff))
    pseudo_inverse = np.linalg.pinv(array, rcond=0.0 if rtol is None else rtol)
    if return_rank:
        return pseudo_inverse, rank
    return pseudo_inverse


def issymmetric(a, rtol=1e-10, atol=1e-12):
    array = np.asarray(a)
    return array.ndim == 2 and array.shape[0] == array.shape[1] and np.allclose(array, array.T, rtol=rtol, atol=atol)


def ishermitian(a, rtol=1e-10, atol=1e-12):
    array = np.asarray(a)
    return array.ndim == 2 and array.shape[0] == array.shape[1] and np.allclose(array, np.conjugate(array.T), rtol=rtol, atol=atol)


from scipy._lib._testutils import PytestTester

test = PytestTester(__name__)
del PytestTester
''',
    )


def _write_scipy_linalg_special_matrices_alias(context) -> None:
    write_source_text(
        context,
        "Lib/scipy/linalg/special_matrices.py",
        '''"""Compatibility alias for scipy.linalg special matrix helpers."""

from ._special_matrices import *  # noqa: F401,F403
''',
    )


def _write_scipy_signal_windows_module(context) -> None:
    write_source_text(
        context,
        "Lib/scipy/signal/windows/_windows.py",
        '''"""Minimal scipy.signal.windows support for StaticPython's SciPy build."""

from __future__ import annotations

import numpy as np

__all__ = [
    "bartlett",
    "blackman",
    "boxcar",
    "cosine",
    "gaussian",
    "general_cosine",
    "general_gaussian",
    "general_hamming",
    "get_window",
    "hamming",
    "hann",
    "kaiser",
    "triang",
    "tukey",
]


def _validate_length(M):
    if int(M) != M or M < 0:
        raise ValueError("Window length M must be a non-negative integer")
    return int(M)


def _extend(M, sym):
    if sym:
        return M, False
    return M + 1, True


def _truncate(values, needs_truncation):
    return values[:-1] if needs_truncation else values


def boxcar(M, sym=True):
    M = _validate_length(M)
    M, needs_truncation = _extend(M, sym)
    values = np.ones(M, dtype=np.float64)
    return _truncate(values, needs_truncation)


def triang(M, sym=True):
    M = _validate_length(M)
    if M <= 1:
        return np.ones(M, dtype=np.float64)
    M, needs_truncation = _extend(M, sym)
    n = np.arange(M, dtype=np.float64)
    if M % 2 == 0:
        values = 1.0 - np.abs((n - (M - 1.0) / 2.0) / (M / 2.0))
    else:
        values = 1.0 - np.abs((n - (M - 1.0) / 2.0) / ((M + 1.0) / 2.0))
    return _truncate(values, needs_truncation)


def bartlett(M, sym=True):
    M = _validate_length(M)
    M, needs_truncation = _extend(M, sym)
    return _truncate(np.bartlett(M), needs_truncation)


def general_cosine(M, a, sym=True):
    M = _validate_length(M)
    if M <= 1:
        return np.ones(M, dtype=np.float64)
    M, needs_truncation = _extend(M, sym)
    coefficients = np.asarray(a, dtype=np.float64)
    x = np.linspace(-np.pi, np.pi, M, dtype=np.float64)
    values = np.zeros(M, dtype=np.float64)
    for index, coefficient in enumerate(coefficients):
        values += coefficient * np.cos(index * x)
    return _truncate(values, needs_truncation)


def general_hamming(M, alpha, sym=True):
    return general_cosine(M, [alpha, 1.0 - alpha], sym=sym)


def hann(M, sym=True):
    M = _validate_length(M)
    M, needs_truncation = _extend(M, sym)
    return _truncate(np.hanning(M), needs_truncation)


def hamming(M, sym=True):
    M = _validate_length(M)
    M, needs_truncation = _extend(M, sym)
    return _truncate(np.hamming(M), needs_truncation)


def blackman(M, sym=True):
    M = _validate_length(M)
    M, needs_truncation = _extend(M, sym)
    return _truncate(np.blackman(M), needs_truncation)


def kaiser(M, beta, sym=True):
    M = _validate_length(M)
    M, needs_truncation = _extend(M, sym)
    return _truncate(np.kaiser(M, beta), needs_truncation)


def gaussian(M, std, sym=True):
    M = _validate_length(M)
    if M <= 1:
        return np.ones(M, dtype=np.float64)
    M, needs_truncation = _extend(M, sym)
    n = np.arange(0, M, dtype=np.float64) - (M - 1.0) / 2.0
    values = np.exp(-(n ** 2) / (2.0 * std * std))
    return _truncate(values, needs_truncation)


def general_gaussian(M, p, sig, sym=True):
    M = _validate_length(M)
    if M <= 1:
        return np.ones(M, dtype=np.float64)
    M, needs_truncation = _extend(M, sym)
    n = np.arange(0, M, dtype=np.float64) - (M - 1.0) / 2.0
    values = np.exp(-0.5 * np.abs(n / sig) ** (2.0 * p))
    return _truncate(values, needs_truncation)


def cosine(M, sym=True):
    M = _validate_length(M)
    if M <= 1:
        return np.ones(M, dtype=np.float64)
    M, needs_truncation = _extend(M, sym)
    n = np.arange(M, dtype=np.float64)
    values = np.sin(np.pi * (n + 0.5) / M)
    return _truncate(values, needs_truncation)


def tukey(M, alpha=0.5, sym=True):
    M = _validate_length(M)
    if M <= 1:
        return np.ones(M, dtype=np.float64)
    if alpha <= 0:
        return boxcar(M, sym=sym)
    if alpha >= 1.0:
        return hann(M, sym=sym)
    M, needs_truncation = _extend(M, sym)
    n = np.arange(M, dtype=np.float64)
    width = alpha * (M - 1) / 2.0
    values = np.ones(M, dtype=np.float64)
    leading = n < width
    trailing = n >= (M - 1) * (1 - alpha / 2.0)
    values[leading] = 0.5 * (1 + np.cos(np.pi * (2 * n[leading] / (alpha * (M - 1)) - 1)))
    values[trailing] = 0.5 * (1 + np.cos(np.pi * (2 * n[trailing] / (alpha * (M - 1)) - 2 / alpha + 1)))
    return _truncate(values, needs_truncation)


def get_window(window, Nx, fftbins=True):
    sym = not fftbins
    if isinstance(window, tuple):
        name = window[0]
        params = window[1:]
    else:
        name = window
        params = ()
    if isinstance(name, (int, float)):
        return kaiser(Nx, float(name), sym=sym)
    normalized = str(name).lower()
    if normalized in {"boxcar", "ones", "rect", "rectangular"}:
        return boxcar(Nx, sym=sym)
    if normalized in {"triang", "triangle"}:
        return triang(Nx, sym=sym)
    if normalized in {"bartlett", "bart"}:
        return bartlett(Nx, sym=sym)
    if normalized in {"hann", "hanning"}:
        return hann(Nx, sym=sym)
    if normalized == "hamming":
        return hamming(Nx, sym=sym)
    if normalized == "blackman":
        return blackman(Nx, sym=sym)
    if normalized == "kaiser":
        beta = 14.0 if not params else params[0]
        return kaiser(Nx, beta, sym=sym)
    if normalized == "gaussian":
        if not params:
            raise ValueError("gaussian window requires a standard deviation")
        return gaussian(Nx, params[0], sym=sym)
    if normalized == "general_gaussian":
        if len(params) != 2:
            raise ValueError("general_gaussian window requires p and sig parameters")
        return general_gaussian(Nx, params[0], params[1], sym=sym)
    if normalized == "general_cosine":
        if len(params) != 1:
            raise ValueError("general_cosine window requires a coefficient sequence")
        return general_cosine(Nx, params[0], sym=sym)
    if normalized == "general_hamming":
        alpha = 0.54 if not params else params[0]
        return general_hamming(Nx, alpha, sym=sym)
    if normalized == "cosine":
        return cosine(Nx, sym=sym)
    if normalized == "tukey":
        alpha = 0.5 if not params else params[0]
        return tukey(Nx, alpha=alpha, sym=sym)
    raise ValueError(f"unsupported window specification: {window!r}")
''',
    )


def _write_scipy_signal_windows_init(context) -> None:
    write_source_text(
        context,
        "Lib/scipy/signal/windows/__init__.py",
        '''"""Minimal scipy.signal.windows support for StaticPython's SciPy build."""

from ._windows import *  # noqa: F401,F403
''',
    )


def _write_scipy_signal_windows_alias(context) -> None:
    write_source_text(
        context,
        "Lib/scipy/signal/windows/windows.py",
        '''"""Compatibility alias for scipy.signal.windows."""

from ._windows import *  # noqa: F401,F403
''',
    )


def _write_scipy_signal_init(context) -> None:
    write_source_text(
        context,
        "Lib/scipy/signal/__init__.py",
        '''"""Minimal scipy.signal support for StaticPython's SciPy build."""

from . import windows
from ._czt import CZT, ZoomFFT, czt, czt_points, zoom_fft
from ._waveforms import chirp, gausspulse, sawtooth, square, sweep_poly, unit_impulse
from .windows import get_window

__all__ = [
    "CZT",
    "ZoomFFT",
    "chirp",
    "czt",
    "czt_points",
    "gausspulse",
    "get_window",
    "sawtooth",
    "square",
    "sweep_poly",
    "unit_impulse",
    "windows",
    "zoom_fft",
]

from scipy._lib._testutils import PytestTester

test = PytestTester(__name__)
del PytestTester
''',
    )


def _write_scipy_signal_waveforms_alias(context) -> None:
    write_source_text(
        context,
        "Lib/scipy/signal/waveforms.py",
        '''"""Compatibility alias for scipy.signal waveform helpers."""

from ._waveforms import *  # noqa: F401,F403
''',
    )


def _write_scipy_optimize_init(context) -> None:
    template_path = Path(__file__).resolve().with_name("optimize_template.py")
    template = template_path.read_text(encoding="utf-8")
    write_source_text(context, "Lib/scipy/optimize/__init__.py", template)


def _write_scipy_interpolate_init(context) -> None:
    template_path = Path(__file__).resolve().with_name("interpolate_template.py")
    template = template_path.read_text(encoding="utf-8")
    write_source_text(context, "Lib/scipy/interpolate/__init__.py", template)


def _write_scipy_stats_init(context) -> None:
    template_path = Path(__file__).resolve().with_name("stats_template.py")
    template = template_path.read_text(encoding="utf-8")
    write_source_text(context, "Lib/scipy/stats/__init__.py", template)


def _write_scipy_sparse_init(context) -> None:
    template_path = Path(__file__).resolve().with_name("sparse_template.py")
    template = template_path.read_text(encoding="utf-8")
    write_source_text(context, "Lib/scipy/sparse/__init__.py", template)


def _write_scipy_sparse_linalg_init(context) -> None:
    template_path = Path(__file__).resolve().with_name("sparse_linalg_template.py")
    template = template_path.read_text(encoding="utf-8")
    write_source_text(context, "Lib/scipy/sparse/linalg/__init__.py", template)


def _write_scipy_spatial_init(context) -> None:
    template_path = Path(__file__).resolve().with_name("spatial_template.py")
    template = template_path.read_text(encoding="utf-8")
    write_source_text(context, "Lib/scipy/spatial/__init__.py", template)


def _write_scipy_spatial_distance_init(context) -> None:
    template_path = Path(__file__).resolve().with_name("spatial_distance_template.py")
    template = template_path.read_text(encoding="utf-8")
    write_source_text(context, "Lib/scipy/spatial/distance.py", template)


def _write_scipy_fftpack_init(context) -> None:
    write_source_text(
        context,
        "Lib/scipy/fftpack/__init__.py",
        '''"""Legacy FFT compatibility layer backed by scipy.fft."""

from ._basic import fft, fft2, fftn, ifft, ifft2, ifftn, irfft, rfft
from ._helper import fftfreq, fftshift, ifftshift, next_fast_len, rfftfreq
from ._realtransforms import dct, dctn, dst, dstn, idct, idctn, idst, idstn

__all__ = [
    "fft",
    "ifft",
    "fftn",
    "ifftn",
    "rfft",
    "irfft",
    "fft2",
    "ifft2",
    "fftfreq",
    "rfftfreq",
    "fftshift",
    "ifftshift",
    "next_fast_len",
    "dct",
    "idct",
    "dst",
    "idst",
    "dctn",
    "idctn",
    "dstn",
    "idstn",
]

from scipy._lib._testutils import PytestTester

test = PytestTester(__name__)
del PytestTester
''',
    )


def _write_scipy_integrate_init(context) -> None:
    write_source_text(
        context,
        "Lib/scipy/integrate/__init__.py",
        '''"""Sample-based numerical integration helpers for StaticPython's SciPy phase-1 build."""

from ._quadrature import (
    cumulative_simpson,
    cumulative_trapezoid,
    newton_cotes,
    romb,
    simpson,
    trapezoid,
)

__all__ = [
    "trapezoid",
    "cumulative_trapezoid",
    "simpson",
    "cumulative_simpson",
    "romb",
    "newton_cotes",
]

from scipy._lib._testutils import PytestTester

test = PytestTester(__name__)
del PytestTester
''',
    )


def _patch_integrate_quadrature_for_phase1(context) -> None:
    def patch(text: str) -> str:
        if "roots_legendre = None" in text and "lgamma as gammaln" in text:
            return text
        old = """from scipy.special import roots_legendre
from scipy.special import gammaln, logsumexp
from scipy._lib._util import _rng_spawn
from scipy._lib._array_api import (_asarray, array_namespace, xp_result_type, xp_copy,
                                   xp_capabilities, xp_promote, xp_swapaxes, is_numpy)
import scipy._lib.array_api_extra as xpx
"""
        new = """try:
    from scipy.special import roots_legendre
except Exception:
    roots_legendre = None

try:
    from scipy.special import gammaln, logsumexp
except Exception:
    from math import lgamma as gammaln

    def logsumexp(*args, **kwargs):
        raise ImportError(
            "scipy.integrate phase-1 build does not include scipy.special-backed logsumexp support"
        )

from scipy._lib._util import _rng_spawn
from scipy._lib._array_api import (_asarray, array_namespace, xp_result_type, xp_copy,
                                   xp_capabilities, xp_promote, xp_swapaxes, is_numpy)
import scipy._lib.array_api_extra as xpx
"""
        if old not in text:
            raise RuntimeError("expected scipy.integrate._quadrature imports not found")
        text = text.replace(old, new, 1)
        old = """def _cached_roots_legendre(n):
    \"""
    Cache roots_legendre results to speed up calls of the fixed_quad
    function.
    \"""
    if n in _cached_roots_legendre.cache:
"""
        new = """def _cached_roots_legendre(n):
    \"""
    Cache roots_legendre results to speed up calls of the fixed_quad
    function.
    \"""
    if roots_legendre is None:
        raise ImportError(
            "scipy.integrate.fixed_quad requires scipy.special, which is not bundled in this phase-1 build"
        )
    if n in _cached_roots_legendre.cache:
"""
        if old not in text:
            raise RuntimeError("expected scipy.integrate._quadrature cache helper not found")
        return text.replace(old, new, 1)

    transform_source_text(context, "Lib/scipy/integrate/_quadrature.py", patch)


def _patch_fft_init_for_phase1(context) -> None:
    def patch(text: str) -> str:
        if "_fftlog_import_error = None" in text:
            return text
        old = """from ._basic import (
    fft, ifft, fft2, ifft2, fftn, ifftn,
    rfft, irfft, rfft2, irfft2, rfftn, irfftn,
    hfft, ihfft, hfft2, ihfft2, hfftn, ihfftn)
from ._realtransforms import dct, idct, dst, idst, dctn, idctn, dstn, idstn
from ._fftlog import fht, ifht, fhtoffset
from ._helper import (
    next_fast_len, prev_fast_len, fftfreq,
    rfftfreq, fftshift, ifftshift)
from ._backend import (set_backend, skip_backend, set_global_backend,
                       register_backend)
from ._pocketfft.helper import set_workers, get_workers
"""
        new = """from ._basic import (
    fft, ifft, fft2, ifft2, fftn, ifftn,
    rfft, irfft, rfft2, irfft2, rfftn, irfftn,
    hfft, ihfft, hfft2, ihfft2, hfftn, ihfftn)
from ._realtransforms import dct, idct, dst, idst, dctn, idctn, dstn, idstn
try:
    from ._fftlog import fht, ifht, fhtoffset
except Exception as exc:
    _fftlog_import_error = exc

    def _raise_fftlog_unavailable(*args, **kwargs):
        raise ImportError(
            "scipy.fft phase-1 build does not include fftlog support; scipy.special is not bundled yet"
        ) from _fftlog_import_error

    fht = _raise_fftlog_unavailable
    ifht = _raise_fftlog_unavailable
    fhtoffset = _raise_fftlog_unavailable
else:
    _fftlog_import_error = None
from ._helper import (
    next_fast_len, prev_fast_len, fftfreq,
    rfftfreq, fftshift, ifftshift)
from ._backend import (set_backend, skip_backend, set_global_backend,
                       register_backend)
from ._pocketfft.helper import set_workers, get_workers
"""
        if old not in text:
            raise RuntimeError("expected scipy.fft.__init__ imports not found")
        return text.replace(old, new, 1)

    transform_source_text(context, "Lib/scipy/fft/__init__.py", patch)


def _patch_fft_backend_for_phase1(context) -> None:
    def patch(text: str) -> str:
        if "_fftlog_backend = None" in text:
            return text
        old = """import scipy._lib.uarray as ua
from scipy._lib._array_api import xp_capabilities
from . import _basic_backend
from . import _realtransforms_backend
from . import _fftlog_backend
"""
        new = """import scipy._lib.uarray as ua
from scipy._lib._array_api import xp_capabilities
from . import _basic_backend
from . import _realtransforms_backend
try:
    from . import _fftlog_backend
except Exception:
    _fftlog_backend = None
"""
        if old not in text:
            raise RuntimeError("expected scipy.fft._backend imports not found")
        text = text.replace(old, new, 1)
        old_snippet = """        if fn is None:
            fn = getattr(_fftlog_backend, method.__name__, None)
"""
        new_snippet = """        if fn is None and _fftlog_backend is not None:
            fn = getattr(_fftlog_backend, method.__name__, None)
"""
        if old_snippet not in text:
            raise RuntimeError("expected scipy.fft._backend dispatch chain not found")
        return text.replace(old_snippet, new_snippet, 1)

    transform_source_text(context, "Lib/scipy/fft/_backend.py", patch)


def _render_scipy_ccallback_project() -> str:
    return _render_static_library_project(
        project_guid=SCIPY_CCALLBACK_PROJECT_GUID,
        root_namespace="scipy__lib__ccallback_c",
        target_name=SCIPY_CCALLBACK_MODULE,
        source_files=SCIPY_CCALLBACK_SOURCES,
        include_dirs=[
            r"..\scipy_builtin\generated",
            r"..\scipy_builtin\source\scipy\_lib",
            r"..\scipy_builtin\source\scipy\_lib\src",
        ],
        definitions=[
            "CYTHON_EXTERN_C=extern \"C\"",
        ],
        language_standard="stdcpp17",
        additional_options=["/bigobj", "/EHsc"],
    )


def _render_scipy_uarray_project() -> str:
    return _render_static_library_project(
        project_guid=SCIPY_UARRAY_PROJECT_GUID,
        root_namespace="scipy__lib__uarray__uarray",
        target_name=SCIPY_UARRAY_MODULE,
        source_files=SCIPY_UARRAY_SOURCES,
        include_dirs=[
            r"..\scipy_builtin\source\scipy\_lib\_uarray",
        ],
        language_standard="stdcpp17",
        additional_options=["/bigobj", "/EHsc"],
    )


def _render_scipy_pocketfft_project() -> str:
    return _render_static_library_project(
        project_guid=SCIPY_POCKETFFT_PROJECT_GUID,
        root_namespace="scipy_fft__pocketfft_pypocketfft",
        target_name=SCIPY_POCKETFFT_MODULE,
        source_files=SCIPY_POCKETFFT_SOURCES,
        include_dirs=[
            r"..\scipy_builtin\source\scipy\fft\_pocketfft",
            r"..\scipy_builtin\source\scipy\_lib\pocketfft",
            r"..\pybind11_builtin\include",
            r"..\Lib\numpy\_core\include",
            r"..\numpy_builtin\source\.build-staticpython-x64\numpy\_core",
        ],
        definitions=[
            "POCKETFFT_CACHE_SIZE=16",
        ],
        language_standard="stdcpp17",
        additional_options=["/bigobj", "/EHsc", "/Zc:preprocessor"],
    )


def _ensure_required_files(context, files: list[str]) -> None:
    missing = [path for path in files if not source_path(context, path).exists()]
    if missing:
        raise RuntimeError("scipy phase-1 source files are missing: " + ", ".join(missing))


def _ensure_scipy_cython_package_layout(context) -> None:
    for package_dir in (scipy_package_root(context), scipy_lib_source_root(context)):
        package_dir.mkdir(parents=True, exist_ok=True)
        init_path = package_dir / "__init__.py"
        if not init_path.exists():
            init_path.write_text("", encoding="utf-8", newline="\n")
            context.log(f"updated {init_path.relative_to(context.source_root)}")


def prepare_scipy_project(context) -> None:
    if context.platform != "x64":
        raise RuntimeError(f"scipy builtin integration currently supports only x64, not {context.platform}")

    _ensure_required_files(
        context,
        [
            "Lib/numpy/_core/include/numpy/arrayobject.h",
            "pybind11_builtin/include/pybind11/pybind11.h",
            "scipy_builtin/source/scipy/_lib/_ccallback_c.pyx",
            "scipy_builtin/source/scipy/_lib/src/ccallback.h",
            "scipy_builtin/source/scipy/_lib/_uarray/_uarray_dispatch.cxx",
            "scipy_builtin/source/scipy/fft/_pocketfft/pypocketfft.cxx",
            "scipy_builtin/source/scipy/_lib/pocketfft/pocketfft_hdronly.h",
        ],
    )
    _write_scipy_config_module(context)
    _write_scipy_tls_header(context)
    _ensure_scipy_cython_package_layout(context)
    _patch_scipy_top_level(context)
    _write_scipy_special_init(context)
    _write_scipy_linalg_init(context)
    _write_scipy_linalg_special_matrices_alias(context)
    _write_scipy_io_init(context)
    _write_scipy_io_arff_alias(context)
    _write_scipy_signal_windows_module(context)
    _write_scipy_signal_windows_init(context)
    _write_scipy_signal_windows_alias(context)
    _write_scipy_signal_init(context)
    _write_scipy_signal_waveforms_alias(context)
    _write_scipy_optimize_init(context)
    _write_scipy_interpolate_init(context)
    _write_scipy_stats_init(context)
    _write_scipy_sparse_init(context)
    _write_scipy_sparse_linalg_init(context)
    _write_scipy_spatial_init(context)
    _write_scipy_spatial_distance_init(context)
    _write_scipy_fftpack_init(context)
    _write_scipy_integrate_init(context)
    _patch_fft_init_for_phase1(context)
    _patch_fft_backend_for_phase1(context)
    _patch_integrate_quadrature_for_phase1(context)
    write_source_text(context, "PCbuild/scipy._lib._ccallback_c.vcxproj", _render_scipy_ccallback_project())
    write_source_text(context, "PCbuild/scipy._lib._uarray._uarray.vcxproj", _render_scipy_uarray_project())
    write_source_text(context, "PCbuild/scipy.fft._pocketfft.pypocketfft.vcxproj", _render_scipy_pocketfft_project())


def prepare_scipy_generated_sources(context) -> None:
    cython_wrapper = _ensure_scipy_cython(context)
    generated_root = scipy_generated_root(context)
    generated_root.mkdir(parents=True, exist_ok=True)
    generated_c = generated_root / "_ccallback_c.c"
    scipy_source = scipy_source_root(context).resolve()
    scipy_lib_root = scipy_lib_source_root(context).resolve()
    command = [
        str(cython_wrapper),
        "--3str",
        "--module-name",
        SCIPY_CCALLBACK_MODULE,
        "-w",
        str(scipy_source),
        "-I",
        str(scipy_lib_root),
        "-o",
        str(generated_c),
        str((scipy_lib_root / "_ccallback_c.pyx").resolve()),
    ]
    display = subprocess.list2cmdline(command)
    context.log(f"RUN {display}")
    subprocess.run(command, cwd=str(context.source_root), check=True, timeout=60 * 10)
    if not generated_c.exists():
        raise RuntimeError("Cython did not generate scipy_builtin/generated/_ccallback_c.c")


LIBRARY_INTEGRATION = pypi_library(
    name="scipy",
    release_version=SCIPY_RELEASE_VERSION,
    source_archive_sha256_by_version={
        "1.17.1": "95d8e012d8cb8816c226aef832200b1d45109ed4464303e997c5b13122b297c0",
    },
    dependencies=[
        "numpy",
        "pybind11",
    ],
    dependency_constraints={
        "numpy": ">=1.26.4,<2.7",
    },
    source_mapping={
        **SCIPY_PYTHON_SOURCE_MAPPING,
        **SCIPY_NATIVE_SOURCE_MAPPING,
        **SCIPY_ARRAY_API_COMPAT_MAPPING,
        **SCIPY_ARRAY_API_EXTRA_MAPPING,
        "LICENSE.txt": "scipy_builtin/source/LICENSE.txt",
        "LICENSES_bundled.txt": "scipy_builtin/source/LICENSES_bundled.txt",
        "README.rst": "scipy_builtin/source/README.rst",
        "meson.build": "scipy_builtin/source/meson.build",
        "meson.options": "scipy_builtin/source/meson.options",
        "pyproject.toml": "scipy_builtin/source/pyproject.toml",
    },
    materialized_paths=[
        "Lib/scipy/__config__.py",
        "Lib/scipy/linalg/__init__.py",
        "Lib/scipy/linalg/special_matrices.py",
        "Lib/scipy/io/__init__.py",
        "Lib/scipy/io/arff/arffread.py",
        "Lib/scipy/interpolate/__init__.py",
        "Lib/scipy/optimize/__init__.py",
        "Lib/scipy/signal/__init__.py",
        "Lib/scipy/signal/waveforms.py",
        "Lib/scipy/signal/windows/__init__.py",
        "Lib/scipy/signal/windows/_windows.py",
        "Lib/scipy/signal/windows/windows.py",
        "Lib/scipy/sparse/__init__.py",
        "Lib/scipy/sparse/linalg/__init__.py",
        "Lib/scipy/spatial/__init__.py",
        "Lib/scipy/spatial/distance.py",
        "Lib/scipy/special/__init__.py",
        "Lib/scipy/stats/__init__.py",
        "Lib/scipy/fftpack/__init__.py",
        "Lib/scipy/integrate/__init__.py",
        "scipy_builtin/generated/scipy_config.h",
        "scipy_builtin/generated/_ccallback_c.c",
        "scipy_builtin/tools/cython.cmd",
        "PCbuild/scipy._lib._ccallback_c.vcxproj",
        "PCbuild/scipy._lib._uarray._uarray.vcxproj",
        "PCbuild/scipy.fft._pocketfft.pypocketfft.vcxproj",
    ],
    python_packages=["scipy"],
    top_level_import_names=["scipy"],
    license_expression="BSD-3-Clause AND MIT",
    license_sources=[
        {
            "filename": "LICENSE-array-api-compat.txt",
            "url": (
                "https://raw.githubusercontent.com/data-apis/array-api-compat/"
                "946ce4ad77968b94e93594c79653162426ec3224/LICENSE"
            ),
            "sha256": "4ffd978e3fa18d058d98c66771cfea7ed634aaf7023cf9612b8b55eee9a8f0fe",
        },
        {
            "filename": "LICENSE-array-api-extra.txt",
            "url": (
                "https://raw.githubusercontent.com/data-apis/array-api-extra/"
                "80240a296483c73f5e4b53218547b8225829c410/LICENSE"
            ),
            "sha256": "58494398fe147fdce76a68b2decd4c08ce3a1ea237b6d6785001c15f822c6ed6",
        },
    ],
    static_library_projects_release_x64=[
        "scipy._lib._ccallback_c.vcxproj",
        "scipy._lib._uarray._uarray.vcxproj",
        "scipy.fft._pocketfft.pypocketfft.vcxproj",
    ],
    native_static_projects=[
        {
            "project": "scipy._lib._ccallback_c.vcxproj",
            "guid": SCIPY_CCALLBACK_PROJECT_GUID,
        },
        {
            "project": "scipy._lib._uarray._uarray.vcxproj",
            "guid": SCIPY_UARRAY_PROJECT_GUID,
        },
        {
            "project": "scipy.fft._pocketfft.pypocketfft.vcxproj",
            "guid": SCIPY_POCKETFFT_PROJECT_GUID,
        },
    ],
    builtin_module_registrations=[
        {
            "name": SCIPY_CCALLBACK_MODULE,
            "pyinit": "PyInit__ccallback_c",
        },
        {
            "name": SCIPY_UARRAY_MODULE,
            "pyinit": "PyInit__uarray",
        },
        {
            "name": SCIPY_POCKETFFT_MODULE,
            "pyinit": "PyInit_pypocketfft",
        },
    ],
    python_link_dependencies_release_x64=[
        "scipy._lib._ccallback_c.lib",
        "scipy._lib._uarray._uarray.lib",
        "scipy.fft._pocketfft.pypocketfft.lib",
    ],
    python_link_wholearchive_release_x64=[
        "scipy._lib._ccallback_c.lib",
        "scipy._lib._uarray._uarray.lib",
        "scipy.fft._pocketfft.pypocketfft.lib",
    ],
    prepare_source_hooks=[prepare_scipy_project],
    post_patch_hooks=[prepare_scipy_generated_sources],
    smoke_tests=[
        {
            "name": "phase-1-numerical-behavior",
            "kind": "inline",
            "code": (
                "import numpy as np, scipy; "
                "from scipy import fft, optimize, sparse; "
                "from scipy.version import version as source_version; "
                "assert scipy.__version__ == source_version; "
                "values = np.array([1.0, 2.0, 3.0, 4.0]); "
                "assert np.allclose(fft.ifft(fft.fft(values)).real, values); "
                "root = optimize.root_scalar(lambda x: x*x-2.0, bracket=(0.0, 2.0)); "
                "assert root.converged and abs(root.root - np.sqrt(2.0)) < 1e-8; "
                "matrix = sparse.csr_matrix([[1.0, 0.0], [0.0, 2.0]]); "
                "assert np.array_equal(matrix @ np.array([3.0, 4.0]), np.array([3.0, 8.0]))"
            ),
        },
        {
            "name": "phase-1-extended-api-behavior",
            "kind": "script",
            "script": "scripts/scipy_profile_verify.py",
            "timeout": 120,
        },
    ],
)
