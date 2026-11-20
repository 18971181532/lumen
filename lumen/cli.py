"""Command-line interface.

Every sub-command can read a netlist from a file or from stdin ("-"), and
every result can be emitted as machine-readable JSON with ``--json``.
Exit code 0 means success and 2 means a netlist/solver error.
"""

import argparse
import json
import math
import os
import sys

from . import __version__, analysis, layout, tolerance, visual
from .circuit import Circuit
from .netlist import NetlistError, format_spec, parse


def _read(path):
    if path == "-":
        return sys.stdin.read()
    with open(path, "r", encoding="utf-8-sig") as fh:
        return fh.read()


def _circuit(path):
    return Circuit(parse(_read(path)))


def _sweep(spec, args, defaults_=(1500e-9, 1600e-9, 0.5e-9)):
    if getattr(args, "start", None) is not None:
        if args.stop is None or args.step is None:
            raise ValueError("--start requires --stop and --step")
        start, stop, step = (args.start * 1e-9, args.stop * 1e-9,
                             args.step * 1e-9)
    elif spec.get("sweep"):
        start, stop, step = spec["sweep"]
    else:
        start, stop, step = defaults_
    if stop <= start or step <= 0:
        raise ValueError("sweep needs stop > start and step > 0")
    points = int(math.floor((stop - start) / step + 1e-9)) + 1
    if points > 5000:
        raise ValueError("sweep has %d points; limit is 5000" % points)
    return start, stop, step


def _json(payload):
    print(json.dumps(payload, indent=2, ensure_ascii=False,
                     default=str))


def _f(value, fmt="%.3f", suffix=""):
    if value is None:
        return "-"
    return (fmt % value) + suffix


def _spectrum_payload(spec, args):
    circuit = Circuit(spec)
    start, stop, step = _sweep(spec, args)
    result = analysis.spectrum(circuit, start, stop, step)
    summary = analysis.summary(result, spec["wavelength"] * 1e9)
    return circuit, result, summary


# ---------------------------------------------------------------- commands
def cmd_parse(args):
    spec = parse(_read(args.netlist))
    circuit = Circuit(spec)
    if args.json:
        _json({"title": spec["title"],
               "components": len(spec["instances"]),
               "primitives": len(circuit.primitives),
               "ports": circuit.port_count(),
               "external_ports": spec["ports"],
               "sweep": spec["sweep"],
               "instances": [{"name": i["name"], "type": i["type"],
                              "ports": i["ports"]}
                             for i in spec["instances"]],
               "nets": circuit.net_summary()})
    else:
        print(format_spec(spec))
        print("  expanded to %d primitives, %d primitive ports" %
              (len(circuit.primitives), circuit.port_count()))


def cmd_spectrum(args):
    spec = parse(_read(args.netlist))
    circuit, result, summary = _spectrum_payload(spec, args)
    if args.json:
        payload = {"title": spec["title"],
                   "count": len(result["wavelengths"]),
                   "wavelengths_nm": result["wavelengths_nm"],
                   "monitors": {},
                   "total_power": result["total_power"],
                   "metrics": summary}
        for name, data in result["monitors"].items():
            payload["monitors"][name] = {
                "power": data["power"],
                "phase_deg": [math.degrees(
                    __import__("cmath").phase(z)) for z in data["field"]],
                "group_delay_ps": summary[name]["group_delay_ps"],
            }
        _json(payload)
        return
    lo, hi = result["wavelengths_nm"][0], result["wavelengths_nm"][-1]
    print("%s - %d points, %.3f to %.3f nm (step %.4g nm)" %
          (spec["title"], len(result["wavelengths"]),
           lo, hi, step_nm(spec, result)))
    print("%-10s %9s %8s %8s %9s %9s %9s" %
          ("monitor", "peak_nm", "IL_dB", "ER_dB", "FSR_nm", "FWHM_nm",
           "tau_max"))
    for name, met in summary.items():
        tau = [v for v in met["group_delay_ps"] if v is not None]
        print("%-10s %9s %8s %8s %9s %9s %9s" %
              (name, _f(met["resonance_nm"], "%.3f"),
               _f(met["insertion_loss_db"], "%.2f"),
               _f(met["extinction_db"], "%.2f"), _f(met["fsr_nm"], "%.2f"),
               _f(met["fwhm_nm"], "%.2f"),
               _f(max(tau) if tau else None, "%.3f", " ps")))


