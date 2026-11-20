import math
import unittest

from lumen import tolerance, visual
from lumen.netlist import parse


class ToleranceTests(unittest.TestCase):
    def test_reproducible_seed(self):
        spec = parse(visual.example("tolerance"))
        a = tolerance.run(spec, runs=12, seed=99, points=41)
        b = tolerance.run(spec, runs=12, seed=99, points=41)
        self.assertEqual(a["values"], b["values"])
        self.assertEqual(a["mean"], b["mean"])

    def test_statistics_and_histogram(self):
        spec = parse(visual.example("tolerance"))
        res = tolerance.run(spec, runs=30, seed=7, points=41)
        self.assertEqual(len(res["values"]), 30)
        self.assertEqual(sum(res["histogram"]["counts"]), 30)
        self.assertGreater(res["std"], 0.0)
        self.assertLessEqual(res["min"], res["mean"])
        self.assertGreaterEqual(res["max"], res["mean"])
        self.assertLessEqual(res["p5"], res["p95"])

    def test_auto_centers_on_resonance(self):
        # the ring example is declared at 1550 nm but resonates near 1552.4;
        # the shift metric must recenter itself instead of returning zeros
        spec = parse(visual.example("ring"))
        res = tolerance.run(spec, runs=20, points=41, seed=5)
        self.assertGreater(res["std"], 1e-3)
        self.assertLess(abs(res["mean"]), 0.5)

    def test_zero_sigma_is_deterministic(self):
        spec = parse(visual.example("tolerance"))
        res = tolerance.run(spec, runs=5, sigma_length=0.0,
                            sigma_neff=0.0, sigma_k=0.0, seed=1, points=21)
        self.assertLess(res["std"], 1e-12)

    def test_loss_metric(self):
        spec = parse(visual.example("tolerance"))
        res = tolerance.run(spec, runs=4, metric="loss", seed=3, points=21)
        self.assertEqual(res["metric"], "loss")
        self.assertTrue(all(v >= 0 for v in res["values"]))

    def test_quantile(self):
        self.assertAlmostEqual(tolerance._quantile([1, 2, 3], 0.5), 2.0)
        self.assertAlmostEqual(tolerance._quantile([1, 2, 3], 0.0), 1.0)
        self.assertAlmostEqual(tolerance._quantile([1, 2, 3], 1.0), 3.0)

    def test_unknown_monitor(self):
        spec = parse(visual.example("tolerance"))
        with self.assertRaises(ValueError):
            tolerance.run(spec, runs=2, monitor="nope", points=21)


if __name__ == "__main__":
    unittest.main()
