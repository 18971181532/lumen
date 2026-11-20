"""Dependency-free local HTTP workbench for Lumen.

The server exposes a small JSON API and serves the static six-tab UI from
``web/``.  It binds to 127.0.0.1 by default: there is no authentication,
TLS, or multi-user isolation, so it must not be exposed to a network.
"""

import json
import math
import os
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import __version__, analysis, layout, tolerance, visual
from .circuit import Circuit
from .netlist import NetlistError, parse

WEB_DIR = os.path.join(os.path.dirname(__file__), "web")
MAX_BODY = 200 * 1024
MAX_POINTS = 4000


def _payload(text, start=None, stop=None, step=None):
    if not text or not text.strip():
        raise ValueError("empty netlist")
    spec = parse(text)
    circuit = Circuit(spec)
    if start is not None:
        if stop is None or step is None:
            raise ValueError("start requires stop and step")
        start, stop, step = start * 1e-9, stop * 1e-9, step * 1e-9
    elif spec.get("sweep"):
        start, stop, step = spec["sweep"]
    else:
        start, stop, step = 1500e-9, 1600e-9, 0.5e-9
    points = int(math.floor((stop - start) / step + 1e-9)) + 1
    if points > MAX_POINTS:
        raise ValueError("sweep has %d points; web limit is %d" %
                         (points, MAX_POINTS))
    result = analysis.spectrum(circuit, start, stop, step)
    centre = round(spec["wavelength"] * 1e9, 6)
    summary = analysis.summary(result, centre)
    monitors = {}
    for name, data in result["monitors"].items():
        monitors[name] = {
            "power": data["power"],
            "phase_deg": [math.degrees(math.atan2(z.imag, z.real))
                          for z in data["field"]],
            "group_delay_ps": summary[name]["group_delay_ps"],
            "metrics": {k: v for k, v in summary[name].items()
                        if k != "group_delay_ps"},
        }
    smat = None
    if spec["ports"]:
        smat = analysis.smatrix_data(circuit, spec["wavelength"])
    return {
        "title": spec["title"],
        "version": __version__,
        "components": len(spec["instances"]),
        "primitives": len(circuit.primitives),
        "primitive_ports": circuit.port_count(),
        "external_ports": spec["ports"],
        "sweep": {"start_nm": start * 1e9, "stop_nm": stop * 1e9,
                  "step_nm": step * 1e9, "points": len(result["wavelengths"])},
        "wavelength_nm": centre,
        "center_nm": centre,
        "wavelengths_nm": result["wavelengths_nm"],
        "monitors": monitors,
        "total_power": result["total_power"],
        "layout": layout.compute(spec),
        "smatrix": smat,
        "instances": [{"name": i["name"], "type": i["type"],
                       "ports": i["ports"]} for i in spec["instances"]],
        "primitives": [{"name": p["name"], "type": p["type"],
                        "ports": p["ports"], "group": p.get("group")}
                       for p in circuit.primitives],
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "Lumen/" + __version__

    def log_message(self, fmt, *args):
        print("[lumen] " + fmt % args, flush=True)

    # ------------------------------------------------------------ helpers
    def _send(self, code, body, content_type):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False), 
                   "application/json; charset=utf-8")

    def _error(self, exc):
        self._json(400, {"error": str(exc)})

    def _body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_BODY:
            raise ValueError("request body too large")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    # ------------------------------------------------------------ routes
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            return self._file("index.html", "text/html; charset=utf-8")
        if path == "/api/health":
            return self._json(200, {"ok": True, "version": __version__})
        if path == "/api/examples":
            return self._json(200, {
                "examples": [{"name": n, "title": visual.EXAMPLES[n]["title"],
                              "summary": visual.EXAMPLES[n]["summary"],
                              "text": visual.EXAMPLES[n]["text"]}
                             for n in visual.EXAMPLES]})
        if path.startswith("/api/bench"):
            stages = _int_param(self.path, "stages", 4, 1, 8)
            points = _int_param(self.path, "points", 21, 3, 101)
            try:
                return self._json(200, visual.bench(stages, points))
            except Exception as exc:  # noqa: BLE001
                return self._error(exc)
        if path.startswith("/static/"):
            name = path[len("/static/"):]
            ctype = {"style.css": "text/css; charset=utf-8",
                     "app.js": "application/javascript; charset=utf-8"}
            if name not in ctype:
                return self._json(404, {"error": "not found"})
            return self._file(name, ctype[name])
        return self._json(404, {"error": "not found"})

    def _file(self, name, ctype):
        full = os.path.join(WEB_DIR, name)
        if not os.path.exists(full):
            return self._json(404, {"error": "missing web asset %s" % name})
        with open(full, "r", encoding="utf-8") as fh:
            return self._send(200, fh.read(), ctype)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            body = self._body()
            if path == "/api/analyze":
                return self._json(200, _payload(
                    body.get("text", ""), body.get("start"),
                    body.get("stop"), body.get("step")))
            if path == "/api/parse":
                spec = parse(body.get("text", ""))
                circuit = Circuit(spec)
                sweep = spec.get("sweep") or (1500e-9, 1600e-9, 0.5e-9)
                points = (int(math.floor((sweep[1] - sweep[0]) / sweep[2]
                                         + 1e-9)) + 1)
                return self._json(200, {
                    "title": spec["title"], "components": len(spec["instances"]),
                    "primitives": [{"name": p["name"], "type": p["type"],
                                    "ports": p["ports"],
                                    "group": p.get("group")}
                                   for p in circuit.primitives],
                    "primitive_ports": circuit.port_count(),
                    "external_ports": spec["ports"],
                    "sweep": {"start_nm": sweep[0] * 1e9,
                              "stop_nm": sweep[1] * 1e9,
                              "step_nm": sweep[2] * 1e9, "points": points},
                    "layout": layout.compute(spec)})
            if path == "/api/tolerance":
                spec = parse(body.get("text", ""))
                runs = int(body.get("runs", 100))
                if not 1 <= runs <= 300:
                    raise ValueError("runs must be in 1..300 on the web UI")
                res = tolerance.run(
                    spec, runs=runs,
                    sigma_length=float(body.get("sigma_length_nm", 2.0)) * 1e-9,
                    sigma_neff=float(body.get("sigma_neff", 0.002)),
                    sigma_k=float(body.get("sigma_k", 0.005)),
                    metric=body.get("metric", "shift"),
                    monitor=body.get("monitor") or None,
                    center_nm=body.get("center_nm"),
                    span_nm=float(body.get("span_nm", 2.0)),
                    points=int(body.get("points", 81)),
                    seed=int(body.get("seed", 12345)))
                return self._json(200, res)
            if path == "/api/smatrix":
                spec = parse(body.get("text", ""))
                wl = float(body.get("wavelength_nm", 1550.0)) * 1e-9
                return self._json(200, analysis.smatrix_data(
                    Circuit(spec), wl))
            return self._json(404, {"error": "not found"})
        except (NetlistError, ValueError, KeyError, TypeError) as exc:
            return self._error(exc)
        except Exception as exc:  # noqa: BLE001
            return self._json(500, {"error": "internal error: %s" % exc})


def _int_param(path, name, default, low, high):
    from urllib.parse import parse_qs
    values = parse_qs(urlparse(path).query)
    raw = values.get(name, [str(default)])[0]
    value = int(raw)
    return max(low, min(high, value))


def run_server(port=8864, open_browser=True):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    url = "http://127.0.0.1:%d/" % port
    print("Lumen %s workbench: %s  (Ctrl+C to stop)" % (__version__, url))
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        httpd.server_close()
