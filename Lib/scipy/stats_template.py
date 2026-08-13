from __future__ import annotations

import math
from collections import namedtuple
from statistics import NormalDist

import numpy as np

__all__ = [
    "DescribeResult",
    "LinregressResult",
    "ModeResult",
    "PearsonRResult",
    "TtestResult",
    "describe",
    "entropy",
    "gmean",
    "hmean",
    "iqr",
    "kurtosis",
    "linregress",
    "median_abs_deviation",
    "mode",
    "norm",
    "pearsonr",
    "rankdata",
    "sem",
    "skew",
    "spearmanr",
    "ttest_1samp",
    "ttest_ind",
    "ttest_rel",
    "variation",
    "zscore",
]

DescribeResult = namedtuple("DescribeResult", "nobs minmax mean variance skewness kurtosis")
ModeResult = namedtuple("ModeResult", "mode count")


class PearsonRResult(namedtuple("PearsonRResultBase", "statistic pvalue")):
    __slots__ = ()

    @property
    def correlation(self):
        return self.statistic


class LinregressResult(namedtuple("LinregressResultBase", "slope intercept rvalue pvalue stderr intercept_stderr")):
    __slots__ = ()


class TtestResult(namedtuple("TtestResultBase", "statistic pvalue df")):
    __slots__ = ()


_STANDARD_NORMAL = NormalDist()


def _asarray(a):
    return np.asarray(a, dtype=np.float64)


def _nan_policy_mode(a, nan_policy):
    if nan_policy not in {"propagate", "omit", "raise"}:
        raise ValueError(f"unsupported nan_policy {nan_policy!r}")
    values = _asarray(a)
    has_nan = np.isnan(values).any()
    if nan_policy == "raise" and has_nan:
        raise ValueError("input contains NaN")
    return values, nan_policy == "omit"


def _normal_cdf(x):
    values = np.asarray(x, dtype=np.float64)
    vectorized = np.vectorize(lambda item: 0.5 * (1.0 + math.erf(float(item) / math.sqrt(2.0))), otypes=[np.float64])
    return vectorized(values)


def _normal_ppf(q):
    values = np.asarray(q, dtype=np.float64)
    vectorized = np.vectorize(lambda item: _STANDARD_NORMAL.inv_cdf(float(item)), otypes=[np.float64])
    return vectorized(values)


def _two_sided_pvalue(statistic):
    values = np.asarray(statistic, dtype=np.float64)
    return 2.0 * (1.0 - _normal_cdf(np.abs(values)))


def _count(values, axis=None, omit_nan=False):
    if omit_nan:
        return np.sum(~np.isnan(values), axis=axis)
    if axis is None:
        return values.size
    return values.shape[axis]


def _mean(values, axis=None, omit_nan=False):
    return np.nanmean(values, axis=axis) if omit_nan else np.mean(values, axis=axis)


def _var(values, axis=None, ddof=0, omit_nan=False):
    return np.nanvar(values, axis=axis, ddof=ddof) if omit_nan else np.var(values, axis=axis, ddof=ddof)


def _std(values, axis=None, ddof=0, omit_nan=False):
    return np.nanstd(values, axis=axis, ddof=ddof) if omit_nan else np.std(values, axis=axis, ddof=ddof)


def gmean(a, axis=0, dtype=None, weights=None):
    values = np.asarray(a, dtype=np.float64 if dtype is None else dtype)
    if np.any(values < 0):
        raise ValueError("gmean is only defined for non-negative values")
    if weights is None:
        return np.exp(np.mean(np.log(values), axis=axis))
    weights_array = np.asarray(weights, dtype=np.float64)
    return np.exp(np.average(np.log(values), axis=axis, weights=weights_array))


def hmean(a, axis=0, dtype=None):
    values = np.asarray(a, dtype=np.float64 if dtype is None else dtype)
    if np.any(values <= 0):
        raise ValueError("hmean is only defined for strictly positive values")
    return 1.0 / np.mean(1.0 / values, axis=axis)


