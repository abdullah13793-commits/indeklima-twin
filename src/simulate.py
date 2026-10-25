"""Physics-based sensor-feed simulator for the monitored rooms of Building 308 (SIMULATED DATA).

Per room, 60 s step, two 14-day periods (winter, summer) from the Copenhagen TMYx weather file:
  CO2      V dC/dt = Q (Cout - C) + N G
  moisture V rho dw/dt = rho Q (w_out - w) + N m_v
  heat     C_th dT/dt = UA (Tout - T) + UA_int (T_adj - T) + rho cp Q (T_sup - T) + gains + solar + radiator
VAV is CO2-controlled on the *measured* CO2 (so a drifting sensor changes the airflow, as in a real building).
Writes raw sensor messages as JSONL (one file per day, MQTT-style payloads), the true state (parquet) and the
planted-fault ground truth (json). Seeded and deterministic.
"""
import json
import math
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from rooms_design import load as load_rooms, SHGC, U_WALL, U_WIN, WIN_SHARE

ROOT = Path(__file__).resolve().parents[1]
EPW = next((ROOT / "data" / "weather").glob("*.epw"))
RHO, CP = 1.2, 1006.0
G_CO2 = 0.0052e-3          # m3/s CO2 per seated adult (~1.2 met), i.e. 0.0052 L/s
M_VAP = 50 / 3600 / 1000   # kg/s water vapour per person
C_OUT = 420.0              # ppm outdoor
DT = 60                    # s
PERIODS = {"winter": (datetime(2026, 2, 2), 14), "summer": (datetime(2026, 6, 15), 14)}   # both start on a Monday
SAMPLE = 5                 # minutes between sensor messages


# ------------------------------------------------------------------ weather
def read_epw():
    cols = ["y", "m", "d", "h", "mi", "src", "tdb", "tdp", "rh", "p", "eth", "etn", "hir", "ghi", "dni", "dhi"]
    w = pd.read_csv(EPW, skiprows=8, header=None, usecols=range(16), names=cols)
    w["doy"] = pd.to_datetime(dict(year=2026, month=w.m, day=w.d)).dt.dayofyear
    w["hour"] = w.h - 1
    return w


def solar_vertical(doy, hour_dec, dni, dhi, ghi, lat=55.6, lon=12.65):
    """Irradiance on vertical facades N/E/S/W (W/m2). Simple solar geometry, isotropic sky, 0.2 albedo."""
    decl = math.radians(23.45) * np.sin(2 * np.pi * (284 + doy) / 365)
    solar_time = hour_dec + (lon - 15) / 15.0           # CET
    ha = np.radians(15 * (solar_time - 12))
    la = math.radians(lat)
    sin_alt = np.sin(la) * np.sin(decl) + np.cos(la) * np.cos(decl) * np.cos(ha)
    alt = np.arcsin(np.clip(sin_alt, -1, 1))
    az = np.arctan2(np.sin(ha), np.cos(ha) * np.sin(la) - np.tan(decl) * np.cos(la))   # 0 = south, + = west
    out = {}
    for k, faz in {"S": 0.0, "W": np.pi / 2, "N": np.pi, "E": -np.pi / 2}.items():
        cos_inc = np.cos(alt) * np.cos(az - faz)
        beam = np.where(alt > 0, dni * np.clip(cos_inc, 0, None), 0)
        out[k] = beam + 0.5 * dhi + 0.5 * 0.2 * ghi
    return out


def sat_vp(t):
    return 610.94 * np.exp(17.625 * t / (t + 243.04))


def w_from_rh(t, rh, p=101325):
    pv = rh / 100 * sat_vp(t)
    return 0.622 * pv / (p - pv)


def rh_from_w(t, w, p=101325):
    pv = w * p / (0.622 + w)
    return np.clip(100 * pv / sat_vp(t), 0, 100)


def mass_balance_step(x, x_ss, q, V, dt):
    """Exact solution of V dx/dt = q (x_ss - x) over one step with constant inputs (no Euler error)."""
    return x_ss + (x - x_ss) * np.exp(-q * dt / V)


