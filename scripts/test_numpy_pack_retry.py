from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def load_numpy_setup():
    module_path = REPO_ROOT / "Lib" / "numpy" / "setup.py"
    spec = importlib.util.spec_from_file_location(
        "staticpython_numpy_setup_retry_test",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


numpy_setup = load_numpy_setup()


class NumpyMesonRetryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.messages: list[str] = []
        self.context = SimpleNamespace(
            source_root=Path("C:/staticpython/cpython"),
            platform="x64",
            version_info=(3, 13, 14),
            log=self.messages.append,
        )

    def test_missing_project_is_retried_sequentially(self) -> None:
        failed = subprocess.CompletedProcess([], 1, "batch failed", "")
        expected_link_failure = subprocess.CompletedProcess(
            [],
            1,
            "shared-module link failed",
            "",
        )
        missing_project = numpy_setup.NUMPY_RANDOM_BOUNDED_INTEGERS_PROJECT_NAME

        with (
            mock.patch.object(numpy_setup, "_numpy_build_env", return_value={}),
            mock.patch.object(
                numpy_setup,
                "_run_numpy_ninja",
                side_effect=[failed, expected_link_failure],
            ) as run_ninja,
            mock.patch.object(
                numpy_setup,
                "_wait_for_expected_numpy_outputs",
                side_effect=[
                    ["_bounded_integers.cp313-win_amd64.pyd.p/*.obj"],
                    [],
                ],
            ),
            mock.patch.object(
                numpy_setup,
                "_missing_numpy_projects",
                return_value=[missing_project],
            ),
            mock.patch.object(
                numpy_setup,
                "numpy_project_object_dir",
            ) as object_dir,
        ):
            object_dir.return_value.glob.return_value = iter([Path("module.obj")])
            numpy_setup._compile_numpy_core(self.context)

        self.assertEqual(run_ninja.call_count, 2)
        retry_call = run_ninja.call_args_list[1]
        self.assertEqual(retry_call.kwargs["jobs"], 1)
        self.assertEqual(
            retry_call.kwargs["targets"],
            [numpy_setup.numpy_project_target_name(self.context, missing_project)],
        )
        self.assertTrue(
            any("retrying those projects sequentially" in message for message in self.messages)
        )
        self.assertTrue(
            any("continuing with builtin static archives" in message for message in self.messages)
        )

    def test_missing_project_after_retry_fails_closed_with_retry_log(self) -> None:
        failed = subprocess.CompletedProcess([], 1, "batch failed", "batch stderr")
        retry_failed = subprocess.CompletedProcess(
            [],
            1,
            "bounded retry stdout",
            "bounded retry stderr",
        )
        missing_project = numpy_setup.NUMPY_RANDOM_BOUNDED_INTEGERS_PROJECT_NAME

        with (
            mock.patch.object(numpy_setup, "_numpy_build_env", return_value={}),
            mock.patch.object(
                numpy_setup,
                "_run_numpy_ninja",
                side_effect=[failed, retry_failed],
            ),
            mock.patch.object(
                numpy_setup,
                "_wait_for_expected_numpy_outputs",
                side_effect=[
                    ["_bounded_integers.cp313-win_amd64.pyd.p/*.obj"],
                    ["_bounded_integers.cp313-win_amd64.pyd.p/*.obj"],
                ],
            ),
            mock.patch.object(
                numpy_setup,
                "_missing_numpy_projects",
                return_value=[missing_project],
            ),
            mock.patch.object(
                numpy_setup,
                "numpy_project_object_dir",
            ) as object_dir,
        ):
            object_dir.return_value.name = "_bounded_integers.cp313-win_amd64.pyd.p"
            object_dir.return_value.glob.return_value = iter(())
            with self.assertRaisesRegex(
                RuntimeError,
                "NumPy Meson compile failed after sequential retry",
            ) as error:
                numpy_setup._compile_numpy_core(self.context)

        self.assertIn("failed project: numpy.random._bounded_integers", str(error.exception))
        self.assertIn("bounded retry stdout", str(error.exception))
        self.assertIn("bounded retry stderr", str(error.exception))

    def test_random_project_requires_initializer_object_and_symbol(self) -> None:
        project = numpy_setup.NUMPY_RANDOM_PHILOX_PROJECT_NAME
        symbol = numpy_setup.NUMPY_RANDOM_INITIALIZER_SYMBOLS[project]
        with tempfile.TemporaryDirectory() as temp_dir:
            object_dir = Path(temp_dir)
            context = SimpleNamespace(version_info=(3, 11, 16))
            required_name = numpy_setup._numpy_project_required_object_name(context, project)
            assert required_name is not None
            (object_dir / "src_philox_philox.c.obj").write_bytes(b"support only")
            with mock.patch.object(
                numpy_setup,
                "numpy_project_object_dir",
                return_value=object_dir,
            ):
                self.assertFalse(numpy_setup._numpy_project_objects_complete(context, project))
                (object_dir / required_name).write_bytes(b"missing initializer")
                self.assertFalse(numpy_setup._numpy_project_objects_complete(context, project))
                (object_dir / required_name).write_bytes(symbol.encode("ascii"))
                self.assertTrue(numpy_setup._numpy_project_objects_complete(context, project))

    def test_random_archive_fails_closed_when_initializer_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = SimpleNamespace(
                source_root=root,
                platform="x64",
                version_info=(3, 11, 16),
                log=self.messages.append,
            )
            for project in numpy_setup.NUMPY_RANDOM_PROJECT_NAMES:
                object_dir = numpy_setup.numpy_project_object_dir(context, project)
                object_dir.mkdir(parents=True, exist_ok=True)
                required_name = numpy_setup._numpy_project_required_object_name(context, project)
                assert required_name is not None
                (object_dir / required_name).write_bytes(
                    numpy_setup.NUMPY_RANDOM_INITIALIZER_SYMBOLS[project].encode("ascii")
                )
            npyrandom = numpy_setup.numpy_npyrandom_lib(context)
            npyrandom.parent.mkdir(parents=True, exist_ok=True)
            npyrandom.write_bytes(b"support")
            output = (
                numpy_setup.get_pcbuild_output_dir(context.source_root, context.platform)
                / f"{numpy_setup.NUMPY_RANDOM_BUILTIN_LIBRARY_NAME}.lib"
            )

            def fake_run(_log, _command, **_kwargs):
                output.write_bytes(
                    b"".join(
                        symbol.encode("ascii")
                        for project, symbol in numpy_setup.NUMPY_RANDOM_INITIALIZER_SYMBOLS.items()
                        if project != numpy_setup.NUMPY_RANDOM_PHILOX_PROJECT_NAME
                    )
                )

            with mock.patch.object(numpy_setup, "run", side_effect=fake_run):
                with self.assertRaisesRegex(RuntimeError, "PyInit__philox"):
                    numpy_setup._archive_numpy_random_builtins(context)


if __name__ == "__main__":
    unittest.main(verbosity=2)
