"""Freeze modules and regen related files (e.g. Python/frozen.c).

See the notes at the top of Python/frozen.c for more info.
"""
import argparse
import ast
import concurrent.futures
from collections import namedtuple
import hashlib
import io
import ntpath
import os
import posixpath
import re
import shutil
import subprocess
import tempfile
import time
import tokenize
import traceback
# Frozen module metadata.
FrozenModule1 = namedtuple('FrozenModule', [
    'fullname',
    'py_path',
    'h_path',
    'c_path',
    'is_package',
])


def _is_valid_module_segment(name):
    return bool(name) and name.isidentifier()


def _is_valid_module_path(parts):
    return all(_is_valid_module_segment(part) for part in parts if part)


SKIP_MODULE_TREES = (
    'idlelib',
    'sympy.testing',
    'test',
    'tkinter',
    'turtledemo',
)
OPTIONAL_FROZEN_TREES_FILE = os.path.join(
    'PCbuild',
    'staticpython_optional_frozen_trees.txt',
)
SKIP_DIRECTORY_NAMES = {
    'bench',
    'benchmark',
    'benchmarks',
    'demo',
    'demos',
    'doc',
    'docs',
    'example',
    'examples',
    'test',
    'tests',
    'testing',
}
NESTED_RUNTIME_PACKAGE_DIRECTORY_NAMES = {
    'doc',
    'docs',
}


def _matches_module_tree(fullname, tree_name):
    return fullname == tree_name or fullname.startswith(tree_name + '.')


def _load_optional_frozen_trees(root_dir):
    marker = os.path.join(root_dir, OPTIONAL_FROZEN_TREES_FILE)
    if not os.path.exists(marker):
        return ()
    with open(marker, encoding='utf-8') as marker_file:
        requested = tuple(
            line.strip()
            for line in marker_file
            if line.strip() and not line.lstrip().startswith('#')
        )
    invalid = sorted({name for name in requested if name not in SKIP_MODULE_TREES})
    if invalid:
        raise RuntimeError(
            'unknown optional frozen module tree(s): ' + ', '.join(invalid)
        )
    return tuple(dict.fromkeys(requested))


def _active_skip_module_trees(root_dir):
    enabled = set(_load_optional_frozen_trees(root_dir))
    return tuple(name for name in SKIP_MODULE_TREES if name not in enabled)


def _should_descend_directory(
    namespace_parts,
    dirname,
    skip_module_trees=SKIP_MODULE_TREES,
    is_package=False,
):
    child_parts = [*namespace_parts, dirname]
    child_name = '.'.join(child_parts)
    if dirname in SKIP_DIRECTORY_NAMES and not (
        namespace_parts
        and is_package
        and dirname in NESTED_RUNTIME_PACKAGE_DIRECTORY_NAMES
    ):
        return False
    if any(_matches_module_tree(child_name, tree_name) for tree_name in skip_module_trees):
        return False
    return True


def _should_freeze_module(fullname, skip_module_trees=SKIP_MODULE_TREES):
    if not fullname:
        return False
    if any(_matches_module_tree(fullname, tree_name) for tree_name in skip_module_trees):
        return False
    return True


def find_python_modules(root_dir):
    """
    Recursively discover Python modules.
    """
    lib_dir = os.path.join(root_dir, 'Lib')
    frozen_dir = os.path.join(root_dir, 'Python', 'frozen_modules')
    skip_module_trees = _active_skip_module_trees(root_dir)

    for root, dirs, files in os.walk(lib_dir):
        # Module path relative to Lib.
        rel_path = os.path.relpath(root, lib_dir)
        if rel_path == ".":
            namespace_parts = []
        else:
            namespace_parts = rel_path.split(os.sep)
            if not _is_valid_module_path(namespace_parts):
                dirs[:] = []
                continue

        # Only descend into valid package-like directories. Skip real test and
        # sample trees while preserving runtime modules like click.testing.
        dirs[:] = sorted(
            d for d in dirs
            if _is_valid_module_segment(d)
            and _should_descend_directory(
                namespace_parts,
                d,
                skip_module_trees=skip_module_trees,
                is_package=os.path.exists(os.path.join(root, d, '__init__.py')),
            )
        )
        package_dir_names = {
            d for d in dirs
            if os.path.exists(os.path.join(root, d, '__init__.py'))
        }

        # Package directory with __init__.py.
        if '__init__.py' in files:
            pkg_name = ".".join(namespace_parts) if namespace_parts else ""
            
            # The package itself is not emitted as __init__.h.
            yield FrozenModule1(
                fullname=pkg_name,
                py_path=os.path.join(root, '__init__.py'),
                h_path=os.path.join(frozen_dir, f"{pkg_name}.h") if pkg_name else "",
                c_path=os.path.join(frozen_dir, f"{pkg_name}.c") if pkg_name else "",
                is_package=True
            )

            # Submodules inside the package directory.
            for f in sorted(files):
                if f.endswith('.py') and f != '__init__.py':
                    mod_name = f[:-3]
                    if not _is_valid_module_segment(mod_name):
                        continue
                    if mod_name in package_dir_names:
                        continue
                    full_name = f"{pkg_name}.{mod_name}" if pkg_name else mod_name
                    yield FrozenModule1(
                        fullname=full_name,
                        py_path=os.path.join(root, f),
                        h_path=os.path.join(frozen_dir, f"{full_name}.h"),
                        c_path=os.path.join(frozen_dir, f"{full_name}.c"),
                        is_package=False
                    )

        # Plain modules at Lib root.
        elif root == lib_dir:
            for f in sorted(files):
                if f.endswith('.py'):
                    mod_name = f[:-3]
                    if not _is_valid_module_segment(mod_name):
                        continue
                    if mod_name in package_dir_names:
                        continue
                    yield FrozenModule1(
                        fullname=mod_name,
                        py_path=os.path.join(root, f),
                        h_path=os.path.join(frozen_dir, f"{mod_name}.h"),
                        c_path=os.path.join(frozen_dir, f"{mod_name}.c"),
                        is_package=False
                    )



