from __future__ import annotations

import numpy as np

from . import distance
from .distance import *  # noqa: F401,F403

__all__ = [
    "KDTree",
    "cKDTree",
    "distance",
    "distance_matrix",
]
__all__ += list(getattr(distance, "__all__", ()))


def _minkowski_distance(points, query, p):
    diff = np.abs(points - query)
    if p == np.inf:
        return np.max(diff, axis=-1)
    if p == 1:
        return np.sum(diff, axis=-1)
    if p == 2:
        return np.sqrt(np.sum(diff * diff, axis=-1))
    return np.sum(diff ** p, axis=-1) ** (1.0 / p)


def distance_matrix(x, y, p=2):
    return distance.cdist(x, y, metric="minkowski", p=p)


class KDTree:
    def __init__(
        self,
        data,
        leafsize=10,
        compact_nodes=True,
        copy_data=False,
        balanced_tree=True,
        boxsize=None,
    ):
        del leafsize, compact_nodes, balanced_tree, boxsize
        array = np.asarray(data, dtype=np.float64)
        if array.ndim != 2:
            raise ValueError("KDTree data must be two-dimensional")
        self.data = np.array(array, copy=bool(copy_data))
        self.n, self.m = self.data.shape

    def query(self, x, k=1, eps=0.0, p=2, distance_upper_bound=np.inf, workers=1):
        del eps, workers
        query = np.asarray(x, dtype=np.float64)
        single = query.ndim == 1
        if single:
            query = query.reshape(1, -1)
        if query.shape[-1] != self.m:
            raise ValueError("query point dimensionality does not match training data")
        distances = []
        indices = []
        neighbor_count = int(k)
        if neighbor_count <= 0:
            raise ValueError("k must be a positive integer")
        for point in query:
            point_distances = _minkowski_distance(self.data, point, p)
            order = np.argsort(point_distances)
            point_distances = point_distances[order]
            order = order.astype(np.intp, copy=False)
            mask = point_distances <= distance_upper_bound
            point_distances = point_distances[mask]
            order = order[mask]
            if point_distances.size < neighbor_count:
                padded_distances = np.full(neighbor_count, np.inf, dtype=np.float64)
                padded_indices = np.full(neighbor_count, self.n, dtype=np.intp)
                padded_distances[: point_distances.size] = point_distances
                padded_indices[: order.size] = order
                point_distances = padded_distances
                order = padded_indices
            else:
                point_distances = point_distances[:neighbor_count]
                order = order[:neighbor_count]
            if neighbor_count == 1:
                distances.append(float(point_distances[0]))
                indices.append(int(order[0]))
            else:
                distances.append(point_distances)
                indices.append(order)
        distances = distances[0] if single else np.asarray(distances)
        indices = indices[0] if single else np.asarray(indices)
        return distances, indices

    def query_ball_point(self, x, r, p=2, eps=0.0, workers=1, return_sorted=None, return_length=False):
        del eps, workers, return_sorted
        query = np.asarray(x, dtype=np.float64)
        single = query.ndim == 1
        if single:
            query = query.reshape(1, -1)
        result = []
        for point in query:
            point_distances = _minkowski_distance(self.data, point, p)
            indices = np.flatnonzero(point_distances <= float(r)).tolist()
            result.append(len(indices) if return_length else indices)
        return result[0] if single else result

    def query_pairs(self, r, p=2, eps=0.0, output_type="set"):
        del eps
        pairs = []
        for i in range(self.n):
            distances = _minkowski_distance(self.data[i + 1 :], self.data[i], p)
            hits = np.flatnonzero(distances <= float(r))
            pairs.extend((i, i + 1 + int(hit)) for hit in hits)
        if output_type == "set":
            return set(pairs)
        if output_type == "ndarray":
            return np.asarray(pairs, dtype=np.intp)
        raise ValueError(f"unsupported output_type {output_type!r}")

    def sparse_distance_matrix(self, other, max_distance, p=2, output_type="coo_matrix"):
        from scipy import sparse

        other_tree = other if isinstance(other, KDTree) else KDTree(other)
        rows = []
        columns = []
        values = []
        for i, point in enumerate(self.data):
            distances = _minkowski_distance(other_tree.data, point, p)
            hits = np.flatnonzero(distances <= float(max_distance))
            rows.extend([i] * int(hits.size))
            columns.extend(int(hit) for hit in hits)
            values.extend(float(distances[hit]) for hit in hits)
        matrix = sparse.coo_matrix(
            (
                np.asarray(values, dtype=np.float64),
                (
                    np.asarray(rows, dtype=np.intp),
                    np.asarray(columns, dtype=np.intp),
                ),
            ),
            shape=(self.n, other_tree.n),
        )
        if output_type == "coo_matrix":
            return matrix
        if output_type == "dict":
            row, col, data = sparse.find(matrix)
            return {(int(r), int(c)): float(v) for r, c, v in zip(row, col, data)}
        raise ValueError(f"unsupported output_type {output_type!r}")

    def count_neighbors(self, other, r, p=2, cumulative=True):
        other_tree = other if isinstance(other, KDTree) else KDTree(other)
        radii = np.asarray(r, dtype=np.float64)
        if radii.ndim == 0:
            radii = radii.reshape(1)
        counts = []
        for radius in radii:
            total = 0
            for point in self.data:
                total += int(np.sum(_minkowski_distance(other_tree.data, point, p) <= radius))
            counts.append(total)
        counts = np.asarray(counts, dtype=np.intp)
        if cumulative:
            return counts if counts.size > 1 else int(counts[0])
        if counts.size <= 1:
            return int(counts[0])
        return np.diff(np.concatenate(([0], counts)))


cKDTree = KDTree


from scipy._lib._testutils import PytestTester

test = PytestTester(__name__)
del PytestTester
