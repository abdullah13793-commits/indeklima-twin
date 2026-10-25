"""Report / gallery figures (light theme, reference palette: series #2a78d6, muted #898781, status critical #d03b3b)."""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
FIG = ROOT / "renders"
S1, MUTE, INK, INK2, GRID, CRIT, GOOD, SURF = "#2a78d6", "#898781", "#0b0b0b", "#52514e", "#e1e0d9", "#d03b3b", "#0ca30c", "#fcfcfb"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": "#c3c2b7", "axes.labelcolor": INK2,
                     "xtick.color": MUTE, "ytick.color": MUTE, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "figure.facecolor": SURF, "axes.facecolor": SURF})

web = json.load(open(ROOT / "web" / "data" / "rooms.json"))
find = json.load(open(ROOT / "web" / "data" / "findings.json"))
r = pd.read_parquet(ROOT / "data" / "store" / "rooms_5min_clean.parquet")
FR = {f["type"]: f["room"] for f in find}          # finding type -> room (never hardcode room ids)


def title(ax, t, sub=None):
    ax.set_title(t, loc="left", fontsize=10.5, fontweight="bold", color=INK, pad=14 if sub else 6)
    if sub:
        ax.text(0, 1.02, sub, transform=ax.transAxes, fontsize=8.5, color=INK2)


def fig_promise():
    fig, ax = plt.subplots(figsize=(6.4, 4.6), dpi=200)
    xs, ys, ids = [], [], []
    for rid, w in web.items():
        if "winter" in w["kpi"]:
            xs.append(w["promise"]["co2_design_ppm"]); ys.append(w["kpi"]["winter"]["co2_p95"]); ids.append(rid)
    lo, hi = 650, max(max(ys), 1200) * 1.05
    ax.plot([lo, hi], [lo, hi], color=MUTE, lw=1, ls="--")
    lim = lambda x: 420 + (x - 420) * 1.15 + 50          # same rule as the verdict (export_web.py)
    ax.fill_between([lo, hi], [lo, hi], [lim(lo), lim(hi)], color=GOOD, alpha=0.10, lw=0)
    broken = sorted([i for i, (x, y) in enumerate(zip(xs, ys)) if y > web[ids[i]]["promise"]["co2_limit_ppm"]], key=lambda i: -ys[i])
    ax.scatter(xs, ys, s=34, color=S1, edgecolor=SURF, linewidth=1.2, zorder=3)
    why = {"airflow_insufficient": "VAV not responding (real breach)", "co2_sensor_drift": "CO₂ sensor drifting (apparent breach)"}
    room_why = {f["room"]: why.get(f["type"], f["type"]) for f in find if f["type"] in why}
    for k, i in enumerate(broken):
        ax.scatter(xs[i], ys[i], s=60, color=CRIT, edgecolor=SURF, linewidth=1.2, zorder=4)
        ax.annotate(f"Room {ids[i]}: {room_why.get(ids[i], 'no diagnosis')}\npromised {xs[i]} ppm, measured {ys[i]} ppm",
                    (xs[i], ys[i]), xytext=(18, -40 if k == 0 else 26), textcoords="offset points", fontsize=8.5, color=INK,
                    arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8))
    ax.text(lo + (hi - lo) * 0.62, lo + (hi - lo) * 0.66, "within promise\n(+15 % on the rise above\noutdoor, +50 ppm sensor)", fontsize=8, color=INK2, rotation=0)
    ax.set_xlim(lo, hi); ax.set_ylim(lo, hi)
    ax.set_xlabel("CO₂ the design promises at design occupancy (ppm)"); ax.set_ylabel("Measured CO₂, P95 occupied (ppm)")
    title(ax, "Design promise vs operation, winter, every monitored room",
          f"{len(xs) - len(broken)} of {len(xs)} rooms keep the CO₂ promise derived from their own MEP design")
    fig.tight_layout(); fig.savefig(FIG / "fig_promise.png"); plt.close(fig)


def fig_ach():
    a = pd.read_csv(ROOT / "results" / "ach_validation_windows.csv", dtype={"room": str})
    v = json.load(open(ROOT / "results" / "ach_validation.json"))
    fig, ax = plt.subplots(figsize=(5.2, 4.4), dpi=200)
    m = max(a.ach_true.max(), a.ach_co2.max()) * 1.05
    ax.fill_between([0, m], [0, m * 0.85], [0, m * 1.15], color=GOOD, alpha=0.08, lw=0)
    ax.plot([0, m], [0, m], color=MUTE, lw=1, ls="--")
    ax.scatter(a.ach_true, a.ach_co2, s=10, color=S1, alpha=0.55, lw=0)
    ax.set_xlim(0, m); ax.set_ylim(0, m)
    ax.set_xlabel("True outdoor-air change rate (1/h)"); ax.set_ylabel("Inferred from CO₂ decay (1/h)")
    title(ax, "Airflow from CO₂ decay vs ground truth",
          f"{v['n_windows']} decay windows · median error {v['median_abs_err'] * 100:.1f} % · bias {v['bias'] * 100:+.1f} % · band ±15 %")
    fig.tight_layout(); fig.savefig(FIG / "fig_ach.png"); plt.close(fig)


