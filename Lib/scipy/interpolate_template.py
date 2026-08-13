from __future__ import annotations

import numpy as np

__all__ = [
    "CubicSpline",
    "PchipInterpolator",
    "interp1d",
    "lagrange",
    "make_interp_spline",
]


def _normalize_axis(axis, ndim):
    axis = int(axis)
    if axis < 0:
        axis += ndim
    if axis < 0 or axis >= ndim:
        raise np.AxisError(axis, ndim=ndim)
    return axis


def _prepare_xy(x, y, axis, assume_sorted):
    x_values = np.asarray(x, dtype=np.float64)
    if x_values.ndim != 1:
        raise ValueError("x must be a one-dimensional array")
    if x_values.size < 2:
        raise ValueError("x must contain at least two points")
    y_values = np.asarray(y)
    axis = _normalize_axis(axis, y_values.ndim)
    if y_values.shape[axis] != x_values.size:
        raise ValueError("x and y arrays must be equal in length along interpolation axis")
    moved = np.moveaxis(y_values, axis, 0).astype(np.result_type(y_values, np.float64), copy=False)
    if not assume_sorted:
        order = np.argsort(x_values)
        x_values = x_values[order]
        moved = moved[order]
    if np.any(np.diff(x_values) <= 0):
        raise ValueError("x must be strictly increasing with no duplicate values")
    return x_values, moved, axis


def _restore_values(flat_values, x_new_shape, axis, rest_shape):
    if not x_new_shape:
        return flat_values.reshape(rest_shape)
    values = flat_values.reshape(x_new_shape + rest_shape)
    prefix_len = axis
    x_ndim = len(x_new_shape)
    permutation = (
        list(range(x_ndim, x_ndim + prefix_len))
        + list(range(x_ndim))
        + list(range(x_ndim + prefix_len, values.ndim))
    )
    if permutation != list(range(values.ndim)):
        values = np.transpose(values, permutation)
    return values


def _coerce_fill_value(fill_value):
    if isinstance(fill_value, str):
        if fill_value != "extrapolate":
            raise ValueError(f"unsupported fill_value {fill_value!r}")
        return True, None, None
    if isinstance(fill_value, tuple):
        if len(fill_value) != 2:
            raise ValueError("fill_value tuple must contain exactly two elements")
        return False, fill_value[0], fill_value[1]
    return False, fill_value, fill_value


def _piecewise_indices(x, x_new_flat):
    return np.clip(np.searchsorted(x, x_new_flat, side="right") - 1, 0, x.size - 2)


def _apply_out_of_bounds(result, below, above, bounds_error, extrapolate, fill_below, fill_above):
    if extrapolate:
        return
    if bounds_error and (np.any(below) or np.any(above)):
        raise ValueError("a value in x_new is outside the interpolation range")
    if np.any(below):
        result[below] = fill_below
    if np.any(above):
        result[above] = fill_above


