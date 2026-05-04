from __future__ import annotations

import base64
import builtins
import hashlib
import io
import importlib
import importlib.util
import locale
import os
import posixpath
import shutil
import stat as _stat
import sys
import time
from dataclasses import dataclass


_INSTALLED = False
_RESOURCE_DATA_CACHE: dict[str, bytes] = {}
_RESOURCE_GROUPS: tuple[tuple[str, str, str], ...] | None = None
_RESOURCE_MODULE_CACHE: dict[str, object] = {}
_RESOURCE_STORE = None
_RESOURCE_STORE_PROBED = False
_START_TIME = int(time.time())


_ORIGINAL_OPEN = builtins.open
_ORIGINAL_IO_OPEN = io.open
_ORIGINAL_OS_STAT = os.stat
_ORIGINAL_OS_LISTDIR = os.listdir
_ORIGINAL_OS_SCANDIR = os.scandir
_ORIGINAL_OS_ACCESS = os.access
_ORIGINAL_OS_MKDIR = os.mkdir
_ORIGINAL_OS_MAKEDIRS = os.makedirs
_ORIGINAL_EXISTS = os.path.exists
_ORIGINAL_ISFILE = os.path.isfile
_ORIGINAL_ISDIR = os.path.isdir
_ORIGINAL_SHUTIL_COPYFILE = shutil.copyfile
_ORIGINAL_SHUTIL_COPY2 = shutil.copy2
_ORIGINAL_SHUTIL_COPYTREE = shutil.copytree
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


def _resource_store_module():
    global _RESOURCE_STORE, _RESOURCE_STORE_PROBED
    if _RESOURCE_STORE_PROBED:
        return _RESOURCE_STORE
    _RESOURCE_STORE_PROBED = True
    try:
        import _staticpython_resource_store as store
    except Exception:
        _RESOURCE_STORE = None
    else:
        _RESOURCE_STORE = store
    return _RESOURCE_STORE


def _has_resources_module() -> bool:
    if _resource_store_module() is not None:
        return True
    try:
        return importlib.util.find_spec("_staticpython_runtime_resources") is not None
    except Exception:
        return _resources_module() is not None


def _decode_resource_payload(encoded: bytes, payload_encoding: str) -> bytes:
    payload = base64.b85decode(encoded)
    if payload_encoding == "b85":
        return payload
    if payload_encoding == "zlib+b85":
        import zlib

        return zlib.decompress(payload)
    raise ValueError(f"unsupported StaticPython resource payload encoding: {payload_encoding!r}")


def _load_resource_groups() -> tuple[tuple[str, str, str], ...]:
    global _RESOURCE_GROUPS
    if _RESOURCE_GROUPS is not None:
        return _RESOURCE_GROUPS

    resources = _resources_module()
    if resources is None:
        _RESOURCE_GROUPS = ()
        return _RESOURCE_GROUPS

    raw_groups = getattr(resources, "RESOURCE_GROUPS", None)
    if raw_groups is None and hasattr(resources, "RESOURCE_TARGETS"):
        _RESOURCE_MODULE_CACHE["_staticpython_runtime_resources"] = resources
        _RESOURCE_GROUPS = (("", "_staticpython_runtime_resources", "_staticpython_runtime_resources"),)
        return _RESOURCE_GROUPS

    if isinstance(raw_groups, dict):
        items = raw_groups.items()
    else:
        items = raw_groups or ()

    raw_indexes = getattr(resources, "RESOURCE_GROUP_INDEXES", {})
    groups: list[tuple[str, str, str]] = []
    for prefix, module_name in items:
        normalized = _normalize_resource_key(prefix)
        if normalized:
            index_module_name = raw_indexes.get(prefix, module_name) if isinstance(raw_indexes, dict) else module_name
            groups.append((normalized, str(module_name), str(index_module_name)))
    groups.sort(key=lambda item: (-len(item[0]), item[0].lower()))
    _RESOURCE_GROUPS = tuple(groups)
    return _RESOURCE_GROUPS


def _load_resource_module(module_name: str):
    module = _RESOURCE_MODULE_CACHE.get(module_name)
    if module is None:
        module = importlib.import_module(module_name)
        _RESOURCE_MODULE_CACHE[module_name] = module
    return module


