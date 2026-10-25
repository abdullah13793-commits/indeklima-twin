"""Outdoor-air change rate from CO2 decay (tracer-gas decay with occupant CO2, cf. ASTM D6245).

A decay window starts when a room empties while the AHU is running and lasts until it is re-occupied or the
AHU stops. With no source, ln(C - Cout) falls linearly with slope -ACH. Only windows with enough signal are
used: start excess >= 150 ppm, >= 25 min, excess stays > 60 ppm in the fit range, fit R^2 >= 0.9.
The inferred ACH is compared with the VAV airflow sensor: a mismatch points at a faulty airflow sensor or
a damper / balancing problem.
"""
import numpy as np
import pandas as pd

C_OUT = 420.0


def windows(g, q_min_ls):
    g = g.reset_index(drop=True)
    empty = (g.occ < 0.5) & g.co2.notna() & (g.q_ls > 0.5 * q_min_ls)
    run_id = (empty != empty.shift()).cumsum()
    for _, seg in g[empty].groupby(run_id[empty]):
        if len(seg) < 5:
            continue
        seg = seg.iloc[2:]                       # skip 10 min for mixing / sensor lag
        exc = seg.co2 - C_OUT
        if exc.iloc[0] < 150:
            continue
        seg = seg[exc > 60]
        if len(seg) < 5:
            continue
        yield seg


def run(r, design):
    rows = []
    for (room, period), g in r.groupby(["room", "period"]):
        d = design[room]
        for seg in windows(g.sort_values("ts"), d["q_min_ls"]):
            tmin = (seg.ts - seg.ts.iloc[0]).dt.total_seconds() / 3600
            y = np.log(seg.co2 - C_OUT)
            A = np.vstack([tmin, np.ones_like(tmin)]).T
            (slope, icpt), res, *_ = np.linalg.lstsq(A, y, rcond=None)
            ss_tot = ((y - y.mean()) ** 2).sum()
            r2 = 1 - (res[0] / ss_tot if len(res) and ss_tot > 0 else 0)
            if r2 < 0.9 or slope >= 0:
                continue
            ach_co2 = -slope
            ach_vav = float((seg.q_ls.mean() / 1000) * 3600 / d["volume_m3"])
            rows.append(dict(room=room, period=period, start=str(seg.ts.iloc[0]), end=str(seg.ts.iloc[-1]),
                             minutes=int(5 * len(seg)), ach_co2=round(float(ach_co2), 3), ach_vav=round(ach_vav, 3),
                             r2=round(float(r2), 3), ratio=round(float(ach_co2 / ach_vav), 3)))
    return pd.DataFrame(rows)


def summarise(dec, design):
    out = []
    for room, g in dec.groupby("room"):
        d = design[room]
        out.append(dict(room=room, n_windows=len(g), ach_co2_median=round(float(g.ach_co2.median()), 2),
                        ach_vav_median=round(float(g.ach_vav.median()), 2),
                        ratio_median=round(float(g.ratio.median()), 2),
                        ach_design=round(d["q_design_ls"] / 1000 * 3600 / d["volume_m3"], 2)))
    return pd.DataFrame(out)
