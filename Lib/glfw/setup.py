from libs import pypi_library, replace_regex_once, transform_source_text


def _patch_glfw_library_loader(context) -> None:
    def patch(text: str) -> str:
        if "import hashlib" not in text:
            text = replace_regex_once(
                text,
                r"(?m)^import ctypes\s*$",
                "import ctypes\nimport hashlib\nimport pkgutil\nimport tempfile",
                label="glfw loader imports",
            )
        helper = r'''

def _staticpython_materialize_package_dll(filename, directory=None):
    data = pkgutil.get_data(__package__ or 'glfw', filename)
    if data is None:
        return None
    if directory is None:
        digest = hashlib.sha256(data).hexdigest()[:16]
        directory = os.path.join(tempfile.gettempdir(), 'staticpython-glfw-' + digest)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, filename)
    if not os.path.exists(path) or os.path.getsize(path) != len(data):
        temporary = path + '.tmp.' + str(os.getpid())
        with open(temporary, 'wb') as handle:
            handle.write(data)
        os.replace(temporary, path)
    return path
'''
        if "_staticpython_materialize_package_dll" not in text:
            text = replace_regex_once(
                text,
                r"(?m)^(def _find_library_candidates\()",
                helper.lstrip("\n") + "\n\\1",
                label="glfw staticpython dll helper anchor",
            )
        resource_loader = r'''
    # try StaticPython embedded package resources
    if glfw is None:
        try:
            glfw_path = _staticpython_materialize_package_dll('glfw3.dll')
            msvcr_path = _staticpython_materialize_package_dll(
                'msvcr120.dll',
                os.path.dirname(glfw_path) if glfw_path else None,
            )
            if msvcr_path:
                globals()['_staticpython_msvcr120'] = ctypes.CDLL(msvcr_path)
            if glfw_path:
                glfw = ctypes.CDLL(glfw_path)
        except OSError:
            pass
'''
        if "try StaticPython embedded package resources" not in text:
            text = replace_regex_once(
                text,
                r"(?m)^    # try package directory\s*$",
                resource_loader.rstrip("\n") + "\n\n    # try package directory",
                label="glfw windows package loader",
            )
        return text

    transform_source_text(context, "Lib/glfw/library.py", patch)


LIBRARY_INTEGRATION = pypi_library(
    name="glfw",
    source_mapping={
        "glfw": "Lib/glfw",
    },
    materialized_paths=[
        "Lib/glfw",
    ],
    python_packages=["glfw"],
    post_patch_hooks=[_patch_glfw_library_loader],
)
