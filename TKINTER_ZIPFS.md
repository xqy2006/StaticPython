# Experimental tkinter ZipFS pack

The `tkinter-experimental` profile builds `_tkinter`, Tcl, and Tk as static
libraries and packages the Tcl/Tk script libraries in a read-only ZipFS image.
The generated executable mounts that image from its own linked data before
`Tcl_Init`; it does not create or extract a Tcl/Tk directory at runtime.
Tk uses Tcl's supported stubs ABI, so the pack also carries the static
`tclstub.lib` archive and links it between Tk and the Tcl core archive. No Tcl
shell executable produced as an intermediate build dependency is exported.

## Pinned inputs

- Tcl 9.0.4: `tcltk/tcl@c655b4770b1d6d32a8cbffd6cef59db6029fe19e`
- Tk 9.0.4: `tcltk/tk@584f8fcf62c320d7c341e77171188cb4d79c3725`
- Both codeload archives are checked against their committed SHA-256 digest.
- Tcl and Tk `license.terms` files are copied into every exported pack. The
  CPython `LICENSE` is included for the frozen tkinter sources, and the
  integration also carries the licenses for Tcl's statically compiled zlib,
  LibTomMath, and Info-ZIP minizip-derived code. Its complete SPDX expression
  is `Python-2.0 AND TCL AND Zlib AND Unlicense AND Info-ZIP`.

The ZipFS includes Tcl initialization, encodings and time-zone data plus Tk and
ttk scripts, native themes, messages, images, and fonts shipped in the upstream
script library. Tcl `dde`, `registry`, and `tcltest`, and Tk demos are excluded
from the first experimental pack.

## Isolation properties

StaticPython removes CPython `_tkinter`'s `TCL_LIBRARY` environment and
filesystem discovery code with strict patch anchors. `Tcl_AppInit` mounts the
embedded archive with `TclZipfs_MountBuffer`, then sets `tcl_library` and
`tk_library` to exact `//zipfs:/staticpython/...` paths before `Tcl_Init` and
`Tk_Init`. A mutex-protected process-local mount flag prevents repeated mounts;
the code never probes the ZipFS-looking path through the host filesystem before
the in-memory filesystem is registered. It also pre-seeds `auto_path` with only
the mounted Tcl directory and
clears `tcl_pkgPath` before initialization, preventing `TCLLIBPATH` from being
adopted. Immediately after `Tcl_Init`, it restores that exact path boundary and
explicitly loads `tm.tcl` from the mounted archive and clears Tcl module (`.tm`)
search roots. The locked `tm.tcl` initialization is patched through a strict
single-match anchor so it never adds executable-relative directories or
`TCL*_TM_PATH` environment paths. The executable's adjacent `lib` and compiled
installation paths therefore cannot supply scripts. The build fails if those
upstream anchors drift. Dedicated behavior tests deliberately poison all of
these environment variables with an external directory and require the
effective Tcl/Tk search paths to remain entirely inside the mounted ZipFS.
After `Tk_Init`, a second native hook restores `tcl_library`, `tk_library`, and
`auto_path` to the exact embedded Tcl, Tk, and ttk directories so Tk's own
initialization cannot leave broader search locations behind. Tcl's process-wide
encoding search path is likewise replaced through `Tcl_SetEncodingSearchPath`
with the single embedded `encoding` directory.

`Lib/tkinter` remains excluded from the base runtime SDK. Selecting this pack
writes `PCbuild/staticpython_optional_frozen_trees.txt`, which enables freezing
the tkinter Python package for that build only. The pack resource manifest
contains the deterministic ZipFS archive; Tcl/Tk source and build files are not
exposed as runtime resources.

## Current support and verification

The implementation targets Windows x64 Release builds on CPython 3.11 through
3.15. CPython 3.12 and newer already contain Tcl 9 `Tcl_Size` compatibility;
for CPython 3.11 the integration strictly and idempotently applies the upstream
CPython gh-112672 backport (`ec139c8fae2064e5f1413dad0aadc1b83daf90d8`) before
the no-extraction discovery patch. Missing, duplicated, partial, or drifted
anchors fail the build.

`.github/workflows/tkinter-zipfs-experiment.yml` builds an audited CPython
runtime SDK, builds only the tkinter pack, links both into a provisional
executable, runs Tcl and Tk/ttk behavior tests, and audits PE imports for the
latest tags in all five target series. A manual dispatch may select one exact
tag for focused diagnosis. The pack stays outside `full` and release shards
until that dedicated workflow is green.

Local deterministic tests can be run with:

```powershell
python .\scripts\test_tcltk_zipfs.py
```
