"""
Génère les icônes PNG pour la PWA.
Lance ce script une fois : python scripts/generate_icons.py
Requiert : pip install Pillow
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Pillow requis : pip install Pillow")
    sys.exit(1)

ICONS_DIR = Path(__file__).parent.parent / "mobile" / "icons"
ICONS_DIR.mkdir(parents=True, exist_ok=True)

BG_COLOR   = (26, 26, 46)      # #1a1a2e
LOGO_COLOR = (0, 212, 170)     # #00d4aa


def _draw_icon(size: int, maskable: bool = False) -> Image.Image:
    img = Image.new("RGBA", (size, size), BG_COLOR + (255,))
    draw = ImageDraw.Draw(img)

    # Fond maskable avec padding 10 %
    pad = int(size * 0.1) if maskable else 0

    # Cercle de fond vert
    margin = pad + int(size * 0.12)
    draw.ellipse([margin, margin, size - margin, size - margin],
                 fill=LOGO_COLOR + (255,))

    # Lettre "B" (Bot) en blanc centré
    text = "₿"
    text_color = BG_COLOR + (255,)
    font_size = int(size * 0.38)
    try:
        fnt = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
    except Exception:
        fnt = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=fnt)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (size - tw) / 2 - bbox[0]
    y = (size - th) / 2 - bbox[1]
    draw.text((x, y), text, fill=text_color, font=fnt)

    return img


def main():
    for size, name in [(192, "icon-192.png"), (512, "icon-512.png")]:
        img = _draw_icon(size)
        path = ICONS_DIR / name
        img.save(path, "PNG")
        print(f"✓ {path}")

    # Maskable
    img = _draw_icon(512, maskable=True)
    path = ICONS_DIR / "icon-maskable-512.png"
    img.save(path, "PNG")
    print(f"✓ {path}")

    print("\nIcones générées dans mobile/icons/")


if __name__ == "__main__":
    main()