def fig_comfort():
    rows = [(rid, w["kpi"]["summer"]["hours_above_26"] / max(w["kpi"]["summer"]["occupied_h"], 1) * 100)
            for rid, w in web.items() if "summer" in w["kpi"]]
    rows.sort(key=lambda t: t[1])
    fig, ax = plt.subplots(figsize=(6.4, 5.4), dpi=200)
    y = np.arange(len(rows))
    vals = [v for _, v in rows]
    cols = [CRIT if rid in {f["room"] for f in find if f["type"] == "solar_gain_increase"} else (S1 if v > 5 else "#b7d3f6") for rid, v in rows]
    ax.barh(y, vals, color=cols, height=0.72)
    ax.axvline(5, color=INK2, lw=1, ls="--")
    ax.text(5.6, 3, "Danish criterion:\n100 h/yr > 26 °C ≈ 5 %", fontsize=8, color=INK2, va="center")
    ax.set_yticks(y, [rid for rid, _ in rows], fontsize=6.5); ax.set_xlabel("Occupied hours above 26 °C (%)")
    ax.grid(axis="y", visible=False)
    n_bad = sum(v > 5 for v in vals)
    title(ax, "Summer overheating by room", f"{n_bad} of {len(vals)} rooms exceed the criterion, mostly dense west/south rooms · red = shading fault")
    fig.tight_layout(); fig.savefig(FIG / "fig_comfort.png"); plt.close(fig)


def fig_evidence():
    from twin import fdd
    wx = pd.read_parquet(ROOT / "data" / "store" / "weather_5min.parquet")
    design = json.load(open(ROOT / "data" / "room_design.json"))
    fig = plt.figure(figsize=(10, 7.0), dpi=200)
    gs = fig.add_gridspec(2, 2, hspace=0.62, wspace=0.28)
    sub = gs[0, 0].subgridspec(2, 1, height_ratios=[2.6, 1], hspace=0.12)
    axs = np.empty((2, 2), dtype=object)
    ax, axq = fig.add_subplot(sub[0]), None
    axq = fig.add_subplot(sub[1], sharex=ax)
    axs[0, 1], axs[1, 0], axs[1, 1] = fig.add_subplot(gs[0, 1]), fig.add_subplot(gs[1, 0]), fig.add_subplot(gs[1, 1])
    # F1 airflow: CO2 (top) and airflow (bottom), separate axes, shared time
    R1 = FR["airflow_insufficient"]
    g = r[(r.room == R1) & (r.period == "winter")].set_index("ts")
    d0 = g.index.min() + pd.Timedelta(days=3)
    gg = g[d0: d0 + pd.Timedelta(days=2)]
    ax.plot(gg.index, gg.co2, color=S1, lw=1.4)
    ax.axhline(web[R1]["promise"]["co2_design_ppm"], color=MUTE, ls="--", lw=1)
    ax.text(gg.index[5], web[R1]["promise"]["co2_design_ppm"] + 60, "promised", fontsize=8, color=INK2)
    ax.set_ylabel("CO₂ (ppm)"); ax.tick_params(labelbottom=False)
    axq.plot(gg.index, gg.q_ls, color=CRIT, lw=1.3)
    axq.axhline(design[R1]["q_design_ls"], color=MUTE, ls="--", lw=0.8)
    axq.text(gg.index[5], design[R1]["q_design_ls"] * 0.78, "design airflow", fontsize=7.5, color=INK2)
    axq.set_ylim(0, design[R1]["q_design_ls"] * 1.2); axq.set_ylabel("L/s")
    axq.xaxis.set_major_locator(matplotlib.dates.HourLocator(byhour=[0, 12]))
    axq.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%a %H:%M"))
    title(ax, f"R1 · Room {R1}: VAV not responding", f"CO₂ climbs to {gg.co2.max():,.0f} ppm while airflow (red) stays at minimum")
    # F2 drift
    ax = axs[0, 1]
    R2 = FR["co2_sensor_drift"]
    for rid in [k for k, w in design.items() if w["kind"] == "office" and w["storey"] == design[R2]["storey"]]:
        h = r[(r.room == rid) & (r.period == "winter") & (r.ts.dt.hour >= 2) & (r.ts.dt.hour < 5)]
        b = h.groupby(h.ts.dt.date).co2.quantile(0.1)
        ax.plot(range(len(b)), b.values, color=CRIT if rid == R2 else "#b7d3f6", lw=2 if rid == R2 else 1,
                marker="o" if rid == R2 else None, ms=3, zorder=3 if rid == R2 else 1)
    ax.set_xlabel("night"); ax.set_ylabel("night CO₂ baseline (ppm)")
    title(ax, f"R2 · Room {R2}: CO₂ sensor drifting", "empty-room baseline keeps rising; other offices on the storey (blue) do not")
    # F4 aperture
    ax = axs[1, 0]
    R4 = FR["solar_gain_increase"]
    ap = fdd.solar_aperture(r, wx, design)
    for rid in ap:
        ax.plot(range(len(ap)), ap[rid].values, color=CRIT if rid == R4 else "#cde2fb", lw=2.2 if rid == R4 else 0.8,
                zorder=3 if rid == R4 else 1)
    ax.set_xticks(range(len(ap)), [d.strftime("%d %b") for d in ap.index], rotation=45, fontsize=7)
    ax.set_ylabel("effective solar aperture (m²)")
    title(ax, f"R4 · Room {R4}: solar shading not deploying", f"inverse energy balance: aperture ~×3; {len(ap.columns) - 1} peers (blue) flat")
    # F7 night temps
    ax = axs[1, 1]
    w = r[(r.period == "winter") & (r.ts.dt.hour >= 1) & (r.ts.dt.hour < 5)]
    nt = w.groupby([w.room, w.ts.dt.date]).t.mean().unstack(0)
    ax.fill_between(range(len(nt)), nt.quantile(0.1, axis=1), nt.quantile(0.9, axis=1), color="#cde2fb", lw=0, label="other rooms P10-P90")
    R5 = FR["heating_no_setback"]
    ax.plot(range(len(nt)), nt[R5], color=CRIT, lw=2, marker="o", ms=3)
    ax.axhline(19, color=MUTE, ls="--", lw=1); ax.text(0.2, 19.2, "night setback 19 °C", fontsize=8, color=INK2)
    ax.set_xlabel("night"); ax.set_ylabel("night temperature (°C)")
    title(ax, f"R5 · Room {R5}: heating ignores setback", "valve stuck open; the other rooms follow the night setback")
    fig.savefig(FIG / "fig_evidence.png", bbox_inches="tight"); plt.close(fig)


