"""Build the muto app icon into package data (pure Python, no PIL).

From one 16x16 pixel map produce:
  src/muto/data/favicon.png   (48x48 RGBA)  — embedded in the dashboard <head>
  src/muto/data/muto.ico      (16/32/48)    — used by `muto shortcut` on Windows

The mascot is the muto "mute" sprite: a CRT-headed blob in Hermès orange.
This orange lives only in the app icon (browser/taskbar chrome), never on the
dashboard canvas, so the on-screen DOS 16-color palette is untouched.

Usage: python3 scripts/build_icon.py   (requires only the stdlib)
"""

import struct
import zlib
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "src" / "muto" / "data"

# Hermès orange body, warm highlight, near-black eyes; '.' = transparent.
PALETTE = {
    "O": (243, 112, 33, 255),   # Hermès orange (~Pantone 1448C)
    "H": (247, 168, 92, 255),   # highlight
    "D": (42, 21, 0, 255),      # eyes / mouth
    ".": (0, 0, 0, 0),
}

ART = """
................
....HHOOOOOO....
..OHHOOOOOOOOO..
..OOOOOOOOOOOO..
..OODDOOOODDOO..
..OODDOOOODDOO..
..OOOOOOOOOOOO..
..OOOOOOOOOOOO..
..OOODDDDDDOOO..
..OOOOOOOOOOOO..
..OOOOOOOOOOOO..
...OOOOOOOOOO...
....OO....OO....
....OO....OO....
................
................
"""


def _grid() -> list:
    rows = [r for r in ART.strip("\n").splitlines()]
    assert len(rows) == 16 and all(len(r) == 16 for r in rows), "art must be 16x16"
    return rows


def _render(scale: int) -> tuple:
    rows = _grid()
    w = h = 16 * scale
    buf = bytearray()
    for row in rows:
        line = bytearray()
        for ch in row:
            line.extend(bytes(PALETTE[ch]))
        line = bytes(line)
        # nearest-neighbor upscale: repeat each pixel `scale` times across...
        wide = bytearray()
        for i in range(0, len(line), 4):
            wide.extend(line[i:i + 4] * scale)
        buf.extend(bytes(wide) * scale)  # ...and each row `scale` times down
    return w, h, bytes(buf)


def _png(scale: int) -> bytes:
    w, h, rgba = _render(scale)
    raw = bytearray()
    stride = w * 4
    for y in range(h):
        raw.append(0)  # filter type 0 (None)
        raw.extend(rgba[y * stride:(y + 1) * stride])

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) +
            chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


def _ico(scales: list) -> bytes:
    pngs = [(16 * s, _png(s)) for s in scales]
    n = len(pngs)
    header = struct.pack("<HHH", 0, 1, n)
    entries = bytearray()
    offset = 6 + 16 * n
    for size, blob in pngs:
        entries += struct.pack("<BBBBHHII",
                               size & 0xFF, size & 0xFF, 0, 0, 1, 32,
                               len(blob), offset)
        offset += len(blob)
    return bytes(header) + bytes(entries) + b"".join(b for _, b in pngs)


def build() -> tuple:
    DATA.mkdir(parents=True, exist_ok=True)
    favicon = DATA / "favicon.png"
    ico = DATA / "muto.ico"
    favicon.write_bytes(_png(3))          # 48x48
    ico.write_bytes(_ico([1, 2, 3]))      # 16 / 32 / 48
    return favicon, ico


if __name__ == "__main__":
    for p in build():
        print(p)