def _resource_target_value(resource_module, key: str) -> tuple[str, str, int] | None:
    value = getattr(resource_module, "RESOURCE_TARGETS", {}).get(key)
    if value is None or len(value) < 2:
        return None
    module_name, blob_id = value[:2]
    try:
        size = int(value[2]) if len(value) >= 3 else -1
    except Exception:
        size = -1
    return str(module_name), str(blob_id), size


def _resource_store_file_info(key: str) -> tuple[str, str, int] | None:
    store = _resource_store_module()
    if store is None:
        return None
    try:
        info = store.file_info(_normalize_resource_key(key))
    except Exception:
        return None
    if info is None:
        return None
    try:
        module_name, blob_id, size = info
        return str(module_name), str(blob_id), int(size)
    except Exception:
        return None


def _resource_store_children(key: str) -> tuple[str, ...] | None:
    store = _resource_store_module()
    if store is None:
        return None
    try:
        children = store.children(_normalize_resource_key(key))
    except Exception:
        return None
    if children is None:
        return None
    return tuple(str(child) for child in children)


def _resource_store_kind(key: str) -> int:
    store = _resource_store_module()
    if store is None:
        return 0
    try:
        return int(store.kind(_normalize_resource_key(key)))
    except Exception:
        return 0


def _resource_file_size_value(resource_module, key: str) -> int | None:
    key = _normalize_resource_key(key)
    sizes = getattr(resource_module, "RESOURCE_FILE_SIZES", None)
    if sizes is not None and key in sizes:
        try:
            return int(sizes[key])
        except Exception:
            return 0
    target = _resource_target_value(resource_module, key)
    if target is None:
        return None
    return target[2]


def _resource_children_for_key(key: str, resource_module=None) -> tuple[str, ...]:
    key = _normalize_resource_key(key)
    if resource_module is None:
        store_children = _resource_store_children(key)
        if store_children is not None:
            return store_children
    modules = (resource_module,) if resource_module is not None else _candidate_resource_modules(key, indexes=True)
    merged: set[str] = set()
    for module in modules:
        children = getattr(module, "RESOURCE_CHILDREN", {}).get(key)
        if children is not None:
            merged.update(children)
    return tuple(sorted(merged))


def _resource_key_is_file(key: str) -> bool:
    key = _normalize_resource_key(key)
    kind = _resource_store_kind(key)
    if kind:
        return kind == 1
    return any(_resource_file_size_value(module, key) is not None for module in _candidate_resource_modules(key, indexes=True))


def _resource_key_is_dir(key: str) -> bool:
    key = _normalize_resource_key(key)
    kind = _resource_store_kind(key)
    if kind:
        return kind == 2
    return any(key in getattr(module, "RESOURCE_CHILDREN", {}) for module in _candidate_resource_modules(key, indexes=True))


def _resolve_resource_key(key: str) -> str | None:
    key = _normalize_resource_key(key)
    if _resource_store_kind(key):
        return key
    for module in _candidate_resource_modules(key, indexes=True):
        if _resource_file_size_value(module, key) is not None or key in getattr(module, "RESOURCE_CHILDREN", {}):
            return key
        for index_name in ("RESOURCE_BASENAME_INDEX", "RESOURCE_DIR_BASENAME_INDEX"):
            for candidate in _suffix_resource_candidates(key, getattr(module, index_name, {})):
                if _resource_file_size_value(module, candidate) is not None or candidate in getattr(module, "RESOURCE_CHILDREN", {}):
                    return candidate
    return None


def _resource_target_for_key(key: str) -> tuple[object, tuple[str, str, int]] | None:
    key = _normalize_resource_key(key)
    store_target = _resource_store_file_info(key)
    if store_target is not None:
        return None, store_target
    for module in _candidate_resource_modules(key):
        target = _resource_target_value(module, key)
        if target is not None:
            return module, target
    return None


def _candidate_resource_modules(candidate: str, *, indexes: bool = False) -> tuple[object, ...]:
    candidate = _normalize_resource_key(candidate)
    lowered = candidate.lower()
    modules: list[object] = []
    for prefix, module_name, index_module_name in _load_resource_groups():
        lowered_prefix = prefix.lower()
        if (
            not prefix
            or lowered == lowered_prefix
            or lowered.startswith(lowered_prefix + "/")
        ):
            modules.append(_load_resource_module(index_module_name if indexes else module_name))
    return tuple(modules)