# ------------------------------------------------------------------ occupancy
def occupancy(rooms, start, days, rng):
    n_steps = days * 1440
    occ = np.zeros((n_steps, len(rooms)))
    for j, r in enumerate(rooms):
        P = r["persons"]
        for d in range(days):
            day = start + timedelta(days=d)
            if day.weekday() >= 5:
                continue
            base = d * 1440
            k = r["kind"]
            if k == "office":
                att = rng.uniform(0.45, 0.9)
                for p in range(P):
                    if rng.random() > att:
                        continue
                    a = int(rng.normal(8.4, 0.5) * 60); b = int(rng.normal(16.3, 0.6) * 60)
                    occ[base + a: base + b, j] += 1
                    l0 = int(rng.normal(11.8, 0.25) * 60)
                    if rng.random() < 0.7:
                        occ[base + l0: base + l0 + 35, j] -= 1
            elif k == "meeting":
                for _ in range(rng.integers(2, 6)):
                    h0 = int(rng.integers(8, 16)) * 60 + int(rng.choice([0, 30]))
                    occ[base + h0: base + h0 + int(rng.choice([45, 60, 90])), j] += rng.integers(4, P + 1)
            elif k in ("multipurpose", "auditorium"):
                for _ in range(rng.integers(1, 4)):
                    h0 = int(rng.integers(8, 15)) * 60
                    occ[base + h0: base + h0 + 105, j] += round(P * rng.uniform(0.35, 0.9))
            elif k == "atrium":
                occ[base + 480: base + 1020, j] += np.round(P * rng.uniform(0.1, 0.35, 540))
    cap = np.array([r["persons"] for r in rooms])
    return np.clip(occ, 0, cap)


# ------------------------------------------------------------------ faults (ground truth)
def plan_faults(rooms):
    import os
    if os.environ.get("TWIN_NO_FAULTS"):
        return []
    by = lambda pred: next(r["id"] for r in rooms if pred(r))
    sunny = sorted([r for r in rooms if "S" in r["facades"] or "W" in r["facades"]], key=lambda r: -sum(r["facades"].values()))
    f = [
        dict(id="F1", type="vav_stuck_min", room=by(lambda r: r["kind"] == "meeting" and r["storey"] == "2"),
             period="winter", start_day=3, end_day=14, category="building",
             note="VAV damper stuck at minimum airflow"),
        dict(id="F2", type="co2_sensor_drift", room=by(lambda r: r["kind"] == "office" and r["storey"] == "2"),
             period="winter", start_day=2, end_day=14, rate_ppm_per_day=18, category="sensor",
             note="CO2 sensor drifts upward ~18 ppm/day; VAV over-ventilates on the false reading"),
        dict(id="F3", type="ahu_out_of_hours", room="storey:3", period="winter", start_day=7, end_day=14,
             category="building", note="AHU zone for storey 3 left in manual: runs 24/7 at design airflow"),
        dict(id="F4", type="solar_shading_failed", room=sunny[0]["id"], period="summer", start_day=7, end_day=14,
             category="building", note="external solar shading stuck retracted from day 7 (g 0.20 -> 0.60)"),
        dict(id="F5", type="temp_sensor_flatline", room=by(lambda r: r["kind"] == "office" and r["storey"] == "3"),
             period="summer", start_day=4, end_day=7, category="data",
             note="temperature sensor frozen at its last value"),
        dict(id="F6", type="gateway_outage", room="storey:2", period="summer", start_day=9, end_day=9,
             hours=(9, 15), category="data", note="LoRa/IoT gateway for storey 2 offline for 6 h"),
        dict(id="F7", type="heating_valve_stuck_open",
             room=next(r["id"] for r in sunny[1:] if r["kind"] == "office" and r["id"] != by(lambda r: r["kind"] == "meeting" and r["storey"] == "2")),
             period="winter", start_day=5, end_day=14, category="building",
             note="radiator thermostatic valve stuck fully open"),
    ]
    return f


def active(f, period, day, room, storey):
    if f["period"] != period or not (f["start_day"] <= day < max(f["end_day"], f["start_day"] + 1)):
        return False
    return f["room"] == room or f["room"] == f"storey:{storey}"


