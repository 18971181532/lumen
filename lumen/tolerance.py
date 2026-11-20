"""Fabrication-tolerance Monte Carlo.

Perturbs the top-level instance parameters ( waveguide length, effective
index, coupler splitting ratio ), rebuilds the circuit and tracks a
spectral figure of merit.  Everything is seeded, so results are
reproducible.
"""

import copy
import math
import random

from .circuit import Circuit
from . import analysis


def perturb(spec, rng, sigma_length=0.0, sigma_neff=0.0, sigma_k=0.0):
    out = copy.deepcopy(spec)
    for inst in out["instances"]:
        kind, p = inst["type"], inst["params"]
        if kind == "wg":
            p["length"] = max(0.0, p["length"] +
                              rng.gauss(0.0, sigma_length))
            if sigma_neff:
                p["neff"] += rng.gauss(0.0, sigma_neff)
        elif kind == "coupler":
            if sigma_k:
                p["k"] = min(1.0, max(0.0, p["k"] +
                                     rng.gauss(0.0, sigma_k)))
        elif kind == "mzi":
            p["dl"] = max(0.0, p["dl"] + rng.gauss(0.0, sigma_length))
            if sigma_neff:
                p["neff"] += rng.gauss(0.0, sigma_neff)
            if sigma_k:
                p["k1"] = min(1.0, max(0.0, p["k1"] +
                                      rng.gauss(0.0, sigma_k)))
                p["k2"] = min(1.0, max(0.0, p["k2"] +
                                      rng.gauss(0.0, sigma_k)))
        elif kind == "ring":
            p["radius"] = max(0.0, p["radius"] +
                              rng.gauss(0.0, sigma_length))
            if sigma_neff:
                p["neff"] += rng.gauss(0.0, sigma_neff)
            if sigma_k:
                p["k"] = min(1.0, max(0.0, p["k"] +
                                     rng.gauss(0.0, sigma_k)))
    return out


def _metric_value(trace, wavelengths_nm, center_nm, metric, kind):
    if metric == "loss":
        idx = min(range(len(wavelengths_nm)),
                  key=lambda i: abs(wavelengths_nm[i] - center_nm))
        return -10 * math.log10(max(trace[idx], 1e-30))
    if metric == "er":
        hi, lo = max(trace), min(trace)
        return 10 * math.log10(max(hi, 1e-30) / max(lo, 1e-30))
    # resonance shift (nm, relative to the nominal centre)
    if kind == "max":
        idxs = [i for i in range(1, len(trace) - 1)
                if trace[i] > trace[i - 1] and trace[i] >= trace[i + 1]]
    else:
        idxs = [i for i in range(1, len(trace) - 1)
                if trace[i] < trace[i - 1] and trace[i] <= trace[i + 1]]
    if not idxs:
        return 0.0
    nearest = min(idxs, key=lambda i: abs(wavelengths_nm[i] - center_nm))
    return wavelengths_nm[nearest] - center_nm


def _find_center(circuit, monitor, w0_nm, search_nm=20.0):
    """Locate the nominal resonance nearest the netlist wavelength."""
    probe = analysis.spectrum(circuit, (w0_nm - search_nm) * 1e-9,
                              (w0_nm + search_nm) * 1e-9, 0.1e-9)
    trace = probe["monitors"][monitor]["power"]
    wl = probe["wavelengths_nm"]
    kind = "max" if sum(trace) / len(trace) < 0.5 * (max(trace) + min(trace)) \
        else "min"
    idxs = _extrema_indices(trace, kind)
    if not idxs:
        return w0_nm
    nearest = min(idxs, key=lambda i: abs(wl[i] - w0_nm))
    return wl[nearest]


def _extrema_indices(trace, kind):
    if kind == "max":
        return [i for i in range(1, len(trace) - 1)
                if trace[i] > trace[i - 1] and trace[i] >= trace[i + 1]]
    return [i for i in range(1, len(trace) - 1)
            if trace[i] < trace[i - 1] and trace[i] <= trace[i + 1]]


def run(spec, runs=100, sigma_length=2.0e-9, sigma_neff=0.002,
        sigma_k=0.005, metric="shift", monitor=None, center_nm=None,
        span_nm=2.0, points=81, seed=12345):
    rng = random.Random(seed)
    nominal = Circuit(spec)
    names = [p["inst"] for p in nominal.ports if p["type"] == "monitor"]
    if not names:
        raise ValueError("tolerance analysis needs at least one monitor")
    name = monitor or names[0]
    if name not in names:
        raise ValueError("unknown monitor %r" % monitor)
    if center_nm is None:
        center_nm = _find_center(nominal, name, spec["wavelength"] * 1e9)
    grid = analysis.wavelength_grid((center_nm - span_nm / 2) * 1e-9,
                                    (center_nm + span_nm / 2) * 1e-9,
                                    span_nm / max(points - 1, 1) * 1e-9)
    # infer the resonance polarity from the nominal trace
    probe = analysis.spectrum(nominal, grid[0], grid[-1],
                              grid[1] - grid[0])
    trace = probe["monitors"][name]["power"]
    kind = "max" if sum(trace) / len(trace) < 0.5 * (max(trace) + min(trace)) \
        else "min"
    values = []
    for _ in range(max(1, int(runs))):
        perturbed = Circuit(perturb(spec, rng, sigma_length, sigma_neff,
                                    sigma_k))
        spec2 = analysis.spectrum(perturbed, grid[0], grid[-1],
                                  grid[1] - grid[0])
        values.append(_metric_value(spec2["monitors"][name]["power"],
                                    spec2["wavelengths_nm"], center_nm,
                                    metric, kind))
    return _summarise(values, metric, name, runs, seed)


def _summarise(values, metric, monitor, runs, seed):
    n = len(values)
    mean = sum(values) / n
    std = math.sqrt(sum((v - mean) ** 2 for v in values) / max(n - 1, 1))
    lo, hi = min(values), max(values)
    if hi == lo:
        hi = lo + 1e-12
    bins = 20
    width = (hi - lo) / bins
    counts = [0] * bins
    for v in values:
        idx = min(bins - 1, int((v - lo) / width))
        counts[idx] += 1
    return {"metric": metric, "monitor": monitor, "runs": runs, "seed": seed,
            "values": values, "mean": mean, "std": std, "min": lo,
            "max": hi, "p5": _quantile(values, 0.05),
            "p95": _quantile(values, 0.95),
            "histogram": {"low": lo, "high": hi, "bins": bins,
                          "counts": counts}}


def _quantile(values, q):
    ordered = sorted(values)
    if not ordered:
        return 0.0
    pos = q * (len(ordered) - 1)
    lo = int(math.floor(pos))
    hi = min(len(ordered) - 1, lo + 1)
    w = pos - lo
    return ordered[lo] * (1 - w) + ordered[hi] * w
