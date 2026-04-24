"""Server-side PNG rendering for shareable teacher cards + printable QR sheets.

Two outputs, one primitive stack (Pillow + qrcode):

1. render_teacher_card() — 1080x1350 (Xiaohongshu/IG portrait ratio) color card
   with branding, name, subject, star rating, "would take again" %, and a QR in
   the corner. This is the social-share asset.

2. render_teacher_qr() — 1024x1024 printable poster with a large QR, teacher
   name, and the site URL. This is the print-and-tape-outside-classrooms asset.

Both routes render on-demand and return PNG bytes — there's no caching layer.
At ~150ms per render on a 60-teacher site, caching adds complexity for a load
that's ~100 renders per week.
"""

import io
import math
from pathlib import Path
from typing import Optional

import qrcode
from PIL import Image, ImageChops, ImageDraw, ImageFont

# Fonts live next to this module so the renderer works regardless of CWD.
# v1 ships Latin-only Instrument Serif + Geist (~325KB total) — matches the
# site's web typography. The current roster (65 teachers) has zero CJK names.
# When a future submission lands with Chinese glyphs, the card will render
# tofu boxes; fix by bundling a CJK fallback (Noto Sans SC Regular, ~8MB)
# and dispatching to it when name contains \u4e00-\u9fff.
FONTS_DIR = Path(__file__).parent / "fonts"
SERIF = str(FONTS_DIR / "InstrumentSerif-Regular.ttf")
SANS = str(FONTS_DIR / "Geist-Regular.ttf")
SANS_BOLD = str(FONTS_DIR / "Geist-Bold.ttf")

# Palette — OKLCH values from styles.css, hand-tuned to sRGB. Kept in one
# place so the share card matches the site's visual identity.
BG = (247, 240, 227)         # warm cream (--bg)
BG_CARD = (250, 245, 233)    # slightly lighter (--bg-card)
INK = (45, 40, 34)           # warm dark (--ink)
INK_SOFT = (98, 90, 82)      # muted (--ink-soft)
INK_MUTE = (150, 140, 128)   # even softer (--ink-mute)
LINE = (224, 216, 200)       # hairline (--line)
ACCENT = (217, 129, 88)      # orange (--accent)
ACCENT_INK = (140, 74, 46)   # dark orange (--accent-ink)
ACCENT_BG = (242, 214, 195)  # peach (--accent-bg)
STAR = (213, 159, 79)        # golden (--star)
STAR_EMPTY = (224, 216, 200) # same as line — faded star outline


def _load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size=size)


def _draw_star(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, fill):
    """Draw a filled 5-point star centered at (cx, cy) with outer radius r.

    Inner radius = r / golden_ratio gives the canonical star proportion.
    """
    inner_r = r / 2.618  # ~ r / golden_ratio_squared-ish, looks right
    pts = []
    for i in range(10):
        angle = math.radians(-90 + i * 36)
        radius = r if i % 2 == 0 else inner_r
        pts.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    draw.polygon(pts, fill=fill)


