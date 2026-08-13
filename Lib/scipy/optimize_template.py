from __future__ import annotations

import inspect
import math
import warnings

import numpy as np

__all__ = [
    "BFGS",
    "Bounds",
    "LinearConstraint",
    "NonlinearConstraint",
    "OptimizeResult",
    "OptimizeWarning",
    "RootResults",
    "SR1",
    "approx_fprime",
    "bisect",
    "bracket",
    "brent",
    "brenth",
    "brentq",
    "check_grad",
    "curve_fit",
    "fmin",
    "fmin_bfgs",
    "fminbound",
    "golden",
    "minimize",
    "minimize_scalar",
    "newton",
    "ridder",
    "root_scalar",
    "rosen",
    "rosen_der",
    "rosen_hess",
    "rosen_hess_prod",
    "show_options",
    "toms748",
]

_CONVERGED = 0
_SIGNERR = -1
_CONVERR = -2
_VALUEERR = -3

_FLAG_MAP = {
    _CONVERGED: "converged",
    _SIGNERR: "sign error",
    _CONVERR: "convergence error",
    _VALUEERR: "value error",
}


class OptimizeResult(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value

    def __delattr__(self, name):
        try:
            del self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


class RootResults(OptimizeResult):
    def __init__(self, root, iterations, function_calls, flag, method):
        super().__init__()
        self.root = root
        self.iterations = iterations
        self.function_calls = function_calls
        self.converged = flag == _CONVERGED
        self.flag = _FLAG_MAP.get(flag, flag)
        self.method = method


class OptimizeWarning(UserWarning):
    pass


class HessianUpdateStrategy:
    def initialize(self, n, approx_type):
        return None


class BFGS(HessianUpdateStrategy):
    pass


class SR1(HessianUpdateStrategy):
    pass


class Bounds:
    def __init__(self, lb=-np.inf, ub=np.inf, keep_feasible=False):
        self.lb = np.asarray(lb, dtype=np.float64)
        self.ub = np.asarray(ub, dtype=np.float64)
        self.keep_feasible = keep_feasible


class LinearConstraint:
    def __init__(self, A, lb=-np.inf, ub=np.inf, keep_feasible=False):
        self.A = np.asarray(A, dtype=np.float64)
        self.lb = np.asarray(lb, dtype=np.float64)
        self.ub = np.asarray(ub, dtype=np.float64)
        self.keep_feasible = keep_feasible


class NonlinearConstraint:
    def __init__(self, fun, lb, ub, jac="2-point", hess=None, keep_feasible=False, finite_diff_rel_step=None, finite_diff_jac_sparsity=None):
        self.fun = fun
        self.lb = lb
        self.ub = ub
        self.jac = jac
        self.hess = BFGS() if hess is None else hess
        self.keep_feasible = keep_feasible
        self.finite_diff_rel_step = finite_diff_rel_step
        self.finite_diff_jac_sparsity = finite_diff_jac_sparsity


def _ensure_tuple(args):
    return args if isinstance(args, tuple) else (args,)


def _asarray1d(x):
    array = np.asarray(x, dtype=np.float64)
    if array.ndim == 0:
        return array.reshape(1)
    return array.astype(np.float64, copy=False)


def _prepare_bounds(bounds, n):
    if bounds is None:
        return np.full(n, -np.inf, dtype=np.float64), np.full(n, np.inf, dtype=np.float64)
    if isinstance(bounds, Bounds):
        lb = np.asarray(bounds.lb, dtype=np.float64)
        ub = np.asarray(bounds.ub, dtype=np.float64)
    else:
        pairs = list(bounds)
        lb = np.array([-np.inf if pair[0] is None else pair[0] for pair in pairs], dtype=np.float64)
        ub = np.array([np.inf if pair[1] is None else pair[1] for pair in pairs], dtype=np.float64)
    if lb.ndim == 0:
        lb = np.full(n, lb.item(), dtype=np.float64)
    if ub.ndim == 0:
        ub = np.full(n, ub.item(), dtype=np.float64)
    return np.broadcast_to(lb, (n,)).astype(np.float64), np.broadcast_to(ub, (n,)).astype(np.float64)


def _project_bounds(x, lb, ub):
    return np.minimum(np.maximum(x, lb), ub)


def approx_fprime(xk, f, epsilon, *args):
    x = np.asarray(xk, dtype=np.float64)
    eps = np.asarray(epsilon, dtype=np.float64)
    if eps.ndim == 0:
        eps = np.full_like(x, float(eps))
    gradient = np.zeros_like(x, dtype=np.float64)
    f0 = float(f(x, *args))
    for index in range(x.size):
        x1 = x.copy()
        step = eps[index]
        x1[index] += step
        gradient[index] = (float(f(x1, *args)) - f0) / step
    return gradient


def check_grad(func, grad, x0, *args):
    x = np.asarray(x0, dtype=np.float64)
    epsilon = np.sqrt(np.finfo(np.float64).eps) * np.maximum(1.0, np.abs(x))
    return np.linalg.norm(approx_fprime(x, func, epsilon, *args) - np.asarray(grad(x, *args), dtype=np.float64))


def rosen(x):
    values = np.asarray(x, dtype=np.float64)
    return np.sum(100.0 * (values[1:] - values[:-1] ** 2.0) ** 2.0 + (1 - values[:-1]) ** 2.0)


def rosen_der(x):
    values = np.asarray(x, dtype=np.float64)
    grad = np.zeros_like(values)
    grad[0:-1] -= 400.0 * values[0:-1] * (values[1:] - values[0:-1] ** 2.0) + 2.0 * (values[0:-1] - 1.0)
    grad[1:] += 200.0 * (values[1:] - values[0:-1] ** 2.0)
    return grad


def rosen_hess(x):
    values = np.asarray(x, dtype=np.float64)
    n = values.size
    hess = np.zeros((n, n), dtype=np.float64)
    diagonal = np.zeros(n, dtype=np.float64)
    diagonal[0:-1] += 1200.0 * values[0:-1] ** 2.0 - 400.0 * values[1:] + 2.0
    diagonal[1:] += 200.0
    np.fill_diagonal(hess, diagonal)
    off = -400.0 * values[0:-1]
    hess[np.arange(n - 1), np.arange(1, n)] = off
    hess[np.arange(1, n), np.arange(n - 1)] = off
    return hess


def rosen_hess_prod(x, p):
    return rosen_hess(x) @ np.asarray(p, dtype=np.float64)


def _make_root_result(full_output, root, iterations, function_calls, flag, method):
    if full_output:
        return root, RootResults(root, iterations, function_calls, flag, method)
    return root


def _bisect_core(func, a, b, args, xtol, rtol, maxiter):
    fa = float(func(a, *args))
    fb = float(func(b, *args))
    calls = 2
    if fa == 0.0:
        return a, 0, calls, _CONVERGED
    if fb == 0.0:
        return b, 0, calls, _CONVERGED
    if np.sign(fa) == np.sign(fb):
        raise ValueError("f(a) and f(b) must have different signs")
    for iteration in range(1, maxiter + 1):
        mid = 0.5 * (a + b)
        fm = float(func(mid, *args))
        calls += 1
        tolerance = xtol + rtol * abs(mid)
        if fm == 0.0 or 0.5 * abs(b - a) <= tolerance:
            return mid, iteration, calls, _CONVERGED
        if np.sign(fm) == np.sign(fa):
            a, fa = mid, fm
        else:
            b, fb = mid, fm
    return mid, maxiter, calls, _CONVERR


def bisect(f, a, b, args=(), xtol=2e-12, rtol=4 * np.finfo(float).eps, maxiter=100, full_output=False, disp=True):
    args = _ensure_tuple(args)
    root, iterations, function_calls, flag = _bisect_core(f, float(a), float(b), args, float(xtol), float(rtol), int(maxiter))
    result = _make_root_result(full_output, root, iterations, function_calls, flag, "bisect")
    if disp and flag != _CONVERGED:
        raise RuntimeError("bisect failed to converge")
    return result


def brentq(f, a, b, args=(), xtol=2e-12, rtol=4 * np.finfo(float).eps, maxiter=100, full_output=False, disp=True):
    args = _ensure_tuple(args)
    root, iterations, function_calls, flag = _bisect_core(f, float(a), float(b), args, float(xtol), float(rtol), int(maxiter))
    result = _make_root_result(full_output, root, iterations, function_calls, flag, "brentq")
    if disp and flag != _CONVERGED:
        raise RuntimeError("brentq failed to converge")
    return result


def brenth(f, a, b, args=(), xtol=2e-12, rtol=4 * np.finfo(float).eps, maxiter=100, full_output=False, disp=True):
    args = _ensure_tuple(args)
    root, iterations, function_calls, flag = _bisect_core(f, float(a), float(b), args, float(xtol), float(rtol), int(maxiter))
    result = _make_root_result(full_output, root, iterations, function_calls, flag, "brenth")
    if disp and flag != _CONVERGED:
        raise RuntimeError("brenth failed to converge")
    return result


def ridder(f, a, b, args=(), xtol=2e-12, rtol=4 * np.finfo(float).eps, maxiter=100, full_output=False, disp=True):
    args = _ensure_tuple(args)
    root, iterations, function_calls, flag = _bisect_core(f, float(a), float(b), args, float(xtol), float(rtol), int(maxiter))
    result = _make_root_result(full_output, root, iterations, function_calls, flag, "ridder")
    if disp and flag != _CONVERGED:
        raise RuntimeError("ridder failed to converge")
    return result


def toms748(f, a, b, args=(), k=1, xtol=2e-12, rtol=4 * np.finfo(float).eps, maxiter=100, full_output=False, disp=True):
    args = _ensure_tuple(args)
    root, iterations, function_calls, flag = _bisect_core(f, float(a), float(b), args, float(xtol), float(rtol), int(maxiter))
    result = _make_root_result(full_output, root, iterations, function_calls, flag, "toms748")
    if disp and flag != _CONVERGED:
        raise RuntimeError("toms748 failed to converge")
    return result


def newton(func, x0, fprime=None, args=(), tol=1.48e-8, maxiter=50, fprime2=None, x1=None, rtol=0.0, full_output=False, disp=True):
    args = _ensure_tuple(args)
    values = np.asarray(x0)
    if values.ndim > 0 and values.size > 1:
        roots = [
            newton(func, value, fprime=fprime, args=args, tol=tol, maxiter=maxiter, fprime2=fprime2, x1=x1, rtol=rtol, full_output=False, disp=disp)
            for value in values
        ]
        return np.asarray(roots)

    current = float(np.asarray(x0).item())
    function_calls = 0
    if fprime is None:
        previous = current + (1e-4 if x1 is None else current - float(x1))
        f_previous = float(func(previous, *args))
        f_current = float(func(current, *args))
        function_calls += 2
        for iteration in range(1, int(maxiter) + 1):
            denominator = f_current - f_previous
            if denominator == 0.0:
                break
            next_value = current - f_current * (current - previous) / denominator
            if abs(next_value - current) <= float(tol) + float(rtol) * abs(next_value):
                result = _make_root_result(full_output, next_value, iteration, function_calls, _CONVERGED, "newton")
                return result
            previous, f_previous = current, f_current
            current = next_value
            f_current = float(func(current, *args))
            function_calls += 1
    else:
        for iteration in range(1, int(maxiter) + 1):
            f_value = float(func(current, *args))
            function_calls += 1
            derivative = float(fprime(current, *args))
            function_calls += 1
            if derivative == 0.0:
                break
            step = f_value / derivative
            if fprime2 is not None:
                second = float(fprime2(current, *args))
                function_calls += 1
                denominator = 1.0 - 0.5 * step * second / derivative
                if denominator != 0.0:
                    step /= denominator
            next_value = current - step
            if abs(next_value - current) <= float(tol) + float(rtol) * abs(next_value):
                result = _make_root_result(full_output, next_value, iteration, function_calls, _CONVERGED, "newton")
                return result
            current = next_value

    result = _make_root_result(full_output, current, int(maxiter), function_calls, _CONVERR, "newton")
    if disp:
        raise RuntimeError("newton failed to converge")
    return result


def root_scalar(f, args=(), method=None, bracket=None, fprime=None, fprime2=None, x0=None, x1=None, xtol=None, rtol=None, maxiter=None, options=None):
    args = _ensure_tuple(args)
    method_name = (method or "").lower()
    xtol = 2e-12 if xtol is None else xtol
    rtol = 4 * np.finfo(float).eps if rtol is None else rtol
    maxiter = 100 if maxiter is None else maxiter
    if not method_name:
        method_name = "brentq" if bracket is not None else "newton"
    if method_name in {"bisect", "brentq", "brenth", "ridder", "toms748"}:
        if bracket is None:
            raise ValueError(f"method {method_name!r} requires a bracket")
        a, b = bracket
        solver = {
            "bisect": bisect,
            "brentq": brentq,
            "brenth": brenth,
            "ridder": ridder,
            "toms748": toms748,
        }[method_name]
        return solver(f, a, b, args=args, xtol=xtol, rtol=rtol, maxiter=maxiter, full_output=True, disp=False)[1]
    if method_name in {"newton", "secant", "halley"}:
        if x0 is None:
            raise ValueError(f"method {method_name!r} requires x0")
        if method_name == "secant":
            return newton(f, x0, fprime=None, args=args, tol=xtol, maxiter=maxiter, x1=x1, rtol=rtol, full_output=True, disp=False)[1]
        if method_name == "halley":
            if fprime is None or fprime2 is None:
                raise ValueError("halley requires both fprime and fprime2")
            return newton(f, x0, fprime=fprime, fprime2=fprime2, args=args, tol=xtol, maxiter=maxiter, rtol=rtol, full_output=True, disp=False)[1]
        return newton(f, x0, fprime=fprime, fprime2=fprime2, args=args, tol=xtol, maxiter=maxiter, x1=x1, rtol=rtol, full_output=True, disp=False)[1]
    raise NotImplementedError(f"unsupported root_scalar method: {method_name}")


def bracket(func, xa=0.0, xb=1.0, args=(), grow_limit=110.0, maxiter=1000):
    args = _ensure_tuple(args)
    xa = float(xa)
    xb = float(xb)
    fa = float(func(xa, *args))
    fb = float(func(xb, *args))
    funcalls = 2
    if fb > fa:
        xa, xb = xb, xa
        fa, fb = fb, fa
    step = xb - xa
    if step == 0.0:
        step = 1.0
    grow_limit = float(grow_limit)
    if not math.isfinite(grow_limit) or grow_limit <= 1.0:
        raise ValueError("grow_limit must be finite and greater than 1")
    max_step = grow_limit * abs(step)
    factor = 1.618033988749895
    xc = xb + factor * step
    fc = float(func(xc, *args))
    funcalls += 1
    iteration = 0
    while not (fb < fa and fb < fc):
        xa, fa = xb, fb
        xb, fb = xc, fc
        step *= factor
        if abs(step) > max_step:
            raise RuntimeError("No valid bracket was found within grow_limit")
        xc = xb + step
        fc = float(func(xc, *args))
        funcalls += 1
        iteration += 1
        if iteration >= maxiter:
            raise RuntimeError("No valid bracket was found before the iteration limit")
    return xa, xb, xc, fa, fb, fc, funcalls


def _golden_search(func, left, right, args, tol, maxiter):
    invphi = (math.sqrt(5.0) - 1.0) / 2.0
    invphi2 = (3.0 - math.sqrt(5.0)) / 2.0
    h = right - left
    if h == 0.0:
        value = float(func(left, *args))
        return left, value, 1, 0
    n = max(1, int(math.ceil(math.log(max(float(tol), np.finfo(float).eps) / abs(h)) / math.log(invphi))))
    c = left + invphi2 * h
    d = left + invphi * h
    yc = float(func(c, *args))
    yd = float(func(d, *args))
    calls = 2
    for iteration in range(1, min(n, maxiter) + 1):
        if yc < yd:
            right, d, yd = d, c, yc
            h = invphi * h
            c = left + invphi2 * h
            yc = float(func(c, *args))
        else:
            left, c, yc = c, d, yd
            h = invphi * h
            d = left + invphi * h
            yd = float(func(d, *args))
        calls += 1
        if abs(right - left) <= tol:
            break
    if yc < yd:
        return c, yc, calls, iteration
    return d, yd, calls, iteration


def golden(func, args=(), brack=None, tol=1.4901161193847656e-08, full_output=False, maxiter=5000):
    args = _ensure_tuple(args)
    if brack is None:
        xa, xb, xc, *_ = bracket(func, args=args)
    elif len(brack) == 2:
        xa, xb, xc, *_ = bracket(func, brack[0], brack[1], args=args)
    else:
        xa, xb, xc = brack[:3]
    left = min(xa, xc)
    right = max(xa, xc)
    xmin, fval, calls, iterations = _golden_search(func, float(left), float(right), args, float(tol), int(maxiter))
    if full_output:
        return xmin, fval, calls
    return xmin


def brent(func, args=(), brack=None, tol=1.48e-8, full_output=False, maxiter=5000):
    result = golden(func, args=args, brack=brack, tol=tol, full_output=True, maxiter=maxiter)
    if full_output:
        return result
    return result[0]


def fminbound(func, x1, x2, args=(), xtol=1e-5, maxfun=500, full_output=False, disp=0):
    args = _ensure_tuple(args)
    xmin, fval, calls, _iterations = _golden_search(func, float(x1), float(x2), args, float(xtol), int(maxfun))
    ierr = 0
    if full_output:
        return xmin, fval, ierr, calls
    return xmin


def minimize_scalar(fun, bracket=None, bounds=None, args=(), method=None, tol=None, options=None):
    args = _ensure_tuple(args)
    method_name = (method or "").lower()
    if options is None:
        options = {}
    maxiter = int(options.get("maxiter", 5000))
    if bounds is not None:
        left, right = bounds
        x, fun_value, calls, iterations = _golden_search(fun, float(left), float(right), args, float(tol or 1e-5), maxiter)
        return OptimizeResult(
            x=float(x),
            fun=float(fun_value),
            nit=int(iterations),
            nfev=int(calls),
            success=True,
            message="Optimization terminated successfully.",
            method="bounded" if not method_name else method_name,
        )
    x, fun_value, calls = golden(fun, args=args, brack=bracket, tol=tol or 1.48e-8, full_output=True, maxiter=maxiter)
    return OptimizeResult(
        x=float(x),
        fun=float(fun_value),
        nit=int(maxiter),
        nfev=int(calls),
        success=True,
        message="Optimization terminated successfully.",
        method=method_name or "golden",
    )


def _evaluate_gradient(fun, x, args, jac):
    if callable(jac):
        return np.asarray(jac(np.copy(x), *args), dtype=np.float64), 0
    epsilon = np.sqrt(np.finfo(np.float64).eps) * np.maximum(1.0, np.abs(x))
    return approx_fprime(x, fun, epsilon, *args), x.size + 1


def _call_callback(callback, x, fun_value):
    if callback is None:
        return
    try:
        signature = inspect.signature(callback)
    except (TypeError, ValueError):
        callback(np.copy(x))
        return
    if "intermediate_result" in signature.parameters:
        callback(intermediate_result=OptimizeResult(x=np.copy(x), fun=float(fun_value)))
    else:
        callback(np.copy(x))


def _minimize_bfgs(fun, x0, args, jac, bounds, tol, callback, options):
    x = np.asarray(x0, dtype=np.float64).copy()
    n = x.size
    lb, ub = _prepare_bounds(bounds, n)
    x = _project_bounds(x, lb, ub)
    maxiter = int(options.get("maxiter", 200))
    gtol = float(options.get("gtol", tol if tol is not None else 1e-6))
    H = np.eye(n, dtype=np.float64)
    nfev = 0
    njev = 0
    fun_value = float(fun(x, *args))
    nfev += 1
    gradient, extra_evals = _evaluate_gradient(fun, x, args, jac)
    nfev += extra_evals
    njev += 1
    for iteration in range(1, maxiter + 1):
        grad_norm = float(np.linalg.norm(gradient))
        if grad_norm <= gtol:
            return OptimizeResult(
                x=x,
                fun=fun_value,
                jac=gradient,
                hess_inv=H,
                nit=iteration - 1,
                nfev=nfev,
                njev=njev,
                success=True,
                message="Optimization terminated successfully.",
                method="BFGS",
            )
        direction = -H @ gradient
        if np.dot(direction, gradient) >= 0:
            direction = -gradient
        alpha = float(options.get("alpha0", 1.0))
        trial_x = x
        trial_value = fun_value
        for _ in range(int(options.get("line_search_maxiter", 25))):
            candidate = _project_bounds(x + alpha * direction, lb, ub)
            candidate_value = float(fun(candidate, *args))
            nfev += 1
            if candidate_value <= fun_value + 1e-4 * alpha * np.dot(gradient, direction):
                trial_x = candidate
                trial_value = candidate_value
                break
            alpha *= 0.5
        else:
            return OptimizeResult(
                x=x,
                fun=fun_value,
                jac=gradient,
                hess_inv=H,
                nit=iteration - 1,
                nfev=nfev,
                njev=njev,
                success=False,
                message="Line search failed to find a decreasing step.",
                method="BFGS",
            )

        trial_gradient, extra_evals = _evaluate_gradient(fun, trial_x, args, jac)
        nfev += extra_evals
        njev += 1
        s = trial_x - x
        y = trial_gradient - gradient
        ys = float(np.dot(y, s))
        if ys > 1e-12:
            rho = 1.0 / ys
            I = np.eye(n, dtype=np.float64)
            outer_sy = np.outer(s, y)
            outer_ys = np.outer(y, s)
            H = (I - rho * outer_sy) @ H @ (I - rho * outer_ys) + rho * np.outer(s, s)
        x = trial_x
        fun_value = trial_value
        gradient = trial_gradient
        _call_callback(callback, x, fun_value)

    return OptimizeResult(
        x=x,
        fun=fun_value,
        jac=gradient,
        hess_inv=H,
        nit=maxiter,
        nfev=nfev,
        njev=njev,
        success=False,
        message="Maximum number of iterations has been exceeded.",
        method="BFGS",
    )


def _initial_simplex(x0):
    x0 = np.asarray(x0, dtype=np.float64)
    simplex = [x0]
    for index in range(x0.size):
        point = x0.copy()
        delta = 0.05 * (abs(point[index]) + 1.0)
        point[index] += delta
        simplex.append(point)
    return np.asarray(simplex, dtype=np.float64)


def _minimize_nelder_mead(fun, x0, args, bounds, tol, callback, options):
    simplex = _initial_simplex(np.asarray(x0, dtype=np.float64))
    lb, ub = _prepare_bounds(bounds, simplex.shape[1])
    simplex = np.array([_project_bounds(vertex, lb, ub) for vertex in simplex], dtype=np.float64)
    maxiter = int(options.get("maxiter", 500))
    xatol = float(options.get("xatol", tol if tol is not None else 1e-6))
    fatol = float(options.get("fatol", tol if tol is not None else 1e-6))
    alpha, gamma, rho, sigma = 1.0, 2.0, 0.5, 0.5
    values = np.array([float(fun(vertex, *args)) for vertex in simplex], dtype=np.float64)
    nfev = simplex.shape[0]
    for iteration in range(1, maxiter + 1):
        order = np.argsort(values)
        simplex = simplex[order]
        values = values[order]
        if np.max(np.abs(simplex[1:] - simplex[0])) <= xatol and np.max(np.abs(values[0] - values[1:])) <= fatol:
            return OptimizeResult(
                x=simplex[0],
                fun=float(values[0]),
                nit=iteration - 1,
                nfev=nfev,
                success=True,
                message="Optimization terminated successfully.",
                method="Nelder-Mead",
            )
        centroid = np.mean(simplex[:-1], axis=0)
        reflected = _project_bounds(centroid + alpha * (centroid - simplex[-1]), lb, ub)
        reflected_value = float(fun(reflected, *args))
        nfev += 1
        if values[0] <= reflected_value < values[-2]:
            simplex[-1] = reflected
            values[-1] = reflected_value
        elif reflected_value < values[0]:
            expanded = _project_bounds(centroid + gamma * (reflected - centroid), lb, ub)
            expanded_value = float(fun(expanded, *args))
            nfev += 1
            if expanded_value < reflected_value:
                simplex[-1] = expanded
                values[-1] = expanded_value
            else:
                simplex[-1] = reflected
                values[-1] = reflected_value
        else:
            contracted = _project_bounds(centroid + rho * (simplex[-1] - centroid), lb, ub)
            contracted_value = float(fun(contracted, *args))
            nfev += 1
            if contracted_value < values[-1]:
                simplex[-1] = contracted
                values[-1] = contracted_value
            else:
                best = simplex[0]
                simplex = np.array([best + sigma * (vertex - best) for vertex in simplex], dtype=np.float64)
                simplex = np.array([_project_bounds(vertex, lb, ub) for vertex in simplex], dtype=np.float64)
                values = np.array([float(fun(vertex, *args)) for vertex in simplex], dtype=np.float64)
                nfev += simplex.shape[0]
        _call_callback(callback, simplex[np.argmin(values)], np.min(values))

    best_index = int(np.argmin(values))
    return OptimizeResult(
        x=simplex[best_index],
        fun=float(values[best_index]),
        nit=maxiter,
        nfev=nfev,
        success=False,
        message="Maximum number of iterations has been exceeded.",
        method="Nelder-Mead",
    )


def minimize(fun, x0, args=(), method=None, jac=None, hess=None, hessp=None, bounds=None, constraints=(), tol=None, callback=None, options=None):
    args = _ensure_tuple(args)
    options = {} if options is None else dict(options)
    method_name = (method or "BFGS").lower()
    x0 = _asarray1d(x0)
    if constraints:
        warnings.warn("minimal scipy.optimize build ignores constraints beyond simple bounds", OptimizeWarning, stacklevel=2)
    if method_name in {"bfgs", "cg", "newton-cg"}:
        return _minimize_bfgs(fun, x0, args, jac, bounds, tol, callback, options)
    if method_name in {"nelder-mead", "powell"}:
        return _minimize_nelder_mead(fun, x0, args, bounds, tol, callback, options)
    raise NotImplementedError(f"unsupported minimize method: {method or 'BFGS'}")


def fmin(func, x0, args=(), xtol=1e-4, ftol=1e-4, maxiter=None, maxfun=None, full_output=False, disp=True, retall=False, callback=None, initial_simplex=None):
    options = {}
    if maxiter is not None:
        options["maxiter"] = maxiter
    options["xatol"] = xtol
    options["fatol"] = ftol
    result = minimize(func, x0, args=args, method="nelder-mead", callback=callback, options=options)
    if full_output:
        return result.x, result.fun, result.nit, result.nfev, int(bool(result.success))
    return result.x


def fmin_bfgs(f, x0, fprime=None, args=(), gtol=1e-5, norm=np.inf, epsilon=np.sqrt(np.finfo(float).eps), maxiter=None, full_output=False, disp=True, retall=False, callback=None, xrtol=0.0, c1=1e-4, c2=0.9, hess_inv0=None):
    options = {"gtol": gtol}
    if maxiter is not None:
        options["maxiter"] = maxiter
    result = minimize(f, x0, args=args, jac=fprime, method="BFGS", callback=callback, options=options)
    if full_output:
        return result.x, result.fun, result.jac, result.hess_inv, result.nfev, result.njev, int(bool(result.success))
    return result.x


def _infer_parameter_count(function):
    signature = inspect.signature(function)
    parameters = list(signature.parameters.values())
    count = 0
    for parameter in parameters[1:]:
        if parameter.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            break
        count += 1
    if count <= 0:
        raise ValueError("could not infer parameter count for curve_fit; pass p0 explicitly")
    return count


def _curve_fit_jacobian(function, xdata, params, yshape):
    params = np.asarray(params, dtype=np.float64)
    base = np.asarray(function(xdata, *params), dtype=np.float64).reshape(-1)
    jacobian = np.zeros((base.size, params.size), dtype=np.float64)
    for index in range(params.size):
        step = np.sqrt(np.finfo(np.float64).eps) * max(1.0, abs(params[index]))
        trial = params.copy()
        trial[index] += step
        values = np.asarray(function(xdata, *trial), dtype=np.float64).reshape(-1)
        jacobian[:, index] = (values - base) / step
    return jacobian.reshape((-1, params.size))


def curve_fit(f, xdata, ydata, p0=None, sigma=None, absolute_sigma=False, check_finite=None, bounds=(-np.inf, np.inf), method=None, jac=None, full_output=False, nan_policy=None, **kwargs):
    x_array = np.asarray(xdata, dtype=np.float64)
    y_array = np.asarray(ydata, dtype=np.float64)
    if p0 is None:
        p0 = np.ones(_infer_parameter_count(f), dtype=np.float64)
    params0 = _asarray1d(p0)
    lb, ub = bounds
    fit_bounds = Bounds(lb, ub)
    if sigma is None:
        weights = None
    else:
        weights = np.asarray(sigma, dtype=np.float64)

    def objective(params):
        residual = np.asarray(f(x_array, *params), dtype=np.float64) - y_array
        if weights is not None:
            residual = residual / weights
        residual = residual.reshape(-1)
        return 0.5 * float(np.dot(residual, residual))

    chosen_method = method or ("nelder-mead" if np.any(np.isfinite(np.asarray(lb))) or np.any(np.isfinite(np.asarray(ub))) else "BFGS")
    result = minimize(objective, params0, method=chosen_method, bounds=fit_bounds, options=kwargs.get("options"))
    popt = np.asarray(result.x, dtype=np.float64)
    jacobian = _curve_fit_jacobian(f, x_array, popt, y_array.shape)
    if weights is not None:
        jacobian = jacobian / weights.reshape(-1, 1)
    try:
        pcov = np.linalg.pinv(jacobian.T @ jacobian)
    except np.linalg.LinAlgError:
        pcov = np.full((popt.size, popt.size), np.inf, dtype=np.float64)
    residual = (np.asarray(f(x_array, *popt), dtype=np.float64) - y_array).reshape(-1)
    if weights is not None:
        residual = residual / weights.reshape(-1)
    dof = max(0, residual.size - popt.size)
    if dof > 0 and not absolute_sigma:
        scale = float(np.dot(residual, residual)) / dof
        pcov = pcov * scale
    if full_output:
        info = {
            "nfev": result.nfev,
            "fvec": residual,
        }
        ier = 1 if result.success else 0
        return popt, pcov, info, result.message, ier
    return popt, pcov


def show_options(solver=None, method=None, disp=True):
    payload = {
        "minimize": ["BFGS", "Nelder-Mead", "Powell"],
        "minimize_scalar": ["golden", "brent", "bounded"],
        "root_scalar": ["bisect", "brentq", "brenth", "ridder", "toms748", "newton", "secant", "halley"],
    }
    if solver is None:
        if disp:
            print(payload)
            return None
        return payload
    key = str(solver)
    value = payload.get(key, [])
    if disp:
        print({key: value})
        return None
    return {key: value}


from scipy._lib._testutils import PytestTester

test = PytestTester(__name__)
del PytestTester