def load_auto_frozen():
    filenames = []
    skip_module_trees = _active_skip_module_trees(ROOT_DIR)

    for module in find_python_modules(ROOT_DIR):
        if not _should_freeze_module(module.fullname, skip_module_trees):
            continue
        if module.is_package:
            filenames.append(f'{module.fullname} : <{module.fullname}> = {module.py_path}')
        else:
            filenames.append(f'{module.fullname} : {module.fullname} = {module.py_path}')

    return filenames


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
ROOT_DIR = os.path.abspath(ROOT_DIR)
FROZEN_ONLY = os.path.join(ROOT_DIR, 'Tools', 'freeze', 'flag.py')

STDLIB_DIR = os.path.join(ROOT_DIR, 'Lib')
# If FROZEN_MODULES_DIR or DEEPFROZEN_MODULES_DIR is changed then the
# .gitattributes and .gitignore files needs to be updated.
FROZEN_MODULES_DIR = os.path.join(ROOT_DIR, 'Python', 'frozen_modules')

FROZEN_FILE = os.path.join(ROOT_DIR, 'Python', 'frozen.c')
MAKEFILE = os.path.join(ROOT_DIR, 'Makefile.pre.in')
PCBUILD_PROJECT = os.path.join(ROOT_DIR, 'PCbuild', '_freeze_module.vcxproj')
PCBUILD_FILTERS = os.path.join(ROOT_DIR, 'PCbuild', '_freeze_module.vcxproj.filters')
PCBUILD_PYTHONCORE = os.path.join(ROOT_DIR, 'PCbuild', 'pythoncore.vcxproj')

OS_PATH = 'ntpath' if os.name == 'nt' else 'posixpath'
_FROZEN_STRUCT_HAS_GET_CODE = None


def frozen_struct_has_get_code():
    global _FROZEN_STRUCT_HAS_GET_CODE
    if _FROZEN_STRUCT_HAS_GET_CODE is not None:
        return _FROZEN_STRUCT_HAS_GET_CODE
    import_h = os.path.join(ROOT_DIR, 'Include', 'cpython', 'import.h')
    try:
        with open(import_h, encoding='utf-8') as infile:
            text = infile.read()
    except OSError:
        _FROZEN_STRUCT_HAS_GET_CODE = False
        return _FROZEN_STRUCT_HAS_GET_CODE
    match = re.search(r'struct\s+_frozen\s*\{(?P<body>.*?)\};', text, flags=re.DOTALL)
    _FROZEN_STRUCT_HAS_GET_CODE = match is not None and 'get_code' in match.group('body')
    return _FROZEN_STRUCT_HAS_GET_CODE

# These are modules that get frozen.
# If you're debugging new bytecode instructions,
# you can delete all sections except 'import system'.
# This also speeds up building somewhat.
TESTS_SECTION = 'Test module'
FROZEN = [
    # See parse_frozen_spec() for the format.
    # In cases where the frozenid is duplicated, the first one is re-used.
    ('import system', [
        *load_auto_frozen(),
        # These frozen modules are necessary for bootstrapping
        # the import system.
        'importlib._bootstrap : _frozen_importlib',
        'importlib._bootstrap_external : _frozen_importlib_external',
        # This module is important because some Python builds rely
        # on a builtin zip file instead of a filesystem.
        'zipimport',
        ]),
    # (You can delete entries from here down to the end of the list.)
    ('stdlib - startup, without site (python -S)', [
        'abc',
        'codecs',
        # For now we do not freeze the encodings, due # to the noise all
        # those extra modules add to the text printed during the build.
        # (See https://github.com/python/cpython/pull/28398#pullrequestreview-756856469.)
        #'<encodings.*>',
        'io',
        ]),
    ('stdlib - startup, with site', [
        '_collections_abc',
        '_sitebuiltins',
        'genericpath',
        'ntpath',
        'posixpath',
        # We must explicitly mark os.path as a frozen module
        # even though it will never be imported.
        f'{OS_PATH} : os.path',
        'os',
        'site',
        'stat',
        ]),
    ('runpy - run module with -m', [
        "importlib.util",
        "importlib.machinery",
        "runpy",
    ]),
    (TESTS_SECTION, [
        
        '__hello__',
        '__hello__ : __hello_alias__',
        '__hello__ : <__phello_alias__>',
        '__hello__ : __phello_alias__.spam',
        ]),
    # (End of stuff you could delete.)
]
BOOTSTRAP = {
    'importlib._bootstrap',
    'importlib._bootstrap_external',
    'zipimport',
}
def _package_markers(fullname):
    return (
        f"__package__ = '{fullname}'".encode("utf-8"),
        b"__path__ = [__name__]",
    )


