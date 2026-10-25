"""Independent reference: CO2-decay ACH (from noisy 5-min sensor data) vs the simulator's true outdoor-air
change rate over the same window (from the 1-min true state, never seen by the pipeline)."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def ach_error(write=True):
    dec = pd.read_csv(ROOT / "results" / "co2_decay_windows.csv", parse_dates=["start", "end"], dtype={"room": str})
    truth = pd.read_parquet(ROOT / "data" / "truth_state.parquet", columns=["ts", "room", "q"])
    vol = {k: v["volume_m3"] for k, v in json.load(open(ROOT / "data" / "room_design.json")).items()}
    truth = truth.set_index(["room", "ts"]).sort_index()
    errs = []
    for _, w in dec.iterrows():
        q = truth.loc[(w.room, slice(w.start, w.end)), "q"]
        ach_true = q.mean() / 1000 * 3600 / vol[w.room]
        errs.append(dict(room=w.room, start=str(w.start), ach_co2=w.ach_co2, ach_true=round(float(ach_true), 3),
                         ach_vav=w.ach_vav, rel_err=round(float((w.ach_co2 - ach_true) / ach_true), 4)))
    e = pd.DataFrame(errs)
    out = dict(n_windows=len(e), median_abs_err=round(float(e.rel_err.abs().median()), 4),
               p90_abs_err=round(float(e.rel_err.abs().quantile(0.9)), 4), bias=round(float(e.rel_err.median()), 4),
               vav_vs_true_median_abs_err=round(float(((e.ach_vav - e.ach_true) / e.ach_true).abs().median()), 4))
    if write:
        e.to_csv(ROOT / "results" / "ach_validation_windows.csv", index=False)
        json.dump(out, open(ROOT / "results" / "ach_validation.json", "w"), indent=1)
    return out


if __name__ == "__main__":
    print(ach_error())
