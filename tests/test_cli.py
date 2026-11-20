import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from lumen import cli

ROOT = Path(__file__).resolve().parent.parent
MZI = str(ROOT / "examples" / "mzi.dev")
RING = str(ROOT / "examples" / "ring.dev")


class CliTests(unittest.TestCase):
    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_parse(self):
        code, out, err = self._run(["parse", RING])
        self.assertEqual(code, 0)
        self.assertIn("ring_add_drop", out)
        self.assertIn("7 primitives", out)

    def test_spectrum_json(self):
        code, out, err = self._run(["spectrum", MZI, "--json"])
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertEqual(data["count"], 401)
        self.assertIn("mb", data["monitors"])
        self.assertAlmostEqual(data["metrics"]["mc"]["fsr_nm"], 28.625,
                               delta=0.5)

    def test_sweep_override_requires_all_values(self):
        code, out, err = self._run(["spectrum", MZI, "--start", "1550"])
        self.assertEqual(code, 2)
        self.assertIn("requires --stop and --step", err)

    def test_smatrix_json(self):
        code, out, err = self._run(["smatrix", str(ROOT / "examples" /
                                                    "smatrix.dev"),
                                    "--wavelength", "1550", "--json"])
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertEqual(data["size"], 4)
        self.assertIn("db", data)

    def test_group_and_layout(self):
        code, out, err = self._run(["group", RING, "--every", "20"])
        self.assertEqual(code, 0, err)
        self.assertIn("lambda_nm", out)
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "ring.svg")
            code, out, err = self._run(["layout", RING, "--out", target])
            self.assertEqual(code, 0, err)
            self.assertTrue(os.path.exists(target))
            self.assertGreater(os.path.getsize(target), 500)

    def test_tolerance_json(self):
        code, out, err = self._run(["tolerance", str(ROOT / "examples" /
                                                     "tolerance.dev"),
                                    "--runs", "8", "--json"])
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertEqual(data["runs"], 8)
        self.assertEqual(len(data["values"]), 8)

    def test_bench(self):
        code, out, err = self._run(["bench", "--stages", "2",
                                    "--points", "5", "--json"])
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertGreater(data["ports"], 0)
        self.assertGreater(data["seconds"], 0)

    def test_bad_netlist_returns_two(self):
        with tempfile.NamedTemporaryFile("w", suffix=".dev", delete=False,
                                         encoding="utf-8") as fh:
            fh.write("coupler c a b c d k=2\n")
            path = fh.name
        try:
            code, out, err = self._run(["parse", path])
        finally:
            os.unlink(path)
        self.assertEqual(code, 2)
        self.assertIn("k must be", err)

    def test_version(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as caught:
                cli.main(["--version"])
        self.assertEqual(caught.exception.code, 0)
        self.assertIn("lumen 1.0.0", out.getvalue())


if __name__ == "__main__":
    unittest.main()
