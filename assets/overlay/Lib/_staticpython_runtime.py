from __future__ import annotations

import base64
import builtins
import hashlib
import io
import os
import posixpath
import stat as _stat
import sys
import time
from dataclasses import dataclass


_INSTALLED = False
_RESOURCE_BYTES: dict[str, bytes] | None = None
_RESOURCE_CHILDREN: dict[str, tuple[str, ...]] | None = None
_RESOURCE_BASENAME_INDEX: dict[str, tuple[str, ...]] | None = None
_RESOURCE_DIR_BASENAME_INDEX: dict[str, tuple[str, ...]] | None = None
_START_TIME = int(time.time())


_ORIGINAL_OPEN = builtins.open
_ORIGINAL_IO_OPEN = io.open
_ORIGINAL_OS_STAT = os.stat
_ORIGINAL_OS_LISTDIR = os.listdir
_ORIGINAL_OS_SCANDIR = os.scandir
_ORIGINAL_OS_ACCESS = os.access
_ORIGINAL_EXISTS = os.path.exists
_ORIGINAL_ISFILE = os.path.isfile
_ORIGINAL_ISDIR = os.path.isdir
_ORIGINAL_SYS_EXCEPTHOOK = sys.excepthook
_ORIGINAL_PKGUTIL_GET_DATA = None
_ORIGINAL_IMPORTLIB_RESOURCES_FROM_PACKAGE = None
_INTERNAL_MODULE_PREFIXES = (
    "_staticpython_runtime",
    "genericpath",
    "importlib.",
    "io",
    "ntpath",
    "os",
    "pathlib",
    "posixpath",
    "stat",
)


def _resources_module():
    try:
        import _staticpython_runtime_resources as resources
    except Exception:
        return None
    return resources


def _load_resource_bytes() -> dict[str, bytes]:
    global _RESOURCE_BYTES
    if _RESOURCE_BYTES is not None:
        return _RESOURCE_BYTES

    resources = _resources_module()
    loaded: dict[str, bytes] = {}
    if resources is not None:
        for relative, encoded_chunks in resources.iter_resource_payloads():
            try:
                encoded = "".join(encoded_chunks).encode("ascii")
                loaded[_normalize_resource_key(relative)] = base64.b85decode(encoded)
            except Exception:
                continue
    _RESOURCE_BYTES = loaded
    return loaded


def _load_resource_children() -> dict[str, tuple[str, ...]]:
    global _RESOURCE_CHILDREN
    if _RESOURCE_CHILDREN is not None:
        return _RESOURCE_CHILDREN

    resources = _resources_module()
    children = getattr(resources, "RESOURCE_CHILDREN", {}) if resources is not None else {}
    loaded: dict[str, tuple[str, ...]] = {}
    for key, value in dict(children).items():
        loaded[_normalize_resource_key(key)] = tuple(value)
    _RESOURCE_CHILDREN = loaded
    return loaded


def _load_resource_basename_index() -> dict[str, tuple[str, ...]]:
    global _RESOURCE_BASENAME_INDEX
    if _RESOURCE_BASENAME_INDEX is not None:
        return _RESOURCE_BASENAME_INDEX

    resources = _resources_module()
    raw_index = getattr(resources, "RESOURCE_BASENAME_INDEX", {}) if resources is not None else {}
    loaded: dict[str, tuple[str, ...]] = {}
    for basename, paths in dict(raw_index).items():
        loaded[str(basename).lower()] = tuple(_normalize_resource_key(path) for path in paths)
    _RESOURCE_BASENAME_INDEX = loaded
    return loaded


def _load_resource_dir_basename_index() -> dict[str, tuple[str, ...]]:
    global _RESOURCE_DIR_BASENAME_INDEX
    if _RESOURCE_DIR_BASENAME_INDEX is not None:
        return _RESOURCE_DIR_BASENAME_INDEX

    resources = _resources_module()
    raw_index = getattr(resources, "RESOURCE_DIR_BASENAME_INDEX", {}) if resources is not None else {}
    loaded: dict[str, tuple[str, ...]] = {}
    for basename, paths in dict(raw_index).items():
        loaded[str(basename).lower()] = tuple(_normalize_resource_key(path) for path in paths)
    _RESOURCE_DIR_BASENAME_INDEX = loaded
    return loaded