def step_nm(spec, result):
    if len(result["wavelengths"]) < 2:
        return 0.0
    return (result["wavelengths"][1] - result["wavelengths"][0]) * 1e9


def cmd_group(args):
    spec = parse(_read(args.netlist))
    circuit, result, summary = _spectrum_payload(spec, args)
    if args.json:
        data = {"wavelengths_nm": result["wavelengths_nm"],
                "monitors": {name: met["group_delay_ps"]
                             for name, met in summary.items()}}
        _json(data)
        return
    names = list(summary)
    print("%12s " % "lambda_nm" + " ".join("%12s" % (n + "_ps")
                                           for n in names))
    for i in range(0, len(result["wavelengths"]), max(1, args.every)):
        row = "%12.4f " % result["wavelengths_nm"][i]
        row += " ".join("%12s" % _f(summary[n]["group_delay_ps"][i], "%.4f")
                        for n in names)
        print(row)


def cmd_smatrix(args):
    spec = parse(_read(args.netlist))
    circuit = Circuit(spec)
    data = analysis.smatrix_data(circuit, args.wavelength * 1e-9)
    if args.json:
        _json(data)
        return
    print("%s - S matrix at %.3f nm (%d ports)" %
          (spec["title"], args.wavelength, data["size"]))
    print("  |S| (dB)")
    print("        " + " ".join("%9s" % n for n in data["labels"]))
    for name, row in zip(data["labels"], data["db"]):
        print("%-8s" % name + " ".join("%9.2f" % v for v in row))
    print("  phase (deg)")
    print("        " + " ".join("%9s" % n for n in data["labels"]))
    for name, row in zip(data["labels"], data["phase"]):
        print("%-8s" % name + " ".join("%9.1f" % v for v in row))
    print("  S^H S - I: %.3g    reciprocity: %.3g" %
          (data["unitary_error"], data["reciprocity_error"]))


def cmd_tolerance(args):
    spec = parse(_read(args.netlist))
    result = tolerance.run(
        spec, runs=args.runs, sigma_length=args.sigma_length * 1e-9,
        sigma_neff=args.sigma_neff, sigma_k=args.sigma_k,
        metric=args.metric, monitor=args.monitor,
        center_nm=args.center, span_nm=args.span, points=args.points,
        seed=args.seed)
    if args.json:
        _json(result)
        return
    print("Monte Carlo on %s: %d runs, metric=%s, monitor=%s, seed=%d" %
          (spec["title"], result["runs"], result["metric"],
           result["monitor"], result["seed"]))
    print("  mean %.4f   std %.4f   min %.4f   max %.4f   p5 %.4f   p95 %.4f"
          % (result["mean"], result["std"], result["min"], result["max"],
             result["p5"], result["p95"]))
    hist = result["histogram"]
    counts = hist["counts"]
    peak = max(counts) or 1
    for i, count in enumerate(counts):
        lo = hist["low"] + (hist["high"] - hist["low"]) * i / hist["bins"]
        bar = "#" * int(round(48.0 * count / peak))
        print("  %9.4f %5d %s" % (lo, count, bar))


def cmd_layout(args):
    spec = parse(_read(args.netlist))
    data = layout.compute(spec)
    if args.json:
        _json(data)
        return
    if not args.out:
        args.out = os.path.splitext(args.netlist)[0] + ".svg"
    svg = layout.to_svg(data, spec["title"])
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(svg)
    print("wrote %s (%d blocks, %d connections)" %
          (args.out, len(data["nodes"]), len(data["edges"])))


def cmd_run(args):
    spec = parse(_read(args.netlist))
    circuit, result, summary = _spectrum_payload(spec, args)
    payload = {"title": spec["title"],
               "components": len(spec["instances"]),
               "primitives": len(circuit.primitives),
               "ports": circuit.port_count(),
               "metrics": summary,
               "layout": layout.compute(spec)}
    if spec["ports"]:
        payload["smatrix"] = analysis.smatrix_data(
            circuit, spec["wavelength"])
    if args.json:
        _json(payload)
        return
    print(format_spec(spec))
    print("  %d primitive ports after expansion" % circuit.port_count())
    print("  monitor      peak_nm    IL_dB    ER_dB   FSR_nm   FWHM_nm")
    for name, met in summary.items():
        print("  %-10s %9s %8s %8s %8s %8s" %
              (name, _f(met["resonance_nm"]), _f(met["insertion_loss_db"]),
               _f(met["extinction_db"]), _f(met["fsr_nm"]),
               _f(met["fwhm_nm"])))
    if spec["ports"]:
        print("  external ports: %s" % ", ".join(spec["ports"]))


