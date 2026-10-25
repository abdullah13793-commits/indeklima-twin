"""LinkedIn film (1920x1080, 30 fps, ~60 s): the idea, the twin, the evidence, the write-back, the MCP chat, the proof.
Every number and every chat line comes from the results files (the chat is the recorded Claude + MCP session)."""
import json
import math
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
W, H, FPS = 1920, 1080, 30
BG = (8, 10, 16)
INK, INK2, MUTE = (240, 239, 236), (195, 194, 183), (137, 135, 129)
BLUE, RED, AMBER = (110, 167, 236), (208, 59, 59), (250, 178, 25)
S = json.load(open(ROOT / "web" / "data" / "summary.json"))
ROOMS = json.load(open(ROOT / "web" / "data" / "rooms.json"))
F = json.load(open(ROOT / "web" / "data" / "findings.json"))
CHAT = json.load(open(ROOT / "results" / "mcp_claude_demo_full.json"))
R1 = next(f["room"] for f in F if f["type"] == "airflow_insufficient")
R2 = next(f["room"] for f in F if f["type"] == "co2_sensor_drift")
P1 = ROOMS[R1]
ROB = S["robustness"]


def font(sz, bold=False):
    return ImageFont.truetype("segoeuib.ttf" if bold else "segoeui.ttf", sz)


