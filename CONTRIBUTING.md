# Contributing

StaticPython patches CPython source trees in place, so changes should stay small, traceable, and easy to verify.

## Guidelines

- Keep generated files out of the repository. Source archives belong in `downloads/`, temporary materialized packages belong in `.vendor-stage/`, and build outputs belong in `dist/`.
- Do not add binary `.lib` assets when a dependency can be built from source. Prefer stable upstream release archives.
- Put each third-party library integration under `Lib/<name>/setup.py`.
- Put library-specific patches under `Lib/<name>/**/*.patch` or implement feature-based source transforms in that library's `setup.py`.
- Update `config.json` when adding or removing selectable build profiles.
- Verify profile changes on CPython 3.13 first.

## Quick Checks

```powershell
python -m py_compile .\build.py .\verify.py .\libs.py .\patch.py .\refresh.py
python .\build.py --help
python .\verify.py --help
```

For build-profile checks without compiling:

```powershell
python .\build.py --source-archive-path D:\cpython-3.13.zip --profile stdlib --skip-get-externals --skip-build
python .\build.py --source-archive-path D:\cpython-3.13.zip --profile full --skip-get-externals --skip-build
```

## Historical dependency locks

Historical package validation must generate a target-specific dependency lock before building:

```powershell
python .\scripts\build_library_contract_config.py `
  --library jupyterlab `
  --version 0.31.0 `
  --target-python-version 3.11.16 `
  --output-config .\dist\jupyterlab-0.31.0-cp311.json
```

The historical solver treats the requested root version as immutable, prefers current integration versions for transitive packages, and backtracks only when their metadata conflicts. The generated config pins the complete closure and records source URLs and SHA-256 values, the target runtime ABI, and the active MSVC/Windows SDK fingerprint. Never hand-edit this lock or copy it between target Python/toolchain combinations.
