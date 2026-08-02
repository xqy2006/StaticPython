# Experimental tkinter ZipFS pack

The `tkinter-experimental` profile builds `_tkinter`, Tcl, and Tk as static
libraries and packages the Tcl/Tk script libraries in a read-only ZipFS image.
The generated executable mounts that image from its own linked data before
`Tcl_Init`; it does not create or extract a Tcl/Tk directory at runtime.

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
`Tk_Init`. It also pre-seeds `auto_path` with only the mounted Tcl directory and
clears `tcl_pkgPath` before initialization, preventing `TCLLIBPATH` from being
adopted. Immediately after `Tcl_Init`, it restores that exact path boundary and
clears Tcl module (`.tm`) search roots derived from the executable and
`TCL*_TM_PATH` environment variables. The executable's adjacent `lib` and
compiled installation paths therefore cannot supply scripts. The build fails
if those upstream anchors drift. Dedicated behavior tests deliberately poison
all of these environment variables with an external directory and require the
effective Tcl/Tk search paths to remain entirely inside the mounted ZipFS.

`Lib/tkinter` remains excluded from the base runtime SDK. Selecting this pack
writes `PCbuild/staticpython_optional_frozen_trees.txt`, which enables freezing
the tkinter Python package for that build only. The pack resource manifest
contains the deterministic ZipFS archive; Tcl/Tk source and build files are not
exposed as runtime resources.

## Current support and verification

The initial implementation supports Windows x64 Release builds on CPython 3.12
and newer because those sources contain Tcl 9 `Tcl_Size` compatibility. CPython
3.11 is deliberately rejected until its `_tkinter` compatibility port is
implemented and tested.

`.github/workflows/tkinter-zipfs-experiment.yml` builds an audited CPython
runtime SDK, builds only the tkinter pack, links both into a provisional
executable, runs Tcl and Tk/ttk behavior tests, and audits PE imports. The pack
stays outside `full` and release shards until that dedicated workflow is green.

Local deterministic tests can be run with:

```powershell
python .\scripts\test_tcltk_zipfs.py
```
