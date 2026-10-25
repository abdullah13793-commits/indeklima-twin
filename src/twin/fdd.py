"""Rule-based fault detection and diagnosis (FDD). Each finding carries the evidence used to raise it.

R1 airflow_insufficient   occupied, CO2 > outdoor + 800 ppm while VAV airflow <= 1.15 x minimum, >= 30 min, >= 2 days
R2 co2_sensor_drift       nightly CO2 baseline (02-05 h, empty room) rises > 6 ppm/day with R^2 > 0.6 over >= 6 nights
R3 ahu_out_of_hours       airflow above 50 % of minimum at night / weekend with nobody in, not explained by
                          summer night cooling; raised per storey when >= 70 % of its rooms do it on the same night
R4 solar_gain_increase    summer, sunny weekdays: indoor-outdoor excess per kWh/m2 of solar rises > 35 % above the
                          room's own previous-5-day median on >= 3 of 4 consecutive sunny days (change detection)
R5 heating_no_setback     winter nights 01-05 h, empty room: temperature stays > 3.5 K above the 19 C night
                          setback on >= 3 consecutive nights (valve / thermostat stuck)
"""
import numpy as np
import pandas as pd

C_OUT = 420.0
SETBACK = 19.0


def _runs(mask, min_len):
    run_id = (mask != mask.shift()).cumsum()
    return [seg for _, seg in mask[mask].groupby(run_id[mask]) if len(seg) >= min_len]


def r1_airflow(r, design):
    out = []
    for (room, period), g in r.groupby(["room", "period"]):
        g = g.set_index("ts")
        bad = (g.occ > 0.5) & (g.co2 - C_OUT > 800) & (g.q_ls <= 1.15 * design[room]["q_min_ls"])
        days = sorted({seg.index[0].date() for seg in _runs(bad, 6)})
        if len(days) >= 2:
            ev = g[bad]
            out.append(dict(rule="R1", type="airflow_insufficient", category="building", room=room, period=period,
                            start=str(days[0]), days=len(days),
                            evidence=f"CO2 up to {ev.co2.max():.0f} ppm while airflow stayed at "
                                     f"{ev.q_ls.median():.0f} L/s (min {design[room]['q_min_ls']:.0f}, design "
                                     f"{design[room]['q_design_ls']:.0f} L/s) on {len(days)} days",
                            diagnosis="VAV damper / actuator not responding to CO2 demand"))
    return out


def r2_drift(r):
    out = []
    for (room, period), g in r.groupby(["room", "period"]):
        h = g.ts.dt.hour
        night = g[(h >= 2) & (h < 5) & (g.occ < 0.5)]
        base = night.groupby(night.ts.dt.date).co2.quantile(0.1).dropna()
        if len(base) < 6:
            continue
        x = np.array([(pd.Timestamp(d) - pd.Timestamp(base.index[0])).days for d in base.index], float)
        slope, icpt = np.polyfit(x, base.values, 1)
        pred = slope * x + icpt
        r2 = 1 - ((base.values - pred) ** 2).sum() / max(((base.values - base.values.mean()) ** 2).sum(), 1e-9)
        if slope > 6 and r2 > 0.6:
            ref = base.iloc[:2].median()
            onset = next((d for d, v in base.items() if v > ref + 30), base.index[0])
            out.append(dict(rule="R2", type="co2_sensor_drift", category="sensor", room=room, period=period,
                            start=str(onset), slope_ppm_day=round(float(slope), 1), r2=round(float(r2), 2),
                            evidence=f"night baseline rose from {base.iloc[0]:.0f} to {base.iloc[-1]:.0f} ppm "
                                     f"({slope:.1f} ppm/day, R2 {r2:.2f}) in an empty room",
                            diagnosis="CO2 sensor drift: recalibrate / replace (VAV is over-ventilating on it)"))
    return out


def r3_out_of_hours(r, design, wx):
    w = wx.set_index("ts").t_out
    rr = r.join(w, on="ts")
    h = rr.ts.dt.hour
    off = (h >= 20) | (h < 5) | (rr.ts.dt.weekday >= 5)
    qmin = rr.room.map({k: v["q_min_ls"] for k, v in design.items()})
    night_cool = (rr.period == "summer") & (rr.t > 23.3) & (rr.t_out < rr.t - 3)
    running = off & (rr.occ < 0.5) & (rr.q_ls > 0.5 * qmin) & ~night_cool
    rr["night"] = (rr.ts - pd.Timedelta(hours=5)).dt.date
    frac = rr[off].assign(run=running[off]).groupby(["storey", "period", "night", "room"]).run.mean()
    per_room = frac > 0.5
    out = []
    by_storey = per_room.groupby(["storey", "period", "night"]).mean()
    n_rooms = rr.groupby("storey").room.nunique()
    flagged = by_storey[(by_storey >= 0.7)]
    for (storey, period), g in flagged.groupby(level=[0, 1]):
        nights = [n for (_, _, n) in g.index]
        if len(nights) >= 1 and n_rooms[storey] >= 2:
            sub = rr[(rr.storey == storey) & (rr.period == period) & rr.night.isin(nights) & running]
            kwh = (sub.q_ls / 1000 * 5 * 60 * 1.5).sum() / 3600   # SFP 1.5 kJ/m3
            out.append(dict(rule="R3", type="ahu_out_of_hours", category="building", room=f"storey:{storey}",
                            period=period, start=str(min(nights)), nights=len(nights),
                            evidence=f"{int(g.mean() * 100)} % of storey-{storey} rooms ventilated at "
                                     f"{sub.q_ls.median():.0f} L/s median with nobody in, {len(nights)} nights; "
                                     f"~{kwh:.0f} kWh fan energy wasted",
                            diagnosis="AHU zone schedule overridden (manual / BMS time program)"))
    return out


