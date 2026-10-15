"""The small drawings of the "free" (Quarter) mark, hinted on the pixel grid like a type designer's small sizes.

Each grid is the left half of the figure; the right half is its mirror, so the midline falls on a pixel edge.
'#' is a full pixel, '+' a half pixel (opacity .5), ' ' is empty. On the right half, rows above CUT are drawn in the
accent (the skin is cut away there), and so is the whole arm (columns from ARM outward): the same cut as the large
mark, without its cut faces, which are thinner than a pixel at these sizes.
"""

# Figure 30 px high, for symbol-small.svg (32 px box) and app headers.
G30 = dict(cut=14, arm=4, rows=[
    "     +#",
    "     ##",
    "     ##",
    "     +#",
    "      #",
    "    +##",
    "  +####",
    "  #####",
    "  #####",
    "  # ###",
    "  # ###",
    "  # +##",
    "  #  ##",
    "  #  ##",
    " +# +##",
    " ## ###",
    " ## ###",
    " +# ###",
    "    ###",
    "    ###",
    "    ## ",
    "    ## ",
    "    +# ",
    "    ## ",
    "    ## ",
    "    +# ",
    "     # ",
    "     # ",
    "    +# ",
    "    ## ",
])

# Figure 22 px high, for the 32 px macOS icon (the tile is 26 px).
G22 = dict(cut=10, arm=3, rows=[
    "    +#",
    "    ##",
    "    +#",
    "     #",
    "   +##",
    " +####",
    " #####",
    " # ###",
    " # ###",
    " # +##",
    " #  ##",
    "+# +##",
    "## ###",
    "+# ###",
    "   ###",
    "   ##+",
    "   ## ",
    "   +# ",
    "   ## ",
    "    # ",
    "    # ",
    "   ## ",
])

# Figure 15 px high, for the favicon and the 16 px symbol.
G15 = dict(cut=7, arm=2, rows=[
    "   +#",
    "   +#",
    "    #",
    "  ###",
    " +###",
    " # ##",
    " # ##",
    " # ##",
    " + ##",
    "   ##",
    "  +# ",
    "   # ",
    "   # ",
    "   # ",
    "  +# ",
])

# Figure 12 px high, for the 16 px macOS icon (the tile is 13 px).
G12 = dict(cut=6, arm=2, rows=[
    "   +#",
    "   +#",
    "  ###",
    " +###",
    " # ##",
    " # ##",
    " + ##",
    "   ##",
    "   # ",
    "   # ",
    "   # ",
    "  +# ",
])

GRIDS = {30: G30, 22: G22, 15: G15, 12: G12}


def cells(grid):
    """(col, row, opacity, accent?) for every lit pixel; columns run from -w to w-1 around the midline at 0."""
    rows, cut, arm = grid["rows"], grid["cut"], grid["arm"]
    w = len(rows[0])
    out = []
    for y, row in enumerate(rows):
        for i, ch in enumerate(row):
            if ch == " ":
                continue
            op = 1 if ch == "#" else .5
            out.append((i - w, y, op, False))                            # left half: skin
            col = w - 1 - i                                              # mirrored column, right half
            accent = y < cut or i < arm
            out.append((col, y, op, accent))
    return out


def rects(grid, ox, oy, s, ink, accent, op_attr="fill-opacity", classes=None):
    """SVG for a grid: merged runs of pixels of one paint, origin (ox, oy) at the midline top, pixel size s."""
    runs = {}
    for x, y, op, acc in cells(grid):
        runs.setdefault((y, op, acc), []).append(x)
    out = {}
    for (y, op, acc), xs in runs.items():
        xs.sort()
        start = prev = xs[0]
        for x in xs[1:] + [None]:
            if x is not None and x == prev + 1:
                prev = x
                continue
            out.setdefault((op, acc), []).append(f"M{_n(ox + start * s)} {_n(oy + y * s)}h{_n((prev - start + 1) * s)}v{_n(s)}h{_n(-(prev - start + 1) * s)}Z")
            if x is not None:
                start = prev = x
    body = ""
    for (op, acc), ds in sorted(out.items(), key=lambda kv: (kv[0][1], -kv[0][0])):
        if classes:
            paint = f' class="{classes[1] if acc else classes[0]}"'
        else:
            paint = f' fill="{accent if acc else ink}"'
        if op != 1:
            paint += f' {op_attr}="{_n(op)}"'
        body += f'<path{paint} d="{"".join(ds)}"/>'
    return body


def _n(v):
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s
