from __future__ import annotations

import numpy as np

from .. import issparse
from .. import csr_matrix

__all__ = [
    "LinearOperator",
    "aslinearoperator",
    "cg",
    "eigs",
    "eigsh",
    "inv",
    "norm",
    "spsolve",
    "svds",
]


def _as_dense(value):
    if isinstance(value, LinearOperator):
        raise TypeError("dense conversion is not available for LinearOperator instances")
    if issparse(value):
        return value.toarray()
    return np.asarray(value)


class LinearOperator:
    def __init__(self, shape, matvec, rmatvec=None, matmat=None, dtype=None):
        self.shape = tuple(int(item) for item in shape)
        self.dtype = np.dtype(dtype if dtype is not None else np.float64)
        self._matvec = matvec
        self._rmatvec = rmatvec
        self._matmat = matmat

    def matvec(self, x):
        return np.asarray(self._matvec(np.asarray(x)))

    def rmatvec(self, x):
        if self._rmatvec is None:
            raise NotImplementedError("rmatvec is not available")
        return np.asarray(self._rmatvec(np.asarray(x)))

    def matmat(self, x):
        matrix = np.asarray(x)
        if self._matmat is not None:
            return np.asarray(self._matmat(matrix))
        return np.column_stack([self.matvec(column) for column in matrix.T])

    def dot(self, x):
        values = np.asarray(x)
        if values.ndim == 1:
            return self.matvec(values)
        return self.matmat(values)

    def __matmul__(self, x):
        return self.dot(x)


def aslinearoperator(A):
    if isinstance(A, LinearOperator):
        return A
    dense = _as_dense(A)
    if dense.ndim != 2:
        raise ValueError("linear operators must be two-dimensional")
    return LinearOperator(
        dense.shape,
        matvec=lambda x: dense @ x,
        rmatvec=lambda x: dense.T.conj() @ x,
        matmat=lambda x: dense @ x,
        dtype=dense.dtype,
    )


def norm(A, ord=None):
    return np.linalg.norm(_as_dense(A), ord=ord)


def spsolve(A, b, permc_spec=None, use_umfpack=True):
    del permc_spec, use_umfpack
    return np.linalg.solve(_as_dense(A), np.asarray(b))


def inv(A):
    return csr_matrix(np.linalg.inv(_as_dense(A)))


def cg(A, b, x0=None, rtol=1e-5, atol=0.0, maxiter=None, M=None, callback=None):
    operator = aslinearoperator(A)
    rhs = np.asarray(b, dtype=np.result_type(np.asarray(b), np.float64))
    x = np.zeros_like(rhs) if x0 is None else np.asarray(x0, dtype=rhs.dtype).copy()
    preconditioner = None if M is None else aslinearoperator(M)
    residual = rhs - operator.matvec(x)
    z = residual.copy() if preconditioner is None else preconditioner.matvec(residual)
    direction = z.copy()
    rz_old = np.vdot(residual, z)
    limit = max(float(rtol) * np.linalg.norm(rhs), float(atol))
    if maxiter is None:
        maxiter = max(rhs.size * 10, 1)
    if np.linalg.norm(residual) <= limit:
        return x, 0
    iterations = 0
    for _iteration in range(int(maxiter)):
        matvec = operator.matvec(direction)
        denominator = np.vdot(direction, matvec)
        if denominator == 0:
            return x, -1
        alpha = rz_old / denominator
        x = x + alpha * direction
        residual = residual - alpha * matvec
        iterations += 1
        if callback is not None:
            callback(x)
        if np.linalg.norm(residual) <= limit:
            return x, 0
        z = residual.copy() if preconditioner is None else preconditioner.matvec(residual)
        rz_new = np.vdot(residual, z)
        if rz_old == 0:
            return x, -1
        beta = rz_new / rz_old
        direction = z + beta * direction
        rz_old = rz_new
    return x, iterations


def _select_indices(values, k, which):
    k = int(k)
    total = values.size
    if k <= 0 or k >= total:
        raise ValueError("k must satisfy 0 < k < N")
    mode = str(which).upper()
    if mode == "LM":
        order = np.argsort(np.abs(values))[::-1]
    elif mode == "SM":
        order = np.argsort(np.abs(values))
    elif mode == "LA":
        order = np.argsort(np.real(values))[::-1]
    elif mode == "SA":
        order = np.argsort(np.real(values))
    else:
        raise NotImplementedError(f"minimal sparse.linalg selection mode {which!r} is not supported")
    return order[:k]


def eigs(A, k=6, which="LM", return_eigenvectors=True):
    values, vectors = np.linalg.eig(_as_dense(A))
    selected = _select_indices(values, k, which)
    if return_eigenvectors:
        return values[selected], vectors[:, selected]
    return values[selected]


def eigsh(A, k=6, which="LM", return_eigenvectors=True):
    values, vectors = np.linalg.eigh(_as_dense(A))
    selected = _select_indices(values, k, which)
    if return_eigenvectors:
        return values[selected], vectors[:, selected]
    return values[selected]


def svds(A, k=6, return_singular_vectors=True):
    u, singular_values, vh = np.linalg.svd(_as_dense(A), full_matrices=False)
    if k <= 0 or k >= singular_values.size:
        raise ValueError("k must satisfy 0 < k < min(A.shape)")
    selected = np.argsort(singular_values)[::-1][: int(k)]
    singular_values = singular_values[selected]
    if return_singular_vectors:
        return u[:, selected], singular_values, vh[selected, :]
    return singular_values


from scipy._lib._testutils import PytestTester

test = PytestTester(__name__)
del PytestTester
