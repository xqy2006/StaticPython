from __future__ import annotations

from libs import pypi_library


LIBRARY_INTEGRATION = pypi_library(
    name="referencing",
    release_version="0.37.0",
    source_archive_sha256_by_version={
        "0.37.0": "44aefc3142c5b842538163acb373e24cce6632bd54bdb01b21ad5863489f50d8",
    },
    source_mapping={
        "referencing": "Lib/referencing",
    },
    python_packages=["referencing"],
    license_expression="MIT",
    smoke_tests=[
        {
            "name": "opaque-resource-registry",
            "kind": "inline",
            "code": (
                "from referencing import Registry, Resource; "
                "registry=Registry().with_resource('urn:staticpython:test', "
                "Resource.opaque({'ok': True})); "
                "assert registry.contents('urn:staticpython:test') == {'ok': True}"
            ),
        }
    ],
)
