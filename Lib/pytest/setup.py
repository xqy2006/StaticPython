from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="pytest",
    source_mapping={
        "pytest": "Lib/pytest",
        "_pytest": "Lib/_pytest",
    },
    verification_steps=[
        inline_verification_step(
            "pytest-smoke",
            """
import tempfile
from pathlib import Path

import pytest

with tempfile.TemporaryDirectory() as temp_dir:
    test_file = Path(temp_dir) / "test_staticpython.py"
    test_file.write_text("def test_ok():\\n    assert 1 + 1 == 2\\n", encoding="utf-8")
    result = pytest.main([str(test_file), "-q", "-p", "no:cacheprovider"])
    assert result == 0
""",
            timeout=300,
        )
    ],
)