def _group_suffix_candidates(normalized: str) -> tuple[str, ...]:
    parts = [part for part in _normalize_resource_key(normalized).split("/") if part and part != "."]
    lowered_parts = [part.lower() for part in parts]
    candidates: list[str] = []
    for prefix, _module_name, _index_module_name in _load_resource_groups():
        prefix_parts = [part for part in prefix.split("/") if part]
        if prefix_parts and prefix_parts[0].lower() in {"lib", "share", "etc"}:
            marker_parts = prefix_parts[1:]
        else:
            marker_parts = prefix_parts
        if not marker_parts:
            continue
        lowered_marker = [part.lower() for part in marker_parts]
        limit = len(parts) - len(marker_parts) + 1
        for index in range(max(limit, 0)):
            if lowered_parts[index : index + len(marker_parts)] != lowered_marker:
                continue
            rest = parts[index + len(marker_parts) :]
            candidate = "/".join([prefix, *rest])
            if candidate not in candidates:
                candidates.append(candidate)
    return tuple(candidates)


def _decode_resource_key(key: str, resource_module=None) -> bytes | None:
    key = _normalize_resource_key(key)
    cached = _RESOURCE_DATA_CACHE.get(key)
    if cached is not None:
        return cached

    modules = (resource_module,) if resource_module is not None else _candidate_resource_modules(key)
    target = None
    target_module = None
    store_target = None if resource_module is not None else _resource_store_file_info(key)
    if store_target is not None:
        target = store_target
    else:
        for module in modules:
            target = _resource_target_value(module, key)
            if target is not None:
                target_module = module
                break
    if target is None:
        return None

    module_name, blob_id, _size = target
    payload_encoding = getattr(target_module, "RESOURCE_PAYLOAD_ENCODING", None) if target_module is not None else None
    if payload_encoding is None:
        resources = _resources_module()
        payload_encoding = getattr(resources, "RESOURCE_PAYLOAD_ENCODING", "b85") if resources is not None else "b85"
    try:
        if target_module is None:
            shard_module = importlib.import_module(module_name)
            encoded_chunks = shard_module.RESOURCE_BLOBS[blob_id]
        elif hasattr(target_module, "get_resource_payload"):
            encoded_chunks = target_module.get_resource_payload(module_name, blob_id)
        else:
            encoded_chunks = None
            for relative, chunks in target_module.iter_resource_payloads():
                if _normalize_resource_key(relative) == key:
                    encoded_chunks = chunks
                    break
        if encoded_chunks is None:
            return None
        encoded = "".join(encoded_chunks).encode("ascii")
        decoded = _decode_resource_payload(encoded, payload_encoding)
    except Exception:
        return None

    _RESOURCE_DATA_CACHE[key] = decoded
    return decoded


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


def _candidate_has_resource_root(candidate: str) -> bool:
    lowered = _normalize_resource_key(candidate).lower()
    return (
        lowered.startswith(("lib/", "share/", "etc/"))
        or "/lib/" in lowered
        or "/share/" in lowered
        or "/etc/" in lowered
    )


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

    raw_text = str(text).replace("\\", "/")
    is_resource_uri = raw_text.startswith("staticpython-resource://")
    normalized = _normalize_resource_key(text)
    candidates = [normalized]
    caller_candidates = _caller_relative_candidates(path)
    candidates.extend(caller_candidates)
    lowered = normalized.lower()
    for marker in ("/lib/", "/share/", "/etc/"):
        index = lowered.rfind(marker)
        if index >= 0:
            candidates.append(normalized[index + 1 :])
    for marker in ("lib/", "share/", "etc/"):
        index = lowered.find(marker)
        if index >= 0:
            candidates.append(normalized[index:])

    if is_resource_uri or bool(caller_candidates) or any(_candidate_has_resource_root(candidate) for candidate in candidates):
        candidates.extend(_group_suffix_candidates(normalized))
    else:
        candidates.extend(_group_suffix_candidates(normalized))

    deduped: list[str] = []
    for candidate in candidates:
        candidate = _normalize_resource_key(candidate)
        if candidate and candidate not in deduped:
            deduped.append(candidate)
    return tuple(deduped)