def cmd_bench(args):
    result = visual.bench(args.stages, args.points)
    if args.json:
        _json(result)
        return
    print("Cascade of %d couplers + waveguides: %d ports, %d unknowns" %
          (result["stages"], result["ports"], result["unknowns"]))
    print("  %d wavelength points in %.4f s (%.3f ms/solve, %.2f us/unknown)"
          % (result["points"], result["seconds"], result["ms_per_solve"],
             result["us_per_unknown"]))


def cmd_serve(args):
    from .server import run_server
    run_server(args.port, open_browser=not args.no_open)


# ---------------------------------------------------------------- parser
def build_parser():
    p = argparse.ArgumentParser(
        prog="lumen",
        description="Hierarchical photonic circuit S-parameter simulator")
    p.add_argument("--version", action="version",
                   version="lumen " + __version__)
    sub = p.add_subparsers(dest="command", required=True)

    def netlist_cmd(name, help_text, func):
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("netlist", help="netlist file, or - for stdin")
        sp.add_argument("--json", action="store_true", help="JSON output")
        sp.set_defaults(func=func)
        return sp

    sp = netlist_cmd("parse", "parse and expand a netlist", cmd_parse)

    sp = netlist_cmd("spectrum", "wavelength sweep with metrics",
                     cmd_spectrum)
    _add_sweep_args(sp)

    sp = netlist_cmd("group", "group delay versus wavelength", cmd_group)
    _add_sweep_args(sp)
    sp.add_argument("--every", type=int, default=1,
                    help="print every Nth point (default 1)")

    sp = netlist_cmd("smatrix", "extract the N-port S matrix", cmd_smatrix)
    sp.add_argument("--wavelength", type=float, default=1550.0,
                    help="wavelength in nm (default 1550)")

    sp = netlist_cmd("tolerance", "fabrication Monte Carlo", cmd_tolerance)
    sp.add_argument("--runs", type=int, default=100)
    sp.add_argument("--sigma-length", type=float, default=2.0,
                    help="1-sigma length/radius error in nm (default 2)")
    sp.add_argument("--sigma-neff", type=float, default=0.002)
    sp.add_argument("--sigma-k", type=float, default=0.005)
    sp.add_argument("--metric", choices=("shift", "loss", "er"),
                    default="shift")
    sp.add_argument("--monitor", default=None)
    sp.add_argument("--center", type=float, default=None,
                    help="centre wavelength in nm (default: nearest "
                         "nominal resonance to the netlist wavelength)")
    sp.add_argument("--span", type=float, default=2.0,
                    help="sweep span in nm (default 2)")
    sp.add_argument("--points", type=int, default=81)
    sp.add_argument("--seed", type=int, default=12345)

    sp = netlist_cmd("layout", "auto schematic and SVG export", cmd_layout)
    sp.add_argument("--out", default=None, help="output SVG path")

    sp = netlist_cmd("run", "parse + sweep + metrics in one go", cmd_run)
    _add_sweep_args(sp)

    sp = sub.add_parser("bench", help="solver scaling benchmark")
    sp.add_argument("--stages", type=int, default=4)
    sp.add_argument("--points", type=int, default=21)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_bench)

    sp = sub.add_parser("serve", help="start the local web workbench")
    sp.add_argument("--port", type=int, default=8864)
    sp.add_argument("--no-open", action="store_true",
                    help="do not launch a browser")
    sp.set_defaults(func=cmd_serve)

    return p


def _add_sweep_args(sp):
    sp.add_argument("--start", type=float, default=None,
                    help="start wavelength in nm")
    sp.add_argument("--stop", type=float, default=None,
                    help="stop wavelength in nm")
    sp.add_argument("--step", type=float, default=None,
                    help="step wavelength in nm")


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
        return 0
    except (NetlistError, ValueError, KeyError, OSError) as exc:
        print("lumen: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
