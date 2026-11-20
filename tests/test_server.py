import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from lumen import server, visual


class QuietHandler(server.Handler):
    def log_message(self, fmt, *args):
        pass


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        cls.httpd.daemon_threads = True
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever,
                                      daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.thread.join(timeout=3)
        cls.httpd.server_close()

    def get(self, path):
        with urllib.request.urlopen("http://127.0.0.1:%d%s" %
                                    (self.port, path), timeout=10) as r:
            return r.status, r.read().decode("utf-8")

    def post(self, path, payload):
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            "http://127.0.0.1:%d%s" % (self.port, path), data=data,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8"))

    def test_health_and_assets(self):
        status, body = self.get("/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])
        status, css = self.get("/static/style.css")
        self.assertEqual(status, 200)
        self.assertIn("--cyan", css)

    def test_examples(self):
        status, body = self.get("/api/examples")
        self.assertEqual(status, 200)
        names = [e["name"] for e in json.loads(body)["examples"]]
        self.assertIn("mzi", names)
        self.assertIn("ring", names)

    def test_analyze_mzi(self):
        status, data = self.post("/api/analyze",
                                 {"text": visual.example("mzi")})
        self.assertEqual(status, 200)
        self.assertEqual(data["title"], "mzi_balanced")
        self.assertEqual(len(data["wavelengths_nm"]), 401)
        self.assertEqual(len(data["layout"]["nodes"]), 4)
        self.assertEqual(data["primitives"][0]["name"], "laser")
        self.assertAlmostEqual(data["sweep"]["start_nm"], 1500.0)

    def test_analyze_with_override(self):
        status, data = self.post("/api/analyze",
                                 {"text": visual.example("ring"),
                                  "start": 1550, "stop": 1552,
                                  "step": 0.5})
        self.assertEqual(status, 200)
        self.assertEqual(len(data["wavelengths_nm"]), 5)

    def test_smatrix_endpoint(self):
        status, data = self.post("/api/smatrix",
                                 {"text": visual.example("smatrix"),
                                  "wavelength_nm": 1550})
        self.assertEqual(status, 200)
        self.assertEqual(data["size"], 4)

    def test_tolerance_endpoint(self):
        status, data = self.post("/api/tolerance",
                                 {"text": visual.example("tolerance"),
                                  "runs": 3, "points": 21})
        self.assertEqual(status, 200)
        self.assertEqual(len(data["values"]), 3)

    def test_bad_request_is_400(self):
        try:
            self.post("/api/analyze", {"text": "coupler c a b c d k=2"})
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 400)
            payload = json.loads(exc.read().decode("utf-8"))
            self.assertIn("k must be", payload["error"])
        else:
            self.fail("expected HTTP 400")

    def test_bench(self):
        status, body = self.get("/api/bench?stages=2&points=3")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["points"], 3)


if __name__ == "__main__":
    unittest.main()
