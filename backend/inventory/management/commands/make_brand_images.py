"""Generate the brand raster images the site serves.

The repository shipped no image assets at all, so a link shared to Facebook,
Messenger or WhatsApp rendered as a bare grey card with no preview, and the
browser tab showed the default blank icon. Those previews are the first thing a
pharmacy owner in Bangladesh sees when someone shares Rakho, so the social card
matters as much as the page copy.

The images are generated rather than hand-drawn so they can be regenerated —
and stay visually consistent with the console theme — without a design tool.
Pure stdlib (``zlib`` + ``struct``): no Pillow, so nothing is added to the
deploy's dependency set.

    python manage.py make_brand_images
"""

import struct
import zlib
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

# Brand palette, matching templates/admin/base_site.html.
DEEP = (11, 74, 52)          # --rk-deep
GREEN = (14, 159, 110)       # --rk-green
GREEN_600 = (12, 139, 96)    # --rk-green-600
AMBER = (217, 166, 46)       # --accent
WHITE = (255, 255, 255)
MINT = (214, 241, 228)

# 5x7 uppercase glyphs, one string per row. Only the letters actually used in
# the wordmark and taglines are defined; anything missing renders as a space.
_FONT = {
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01110", "10001", "10000", "10000", "10000", "10001", "01110"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("11111", "00100", "00100", "00100", "00100", "00100", "11111"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "11011", "10001"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    " ": ("00000",) * 7,
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    ".": ("00000", "00000", "00000", "00000", "00000", "00000", "00100"),
    "·": ("00000", "00000", "00000", "00100", "00000", "00000", "00000"),
}

GLYPH_W, GLYPH_H = 5, 7


def _png(width, height, pixels):
    """Encode straight RGBA bytes as a PNG (colour type 6, 8 bits/channel)."""
    raw = b"".join(
        b"\x00" + bytes(pixels[y * width * 4:(y + 1) * width * 4])
        for y in range(height)
    )

    def chunk(tag, payload):
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def _lerp(start, end, ratio):
    return round(start + (end - start) * ratio)


class Canvas:
    """Minimal RGBA raster canvas with alpha compositing."""

    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.pixels = bytearray(width * height * 4)

    def blend(self, x, y, color, alpha=1.0):
        if alpha <= 0 or not (0 <= x < self.width and 0 <= y < self.height):
            return
        offset = (y * self.width + x) * 4
        target_alpha = self.pixels[offset + 3] / 255
        out_alpha = alpha + target_alpha * (1 - alpha)
        if out_alpha <= 0:
            return
        for channel in range(3):
            source = color[channel] * alpha
            backdrop = self.pixels[offset + channel] * target_alpha * (1 - alpha)
            self.pixels[offset + channel] = round((source + backdrop) / out_alpha)
        self.pixels[offset + 3] = round(out_alpha * 255)

    def rect(self, x0, y0, x1, y1, color, alpha=1.0):
        for y in range(max(0, y0), min(self.height, y1)):
            for x in range(max(0, x0), min(self.width, x1)):
                self.blend(x, y, color, alpha)

    def horizontal_gradient(self, start, end):
        for x in range(self.width):
            ratio = x / max(1, self.width - 1)
            color = tuple(_lerp(start[i], end[i], ratio) for i in range(3))
            self.rect(x, 0, x + 1, self.height, color)

    def rounded_rect(self, x0, y0, x1, y1, radius, color, alpha=1.0):
        """Rounded rectangle with a one-pixel antialiased corner."""
        for y in range(y0, y1):
            for x in range(x0, x1):
                centre_x, centre_y = x + 0.5, y + 0.5
                dx = dy = 0.0
                if centre_x < x0 + radius:
                    dx = (x0 + radius) - centre_x
                elif centre_x > x1 - radius:
                    dx = centre_x - (x1 - radius)
                if centre_y < y0 + radius:
                    dy = (y0 + radius) - centre_y
                elif centre_y > y1 - radius:
                    dy = centre_y - (y1 - radius)
                if dx and dy:  # inside a corner box
                    distance = (dx * dx + dy * dy) ** 0.5
                    coverage = min(1.0, max(0.0, radius - distance + 0.5))
                else:
                    coverage = 1.0
                self.blend(x, y, color, alpha * coverage)

    def text(self, x, y, text, scale, color, alpha=1.0, spacing=1):
        cursor = x
        for character in text.upper():
            glyph = _FONT.get(character)
            if glyph:
                for row_index, row in enumerate(glyph):
                    for column, bit in enumerate(row):
                        if bit == "1":
                            self.rect(
                                cursor + column * scale,
                                y + row_index * scale,
                                cursor + (column + 1) * scale,
                                y + (row_index + 1) * scale,
                                color,
                                alpha,
                            )
            cursor += (GLYPH_W + spacing) * scale