def _normalize_resource_key(path: object) -> str:
    text = os.fspath(path)
    text = str(text).replace("\\", "/")
    if text.startswith("staticpython-resource://"):
        text = text[len("staticpython-resource://") :]
        package, _, rest = text.partition("/")
        if package and rest:
            return f"Lib/{package}/{rest}".strip("/")
    while "//" in text:
        text = text.replace("//", "/")
    return posixpath.normpath(text).strip("/")


def _is_probably_absolute(path: str) -> bool:
    path = path.replace("\\", "/")
    return path.startswith("/") or (len(path) >= 3 and path[1] == ":" and path[2] == "/")


def _module_key_from_file(module_file: object) -> str | None:
    if not module_file:
        return None
    normalized = _normalize_resource_key(module_file)
    lowered = normalized.lower()
    for marker in ("/lib/", "/share/", "/etc/"):
        index = lowered.rfind(marker)
        if index >= 0:
            return normalized[index + 1 :]
    for marker in ("lib/", "share/", "etc/"):
        index = lowered.find(marker)
        if index >= 0:
            return normalized[index:]
    return None


def _package_resource_bases(package_name: str | None, module_name: str | None) -> tuple[str, ...]:
    candidates: list[str] = []
    for raw_name in (package_name, module_name):
        if not raw_name:
            continue
        parts = [part for part in str(raw_name).split(".") if part]
        while parts:
            base = "Lib/" + "/".join(parts)
            if base not in candidates:
                candidates.append(base)
            parts.pop()
    return tuple(candidates)


def _caller_relative_candidates(path: object) -> tuple[str, ...]:
    try:
        raw_path = os.fspath(path)
    except TypeError:
        return ()
    if isinstance(raw_path, bytes):
        try:
            raw_path = os.fsdecode(raw_path)
        except Exception:
            return ()
    raw_text = str(raw_path).replace("\\", "/")
    if not raw_text or _is_probably_absolute(raw_text) or raw_text.startswith("staticpython-resource://"):
        return ()

    candidates: list[str] = []
    frame = sys._getframe(2)
    while frame is not None:
        globals_ = frame.f_globals
        module_name = str(globals_.get("__name__", ""))
        if module_name and not module_name.startswith(_INTERNAL_MODULE_PREFIXES):
            module_key = _module_key_from_file(globals_.get("__file__"))
            if module_key:
                base = posixpath.dirname(module_key)
                candidates.append(_normalize_resource_key(posixpath.join(base, raw_text)))

            package_name = globals_.get("__package__")
            for base in _package_resource_bases(
                str(package_name) if package_name else None,
                module_name,
            ):
                candidates.append(_normalize_resource_key(posixpath.join(base, raw_text)))
        frame = frame.f_back

    deduped: list[str] = []
    for candidate in candidates:
        if candidate and candidate != "." and candidate not in deduped:
            deduped.append(candidate)
    return tuple(deduped)


