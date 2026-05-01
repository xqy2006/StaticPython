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
    root = Path(temp_dir)
    (root / "conftest.py").write_text(
        "import pytest\\n@pytest.fixture()\\ndef answer():\\n    return 42\\n",
        encoding="utf-8",
    )
    (root / "test_staticpython.py").write_text(
        "import pytest\\n\\n@pytest.mark.parametrize('value', [1, 2, 3])\\ndef test_ok(answer, value):\\n    assert answer + value in {43, 44, 45}\\n",
        encoding="utf-8",
    )
    result = pytest.main([str(root), "-q", "-p", "no:cacheprovider"])
    assert result == 0
""",
            timeout=300,
        )
    ],
)
