from __future__ import annotations

import math

import numpy as np

__all__ = [
    "braycurtis",
    "canberra",
    "cdist",
    "chebyshev",
    "cityblock",
    "correlation",
    "cosine",
    "euclidean",
    "hamming",
    "jaccard",
    "minkowski",
    "pdist",
    "sqeuclidean",
    "squareform",
]


def _as_vector(x):
    values = np.asarray(x, dtype=np.float64)
    if values.ndim != 1:
        raise ValueError("distance metrics expect one-dimensional vectors")
    return values


def _as_matrix(x):
    values = np.asarray(x, dtype=np.float64)
    if values.ndim != 2:
        raise ValueError("pairwise distance helpers expect two-dimensional arrays")
    return values


def euclidean(u, v):
    diff = _as_vector(u) - _as_vector(v)
    return float(np.sqrt(np.dot(diff, diff)))


def sqeuclidean(u, v):
    diff = _as_vector(u) - _as_vector(v)
    return float(np.dot(diff, diff))


def cityblock(u, v):
    return float(np.sum(np.abs(_as_vector(u) - _as_vector(v))))


def chebyshev(u, v):
    return float(np.max(np.abs(_as_vector(u) - _as_vector(v))))


def minkowski(u, v, p=2):
    diff = np.abs(_as_vector(u) - _as_vector(v))
    if p == np.inf:
        return float(np.max(diff))
    if p == 1:
        return float(np.sum(diff))
    if p == 2:
        return float(np.sqrt(np.dot(diff, diff)))
    return float(np.sum(diff ** p) ** (1.0 / p))


def cosine(u, v):
    first = _as_vector(u)
    second = _as_vector(v)
    denominator = np.linalg.norm(first) * np.linalg.norm(second)
    if denominator == 0.0:
        return 0.0
    return float(1.0 - np.dot(first, second) / denominator)


def correlation(u, v):
    first = _as_vector(u)
    second = _as_vector(v)
    return cosine(first - np.mean(first), second - np.mean(second))


def canberra(u, v):
    first = _as_vector(u)
    second = _as_vector(v)
    numerator = np.abs(first - second)
    denominator = np.abs(first) + np.abs(second)
    with np.errstate(divide="ignore", invalid="ignore"):
        terms = np.divide(numerator, denominator, out=np.zeros_like(numerator), where=denominator != 0.0)
    return float(np.sum(terms))


def braycurtis(u, v):
    first = _as_vector(u)
    second = _as_vector(v)
    denominator = np.sum(np.abs(first + second))
    if denominator == 0.0:
        return 0.0
    return float(np.sum(np.abs(first - second)) / denominator)


def hamming(u, v):
    first = np.asarray(u)
    second = np.asarray(v)
    if first.shape != second.shape:
        raise ValueError("hamming inputs must have identical shapes")
    return float(np.mean(first != second))


def jaccard(u, v):
    first = np.asarray(u).astype(bool)
    second = np.asarray(v).astype(bool)
    if first.shape != second.shape:
        raise ValueError("jaccard inputs must have identical shapes")
    union = np.count_nonzero(first | second)
    if union == 0:
        return 0.0
    intersection = np.count_nonzero(first & second)
    return float(1.0 - intersection / union)


def _metric_callable(metric, kwargs):
    if callable(metric):
        return lambda u, v: metric(u, v, **kwargs)
    name = str(metric).lower()
    mapping = {
        "euclidean": euclidean,
        "sqeuclidean": sqeuclidean,
        "cityblock": cityblock,
        "manhattan": cityblock,
        "taxicab": cityblock,
        "chebyshev": chebyshev,
        "cosine": cosine,
        "correlation": correlation,
        "canberra": canberra,
        "braycurtis": braycurtis,
        "hamming": hamming,
        "jaccard": jaccard,
        "minkowski": lambda u, v: minkowski(u, v, p=kwargs.get("p", 2)),
    }
    if name not in mapping:
        raise NotImplementedError(f"minimal scipy.spatial.distance does not support metric={metric!r}")
    return mapping[name]


def cdist(XA, XB, metric="euclidean", *, out=None, **kwargs):
    first = _as_matrix(XA)
    second = _as_matrix(XB)
    if first.shape[1] != second.shape[1]:
        raise ValueError("XA and XB must have the same number of columns")
    metric_fn = _metric_callable(metric, kwargs)
    result = np.empty((first.shape[0], second.shape[0]), dtype=np.float64)
    for i, left in enumerate(first):
        for j, right in enumerate(second):
            result[i, j] = metric_fn(left, right)
    if out is not None:
        out[...] = result
        return out
    return result


def pdist(X, metric="euclidean", *, out=None, **kwargs):
    values = _as_matrix(X)
    metric_fn = _metric_callable(metric, kwargs)
    size = values.shape[0]
    result = np.empty(size * (size - 1) // 2, dtype=np.float64)
    index = 0
    for i in range(size - 1):
        for j in range(i + 1, size):
            result[index] = metric_fn(values[i], values[j])
            index += 1
    if out is not None:
        out[...] = result
        return out
    return result


def squareform(X, force="no", checks=True):
    del checks
    values = np.asarray(X)
    if values.ndim == 2 and force != "tovector":
        if values.shape[0] != values.shape[1]:
            raise ValueError("distance matrix must be square")
        size = values.shape[0]
        result = np.empty(size * (size - 1) // 2, dtype=values.dtype)
        index = 0
        for i in range(size - 1):
            for j in range(i + 1, size):
                result[index] = values[i, j]
                index += 1
        return result
    if values.ndim != 1:
        raise ValueError("squareform input must be one-dimensional or square")
    length = values.size
    size = int((1.0 + math.sqrt(1.0 + 8.0 * length)) / 2.0)
    if size * (size - 1) // 2 != length:
        raise ValueError("invalid condensed distance matrix length")
    matrix = np.zeros((size, size), dtype=values.dtype)
    index = 0
    for i in range(size - 1):
        for j in range(i + 1, size):
            matrix[i, j] = matrix[j, i] = values[index]
            index += 1
    return matrix