def _draw_stars(draw: ImageDraw.ImageDraw, x: int, y: int, rating: float, *,
                size: int = 48, gap: int = 14):
    """Five stars in a row. Partial fills rendered via masking."""
    r = size / 2
    for i in range(5):
        cx = x + r + i * (size + gap)
        cy = y + r
        # full star outline (empty bg)
        _draw_star(draw, cx, cy, r, fill=STAR_EMPTY)
    # fill stars left-to-right up to the rating value
    full = int(rating)
    partial = rating - full
    for i in range(full):
        cx = x + r + i * (size + gap)
        cy = y + r
        _draw_star(draw, cx, cy, r, fill=STAR)
    if partial > 0 and full < 5:
        # Partial fill: intersect the star's own alpha mask with a horizontal
        # clip so only the left `partial * width` pixels of the star remain
        # visible. Naive putalpha() over-writes the alpha channel (including
        # the empty pixels around the star), which paints the transparent
        # background black when composited. ImageChops.multiply keeps both.
        pad = 4
        side = size + pad
        layer = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        ldraw = ImageDraw.Draw(layer)
        _draw_star(ldraw, side / 2, side / 2, r, fill=STAR + (255,))
        star_alpha = layer.split()[-1]
        clip = Image.new("L", (side, side), 0)
        ImageDraw.Draw(clip).rectangle(
            [(0, 0), (int(partial * side), side)], fill=255,
        )
        layer.putalpha(ImageChops.multiply(star_alpha, clip))
        return layer, (x + full * (size + gap) - pad // 2, y - pad // 2)
    return None, None


def _make_qr(url: str, *, box_size: int = 10, border: int = 2,
             fg=INK, bg=None) -> Image.Image:
    """Generate a QR code image. Transparent bg if bg is None."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(
        fill_color=fg,
        back_color=bg if bg is not None else (255, 255, 255, 0),
    )
    # Convert to RGBA so we can composite over colored backgrounds.
    return img.convert("RGBA")


def _fit_text(text: str, font_path: str, max_px: int, target_size: int,
              min_size: int = 40) -> ImageFont.FreeTypeFont:
    """Pick the largest font size <= target_size where text fits max_px wide."""
    for size in range(target_size, min_size - 1, -4):
        f = _load_font(font_path, size)
        w = f.getlength(text)
        if w <= max_px:
            return f
    return _load_font(font_path, min_size)


def _compose_card(
    *, name: str, subject: Optional[str], rating: Optional[float],
    review_count: int, wta_percent: Optional[int], wta_count: int,
    qr_url: str, site_label: str,
) -> Image.Image:
    """Build the 1080x1350 share card.

    Layout (four stacked zones, left-aligned except the QR block):
      - Header (y≈120):  brand lockup + one-line tagline
      - Identity (y≈330): SUBJECT eyebrow + huge name + hairline rule
      - Stats (y≈720):   big rating number + /5 + stars + review count
      - CTA (y≈1050):    WTA chip on the left, QR + caption on the right
    """
    W, H = 1080, 1350
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    MARGIN = 60
    PAD = 60  # inner padding inside the card panel
    CARD_RADIUS = 32
    draw.rounded_rectangle(
        [(MARGIN, MARGIN), (W - MARGIN, H - MARGIN)],
        radius=CARD_RADIUS, fill=BG_CARD, outline=LINE, width=2,
    )

    content_x = MARGIN + PAD
    content_w = W - 2 * (MARGIN + PAD)

    # ─── Header: brand lockup on the left, site URL top-right, tagline under
    brand_font = _load_font(SERIF, 54)
    tagline_font = _load_font(SANS, 22)
    brand_y = MARGIN + 70
    draw.text((content_x, brand_y), "Rate", font=brand_font, fill=INK)
    rate_w = brand_font.getlength("Rate ")
    draw.text((content_x + rate_w, brand_y), "BIPH", font=brand_font, fill=ACCENT_INK)
    draw.text((content_x, brand_y + 76),
              "Honest reviews from BIPH students",
              font=tagline_font, fill=INK_SOFT)
    # Site URL top-right — fills the empty corner and markets the site
    # even when the image is viewed without scanning.
    url_font = _load_font(SANS_BOLD, 26)
    url_w = url_font.getlength(site_label)
    draw.text((W - MARGIN - PAD - url_w, brand_y + 18),
              site_label, font=url_font, fill=INK_SOFT)

    # ─── Identity
    subject_y = MARGIN + 280
    if subject:
        eyebrow_font = _load_font(SANS_BOLD, 22)
        draw.text((content_x, subject_y), subject.upper(),
                  font=eyebrow_font, fill=ACCENT_INK)

    name_font = _fit_text(name, SERIF, content_w, target_size=140, min_size=72)
    name_y = subject_y + 50
    draw.text((content_x, name_y), name, font=name_font, fill=INK)

    rule_y = name_y + name_font.size + 40
    draw.line([(content_x, rule_y), (content_x + content_w, rule_y)],
              fill=LINE, width=2)

    # ─── Stats (left column) — anchored dynamically below the rule so
    # the composition stays tight regardless of name height. The QR
    # panel below vertically centers on this block, so they read as a
    # paired row instead of stats-on-top / QR-floating-in-corner.
    stats_y = rule_y + 70
    if rating is not None:
        big_font = _load_font(SERIF, 180)
        rating_str = f"{rating:.2f}"
        draw.text((content_x, stats_y), rating_str, font=big_font, fill=INK)
        rnum_w = big_font.getlength(rating_str)
        slash_font = _load_font(SERIF, 72)
        draw.text((content_x + rnum_w + 10, stats_y + 100),
                  "/5", font=slash_font, fill=INK_MUTE)

        stars_y = stats_y + 200
        partial_layer, partial_pos = _draw_stars(
            draw, content_x, stars_y, rating, size=56, gap=16)
        if partial_layer is not None:
            img.paste(partial_layer, partial_pos, partial_layer)

        rc_font = _load_font(SANS, 26)
        rc_text = f"based on {review_count} anonymous review{'s' if review_count != 1 else ''}"
        draw.text((content_x, stars_y + 90), rc_text,
                  font=rc_font, fill=INK_SOFT)
        stats_bottom = stars_y + 90 + 28
    else:
        no_data_font = _load_font(SERIF, 72)
        draw.text((content_x, stats_y + 30), "No reviews yet",
                  font=no_data_font, fill=INK_MUTE)
        stats_bottom = stats_y + 30 + 72

    # ─── QR panel (right column). Caption integrated INSIDE the panel at
    # the top so the corner reads as one cohesive object and doesn't
    # crowd the card's bottom edge. Panel is vertically centered on the
    # stats block so the two feel paired.
    qr_size = 260
    qr_pad_x = 26
    qr_pad_top = 48     # extra top padding holds the caption
    qr_pad_bottom = 26
    panel_w = qr_size + 2 * qr_pad_x
    panel_h = qr_size + qr_pad_top + qr_pad_bottom

    stats_center = (stats_y + stats_bottom) // 2
    panel_top = stats_center - panel_h // 2
    # Clamp so the panel never escapes the card's content area.
    min_panel_top = MARGIN + PAD + 240  # below the header/identity zone
    max_panel_bottom = H - MARGIN - PAD
    if panel_top < min_panel_top:
        panel_top = min_panel_top
    if panel_top + panel_h > max_panel_bottom:
        panel_top = max_panel_bottom - panel_h
    panel_bottom = panel_top + panel_h
    panel_right = W - MARGIN - PAD
    panel_left = panel_right - panel_w

    draw.rounded_rectangle(
        [(panel_left, panel_top), (panel_right, panel_bottom)],
        radius=20, fill=(255, 255, 255), outline=LINE, width=2,
    )
    # Caption at top of panel
    cap_font = _load_font(SANS, 20)
    cap_text = "Scan to read reviews"
    cap_w = cap_font.getlength(cap_text)
    cap_x = panel_left + (panel_w - cap_w) / 2
    cap_y = panel_top + 16
    draw.text((cap_x, cap_y), cap_text, font=cap_font, fill=INK_SOFT)
    # QR below caption
    qr_img = _make_qr(qr_url, box_size=11, border=0, fg=INK, bg=(255, 255, 255))
    qr_img = qr_img.resize((qr_size, qr_size), Image.NEAREST)
    qr_x = panel_left + qr_pad_x
    qr_y = panel_top + qr_pad_top
    img.paste(qr_img, (qr_x, qr_y), qr_img)

    # ─── WTA chip — below the stats block on the left, tied to the
    # stats column. The horizontal constraint is now the QR panel's
    # left edge instead of the old QR corner position.
    if wta_percent is not None and wta_count >= 3:
        chip_padx = 32
        chip_pady = 18
        wta_num_font = _load_font(SERIF, 68)
        wta_label_font = _load_font(SANS_BOLD, 28)
        pct_text = f"{wta_percent}%"
        label_text = "would take again"
        pct_w = wta_num_font.getlength(pct_text)
        label_w = wta_label_font.getlength(label_text)
        chip_w = pct_w + 24 + label_w + chip_padx * 2
        max_chip_w = panel_left - content_x - 30
        stacked = chip_w > max_chip_w
        if stacked:
            label_text_l1 = "would take"
            label_text_l2 = "again"
            label_font2 = _load_font(SANS_BOLD, 26)
            l1_w = label_font2.getlength(label_text_l1)
            l2_w = label_font2.getlength(label_text_l2)
            label_w = max(l1_w, l2_w)
            chip_w = pct_w + 20 + label_w + chip_padx * 2
        chip_h = wta_num_font.size + chip_pady * 2
        # Sit just below stats, but never below the QR panel's bottom
        # edge (otherwise the chip drifts into empty space).
        chip_y = min(stats_bottom + 40, panel_bottom - chip_h)
        draw.rounded_rectangle(
            [(content_x, chip_y), (content_x + chip_w, chip_y + chip_h)],
            radius=chip_h // 2, fill=ACCENT_BG,
        )
        pct_bbox = wta_num_font.getbbox(pct_text)
        pct_h = pct_bbox[3] - pct_bbox[1]
        draw.text(
            (content_x + chip_padx, chip_y + (chip_h - pct_h) / 2 - pct_bbox[1]),
            pct_text, font=wta_num_font, fill=ACCENT_INK,
        )
        if stacked:
            line_h = label_font2.size + 4
            total_h = line_h * 2
            label_start_y = chip_y + (chip_h - total_h) / 2
            draw.text((content_x + chip_padx + pct_w + 20, label_start_y),
                      label_text_l1, font=label_font2, fill=ACCENT_INK)
            draw.text((content_x + chip_padx + pct_w + 20, label_start_y + line_h),
                      label_text_l2, font=label_font2, fill=ACCENT_INK)
        else:
            label_bbox = wta_label_font.getbbox(label_text)
            label_h = label_bbox[3] - label_bbox[1]
            draw.text(
                (content_x + chip_padx + pct_w + 24,
                 chip_y + (chip_h - label_h) / 2 - label_bbox[1]),
                label_text, font=wta_label_font, fill=ACCENT_INK,
            )

    return img


def render_teacher_card(
    *, name: str, subject: Optional[str], rating: Optional[float],
    review_count: int, wta_percent: Optional[int], wta_count: int,
    qr_url: str, site_label: str,
) -> bytes:
    """Render the 1080x1350 share card and return PNG bytes."""
    img = _compose_card(
        name=name, subject=subject, rating=rating, review_count=review_count,
        wta_percent=wta_percent, wta_count=wta_count,
        qr_url=qr_url, site_label=site_label,
    )
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_teacher_qr(
    *, name: str, subject: Optional[str], qr_url: str, site_label: str,
) -> bytes:
    """Render a 1024x1024 printable poster: big name + big QR + site URL.

    Designed to print cleanly at any size — taped outside a classroom door it
    should be legible from a few feet away.
    """
    W, H = 1024, 1024
    img = Image.new("RGB", (W, H), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Name at top — fit to width
    name_font = _fit_text(name, SERIF, W - 120, target_size=110, min_size=56)
    # Pillow's getlength is the advance width — good enough for centering
    name_w = name_font.getlength(name)
    draw.text(((W - name_w) / 2, 90), name, font=name_font, fill=INK)

    # Subject under name
    if subject:
        sub_font = _load_font(SANS, 36)
        sub_w = sub_font.getlength(subject.upper())
        draw.text(((W - sub_w) / 2, 90 + name_font.size + 20), subject.upper(),
                  font=sub_font, fill=ACCENT_INK)

    # QR centered, large
    qr_img = _make_qr(qr_url, box_size=20, border=1, fg=INK, bg=(255, 255, 255))
    qr_size = 600
    qr_img = qr_img.resize((qr_size, qr_size), Image.NEAREST)
    qr_x = (W - qr_size) // 2
    qr_y = 260
    img.paste(qr_img, (qr_x, qr_y), qr_img)

    # Footer — tagline + URL
    tag_font = _load_font(SANS, 28)
    url_font = _load_font(SANS_BOLD, 40)
    tagline = "Scan for honest reviews"
    tag_w = tag_font.getlength(tagline)
    url_w = url_font.getlength(site_label)
    footer_y = qr_y + qr_size + 34
    draw.text(((W - tag_w) / 2, footer_y), tagline, font=tag_font, fill=INK_SOFT)
    draw.text(((W - url_w) / 2, footer_y + 44), site_label, font=url_font, fill=INK)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