def _package_header_present(lines, fullname):
    package_line, path_line = _package_markers(fullname)
    return any(line.strip() == package_line for line in lines) and any(
        line.strip() == path_line for line in lines
    )


def _detect_newline(lines):
    for line in lines:
        if line.endswith(b'\r\n'):
            return b'\r\n'
        if line.endswith(b'\n'):
            return b'\n'
    return b'\n'


def _find_package_insert_index_with_tokens(content, lines):
    insert_pos = 0
    reader = io.BytesIO(content).readline
    tokens = tokenize.tokenize(reader)
    statement = []

    try:
        for tok in tokens:
            tok_type = tok.type
            if tok_type in {
                tokenize.ENCODING,
                tokenize.NL,
                tokenize.COMMENT,
                tokenize.INDENT,
                tokenize.DEDENT,
            }:
                continue
            if tok_type == tokenize.ENDMARKER:
                break

            statement.append(tok)
            if tok_type != tokenize.NEWLINE:
                continue

            significant = [item for item in statement if item.type != tokenize.NEWLINE]
            statement = []
            if not significant:
                continue

            first = significant[0]
            if first.type == tokenize.STRING and insert_pos == 0:
                insert_pos = first.end[0]
                continue

            if (
                len(significant) >= 3
                and significant[0].string == 'from'
                and significant[1].string == '__future__'
                and significant[2].string == 'import'
            ):
                insert_pos = tok.end[0]
                continue

            break
    except tokenize.TokenError:
        insert_pos = 0

    preamble_limit = min(2, len(lines))
    while insert_pos < preamble_limit:
        stripped = lines[insert_pos].lstrip()
        if stripped.startswith(b'#!') or stripped.startswith(b'#') and b'coding' in stripped:
            insert_pos += 1
            continue
        break
    return max(0, min(insert_pos, len(lines)))


def _find_package_insert_index(content, lines):
    text = content.decode('utf-8')
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return _find_package_insert_index_with_tokens(content, lines)
    insert_lineno = 1
    body = list(tree.body)

    if body:
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(getattr(first, 'value', None), ast.Constant)
            and isinstance(first.value.value, str)
        ):
            insert_lineno = getattr(first, 'end_lineno', first.lineno) + 1
            body = body[1:]

    for node in body:
        if isinstance(node, ast.ImportFrom) and node.module == '__future__':
            insert_lineno = getattr(node, 'end_lineno', node.lineno) + 1
            continue
        break

    insert_pos = max(0, min(insert_lineno - 1, len(lines)))

    # Preserve shebang/coding cookie placement if they exist.
    preamble_limit = min(2, len(lines))
    while insert_pos < preamble_limit:
        stripped = lines[insert_pos].lstrip()
        if stripped.startswith(b'#!') or stripped.startswith(b'#') and b'coding' in stripped:
            insert_pos += 1
            continue
        break
    return insert_pos


def _inject_package_header(content, fullname):
    bom = b''
    payload = content

    if payload.startswith(b'\xef\xbb\xbf'):
        bom = payload[:3]
        payload = payload[3:]

    lines = payload.splitlines(keepends=True)
    if _package_header_present(lines, fullname):
        return content, False

    newline = _detect_newline(lines)
    insert_pos = _find_package_insert_index(payload, lines) if lines else 0
    if insert_pos > 0 and not lines[insert_pos - 1].endswith((b'\n', b'\r\n')):
        lines[insert_pos - 1] += newline
    lines[insert_pos:insert_pos] = [
        f"__package__ = '{fullname}'".encode('utf-8') + newline,
        b"__path__ = [__name__]" + newline,
    ]
    return bom + b''.join(lines), True


def _normalize_source_for_freezing(content):
    if b'\\N{' not in content:
        return content, False

    text = content.decode('utf-8-sig')
    normalized = ast.unparse(ast.parse(text))
    if not normalized.endswith('\n'):
        normalized += '\n'
    return normalized.encode('utf-8'), True


