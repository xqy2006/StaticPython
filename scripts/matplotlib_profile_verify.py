from __future__ import annotations

import importlib.util
import io
import os
import tempfile


def _assert_builtin(module_name: str) -> None:
    spec = importlib.util.find_spec(module_name)
    assert spec is not None, module_name
    assert spec.origin == "built-in", (module_name, spec.origin)


def test_numpy() -> None:
    import numpy as np

    matrix = np.arange(6, dtype=np.int64).reshape(2, 3)
    vector = np.array([10, 20, 30], dtype=np.int64)
    assert matrix.shape == (2, 3)
    assert (matrix + vector).tolist() == [[10, 21, 32], [13, 24, 35]]
    assert np.dot(np.array([1, 2, 3]), np.array([4, 5, 6])) == 32


def test_pillow() -> None:
    from PIL import Image, ImageDraw

    _assert_builtin("PIL._imaging")
    image = Image.new("RGB", (8, 8), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((1, 1, 6, 6), fill=(20, 80, 200))

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    payload = buffer.getvalue()
    assert payload.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(payload) > 64


def test_contourpy() -> None:
    import contourpy
    import numpy as np
    from contourpy.util import build_config

    _assert_builtin("contourpy._contourpy")
    z = np.array(
        [
            [0.0, 0.5, 1.0],
            [0.5, 1.0, 1.5],
            [1.0, 1.5, 2.0],
        ],
        dtype=np.float64,
    )
    generator = contourpy.contour_generator(z=z, name="serial")
    lines = generator.lines(0.75)
    assert lines
    assert all(line.shape[1] == 2 for line in lines)
    assert build_config()["contourpy_version"] == contourpy.__version__


def test_kiwisolver() -> None:
    import kiwisolver as kiwi

    _assert_builtin("kiwisolver._cext")
    x = kiwi.Variable("x")
    y = kiwi.Variable("y")
    solver = kiwi.Solver()
    solver.addConstraint(x + y == 10)
    solver.addConstraint(x - y == 2)
    solver.updateVariables()
    assert round(x.value(), 7) == 6.0
    assert round(y.value(), 7) == 4.0


def test_matplotlib() -> None:
    os.environ.setdefault("MPLCONFIGDIR", tempfile.mkdtemp(prefix="staticpython-mpl-"))

    import matplotlib

    matplotlib.use("Agg", force=True)

    for name in (
        "matplotlib.ft2font",
        "matplotlib._path",
        "matplotlib._image",
        "matplotlib._qhull",
        "matplotlib._tri",
        "matplotlib._c_internal_utils",
        "matplotlib.backends._backend_agg",
    ):
        _assert_builtin(name)

    from matplotlib import ft2font
    from matplotlib import pyplot as plt

    assert ft2font.__freetype_version__ == "2.6.1"
    assert ft2font.__freetype_build_type__ == "local"
    assert matplotlib.get_data_path().endswith("mpl-data")

    fig, ax = plt.subplots(figsize=(2, 1.5), dpi=80)
    ax.plot([0, 1, 2], [0, 1, 0], marker="o")
    ax.set_title("StaticPython")
    ax.fill_between([0, 1, 2], [0, 0.25, 0], alpha=0.2)

    buffer = io.BytesIO()
    fig.savefig(buffer, format="png")
    plt.close(fig)

    payload = buffer.getvalue()
    assert payload.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(payload) > 1000


def main() -> int:
    tests = [
        ("numpy", test_numpy),
        ("pillow", test_pillow),
        ("contourpy", test_contourpy),
        ("kiwisolver", test_kiwisolver),
        ("matplotlib", test_matplotlib),
    ]
    for name, test in tests:
        print(f"[staticpython-matplotlib-verify] {name}: running", flush=True)
        test()
        print(f"[staticpython-matplotlib-verify] {name}: passed", flush=True)
    print(f"[staticpython-matplotlib-verify] all {len(tests)} smoke test(s) passed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