def zscore(a, axis=0, ddof=0, nan_policy="propagate"):
    values, omit_nan = _nan_policy_mode(a, nan_policy)
    mean = _mean(values, axis=axis, omit_nan=omit_nan)
    std = _std(values, axis=axis, ddof=ddof, omit_nan=omit_nan)
    return (values - np.expand_dims(mean, axis)) / np.expand_dims(std, axis)


def variation(a, axis=0, nan_policy="propagate", ddof=0):
    values, omit_nan = _nan_policy_mode(a, nan_policy)
    return _std(values, axis=axis, ddof=ddof, omit_nan=omit_nan) / _mean(values, axis=axis, omit_nan=omit_nan)


def skew(a, axis=0, bias=True, nan_policy="propagate"):
    values, omit_nan = _nan_policy_mode(a, nan_policy)
    mean = _mean(values, axis=axis, omit_nan=omit_nan)
    centered = values - np.expand_dims(mean, axis)
    m2 = _mean(centered ** 2, axis=axis, omit_nan=omit_nan)
    m3 = _mean(centered ** 3, axis=axis, omit_nan=omit_nan)
    result = m3 / np.power(m2, 1.5)
    if bias:
        return result
    n = _count(values, axis=axis, omit_nan=omit_nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.sqrt(n * (n - 1.0)) / (n - 2.0) * result


def kurtosis(a, axis=0, fisher=True, bias=True, nan_policy="propagate"):
    values, omit_nan = _nan_policy_mode(a, nan_policy)
    mean = _mean(values, axis=axis, omit_nan=omit_nan)
    centered = values - np.expand_dims(mean, axis)
    m2 = _mean(centered ** 2, axis=axis, omit_nan=omit_nan)
    m4 = _mean(centered ** 4, axis=axis, omit_nan=omit_nan)
    result = m4 / (m2 ** 2)
    if fisher:
        result = result - 3.0
    if bias:
        return result
    n = _count(values, axis=axis, omit_nan=omit_nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        adjusted = ((n - 1.0) / ((n - 2.0) * (n - 3.0))) * ((n + 1.0) * result + 6.0)
    return adjusted


def sem(a, axis=0, ddof=1, nan_policy="propagate"):
    values, omit_nan = _nan_policy_mode(a, nan_policy)
    count = _count(values, axis=axis, omit_nan=omit_nan)
    return _std(values, axis=axis, ddof=ddof, omit_nan=omit_nan) / np.sqrt(count)


def entropy(pk, qk=None, base=None, axis=0):
    probabilities = np.asarray(pk, dtype=np.float64)
    probabilities = probabilities / np.sum(probabilities, axis=axis, keepdims=True)
    if qk is None:
        with np.errstate(divide="ignore", invalid="ignore"):
            logs = np.where(probabilities > 0.0, np.log(probabilities), 0.0)
        result = -np.sum(probabilities * logs, axis=axis)
    else:
        comparison = np.asarray(qk, dtype=np.float64)
        comparison = comparison / np.sum(comparison, axis=axis, keepdims=True)
        with np.errstate(divide="ignore", invalid="ignore"):
            logs = np.where(probabilities > 0.0, np.log(probabilities / comparison), 0.0)
        result = np.sum(probabilities * logs, axis=axis)
    if base is not None:
        result = result / math.log(base)
    return result


def rankdata(a, method="average"):
    if method != "average":
        raise NotImplementedError("minimal rankdata supports only method='average'")
    values = _asarray(a).ravel()
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(values.size, dtype=np.float64)
    sorted_values = values[order]
    index = 0
    while index < values.size:
        end = index + 1
        while end < values.size and sorted_values[end] == sorted_values[index]:
            end += 1
        rank = 0.5 * (index + end - 1) + 1.0
        ranks[order[index:end]] = rank
        index = end
    return ranks.reshape(np.asarray(a).shape)


def pearsonr(x, y, alternative="two-sided", method=None):
    if alternative != "two-sided":
        raise NotImplementedError("minimal pearsonr supports only alternative='two-sided'")
    if method is not None:
        raise NotImplementedError("minimal pearsonr does not support resampling methods")
    x_values = _asarray(x).ravel()
    y_values = _asarray(y).ravel()
    if x_values.size != y_values.size:
        raise ValueError("x and y must have the same length")
    if x_values.size < 2:
        raise ValueError("pearsonr requires at least two paired samples")
    x_centered = x_values - x_values.mean()
    y_centered = y_values - y_values.mean()
    denominator = np.sqrt(np.sum(x_centered ** 2) * np.sum(y_centered ** 2))
    if denominator == 0.0:
        raise ValueError("constant input is not supported")
    statistic = float(np.sum(x_centered * y_centered) / denominator)
    if x_values.size <= 3:
        pvalue = 0.0 if abs(statistic) == 1.0 else 1.0
    else:
        clipped = np.clip(statistic, -0.999999999999, 0.999999999999)
        z_value = np.arctanh(clipped) * math.sqrt(x_values.size - 3.0)
        pvalue = float(_two_sided_pvalue(z_value))
    return PearsonRResult(statistic, pvalue)


def spearmanr(a, b=None, axis=0, nan_policy="propagate", alternative="two-sided"):
    if axis not in (0, None):
        raise NotImplementedError("minimal spearmanr supports axis=0 or axis=None")
    if b is None:
        raise ValueError("minimal spearmanr requires both a and b inputs")
    x_values, omit_nan = _nan_policy_mode(a, nan_policy)
    y_values, _ = _nan_policy_mode(b, nan_policy)
    x_flat = x_values.ravel()
    y_flat = y_values.ravel()
    if omit_nan:
        mask = ~(np.isnan(x_flat) | np.isnan(y_flat))
        x_flat = x_flat[mask]
        y_flat = y_flat[mask]
    return pearsonr(rankdata(x_flat), rankdata(y_flat), alternative=alternative)


def linregress(x, y, alternative="two-sided"):
    if alternative != "two-sided":
        raise NotImplementedError("minimal linregress supports only alternative='two-sided'")
    x_values = _asarray(x).ravel()
    y_values = _asarray(y).ravel()
    if x_values.size != y_values.size:
        raise ValueError("x and y must have the same length")
    if x_values.size < 2:
        raise ValueError("linregress requires at least two paired samples")
    x_mean = x_values.mean()
    y_mean = y_values.mean()
    ssxm = np.sum((x_values - x_mean) ** 2)
    ssym = np.sum((y_values - y_mean) ** 2)
    ssxym = np.sum((x_values - x_mean) * (y_values - y_mean))
    slope = ssxym / ssxm
    intercept = y_mean - slope * x_mean
    rvalue = ssxym / math.sqrt(ssxm * ssym)
    n = x_values.size
    if n > 2:
        residual = y_values - (slope * x_values + intercept)
        residual_var = np.sum(residual ** 2) / (n - 2.0)
        stderr = math.sqrt(residual_var / ssxm)
        intercept_stderr = math.sqrt(residual_var * (1.0 / n + x_mean * x_mean / ssxm))
        pvalue = float(_two_sided_pvalue(rvalue * math.sqrt(max(n - 2.0, 1.0))))
    else:
        stderr = 0.0
        intercept_stderr = 0.0
        pvalue = 0.0 if abs(rvalue) == 1.0 else 1.0
    return LinregressResult(float(slope), float(intercept), float(rvalue), float(pvalue), float(stderr), float(intercept_stderr))


def describe(a, axis=0, ddof=1, bias=True, nan_policy="propagate"):
    values, omit_nan = _nan_policy_mode(a, nan_policy)
    nobs = _count(values, axis=axis, omit_nan=omit_nan)
    minmax = (
        np.nanmin(values, axis=axis) if omit_nan else np.min(values, axis=axis),
        np.nanmax(values, axis=axis) if omit_nan else np.max(values, axis=axis),
    )
    mean = _mean(values, axis=axis, omit_nan=omit_nan)
    variance = _var(values, axis=axis, ddof=ddof, omit_nan=omit_nan)
    skewness = skew(values, axis=axis, bias=bias, nan_policy=nan_policy)
    kurt = kurtosis(values, axis=axis, fisher=True, bias=bias, nan_policy=nan_policy)
    return DescribeResult(nobs, minmax, mean, variance, skewness, kurt)


def median_abs_deviation(x, axis=0, center=np.median, scale=1.0, nan_policy="propagate"):
    values, omit_nan = _nan_policy_mode(x, nan_policy)
    center_value = center(values, axis=axis)
    deviation = np.abs(values - np.expand_dims(center_value, axis))
    median = np.nanmedian(deviation, axis=axis) if omit_nan else np.median(deviation, axis=axis)
    return median / scale


def iqr(x, axis=0, rng=(25.0, 75.0), scale=1.0, nan_policy="propagate"):
    values, omit_nan = _nan_policy_mode(x, nan_policy)
    if omit_nan:
        high = np.nanpercentile(values, rng[1], axis=axis)
        low = np.nanpercentile(values, rng[0], axis=axis)
    else:
        high = np.percentile(values, rng[1], axis=axis)
        low = np.percentile(values, rng[0], axis=axis)
    return (high - low) / scale


def mode(a, axis=0, nan_policy="propagate", keepdims=False):
    values, omit_nan = _nan_policy_mode(a, nan_policy)
    if axis is None:
        flattened = values.ravel()
        if omit_nan:
            flattened = flattened[~np.isnan(flattened)]
        unique, counts = np.unique(flattened, return_counts=True)
        index = int(np.argmax(counts))
        mode_value = unique[index]
        count_value = counts[index]
        if keepdims:
            return ModeResult(np.array([mode_value]), np.array([count_value]))
        return ModeResult(mode_value, count_value)

    def _mode_1d(column):
        if omit_nan:
            column = column[~np.isnan(column)]
        unique, counts = np.unique(column, return_counts=True)
        index = int(np.argmax(counts))
        return unique[index], counts[index]

    moved = np.moveaxis(values, axis, 0)
    flat = moved.reshape(moved.shape[0], -1)
    modes = []
    counts = []
    for column in flat.T:
        mode_value, count_value = _mode_1d(column)
        modes.append(mode_value)
        counts.append(count_value)
    mode_array = np.asarray(modes).reshape(moved.shape[1:])
    count_array = np.asarray(counts).reshape(moved.shape[1:])
    if keepdims:
        mode_array = np.expand_dims(mode_array, axis)
        count_array = np.expand_dims(count_array, axis)
    return ModeResult(mode_array, count_array)


def _ttest_result(statistic, df):
    return TtestResult(float(statistic), float(_two_sided_pvalue(statistic)), float(df))


def ttest_1samp(a, popmean, axis=0, nan_policy="propagate", alternative="two-sided"):
    if alternative != "two-sided":
        raise NotImplementedError("minimal ttest_1samp supports only alternative='two-sided'")
    values, omit_nan = _nan_policy_mode(a, nan_policy)
    n = _count(values, axis=axis, omit_nan=omit_nan)
    mean = _mean(values, axis=axis, omit_nan=omit_nan)
    standard_error = sem(values, axis=axis, ddof=1, nan_policy=nan_policy)
    statistic = (mean - popmean) / standard_error
    return _ttest_result(statistic, n - 1.0)


def ttest_ind(a, b, axis=0, equal_var=True, nan_policy="propagate", alternative="two-sided"):
    if alternative != "two-sided":
        raise NotImplementedError("minimal ttest_ind supports only alternative='two-sided'")
    first, omit_nan = _nan_policy_mode(a, nan_policy)
    second, _ = _nan_policy_mode(b, nan_policy)
    n1 = _count(first, axis=axis, omit_nan=omit_nan)
    n2 = _count(second, axis=axis, omit_nan=omit_nan)
    mean1 = _mean(first, axis=axis, omit_nan=omit_nan)
    mean2 = _mean(second, axis=axis, omit_nan=omit_nan)
    var1 = _var(first, axis=axis, ddof=1, omit_nan=omit_nan)
    var2 = _var(second, axis=axis, ddof=1, omit_nan=omit_nan)
    if equal_var:
        pooled = ((n1 - 1.0) * var1 + (n2 - 1.0) * var2) / (n1 + n2 - 2.0)
        standard_error = np.sqrt(pooled * (1.0 / n1 + 1.0 / n2))
        df = n1 + n2 - 2.0
    else:
        standard_error = np.sqrt(var1 / n1 + var2 / n2)
        numerator = (var1 / n1 + var2 / n2) ** 2
        denominator = ((var1 / n1) ** 2) / (n1 - 1.0) + ((var2 / n2) ** 2) / (n2 - 1.0)
        df = numerator / denominator
    statistic = (mean1 - mean2) / standard_error
    return _ttest_result(statistic, df)


def ttest_rel(a, b, axis=0, nan_policy="propagate", alternative="two-sided"):
    if alternative != "two-sided":
        raise NotImplementedError("minimal ttest_rel supports only alternative='two-sided'")
    return ttest_1samp(_asarray(a) - _asarray(b), 0.0, axis=axis, nan_policy=nan_policy, alternative=alternative)


class _NormDistribution:
    def pdf(self, x, loc=0.0, scale=1.0):
        values = (np.asarray(x, dtype=np.float64) - loc) / scale
        return np.exp(-0.5 * values * values) / (abs(scale) * math.sqrt(2.0 * math.pi))

    def logpdf(self, x, loc=0.0, scale=1.0):
        values = (np.asarray(x, dtype=np.float64) - loc) / scale
        return -0.5 * values * values - math.log(abs(scale)) - 0.5 * math.log(2.0 * math.pi)

    def cdf(self, x, loc=0.0, scale=1.0):
        return _normal_cdf((np.asarray(x, dtype=np.float64) - loc) / scale)

    def sf(self, x, loc=0.0, scale=1.0):
        return 1.0 - self.cdf(x, loc=loc, scale=scale)

    def ppf(self, q, loc=0.0, scale=1.0):
        return loc + scale * _normal_ppf(q)

    def isf(self, q, loc=0.0, scale=1.0):
        return self.ppf(1.0 - np.asarray(q, dtype=np.float64), loc=loc, scale=scale)

    def interval(self, confidence, loc=0.0, scale=1.0):
        alpha = (1.0 - confidence) / 2.0
        return self.ppf(alpha, loc=loc, scale=scale), self.ppf(1.0 - alpha, loc=loc, scale=scale)

    def rvs(self, loc=0.0, scale=1.0, size=None, random_state=None):
        rng = np.random.default_rng(random_state)
        return rng.normal(loc=loc, scale=scale, size=size)

    def fit(self, data):
        values = _asarray(data).ravel()
        return float(values.mean()), float(values.std(ddof=0))

    def stats(self, loc=0.0, scale=1.0, moments="mv"):
        results = []
        for code in moments:
            if code == "m":
                results.append(loc)
            elif code == "v":
                results.append(scale ** 2)
            elif code == "s":
                results.append(0.0)
            elif code == "k":
                results.append(0.0)
            else:
                raise ValueError(f"unsupported moment code {code!r}")
        if len(results) == 1:
            return results[0]
        return tuple(results)


norm = _NormDistribution()


from scipy._lib._testutils import PytestTester

test = PytestTester(__name__)
del PytestTester