def _write_temp_source(content):
    fd, temp_path = tempfile.mkstemp(suffix='.py')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(content)
    except Exception:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise
    return temp_path


def _prepare_source_for_freezing(py_path, fullname=None, is_package=False):
    with open(py_path, 'rb') as f:
        content = f.read()

    changed = False
    if is_package:
        content, package_changed = _inject_package_header(content, fullname)
        changed = changed or package_changed

    content, normalized = _normalize_source_for_freezing(content)
    changed = changed or normalized

    if not changed:
        return None

    return _write_temp_source(content)


def _get_freeze_worker_count():
    return max((os.cpu_count() or 1) - 2, 1)


def _freeze_module_worker(root_dir, freeze_tool, module):
    cmd = [
        freeze_tool,
        module.fullname,
        module.py_path,
        module.h_path,
    ]
    temp_py_path = None
    try:
        temp_py_path = _prepare_source_for_freezing(
            module.py_path,
            fullname=module.fullname if module.is_package else None,
            is_package=module.is_package,
        )
        if temp_py_path is not None:
            cmd[2] = temp_py_path

        result = subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace',
            cwd=root_dir,
        )
        return {
            'ok': True,
            'module': module.fullname,
            'cmd': cmd,
            'stdout': result.stdout or '',
            'h_path': module.h_path,
            'c_path': module.c_path,
        }
    except subprocess.CalledProcessError as exc:
        return {
            'ok': False,
            'module': module.fullname,
            'cmd': cmd,
            'stdout': exc.stdout or '',
            'h_path': module.h_path,
            'c_path': module.c_path,
        }
    except Exception:
        return {
            'ok': False,
            'module': module.fullname,
            'cmd': cmd,
            'stdout': traceback.format_exc(),
            'h_path': module.h_path,
            'c_path': module.c_path,
        }
    finally:
        if temp_py_path is not None and os.path.exists(temp_py_path):
            os.unlink(temp_py_path)


def _frozen_header_is_valid(module):
    expected_prefix = b'/* Auto-generated by Programs/_freeze_module.c */'
    expected_symbol = f"_Py_M__{module.fullname.replace('.', '_')}".encode("ascii")
    try:
        with open(module.h_path, 'rb') as header_file:
            content = header_file.read()
    except OSError:
        return False
    return content.startswith(expected_prefix) and expected_symbol in content


def _repair_invalid_frozen_headers(root_dir, freeze_tool, modules):
    invalid = [module for module in modules if not _frozen_header_is_valid(module)]
    if not invalid:
        return []

    print(f'Detected {len(invalid)} incomplete frozen headers; retrying sequentially')
    remaining = []
    for module in invalid:
        result = _freeze_module_worker(root_dir, freeze_tool, module)
        if result['ok'] and _frozen_header_is_valid(module):
            print(f"Retry succeeded: {module.fullname}")
            continue
        remaining.append(result)
        print(f"Retry failed: {module.fullname}")
        print(f"Command: {' '.join(result['cmd'])}")
        if result['stdout']:
            print('Output:')
            print(result['stdout'])
    return remaining


def resolve_freeze_module_exe(root_dir):
    env_path = os.environ.get('FREEZE_MODULE_EXE')
    if env_path:
        env_path = os.path.abspath(env_path)
        if os.path.exists(env_path):
            return env_path

    candidates = []
    for arch in ('amd64', 'win32', 'arm64', 'arm'):
        candidates.append(os.path.join(root_dir, 'PCbuild', arch, '_freeze_module.exe'))

    obj_root = os.path.join(root_dir, 'PCbuild', 'obj')
    if os.path.isdir(obj_root):
        for current_root, _, files in os.walk(obj_root):
            if '_freeze_module.exe' in files:
                candidates.append(os.path.join(current_root, '_freeze_module.exe'))

    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate

    raise FileNotFoundError(f'could not locate _freeze_module.exe under {os.path.join(root_dir, "PCbuild")}')



def generate_frozen_files(root_dir):
    """
    Generate frozen module files.
    """
    frozen_dir = os.path.join(root_dir, 'Python', 'frozen_modules')
    if os.path.exists(frozen_dir):
        shutil.rmtree(frozen_dir)
    os.makedirs(frozen_dir, exist_ok=True)

    freeze_tool = resolve_freeze_module_exe(root_dir)

    skip_module_trees = _active_skip_module_trees(root_dir)
    modules_to_freeze = [
        module
        for module in find_python_modules(root_dir)
        if _should_freeze_module(module.fullname, skip_module_trees)
    ]
    total = len(modules_to_freeze)
    if not total:
        print('No modules need freezing')
        return

    workers = min(_get_freeze_worker_count(), total)
    start_time = time.perf_counter()
    print(f'Freezing {total} modules with workers={workers}')

    failures = []
    completed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(_freeze_module_worker, root_dir, freeze_tool, module)
            for module in modules_to_freeze
        ]
        for future in concurrent.futures.as_completed(futures):
            completed += 1
            result = future.result()
            if result['ok']:
                print(f"[{completed}/{total}] Frozen: {result['module']}")
            else:
                failures.append(result)
                print(f"[{completed}/{total}] Freeze failed: {result['module']}")
                print(f"Command: {' '.join(result['cmd'])}")
                if result['stdout']:
                    print('Output:')
                    print(result['stdout'])

    elapsed = time.perf_counter() - start_time
    print(f'Freeze phase finished in {elapsed:.2f} seconds')

    failures.extend(_repair_invalid_frozen_headers(root_dir, freeze_tool, modules_to_freeze))

    if failures:
        failed_names = ', '.join(item['module'] for item in failures[:10])
        if len(failures) > 10:
            failed_names += f' ... (+{len(failures) - 10} more)'
        raise RuntimeError(f'Freeze failed for {len(failures)} modules: {failed_names}')