def _suffix_resource_candidates(normalized: str, index: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    basename = normalized.rsplit("/", 1)[-1].lower()
    if not basename:
        return ()
    lowered_normalized = normalized.lower()
    normalized_parts = lowered_normalized.split("/")
    matches: list[tuple[int, int, str]] = []
    for key in index.get(basename, ()):
        lowered_key = key.lower()
        key_parts = lowered_key.split("/")
        shared = 0
        while shared < min(len(normalized_parts), len(key_parts)):
            if normalized_parts[-1 - shared] != key_parts[-1 - shared]:
                break
            shared += 1
        if shared:
            matches.append((-shared, len(normalized) - len(key), key))
    matches.sort()
    if len(matches) > 1 and matches[0][0] == matches[1][0]:
        return ()
    deduped: list[str] = []
    for _, _, key in matches:
        if key not in deduped:
            deduped.append(key)
    return tuple(deduped)


def _candidate_resource_keys(path: object) -> tuple[str, ...]:
    try:
        text = os.fspath(path)
    except TypeError:
        return ()
    if isinstance(text, bytes):
        try:
            text = os.fsdecode(text)
        except Exception:
            return ()

    normalized = _normalize_resource_key(text)
    candidates = [normalized]
    candidates.extend(_caller_relative_candidates(path))
    lowered = normalized.lower()
    for marker in ("/lib/", "/share/", "/etc/"):
        index = lowered.rfind(marker)
        if index >= 0:
            candidates.append(normalized[index + 1 :])
    for marker in ("lib/", "share/", "etc/"):
        index = lowered.find(marker)
        if index >= 0:
            candidates.append(normalized[index:])
    candidates.extend(_suffix_resource_candidates(normalized, _load_resource_basename_index()))
    candidates.extend(_suffix_resource_candidates(normalized, _load_resource_dir_basename_index()))

    deduped: list[str] = []
    for candidate in candidates:
        candidate = _normalize_resource_key(candidate)
        if candidate and candidate not in deduped:
            deduped.append(candidate)
    return tuple(deduped)


def _resource_key(path: object) -> str | None:
    resources = _load_resource_bytes()
    children = _load_resource_children()
    for candidate in _candidate_resource_keys(path):
        if candidate in resources or candidate in children:
            return candidate
    return None


def _resource_data(path: object) -> bytes | None:
    resources = _load_resource_bytes()
    for candidate in _candidate_resource_keys(path):
        data = resources.get(candidate)
        if data is not None:
            return data
    return None


def _is_resource_dir(path: object) -> bool:
    key = _resource_key(path)
    return key is not None and key in _load_resource_children()


def _resource_stat(path: object, *, follow_symlinks: bool = True):
    key = _resource_key(path)
    if key is None:
        raise FileNotFoundError(os.fspath(path))
    data = _load_resource_bytes().get(key)
    if data is not None:
        mode = _stat.S_IFREG | 0o444
        size = len(data)
    elif key in _load_resource_children():
        mode = _stat.S_IFDIR | 0o555
        size = 0
    else:
        raise FileNotFoundError(os.fspath(path))
    inode = int.from_bytes(hashlib.blake2s(key.encode("utf-8"), digest_size=8).digest(), "little")
    inode &= (1 << 63) - 1
    return os.stat_result((mode, inode or 1, 0, 1, 0, 0, size, _START_TIME, _START_TIME, _START_TIME))


def _open_resource(path: object, mode: str = "r", buffering: int = -1, encoding=None, errors=None, newline=None):
    if any(flag in mode for flag in ("w", "a", "x", "+")):
        return None
    data = _resource_data(path)
    if data is None:
        return None
    if "b" in mode:
        handle = io.BytesIO(data)
    else:
        text_encoding = encoding or "utf-8"
        handle = io.StringIO(data.decode(text_encoding, errors or "strict"), newline=newline)
    try:
        handle.name = os.fspath(path)
        handle.mode = mode
    except Exception:
        pass
    return handle


def _staticpython_open(file, mode="r", buffering=-1, encoding=None, errors=None, newline=None, closefd=True, opener=None):
    handle = _open_resource(file, mode, buffering, encoding, errors, newline)
    if handle is not None:
        return handle
    return _ORIGINAL_OPEN(file, mode, buffering, encoding, errors, newline, closefd, opener)


def _staticpython_io_open(file, mode="r", buffering=-1, encoding=None, errors=None, newline=None, closefd=True, opener=None):
    handle = _open_resource(file, mode, buffering, encoding, errors, newline)
    if handle is not None:
        return handle
    return _ORIGINAL_IO_OPEN(file, mode, buffering, encoding, errors, newline, closefd, opener)


def _staticpython_stat(path, *args, dir_fd=None, follow_symlinks=True):
    if dir_fd is None:
        try:
            return _resource_stat(path, follow_symlinks=follow_symlinks)
        except FileNotFoundError:
            pass
    return _ORIGINAL_OS_STAT(path, *args, dir_fd=dir_fd, follow_symlinks=follow_symlinks)


def _staticpython_exists(path) -> bool:
    return _resource_key(path) is not None or _ORIGINAL_EXISTS(path)


def _staticpython_isfile(path) -> bool:
    return _resource_data(path) is not None or _ORIGINAL_ISFILE(path)


def _staticpython_isdir(path) -> bool:
    return _is_resource_dir(path) or _ORIGINAL_ISDIR(path)


def _staticpython_access(path, mode, *args, dir_fd=None, effective_ids=False, follow_symlinks=True):
    if _resource_key(path) is not None:
        if mode & os.W_OK:
            return False
        return True
    return _ORIGINAL_OS_ACCESS(
        path,
        mode,
        *args,
        dir_fd=dir_fd,
        effective_ids=effective_ids,
        follow_symlinks=follow_symlinks,
    )


def _merge_directory_children(path: object) -> list[str] | None:
    key = _resource_key(path)
    if key is None:
        return None
    children = set(_load_resource_children().get(key, ()))
    try:
        children.update(_ORIGINAL_OS_LISTDIR(path))
    except OSError:
        pass
    return sorted(children)


def _staticpython_listdir(path=None):
    if path is None:
        return _ORIGINAL_OS_LISTDIR(path)
    children = _merge_directory_children(path)
    if children is not None:
        return children
    return _ORIGINAL_OS_LISTDIR(path)


@dataclass
class _StaticPythonDirEntry:
    _root: object
    name: str

    @property
    def path(self):
        return os.path.join(os.fspath(self._root), self.name)

    def inode(self):
        return 0

    def __fspath__(self):
        return self.path

    def is_dir(self, *, follow_symlinks=True):
        return _staticpython_isdir(self.path)

    def is_file(self, *, follow_symlinks=True):
        return _staticpython_isfile(self.path)

    def is_symlink(self):
        return False

    def stat(self, *, follow_symlinks=True):
        return _staticpython_stat(self.path, follow_symlinks=follow_symlinks)


class _StaticPythonScandir:
    def __init__(self, path):
        self._path = path
        children = _merge_directory_children(path)
        if children is None:
            self._native = _ORIGINAL_OS_SCANDIR(path)
            self._iterator = None
        else:
            self._native = None
            self._iterator = iter(_StaticPythonDirEntry(path, name) for name in children)

    def __iter__(self):
        return self

    def __next__(self):
        if self._native is not None:
            return next(self._native)
        return next(self._iterator)

    def close(self):
        if self._native is not None:
            self._native.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


def _staticpython_scandir(path="."):
    return _StaticPythonScandir(path)


def _patch_importlib_resources() -> None:
    global _ORIGINAL_IMPORTLIB_RESOURCES_FROM_PACKAGE
    try:
        import importlib.resources.abc as abc
        import importlib.resources._common as common
    except Exception:
        return

    original_from_package = getattr(common, "from_package", None)
    if original_from_package is None or getattr(original_from_package, "_staticpython_wrapped", False):
        return
    _ORIGINAL_IMPORTLIB_RESOURCES_FROM_PACKAGE = original_from_package

    class _StaticPythonResourceReader:
        def __init__(self, package_name: str):
            self.package_name = package_name
            self.base = "Lib/" + package_name.replace(".", "/")

        def open_resource(self, resource):
            data = _resource_data(f"{self.base}/{resource}")
            if data is None:
                raise FileNotFoundError(resource)
            return io.BytesIO(data)

        def resource_path(self, resource):
            return f"staticpython-resource://{self.package_name}/{resource}"

        def is_resource(self, name):
            return _resource_data(f"{self.base}/{name}") is not None

        def contents(self):
            return list(_load_resource_children().get(self.base, ()))

        def files(self):
            return _StaticPythonTraversable(self.base, self.package_name, "")

    class _StaticPythonTraversable(abc.Traversable):
        def __init__(self, key: str, package_name: str | None = None, display_name: str | None = None):
            self.key = _normalize_resource_key(key)
            self.package_name = package_name
            self._display_name = display_name if display_name is not None else self.key.rsplit("/", 1)[-1]

        @property
        def name(self):
            return self._display_name

        def iterdir(self):
            for child in _load_resource_children().get(self.key, ()):
                yield _StaticPythonTraversable(
                    f"{self.key}/{child}",
                    self.package_name,
                    child,
                )

        def is_dir(self):
            return self.key in _load_resource_children()

        def is_file(self):
            return self.key in _load_resource_bytes()

        def joinpath(self, child, *descendants):
            key = self.key
            for part in (child, *descendants):
                key = f"{key}/{part}"
            return _StaticPythonTraversable(key, self.package_name)

        __truediv__ = joinpath

        def open(self, mode="r", *args, **kwargs):
            data = _load_resource_bytes().get(self.key)
            if data is None:
                raise FileNotFoundError(self.key)
            if "b" in mode:
                return io.BytesIO(data)
            encoding = kwargs.get("encoding") or (args[0] if args else None) or "utf-8"
            errors = kwargs.get("errors") or "strict"
            newline = kwargs.get("newline")
            return io.StringIO(data.decode(encoding, errors), newline=newline)

        def read_bytes(self):
            data = _load_resource_bytes().get(self.key)
            if data is None:
                raise FileNotFoundError(self.key)
            return data

        def read_text(self, encoding=None, errors="strict"):
            return self.read_bytes().decode(encoding or "utf-8", errors)

        def __repr__(self):
            return f"<staticpython resource {self.key!r}>"

    def _staticpython_from_package(package):
        package_name = getattr(package, "__spec__", None)
        package_name = getattr(package_name, "name", None) or getattr(package, "__name__", None)
        if package_name:
            base = "Lib/" + package_name.replace(".", "/")
            if base in _load_resource_children():
                return _StaticPythonResourceReader(package_name).files()
        return original_from_package(package)

    _staticpython_from_package._staticpython_wrapped = True
    common.from_package = _staticpython_from_package


def _patch_pkgutil() -> None:
    global _ORIGINAL_PKGUTIL_GET_DATA
    try:
        import pkgutil
    except Exception:
        return

    original_get_data = getattr(pkgutil, "get_data", None)
    if original_get_data is None or getattr(original_get_data, "_staticpython_wrapped", False):
        return
    _ORIGINAL_PKGUTIL_GET_DATA = original_get_data

    def _staticpython_get_data(package, resource):
        package_path = "Lib/" + str(package).replace(".", "/")
        data = _resource_data(f"{package_path}/{resource}")
        if data is not None:
            return data
        return original_get_data(package, resource)

    _staticpython_get_data._staticpython_wrapped = True
    pkgutil.get_data = _staticpython_get_data


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    if _resources_module() is None:
        return
    builtins.open = _staticpython_open
    io.open = _staticpython_io_open
    os.stat = _staticpython_stat
    os.listdir = _staticpython_listdir
    os.scandir = _staticpython_scandir
    os.access = _staticpython_access
    os.path.exists = _staticpython_exists
    os.path.isfile = _staticpython_isfile
    os.path.isdir = _staticpython_isdir
    _patch_importlib_resources()
    _patch_pkgutil()
    _INSTALLED = True


def uninstall() -> None:
    global _INSTALLED
    if not _INSTALLED:
        return
    builtins.open = _ORIGINAL_OPEN
    io.open = _ORIGINAL_IO_OPEN
    os.stat = _ORIGINAL_OS_STAT
    os.listdir = _ORIGINAL_OS_LISTDIR
    os.scandir = _ORIGINAL_OS_SCANDIR
    os.access = _ORIGINAL_OS_ACCESS
    os.path.exists = _ORIGINAL_EXISTS
    os.path.isfile = _ORIGINAL_ISFILE
    os.path.isdir = _ORIGINAL_ISDIR
    if _ORIGINAL_PKGUTIL_GET_DATA is not None:
        try:
            import pkgutil

            pkgutil.get_data = _ORIGINAL_PKGUTIL_GET_DATA
        except Exception:
            pass
    if _ORIGINAL_IMPORTLIB_RESOURCES_FROM_PACKAGE is not None:
        try:
            import importlib.resources._common as common

            common.from_package = _ORIGINAL_IMPORTLIB_RESOURCES_FROM_PACKAGE
        except Exception:
            pass
    _INSTALLED = False