def _resource_key(path: object) -> str | None:
    for candidate in _candidate_resource_keys(path):
        resolved = _resolve_resource_key(candidate)
        if resolved is not None:
            return resolved
    return None


def _resource_data(path: object) -> bytes | None:
    for candidate in _candidate_resource_keys(path):
        resolved = _resolve_resource_key(candidate)
        if resolved is None:
            continue
        data = _decode_resource_key(resolved)
        if data is not None:
            return data
    return None


def _is_resource_dir(path: object) -> bool:
    key = _resource_key(path)
    return key is not None and _resource_key_is_dir(key)


def _resource_stat(path: object, *, follow_symlinks: bool = True):
    key = _resource_key(path)
    if key is None:
        raise FileNotFoundError(os.fspath(path))
    store_target = _resource_store_file_info(key)
    size = store_target[2] if store_target is not None else None
    if size is None:
        for module in _candidate_resource_modules(key, indexes=True):
            size = _resource_file_size_value(module, key)
            if size is not None:
                break
    if size is not None:
        mode = _stat.S_IFREG | 0o444
        if size < 0:
            data = _decode_resource_key(key)
            size = len(data) if data is not None else 0
    elif _resource_key_is_dir(key):
        mode = _stat.S_IFDIR | 0o555
        size = 0
    else:
        raise FileNotFoundError(os.fspath(path))
    inode = int.from_bytes(hashlib.blake2s(key.encode("utf-8"), digest_size=8).digest(), "little")
    inode &= (1 << 63) - 1
    ns = _START_TIME * 1_000_000_000
    return os.stat_result(
        (mode, inode or 1, 0, 1, 0, 0, size, _START_TIME, _START_TIME, _START_TIME),
        {
            "st_atime": float(_START_TIME),
            "st_mtime": float(_START_TIME),
            "st_ctime": float(_START_TIME),
            "st_atime_ns": ns,
            "st_mtime_ns": ns,
            "st_ctime_ns": ns,
            "st_file_attributes": 0,
            "st_reparse_tag": 0,
        },
    )


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
        if text_encoding == "locale":
            text_encoding = locale.getencoding()
        handle = io.StringIO(data.decode(text_encoding, errors or "strict"), newline=newline)
    try:
        handle.name = os.fspath(path)
        handle.mode = mode
    except Exception:
        pass
    return handle


def _staticpython_open(file, mode="r", buffering=-1, encoding=None, errors=None, newline=None, closefd=True, opener=None):
    if any(flag in mode for flag in ("w", "a", "x", "+")):
        return _ORIGINAL_OPEN(file, mode, buffering, encoding, errors, newline, closefd, opener)
    native_error = None
    try:
        return _ORIGINAL_OPEN(file, mode, buffering, encoding, errors, newline, closefd, opener)
    except OSError as exc:
        native_error = exc
    handle = _open_resource(file, mode, buffering, encoding, errors, newline)
    if handle is not None:
        return handle
    if native_error is not None:
        raise native_error
    return _ORIGINAL_OPEN(file, mode, buffering, encoding, errors, newline, closefd, opener)


def _staticpython_io_open(file, mode="r", buffering=-1, encoding=None, errors=None, newline=None, closefd=True, opener=None):
    if any(flag in mode for flag in ("w", "a", "x", "+")):
        return _ORIGINAL_IO_OPEN(file, mode, buffering, encoding, errors, newline, closefd, opener)
    native_error = None
    try:
        return _ORIGINAL_IO_OPEN(file, mode, buffering, encoding, errors, newline, closefd, opener)
    except OSError as exc:
        native_error = exc
    handle = _open_resource(file, mode, buffering, encoding, errors, newline)
    if handle is not None:
        return handle
    if native_error is not None:
        raise native_error
    return _ORIGINAL_IO_OPEN(file, mode, buffering, encoding, errors, newline, closefd, opener)


