"""Build src/muto/data/vga_8x16.woff2 from src/muto/data/vga8x16.json.

The JSON maps each of the 256 CP437 characters (as Unicode) to 16 row bytes
(8 px wide, MSB = leftmost) of the classic IBM VGA 8x16 ROM font. Glyph data
extracted from susam/pcface (MIT); see src/muto/data/LICENSE-pcface.md.

Every lit pixel becomes a 64-unit square (runs merged per row), so the
rendered outline is pixel-identical to the bitmap at multiples of 16px.

Usage: python3 scripts/build_font.py
Requires: fonttools, brotli
"""

import json
from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

DATA = Path(__file__).resolve().parent.parent / "src" / "muto" / "data"
PX = 64          # font units per bitmap pixel
EM = 16 * PX     # 1024
ASCENT = 12 * PX  # baseline sits below row 11 (caps occupy rows 2..11)
DESCENT = 4 * PX


# Characters outside CP437 that the dashboard uses, mapped onto CP437
# bitmaps so they stay on the 8px grid instead of falling back to another
# font: em dash (U+2014) renders as the single box line (U+2500).
ALIASES = {"—": "─"}


def build() -> Path:
    glyphs = json.loads((DATA / "vga8x16.json").read_text())
    for extra, source in ALIASES.items():
        glyphs[extra] = glyphs[source]

    order = [".notdef"]
    cmap = {}
    glyf = {}
    metrics = {}

    pen = TTGlyphPen(None)
    glyf[".notdef"] = pen.glyph()
    metrics[".notdef"] = (8 * PX, 0)

    for i, (ch, rows) in enumerate(sorted(glyphs.items(), key=lambda kv: ord(kv[0]))):
        name = f"u{ord(ch):04X}"
        order.append(name)
        cmap[ord(ch)] = name
        pen = TTGlyphPen(None)
        for row_i, byte in enumerate(rows):
            y_top = ASCENT - row_i * PX
            col = 0
            while col < 8:
                if byte & (0x80 >> col):
                    run = col
                    while run < 8 and byte & (0x80 >> run):
                        run += 1
                    x0, x1 = col * PX, run * PX
                    pen.moveTo((x0, y_top - PX))
                    pen.lineTo((x1, y_top - PX))
                    pen.lineTo((x1, y_top))
                    pen.lineTo((x0, y_top))
                    pen.closePath()
                    col = run
                else:
                    col += 1
        glyf[name] = pen.glyph()
        metrics[name] = (8 * PX, 0)

    fb = FontBuilder(EM, isTTF=True)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(glyf)
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=ASCENT, descent=-DESCENT)
    fb.setupOS2(sTypoAscender=ASCENT, sTypoDescender=-DESCENT, sTypoLineGap=0,
                usWinAscent=ASCENT, usWinDescent=DESCENT)
    fb.setupNameTable({"familyName": "MutoVGA", "styleName": "Regular",
                       "fullName": "MutoVGA 8x16",
                       "psName": "MutoVGA-Regular",
                       "licenseDescription":
                           "IBM VGA 8x16 ROM bitmap; glyph data via susam/pcface (MIT)."})
    fb.setupPost(isFixedPitch=1)
    fb.font.flavor = "woff2"
    out = DATA / "vga_8x16.woff2"
    fb.save(out)
    return out


if __name__ == "__main__":
    print(build())
