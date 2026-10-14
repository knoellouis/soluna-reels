"""Render a Soluna Mantras reel (1080x1920, 30fps) as MP4, in one of several layouts.

usage: python3 make_reel.py morning|night "Mantra text" out.mp4 [style]
styles: classic, horizon, words, frame, radiance  (omit to auto-rotate by date)
"""
import datetime
import math
import random
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
FONTS = Path(__import__("os").environ.get("SOLUNA_FONTS", str(HERE / "npmtmp")))
SERIF = FONTS / "fontsource-cormorant-garamond-5.3.0/files/cormorant-garamond-latin-500-normal.woff"
SERIF_IT = FONTS / "fontsource-cormorant-garamond-5.3.0/files/cormorant-garamond-latin-500-italic.woff"
SANS = FONTS / "fontsource-jost-5.3.0/files/jost-latin-500-normal.woff"

W, H, FPS, DUR = 1080, 1920, 30, 10.0
SS = 4
STYLES = ["classic", "horizon", "words", "frame", "radiance"]

THEMES = {
    "morning": dict(bg="#F4ECE1", icon="#C98A2B", label="#9A6A1F", text="#1F2440",
                    small="#5A5E78", star="#C98A2B", label_text="GOOD MORNING", tag="#SolunaRise"),
    "night": dict(bg="#1F2440", icon="#E3B160", label="#E3B160", text="#FBF7F1",
                  small="#B9BBCB", star="#FBF7F1", label_text="GOOD NIGHT", tag="#SolunaRest"),
}


