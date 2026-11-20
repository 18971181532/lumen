import cmath
import math
import unittest

from lumen import analysis, components
from lumen.circuit import Circuit
from lumen.netlist import parse

MZI = """
circuit mzi_test
wavelength 1550
source laser in power=1
mzi m in bar cross dL=%s k1=0.5 k2=0.5 neff=2.4 ng=4.2 loss=0
monitor mb bar
monitor mc cross
.sweep 1500 1600 0.5
.end
"""

RING = """
circuit ring_test
wavelength 1550
port in
port through
port add
port drop
ring r in through add drop radius=10u neff=2.4 ng=4.2 k=0.2 loss=0
.sweep 1540 1560 0.05
.end
"""


class CircuitTests(unittest.TestCase):
    def test_balanced_mzi(self):
        circuit = Circuit(parse(MZI % "0"))
        sol = circuit.solve(1550e-9)
        self.assertAlmostEqual(abs(sol["monitors"]["mb"]) ** 2, 0.0,
                               places=12)
        self.assertAlmostEqual(abs(sol["monitors"]["mc"]) ** 2, 1.0,
                               places=12)
        self.assertAlmostEqual(sum(abs(v) ** 2 for v in
                                   sol["monitors"].values()), 1.0, places=12)

    def test_mzi_phase_formula(self):
        circuit = Circuit(parse(MZI % "20u"))
        sol = circuit.solve(1550e-9)
        dphi = 2 * math.pi * 2.4 * 20e-6 / 1550e-9
        self.assertAlmostEqual(abs(sol["monitors"]["mb"]) ** 2,
                               math.sin(dphi / 2) ** 2, places=10)
        self.assertAlmostEqual(abs(sol["monitors"]["mc"]) ** 2,
                               math.cos(dphi / 2) ** 2, places=10)

    def test_expansion_names_and_counts(self):
        circuit = Circuit(parse(MZI % "20u"))
        names = [p["name"] for p in circuit.primitives]
        self.assertIn("m.c1", names)
        self.assertIn("m.w2", names)
        self.assertEqual(circuit.port_count(), 15)
        self.assertTrue(any("@" in net for net in circuit.nets))

    def test_ring_smatrix_lossless(self):
        circuit = Circuit(parse(RING))
        s = circuit.s_matrix(1550e-9)
        self.assertEqual(len(s), 4)
        err = analysis._unitary_error(s)
        self.assertLess(err, 1e-9)
        self.assertLess(analysis._reciprocity_error(s), 1e-12)
        # a ring with no loss must still conserve power at every wavelength
        for wl in (1548e-9, 1552.65e-9, 1558e-9):
            s2 = circuit.s_matrix(wl)
            self.assertLess(analysis._unitary_error(s2), 1e-9)

    def test_source_off_is_matched_load(self):
        text = """
circuit sw
source s in power=1
wg w in out length=10u loss=0 neff=2.4 ng=4.2
monitor m out
"""
        circuit = Circuit(parse(text))
        on = circuit.solve(1550e-9)
        off = circuit.solve(1550e-9, include_sources=False)
        self.assertAlmostEqual(abs(on["monitors"]["m"]) ** 2, 1.0, places=8)
        self.assertAlmostEqual(abs(off["monitors"]["m"]) ** 2, 0.0, places=12)

    def test_smatrix_requires_single_port_nets(self):
        text = """
circuit bad
port p
source s p power=1
wg w p out length=10u
"""
        circuit = Circuit(parse(text))
        with self.assertRaises(ValueError):
            circuit.s_matrix(1550e-9)

    def test_net_summary(self):
        circuit = Circuit(parse(MZI % "0"))
        summary = circuit.net_summary()
        self.assertTrue(any(row["net"] == "bar" for row in summary))

    def test_default_wavelength_is_used(self):
        spec = parse("wg w a b length=10u\nmonitor m b\nsource s a\n")
        self.assertAlmostEqual(spec["wavelength"], 1550e-9)

    def test_phase_of_longer_arm(self):
        # at 1550 nm the 20 um imbalance is close to a bar null
        circuit = Circuit(parse(MZI % "20u"))
        sol = circuit.solve(1549e-9)
        self.assertLess(abs(sol["monitors"]["mb"]) ** 2, 1e-3)


if __name__ == "__main__":
    unittest.main()
