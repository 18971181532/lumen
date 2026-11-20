"""Photonic component library: S-matrices for primitives.

Port conventions
    wg         p1 -> p2            (propagation p1 to p2)
    coupler    p1,p2 = bus A left/right ; p3,p4 = bus B left/right
               S = [[0, t, 0, jk], [t, 0, jk, 0],
                    [0, jk, 0, t], [jk, 0, t, 0]]
               with t = sqrt(1-K), k = sqrt(K); K is *power* coupling.
    atten      p1,p2
    source/monitor  1 port (S = 0; handled by the circuit solver)

Sub-circuits (mzi, ring) are expanded in :mod:`lumen.circuit`, so the
solver only ever sees these primitives - loops and feedback come out of
the linear solve naturally.
"""

import cmath
import math

C_LIGHT = 299792458.0
LAMBDA_REF = 1550e-9


def _loss_amplitude(db):
    return 10.0 ** (-db / 20.0)


def neff_at(params, wavelength):
    neff0 = params.get("neff", 2.4)
    ng = params.get("ng", 4.2)
    lam0 = params.get("lam0", LAMBDA_REF)
    slope = (neff0 - ng) / lam0
    return neff0 + slope * (wavelength - lam0)


def waveguide_phase(params, wavelength, extra=0.0):
    length = params.get("length", 0.0)
    phi = 2.0 * math.pi * neff_at(params, wavelength) * length / wavelength
    return phi - params.get("phase", 0.0) - extra


def smatrix(inst, wavelength):
    """Return the port S-matrix of a primitive instance at wavelength (m)."""
    kind = inst["type"]
    p = inst["params"]
    m = len(inst["ports"])

    if kind == "wg":
        t = _loss_amplitude(p.get("loss", 0.0) * p.get("length", 0.0) * 100.0)
        theta = waveguide_phase(p, wavelength)
        field = t * cmath.exp(-1j * theta)
        return [[0j, field], [field, 0j]]

    if kind == "atten":
        t = _loss_amplitude(p.get("loss", 0.0))
        return [[0j, t + 0j], [t + 0j, 0j]]

    if kind == "coupler":
        k = min(max(p.get("k", 0.5), 0.0), 1.0)
        loss = _loss_amplitude(p.get("loss", 0.0))
        tau = math.sqrt(1.0 - k) * loss
        kappa = math.sqrt(k) * loss
        jk = 1j * kappa
        return [[0j, tau + 0j, 0j, jk],
                [tau + 0j, 0j, jk, 0j],
                [0j, jk, 0j, tau + 0j],
                [jk, 0j, tau + 0j, 0j]]

    if kind in ("source", "monitor"):
        return [[0j]]

    raise ValueError("no S-matrix for primitive %r" % kind)


# port counts and layout sides for every *instantiable* type (sub-circuits
# included, for the netlist parser and schematic)
PORTS = {
    "wg": 2, "coupler": 4, "atten": 2, "source": 1, "monitor": 1,
    "mzi": 3, "ring": 4,
}

PORT_SIDES = {
    "wg": ["L", "R"],
    "coupler": ["L", "R", "L", "R"],
    "atten": ["L", "R"],
    "source": ["R"],
    "monitor": ["L"],
    "mzi": ["L", "R", "R"],
    "ring": ["L", "R", "L", "R"],
}


def defaults(kind):
    if kind == "wg":
        return {"length": 100e-6, "neff": 2.4, "ng": 4.2, "loss": 2.0,
                "phase": 0.0}
    if kind == "coupler":
        return {"k": 0.5, "loss": 0.0}
    if kind == "atten":
        return {"loss": 3.0}
    if kind == "source":
        return {"power": 1.0, "phase": 0.0}
    if kind == "monitor":
        return {}
    if kind == "mzi":
        return {"dl": 20e-6, "neff": 2.4, "ng": 4.2, "k1": 0.5, "k2": 0.5,
                "loss": 2.0}
    if kind == "ring":
        return {"radius": 10e-6, "neff": 2.4, "ng": 4.2, "k": 0.2,
                "loss": 2.0}
    return {}


def source_amplitude(params):
    power = params.get("power", 1.0)
    phase = math.radians(params.get("phase", 0.0))
    return cmath.sqrt(power) * cmath.exp(1j * phase)
