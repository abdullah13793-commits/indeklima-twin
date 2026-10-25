"""Export compact JSON for the static dashboard (web/data/)."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web" / "data"
RES = ROOT / "results"


def main():
    WEB.mkdir(parents=True, exist_ok=True)
    design = json.load(open(ROOT / "data" / "room_design.json"))
    r = pd.read_parquet(ROOT / "data" / "store" / "rooms_5min_clean.parquet")
    wx = pd.read_parquet(ROOT / "data" / "store" / "weather_5min.parquet")
    ieq = pd.read_json(RES / "ieq_by_room.json", dtype={"room": str})
    vent = pd.read_csv(RES / "ventilation_by_room.csv", dtype={"room": str}).set_index("room")
    fdd = json.load(open(RES / "fdd_findings.json"))
    qc = json.load(open(RES / "qc.json"))
    ev = json.load(open(RES / "fdd_evaluation.json"))
    ach = json.load(open(RES / "ach_validation.json"))
    rob = json.load(open(RES / "robustness.json"))

    # ---- 15-min series per period, integers for size
    series = {}
    for period, g in r.groupby("period"):
        g = g.set_index("ts")
        idx = pd.date_range(g.index.min().floor("D"), g.index.max().ceil("D") - pd.Timedelta("15min"), freq="15min")
        out = {"t0": str(idx[0]), "step_min": 15, "n": len(idx), "rooms": {}}
        for room, gr in g.groupby("room"):
            a = gr[["co2", "t", "q_ls", "occ"]].resample("15min").mean().reindex(idx)
            enc = lambda s, k: [None if pd.isna(v) else int(round(v * k)) for v in s]
            out["rooms"][room] = {"co2": enc(a.co2, 1), "t": enc(a.t, 10), "q": enc(a.q_ls, 1), "occ": enc(a.occ, 1)}
        w = wx.set_index("ts")
        w = w[(w.index >= idx[0]) & (w.index <= idx[-1] + pd.Timedelta("15min"))].resample("15min").mean().reindex(idx)
        out["weather"] = {"t_out": [None if pd.isna(v) else int(round(v * 10)) for v in w.t_out],
                          "ghi": [None if pd.isna(v) else int(round(v)) for v in w.ghi]}
        series[period] = out
        json.dump(out, open(WEB / f"series_{period}.json", "w"), separators=(",", ":"))

    # ---- rooms
    rooms = {}
    for rid, d in design.items():
        k = {}
        for _, row in ieq[ieq.room == rid].iterrows():
            k[row.period] = dict(co2_within_II=row.co2_within_II, t_within_II=row.t_within_II, co2_p95=row.co2_p95,
                                 hours_above_26=row.hours_above_26, hours_above_27=row.hours_above_27,
                                 too_warm_II=row.too_warm_II, too_cool_II=row.too_cool_II, occupied_h=row.occupied_h)
        v = vent.loc[rid].to_dict() if rid in vent.index else {}
        # design promise: CO2 rise at design occupancy and design airflow (steady state, N G / q) + EN 16798-1 cat II
        dc_design = d["persons"] * 0.0052 / d["q_design_ls"] * 1e6
        promise = dict(co2_design_ppm=round(420 + dc_design), co2_limit_ppm=round(420 + max(dc_design * 1.15 + 50, 0)),
                       cat="II")
        verdicts = {}
        for p, kk in k.items():
            co2_ok = kk["co2_p95"] <= promise["co2_limit_ppm"]
            if p == "winter":      # EN 16798-1: <= 5 % of occupied hours outside the category range
                t_ok = kk["t_within_II"] is not None and kk["t_within_II"] >= 0.95
            else:                  # Danish practice: <= 100 h > 26 C and <= 25 h > 27 C per ~2000 occupied h/year
                occ_h = max(kk["occupied_h"], 1)
                t_ok = kk["hours_above_26"] / occ_h <= 0.05 and kk["hours_above_27"] / occ_h <= 0.0125
            verdicts[p] = dict(co2_kept=bool(co2_ok), t_kept=bool(t_ok))
        promise["verdict"] = verdicts
        rooms[rid] = dict(d, kpi=k, ventilation=v, promise=promise,
                          findings=[f["rule"] for f in fdd if f["room"] in (rid, f"storey:{d['storey']}")])
    json.dump(rooms, open(WEB / "rooms.json", "w"), indent=0)
    promise_stats = {p: dict(co2_kept=sum(r["promise"]["verdict"].get(p, {}).get("co2_kept", False) for r in rooms.values()),
                             t_kept=sum(r["promise"]["verdict"].get(p, {}).get("t_kept", False) for r in rooms.values()),
                             rooms=sum(p in r["promise"]["verdict"] for r in rooms.values()))
                     for p in ("winter", "summer")}

    # ---- findings (FDD + QC data faults), each with an evidence window id
    items = []
    for f in fdd:
        items.append(dict(f, src="FDD"))
    for q in qc["qc_findings"]:
        if q["kind"] in ("flatline", "gateway_outage"):
            items.append(dict(rule="QC", type=q["kind"], category="data", room=q["room"], period=q["period"],
                              start=q["start"], end=q["end"], src="QC",
                              evidence=f"{q['kind'].replace('_', ' ')} for {q['minutes'] / 60:.1f} h"
                                       + (f" on {q.get('rooms')} rooms" if q.get("rooms") else ""),
                              diagnosis="data issue: not reported as a building fault"))
    json.dump(items, open(WEB / "findings.json", "w"), indent=1, default=str)

    # ---- comfort findings (design-stage issues, not faults): rooms with > 10 % occupied hours outside cat II
    comfort = []
    for _, row in ieq.iterrows():
        if row.t_within_II is not None and row.t_within_II < 0.9:
            comfort.append(dict(room=row.room, period=row.period, t_within_II=row.t_within_II,
                                hours_above_26=row.hours_above_26))
    occ = ieq
    summary = dict(
        rooms_monitored=len(design), messages=qc["ingest"]["messages"], completeness=qc["qc"]["completeness"],
        spikes_removed=qc["qc"]["spikes_removed"],
        co2_within_II={p: round(float(g.co2_within_II.mean()), 3) for p, g in occ.groupby("period")},
        t_within_II={p: round(float(g.t_within_II.mean()), 3) for p, g in occ.groupby("period")},
        findings=len(items), building_faults=len(fdd), recall=f"{sum(x['detected'] for x in ev['faults'])}/{len(ev['faults'])}",
        false_alarms=ev["n_false_alarms"], ach=ach, robustness=rob, comfort_issues=comfort, promise=promise_stats,
        q_design_total_ls=round(sum(d["q_design_ls"] for d in design.values())))
    json.dump(summary, open(WEB / "summary.json", "w"), indent=1)
    sizes = {p.name: round(p.stat().st_size / 1e6, 2) for p in WEB.iterdir()}
    print(sizes)


if __name__ == "__main__":
    main()
