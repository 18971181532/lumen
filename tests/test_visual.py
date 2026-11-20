import unittest

from lumen import visual
from lumen.netlist import parse


class VisualTests(unittest.TestCase):
    def test_examples_have_metadata(self):
        for name in visual.example_names():
            entry = visual.EXAMPLES[name]
            for key in ("title", "summary", "text"):
                self.assertTrue(entry[key])
            self.assertIn("circuit ", entry["text"])
            self.assertIn(".end", entry["text"])

    def test_every_example_contains_monitor(self):
        for name in visual.example_names():
            if name == "smatrix":
                self.assertIn("port", visual.example(name))
            else:
                self.assertIn("monitor", visual.example(name))

    def test_bench_payload(self):
        result = visual.bench(3, 9)
        self.assertEqual(result["stages"], 3)
        self.assertEqual(result["points"], 9)
        self.assertGreater(result["ports"], 10)
        self.assertEqual(result["unknowns"], result["ports"])
        self.assertGreater(result["seconds"], 0)
        self.assertGreater(result["ms_per_solve"], 0)
        self.assertGreater(result["us_per_unknown"], 0)

    def test_bench_spec_is_valid(self):
        from lumen.circuit import Circuit
        spec = visual.bench_spec(2)
        self.assertEqual(len(spec["instances"]), 1 + 2 * 3 + 1)
        circuit = Circuit(spec)
        self.assertEqual(len(circuit.primitives), 8)
        self.assertGreater(circuit.port_count(), 0)


if __name__ == "__main__":
    unittest.main()
