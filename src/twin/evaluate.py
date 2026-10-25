"""Score the pipeline findings against the planted-fault ground truth (never read by the pipeline itself)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MATCH = {"vav_stuck_min": "airflow_insufficient", "co2_sensor_drift": "co2_sensor_drift",
         "ahu_out_of_hours": "ahu_out_of_hours", "solar_shading_failed": "solar_gain_increase",
         "heating_valve_stuck_open": "heating_no_setback", "temp_sensor_flatline": "flatline",
         "gateway_outage": "gateway_outage"}
PERIOD_START = {"winter": "2026-02-02", "summer": "2026-06-15"}


def evaluate(fdd, qc):
    truth = json.load(open(ROOT / "data" / "truth_faults.json"))
    findings = [dict(f, src="FDD") for f in fdd] + [dict(type=q["kind"], src="QC", **{k: v for k, v in q.items() if k != "kind"})
                                                     for q in qc if q["kind"] in ("flatline", "gateway_outage")]
    used, rows = set(), []
    for t in truth:
        hit = None
        for i, f in enumerate(findings):
            if f["type"] == MATCH[t["type"]] and f["room"] == t["room"] and f["period"] == t["period"]:
                hit = i
                break
        if hit is not None:
            used.add(hit)
            import pandas as pd
            onset = pd.Timestamp(PERIOD_START[t["period"]]) + pd.Timedelta(days=t["start_day"])
            delay = (pd.Timestamp(findings[hit]["start"]) - onset).total_seconds() / 86400
        rows.append(dict(fault=t["id"], type=t["type"], category=t["category"], room=t["room"], period=t["period"],
                         detected=hit is not None, by=findings[hit]["src"] + ":" + findings[hit].get("rule", findings[hit]["type"]) if hit is not None else None,
                         detection_delay_days=round(delay, 2) if hit is not None else None))
    false_alarms = [f for i, f in enumerate(findings) if i not in used]
    building = [r for r in rows if r["category"] in ("building", "sensor")]
    data = [r for r in rows if r["category"] == "data"]
    return dict(faults=rows, false_alarms=false_alarms,
                recall_building=f"{sum(r['detected'] for r in building)}/{len(building)}",
                recall_data=f"{sum(r['detected'] for r in data)}/{len(data)}",
                n_false_alarms=len(false_alarms))