#######################################
# platform-specific helpers

if os.path is posixpath:
    relpath_for_posix_display = os.path.relpath

    def relpath_for_windows_display(path, base):
        return ntpath.relpath(
            ntpath.join(*path.split(os.path.sep)),
            ntpath.join(*base.split(os.path.sep)),
        )

else:
    relpath_for_windows_display = ntpath.relpath

    def relpath_for_posix_display(path, base):
        return posixpath.relpath(
            posixpath.join(*path.split(os.path.sep)),
            posixpath.join(*base.split(os.path.sep)),
        )


#######################################
# specs

def parse_frozen_specs():
    seen = {}
    for section, specs in FROZEN:
        parsed = _parse_specs(specs, section, seen)
        for item in parsed:
            frozenid, pyfile, modname, ispkg, section = item
            try:
                source = seen[frozenid]
            except KeyError:
                source = FrozenSource.from_id(frozenid, pyfile)
                seen[frozenid] = source
            else:
                assert not pyfile or pyfile == source.pyfile, item
            yield FrozenModule(modname, ispkg, section, source)


def _parse_specs(specs, section, seen):
    for spec in specs:
        info, subs = _parse_spec(spec, seen, section)
        yield info
        for info in subs or ():
            yield info


def _parse_spec(spec, knownids=None, section=None):
    """Yield an info tuple for each module corresponding to the given spec.

    The info consists of: (frozenid, pyfile, modname, ispkg, section).

    Supported formats:

      frozenid
      frozenid : modname
      frozenid : modname = pyfile

    "frozenid" and "modname" must be valid module names (dot-separated
    identifiers).  If "modname" is not provided then "frozenid" is used.
    If "pyfile" is not provided then the filename of the module
    corresponding to "frozenid" is used.

    Angle brackets around a frozenid (e.g. '<encodings>") indicate
    it is a package.  This also means it must be an actual module
    (i.e. "pyfile" cannot have been provided).  Such values can have
    patterns to expand submodules:

      <encodings.*>    - also freeze all direct submodules
      <encodings.**.*> - also freeze the full submodule tree

    As with "frozenid", angle brackets around "modname" indicate
    it is a package.  However, in this case "pyfile" should not
    have been provided and patterns in "modname" are not supported.
    Also, if "modname" has brackets then "frozenid" should not,
    and "pyfile" should have been provided..
    """
    frozenid, _, remainder = spec.partition(':')
    modname, _, pyfile = remainder.partition('=')
    frozenid = frozenid.strip()
    modname = modname.strip()
    pyfile = pyfile.strip()

    submodules = None
    if modname.startswith('<') and modname.endswith('>'):
        assert check_modname(frozenid), spec
        modname = modname[1:-1]
        assert check_modname(modname), spec
        if frozenid in knownids:
            pass
        elif pyfile:
            assert not os.path.isdir(pyfile), spec
        else:
            pyfile = _resolve_module(frozenid, ispkg=False)
        ispkg = True
    elif pyfile:
        assert check_modname(frozenid), spec
        assert not knownids or frozenid not in knownids, spec
        assert check_modname(modname), spec
        assert not os.path.isdir(pyfile), spec
        ispkg = False
    elif knownids and frozenid in knownids:
        assert check_modname(frozenid), spec
        #assert check_modname(modname), spec
        ispkg = False
    else:
        assert not modname or check_modname(modname), spec
        resolved = iter(resolve_modules(frozenid))
        frozenid, pyfile, ispkg = next(resolved)
        if not modname:
            modname = frozenid
        if ispkg:
            pkgid = frozenid
            pkgname = modname
            pkgfiles = {pyfile: pkgid}
            def iter_subs():
                for frozenid, pyfile, ispkg in resolved:
                    if pkgname:
                        modname = frozenid.replace(pkgid, pkgname, 1)
                    else:
                        modname = frozenid
                    if pyfile:
                        if pyfile in pkgfiles:
                            frozenid = pkgfiles[pyfile]
                            pyfile = None
                        elif ispkg:
                            pkgfiles[pyfile] = frozenid
                    yield frozenid, pyfile, modname, ispkg, section
            submodules = iter_subs()

    info = (frozenid, pyfile or None, modname, ispkg, section)
    return info, submodules


