from __future__ import annotations

import numpy as np

__all__ = [
    "bsr_matrix",
    "bmat",
    "coo_array",
    "coo_matrix",
    "csc_array",
    "csc_matrix",
    "csr_array",
    "csr_matrix",
    "dia_matrix",
    "diags",
    "dok_matrix",
    "eye",
    "find",
    "hstack",
    "identity",
    "issparse",
    "isspmatrix",
    "isspmatrix_coo",
    "isspmatrix_csc",
    "isspmatrix_csr",
    "kron",
    "kronsum",
    "lil_matrix",
    "linalg",
    "random",
    "spdiags",
    "spmatrix",
    "tril",
    "triu",
    "vstack",
]


def _is_integral_shape_tuple(value):
    return (
        isinstance(value, tuple)
        and len(value) == 2
        and all(isinstance(item, (int, np.integer)) for item in value)
    )


def _coerce_shape(shape):
    if shape is None:
        return None
    result = tuple(int(item) for item in shape)
    if len(result) != 2:
        raise ValueError("shape must be a two-dimensional tuple")
    return result


def _issparse_instance(value):
    return isinstance(value, spmatrix)


def _to_dense(value):
    if _issparse_instance(value):
        return value.toarray()
    return np.asarray(value)


def _dense_from_input(arg1, shape=None, dtype=None):
    shape = _coerce_shape(shape)
    if _issparse_instance(arg1):
        dense = arg1.toarray()
    elif _is_integral_shape_tuple(arg1) and shape is None:
        dense = np.zeros(tuple(int(item) for item in arg1), dtype=np.float64 if dtype is None else dtype)
    elif isinstance(arg1, tuple):
        if len(arg1) == 2 and isinstance(arg1[1], tuple) and len(arg1[1]) == 2:
            if shape is None:
                raise ValueError("shape is required when building a sparse matrix from coordinate data")
            dense = np.zeros(shape, dtype=np.float64 if dtype is None else dtype)
            data, (row, col) = arg1
            dense[np.asarray(row, dtype=np.intp), np.asarray(col, dtype=np.intp)] = np.asarray(data, dtype=dtype)
        elif len(arg1) == 3:
            if shape is None:
                raise ValueError("shape is required when building a sparse matrix from CSR/CSC data")
            data, indices, indptr = arg1
            dense = np.zeros(shape, dtype=np.float64 if dtype is None else dtype)
            data = np.asarray(data, dtype=dtype)
            indices = np.asarray(indices, dtype=np.intp)
            indptr = np.asarray(indptr, dtype=np.intp)
            for row in range(shape[0]):
                start = indptr[row]
                stop = indptr[row + 1]
                dense[row, indices[start:stop]] = data[start:stop]
        else:
            dense = np.asarray(arg1, dtype=dtype)
    else:
        dense = np.asarray(arg1, dtype=dtype)
    if dense.ndim != 2:
        raise ValueError("sparse matrices must be two-dimensional")
    if shape is not None and tuple(dense.shape) != shape:
        raise ValueError(f"matrix shape {dense.shape!r} does not match requested shape {shape!r}")
    return np.array(dense, dtype=dtype if dtype is not None else None, copy=False)


def _construct_sparse(array, format_name):
    mapping = {
        "csr": csr_matrix,
        "csc": csc_matrix,
        "coo": coo_matrix,
    }
    cls = mapping.get(format_name, csr_matrix)
    return cls(array)