class interp1d:
    def __init__(
        self,
        x,
        y,
        kind="linear",
        axis=-1,
        copy=True,
        bounds_error=None,
        fill_value=np.nan,
        assume_sorted=False,
    ):
        self.x, prepared_y, self.axis = _prepare_xy(x, y, axis, assume_sorted)
        self._y = np.array(prepared_y, copy=bool(copy))
        self._rest_shape = self._y.shape[1:]
        self._rest_ndim = len(self._rest_shape)
        self._kind = str(kind).lower()
        if self._kind == "slinear":
            self._kind = "linear"
        if self._kind == "zero":
            self._kind = "previous"
        supported = {"linear", "nearest", "previous", "next", "quadratic", "cubic"}
        if self._kind not in supported:
            raise NotImplementedError(f"minimal interp1d does not support kind={kind!r}")
        extrapolate, fill_below, fill_above = _coerce_fill_value(fill_value)
        self._extrapolate = extrapolate
        self._fill_below = fill_below
        self._fill_above = fill_above
        self.fill_value = fill_value
        self.bounds_error = False if bounds_error is None else bool(bounds_error)
        self._spline = None
        if self._kind in {"quadratic", "cubic"}:
            self._spline = CubicSpline(self.x, self._y, axis=0, bc_type="natural", extrapolate=extrapolate)

    def _evaluate_linear(self, x_new_flat):
        indices = _piecewise_indices(self.x, x_new_flat)
        x0 = self.x[indices]
        x1 = self.x[indices + 1]
        scale = (x_new_flat - x0) / (x1 - x0)
        scale = scale.reshape((-1,) + (1,) * self._rest_ndim)
        y0 = self._y[indices]
        y1 = self._y[indices + 1]
        result = y0 + (y1 - y0) * scale
        below = x_new_flat < self.x[0]
        above = x_new_flat > self.x[-1]
        _apply_out_of_bounds(
            result,
            below,
            above,
            self.bounds_error,
            self._extrapolate,
            self._fill_below,
            self._fill_above,
        )
        return result

    def _evaluate_nearest(self, x_new_flat):
        midpoints = 0.5 * (self.x[:-1] + self.x[1:])
        indices = np.searchsorted(midpoints, x_new_flat, side="left")
        indices = np.clip(indices, 0, self.x.size - 1)
        result = self._y[indices]
        below = x_new_flat < self.x[0]
        above = x_new_flat > self.x[-1]
        _apply_out_of_bounds(
            result,
            below,
            above,
            self.bounds_error,
            self._extrapolate,
            self._fill_below,
            self._fill_above,
        )
        return result

    def _evaluate_step(self, x_new_flat, *, use_next):
        side = "left" if use_next else "right"
        indices = np.searchsorted(self.x, x_new_flat, side=side)
        if use_next:
            indices = np.clip(indices, 0, self.x.size - 1)
        else:
            indices = np.clip(indices - 1, 0, self.x.size - 1)
        result = self._y[indices]
        below = x_new_flat < self.x[0]
        above = x_new_flat > self.x[-1]
        _apply_out_of_bounds(
            result,
            below,
            above,
            self.bounds_error,
            self._extrapolate,
            self._fill_below,
            self._fill_above,
        )
        return result

    def __call__(self, x_new):
        x_new_values = np.asarray(x_new, dtype=np.float64)
        x_new_flat = x_new_values.reshape(-1)
        if self._kind == "linear":
            evaluated = self._evaluate_linear(x_new_flat)
        elif self._kind == "nearest":
            evaluated = self._evaluate_nearest(x_new_flat)
        elif self._kind == "previous":
            evaluated = self._evaluate_step(x_new_flat, use_next=False)
        elif self._kind == "next":
            evaluated = self._evaluate_step(x_new_flat, use_next=True)
        else:
            evaluated = self._spline(x_new_values).reshape((-1,) + self._rest_shape)
        return _restore_values(evaluated, x_new_values.shape, self.axis, self._rest_shape)


def _solve_natural_cubic_coefficients(x, y):
    n = x.size
    rest_shape = y.shape[1:]
    rest_ndim = len(rest_shape)
    h = np.diff(x)
    expand = (-1,) + (1,) * rest_ndim
    delta = np.diff(y, axis=0) / h.reshape(expand)
    matrix = np.zeros((n, n), dtype=np.float64)
    matrix[0, 0] = 1.0
    matrix[-1, -1] = 1.0
    if n > 2:
        lower = h[:-1]
        upper = h[1:]
        diagonal = 2.0 * (lower + upper)
        matrix[np.arange(1, n - 1), np.arange(0, n - 2)] = lower
        matrix[np.arange(1, n - 1), np.arange(1, n - 1)] = diagonal
        matrix[np.arange(1, n - 1), np.arange(2, n)] = upper
    rhs = np.zeros((n,) + rest_shape, dtype=np.result_type(y, np.float64))
    if n > 2:
        rhs[1:-1] = 6.0 * (delta[1:] - delta[:-1])
    second = np.linalg.solve(matrix, rhs.reshape(n, -1)).reshape((n,) + rest_shape)
    interval_h = h.reshape(expand)
    a = y[:-1]
    b = delta - interval_h * (2.0 * second[:-1] + second[1:]) / 6.0
    c = 0.5 * second[:-1]
    d = (second[1:] - second[:-1]) / (6.0 * interval_h)
    return a, b, c, d


