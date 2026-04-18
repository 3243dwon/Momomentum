"""Generate PWA + iOS app icons matching the favicon trending-up arrow.

Run with: .venv/bin/python scripts/make_icons.py
Outputs: web/static/icon-192.png, icon-512.png, apple-touch-icon.png
"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "web" / "static"
OUT.mkdir(parents=True, exist_ok=True)

BG = (10, 12, 16, 255)        # ink-950
FG = (59, 130, 246, 255)      # signal-info / blue-500

# SVG path coords (viewBox 0..24): "M3 17l5-5 4 4 8-8" + "M14 8h6v6"
TREND = [(3, 17), (8, 12), (12, 16), (20, 8)]
HEAD = [(14, 8), (20, 8), (20, 14)]


def make_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), BG)
    draw = ImageDraw.Draw(img)

    pad = int(size * 0.18)
    s = (size - 2 * pad) / 24

    def pt(x, y):
        return (pad + x * s, pad + y * s)

    width = max(2, int(size * 0.10))
    r = width // 2

    def stroke(points):
        scaled = [pt(*p) for p in points]
        draw.line(scaled, fill=FG, width=width, joint="curve")
        # Pillow's joint='curve' rounds joints but not endpoints — add caps.
        for x, y in scaled:
            draw.ellipse((x - r, y - r, x + r, y + r), fill=FG)

    stroke(TREND)
    stroke(HEAD)
    return img


for name, size in {
    "icon-192.png": 192,
    "icon-512.png": 512,
    "apple-touch-icon.png": 180,
}.items():
    path = OUT / name
    make_icon(size).save(path, "PNG", optimize=True)
    print(f"wrote {path.relative_to(OUT.parent.parent)} ({size}x{size})")