def fig_pipeline():
    fig, ax = plt.subplots(figsize=(10, 2.6), dpi=200); ax.axis("off"); ax.set_xlim(0, 10); ax.set_ylim(0, 2.6)
    boxes = [("Design", "IFC spaces +\nMEP design airflow\n(EN 16798-1)"), ("Sensors", "MQTT / JSONL\nCO₂ · T · RH · VAV · occ"),
             ("Ingest + QC", "DuckDB → Parquet\ngaps · spikes · flatlines"), ("Analytics", "EN 16798-1 categories\nCO₂-decay airflow"),
             ("Diagnosis", "5 FDD rules\nwith evidence"), ("Write-back", "IFC Psets · BCF 2.1\nBrick · dashboard")]
    for i, (h, t) in enumerate(boxes):
        x = 0.1 + i * 1.65
        ax.add_patch(FancyBboxPatch((x, 0.55), 1.4, 1.5, boxstyle="round,pad=0.02,rounding_size=0.12", fc="white",
                                    ec=S1 if i in (0, 5) else "#c3c2b7", lw=1.4 if i in (0, 5) else 0.8))
        ax.text(x + 0.7, 1.72, h, ha="center", fontsize=10, fontweight="bold", color=INK)
        ax.text(x + 0.7, 1.1, t, ha="center", va="center", fontsize=7.6, color=INK2)
        if i < 5:
            ax.annotate("", (x + 1.62, 1.3), (x + 1.42, 1.3), arrowprops=dict(arrowstyle="-|>", color=INK2, lw=1))
    ax.annotate("", (0.8, 0.5), (9.15, 0.5), arrowprops=dict(arrowstyle="-|>", color=S1, lw=1.2, connectionstyle="arc3,rad=0.25"))
    ax.text(5, 0.06, "results go back into the same model and tools the project already uses", ha="center", fontsize=8.5, color=S1)
    fig.savefig(FIG / "fig_pipeline.png", bbox_inches="tight"); plt.close(fig)


if __name__ == "__main__":
    for f in (fig_promise, fig_ach, fig_comfort, fig_evidence, fig_pipeline):
        f(); print("ok", f.__name__)