def _evaluate_piecewise_polynomial(x, coefficients, x_new_flat, rest_ndim, extrapolate):
    a, b, c, d = coefficients
    indices = _piecewise_indices(x, x_new_flat)
    dx = (x_new_flat - x[indices]).reshape((-1,) + (1,) * rest_ndim)
    result = a[indices] + b[indices] * dx + c[indices] * dx * dx + d[indices] * dx * dx * dx
    if not extrapolate:
        mask = (x_new_flat < x[0]) | (x_new_flat > x[-1])
        if np.any(mask):
            result[mask] = np.nan
    return result


def _evaluate_piecewise_derivative(x, coefficients, x_new_flat, rest_ndim, nu, extrapolate):
    a, b, c, d = coefficients
    indices = _piecewise_indices(x, x_new_flat)
    dx = (x_new_flat - x[indices]).reshape((-1,) + (1,) * rest_ndim)
    if nu == 0:
        result = a[indices] + b[indices] * dx + c[indices] * dx * dx + d[indices] * dx * dx * dx
    elif nu == 1:
        result = b[indices] + 2.0 * c[indices] * dx + 3.0 * d[indices] * dx * dx
    elif nu == 2:
        result = 2.0 * c[indices] + 6.0 * d[indices] * dx
    elif nu == 3:
        result = 6.0 * d[indices]
    else:
        result = np.zeros((x_new_flat.size,) + a.shape[1:], dtype=np.result_type(a, np.float64))
    if not extrapolate:
        mask = (x_new_flat < x[0]) | (x_new_flat > x[-1])
        if np.any(mask):
            result[mask] = np.nan
    return result


class CubicSpline:
    def __init__(self, x, y, axis=0, bc_type="not-a-knot", extrapolate=None):
        if bc_type not in ("not-a-knot", "natural", None):
            raise NotImplementedError("minimal CubicSpline supports only natural-style boundary conditions")
        self.x, prepared_y, self.axis = _prepare_xy(x, y, axis, assume_sorted=True)
        self._y = prepared_y.astype(np.result_type(prepared_y, np.float64), copy=False)
        self._rest_shape = self._y.shape[1:]
        self._rest_ndim = len(self._rest_shape)
        self.extrapolate = True if extrapolate is None else bool(extrapolate)
        self._coefficients = _solve_natural_cubic_coefficients(self.x, self._y)
        a, b, c, d = self._coefficients
        self.c = np.stack([d, c, b, a], axis=0)

    def __call__(self, x_new, nu=0, extrapolate=None):
        use_extrapolate = self.extrapolate if extrapolate is None else bool(extrapolate)
        x_new_values = np.asarray(x_new, dtype=np.float64)
        x_new_flat = x_new_values.reshape(-1)
        evaluated = _evaluate_piecewise_derivative(
            self.x,
            self._coefficients,
            x_new_flat,
            self._rest_ndim,
            int(nu),
            use_extrapolate,
        )
        return _restore_values(evaluated, x_new_values.shape, self.axis, self._rest_shape)


def _pchip_edge(h0, h1, delta0, delta1):
    slope = ((2.0 * h0 + h1) * delta0 - h0 * delta1) / (h0 + h1)
    bad_sign = np.sign(slope) != np.sign(delta0)
    slope = np.where(bad_sign, 0.0, slope)
    too_large = (np.sign(delta0) != np.sign(delta1)) & (np.abs(slope) > 3.0 * np.abs(delta0))
    slope = np.where(too_large, 3.0 * delta0, slope)
    return slope