# ------------------------------------------------------------------ simulation
def simulate(seed=308, out=None):
    rng = np.random.default_rng(seed)
    rooms = [r for r in load_rooms() if r["monitored"]]
    faults = plan_faults(rooms)
    w = read_epw()
    n = len(rooms)
    A = np.array([r["area_m2"] for r in rooms]); V = np.array([r["volume_m3"] for r in rooms])
    qd = np.array([r["q_design_ls"] for r in rooms]) / 1000; qmin = np.array([r["q_min_ls"] for r in rooms]) / 1000
    fac = {k: np.array([r["facades"].get(k, 0.0) for r in rooms]) for k in "NESW"}
    UA = sum(fac.values()) * ((1 - WIN_SHARE) * U_WALL + WIN_SHARE * U_WIN) + 0.15 * A   # + roof/slab/thermal bridges
    UA_int = 1.5 * A
    Cth = 120e3 * A
    glass = {k: fac[k] * WIN_SHARE * 0.8 for k in "NESW"}
    dev_gain = rng.normal(1, 0.02, n); dev_t = rng.normal(0, 0.2, n); dev_rh = rng.normal(0, 2, n)

    truth_frames, messages = [], []
    for period, (start, days) in PERIODS.items():
        occ = occupancy(rooms, start, days, rng)
        steps = days * 1440
        t_idx = [start + timedelta(minutes=i) for i in range(steps)]
        doy0 = start.timetuple().tm_yday
        wday = w[(w.doy >= doy0) & (w.doy < doy0 + days + 1)].reset_index(drop=True)
        hrs = np.arange(steps) / 60.0
        interp = lambda col: np.interp(hrs, np.arange(len(wday)), wday[col].values)
        tout, rhout = interp("tdb"), interp("rh")
        sol = solar_vertical(doy0 + hrs // 24, hrs % 24, interp("dni"), interp("dhi"), interp("ghi"))
        wout = w_from_rh(tout, rhout)
        winter = period == "winter"
        C = np.full(n, C_OUT + 30.0); T = np.full(n, 21.0 if winter else 23.0); W = np.full(n, wout[0])
        C_meas_prev = C.copy()
        state = {k: np.zeros((steps, n)) for k in ("co2", "t", "rh", "q", "occ", "heat")}
        for i in range(steps):
            ts = t_idx[i]; d = i // 1440; mod = i % 1440
            weekday = ts.weekday() < 5
            ahu_on = weekday and 6 * 60 <= mod < 18 * 60
            if mod == 0:   # fault masks change at most once a day
                M = {t: np.array([any(f["type"] == t and active(f, period, d, r["id"], r["storey"]) for f in faults)
                                  for r in rooms]) for t in ("ahu_out_of_hours", "vav_stuck_min", "solar_shading_failed",
                                                              "heating_valve_stuck_open", "co2_sensor_drift")}
                drift_rate = np.array([sum(f.get("rate_ppm_per_day", 0) for f in faults if f["type"] == "co2_sensor_drift"
                                           and active(f, period, d, r["id"], r["storey"])) for r in rooms])
                drift_start = next((f["start_day"] for f in faults if f["type"] == "co2_sensor_drift"), 0)
            ahu24, stuck_min, shade_fail, valve_open = (M["ahu_out_of_hours"], M["vav_stuck_min"],
                                                        M["solar_shading_failed"], M["heating_valve_stuck_open"])
            # summer night cooling: AHU runs 22-06 at design airflow when the room is warm and outdoors is cool
            night_cool = (not winter) and (mod >= 22 * 60 or mod < 6 * 60) and tout[i] < 18
            on = ahu_on | ahu24 | (night_cool & (T > 23.5))
            # VAV on measured CO2 (includes sensor faults) and on room temperature (cooling with outdoor air)
            demand = np.clip((C_meas_prev - 600) / 300, 0, 1)
            demand = np.maximum(demand, np.clip((T - (24.0 if not winter else 24.5)) / 1.5, 0, 1))
            if night_cool:
                demand = np.where(T > 23.5, 1.0, demand)
            q = np.where(on, qmin + (qd - qmin) * demand, 0.1 * V / 3600)
            q = np.where(stuck_min & on, qmin, q)
            if not ahu_on:
                q = np.where(ahu24, qd, q)
            N = occ[i]
            # CO2 and moisture
            C = mass_balance_step(C, C_OUT + N * G_CO2 * 1e6 / q, q, V, DT)
            W = mass_balance_step(W, wout[i] + N * M_VAP / RHO / q, q, V, DT)
            # heat
            tsup = np.clip(tout[i] + 0.8 * (T - tout[i]), 19, 21) if winter else np.maximum(tout[i], 18.0)
            shgc = np.where(shade_fail, 0.60, 0.20 if not winter else 0.5)   # external blinds deployed in summer (Fc ~0.3)
            solar = sum(glass[k] * sol[k][i] for k in "NESW") * shgc
            lights = np.where(N > 0, 5 * A, 0)
            gains = N * (70 + 30) + lights + solar
            setp = 21.0 if (weekday and 6 * 60 <= mod < 18 * 60) else 19.0
            heat = np.clip(600 * (setp - T), 0, 50 * A) if winter else np.zeros(n)
            heat = np.where(valve_open, 25 * A, heat)   # valve stuck at ~50 % opening
            T_adj = 21.5 if winter else 23.8 + 0.2 * (tout[i] - 18)   # corridors / stairs (unconditioned)
            T = T + DT * (UA * (tout[i] - T) + UA_int * (T_adj - T) + RHO * CP * q * (tsup - T) + gains + heat) / Cth
            rh = rh_from_w(T, W)
            # measured CO2 used by the controller next step (drift fault)
            drift = drift_rate * (i / 1440 - drift_start)
            C_meas_prev = C * dev_gain + drift
            for k, v in (("co2", C), ("t", T), ("rh", rh), ("q", q * 1000), ("occ", N), ("heat", heat)):
                state[k][i] = v
        # -------- truth table at 1-min
        tf = pd.DataFrame({"ts": np.repeat(pd.to_datetime(t_idx), n), "room": np.tile([r["id"] for r in rooms], steps),
                           **{k: state[k].ravel() for k in state}})
        tf["period"] = period; tf["tout"] = np.repeat(tout, n)
        truth_frames.append(tf)
        # -------- sensor messages every SAMPLE min
        frozen = {}
        ghi = interp("ghi")
        for i in range(0, steps, SAMPLE):
            ts = t_idx[i]; d = i // 1440; hour = (i % 1440) / 60
            messages.append({"ts": ts.isoformat(), "topic": "site/b308/roof/weather",
                             "t_out": round(float(tout[i] + rng.normal(0, 0.1)), 2),
                             "rh_out": round(float(rhout[i]), 1), "ghi": round(float(ghi[i]))})
            for j, r in enumerate(rooms):
                if rng.random() < 0.002:
                    continue                                 # random message loss
                outage = any(f["type"] == "gateway_outage" and active(f, period, d, r["id"], r["storey"])
                             and f["hours"][0] <= hour < f["hours"][1] for f in faults)
                if outage:
                    continue
                drift = sum(f["rate_ppm_per_day"] * (i / 1440 - f["start_day"]) for f in faults
                            if f["type"] == "co2_sensor_drift" and active(f, period, d, r["id"], r["storey"]))
                co2 = state["co2"][i, j] * dev_gain[j] + drift + rng.normal(0, 15)
                if rng.random() < 0.0008:
                    co2 += rng.choice([-1, 1]) * rng.uniform(800, 2000)        # spike glitch
                t_val = state["t"][i, j] + dev_t[j] + rng.normal(0, 0.08)
                flat = any(f["type"] == "temp_sensor_flatline" and active(f, period, d, r["id"], r["storey"]) for f in faults)
                if flat:
                    t_val = frozen.setdefault(r["id"], round(t_val, 2))
                messages.append({"ts": ts.isoformat(), "topic": f"site/b308/{r['storey']}/{r['id']}/env",
                                 "co2": round(float(co2)), "t": round(float(t_val), 2),
                                 "rh": round(float(state["rh"][i, j] + dev_rh[j] + rng.normal(0, 1)), 1)})
                messages.append({"ts": ts.isoformat(), "topic": f"site/b308/{r['storey']}/{r['id']}/vav",
                                 "q_ls": round(float(state["q"][i, j] * rng.normal(1, 0.03)), 1)})
                messages.append({"ts": ts.isoformat(), "topic": f"site/b308/{r['storey']}/{r['id']}/occ",
                                 "count": int(max(0, state["occ"][i, j] + (rng.random() < 0.03) * rng.choice([-1, 1])))})
    raw = ROOT / "data" / "raw"; raw.mkdir(parents=True, exist_ok=True)
    for p in raw.glob("*.jsonl"):
        p.unlink()
    df = pd.DataFrame(messages)
    for day, g in df.groupby(df.ts.str[:10]):
        with open(raw / f"{day}.jsonl", "w") as fh:
            for rec in g.to_dict("records"):
                fh.write(json.dumps({k: v for k, v in rec.items() if v == v}) + "\n")
    truth = pd.concat(truth_frames)
    truth.to_parquet(ROOT / "data" / "truth_state.parquet", index=False)
    json.dump(faults, open(ROOT / "data" / "truth_faults.json", "w"), indent=1)
    meta = {r["id"]: {k: r[k] for k in ("kind", "storey", "area_m2", "volume_m3", "persons", "q_design_ls", "q_min_ls", "facades", "type")}
            for r in rooms}
    json.dump(meta, open(ROOT / "data" / "room_design.json", "w"), indent=1)
    print(f"{len(rooms)} rooms, {len(messages):,} messages, {truth.shape[0]:,} truth rows")


if __name__ == "__main__":
    import sys
    simulate(seed=int(sys.argv[1]) if len(sys.argv) > 1 else 308)
