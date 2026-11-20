import unittest

from lumen import layout, visual
from lumen.netlist import parse


class LayoutTests(unittest.TestCase):
    def test_mzi_layers(self):
        data = layout.compute(parse(visual.example("mzi")))
        self.assertEqual(len(data["nodes"]), 4)
        self.assertEqual(len(data["edges"]), 3)
        names = {n["id"] for n in data["nodes"]}
        self.assertEqual(names, {"laser", "m", "mb", "mc"})
        laser = next(n for n in data["nodes"] if n["id"] == "laser")
        monitors = [n for n in data["nodes"] if n["type"] == "monitor"]
        self.assertLess(laser["x"], monitors[0]["x"])
        self.assertGreater(data["width"], 0)
        self.assertGreater(data["height"], 0)

    def test_ring_and_vernier_layout(self):
        for name in ("ring", "vernier", "tolerance"):
            data = layout.compute(parse(visual.example(name)))
            self.assertGreaterEqual(len(data["nodes"]), 4)
            self.assertGreaterEqual(len(data["edges"]), 2)
            for node in data["nodes"]:
                self.assertGreaterEqual(node["x"], 0)
                self.assertGreaterEqual(node["y"], 0)

    def test_svg_export(self):
        data = layout.compute(parse(visual.example("ring")))
        svg = layout.to_svg(data, "ring <test>")
        self.assertTrue(svg.startswith("<svg"))
        self.assertTrue(svg.rstrip().endswith("</svg>"))
        self.assertIn("ring &lt;test&gt;", svg)
        self.assertIn("laser", svg)
        self.assertEqual(svg.count("<rect"), len(data["nodes"]) + 1)

    def test_port_sides(self):
        data = layout.compute(parse(visual.example("ring")))
        ring = next(n for n in data["nodes"] if n["id"] == "r")
        sides = [p["side"] for p in ring["ports"]]
        self.assertEqual(sides, ["L", "R", "L", "R"])

    def test_empty_source_fallback(self):
        data = layout.compute(parse("wg w in out\nmonitor m out\n"))
        self.assertEqual(len(data["nodes"]), 2)


if __name__ == "__main__":
    unittest.main()
