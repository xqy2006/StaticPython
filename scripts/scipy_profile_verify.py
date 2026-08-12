from __future__ import annotations

import numpy as np
from io import BytesIO


def test_scipy_import() -> None:
    import scipy
    from scipy.version import version as source_version

    assert scipy.__version__ == source_version


def test_scipy_fft() -> None:
    import scipy.fft

    data = np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float64)
    transformed = scipy.fft.fft(data)
    restored = scipy.fft.ifft(transformed)
    np.testing.assert_allclose(restored.real, data, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(restored.imag, 0.0, rtol=1e-12, atol=1e-12)

    dct = scipy.fft.dct(data, norm="ortho")
    restored_dct = scipy.fft.idct(dct, norm="ortho")
    np.testing.assert_allclose(restored_dct, data, rtol=1e-12, atol=1e-12)


def test_scipy_constants() -> None:
    import scipy.constants

    assert scipy.constants.pi == np.pi
    assert scipy.constants.speed_of_light == scipy.constants.c
    assert scipy.constants.golden == scipy.constants.golden_ratio
    np.testing.assert_allclose(
        scipy.constants.convert_temperature([0.0, 100.0], "Celsius", "Kelvin"),
        np.array([273.15, 373.15]),
        rtol=0.0,
        atol=1e-12,
    )


def test_scipy_fftpack() -> None:
    import scipy.fftpack

    data = np.array([1.0, 3.0, 2.0, 5.0], dtype=np.float64)
    transformed = scipy.fftpack.fft(data)
    restored = scipy.fftpack.ifft(transformed)
    np.testing.assert_allclose(restored.real, data, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(restored.imag, 0.0, rtol=1e-12, atol=1e-12)

    dct = scipy.fftpack.dct(data, norm="ortho")
    restored_dct = scipy.fftpack.idct(dct, norm="ortho")
    np.testing.assert_allclose(restored_dct, data, rtol=1e-12, atol=1e-12)

    freqs = scipy.fftpack.rfftfreq(data.size, d=0.5)
    np.testing.assert_allclose(freqs, np.array([0.0, 0.5, 0.5, 1.0]), rtol=0.0, atol=1e-12)


def test_scipy_io_wavfile() -> None:
    from scipy.io import wavfile

    rate = 16000
    samples = np.array([0, 1024, -1024, 2048, -2048], dtype=np.int16)
    payload = BytesIO()
    wavfile.write(payload, rate, samples)
    payload.seek(0)
    read_rate, read_samples = wavfile.read(payload)
    assert read_rate == rate
    np.testing.assert_array_equal(read_samples, samples)


def test_scipy_io_arff() -> None:
    from io import StringIO

    from scipy.io.arff import loadarff

    payload = """
@RELATION demo

@ATTRIBUTE length NUMERIC
@ATTRIBUTE color {red,green,blue}

@DATA
1.5,red
2.0,green
?,blue
""".strip()
    data, meta = loadarff(StringIO(payload))
    assert meta.name == "demo"
    np.testing.assert_allclose(data["length"][:2], np.array([1.5, 2.0]), rtol=0.0, atol=1e-12)
    assert np.isnan(data["length"][2])
    assert data["color"].tolist() == [b"red", b"green", b"blue"]


def test_scipy_integrate() -> None:
    import scipy.integrate

    x = np.linspace(0.0, 1.0, 11)
    y = x * x

    trap = scipy.integrate.trapezoid(y, x=x)
    simp = scipy.integrate.simpson(y, x=x)
    cumtrap = scipy.integrate.cumulative_trapezoid(y, x=x, initial=0.0)
    cumsimp = scipy.integrate.cumulative_simpson(y, x=x, initial=0.0)
    romb_x = np.linspace(0.0, 1.0, 9)
    romb_y = romb_x * romb_x
    romb = scipy.integrate.romb(romb_y, dx=romb_x[1] - romb_x[0])
    weights, error = scipy.integrate.newton_cotes(2, 1)

    np.testing.assert_allclose(trap, 1.0 / 3.0, rtol=0.0, atol=5e-3)
    np.testing.assert_allclose(simp, 1.0 / 3.0, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(cumtrap[-1], trap, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(cumsimp[-1], simp, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(romb, 1.0 / 3.0, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(weights, np.array([1.0, 4.0, 1.0]) / 3.0, rtol=0.0, atol=1e-12)
    assert np.isfinite(error)


def test_scipy_special() -> None:
    import scipy.special

    np.testing.assert_allclose(scipy.special.erf(0.0), 0.0, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(scipy.special.erfc(0.0), 1.0, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(scipy.special.i0(0.0), 1.0, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(scipy.special.gammaln(6.0), np.log(120.0), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(scipy.special.expit(0.0), 0.5, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(scipy.special.logit(0.5), 0.0, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(scipy.special.ndtr(0.0), 0.5, rtol=0.0, atol=1e-12)
    nodes, weights = scipy.special.roots_legendre(3)
    np.testing.assert_allclose(np.sum(weights), 2.0, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(nodes, np.array([-np.sqrt(3.0 / 5.0), 0.0, np.sqrt(3.0 / 5.0)]), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(scipy.special.logsumexp([1.0, 2.0, 3.0]), np.log(np.exp(1.0) + np.exp(2.0) + np.exp(3.0)), rtol=0.0, atol=1e-12)


def test_scipy_linalg() -> None:
    import scipy.linalg

    matrix = np.array([[3.0, 1.0], [1.0, 2.0]], dtype=np.float64)
    rhs = np.array([9.0, 8.0], dtype=np.float64)
    solution = scipy.linalg.solve(matrix, rhs)
    np.testing.assert_allclose(solution, np.linalg.solve(matrix, rhs), rtol=0.0, atol=1e-12)

    values, vectors = scipy.linalg.eigh(matrix)
    np.testing.assert_allclose(values, np.linalg.eigvalsh(matrix), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(matrix @ vectors, vectors * values, rtol=1e-12, atol=1e-12)

    diagonal = np.array([2.0, 3.0, 5.0], dtype=np.float64)
    off_diagonal = np.array([0.5, -0.25], dtype=np.float64)
    tri_values = scipy.linalg.eigh_tridiagonal(diagonal, off_diagonal, eigvals_only=True)
    tri_matrix = np.diag(diagonal) + np.diag(off_diagonal, 1) + np.diag(off_diagonal, -1)
    np.testing.assert_allclose(tri_values, np.linalg.eigvalsh(tri_matrix), rtol=0.0, atol=1e-12)

    toeplitz = scipy.linalg.toeplitz([1, 2, 3], [1, 4, 5])
    np.testing.assert_array_equal(toeplitz, np.array([[1, 4, 5], [2, 1, 4], [3, 2, 1]]))
    block = scipy.linalg.block_diag(np.eye(2), np.array([[7.0]]))
    np.testing.assert_array_equal(block, np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 7.0]]))
    np.testing.assert_allclose(scipy.linalg.norm(matrix), np.linalg.norm(matrix), rtol=0.0, atol=1e-12)


def test_scipy_signal() -> None:
    import scipy.signal

    samples = np.linspace(0.0, 1.0, 8, endpoint=False)
    saw = scipy.signal.sawtooth(2 * np.pi * samples)
    square = scipy.signal.square(2 * np.pi * samples)
    assert saw.shape == samples.shape
    assert square.shape == samples.shape
    assert set(np.unique(square)).issubset({-1.0, 1.0})

    czt_result = scipy.signal.czt(np.array([1.0, 2.0, 3.0, 4.0]))
    np.testing.assert_allclose(czt_result, np.fft.fft(np.array([1.0, 2.0, 3.0, 4.0])), rtol=1e-12, atol=1e-12)

    hann = scipy.signal.windows.hann(8)
    hamming = scipy.signal.get_window("hamming", 8)
    tukey = scipy.signal.windows.tukey(8, alpha=0.5)
    assert hann.shape == (8,)
    assert hamming.shape == (8,)
    assert tukey.shape == (8,)
    np.testing.assert_allclose(hann[0], 0.0, rtol=0.0, atol=1e-12)


def test_scipy_optimize() -> None:
    import scipy.optimize

    root = scipy.optimize.root_scalar(lambda x: x * x - 2.0, bracket=(0.0, 2.0), method="brentq")
    assert root.converged
    np.testing.assert_allclose(root.root, np.sqrt(2.0), rtol=0.0, atol=1e-8)

    newton_root = scipy.optimize.newton(lambda x: x * x - 2.0, 1.0, fprime=lambda x: 2.0 * x)
    np.testing.assert_allclose(newton_root, np.sqrt(2.0), rtol=0.0, atol=1e-8)

    scalar = scipy.optimize.minimize_scalar(lambda x: (x - 3.0) ** 2, bounds=(0.0, 6.0))
    assert scalar.success
    np.testing.assert_allclose(scalar.x, 3.0, rtol=0.0, atol=1e-4)

    result = scipy.optimize.minimize(lambda x: (x[0] - 1.0) ** 2 + (x[1] + 2.0) ** 2, np.array([0.0, 0.0]), method="BFGS")
    assert result.success
    np.testing.assert_allclose(result.x, np.array([1.0, -2.0]), rtol=0.0, atol=1e-4)

    xdata = np.array([0.0, 1.0, 2.0, 3.0], dtype=np.float64)
    ydata = 2.0 * xdata + 1.0
    popt, _pcov = scipy.optimize.curve_fit(lambda x, a, b: a * x + b, xdata, ydata, p0=[0.0, 0.0])
    np.testing.assert_allclose(popt, np.array([2.0, 1.0]), rtol=0.0, atol=1e-3)

    bracket_result = scipy.optimize.bracket(
        lambda value: (value - 2.0) ** 2,
        xa=0.0,
        xb=1.0,
    )
    assert len(bracket_result) == 7
    xa, xb, xc, fa, fb, fc, funcalls = bracket_result
    assert xa < xb < xc
    assert fb < fa and fb < fc
    assert funcalls >= 3


def test_scipy_interpolate() -> None:
    import scipy.interpolate

    x = np.array([0.0, 1.0, 2.0, 3.0], dtype=np.float64)
    y = np.array([0.0, 1.0, 0.0, 1.0], dtype=np.float64)

    linear = scipy.interpolate.interp1d(x, y, kind="linear")
    np.testing.assert_allclose(linear([0.5, 1.5, 2.5]), np.array([0.5, 0.5, 0.5]), rtol=0.0, atol=1e-12)

    cubic = scipy.interpolate.CubicSpline(x, y)
    np.testing.assert_allclose(cubic(x), y, rtol=0.0, atol=1e-12)

    pchip = scipy.interpolate.PchipInterpolator(x, y)
    np.testing.assert_allclose(pchip(x), y, rtol=0.0, atol=1e-12)

    spline = scipy.interpolate.make_interp_spline(x, y, k=3)
    np.testing.assert_allclose(spline(x), y, rtol=0.0, atol=1e-12)

    poly = scipy.interpolate.lagrange([0.0, 1.0, 2.0], [1.0, 3.0, 7.0])
    np.testing.assert_allclose(poly([0.0, 1.0, 2.0]), np.array([1.0, 3.0, 7.0]), rtol=0.0, atol=1e-10)


def test_scipy_stats() -> None:
    import scipy.stats

    values = np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float64)
    other = np.array([2.0, 4.0, 6.0, 8.0], dtype=np.float64)

    np.testing.assert_allclose(scipy.stats.gmean(values), np.exp(np.mean(np.log(values))), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(scipy.stats.hmean(values), 4.0 / (1.0 + 0.5 + 1.0 / 3.0 + 0.25), rtol=0.0, atol=1e-12)

    z = scipy.stats.zscore(values)
    np.testing.assert_allclose(np.mean(z), 0.0, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(np.std(z), 1.0, rtol=0.0, atol=1e-12)

    describe = scipy.stats.describe(values)
    assert describe.nobs == values.size
    np.testing.assert_allclose(describe.mean, values.mean(), rtol=0.0, atol=1e-12)

    pearson = scipy.stats.pearsonr(values, other)
    np.testing.assert_allclose(pearson.statistic, 1.0, rtol=0.0, atol=1e-12)

    linregress = scipy.stats.linregress(values, other)
    np.testing.assert_allclose(linregress.slope, 2.0, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(linregress.intercept, 0.0, rtol=0.0, atol=1e-12)

    entropy = scipy.stats.entropy([0.25, 0.75], base=2.0)
    np.testing.assert_allclose(entropy, -(0.25 * np.log2(0.25) + 0.75 * np.log2(0.75)), rtol=0.0, atol=1e-12)

    t1 = scipy.stats.ttest_1samp(values, 2.5)
    assert np.isfinite(t1.statistic)
    t2 = scipy.stats.ttest_ind(values, values + 1.0)
    assert np.isfinite(t2.statistic)
    t3 = scipy.stats.ttest_rel(values, values + np.array([0.25, -0.25, 0.5, -0.5], dtype=np.float64))
    assert np.isfinite(t3.statistic)

    rv = scipy.stats.norm
    np.testing.assert_allclose(rv.cdf(0.0), 0.5, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(rv.ppf(0.5), 0.0, rtol=0.0, atol=1e-12)
    fit_mu, fit_sigma = rv.fit(values)
    np.testing.assert_allclose(fit_mu, values.mean(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(fit_sigma, values.std(ddof=0), rtol=0.0, atol=1e-12)


def test_scipy_sparse() -> None:
    import scipy.sparse

    matrix = scipy.sparse.csr_matrix([[1.0, 0.0], [0.0, 2.0]])
    assert scipy.sparse.issparse(matrix)
    np.testing.assert_array_equal(matrix.toarray(), np.array([[1.0, 0.0], [0.0, 2.0]]))
    np.testing.assert_array_equal(matrix @ np.array([3.0, 4.0]), np.array([3.0, 8.0]))

    eye = scipy.sparse.eye(3, format="csr")
    np.testing.assert_array_equal(eye.toarray(), np.eye(3))

    diagonal = scipy.sparse.diags([[1.0, 2.0, 3.0]], [0], shape=(3, 3), format="csr")
    np.testing.assert_array_equal(diagonal.toarray(), np.diag([1.0, 2.0, 3.0]))

    stacked = scipy.sparse.vstack([matrix, matrix])
    np.testing.assert_array_equal(stacked.toarray(), np.array([[1.0, 0.0], [0.0, 2.0], [1.0, 0.0], [0.0, 2.0]]))

    row, col, data = scipy.sparse.find(matrix)
    np.testing.assert_array_equal(row, np.array([0, 1]))
    np.testing.assert_array_equal(col, np.array([0, 1]))
    np.testing.assert_array_equal(data, np.array([1.0, 2.0]))

    upper = scipy.sparse.triu(scipy.sparse.csr_matrix([[1.0, 2.0], [3.0, 4.0]]))
    np.testing.assert_array_equal(upper.toarray(), np.array([[1.0, 2.0], [0.0, 4.0]]))


def test_scipy_sparse_linalg() -> None:
    import scipy.sparse
    import scipy.sparse.linalg

    matrix = scipy.sparse.csr_matrix([[4.0, 1.0], [1.0, 3.0]])
    rhs = np.array([1.0, 2.0], dtype=np.float64)

    solved = scipy.sparse.linalg.spsolve(matrix, rhs)
    np.testing.assert_allclose(solved, np.linalg.solve(matrix.toarray(), rhs), rtol=0.0, atol=1e-12)

    cg_solution, cg_info = scipy.sparse.linalg.cg(matrix, rhs, rtol=1e-10, maxiter=50)
    assert cg_info == 0
    np.testing.assert_allclose(cg_solution, np.linalg.solve(matrix.toarray(), rhs), rtol=0.0, atol=1e-8)

    _breakdown_solution, breakdown_info = scipy.sparse.linalg.cg(
        scipy.sparse.csr_matrix([[0.0]]),
        np.array([1.0]),
        maxiter=50,
    )
    assert breakdown_info > 0

    _limited_solution, limited_info = scipy.sparse.linalg.cg(matrix, rhs, rtol=0.0, maxiter=1)
    assert limited_info == 1

    values, vectors = scipy.sparse.linalg.eigsh(matrix, k=1)
    reference_values, reference_vectors = np.linalg.eigh(matrix.toarray())
    np.testing.assert_allclose(values[0], reference_values[-1], rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(np.abs(vectors[:, 0]), np.abs(reference_vectors[:, -1]), rtol=1e-8, atol=1e-8)

    norm = scipy.sparse.linalg.norm(matrix)
    np.testing.assert_allclose(norm, np.linalg.norm(matrix.toarray()), rtol=0.0, atol=1e-12)


def test_scipy_spatial() -> None:
    import scipy.spatial
    import scipy.spatial.distance

    points_a = np.array([[0.0, 0.0], [1.0, 0.0]], dtype=np.float64)
    points_b = np.array([[0.0, 1.0], [1.0, 1.0]], dtype=np.float64)

    cdist = scipy.spatial.distance.cdist(points_a, points_b)
    np.testing.assert_allclose(cdist, np.array([[1.0, np.sqrt(2.0)], [np.sqrt(2.0), 1.0]]), rtol=0.0, atol=1e-12)

    condensed = scipy.spatial.distance.pdist(points_a)
    np.testing.assert_allclose(condensed, np.array([1.0]), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(scipy.spatial.distance.squareform(condensed), np.array([[0.0, 1.0], [1.0, 0.0]]), rtol=0.0, atol=1e-12)

    tree = scipy.spatial.KDTree(points_a)
    distance, index = tree.query([0.9, 0.1])
    np.testing.assert_allclose(distance, np.sqrt(0.02), rtol=0.0, atol=1e-12)
    assert index == 1

    neighbors = tree.query_ball_point([0.0, 0.0], r=0.2)
    assert neighbors == [0]

    sparse_dist = tree.sparse_distance_matrix(scipy.spatial.KDTree(points_b), max_distance=1.1)
    np.testing.assert_allclose(sparse_dist.toarray(), np.array([[1.0, 0.0], [0.0, 1.0]]), rtol=0.0, atol=1e-12)


def main() -> int:
    tests = [
        ("scipy-import", test_scipy_import),
        ("scipy-fft", test_scipy_fft),
        ("scipy-constants", test_scipy_constants),
        ("scipy-fftpack", test_scipy_fftpack),
        ("scipy-io-wavfile", test_scipy_io_wavfile),
        ("scipy-io-arff", test_scipy_io_arff),
        ("scipy-integrate", test_scipy_integrate),
        ("scipy-special", test_scipy_special),
        ("scipy-linalg", test_scipy_linalg),
        ("scipy-signal", test_scipy_signal),
        ("scipy-optimize", test_scipy_optimize),
        ("scipy-interpolate", test_scipy_interpolate),
        ("scipy-stats", test_scipy_stats),
        ("scipy-sparse", test_scipy_sparse),
        ("scipy-sparse-linalg", test_scipy_sparse_linalg),
        ("scipy-spatial", test_scipy_spatial),
    ]
    for name, test in tests:
        print(f"[staticpython-scipy-verify] {name}: running", flush=True)
        test()
        print(f"[staticpython-scipy-verify] {name}: passed", flush=True)
    print(f"[staticpython-scipy-verify] all {len(tests)} smoke test(s) passed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