def text_width(text, scale, spacing=1):
    return len(text) * (GLYPH_W + spacing) * scale - spacing * scale


def _cross(canvas, center_x, center_y, arm, thickness, color):
    """Pharmacy cross: the mark used in the console header and the landing nav."""
    half = thickness // 2
    canvas.rect(center_x - half, center_y - arm, center_x + half, center_y + arm, color)
    canvas.rect(center_x - arm, center_y - half, center_x + arm, center_y + half, color)


def render_favicon(size=32):
    canvas = Canvas(size, size)
    radius = max(4, size // 5)
    canvas.horizontal_gradient(GREEN, DEEP)
    # Re-cut the edges so the gradient only survives inside the rounded square.
    mask = Canvas(size, size)
    mask.rounded_rect(0, 0, size, size, radius, WHITE)
    for index in range(3, len(mask.pixels), 4):
        canvas.pixels[index] = mask.pixels[index]
    _cross(canvas, size // 2, size // 2, size // 5, max(3, size // 6), WHITE)
    return canvas


def render_app_icon(size=180):
    """Full-bleed: iOS and Android apply their own mask."""
    canvas = Canvas(size, size)
    canvas.horizontal_gradient(GREEN, DEEP)
    _cross(canvas, size // 2, size // 2, size // 5, max(6, size // 6), WHITE)
    return canvas


def render_og_card(width=1200, height=630, host="RAKHO-API.ONRENDER.COM"):
    canvas = Canvas(width, height)
    canvas.horizontal_gradient(DEEP, GREEN_600)

    # Logo mark: white rounded square with a green cross, as in the nav.
    mark_size, mark_x, mark_y = 108, 92, 96
    canvas.rounded_rect(
        mark_x, mark_y, mark_x + mark_size, mark_y + mark_size, 28, WHITE
    )
    _cross(
        canvas,
        mark_x + mark_size // 2,
        mark_y + mark_size // 2,
        32,
        20,
        (11, 107, 74),
    )

    canvas.text(232, 118, "RAKHO", 16, WHITE)
    canvas.text(96, 306, "PHARMACY INVENTORY · EXPIRY ALERTS", 4, MINT)
    canvas.text(96, 356, "BAKI BOOK · OFFLINE · FREE TO START", 4, MINT)
    canvas.text(96, 520, host, 3, WHITE, alpha=0.62)
    canvas.rect(0, height - 10, width, height, AMBER)
    return canvas


class Command(BaseCommand):
    help = "Generate the favicon, app icon and Open Graph share card."

    def handle(self, *args, **options):
        target = Path(settings.BASE_DIR) / "static" / "brand"
        target.mkdir(parents=True, exist_ok=True)

        host = settings.SITE_URL.split("//")[-1].replace("/", "").upper()
        images = {
            "favicon-32.png": render_favicon(32),
            "apple-touch-icon.png": render_app_icon(180),
            "og.png": render_og_card(host=host),
        }
        for name, canvas in images.items():
            path = target / name
            path.write_bytes(
                _png(canvas.width, canvas.height, canvas.pixels)
            )
            self.stdout.write(
                f"{name}: {canvas.width}x{canvas.height} -> {path}"
            )
