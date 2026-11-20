"""Circuit assembly, sub-circuit expansion and the complex S solver.

A photonic circuit is a set of multi-port components joined by ideal
single-mode nets.  Each port has an incident wave ``a`` and an outgoing
wave ``b = S a``.  A net that joins ports p and q imposes ``a_p = b_q``
and ``a_q = b_p``; sources fix an outgoing wave, monitors terminate a
port.  Collecting every constraint gives one complex linear system

    (I - S P) a = b_source

which is solved by :func:`lumen.complexmatrix.lu_solve`.  Feedback (ring
resonators, cascaded loops) is therefore exact, not an iterative
approximation.
"""

import math

from . import components
from .complexmatrix import lu_solve, zeros
from .netlist import NetlistError


class Circuit:
    def __init__(self, spec):
        self.spec = spec
        self.title = spec["title"]
        self.primitives = []
        self.ports = []          # {index, inst, local, net, type}
        self.nets = {}           # net -> [port dicts]
        self.inst_ports = {}     # primitive name -> [global port indices]
        self.external_ports = list(spec["ports"])
        self._expand()
        self._build_ports()

    # ------------------------------------------------------------ expansion
    def _add(self, kind, name, nets, params, group=None):
        inst = {"type": kind, "name": name, "ports": list(nets),
                "params": dict(params), "group": group}
        self.primitives.append(inst)
        return inst

    def _expand(self):
        for inst in self.spec["instances"]:
            kind, name = inst["type"], inst["name"]
            p = inst["params"]
            nets = inst["ports"]
            if kind in ("wg", "atten"):
                self._add(kind, name, nets, p, name)
            elif kind == "coupler":
                self._add("coupler", name, nets, p, name)
            elif kind == "source":
                self._add("source", name, nets, p, name)
            elif kind == "monitor":
                self._add("monitor", name, nets, p, name)
            elif kind == "mzi":
                prefix = name + "@"
                arm1 = prefix + "arm1"
                arm2 = prefix + "arm2"
                arm1b = prefix + "arm1b"
                arm2b = prefix + "arm2b"
                spare = prefix + "spare"
                self._add("coupler", name + ".c1",
                          [nets[0], arm1, spare, arm2],
                          {"k": p["k1"], "loss": 0.0}, name)
                self._add("wg", name + ".w1", [arm1, arm1b],
                          {"length": p.get("arm", 0.0),
                           "neff": p["neff"], "ng": p["ng"],
                           "loss": p["loss"]}, name)
                self._add("wg", name + ".w2", [arm2, arm2b],
                          {"length": p.get("arm", 0.0) + p["dl"],
                           "neff": p["neff"], "ng": p["ng"],
                           "loss": p["loss"]}, name)
                # C2: p1=arm1b, p2=bar, p3=arm2b, p4=cross
                self._add("coupler", name + ".c2",
                          [arm1b, nets[1], arm2b, nets[2]],
                          {"k": p["k2"], "loss": 0.0}, name)
            elif kind == "ring":
                prefix = name + "@"
                r1a = prefix + "r1a"
                r1b = prefix + "r1b"
                r2a = prefix + "r2a"
                r2b = prefix + "r2b"
                radius = p["radius"]
                arc = math.pi * radius
                # C1: p1=in, p2=through, p3=ring left, p4=ring right
                self._add("coupler", name + ".c1",
                          [nets[0], nets[1], r1a, r1b],
                          {"k": p["k"], "loss": 0.0}, name)
                self._add("wg", name + ".w1", [r1b, r2a],
                          {"length": arc, "neff": p["neff"], "ng": p["ng"],
                           "loss": p["loss"]}, name)
                # C2: p1=add, p2=drop, p3=ring in, p4=ring out
                self._add("coupler", name + ".c2",
                          [nets[2], nets[3], r2a, r2b],
                          {"k": p["k"], "loss": 0.0}, name)
                self._add("wg", name + ".w2", [r2b, r1a],
                          {"length": arc, "neff": p["neff"], "ng": p["ng"],
                           "loss": p["loss"]}, name)
            else:
                raise NetlistError("cannot expand %r" % kind, inst.get("line"))

    def _build_ports(self):
        index = 0
        for inst in self.primitives:
            for local, net in enumerate(inst["ports"]):
                rec = {"index": index, "inst": inst["name"], "local": local,
                       "net": net, "type": inst["type"]}
                self.ports.append(rec)
                self.nets.setdefault(net, []).append(rec)
                self.inst_ports.setdefault(inst["name"], []).append(index)
                index += 1
        for net, recs in self.nets.items():
            if len(recs) > 2:
                raise NetlistError(
                    "net %r has %d primitive ports; a single-mode net must "
                    "join at most two" % (net, len(recs)))
            if len(recs) == 2:
                kinds = sorted(r["type"] for r in recs)
                if kinds == ["source", "source"]:
                    raise NetlistError("two sources share net %r" % net)
                if kinds == ["monitor", "monitor"]:
                    raise NetlistError("two monitors share net %r" % net)
                if kinds == ["monitor", "source"]:
                    raise NetlistError("a source cannot drive a monitor "
                                       "directly (net %r)" % net)
        for port in self.external_ports:
            if port not in self.nets:
                raise NetlistError("declared port %r is not connected" % port)

    # ------------------------------------------------------------ indexing
    def _port_index(self):
        return {p["index"]: p for p in self.ports}

    def _component_ports(self, net):
        return [r for r in self.nets[net] if r["type"] not in
                ("source", "monitor")]

    def _monitor_ports(self):
        return [p for p in self.ports if p["type"] == "monitor"]

    # ------------------------------------------------------------ solver
    def system(self, wavelength, excitations=None, include_sources=True):
        """Assemble A, rhs for ``(I - S P) a = b``."""
        excitations = excitations or {}
        n = len(self.ports)
        a_mat = zeros(n, n)
        rhs = [0j] * n
        port_map = self._port_index()

        # per-component S blocks
        blocks = {}
        for inst in self.primitives:
            blocks[inst["name"]] = components.smatrix(inst, wavelength)

        inst_indices = self.inst_ports

        for net, recs in self.nets.items():
            if len(recs) == 1:
                p = recs[0]
                row = p["index"]
                a_mat[row][row] = 1.0
                rhs[row] = excitations.get(net, 0j)
                continue
            p, q = recs
            sources = [r for r in recs if r["type"] == "source"]
            if sources:
                src = sources[0]
                other = q if p is src else p
                src_idx, other_idx = src["index"], other["index"]
                a_mat[src_idx][src_idx] = 1.0
                a_mat[other_idx][other_idx] = 1.0
                if include_sources:
                    rhs[other_idx] = components.source_amplitude(
                        self._inst(src["inst"])["params"])
                    # a_src = b_other : subtract the S row of `other`
                    block = blocks[other["inst"]]
                    row = block[other["local"]]
                    for col, gidx in enumerate(
                            inst_indices[other["inst"]]):
                        a_mat[src_idx][gidx] -= row[col]
                else:
                    # sources act as matched loads for S-parameter extraction
                    rhs[src_idx] = 0j
                    rhs[other_idx] = 0j
                continue

            # ordinary two-port net: a_p = b_q and a_q = b_p
            for me, you in ((p, q), (q, p)):
                row_idx = me["index"]
                a_mat[row_idx][row_idx] = 1.0
                block = blocks[you["inst"]]
                srow = block[you["local"]]
                for col, gidx in enumerate(inst_indices[you["inst"]]):
                    a_mat[row_idx][gidx] -= srow[col]

        return a_mat, rhs, blocks

    def _inst(self, name):
        for inst in self.primitives:
            if inst["name"] == name:
                return inst
        raise KeyError(name)

    def solve(self, wavelength, excitations=None, include_sources=True):
        a_mat, rhs, blocks = self.system(wavelength, excitations,
                                         include_sources)
        a = lu_solve(a_mat, rhs)
        b = [0j] * len(a)
        for inst in self.primitives:
            idxs = self.inst_ports[inst["name"]]
            block = blocks[inst["name"]]
            for local in range(len(idxs)):
                b[idxs[local]] = sum(block[local][c] * a[idxs[c]]
                                     for c in range(len(idxs)))
        monitors = {p["inst"]: a[p["index"]] for p in self._monitor_ports()}
        return {"a": a, "b": b, "monitors": monitors,
                "source_power": sum(abs(components.source_amplitude(
                    self._inst(p["inst"])["params"])) ** 2
                    for p in self.ports if p["type"] == "source")}

    def s_matrix(self, wavelength):
        """N-port S-matrix between declared external ports."""
        nets = self.external_ports
        if not nets:
            raise ValueError("no ports declared; add 'port <net>' lines")
        indices = []
        for net in nets:
            recs = self.nets[net]
            if len(recs) != 1:
                raise ValueError("port net %r must touch exactly one port "
                                 "(found %d)" % (net, len(recs)))
            indices.append(recs[0]["index"])
        out = [[0j] * len(nets) for _ in nets]
        for i, net in enumerate(nets):
            sol = self.solve(wavelength, excitations={net: 1.0},
                             include_sources=False)
            for j, idx in enumerate(indices):
                out[j][i] = sol["b"][idx]
        return out

    # ------------------------------------------------------------ summaries
    def instances(self):
        return list(self.primitives)

    def net_summary(self):
        return [{"net": net,
                 "ports": ["%s.%d(%s)" % (r["inst"], r["local"], r["type"])
                           for r in recs]}
                for net, recs in self.nets.items()]

    def port_count(self):
        return len(self.ports)
