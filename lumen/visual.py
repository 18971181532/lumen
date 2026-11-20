"""Built-in examples, benchmark harness and shared presentation helpers."""

import time

from .circuit import Circuit
from .components import defaults
from . import analysis

EXAMPLES = {
    "mzi": {
        "title": "Mach-Zehnder interferometer",
        "summary": "3 dB couplers and a 20 um path imbalance: sinusoidal "
                   "bar/cross response with a 28.6 nm free spectral range.",
        "text": """circuit mzi_balanced
wavelength 1550
source laser in power=1
mzi m in bar cross dL=20u k1=0.5 k2=0.5 neff=2.4 ng=4.2 loss=2
monitor mb bar
monitor mc cross
.sweep 1500 1600 0.25
.end
""",
    },
    "ring": {
        "title": "Add-drop ring resonator",
        "summary": "A 10 um radius ring with k=0.2: through-port dips and "
                   "drop-port peaks spaced by 9.5 nm.",
        "text": """circuit ring_add_drop
wavelength 1550
source laser in power=1
ring r in through add drop radius=10u neff=2.4 ng=4.2 k=0.2 loss=1
monitor mt through
monitor md drop
.sweep 1540 1560 0.05
.end
""",
    },
    "vernier": {
        "title": "Vernier cascade",
        "summary": "Two rings of 10.0 and 10.4 um radius in series. The "
                   "product of their transfer functions gives a long "
                   "effective FSR for coarse WDM channel selection.",
        "text": """circuit vernier_cascade
wavelength 1550
source laser in power=1
ring r1 in through1 add1 drop1 radius=10u neff=2.4 ng=4.2 k=0.1 loss=1
ring r2 drop1 through2 add2 drop2 radius=10.4u neff=2.4 ng=4.2 k=0.1 loss=1
monitor mt through2
monitor md drop2
.sweep 1520 1580 0.02
.end
""",
    },
    "smatrix": {
        "title": "Four-port S matrix",
        "summary": "No sources: four external ports are declared and the "
                   "solver extracts the full 4x4 scattering matrix at 1550 nm.",
        "text": """circuit ring_smatrix
wavelength 1550
port in
port through
port add
port drop
ring r in through add drop radius=10u neff=2.4 ng=4.2 k=0.2 loss=1
.sweep 1540 1560 0.05
.end
""",
    },
    "tolerance": {
        "title": "Fabrication tolerance",
        "summary": "A 10 um add-drop ring near its 1552.6 nm resonance. "
                   "Monte Carlo perturbs radius, effective index and the "
                   "coupling ratio, then tracks resonance drift.",
        "text": """circuit ring_tolerance
wavelength 1552.63
source laser in power=1
ring r in through add drop radius=10u neff=2.4 ng=4.2 k=0.2 loss=1
monitor md drop
monitor mt through
.sweep 1551.9 1553.3 0.02
.end
""",
    },
}


def example_names():
    return list(EXAMPLES)


def example(name):
    if name not in EXAMPLES:
        raise KeyError(name)
    return EXAMPLES[name]["text"]


def bench_spec(stages=4):
    insts = [{"name": "laser", "type": "source", "ports": ["in0"],
              "params": {"power": 1.0, "phase_deg": 0.0}}]
    for i in range(stages):
        params = defaults("coupler")
        params["k"] = 0.5
        insts.append({"name": "c%d" % i, "type": "coupler",
                      "ports": ["in%d" % i, "spare%d" % i,
                                "mid%d" % i, "drop%d" % i],
                      "params": params})
        insts.append({"name": "m%d" % i, "type": "monitor",
                      "ports": ["drop%d" % i], "params": {}})
        wg = defaults("wg")
        wg["length"] = 50e-6
        insts.append({"name": "w%d" % i, "type": "wg",
                      "ports": ["mid%d" % i, "in%d" % (i + 1)],
                      "params": wg})
    insts.append({"name": "out", "type": "monitor",
                  "ports": ["in%d" % stages], "params": {}})
    return {"title": "bench_%d" % stages, "wavelength": 1550e-9,
            "instances": insts, "ports": [],
            "sweep": {"start": 1540e-9, "stop": 1560e-9, "step": 0.5e-9},
            "arity": {}, "source_net": None, "monitor_nets": [],
            "external_ports": [], "port_nets": []}


def bench(stages=4, points=21):
    spec = bench_spec(stages)
    circuit = Circuit(spec)
    grid = analysis.wavelength_grid(1540e-9, 1560e-9,
                                    (20e-9) / max(points - 1, 1))
    t0 = time.perf_counter()
    for lam in grid:
        circuit.solve(lam)
    elapsed = time.perf_counter() - t0
    size = circuit.port_count()
    return {"stages": stages, "ports": circuit.port_count(),
            "unknowns": size, "points": len(grid),
            "seconds": elapsed,
            "ms_per_solve": elapsed / len(grid) * 1e3,
            "us_per_unknown": elapsed / len(grid) / size * 1e6}