class spmatrix:
    __array_priority__ = 1000
    format = "generic"

    def __init__(self, arg1, shape=None, dtype=None, copy=False):
        self._array = np.array(_dense_from_input(arg1, shape=shape, dtype=dtype), copy=bool(copy))

    @property
    def A(self):
        return self.toarray()

    @property
    def T(self):
        return self.transpose()

    @property
    def dtype(self):
        return self._array.dtype

    @property
    def ndim(self):
        return 2

    @property
    def nnz(self):
        return int(np.count_nonzero(self._array))

    @property
    def shape(self):
        return self._array.shape

    @property
    def size(self):
        return self._array.size

    @property
    def data(self):
        row, col = np.nonzero(self._array)
        return self._array[row, col]

    @property
    def indices(self):
        row, col = np.nonzero(self._array)
        return col if self.format != "csc" else row

    @property
    def indptr(self):
        axis = 1 if self.format != "csc" else 0
        counts = np.count_nonzero(self._array, axis=axis)
        return np.concatenate(([0], np.cumsum(counts, dtype=np.intp)))

    def __array__(self, dtype=None):
        return np.asarray(self._array, dtype=dtype)

    def __getitem__(self, key):
        return self._array[key]

    def __setitem__(self, key, value):
        self._array[key] = value

    def __repr__(self):
        return f"{self.__class__.__name__}({self._array!r})"

    def __add__(self, other):
        result = self._array + _to_dense(other)
        return self.__class__(result) if np.asarray(result).ndim == 2 else result

    def __sub__(self, other):
        result = self._array - _to_dense(other)
        return self.__class__(result) if np.asarray(result).ndim == 2 else result

    def __mul__(self, other):
        if np.isscalar(other):
            return self.__class__(self._array * other)
        result = self._array @ _to_dense(other)
        return self.__class__(result) if np.asarray(result).ndim == 2 else result

    def __rmul__(self, other):
        if np.isscalar(other):
            return self.__class__(other * self._array)
        result = _to_dense(other) @ self._array
        return self.__class__(result) if np.asarray(result).ndim == 2 else result

    def __matmul__(self, other):
        result = self._array @ _to_dense(other)
        return self.__class__(result) if np.asarray(result).ndim == 2 else result

    def __rmatmul__(self, other):
        result = _to_dense(other) @ self._array
        return self.__class__(result) if np.asarray(result).ndim == 2 else result

    def __truediv__(self, other):
        return self.__class__(self._array / other)

    def __neg__(self):
        return self.__class__(-self._array)

    def asformat(self, format=None, copy=False):
        if format is None or format == self.format:
            return self.copy() if copy else self
        return _construct_sparse(self._array.copy() if copy else self._array, str(format).lower())

    def astype(self, dtype, copy=True):
        return self.__class__(self._array.astype(dtype, copy=copy))

    def copy(self):
        return self.__class__(self._array.copy())

    def count_nonzero(self):
        return self.nnz

    def diagonal(self, k=0):
        return np.diagonal(self._array, offset=k)

    def dot(self, other):
        result = self._array.dot(_to_dense(other))
        return self.__class__(result) if np.asarray(result).ndim == 2 else result

    def eliminate_zeros(self):
        return None

    def getH(self):
        return self.__class__(self._array.conj().T)

    def getnnz(self, axis=None):
        if axis is None:
            return self.nnz
        return np.count_nonzero(self._array, axis=axis)

    def maximum(self, other):
        return self.__class__(np.maximum(self._array, _to_dense(other)))

    def minimum(self, other):
        return self.__class__(np.minimum(self._array, _to_dense(other)))

    def multiply(self, other):
        return self.__class__(self._array * _to_dense(other))

    def nonzero(self):
        return np.nonzero(self._array)

    def power(self, n):
        return self.__class__(self._array ** n)

    def setdiag(self, values, k=0):
        rows, cols = np.diag_indices(min(self.shape))
        if k >= 0:
            rows = rows[: self.shape[1] - k]
            cols = cols[: self.shape[1] - k] + k
        else:
            rows = rows[-k :]
            cols = cols[-k :]
        self._array[rows, cols] = values

    def sum(self, axis=None, dtype=None, out=None):
        return self._array.sum(axis=axis, dtype=dtype, out=out)

    def todense(self):
        return np.matrix(self._array)

    def toarray(self, order=None, out=None):
        if out is not None:
            out[...] = self._array
            return out
        if order in (None, "C", "K"):
            return np.array(self._array, copy=True)
        return np.array(self._array, order=order, copy=True)

    def tocoo(self, copy=False):
        return coo_matrix(self._array.copy() if copy else self._array)

    def tocsc(self, copy=False):
        return csc_matrix(self._array.copy() if copy else self._array)

    def tocsr(self, copy=False):
        return csr_matrix(self._array.copy() if copy else self._array)

    def trace(self):
        return np.trace(self._array)

    def transpose(self, axes=None, copy=False):
        if axes not in (None, (1, 0)):
            raise ValueError("sparse matrices only support two-dimensional transposes")
        return self.__class__(self._array.T.copy() if copy else self._array.T)


class csr_matrix(spmatrix):
    format = "csr"


class csc_matrix(spmatrix):
    format = "csc"


class coo_matrix(spmatrix):
    format = "coo"

    @property
    def row(self):
        return np.nonzero(self._array)[0]

    @property
    def col(self):
        return np.nonzero(self._array)[1]


