from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from nbconvert.exporters.base import get_export_names, get_exporter


def main() -> int:
    export_names = set(get_export_names())
    assert {"html", "notebook", "script"} <= export_names
    assert get_exporter("html").__name__ == "HTMLExporter"
    assert get_exporter("script").__name__ == "ScriptExporter"

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        notebook_path = root / "demo.ipynb"
        notebook_path.write_text(
            json.dumps(
                {
                    "cells": [
                        {"cell_type": "markdown", "metadata": {}, "source": ["# StaticPython"]},
                        {
                            "cell_type": "code",
                            "execution_count": None,
                            "metadata": {},
                            "outputs": [],
                            "source": ["answer = 40 + 2\nanswer"],
                        },
                    ],
                    "metadata": {
                        "kernelspec": {
                            "display_name": "Python 3",
                            "language": "python",
                            "name": "python3",
                        }
                    },
                    "nbformat": 4,
                    "nbformat_minor": 5,
                }
            ),
            encoding="utf-8",
        )

        completed = subprocess.run(
            [sys.executable, "-m", "nbconvert", "--to", "html", "--execute", str(notebook_path)],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
        assert completed.returncode == 0, completed.stderr

        html_path = root / "demo.html"
        assert html_path.exists()
        html_body = html_path.read_text(encoding="utf-8")
        assert "StaticPython" in html_body
        assert "42" in html_body

        completed = subprocess.run(
            [sys.executable, "-m", "nbconvert", "--to", "script", str(notebook_path)],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
        assert completed.returncode == 0, completed.stderr

        script_candidates = [root / "demo.py", root / "demo.txt"]
        script_path = next((candidate for candidate in script_candidates if candidate.exists()), None)
        assert script_path is not None
        script_body = script_path.read_text(encoding="utf-8")
        assert "answer = 40 + 2" in script_body

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