def _staticpython_stat(path, *args, dir_fd=None, follow_symlinks=True):
    native_error = None
    try:
        return _ORIGINAL_OS_STAT(path, *args, dir_fd=dir_fd, follow_symlinks=follow_symlinks)
    except OSError as exc:
        native_error = exc
    if dir_fd is None:
        try:
            return _resource_stat(path, follow_symlinks=follow_symlinks)
        except FileNotFoundError:
            pass
    if native_error is not None:
        raise native_error
    return _ORIGINAL_OS_STAT(path, *args, dir_fd=dir_fd, follow_symlinks=follow_symlinks)


def _staticpython_exists(path) -> bool:
    return _ORIGINAL_EXISTS(path) or _resource_key(path) is not None


def _staticpython_isfile(path) -> bool:
    if _ORIGINAL_ISFILE(path):
        return True
    key = _resource_key(path)
    return key is not None and _resource_key_is_file(key)


def _staticpython_isdir(path) -> bool:
    return _ORIGINAL_ISDIR(path) or _is_resource_dir(path)


def _staticpython_access(path, mode, *args, dir_fd=None, effective_ids=False, follow_symlinks=True):
    native_access = _ORIGINAL_OS_ACCESS(
        path,
        mode,
        *args,
        dir_fd=dir_fd,
        effective_ids=effective_ids,
        follow_symlinks=follow_symlinks,
    )
    if native_access:
        return True
    if _resource_key(path) is not None:
        if mode & os.W_OK:
            return False
        return True
    return native_access


def _real_path_exists(path) -> bool:
    try:
        _ORIGINAL_OS_STAT(path)
    except OSError:
        return False
    return True


def _real_path_isdir(path) -> bool:
    try:
        result = _ORIGINAL_OS_STAT(path)
    except OSError:
        return False
    return _stat.S_ISDIR(result.st_mode)


def _staticpython_makedirs(name, mode=0o777, exist_ok=False):
    head, tail = os.path.split(name)
    if not tail:
        head, tail = os.path.split(head)
    if head and tail and not _real_path_exists(head):
        try:
            _staticpython_makedirs(head, exist_ok=exist_ok)
        except FileExistsError:
            pass
        current_directory = os.curdir
        if isinstance(tail, bytes):
            current_directory = os.fsencode(current_directory)
        if tail == current_directory:
            return
    try:
        _ORIGINAL_OS_MKDIR(name, mode)
    except OSError:
        if not exist_ok or not _real_path_isdir(name):
            raise


def _merge_directory_children(path: object) -> list[str] | None:
    key = _resource_key(path)
    if key is None:
        return None
    children = set(_resource_children_for_key(key))
    try:
        children.update(_ORIGINAL_OS_LISTDIR(path))
    except OSError:
        pass
    return sorted(children)


def _staticpython_listdir(path=None):
    if path is None:
        return _ORIGINAL_OS_LISTDIR(path)
    try:
        native_children = _ORIGINAL_OS_LISTDIR(path)
    except OSError:
        native_children = None
    children = _merge_directory_children(path)
    if children is not None:
        if native_children is not None:
            children = sorted(set(children).union(native_children))
        return children
    if native_children is not None:
        return native_children
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


def _staticpython_shutil_copyfile(src, dst, *, follow_symlinks=True):
    data = _resource_data(src)
    if data is None:
        return _ORIGINAL_SHUTIL_COPYFILE(src, dst, follow_symlinks=follow_symlinks)
    with _ORIGINAL_OPEN(dst, "wb") as handle:
        handle.write(data)
    return dst


def _staticpython_shutil_copy2(src, dst, *, follow_symlinks=True):
    data = _resource_data(src)
    if data is None:
        return _ORIGINAL_SHUTIL_COPY2(src, dst, follow_symlinks=follow_symlinks)
    if _staticpython_isdir(dst):
        dst = os.path.join(dst, os.path.basename(os.fspath(src)))
    _staticpython_shutil_copyfile(src, dst, follow_symlinks=follow_symlinks)
    shutil.copystat(src, dst, follow_symlinks=follow_symlinks)
    return dst


