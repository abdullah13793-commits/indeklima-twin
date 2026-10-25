"""Data quality control. Data faults are reported as QC findings, never as building faults.

Checks: physical range, single-sample spikes (Hampel filter), gaps (per room and storey-wide simultaneous
gaps = gateway outage), flatlines (sensor frozen).
"""
import numpy as np
import pandas as pd

RANGE = {"co2": (300, 5000), "t": (5, 45), "rh": (0, 100), "q_ls": (0, 2000)}


def regular_grid(r):
    """Reindex every room to the full 5-min grid of its period so that gaps become explicit NaN rows."""
    out = []
    r = r.copy()
    r["period"] = np.where(r.ts.dt.month <= 3, "winter", "summer")
    for (room, period), g in r.groupby(["room", "period"]):
        idx = pd.date_range(g.ts.min().normalize(), g.ts.max().normalize() + pd.Timedelta("23:55:00"), freq="5min")
        g = g.set_index("ts").reindex(idx)
        g.index.name = "ts"
        g["room"], g["period"], g["storey"] = room, period, room.split(".")[0]
        out.append(g.reset_index())
    return pd.concat(out, ignore_index=True)


def hampel(s, k=7, nsig=5.0):
    med = s.rolling(k, center=True, min_periods=3).median()
    mad = (s - med).abs().rolling(k, center=True, min_periods=3).median() * 1.4826
    return (s - med).abs() > nsig * mad.clip(lower=10)


def run(r):
    r = regular_grid(r)
    findings = []
    for var, (lo, hi) in RANGE.items():
        bad = (r[var] < lo) | (r[var] > hi)
        r.loc[bad, var] = np.nan
    spikes = r.groupby("room", group_keys=False)["co2"].apply(hampel)
    n_spikes = int(spikes.sum())
    r.loc[spikes.values, "co2"] = np.nan
    # gaps
    r["missing"] = r[["co2", "t", "q_ls"]].isna().all(axis=1)
    for (room, period), g in r.groupby(["room", "period"]):
        run_id = (g.missing != g.missing.shift()).cumsum()
        for _, seg in g[g.missing].groupby(run_id[g.missing]):
            if len(seg) >= 6:   # >= 30 min
                findings.append(dict(kind="gap", room=room, period=period, start=str(seg.ts.iloc[0]),
                                     end=str(seg.ts.iloc[-1]), minutes=5 * len(seg)))
    # storey-wide simultaneous gaps -> gateway outage
    gaps = pd.DataFrame([f for f in findings if f["kind"] == "gap"])
    outages = []
    if len(gaps):
        gaps["storey"] = gaps.room.str.split(".").str[0]
        n_rooms = r.groupby("storey").room.nunique()
        for (storey, start), g in gaps.groupby(["storey", "start"]):
            if len(g) >= max(3, 0.8 * n_rooms[storey]):
                outages.append(dict(kind="gateway_outage", room=f"storey:{storey}", period=g.period.iloc[0],
                                    start=start, end=g.end.max(), minutes=int(g.minutes.max()), rooms=len(g)))
        findings = [f for f in findings if not (f["kind"] == "gap" and any(
            o["room"] == f"storey:{f['room'].split('.')[0]}" and o["start"] == f["start"] for o in outages))] + outages
    # flatline: temperature identical for >= 2 h (sensor frozen)
    for (room, period), g in r.groupby(["room", "period"]):
        t = g.t
        same = t.diff().abs() < 1e-9
        run_id = (same != same.shift()).cumsum()
        for _, seg in g[same.fillna(False)].groupby(run_id[same.fillna(False)]):
            if len(seg) >= 24:
                findings.append(dict(kind="flatline", room=room, period=period, variable="t",
                                     start=str(seg.ts.iloc[0]), end=str(seg.ts.iloc[-1]), minutes=5 * len(seg)))
                r.loc[seg.index, "t"] = np.nan
    # merge flatline runs of the same sensor split by a lost message (< 2 h apart)
    flats = sorted([f for f in findings if f["kind"] == "flatline"], key=lambda f: (f["room"], f["start"]))
    merged = []
    for f in flats:
        if merged and merged[-1]["room"] == f["room"] and \
                pd.Timestamp(f["start"]) - pd.Timestamp(merged[-1]["end"]) <= pd.Timedelta("2h"):
            merged[-1]["end"] = f["end"]
            merged[-1]["minutes"] = int((pd.Timestamp(f["end"]) - pd.Timestamp(merged[-1]["start"])).total_seconds() / 60) + 5
        else:
            merged.append(dict(f))
    findings = [f for f in findings if f["kind"] != "flatline"] + merged
    summary =dict(spikes_removed=n_spikes, completeness=round(float(1 - r.missing.mean()), 4),
                   n_gaps=sum(f["kind"] == "gap" for f in findings),
                   n_outages=sum(f["kind"] == "gateway_outage" for f in findings),
                   n_flatlines=sum(f["kind"] == "flatline" for f in findings))
    return r, findings, summary
