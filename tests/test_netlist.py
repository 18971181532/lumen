import os
import unittest
from pathlib import Path

from lumen import visual
from lumen.netlist import NetlistError, format_spec, parse, parse_value

ROOT = Path(__file__).resolve().parent.parent


class NetlistTests(unittest.TestCase):
    def test_engineering_suffixes(self):
        self.assertAlmostEqual(parse_value("100u"), 100e-6)
        self.assertAlmostEqual(parse_value("2.5n"), 2.5e-9)
        self.assertAlmostEqual(parse_value("10p"), 10e-12)
        self.assertAlmostEqual(parse_value("1k"), 1e3)
        self.assertAlmostEqual(parse_value("2meg"), 2e6)
        self.assertAlmostEqual(parse_value("1e-3"), 1e-3)
        with self.assertRaises(NetlistError):
            parse_value("abc")

    def test_minimal_parse(self):
        spec = parse("""
circuit demo
wavelength 1560
source laser in power=2 phase=90
wg w in out length=100u neff=2.4 ng=4.2 loss=0
monitor m out
.sweep 1550 1570 0.1
.end
""")
        self.assertEqual(spec["title"], "demo")
        self.assertAlmostEqual(spec["wavelength"], 1560e-9)
        self.assertEqual(len(spec["instances"]), 3)
        self.assertEqual(spec["instances"][2]["ports"], ["out"])
        self.assertAlmostEqual(spec["sweep"][0], 1550e-9)
        self.assertAlmostEqual(spec["sweep"][2], 0.1e-9)
        self.assertAlmostEqual(spec["instances"][2]["params"], {})
        self.assertIn("demo", format_spec(spec))

    def test_all_examples_parse(self):
        for name in visual.example_names():
            spec = parse(visual.example(name))
            self.assertTrue(spec["instances"])
            self.assertGreaterEqual(len(spec["instances"]), 1)

    def test_example_files_match_builtins(self):
        for name in visual.example_names():
            path = ROOT / "examples" / (name + ".dev")
            self.assertTrue(path.exists(), path)
            spec = parse(path.read_text(encoding="utf-8"))
            self.assertEqual(spec["title"].split()[0],
                             parse(visual.example(name))["title"].split()[0])

    def test_duplicate_name(self):
        with self.assertRaises(NetlistError):
            parse("wg w in out\nwg w in2 out2\n")

    def test_three_ports_on_one_net(self):
        with self.assertRaises(NetlistError):
            parse("wg w1 a b\nwg w2 a c\nwg w3 a d\n")

    def test_reserved_at_sign(self):
        with self.assertRaises(NetlistError):
            parse("wg w a bad@net\n")

    def test_coupler_ratio_range(self):
        with self.assertRaises(NetlistError):
            parse("coupler c a b c d k=1.2\n")

    def test_unknown_type_and_bad_value(self):
        with self.assertRaises(NetlistError):
            parse("laser l a\n")
        with self.assertRaises(NetlistError):
            parse("wg w a b length=banana\n")

    def test_empty_netlist(self):
        with self.assertRaises(NetlistError):
            parse("# only a comment\n")

    def test_sweep_validation(self):
        with self.assertRaises(NetlistError):
            parse("wg w a b\n.sweep 1600 1500 1\n")
        with self.assertRaises(NetlistError):
            parse("wg w a b\n.sweep 1500 1600\n")


if __name__ == "__main__":
    unittest.main()