csr_array = csr_matrix
csc_array = csc_matrix
coo_array = coo_matrix
bsr_matrix = csr_matrix
dia_matrix = csr_matrix
dok_matrix = coo_matrix
lil_matrix = coo_matrix


def issparse(x):
    return _issparse_instance(x)


def isspmatrix(x):
    return _issparse_instance(x)


def isspmatrix_csr(x):
    return isinstance(x, csr_matrix)


def isspmatrix_csc(x):
    return isinstance(x, csc_matrix)


def isspmatrix_coo(x):
    return isinstance(x, coo_matrix)


def eye(m, n=None, k=0, dtype=float, format=None):
    n = m if n is None else n
    dense = np.eye(int(m), int(n), k=int(k), dtype=dtype)
    return _construct_sparse(dense, format or "csr")


def identity(n, dtype=float, format=None):
    return eye(n, n=n, dtype=dtype, format=format)


def diags(diagonals, offsets=0, shape=None, format=None, dtype=None):
    if np.isscalar(offsets):
        offsets = [int(offsets)]
        diagonals = [diagonals]
    else:
        offsets = [int(value) for value in offsets]
    if shape is None:
        max_len = max(np.asarray(diagonal).size for diagonal in diagonals)
        size = max_len + max(max(offsets, default=0), -min(offsets, default=0))
        shape = (size, size)
    dense = np.zeros(tuple(int(item) for item in shape), dtype=np.float64 if dtype is None else dtype)
    for diagonal, offset in zip(diagonals, offsets):
        dense += np.diag(np.asarray(diagonal, dtype=dtype), k=offset)
    return _construct_sparse(dense, format or "csr")


def spdiags(data, diags_values, m, n, format=None):
    diagonals = [np.asarray(diagonal) for diagonal in np.asarray(data)]
    return diags(diagonals, offsets=list(np.asarray(diags_values).ravel()), shape=(int(m), int(n)), format=format)


def vstack(blocks, format=None, dtype=None):
    dense = np.vstack([_to_dense(block) for block in blocks])
    if dtype is not None:
        dense = dense.astype(dtype, copy=False)
    return _construct_sparse(dense, format or "csr")


def hstack(blocks, format=None, dtype=None):
    dense = np.hstack([_to_dense(block) for block in blocks])
    if dtype is not None:
        dense = dense.astype(dtype, copy=False)
    return _construct_sparse(dense, format or "csr")


def bmat(blocks, format=None, dtype=None):
    rows = []
    for row in blocks:
        rows.append(np.hstack([_to_dense(block) for block in row]))
    dense = np.vstack(rows)
    if dtype is not None:
        dense = dense.astype(dtype, copy=False)
    return _construct_sparse(dense, format or "csr")


def find(A):
    dense = _to_dense(A)
    row, col = np.nonzero(dense)
    return row, col, dense[row, col]


def triu(A, k=0, format=None):
    return _construct_sparse(np.triu(_to_dense(A), k=int(k)), format or getattr(A, "format", "csr"))


def tril(A, k=0, format=None):
    return _construct_sparse(np.tril(_to_dense(A), k=int(k)), format or getattr(A, "format", "csr"))


def kron(A, B, format=None):
    return _construct_sparse(np.kron(_to_dense(A), _to_dense(B)), format or "csr")


def kronsum(A, B, format=None):
    left = _to_dense(A)
    right = _to_dense(B)
    result = np.kron(np.eye(right.shape[0], dtype=left.dtype), left) + np.kron(right, np.eye(left.shape[0], dtype=right.dtype))
    return _construct_sparse(result, format or "csr")


def random(m, n, density=0.01, format="coo", dtype=float, random_state=None, data_rvs=None):
    rng = np.random.default_rng(random_state)
    total = int(m) * int(n)
    count = int(round(float(density) * total))
    dense = np.zeros((int(m), int(n)), dtype=dtype)
    if count > 0:
        chosen = rng.choice(total, size=min(count, total), replace=False)
        row = chosen // int(n)
        col = chosen % int(n)
        if data_rvs is None:
            data = rng.random(chosen.size).astype(dtype, copy=False)
        else:
            data = np.asarray(data_rvs(chosen.size), dtype=dtype)
        dense[row, col] = data
    return _construct_sparse(dense, format or "coo")


from . import linalg  # noqa: E402
from scipy._lib._testutils import PytestTester

test = PytestTester(__name__)
del PytestTester
