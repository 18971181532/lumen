"""Lumen netlist parser.

A deliberately small, readable photonic-circuit language:

    circuit mzi_demo
    wavelength 1550                 # nm
    source laser in power=1
    mzi m1 in bar cross dL=20u neff=2.4 ng=4.2 k1=0.5 k2=0.5
    monitor mbar bar
    port in                         # declare an external S-matrix port
    .sweep 1500 1600 0.05           # nm, start stop step
    .end

Lengths use SPICE-style engineering suffixes (100u = 100 um).  Nets are
lower-cased; port names come from the component type, and two ports with
the same net name are connected.
"""

import re

from .components import PORTS, defaults

SUFFIXES = {"t": 1e12, "g": 1e9, "meg": 1e6, "k": 1e3, "m": 1e-3,
            "u": 1e-6, "n": 1e-9, "p": 1e-12, "f": 1e-15}
_NUM = r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?"
_VALUE_RE = re.compile(r"^(" + _NUM + r")\s*([a-zA-Z]*)$")


class NetlistError(ValueError):
    def __init__(self, message, line=None):
        self.line = line
        super().__init__(("line %d: %s" % (line, message)) if line
                         else message)


def parse_value(token, line=None):
    match = _VALUE_RE.match(token.strip())
    if not match:
        raise NetlistError("cannot parse value %r" % token, line)
    number, suffix = match.groups()
    scale = 1.0
    if suffix:
        lower = suffix.lower()
        for key in sorted(SUFFIXES, key=len, reverse=True):
            if lower.startswith(key):
                scale = SUFFIXES[key]
                break
    return float(number) * scale


LENGTH_KEYS = {"length", "dl", "radius", "lam0", "arm"}


def _length(token, line):
    return parse_value(token, line)


def parse(text):
    raw_lines = text.splitlines()
    logical = []
    for idx, raw in enumerate(raw_lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("*"):
            continue
        if "#" in line:
            line = line.split("#", 1)[0].strip()
        if line:
            logical.append((idx, line))

    spec = {"title": "photonic circuit", "wavelength": 1550e-9,
            "instances": [], "ports": [], "sweep": None, "line": 1}
    if logical:
        first = logical[0][1]
        if first.lower().startswith("circuit "):
            spec["title"] = first.split(None, 1)[1].strip()
            logical = logical[1:]
        elif not first.lower().startswith(("circuit", "wavelength", "source",
                                           "port", ".", "wg", "coupler",
                                           "atten", "monitor", "mzi", "ring")):
            spec["title"] = first
            logical = logical[1:]

    ended = False
    for line_no, line in logical:
        fields = line.split()
        head = fields[0].lower()

        if head == ".end":
            ended = True
            break
        if head == ".sweep":
            if len(fields) != 4:
                raise NetlistError(".sweep needs start stop step (nm)", line_no)
            start, stop, step = (parse_value(v, line_no) * 1e-9
                                 for v in fields[1:])
            if start <= 0 or stop <= start or step <= 0:
                raise NetlistError("invalid .sweep range/step", line_no)
            spec["sweep"] = (start, stop, step)
            continue
        if head == "wavelength":
            if len(fields) != 2:
                raise NetlistError("wavelength needs one value (nm)", line_no)
            spec["wavelength"] = parse_value(fields[1], line_no) * 1e-9
            continue
        if head == "port":
            if len(fields) != 2:
                raise NetlistError("port needs a net name", line_no)
            spec["ports"].append(fields[1].lower())
            continue
        if head not in PORTS:
            raise NetlistError("unknown component type %r" % fields[0], line_no)

        nports = PORTS[head]
        if len(fields) < 2 + nports:
            raise NetlistError("%s needs %d nets" % (head, nports), line_no)
        name = fields[1].lower()
        nets = [f.lower() for f in fields[2:2 + nports]]
        params = dict(defaults(head))
        for token in fields[2 + nports:]:
            if "=" not in token:
                raise NetlistError("parameter %r must be key=value" % token,
                                   line_no)
            key, value = token.split("=", 1)
            key = key.lower()
            if key in LENGTH_KEYS:
                params[key] = _length(value, line_no)
            else:
                params[key] = parse_value(value, line_no)
        if head == "wg" and params.get("length", 0) < 0:
            raise NetlistError("waveguide length must be >= 0", line_no)
        if head == "coupler" and not 0 <= params.get("k", 0.5) <= 1:
            raise NetlistError("coupler k must be in [0, 1]", line_no)
        if head == "mzi" and not (0 <= params.get("k1", 0.5) <= 1
                                  and 0 <= params.get("k2", 0.5) <= 1):
            raise NetlistError("mzi k1/k2 must be in [0, 1]", line_no)
        if head == "ring" and not 0 <= params.get("k", 0.2) <= 1:
            raise NetlistError("ring k must be in [0, 1]", line_no)
        spec["instances"].append({"type": head, "name": name,
                                  "ports": nets, "params": params,
                                  "line": line_no})

    if not spec["instances"]:
        raise NetlistError("netlist contains no components")

    names = [inst["name"] for inst in spec["instances"]]
    if len(names) != len(set(names)):
        raise NetlistError("duplicate instance name")
    for net in _all_nets(spec):
        if "@" in net:
            raise NetlistError("'@' is reserved for internal sub-circuit nets")
    arity = {}
    for inst in spec["instances"]:
        for net in inst["ports"]:
            arity.setdefault(net, []).append((inst["name"], inst["type"]))
    for net, users in arity.items():
        if len(users) > 2:
            raise NetlistError(
                "net %r connects %d ports; ideal single-mode nets may "
                "connect at most two (insert a coupler)" % (net, len(users)))
    if not ended:
        pass  # .end is conventional, not mandatory
    spec["arity"] = arity
    return spec


def _all_nets(spec):
    out = []
    for inst in spec["instances"]:
        out.extend(inst["ports"])
    return out


def format_spec(spec):
    """Pretty one-line-per-instance summary (used by CLI/web)."""
    lines = ["%s  (%d components, %d external ports)" %
             (spec["title"], len(spec["instances"]), len(spec["ports"]))]
    for inst in spec["instances"]:
        lines.append("  %-8s %-8s %s" % (inst["name"], inst["type"],
                                         " ".join(inst["ports"])))
    if spec["sweep"]:
        lines.append("  sweep %.6g -> %.6g nm, step %.3g nm" %
                     (spec["sweep"][0] * 1e9, spec["sweep"][1] * 1e9,
                      spec["sweep"][2] * 1e9))
    return "\n".join(lines)
