"""EN 16798-1 indoor-environment categories per room (occupied hours only).

CO2 above outdoor (Annex B, default values): cat I <= 550, II <= 800, III <= 1350 ppm, IV above.
Operative temperature (approximated by air temperature; offices, sedentary):
  heating season  I 21-23, II 20-24, III 19-25 ;  cooling season  I 23.5-25.5, II 23-26, III 22-27
"""
import numpy as np
import pandas as pd

C_OUT = 420.0
CO2_LIM = [550, 800, 1350]
T_LIM = {"winter": [(21, 23), (20, 24), (19, 25)], "summer": [(23.5, 25.5), (23, 26), (22, 27)]}


def co2_cat(dc):
    return np.select([dc <= CO2_LIM[0], dc <= CO2_LIM[1], dc <= CO2_LIM[2]], [1, 2, 3], 4)


def t_cat(t, period):
    lims = T_LIM[period]
    conds = [(t >= lo) & (t <= hi) for lo, hi in lims]
    return np.select(conds, [1, 2, 3], 4)


def run(r):
    occ = r[(r.occ > 0.5) & r.co2.notna()].copy()
    occ["co2_cat"] = co2_cat(occ.co2 - C_OUT)
    occ["t_cat"] = np.nan
    for p in ("winter", "summer"):
        m = (occ.period == p) & occ.t.notna()
        occ.loc[m, "t_cat"] = t_cat(occ.loc[m, "t"], p)
    rows = []
    for (room, period), g in occ.groupby(["room", "period"]):
        n = len(g)
        tc = g.t_cat.dropna()
        rows.append(dict(room=room, period=period, occupied_h=round(n / 12, 1),
                         co2_p95=round(float(g.co2.quantile(0.95))),
                         co2_cat_share={k: round(float((g.co2_cat == k).mean()), 3) for k in (1, 2, 3, 4)},
                         t_cat_share={k: round(float((tc == k).mean()), 3) for k in (1, 2, 3, 4)},
                         co2_within_II=round(float((g.co2_cat <= 2).mean()), 3),
                         t_within_II=round(float((tc <= 2).mean()), 3) if len(tc) else None,
                         too_warm_II=round(float((g.t > T_LIM[period][1][1]).mean()), 3),
                         too_cool_II=round(float((g.t < T_LIM[period][1][0]).mean()), 3),
                         hours_above_26=round(float((g.t > 26).sum() / 12), 1),
                         hours_above_27=round(float((g.t > 27).sum() / 12), 1),
                         rh_min=round(float(g.rh.min()), 1), rh_max=round(float(g.rh.max()), 1)))
    return pd.DataFrame(rows)
