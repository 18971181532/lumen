import math
import unittest

from lumen import analysis, components, visual
from lumen.circuit import Circuit
from lumen.netlist import parse


class AnalysisTests(unittest.TestCase):
    def test_mzi_fsr(self):
        spec = parse(visual.example("mzi"))
        result = analysis.spectrum(Circuit(spec), *spec["sweep"])
        summary = analysis.summary(result)
        fsr = summary["mc"]["fsr_nm"]
        self.assertIsNotNone(fsr)
        expect = (1550e-9) ** 2 / (4.2 * 20e-6) * 1e9
        self.assertAlmostEqual(fsr, expect, delta=0.6)

    def test_ring_fsr_and_extinction(self):
        spec = parse(visual.example("ring"))
        result = analysis.spectrum(Circuit(spec), *spec["sweep"])
        summary = analysis.summary(result)
        fsr = summary["md"]["fsr_nm"]
        self.assertIsNotNone(fsr)
        expect = (1550e-9) ** 2 / (4.2 * 2 * math.pi * 10e-6) * 1e9
        self.assertAlmostEqual(fsr, expect, delta=0.3)
        self.assertGreater(max(result["monitors"]["md"]["power"]), 0.95)
        self.assertLess(min(result["monitors"]["mt"]["power"]), 0.01)
        self.assertGreater(summary["mt"]["extinction_db"], 30)

    def test_group_delay_of_waveguide(self):
        text = """
circuit wg
source s in power=1
wg w in out length=100u neff=2.4 ng=4.2 loss=0
monitor m out
.sweep 1549 1551 0.01
.end
"""
        spec = parse(text)
        result = analysis.spectrum(Circuit(spec), *spec["sweep"])
        tau = analysis.group_delay(result["wavelengths"],
                                   result["monitors"]["m"]["field"])
        expected = 100e-6 * 4.2 / components.C_LIGHT
        for value in tau[1:-1]:
            self.assertAlmostEqual(value * 1e12, expected * 1e12,
                                   delta=1e-3)

    def test_unwrapped_phase_is_continuous(self):
        fields = [complex(math.cos(0.1 * i), math.sin(0.1 * i))
                  for i in range(80)]
        phase = analysis.unwrapped_phase(fields)
        for i in range(1, len(phase)):
            self.assertLess(abs(phase[i] - phase[i - 1]), math.pi)

    def test_wavelength_grid(self):
        grid = analysis.wavelength_grid(1500e-9, 1501e-9, 0.5e-9)
        self.assertEqual(len(grid), 3)
        with self.assertRaises(ValueError):
            analysis.wavelength_grid(1501e-9, 1500e-9, 0.5e-9)
        with self.assertRaises(ValueError):
            analysis.wavelength_grid(1500e-9, 1501e-9, 0)

    def test_smatrix_data(self):
        spec = parse(visual.example("smatrix"))
        data = analysis.smatrix_data(Circuit(spec), 1550e-9)
        self.assertEqual(data["size"], 4)
        self.assertEqual(data["labels"], ["in", "through", "add", "drop"])
        self.assertLess(data["reciprocity_error"], 1e-9)
        self.assertTrue(all(len(row) == 4 for row in data["db"]))

    def test_metrics_on_flat_trace(self):
        met = analysis.metrics([1500, 1501, 1502], [0.5, 0.5, 0.5])
        self.assertAlmostEqual(met["extinction_db"], 0.0)
        self.assertIsNone(met["fsr_nm"])

    def test_total_power_is_conserved_without_radiation(self):
        spec = parse(visual.example("mzi"))
        result = analysis.spectrum(Circuit(spec), *spec["sweep"])
        for value in result["total_power"]:
            self.assertAlmostEqual(value, 1.0, delta=2e-3)


if __name__ == "__main__":
    unittest.main()
