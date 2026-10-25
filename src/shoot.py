"""Gallery screenshots and walkthrough video frames of the dashboard (Edge headless, software WebGL).

python src/shoot.py gallery          -> publish/02_dashboard_*.png
python src/shoot.py video            -> publish/indeklima_walkthrough.mp4
Needs the dashboard served on http://localhost:8077 (python -m http.server 8077 --directory web).
"""
import json
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PUB = ROOT / "publish"
URL = "http://localhost:8077/index.html?theme=dark"
ARGS = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]
F = json.load(open(ROOT / "web" / "data" / "findings.json"))
FR = {f["type"]: f for f in F}


def open_page(pw, w=1600, h=1000):
    b = pw.chromium.launch(channel="msedge", headless=True, args=ARGS)
    pg = b.new_page(viewport={"width": w, "height": h})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(URL)
    pg.wait_for_function("window.Twin && window.Twin.ready", timeout=120000)
    pg.wait_for_timeout(800)
    return b, pg, errs


def idx_of(f, extra_h=10.5):
    t0 = {"winter": "2026-02-02", "summer": "2026-06-15"}[f["period"]]
    import pandas as pd
    return int((pd.Timestamp(str(f["start"])) - pd.Timestamp(t0)).total_seconds() / 900 + extra_h * 4)


def gallery():
    with sync_playwright() as pw:
        b, pg, errs = open_page(pw)
        f1 = FR["airflow_insufficient"]
        pg.evaluate(f"Twin.setPeriod('winter'); Twin.selectRoom('{f1['room']}'); Twin.setTime({idx_of(f1)}); Twin.render()")
        pg.wait_for_timeout(500); pg.screenshot(path=str(PUB / "02_dashboard_co2.png"))
        f4 = FR["solar_gain_increase"]
        pg.evaluate(f"Twin.setPeriod('summer'); Twin.setMetric('t'); Twin.selectRoom('{f4['room']}'); Twin.setTime({idx_of(f4, 15)}); Twin.render()")
        pg.wait_for_timeout(500); pg.screenshot(path=str(PUB / "03_dashboard_temperature.png"))
        pg.evaluate(f"Twin.setStorey('{f4['room'].split('.')[0]}'); Twin.render()")
        pg.wait_for_timeout(500); pg.screenshot(path=str(PUB / "04_dashboard_storey.png"))
        b.close()
        print("gallery ok", errs)


def video(n=220, fps=24):
    frames = ROOT / "renders" / "frames"; frames.mkdir(exist_ok=True)
    for p in frames.glob("*.png"):
        p.unlink()
    f1 = FR["airflow_insufficient"]
    start = idx_of(f1, 6) - 8
    with sync_playwright() as pw:
        b, pg, errs = open_page(pw, 1600, 900)
        pg.evaluate(f"Twin.setPeriod('winter'); Twin.selectRoom('{f1['room']}')")
        for i in range(n):
            pg.evaluate(f"Twin.setTime({start + i // 2}); Twin.orbit(0.35); Twin.render()")
            pg.screenshot(path=str(frames / f"f{i:04d}.png"))
        b.close()
    import imageio_ffmpeg
    out = PUB / "indeklima_walkthrough.mp4"
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-framerate", str(fps), "-i", str(frames / "f%04d.png"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "22", "-preset", "slow", str(out)], check=True,
                   capture_output=True)
    print("video", out, round(out.stat().st_size / 1e6, 1), "MB", errs)


def linkedin_footage():
    """1920x1080 frames for the LinkedIn film: A) a winter day 06-18 h with a slow orbit, B) storey 2 + room card."""
    out = ROOT / "renders" / "li_dash"; out.mkdir(exist_ok=True)
    for p in out.glob("*.png"):
        p.unlink()
    f1 = FR["airflow_insufficient"]
    day0 = idx_of(f1, 0)                                   # midnight of the fault's first day
    with sync_playwright() as pw:
        b, pg, errs = open_page(pw, 1920, 1080)
        pg.evaluate("Twin.setPeriod('winter'); Twin.orbit(-35)")
        k = 0
        for i in range(110):                                # A: 06:00 -> ~19:45 in 15-min steps, 2 frames each
            pg.evaluate(f"Twin.setTime({day0 + 24 + i // 2}); Twin.orbit(0.33); Twin.render()")
            pg.screenshot(path=str(out / f"a{k:04d}.png")); k += 1
        pg.evaluate(f"Twin.setStorey('{f1['room'].split('.')[0]}'); Twin.selectRoom('{f1['room']}'); Twin.setTime({day0 + 54})")
        for i in range(60):                                 # B: storey 2, the stuck-damper room selected
            pg.evaluate(f"Twin.setTime({day0 + 54 + i // 6}); Twin.orbit(0.25); Twin.render()")
            pg.screenshot(path=str(out / f"b{i:04d}.png"))
        b.close()
    print("footage ok", errs)


if __name__ == "__main__":
    {"gallery": gallery, "video": video, "linkedin": linkedin_footage}[sys.argv[1]]()