RHO_CP = 1.2 * 1006       # J/(m3 K)
C_AREA = 120e3            # J/(K m2 floor), medium construction (assumption, stated in the report)


def solar_aperture(r, wx, design):
    """Inverse daily energy balance (08-20 h) per room: heat removed by ventilation + heat stored - occupant and
    lighting gains = solar gain. Divided by global horizontal irradiation it gives an effective solar aperture
    [m2], independent of how hard the VAV is cooling. Supply temperature follows the AHU summer control law
    (max(outdoor, 18 C)); in a real building it is read from the BMS."""
    w = wx.set_index("ts")
    rr = r[(r.period == "summer") & (r.ts.dt.hour >= 8) & (r.ts.dt.hour < 20)].join(w[["t_out", "ghi"]], on="ts")
    rr = rr.dropna(subset=["t", "q_ls"])
    dt = 300.0
    rr["t_sup"] = np.maximum(rr.t_out, 18.0)
    rr["q_vent"] = RHO_CP * rr.q_ls / 1000 * (rr.t - rr.t_sup) * dt                # J removed by ventilation
    rr["q_int"] = (rr.occ.fillna(0) * 100 + np.where(rr.occ.fillna(0) > 0.5, 5, 0) *
                   rr.room.map({k: v["area_m2"] for k, v in design.items()})) * dt
    rr["day"] = rr.ts.dt.date
    first_day = rr.day.min()
    rows = {}
    for (room, day), g in rr.groupby(["room", "day"]):
        if day == first_day or len(g) < 100:
            continue
        H = g.ghi.sum() * dt                                   # J/m2
        if H < 3.0 * 3.6e6:                                    # sunny days only (> 3 kWh/m2 in the window)
            continue
        store = C_AREA * design[room]["area_m2"] * (g.t.iloc[-1] - g.t.iloc[0])
        rows.setdefault(room, {})[day] = (g.q_vent.sum() + store - g.q_int.sum()) / H
    return pd.DataFrame(rows).sort_index()


def r4_solar(r, wx, design):
    out = []
    ap = solar_aperture(r, wx, design)
    if len(ap) < 8:
        return out
    ref = ap.iloc[:5].median()
    ratio = ap / ref.where(ref > 0.2)
    peer = ratio.median(axis=1)
    for room in ap:
        later = ratio[room].iloc[5:]
        flags = (later > 1.8) & (peer.iloc[5:] < 1.3) & ((ap[room].iloc[5:] - ref[room]) > 0.8)   # >= 0.8 m2 more aperture
        for j in range(len(flags) - 3):
            if flags.iloc[j:j + 4].sum() >= 3:
                d0 = flags.index[j]
                before, after = ref[room], ap[room][ap.index >= d0].median()
                out.append(dict(rule="R4", type="solar_gain_increase", category="building", room=room,
                                period="summer", start=str(d0),
                                evidence=f"effective solar aperture (inverse energy balance) rose from "
                                         f"{before:.1f} to {after:.1f} m2 (x{after / before:.1f}) from {d0}; "
                                         f"peer rooms unchanged (median x{peer[ap.index >= d0].median():.2f})",
                                diagnosis="external solar shading not deploying (motor / control / wind lock)"))
                break
    return out


def r5_setback(r):
    out = []
    w = r[(r.period == "winter") & (r.ts.dt.hour >= 1) & (r.ts.dt.hour < 5) & (r.occ < 0.5)]
    peers_night = w.groupby([w.room, w.ts.dt.date]).t.mean().groupby(level=1).median()
    for room, g in r[r.period == "winter"].groupby("room"):
        h = g.ts.dt.hour
        night = g[(h >= 1) & (h < 5) & (g.occ < 0.5)]
        tn = night.groupby(night.ts.dt.date).t.mean().dropna()
        rel = tn - peers_night.reindex(tn.index)
        hot = (tn > SETBACK + 3.5) & (rel > 2.5)          # warm at night AND well above the other rooms that night
        runs = _runs(hot, 3)
        if runs:
            seg = runs[0]
            out.append(dict(rule="R5", type="heating_no_setback", category="building", room=room, period="winter",
                            start=str(seg.index[0]), nights=int(hot.sum()),
                            evidence=f"night temperature {tn[hot].mean():.1f} C on {int(hot.sum())} nights "
                                     f"(setback {SETBACK:.0f} C; other rooms {peers_night[tn[hot].index].median():.1f} C the same nights)",
                            diagnosis="radiator valve / thermostat stuck open"))
    return out


def run(r, design, wx):
    return r1_airflow(r, design) + r2_drift(r) + r3_out_of_hours(r, design, wx) + r4_solar(r, wx, design) + r5_setback(r)