# ---------------------------------------------------------------- helpers
def hexrgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def ease(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def window(t, start, dur):
    return ease((t - start) / dur)


def with_alpha(layer, a):
    if a >= 0.999:
        return layer
    out = layer.copy()
    out.putalpha(layer.getchannel("A").point(lambda v: int(v * a)))
    return out


def text_layer(text, font, color, tracking=0):
    tmp = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    widths = [tmp.textlength(ch, font=font) for ch in text]
    total = sum(widths) + tracking * (len(text) - 1)
    asc, desc = font.getmetrics()
    layer = Image.new("RGBA", (W, asc + desc + 10), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x = (W - total) / 2
    for ch, w in zip(text, widths):
        d.text((x, 0), ch, font=font, fill=color)
        x += w + tracking
    return layer


def word_layer(word, font, color):
    tmp = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    w = int(tmp.textlength(word, font=font)) + 8
    asc, desc = font.getmetrics()
    layer = Image.new("RGBA", (w, asc + desc + 10), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((0, 0), word, font=font, fill=color)
    return layer


def wrap(text, font, max_w):
    """Greedy wrap, then narrow the width as far as possible without adding a line,
    so lines come out evenly balanced (no lonely last word)."""
    n = len(_greedy(text, font, max_w))
    best = max_w
    for w in range(max_w, 360, -10):
        if len(_greedy(text, font, w)) > n:
            break
        best = w
    return _greedy(text, font, best)


def _greedy(text, font, max_w):
    d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    lines, cur = [], ""
    for word in text.split():
        trial = (cur + " " + word).strip()
        if d.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def sun_sprite(color, rot, size=420):
    big = Image.new("RGBA", (size * SS, size * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    k = size / 420
    c = size * SS / 2
    r = 110 * SS * k
    d.ellipse((c - r, c - r, c + r, c + r), fill=color)
    for i in range(12):
        a = math.radians(i * 30 + rot)
        r1, r2 = 140 * SS * k, 185 * SS * k
        d.line((c + r1 * math.cos(a), c + r1 * math.sin(a),
                c + r2 * math.cos(a), c + r2 * math.sin(a)), fill=color, width=int(9 * SS * k))
        for rr in (r1, r2):
            px, py = c + rr * math.cos(a), c + rr * math.sin(a)
            e = 4.5 * SS * k
            d.ellipse((px - e, py - e, px + e, py + e), fill=color)
    return big.resize((size, size), Image.LANCZOS)


def moon_sprite(color, size=420):
    big = Image.new("RGBA", (size * SS, size * SS), (0, 0, 0, 0))
    mask = Image.new("L", big.size, 0)
    md = ImageDraw.Draw(mask)
    k = size / 420
    c = size * SS / 2
    r = 120 * SS * k
    md.ellipse((c - r, c - r, c + r, c + r), fill=255)
    off = 62 * SS * k
    md.ellipse((c - r + off, c - r - off * 0.55, c + r + off, c + r - off * 0.55), fill=0)
    solid = Image.new("RGBA", big.size, color + (255,))
    big.paste(solid, (0, 0), mask)
    return big.resize((size, size), Image.LANCZOS)


def dot_sprite(color, r):
    s = int(r * 2 + 4)
    big = Image.new("RGBA", (s * SS, s * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    c = s * SS / 2
    d.ellipse((c - r * SS, c - r * SS, c + r * SS, c + r * SS), fill=color)
    return big.resize((s, s), Image.LANCZOS)


def paste_c(frame, spr, cx, cy, a=1.0):
    if a <= 0:
        return
    s = with_alpha(spr, a)
    frame.alpha_composite(s, (int(cx - s.width / 2), int(cy - s.height / 2)))


class Kit:
    """Everything a style needs, prepared once."""

    def __init__(self, mode, mantra):
        self.mode = mode
        self.th = th = THEMES[mode]
        self.bg = hexrgb(th["bg"])
        self.icon = hexrgb(th["icon"])
        self.label_font = ImageFont.truetype(str(SANS), 36)
        self.small_font = ImageFont.truetype(str(SANS), 32)
        self.brand_font = ImageFont.truetype(str(SERIF_IT), 44)
        self.label = text_layer(th["label_text"], self.label_font, th["label"], tracking=14)
        self.handle = text_layer("@solunamantras", self.small_font, th["small"], tracking=3)
        self.tag = text_layer(th["tag"], self.small_font, th["small"], tracking=3)
        self.brand = text_layer("Soluna Mantras", self.brand_font, th["small"])
        self.mantra = mantra
        self.moon = moon_sprite(self.icon)
        self.star_spr = {r: dot_sprite(hexrgb(th["star"]), r) for r in (2, 2.5, 3, 4)}

    def lines(self, font, max_w=780, color=None):
        color = color or self.th["text"]
        return [text_layer(l, font, color) for l in wrap(self.mantra, font, max_w)]

    def blank(self):
        return Image.new("RGBA", (W, H), self.bg + (255,))

    def stars(self, seed, n, y0, y1, avoid=None, avoid_r=190):
        random.seed(seed)
        out = []
        while len(out) < n:
            x, y = random.randint(60, W - 60), random.randint(y0, y1)
            if avoid and math.hypot(x - avoid[0], y - avoid[1]) < avoid_r:
                continue
            out.append((x, y, random.choice([2, 2.5, 3, 4]), random.uniform(0, math.tau),
                        random.uniform(0.6, 1.4)))
        return out

    def draw_stars(self, frame, stars, t, fade=1.0):
        for x, y, r, ph, sp in stars:
            tw = 0.45 + 0.55 * (0.5 + 0.5 * math.sin(ph + t * sp * 2.2))
            paste_c(frame, self.star_spr[r], x, y, fade * tw)

    def label_at(self, frame, t, y, start=1.3):
        a = window(t, start, 1.0)
        if a > 0:
            frame.alpha_composite(with_alpha(self.label, a), (0, y + int((1 - a) * 16)))

    def lines_at(self, frame, t, lines, top, line_h, start=2.0, gap=0.45):
        for i, layer in enumerate(lines):
            a = window(t, start + i * gap, 1.1)
            if a > 0:
                frame.alpha_composite(with_alpha(layer, a), (0, top + i * line_h + int((1 - a) * 24)))

    def footer_at(self, frame, t, y, start):
        a = window(t, start, 1.0)
        if a > 0:
            frame.alpha_composite(with_alpha(self.brand, a), (0, y))
            frame.alpha_composite(with_alpha(self.handle, a), (0, y + 70))
            frame.alpha_composite(with_alpha(self.tag, a), (0, y + 116))


# ---------------------------------------------------------------- styles
def style_classic(k):
    """Icon centre-top, label, mantra fading in line by line."""
    font = ImageFont.truetype(str(SERIF), 96)
    lines = k.lines(font)
    stars = k.stars(7, 26, 240, 840, avoid=(W / 2, 600)) if k.mode == "night" else []

    def frame(t):
        f = k.blank()
        if stars:
            k.draw_stars(f, stars, t, window(t, 0, 1.5))
        p = window(t, 0, 2.0)
        if k.mode == "morning":
            paste_c(f, sun_sprite(k.icon, t * 6), W / 2, 620 + (1 - p) * 180, p)
        else:
            paste_c(f, k.moon, W / 2, 600 - (1 - p) * 140, p)
        k.label_at(f, t, 900)
        k.lines_at(f, t, lines, 1000, 118)
        k.footer_at(f, t, 1000 + 118 * len(lines) + 70, 4.6 + 0.45 * len(lines))
        return f
    return frame


def style_horizon(k):
    """Text up top; the sun (or moon) rises slowly from behind a horizon line."""
    font = ImageFont.truetype(str(SERIF), 92)
    lines = k.lines(font)
    top = 400
    hy = 1300  # horizon
    stars = k.stars(21, 22, 960, hy - 40, avoid=(W / 2, hy - 90), avoid_r=230) if k.mode == "night" else []
    line_col = hexrgb(k.th["label"])

    def frame(t):
        f = k.blank()
        if stars:
            k.draw_stars(f, stars, t, window(t, 0.5, 2.0))
        p = window(t, 0.2, 4.5)
        body = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        if k.mode == "morning":
            paste_c(body, sun_sprite(k.icon, t * 4), W / 2, hy + 120 - p * 260)
        else:
            paste_c(body, k.moon, W / 2, hy + 120 - p * 230)
        mask = Image.new("L", (W, H), 0)
        ImageDraw.Draw(mask).rectangle((0, 0, W, hy), fill=255)
        f.paste(body, (0, 0), Image.composite(body.getchannel("A"), Image.new("L", (W, H), 0), mask))
        # horizon line drawing outwards from the centre
        lw = window(t, 0.0, 1.6)
        ImageDraw.Draw(f).line((W / 2 - 420 * lw, hy, W / 2 + 420 * lw, hy), fill=line_col, width=3)
        k.label_at(f, t, top - 100, start=1.0)
        k.lines_at(f, t, lines, top, 112, start=1.6)
        k.footer_at(f, t, hy + 50, 4.4 + 0.45 * len(lines))
        return f
    return frame


def style_words(k):
    """Small icon, then the mantra appears word by word, slightly larger."""
    font = ImageFont.truetype(str(SERIF), 104)
    raw = wrap(k.mantra, font, 820)
    d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    space = d.textlength(" ", font=font)
    words = []  # (layer, x, line_index)
    for li, line in enumerate(raw):
        ws = line.split()
        total = d.textlength(line, font=font)
        x = (W - total) / 2
        for w in ws:
            words.append((word_layer(w, font, k.th["text"]), x, li))
            x += d.textlength(w, font=font) + space
    line_h = 126
    top = 820
    icon = sun_sprite(k.icon, 0, 230) if k.mode == "morning" else moon_sprite(k.icon, 230)
    stars = k.stars(33, 18, 220, 700, avoid=(W / 2, 470), avoid_r=150) if k.mode == "night" else []
    step = min(0.32, 3.4 / max(1, len(words)))

    def frame(t):
        f = k.blank()
        if stars:
            k.draw_stars(f, stars, t, window(t, 0, 1.2))
        p = window(t, 0, 1.4)
        spr = sun_sprite(k.icon, t * 8, 230) if k.mode == "morning" else icon
        paste_c(f, spr, W / 2, 470, p)
        k.label_at(f, t, 680, start=0.8)
        for i, (lay, x, li) in enumerate(words):
            a = window(t, 1.6 + i * step, 0.7)
            if a > 0:
                f.alpha_composite(with_alpha(lay, a), (int(x), top + li * line_h + int((1 - a) * 18)))
        end = 1.6 + len(words) * step + 0.8
        k.footer_at(f, t, top + line_h * len(raw) + 80, end)
        return f
    return frame


def style_frame(k):
    """A fine double gold frame with corner diamonds; mantra in italic serif."""
    font = ImageFont.truetype(str(SERIF_IT), 100)
    lines = k.lines(font, max_w=740)
    col = hexrgb(k.th["label"])
    icon_small = sun_sprite(k.icon, 0, 200) if k.mode == "morning" else moon_sprite(k.icon, 200)
    inset, inset2 = 90, 108
    n = len(lines)
    top = 960 - (n * 116) // 2 + 40

    def border(f, prog):
        layer = Image.new("RGBA", (W * 2, H * 2), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        for ins, wid in ((inset, 4), (inset2, 2)):
            x0, y0, x1, y1 = ins * 2, ins * 2, (W - ins) * 2, (H - ins) * 2
            per = 2 * ((x1 - x0) + (y1 - y0))
            L = per * prog
            segs = [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]
            for (ax, ay), (bx, by) in segs:
                seg = math.hypot(bx - ax, by - ay)
                if L <= 0:
                    break
                u = min(1, L / seg)
                d.line((ax, ay, ax + (bx - ax) * u, ay + (by - ay) * u), fill=col + (255,), width=wid * 2)
                L -= seg
        for cx, cy in ((inset, inset), (W - inset, inset), (W - inset, H - inset), (inset, H - inset)):
            s = 20 * min(1, prog * 1.5)
            cx2, cy2 = cx * 2, cy * 2
            d.polygon([(cx2, cy2 - s * 2), (cx2 + s * 2, cy2), (cx2, cy2 + s * 2), (cx2 - s * 2, cy2)], fill=col + (255,))
        f.alpha_composite(layer.resize((W, H), Image.LANCZOS))

    def frame(t):
        f = k.blank()
        border(f, window(t, 0, 2.6))
        p = window(t, 0.6, 1.6)
        spr = sun_sprite(k.icon, t * 6, 200) if k.mode == "morning" else icon_small
        paste_c(f, spr, W / 2, top - 330, p)
        k.label_at(f, t, top - 150, start=1.2)
        k.lines_at(f, t, lines, top, 116, start=1.9, gap=0.5)
        k.footer_at(f, t, top + 116 * n + 70, 4.6 + 0.5 * n)
        return f
    return frame


def style_radiance(k):
    """Morning: long soft rays sweep out from the sun. Night: the moon glows in soft rings."""
    font = ImageFont.truetype(str(SERIF), 96)
    lines = k.lines(font)
    cx, cy = W / 2, 600
    col = k.icon
    stars = k.stars(51, 30, 120, 860, avoid=(cx, cy), avoid_r=330) if k.mode == "night" else []

    def glow(f, t, p):
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        if k.mode == "morning":
            for i in range(24):
                a = math.radians(i * 15 + t * 3)
                r1, r2 = 240, 240 + 520 * p
                alpha = int(70 if i % 2 == 0 else 38)
                d.line((cx + r1 * math.cos(a), cy + r1 * math.sin(a),
                        cx + r2 * math.cos(a), cy + r2 * math.sin(a)), fill=col + (alpha,), width=5)
        else:
            for i, base in enumerate((190, 250, 320)):
                r = base + 8 * math.sin(t * 1.6 + i)
                alpha = int((120 - i * 30) * p)
                d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=col + (alpha,), width=3)
        f.alpha_composite(layer)

    def frame(t):
        f = k.blank()
        if stars:
            k.draw_stars(f, stars, t, window(t, 0.6, 1.8))
        p = window(t, 0.2, 2.6)
        glow(f, t, p)
        q = window(t, 0, 1.6)
        if k.mode == "morning":
            paste_c(f, sun_sprite(k.icon, -t * 5), cx, cy, q)
        else:
            paste_c(f, k.moon, cx, cy, q)
        k.label_at(f, t, 960, start=1.4)
        k.lines_at(f, t, lines, 1060, 118, start=2.1)
        k.footer_at(f, t, 1060 + 118 * len(lines) + 60, 4.7 + 0.45 * len(lines))
        return f
    return frame


def pick_style(mode):
    d = datetime.date.today().toordinal()
    return STYLES[(d + (2 if mode == "night" else 0)) % len(STYLES)]


def main():
    mode, mantra, out = sys.argv[1], sys.argv[2], sys.argv[3]
    style = sys.argv[4] if len(sys.argv) > 4 else pick_style(mode)
    k = Kit(mode, mantra)
    render = globals()["style_" + style](k)
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", out],
        stdin=subprocess.PIPE)
    bg = Image.new("RGBA", (W, H), k.bg + (255,))
    for fi in range(int(DUR * FPS)):
        t = fi / FPS
        fr = render(t)
        fo = window(t, DUR - 0.6, 0.6)
        if fo > 0:
            fr = Image.blend(fr, bg, fo)
        proc.stdin.write(fr.convert("RGB").tobytes())
    proc.stdin.close()
    proc.wait()
    print(style)


if __name__ == "__main__":
    main()
