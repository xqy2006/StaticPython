# Third-party notices

StaticPython is build and integration tooling. It does not change the license
of CPython or any integrated dependency.

- CPython is distributed under the Python Software Foundation License. Every
  runtime SDK includes the exact CPython `LICENSE` from the selected source.
- Each optional library pack must include the license files declared by its
  `LibraryIntegration` and a machine-readable license expression in
  `pack.json`.
- Generated release indexes contain hashes and source provenance, but do not
  replace the license texts shipped in SDK and pack archives.

Before publishing a new pack, its source, license expression, notice files,
and static-linking obligations must be reviewed. Qt/PySide static packs are
not public release assets unless the publisher has a suitable commercial
license or satisfies the applicable LGPL relinking obligations.
