"""Build station/landmask.py: a coarse land / sea map of the world for HF ground reflections (station/hfprop.py).

    python -m tools.build_landmask path/to/ne_110m_land.geojson

Source: Natural Earth 1:110m land polygons (public domain, naturalearthdata.com). Each 2 x 2 degree cell is land when
its centre is inside a land polygon. The result is 16,200 bits, packed and base64'd into the module.
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

STEP = 2
OUT = Path(__file__).resolve().parent.parent / "station" / "landmask.py"


def _inside(x: float, y: float, ring: list) -> bool:
    n, c = len(ring), False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            c = not c
        j = i
    return c


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    polys = []
    for f in json.loads(Path(argv[0]).read_text(encoding="utf-8"))["features"]:
        g = f["geometry"]
        for p in ([g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]):
            xs = [pt[0] for pt in p[0]]
            ys = [pt[1] for pt in p[0]]
            polys.append((min(xs), max(xs), min(ys), max(ys), p))
    bits = bytearray()
    acc = n = land = 0
    for lat in range(90 - STEP // 2, -90, -STEP):                # north to south
        for lon in range(-180 + STEP // 2, 180, STEP):           # west to east
            hit = any(a <= lon <= b and c <= lat <= d and _inside(lon, lat, p[0])
                      and not any(_inside(lon, lat, h) for h in p[1:]) for a, b, c, d, p in polys)
            land += hit
            acc = (acc << 1) | int(hit)
            n += 1
            if n % 8 == 0:
                bits.append(acc)
                acc = 0
    if n % 8:
        bits.append(acc << (8 - n % 8))
    b64 = base64.b64encode(bytes(bits)).decode()
    lines = "\n".join(f'    "{b64[i:i + 100]}"' for i in range(0, len(b64), 100))
    OUT.write_text(f'''"""A coarse land / sea map of the world: {STEP} x {STEP} degree cells, land when the cell's centre is on land.

Built by tools/build_landmask.py from Natural Earth 1:110m land (public domain). Used by station/hfprop.py: an HF
signal's ground reflection between two hops loses less on sea water than on land.
"""
from __future__ import annotations

import base64

STEP = {STEP}
COLS, ROWS = 360 // STEP, 180 // STEP
_BITS = base64.b64decode(
{lines}
)


def is_land(lat: float, lon: float) -> bool:
    """True when this point is on land (to the map's {STEP}-degree cells: a coast or a small island may go either way)."""
    r = min(ROWS - 1, max(0, int((90.0 - float(lat)) // STEP)))
    c = int(((float(lon) + 180.0) % 360.0) // STEP) % COLS
    i = r * COLS + c
    return bool(_BITS[i >> 3] >> (7 - (i & 7)) & 1)
''', encoding="utf-8")
    print(f"{OUT}: {n} cells, {land} land ({100 * land / n:.0f}%), {len(b64)} characters")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