#######################################
# frozen source files

class FrozenSource(namedtuple('FrozenSource', 'id pyfile frozenfile')):

    @classmethod
    def from_id(cls, frozenid, pyfile=None):
        if not pyfile:
            pyfile = os.path.join(STDLIB_DIR, *frozenid.split('.')) + '.py'
            #assert os.path.exists(pyfile), (frozenid, pyfile)
        #print(frozenid)
        frozenfile = resolve_frozen_file(frozenid, FROZEN_MODULES_DIR)
        return cls(frozenid, pyfile, frozenfile)

    @property
    def frozenid(self):
        return self.id

    @property
    def modname(self):
        if self.pyfile.startswith(STDLIB_DIR):
            return self.id
        return None

    @property
    def symbol(self):
        # This matches what we do in Programs/_freeze_module.c:
        name = self.frozenid.replace('.', '_')
        return '_Py_M__' + name

    @property
    def ispkg(self):
        if not self.pyfile:
            return False
        elif self.frozenid.endswith('.__init__'):
            return False
        else:
            return os.path.basename(self.pyfile) == '__init__.py'

    @property
    def isbootstrap(self):
        return self.id in BOOTSTRAP


def resolve_frozen_file(frozenid, destdir):
    """Return the filename corresponding to the given frozen ID.

    For stdlib modules the ID will always be the full name
    of the source module.
    """
    if not isinstance(frozenid, str):
        try:
            frozenid = frozenid.frozenid
        except AttributeError:
            raise ValueError(f'unsupported frozenid {frozenid!r}')
    # We use a consistent naming convention for all frozen modules.
    frozenfile = f'{frozenid}.h'
    if not destdir:
        return frozenfile
    return os.path.join(destdir, frozenfile)


#######################################
# frozen modules

class FrozenModule(namedtuple('FrozenModule', 'name ispkg section source')):

    def __getattr__(self, name):
        return getattr(self.source, name)

    @property
    def modname(self):
        return self.name

    @property
    def orig(self):
        return self.source.modname

    @property
    def isalias(self):
        orig = self.source.modname
        if not orig:
            return True
        return self.name != orig

    def summarize(self):
        source = self.source.modname
        if source:
            source = f'<{source}>'
        else:
            source = relpath_for_posix_display(self.pyfile, ROOT_DIR)
        return {
            'module': self.name,
            'ispkg': self.ispkg,
            'source': source,
            'frozen': os.path.basename(self.frozenfile),
            'checksum': _get_checksum(self.frozenfile),
        }


def _iter_sources(modules):
    seen = set()
    for mod in modules:
        if mod.source not in seen:
            yield mod.source
            seen.add(mod.source)


#######################################
# generic helpers

def _get_checksum(filename):
    with open(filename, "rb") as infile:
        contents = infile.read()
    m = hashlib.sha256()
    m.update(contents)
    return m.hexdigest()


def read_text_lines(filename):
    with open(filename, encoding='utf-8-sig', newline='') as infile:
        return infile.readlines()


def write_text_lines(filename, lines):
    with open(filename, 'w', encoding='utf-8', newline='') as outfile:
        outfile.writelines(lines)


def resolve_modules(modname, pyfile=None):
    """Resolve package directories and plain modules."""
    # Detect package structure automatically.
    if not pyfile:
        pyfile = _resolve_module(modname, ispkg=False)
        if os.path.isdir(pyfile):
            pyfile = os.path.join(pyfile, '__init__.py')
    
    ispkg = False
    # Check whether this is a package.
    if os.path.basename(pyfile) == '__init__.py':
        ispkg = True
        actual_path = os.path.dirname(pyfile)
    else:
        actual_path = pyfile
    
    # Recursively discover modules in package directories.
    if os.path.isdir(actual_path):
        ispkg = True
        yield from _find_package_modules(modname, actual_path)
    else:
        yield modname, pyfile, ispkg

def _find_package_modules(pkgname, pkgdir):
    """Recursively discover submodules inside a package."""
    yield pkgname, os.path.join(pkgdir, '__init__.py'), True
    
    for root, dirs, files in os.walk(pkgdir):
        rel_path = os.path.relpath(root, pkgdir).replace(os.sep, '.')
        if rel_path == '.':
            rel_path = ''
        
        for f in files:
            if f.endswith('.py') and f != '__init__.py':
                modname = f'{pkgname}.{rel_path}.{f[:-3]}' if rel_path else f'{pkgname}.{f[:-3]}'
                yield modname, os.path.join(root, f), False
        
        for d in dirs:
            subdir = os.path.join(root, d)
            if os.path.exists(os.path.join(subdir, '__init__.py')):
                submod = f'{pkgname}.{rel_path}.{d}' if rel_path else f'{pkgname}.{d}'
                yield from _find_package_modules(submod, subdir)

