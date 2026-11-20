"""Automatic schematic layout for hierarchical photonic netlists.

The layout is a layered graph: sources sit in the first column, monitors in
the last, and every other block is placed by BFS depth from the sources.
Because the netlist is a graph rather than a fixed template, feedback paths
(ring resonators, recursive meshes) simply appear as backward edges.
"""

from .components import PORTS

PORT_SIDES = {
    "wg": ["L", "R"],
    "coupler": ["L", "R", "L", "R"],
    "atten": ["L", "R"],
    "source": ["R"],
    "monitor": ["L"],
    "mzi": ["L", "R", "R"],
    "ring": ["L", "R", "L", "R"],
}

SIZES = {
    "wg": (130, 58),
    "atten": (110, 58),
    "coupler": (130, 86),
    "mzi": (170, 96),
    "ring": (160, 104),
    "source": (96, 58),
    "monitor": (100, 58),
}

COL_WIDTH = 250
ROW_HEIGHT = 130
MARGIN = 50


def _port_count(kind):
    return len(PORTS[kind])


def compute(spec):
    insts = spec["instances"]
    users = {}
    for inst in insts:
        for idx, net in enumerate(inst["ports"]):
            users.setdefault(net, []).append((inst["name"], idx))

    edges = []
    adjacency = {}
    for net, members in users.items():
        if len(members) != 2:
            continue
        a, b = members
        if a[0] == b[0]:
            continue
        edges.append({"net": net, "a": {"node": a[0], "port": a[1]},
                      "b": {"node": b[0], "port": b[1]}})
        adjacency.setdefault(a[0], []).append(b[0])
        adjacency.setdefault(b[0], []).append(a[0])

    layers = {}
    queue = [(i["name"], 0) for i in insts if i["type"] == "source"]
    if not queue:
        queue = [(insts[0]["name"], 0)] if insts else []
    for name, depth in queue:
        layers[name] = depth
    order = [n for n, _ in queue]
    while order:
        name = order.pop(0)
        for nb in adjacency.get(name, []):
            if nb not in layers:
                layers[nb] = layers[name] + 1
                order.append(nb)
    for inst in insts:
        layers.setdefault(inst["name"], 0)

    # monitors always sit in the far-right column
    max_layer = max(layers.values()) if layers else 0
    for inst in insts:
        if inst["type"] == "monitor":
            layers[inst["name"]] = max_layer
    max_layer = max(layers.values()) if layers else 0

    by_layer = {}
    for inst in insts:
        by_layer.setdefault(layers[inst["name"]], []).append(inst["name"])
    index_in_layer = {}
    for layer, names in by_layer.items():
        for i, name in enumerate(names):
            index_in_layer[name] = i

    lookup = {i["name"]: i for i in insts}
    nodes = []
    height_needed = 0
    for inst in insts:
        kind = inst["type"]
        w, h = SIZES.get(kind, (140, 70))
        layer = layers[inst["name"]]
        x = MARGIN + layer * COL_WIDTH
        y = MARGIN + index_in_layer[inst["name"]] * ROW_HEIGHT
        height_needed = max(height_needed, y + h)
        ports = []
        sides = PORT_SIDES.get(kind, [])
        for pidx, side in enumerate(sides):
            count = sides.count(side)
            slot = sum(1 for s in sides[:pidx] if s == side)
            py = y + h * (slot + 1) / (count + 1)
            px = x if side == "L" else x + w
            ports.append({"index": pidx, "side": side, "x": px, "y": py,
                          "name": inst["ports"][pidx]})
        nodes.append({"id": inst["name"], "name": inst["name"],
                      "type": kind, "x": x, "y": y, "w": w, "h": h,
                      "label": "%s\n%s" % (inst["name"], kind),
                      "ports": ports, "layer": layer})

    total_w = MARGIN + (max_layer + 1) * COL_WIDTH + MARGIN
    total_h = height_needed + MARGIN
    node_map = {n["id"]: n for n in nodes}
    for edge in edges:
        for end in ("a", "b"):
            ref = edge[end]
            node = node_map[ref["node"]]
            port = next(p for p in node["ports"] if p["index"] == ref["port"])
            ref["x"], ref["y"] = port["x"], port["y"]
        edge["back"] = (node_map[edge["b"]["node"]]["layer"] <
                        node_map[edge["a"]["node"]]["layer"])
    return {"width": total_w, "height": total_h, "nodes": nodes,
            "edges": edges, "layers": max_layer + 1}


def to_svg(layout, title="Lumen schematic"):
    colors = {"source": "#0e7490", "monitor": "#7c3aed", "mzi": "#1d4ed8",
              "ring": "#b45309", "coupler": "#15803d", "wg": "#475569",
              "atten": "#9f1239"}
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" '
             'height="%d" viewBox="0 0 %d %d">' %
             (layout["width"], layout["height"], layout["width"],
              layout["height"])]
    parts.append('<rect width="100%" height="100%" fill="#ffffff"/>')
    parts.append('<text x="%d" y="24" font-family="Helvetica,Arial" '
                 'font-size="14" fill="#0f172a">%s</text>'
                 % (MARGIN, _esc(title)))
    for edge in layout["edges"]:
        style = "stroke:#cbd5e1;stroke-width:2"
        if edge["back"]:
            style = "stroke:#c026d3;stroke-width:1.6;stroke-dasharray:6 4"
        parts.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
                     'style="%s"/>' % (edge["a"]["x"], edge["a"]["y"],
                                       edge["b"]["x"], edge["b"]["y"],
                                       style))
    for node in layout["nodes"]:
        fill = colors.get(node["type"], "#334155")
        parts.append('<rect x="%.1f" y="%.1f" width="%d" height="%d" '
                     'rx="10" fill="%s" opacity="0.92"/>'
                     % (node["x"], node["y"], node["w"], node["h"], fill))
        for i, line in enumerate(node["label"].split("\n")):
            parts.append('<text x="%.1f" y="%.1f" font-family="Helvetica" '
                         'font-size="12" fill="#ffffff" text-anchor="middle">'
                         '%s</text>' % (node["x"] + node["w"] / 2,
                                        node["y"] + 24 + i * 15,
                                        _esc(line)))
        for port in node["ports"]:
            parts.append('<circle cx="%.1f" cy="%.1f" r="4" fill="#e2e8f0" '
                         'stroke="#0f172a" stroke-width="1"/>'
                         % (port["x"], port["y"]))
    parts.append("</svg>")
    return "\n".join(parts)


def _esc(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))
