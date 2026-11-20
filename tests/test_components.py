import cmath
import math
import unittest

from lumen import components


class ComponentTests(unittest.TestCase):
    def test_neff_dispersion_hits_reference(self):
        p = components.defaults("wg")
        self.assertAlmostEqual(components.neff_at(p, 1550e-9),
                               p["neff"])
        self.assertLess(components.neff_at(p, 1560e-9), p["neff"])

    def test_waveguide_is_reciprocal_and_lossy(self):
        p = components.defaults("wg")
        p["length"] = 100e-6
        p["loss"] = 2.0
        s = components.smatrix({"type": "wg", "ports": ["a", "b"],
                                "params": p}, 1550e-9)
        self.assertEqual(s[0][0], 0j)
        self.assertAlmostEqual(abs(s[0][1]), abs(s[1][0]))
        expect = 10 ** (-2.0 * 0.01 / 20.0)
        self.assertAlmostEqual(abs(s[0][1]), expect, places=12)
        self.assertAlmostEqual(abs(abs(s[0][1]) - 1), 0, places=2)

    def test_waveguide_phase_direction(self):
        p = components.defaults("wg")
        p["length"] = 100e-6
        p["loss"] = 0.0
        p2 = dict(p, length=200e-6)
        self.assertGreater(components.waveguide_phase(p2, 1550e-9),
                           components.waveguide_phase(p, 1550e-9))
        field = components.smatrix(
            {"type": "wg", "ports": ["a", "b"], "params": p}, 1550e-9)[0][1]
        self.assertAlmostEqual(abs(field), 1.0, places=12)

    def test_coupler_unitary_and_power_split(self):
        s = components.smatrix(
            {"type": "coupler", "ports": ["a", "b", "c", "d"],
             "params": {"k": 0.5, "loss": 0.0}}, 1550e-9)
        for i in range(4):
            for j in range(4):
                acc = sum(s[k][i].conjugate() * s[k][j] for k in range(4))
                self.assertAlmostEqual(abs(acc - (1.0 if i == j else 0.0)),
                                       0, places=12)
        self.assertAlmostEqual(abs(s[0][1]) ** 2, 0.5, places=12)
        self.assertAlmostEqual(abs(s[0][3]) ** 2, 0.5, places=12)
        self.assertAlmostEqual(abs(s[0][1]) ** 2 + abs(s[0][3]) ** 2, 1.0,
                               places=12)

    def test_coupler_excess_loss(self):
        s = components.smatrix(
            {"type": "coupler", "ports": ["a", "b", "c", "d"],
             "params": {"k": 0.1, "loss": 1.0}}, 1550e-9)
        total = abs(s[0][1]) ** 2 + abs(s[0][3]) ** 2
        self.assertAlmostEqual(total, 10 ** (-1.0 / 10.0), places=12)

    def test_attenuator(self):
        s = components.smatrix(
            {"type": "atten", "ports": ["a", "b"],
             "params": {"loss": 3.0}}, 1550e-9)
        self.assertAlmostEqual(abs(s[0][1]), 10 ** (-3.0 / 20.0), places=12)

    def test_source_amplitude(self):
        z = components.source_amplitude({"power": 4.0, "phase": 90.0})
        self.assertAlmostEqual(abs(z), 2.0, places=12)
        self.assertAlmostEqual(cmath.phase(z), math.pi / 2, places=12)

    def test_missing_smatrix(self):
        with self.assertRaises(ValueError):
            components.smatrix({"type": "mzi", "ports": [], "params": {}},
                               1550e-9)


if __name__ == "__main__":
    unittest.main()