def check_modname(modname):
    return all(n.isidentifier() for n in modname.split('.'))


def iter_submodules(pkgname, pkgdir=None, match='*'):
    if not pkgdir:
        pkgdir = os.path.join(STDLIB_DIR, *pkgname.split('.'))
    if not match:
        match = '**.*'
    match_modname = _resolve_modname_matcher(match, pkgdir)

    def _iter_submodules(pkgname, pkgdir):
        for entry in sorted(os.scandir(pkgdir), key=lambda e: e.name):
            matched, recursive = match_modname(entry.name)
            if not matched:
                continue
            modname = f'{pkgname}.{entry.name}'
            if modname.endswith('.py'):
                yield modname[:-3], entry.path, False
            elif entry.is_dir():
                pyfile = os.path.join(entry.path, '__init__.py')
                # We ignore namespace packages.
                if os.path.exists(pyfile):
                    yield modname, pyfile, True
                    if recursive:
                        yield from _iter_submodules(modname, entry.path)

    return _iter_submodules(pkgname, pkgdir)


def _resolve_modname_matcher(match, rootdir=None):
    if isinstance(match, str):
        if match.startswith('**.'):
            recursive = True
            pat = match[3:]
            assert match
        else:
            recursive = False
            pat = match

        if pat == '*':
            def match_modname(modname):
                return True, recursive
        else:
            raise NotImplementedError(match)
    elif callable(match):
        match_modname = match(rootdir)
    else:
        raise ValueError(f'unsupported matcher {match!r}')
    return match_modname


def _resolve_module(modname, pathentry=STDLIB_DIR, ispkg=False):
    assert pathentry, pathentry
    pathentry = os.path.normpath(pathentry)
    assert os.path.isabs(pathentry)
    if ispkg:
        return os.path.join(pathentry, *modname.split('.'), '__init__.py')
    return os.path.join(pathentry, *modname.split('.')) + '.py'


#######################################
# regenerating dependent files

def find_marker(lines, marker, file):
    for pos, line in enumerate(lines):
        if marker in line:
            return pos
    raise Exception(f"Can't find {marker!r} in file {file}")


def replace_block(lines, start_marker, end_marker, replacements, file):
    start_pos = find_marker(lines, start_marker, file)
    end_pos = find_marker(lines, end_marker, file)
    if end_pos <= start_pos:
        raise Exception(f"End marker {end_marker!r} "
                        f"occurs before start marker {start_marker!r} "
                        f"in file {file}")
    replacements = [line.rstrip() + '\n' for line in replacements]
    return lines[:start_pos + 1] + replacements + lines[end_pos:]


class UniqueList(list):
    def __init__(self):
        self._seen = set()

    def append(self, item):
        if item in self._seen:
            return
        super().append(item)
        self._seen.add(item)


def regen_frozen(modules):
    headerlines = []
    parentdir = os.path.dirname(FROZEN_FILE)
    for src in _iter_sources(modules):
        # Adding a comment to separate sections here doesn't add much,
        # so we don't.
        header = relpath_for_posix_display(src.frozenfile, parentdir)
        headerlines.append(f'#include "{header}"')

    externlines = UniqueList()
    bootstraplines = []
    stdliblines = []
    testlines = []
    aliaslines = []
    indent = '    '
    lastsection = None
    for mod in modules:
        if mod.isbootstrap:
            lines = bootstraplines
        elif mod.section == TESTS_SECTION:
            lines = testlines
        else:
            lines = stdliblines
            if mod.section != lastsection:
                if lastsection is not None:
                    lines.append('')
                lines.append(f'/* {mod.section} */')
            lastsection = mod.section

        pkg = 'true' if mod.ispkg else 'false'
        size = f"(int)sizeof({mod.symbol})"
        if frozen_struct_has_get_code():
            line = f'{{"{mod.name}", {mod.symbol}, {size}, {pkg}, NULL}},'
        else:
            line = f'{{"{mod.name}", {mod.symbol}, {size}, {pkg}}},'
        lines.append(line)

        if mod.isalias:
            if not mod.orig:
                entry = '{"%s", NULL},' % (mod.name,)
            elif mod.source.ispkg:
                entry = '{"%s", "<%s"},' % (mod.name, mod.orig)
            else:
                entry = '{"%s", "%s"},' % (mod.name, mod.orig)
            aliaslines.append(indent + entry)

    for lines in (bootstraplines, stdliblines, testlines):
        # TODO: Is this necessary any more?
        if lines and not lines[0]:
            del lines[0]
        for i, line in enumerate(lines):
            if line:
                lines[i] = indent + line

    print(f'# Updating {os.path.relpath(FROZEN_FILE)}')
    lines = read_text_lines(FROZEN_FILE)
    # TODO: Use more obvious markers, e.g.
    # $START GENERATED FOOBAR$ / $END GENERATED FOOBAR$
    lines = replace_block(
        lines,
        "/* Includes for frozen modules: */",
        "/* End includes */",
        headerlines,
        FROZEN_FILE,
    )
    lines = replace_block(
        lines,
        "static const struct _frozen bootstrap_modules[] =",
        "/* bootstrap sentinel */",
        bootstraplines,
        FROZEN_FILE,
    )
    lines = replace_block(
        lines,
        "static const struct _frozen stdlib_modules[] =",
        "/* stdlib sentinel */",
        stdliblines,
        FROZEN_FILE,
    )
    lines = replace_block(
        lines,
        "static const struct _frozen test_modules[] =",
        "/* test sentinel */",
        testlines,
        FROZEN_FILE,
    )
    lines = replace_block(
        lines,
        "const struct _module_alias aliases[] =",
        "/* aliases sentinel */",
        aliaslines,
        FROZEN_FILE,
    )
    write_text_lines(FROZEN_FILE, lines)