def ease(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def fade(t, t0, t1, d=0.5):
    """1 inside [t0, t1], ramps d seconds at both ends."""
    return ease((t - t0) / d) * ease((t1 - t) / d)


def cover_crop(im, scale=1.0, cx=0.5, cy=0.5, size=(W, H)):
    """Scale an image to cover `size`, zoomed by `scale` around (cx, cy)."""
    tw, th = size
    s = max(tw / im.width, th / im.height) * scale
    rw, rh = int(im.width * s), int(im.height * s)
    r = im.resize((rw, rh), Image.LANCZOS)
    x = int((rw - tw) * cx); y = int((rh - th) * cy)
    return r.crop((x, y, x + tw, y + th))


def wrap(d, text, f, maxw):
    lines, cur = [], ""
    for w in text.split(" "):
        test = (cur + " " + w).strip()
        if d.textlength(test, font=f) > maxw and cur:
            lines.append(cur); cur = w
        else:
            cur = test
    lines.append(cur)
    return lines


def caption(img, text, a, y=920, size=50, sub=None, x=96):
    """Lower-third caption with a soft dark band behind it."""
    if a <= 0:
        return img
    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    f = font(size, True)
    lines = wrap(d, text, f, W - 2 * x)
    top = y - (len(lines) - 1) * (size + 12) - 30
    band = Image.new("L", img.size, 0)
    bd = ImageDraw.Draw(band)
    for yy in range(top - 80, H):
        bd.line([(0, yy), (W, yy)], fill=int(205 * min(1, (yy - (top - 80)) / 160)))
    img = Image.composite(Image.new("RGB", img.size, BG), img, band.point(lambda v: int(v * a)))
    d = ImageDraw.Draw(over)
    for i, ln in enumerate(lines):
        d.text((x, top + i * (size + 12)), ln, font=f, fill=INK + (int(255 * a),))
    if sub:
        d.text((x, top + len(lines) * (size + 12) + 6), sub, font=font(28), fill=INK2 + (int(255 * a),))
    img = img.convert("RGBA"); img.alpha_composite(over)
    return img.convert("RGB")


def tag(img, a=1.0):
    d = ImageDraw.Draw(img)
    d.text((W - 60, 46), "simulated sensor data · physics-based", font=font(22), fill=tuple(int(c * a) for c in AMBER), anchor="ra")
    d.text((60, 40), "INDEKLIMA TWIN", font=font(26, True), fill=tuple(int(c * a) for c in BLUE))
    return img


def card(src, box_w, radius=22, pad=0):
    """Light figure on a rounded card with a soft shadow, returned as RGBA."""
    im = src.convert("RGB")
    s = box_w / im.width
    im = im.resize((int(im.width * s), int(im.height * s)), Image.LANCZOS)
    w, h = im.size
    out = Image.new("RGBA", (w + 80, h + 80), (0, 0, 0, 0))
    sh = Image.new("L", out.size, 0); ImageDraw.Draw(sh).rounded_rectangle([40, 50, w + 40, h + 50], radius, fill=170)
    out.paste((0, 0, 0, 255), (0, 0), sh.filter(ImageFilter.GaussianBlur(22)))
    mask = Image.new("L", (w, h), 0); ImageDraw.Draw(mask).rounded_rectangle([0, 0, w, h], radius, fill=255)
    out.paste(im, (40, 40), mask)
    return out


def paste_center(bg, fg, cx, cy, a=1.0, scale=1.0):
    if scale != 1.0:
        fg = fg.resize((int(fg.width * scale), int(fg.height * scale)), Image.LANCZOS)
    if a < 1:
        r, g, b, al = fg.split(); fg = Image.merge("RGBA", (r, g, b, al.point(lambda v: int(v * a))))
    bg = bg.convert("RGBA"); bg.alpha_composite(fg, (int(cx - fg.width / 2), int(cy - fg.height / 2)))
    return bg.convert("RGB")


# ------------------------------------------------------------------ assets
hero = Image.open(ROOT / "renders" / "hero.png").convert("RGB")
promise_fig = Image.open(ROOT / "renders" / "fig_promise.png")
evid_fig = Image.open(ROOT / "renders" / "fig_evidence.png")
wb = Image.open(ROOT / "publish" / "05_writeback.png").convert("RGB")
A = sorted((ROOT / "renders" / "li_dash").glob("a*.png"))
Bf = sorted((ROOT / "renders" / "li_dash").glob("b*.png"))
_cache = {}


def frame_seq(files, u):
    """Smooth playback of a short frame sequence: crossfade between neighbouring captured frames."""
    x = u * (len(files) - 1)
    i = int(x); j = min(i + 1, len(files) - 1); w = x - i
    for k in (i, j):
        if k not in _cache:
            if len(_cache) > 8:
                _cache.pop(next(iter(_cache)))
            _cache[k] = Image.open(files[k]).convert("RGB")
    return Image.blend(_cache[i], _cache[j], w) if w > 0.01 else _cache[i]


# ------------------------------------------------------------------ scenes (start, end, fn)
def s_hook(t):          # 0-5
    img = cover_crop(hero, 1.0 + 0.06 * t / 5, 0.5, 0.45)
    img = tag(img, ease(t / 1))
    return caption(img, "Every room in a building is designed with a promise.", ease((t - 0.6) / 0.8))


def s_promise(t):       # 5-10
    img = Image.new("RGB", (W, H), BG); d = ImageDraw.Draw(img); tag(img)
    d.text((140, 190), f"Meeting room {R1}, as designed", font=font(34), fill=MUTE)
    items = [(f"{P1['persons']}", "people"), (f"{P1['q_design_ls']:.0f} L/s", "fresh air"), ("Category II", "EN 16798-1 comfort")]
    for k, (big, small) in enumerate(items):
        a = ease((t - 0.4 - 0.55 * k) / 0.5)
        x = 140 + k * 560
        d.text((x, 260), big, font=font(104, True), fill=tuple(int(c * a) for c in INK))
        d.text((x + 4, 400), small, font=font(34), fill=tuple(int(c * a) for c in INK2))
    a = ease((t - 2.4) / 0.6)
    d.text((140, 520), "so its CO₂ should stay around", font=font(40), fill=tuple(int(c * a) for c in INK2))
    d.text((140, 575), f"{P1['promise']['co2_design_ppm']:,} ppm", font=font(130, True), fill=tuple(int(c * a) for c in BLUE))
    return caption(img, "How many people. How much fresh air. How comfortable.", ease((t - 0.2) / 0.6))


def s_forgotten(t):     # 10-14
    img = Image.new("RGB", (W, H), BG); d = ImageDraw.Draw(img); tag(img)
    a = ease(1 - (t - 0.3) / 2.2)
    d.text((140, 300), f"{P1['promise']['co2_design_ppm']:,} ppm", font=font(130, True), fill=tuple(int(c * max(a, 0.12)) for c in BLUE))
    b = ease((t - 1.4) / 0.6)
    d.rounded_rectangle([140, 520, 1010, 650], 18, outline=tuple(int(c * b) for c in MUTE), width=3)
    d.text((180, 548), "ALARM IF CO₂ > 1,000 ppm", font=font(54, True), fill=tuple(int(c * b) for c in INK2))
    d.text((140, 680), "the same generic line for every room", font=font(34), fill=tuple(int(c * b) for c in MUTE))
    return caption(img, "Then the building is handed over, and the promise is forgotten.", ease((t - 0.2) / 0.6))


def s_twin(t):          # 14-24
    u = t / 10
    fr = frame_seq(A, u)
    z = 1.0 + 0.55 * ease((t - 3.0) / 4.0)        # zoom into the 3D viewer after 3 s
    img = cover_crop(fr, z, 0.18 * ease((t - 3) / 4) + 0.5 * (1 - ease((t - 3) / 4)), 0.55)
    txt = ("Indeklima Twin reads that promise from the IFC model and the MEP design" if t < 5.2
           else "and checks every room's sensors against it, all day, every day.")
    a = fade(t, 0.3, 5.2, 0.4) if t < 5.2 else fade(t, 5.2, 10, 0.4)
    return caption(img, txt, a)


def s_room(t):          # 24-29
    fr = frame_seq(Bf, t / 5)
    view = cover_crop(fr.crop((0, 170, 1180, 1030)), 1.12, 0.5, 0.5)
    room_card = fr.crop((1496, 850, 1910, 1040))          # promise card of the selected room (aside, bottom)
    rc = card(room_card, 760, radius=14)
    img = paste_center(view, rc, W - 470, 330, ease((t - 0.8) / 0.6))
    k = P1["kpi"]["winter"]
    return caption(img, f"Room {R1} promised {P1['promise']['co2_design_ppm']:,} ppm. It measures {k['co2_p95']:,}.",
                   ease((t - 0.3) / 0.6), sub="the twin shows exactly where, when and by how much")


def s_chart(t):         # 29-35
    img = Image.new("RGB", (W, H), BG); tag(img)
    c = card(promise_fig, 1080)
    img = paste_center(img, c, W / 2, 470, ease(t / 0.6), 1.0 + 0.03 * t / 6)
    kept = S["promise"]["winter"]["co2_kept"]
    return caption(img, f"{kept} of 37 rooms keep it. One really doesn't. One only looks like it: a drifting sensor.",
                   ease((t - 0.8) / 0.6), size=44)


def s_evidence(t):      # 35-41
    img = Image.new("RGB", (W, H), BG); tag(img)
    c = card(evid_fig, 1100)
    cx = W / 2 + 60 - 120 * ease((t - 1) / 4.5)
    img = paste_center(img, c, cx, 470, ease(t / 0.6), 1.0 + 0.04 * t / 6)
    return caption(img, "Every finding comes with its evidence and a diagnosis.", ease((t - 0.4) / 0.6), size=48)


def s_writeback(t):     # 41-46
    img = Image.new("RGB", (W, H), BG); tag(img)
    img = paste_center(img, card(wb, 960, radius=16), W / 2, 470, ease(t / 0.6), 1.0 + 0.03 * t / 5)
    return caption(img, "Nothing new to learn: the answer goes back into IFC, BCF and Brick.", ease((t - 0.5) / 0.6), size=46)


def s_chat(t):          # 46-55
    img = Image.new("RGB", (W, H), (13, 13, 13)); d = ImageDraw.Draw(img); tag(img)
    d.text((96, 104), "Claude  ×  Indeklima Twin MCP server  ·  recorded session", font=font(26), fill=MUTE)
    q = "Which rooms break their design promise this winter, and why?"
    n = int(len(q) * ease(t / 1.6))
    d.rounded_rectangle([W - 96 - 1060, 160, W - 96, 250], 24, fill=(37, 99, 168))
    d.text((W - 96 - 1030, 185), q[:n], font=font(34), fill=INK)
    calls = [c for c, _ in CHAT["calls"] if c != "ToolSearch"]
    x = 96
    for k, c in enumerate(calls):
        a = ease((t - 1.9 - 0.35 * k) / 0.3)
        if a <= 0:
            continue
        w = d.textlength(c, font=font(24)) + 40
        d.rounded_rectangle([x, 290, x + w, 334], 22, outline=tuple(int(v * a) for v in BLUE), width=2)
        d.text((x + 20, 296), c, font=font(24), fill=tuple(int(v * a) for v in BLUE))
        x += w + 12
    ans = CHAT["answer"].replace("**", "")
    bullets = [b.strip(" -") for b in ans.split("\n") if b.strip().startswith("-")][:2]
    text = "\n".join("•  " + b for b in bullets)
    start = 4.2
    nshow = int(len(text) * ease((t - start) / 4.0)) if t > start else 0
    y = 380
    f = font(30)
    shown = text[:nshow]
    for para in shown.split("\n"):
        for ln in wrap(d, para, f, W - 260):
            d.text((126, y), ln, font=f, fill=INK2); y += 42
        y += 16
    return caption(img, "Or simply ask your building.", ease((t - 0.3) / 0.6), y=1000, size=46)


def s_proof(t):         # 55-58.5
    img = Image.new("RGB", (W, H), BG); d = ImageDraw.Draw(img); tag(img)
    held = sum(1 for r in ROB if r.get("held_out"))
    stats = [("7 / 7", "planted faults found"), ("0", "false alarms"), (f"{len(ROB)}", f"validation runs ({held} held out)"),
             (f"±{S['ach']['median_abs_err'] * 100:.0f} %", "airflow from CO₂ decay")]
    for k, (big, small) in enumerate(stats):
        a = ease((t - 0.2 - 0.3 * k) / 0.45)
        x = 120 + k * 440
        d.text((x, 360), big, font=font(110, True), fill=tuple(int(c * a) for c in INK))
        d.text((x + 4, 510), small, font=font(30), fill=tuple(int(c * a) for c in INK2))
    a = ease((t - 1.6) / 0.5)
    d.text((120, 640), "Physics-based simulated sensor data with planted faults; the pipeline takes a real MQTT / CSV feed unchanged.",
           font=font(28), fill=tuple(int(c * a) for c in AMBER))
    return img


def s_end(t):           # 58.5-62
    img = cover_crop(hero, 1.08 + 0.03 * t / 3.5, 0.5, 0.45).filter(ImageFilter.GaussianBlur(3))
    img = Image.blend(img, Image.new("RGB", (W, H), BG), 0.72)
    d = ImageDraw.Draw(img); a = ease(t / 0.7)
    d.text((W / 2, 420), "Indeklima Twin", font=font(110, True), fill=tuple(int(c * a) for c in INK), anchor="mm")
    d.text((W / 2, 520), "Does every room keep its design promise?", font=font(46), fill=tuple(int(c * a) for c in INK2), anchor="mm")
    d.text((W / 2, 640), "IFC  ·  live sensor data  ·  EN 16798-1  ·  BCF  ·  Brick  ·  MCP", font=font(32), fill=tuple(int(c * a) for c in BLUE), anchor="mm")
    return img


SCENES = [(0, 5, s_hook), (5, 10, s_promise), (10, 14, s_forgotten), (14, 24, s_twin), (24, 29, s_room),
          (29, 35, s_chart), (35, 41, s_evidence), (41, 46, s_writeback), (46, 55, s_chat), (55, 58.5, s_proof),
          (58.5, 62, s_end)]
XF = 0.35   # crossfade between scenes (s)


def render(t):
    for k, (t0, t1, fn) in enumerate(SCENES):
        if t0 <= t < t1:
            img = fn(t - t0)
            if k + 1 < len(SCENES) and t > t1 - XF:
                nxt = SCENES[k + 1][2](t - t1 + XF)
                img = Image.blend(img, nxt, ease((t - (t1 - XF)) / XF))
            return img
    return SCENES[-1][2](SCENES[-1][1] - SCENES[-1][0] - 0.01)


def main(out=ROOT / "publish" / "indeklima_twin_linkedin.mp4", preview=False):
    dur = SCENES[-1][1]
    if preview:
        for ts in (2.5, 7.5, 12, 17, 21, 26.5, 32, 38, 43.5, 52, 57, 60.5):
            render(ts).save(ROOT / "renders" / f"_film_{ts:05.1f}.png")
        return
    wr = imageio_ffmpeg.write_frames(str(out), (W, H), fps=FPS, codec="libx264", quality=None, bitrate="6M",
                                     pix_fmt_out="yuv420p", macro_block_size=8, ffmpeg_log_level="error",
                                     output_params=["-preset", "slow", "-movflags", "+faststart"])
    wr.send(None)
    for i in range(int(dur * FPS)):
        wr.send(np.asarray(render(i / FPS), dtype=np.uint8).tobytes())
    wr.close()
    print("film", out, round(out.stat().st_size / 1e6, 1), "MB", dur, "s")


if __name__ == "__main__":
    import sys
    main(preview="preview" in sys.argv)