def _solve_pchip_coefficients(x, y):
    n = x.size
    rest_shape = y.shape[1:]
    rest_ndim = len(rest_shape)
    h = np.diff(x)
    expand = (-1,) + (1,) * rest_ndim
    delta = np.diff(y, axis=0) / h.reshape(expand)
    slopes = np.zeros_like(y, dtype=np.result_type(y, np.float64))
    if n == 2:
        slopes[:] = delta[0]
    else:
        slopes[0] = _pchip_edge(h[0], h[1], delta[0], delta[1])
        slopes[-1] = _pchip_edge(h[-1], h[-2], delta[-1], delta[-2])
        w1 = (2.0 * h[1:] + h[:-1]).reshape(expand)
        w2 = (h[1:] + 2.0 * h[:-1]).reshape(expand)
        same_sign = (delta[:-1] != 0.0) & (delta[1:] != 0.0) & (np.sign(delta[:-1]) == np.sign(delta[1:]))
        denominator = w1 / delta[:-1] + w2 / delta[1:]
        harmonic = np.zeros_like(delta[:-1], dtype=np.result_type(y, np.float64))
        np.divide(w1 + w2, denominator, out=harmonic, where=same_sign)
        slopes[1:-1] = np.where(same_sign, harmonic, 0.0)
    interval_h = h.reshape(expand)
    a = y[:-1]
    b = slopes[:-1]
    c = (3.0 * delta - 2.0 * slopes[:-1] - slopes[1:]) / interval_h
    d = (slopes[:-1] + slopes[1:] - 2.0 * delta) / (interval_h * interval_h)
    return a, b, c, d


class PchipInterpolator:
    def __init__(self, x, y, axis=0, extrapolate=None):
        self.x, prepared_y, self.axis = _prepare_xy(x, y, axis, assume_sorted=True)
        self._y = prepared_y.astype(np.result_type(prepared_y, np.float64), copy=False)
        self._rest_shape = self._y.shape[1:]
        self._rest_ndim = len(self._rest_shape)
        self.extrapolate = True if extrapolate is None else bool(extrapolate)
        self._coefficients = _solve_pchip_coefficients(self.x, self._y)
        a, b, c, d = self._coefficients
        self.c = np.stack([d, c, b, a], axis=0)

    def __call__(self, x_new, nu=0, extrapolate=None):
        use_extrapolate = self.extrapolate if extrapolate is None else bool(extrapolate)
        x_new_values = np.asarray(x_new, dtype=np.float64)
        x_new_flat = x_new_values.reshape(-1)
        evaluated = _evaluate_piecewise_derivative(
            self.x,
            self._coefficients,
            x_new_flat,
            self._rest_ndim,
            int(nu),
            use_extrapolate,
        )
        return _restore_values(evaluated, x_new_values.shape, self.axis, self._rest_shape)


def make_interp_spline(x, y, k=3, axis=0, bc_type=None, check_finite=True):
    if check_finite:
        if not np.all(np.isfinite(np.asarray(x, dtype=np.float64))):
            raise ValueError("x must contain only finite values")
        if not np.all(np.isfinite(np.asarray(y, dtype=np.float64))):
            raise ValueError("y must contain only finite values")
    if int(k) == 1:
        return interp1d(x, y, kind="linear", axis=axis, bounds_error=False, fill_value="extrapolate", assume_sorted=False)
    if int(k) == 3:
        return CubicSpline(x, y, axis=axis, bc_type="natural" if bc_type is None else bc_type)
    raise NotImplementedError("minimal make_interp_spline supports only k=1 and k=3")


def lagrange(x, w):
    x_values = np.asarray(x, dtype=np.float64)
    y_values = np.asarray(w, dtype=np.float64)
    if x_values.ndim != 1 or y_values.ndim != 1 or x_values.size != y_values.size:
        raise ValueError("lagrange expects one-dimensional x and y arrays of equal length")
    vandermonde = np.vander(x_values, N=x_values.size, increasing=False)
    coefficients = np.linalg.solve(vandermonde, y_values)
    return np.poly1d(coefficients)


from scipy._lib._testutils import PytestTester

test = PytestTester(__name__)
del PytestTester