def _staticpython_shutil_copytree(
    src,
    dst,
    symlinks=False,
    ignore=None,
    copy_function=None,
    ignore_dangling_symlinks=False,
    dirs_exist_ok=False,
):
    resource_key = _resource_key(src)
    if resource_key is None or not _resource_key_is_dir(resource_key):
        return _ORIGINAL_SHUTIL_COPYTREE(
            src,
            dst,
            symlinks=symlinks,
            ignore=ignore,
            copy_function=_staticpython_shutil_copy2 if copy_function is None else copy_function,
            ignore_dangling_symlinks=ignore_dangling_symlinks,
            dirs_exist_ok=dirs_exist_ok,
        )

    names = _staticpython_listdir(src)
    ignored_names = set(ignore(os.fspath(src), names)) if ignore is not None else set()
    errors = []
    _ORIGINAL_OS_MAKEDIRS(dst, exist_ok=dirs_exist_ok)
    copy_function = _staticpython_shutil_copy2 if copy_function is None else copy_function

    for name in names:
        if name in ignored_names:
            continue
        src_name = os.path.join(os.fspath(src), name)
        dst_name = os.path.join(os.fspath(dst), name)
        try:
            if _staticpython_isdir(src_name):
                _staticpython_shutil_copytree(
                    src_name,
                    dst_name,
                    symlinks=symlinks,
                    ignore=ignore,
                    copy_function=copy_function,
                    ignore_dangling_symlinks=ignore_dangling_symlinks,
                    dirs_exist_ok=dirs_exist_ok,
                )
            else:
                copy_function(src_name, dst_name)
        except shutil.Error as exc:
            errors.extend(exc.args[0])
        except OSError as exc:
            errors.append((src_name, dst_name, str(exc)))

    try:
        shutil.copystat(src, dst)
    except OSError as exc:
        errors.append((src, dst, str(exc)))
    if errors:
        raise shutil.Error(errors)
    return dst


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
            return list(_resource_children_for_key(self.base))

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
            for child in _resource_children_for_key(self.key):
                yield _StaticPythonTraversable(
                    f"{self.key}/{child}",
                    self.package_name,
                    child,
                )

        def is_dir(self):
            return _resource_key_is_dir(self.key)

        def is_file(self):
            key = _resource_key(self.key)
            return key is not None and _resource_key_is_file(key)

        def joinpath(self, child, *descendants):
            key = self.key
            for part in (child, *descendants):
                key = f"{key}/{part}"
            return _StaticPythonTraversable(key, self.package_name)

        __truediv__ = joinpath

        def open(self, mode="r", *args, **kwargs):
            key = _resource_key(self.key)
            data = _decode_resource_key(key) if key is not None else None
            if data is None:
                raise FileNotFoundError(self.key)
            if "b" in mode:
                return io.BytesIO(data)
            encoding = kwargs.get("encoding") or (args[0] if args else None) or "utf-8"
            errors = kwargs.get("errors") or "strict"
            newline = kwargs.get("newline")
            return io.StringIO(data.decode(encoding, errors), newline=newline)

        def read_bytes(self):
            key = _resource_key(self.key)
            data = _decode_resource_key(key) if key is not None else None
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
            if _resource_key_is_dir(base):
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
    if not _has_resources_module():
        return
    builtins.open = _staticpython_open
    io.open = _staticpython_io_open
    os.stat = _staticpython_stat
    os.listdir = _staticpython_listdir
    os.scandir = _staticpython_scandir
    os.access = _staticpython_access
    os.makedirs = _staticpython_makedirs
    os.path.exists = _staticpython_exists
    os.path.isfile = _staticpython_isfile
    os.path.isdir = _staticpython_isdir
    shutil.copyfile = _staticpython_shutil_copyfile
    shutil.copy2 = _staticpython_shutil_copy2
    shutil.copytree = _staticpython_shutil_copytree
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
    os.makedirs = _ORIGINAL_OS_MAKEDIRS
    os.path.exists = _ORIGINAL_EXISTS
    os.path.isfile = _ORIGINAL_ISFILE
    os.path.isdir = _ORIGINAL_ISDIR
    shutil.copyfile = _ORIGINAL_SHUTIL_COPYFILE
    shutil.copy2 = _ORIGINAL_SHUTIL_COPY2
    shutil.copytree = _ORIGINAL_SHUTIL_COPYTREE
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
