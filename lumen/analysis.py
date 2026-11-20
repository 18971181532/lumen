"""Spectral analyses and engineering metrics."""

import cmath
import math

from .circuit import Circuit
from .components import C_LIGHT

import copy


def wavelength_grid(start, stop, step):
    if step <= 0 or stop < start:
        raise ValueError("invalid wavelength sweep")
    n = int(math.floor((stop - start) / step + 1e-9)) + 1
    return [start + i * step for i in range(n)]


def spectrum(circuit, start, stop, step, include_sources=True):
    wavelengths = wavelength_grid(start, stop, step)
    monitors = {p["inst"]: {"power": [], "field": []}
                for p in circuit.ports if p["type"] == "monitor"}
    total = []
    for lam in wavelengths:
        sol = circuit.solve(lam, include_sources=include_sources)
        psum = 0.0
        for name in monitors:
            field = sol["monitors"][name]
            pw = abs(field) ** 2
            monitors[name]["power"].append(pw)
            monitors[name]["field"].append(field)
            psum += pw
        total.append(psum)
    return {"wavelengths": wavelengths,
            "wavelengths_nm": [w * 1e9 for w in wavelengths],
            "monitors": monitors, "total_power": total}


def unwrapped_phase(fields):
    phases = [cmath.phase(f) for f in fields]
    out = [phases[0]] if phases else []
    for i in range(1, len(phases)):
        d = phases[i] - phases[i - 1]
        while d > math.pi:
            d -= 2 * math.pi
        while d < -math.pi:
            d += 2 * math.pi
        out.append(out[-1] + d)
    return out


def group_delay(wavelengths, fields, min_fraction=0.1):
    """tau_g = (lambda^2 / 2 pi c) d(arg H)/dlambda, in seconds.

    Points where the field nearly vanishes (a notch or a null) have an
    undefined phase, so a small neighbourhood around them is reported as
    ``None`` instead of a meaningless spike. ``min_fraction`` is relative to
    the peak field amplitude (0.1 means -20 dB in power).
    """
    if len(wavelengths) < 2:
        return [0.0] * len(wavelengths)
    mags = [abs(f) for f in fields]
    peak = max(mags) if mags else 0.0
    valid = [m >= peak * min_fraction for m in mags]
    phases = unwrapped_phase(fields)
    out = []
    for i, lam in enumerate(wavelengths):
        if not valid[i]:
            out.append(None)
            continue
        prev_ok = i > 0 and valid[i - 1]
        next_ok = i < len(valid) - 1 and valid[i + 1]
        if prev_ok and next_ok:
            dphi = ((phases[i + 1] - phases[i - 1]) /
                    (wavelengths[i + 1] - wavelengths[i - 1]))
        elif prev_ok:
            dphi = ((phases[i] - phases[i - 1]) /
                    (wavelengths[i] - wavelengths[i - 1]))
        elif next_ok:
            dphi = ((phases[i + 1] - phases[i]) /
                    (wavelengths[i + 1] - wavelengths[i]))
        else:
            out.append(None)
            continue
        out.append((lam ** 2) / (2 * math.pi * C_LIGHT) * dphi)
    return out


def _extrema(xs, ys, kind="max"):
    out = []
    for i in range(1, len(ys) - 1):
        if kind == "max":
            hit = ys[i] > ys[i - 1] and ys[i] >= ys[i + 1]
        else:
            hit = ys[i] < ys[i - 1] and ys[i] <= ys[i + 1]
        if hit:
            out.append(i)
    if not out:
        return out
    hi, lo = max(ys), min(ys)
    span = hi - lo
    if span <= 0:
        return []
    if kind == "max":
        return [i for i in out if ys[i] >= lo + 0.4 * span]
    return [i for i in out if ys[i] <= lo + 0.6 * span]


def fwhm(xs, ys, center_index):
    peak = ys[center_index]
    base = max(ys) if peak < (max(ys) + min(ys)) / 2 else min(ys)
    level = (peak + base) / 2.0
    left = center_index
    while left > 0 and ((ys[left] - level) * (peak - level) > 0):
        left -= 1
    right = center_index
    while right < len(ys) - 1 and ((ys[right] - level) *
                                   (peak - level) > 0):
        right += 1
    return abs(xs[right] - xs[left])


def metrics(wavelengths_nm, powers, center_nm=1550.0, kind="max"):
    if not powers:
        return {}
    idx0 = min(range(len(wavelengths_nm)),
               key=lambda i: abs(wavelengths_nm[i] - center_nm))
    p0 = powers[idx0]
    hi, lo = max(powers), min(powers)
    ext = _extrema(wavelengths_nm, powers, kind)
    fsr = None
    if len(ext) >= 2:
        gaps = [wavelengths_nm[b] - wavelengths_nm[a]
                for a, b in zip(ext, ext[1:])]
        fsr = sum(gaps) / len(gaps)
    nearest = min(ext, key=lambda i: abs(wavelengths_nm[i] - center_nm)) \
        if ext else None
    width = fwhm(wavelengths_nm, powers, nearest) if nearest is not None \
        else None
    return {
        "loss_db": -10 * math.log10(max(p0, 1e-30)),
        "insertion_loss_db": -10 * math.log10(max(hi, 1e-30)),
        "extinction_db": 10 * math.log10(max(hi, 1e-30) / max(lo, 1e-30)),
        "fsr_nm": fsr,
        "fwhm_nm": width,
        "center_nm": wavelengths_nm[idx0],
        "center_power": p0,
        "resonance_nm": (wavelengths_nm[nearest]
                         if nearest is not None else None),
    }


def summary(result, center_nm=1550.0):
    out = {}
    for name, data in result["monitors"].items():
        trace = data["power"]
        kind = ("max" if sum(trace) / len(trace) < 0.5 * (max(trace) + min(trace))
                else "min")
        out[name] = metrics(result["wavelengths_nm"], trace, center_nm, kind)
        out[name]["group_delay_ps"] = [
            None if t is None else t * 1e12
            for t in group_delay(result["wavelengths"], data["field"])]
    return out


def smatrix_data(circuit, wavelength):
    s = circuit.s_matrix(wavelength)
    mag = [[abs(v) for v in row] for row in s]
    db = [[20 * math.log10(max(v, 1e-30)) for v in row] for row in mag]
    phase = [[math.degrees(cmath.phase(v)) for v in row] for row in s]
    return {"labels": circuit.external_ports, "magnitude": mag,
            "db": db, "phase": phase, "size": len(s),
            "wavelength_nm": wavelength * 1e9,
            "unitary_error": _unitary_error(s),
            "reciprocity_error": _reciprocity_error(s)}


def _reciprocity_error(s):
    n = len(s)
    worst = 0.0
    for i in range(n):
        for j in range(n):
            worst = max(worst, abs(s[i][j] - s[j][i]))
    return worst


def _unitary_error(s):
    n = len(s)
    worst = 0.0
    for i in range(n):
        for j in range(n):
            acc = sum(s[k][i].conjugate() * s[k][j] for k in range(n))
            target = 1.0 if i == j else 0.0
            worst = max(worst, abs(acc - target))
    return worst


def clone_circuit(circuit):
    spec = copy.deepcopy(circuit.spec)
    return Circuit(spec)