def regen_makefile(modules):
    pyfiles = []
    frozenfiles = []
    rules = ['']
    for src in _iter_sources(modules):
        frozen_header = relpath_for_posix_display(src.frozenfile, ROOT_DIR)
        frozenfiles.append(f'\t\t{frozen_header} \\')
        #print(frozen_header)
        pyfile = relpath_for_posix_display(src.pyfile, ROOT_DIR)
        pyfiles.append(f'\t\t{pyfile} \\')

        if src.isbootstrap:
            freezecmd = '$(FREEZE_MODULE_BOOTSTRAP)'
            freezedep = '$(FREEZE_MODULE_BOOTSTRAP_DEPS)'
        else:
            freezecmd = '$(FREEZE_MODULE)'
            freezedep = '$(FREEZE_MODULE_DEPS)'

        freeze = (f'{freezecmd} {src.frozenid} '
                    f'$(srcdir)/{pyfile} {frozen_header}')
        rules.extend([
            f'{frozen_header}: {pyfile} {freezedep}',
            f'\t{freeze}',
            '',
        ])
    pyfiles[-1] = pyfiles[-1].rstrip(" \\")
    frozenfiles[-1] = frozenfiles[-1].rstrip(" \\")

    print(f'# Updating {os.path.relpath(MAKEFILE)}')
    lines = read_text_lines(MAKEFILE)
    lines = replace_block(
        lines,
        "FROZEN_FILES_IN =",
        "# End FROZEN_FILES_IN",
        pyfiles,
        MAKEFILE,
    )
    lines = replace_block(
        lines,
        "FROZEN_FILES_OUT =",
        "# End FROZEN_FILES_OUT",
        frozenfiles,
        MAKEFILE,
    )
    lines = replace_block(
        lines,
        "# BEGIN: freezing modules",
        "# END: freezing modules",
        rules,
        MAKEFILE,
    )
    write_text_lines(MAKEFILE, lines)


def regen_pcbuild(modules):
    projlines = []
    filterlines = []
    corelines = []
    for src in _iter_sources(modules):
        pyfile = relpath_for_windows_display(src.pyfile, ROOT_DIR)
        header = relpath_for_windows_display(src.frozenfile, ROOT_DIR)
        intfile = ntpath.splitext(ntpath.basename(header))[0] + '.g.h'
        projlines.append(f'    <None Include="..\\{pyfile}">')
        projlines.append(f'      <ModName>{src.frozenid}</ModName>')
        projlines.append(f'      <IntFile>$(IntDir){intfile}</IntFile>')
        projlines.append(f'      <OutFile>$(GeneratedFrozenModulesDir){header}</OutFile>')
        projlines.append(f'    </None>')

        filterlines.append(f'    <None Include="..\\{pyfile}">')
        filterlines.append('      <Filter>Python Files</Filter>')
        filterlines.append('    </None>')

    print(f'# Updating {os.path.relpath(PCBUILD_PROJECT)}')
    lines = read_text_lines(PCBUILD_PROJECT)
    lines = replace_block(
        lines,
        '<!-- BEGIN frozen modules -->',
        '<!-- END frozen modules -->',
        projlines,
        PCBUILD_PROJECT,
    )
    write_text_lines(PCBUILD_PROJECT, lines)
    print(f'# Updating {os.path.relpath(PCBUILD_FILTERS)}')
    lines = read_text_lines(PCBUILD_FILTERS)
    lines = replace_block(
        lines,
        '<!-- BEGIN frozen modules -->',
        '<!-- END frozen modules -->',
        filterlines,
        PCBUILD_FILTERS,
    )
    write_text_lines(PCBUILD_FILTERS, lines)


#######################################
# the script

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--step', type=int, default=0)
    args = parser.parse_args()
    if args.step == 0:
        generate_frozen_files(ROOT_DIR)
    elif args.step == 1:
        modules = list(parse_frozen_specs())
        regen_makefile(modules)
        regen_pcbuild(modules)
        regen_frozen(modules)

if __name__ == '__main__':
    main()
