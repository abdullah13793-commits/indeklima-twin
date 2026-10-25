"""Acceptance tests (SPEC.md A1-A9). Fast unit tests plus checks on the recorded pipeline results."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from simulate import mass_balance_step, G_CO2, C_OUT, w_from_rh, rh_from_w  # noqa: E402
from twin import qc, ieq  # noqa: E402

RES = ROOT / "results"


# ---- A1/A2 physics -------------------------------------------------------------------------------
def test_a1_co2_matches_closed_form():
    V, q, N = 150.0, 0.12, 12           # m3, m3/s, persons
    cs = C_OUT + N * G_CO2 * 1e6 / q
    c, t = 420.0, 0.0
    for _ in range(240):
        c = mass_balance_step(c, cs, q, V, 60)
        t += 60
        exact = cs + (420.0 - cs) * np.exp(-q * t / V)
        assert abs(c - exact) < 1.0


def test_a2_steady_state():
    V, q, N = 80.0, 0.05, 6
    cs = C_OUT + N * G_CO2 * 1e6 / q
    c = 420.0
    for _ in range(2000):
        c = mass_balance_step(c, cs, q, V, 60)
    assert abs(c - cs) / (cs - C_OUT) < 0.005
    # cross-check with the textbook value: 6 persons, 50 L/s -> ~ 624 ppm above outdoor
    assert abs((cs - C_OUT) - 6 * 0.0052 / 0.050 * 1e6 / 1000) < 1


def test_psychrometrics_roundtrip():
    for t, rh in [(0, 80), (21, 35), (26, 60)]:
        assert abs(rh_from_w(t, w_from_rh(t, rh)) - rh) < 0.01


# ---- QC ----------------------------------------------------------------------------------------
def test_qc_flags_spike_gap_flatline():
    ts = pd.date_range("2026-02-02", periods=288 * 2, freq="5min")
    df = pd.DataFrame({"ts": ts, "storey": "9", "room": "9.01", "co2": 500 + 50 * np.sin(np.arange(len(ts)) / 20),
                       "t": 21 + 0.3 * np.sin(np.arange(len(ts)) / 30), "rh": 30.0, "q_ls": 50.0, "occ": 0.0})
    df.loc[100, "co2"] = 3000                       # spike
    df.loc[150:200, "t"] = 21.37                    # flatline 4 h
    df = df.drop(index=range(300, 320))             # 100 min gap
    clean, findings, summary = qc.run(df)
    kinds = {f["kind"] for f in findings}
    assert summary["spikes_removed"] >= 1 and "flatline" in kinds and "gap" in kinds


# ---- IEQ categories ------------------------------------------------------------------------------
def test_en16798_categories():
    assert list(ieq.co2_cat(np.array([300, 700, 1000, 2000]))) == [1, 2, 3, 4]
    assert list(ieq.t_cat(np.array([22.0, 23.8, 24.8, 26.5]), "winter")) == [1, 2, 3, 4]


# ---- A3-A6 recorded pipeline results -------------------------------------------------------------
def test_a3_ach_accuracy():
    v = json.load(open(RES / "ach_validation.json"))
    assert v["n_windows"] >= 100 and v["median_abs_err"] <= 0.15


def test_a4_a5_fdd_recall_and_false_alarms():
    ev = json.load(open(RES / "fdd_evaluation.json"))
    b = [f for f in ev["faults"] if f["category"] in ("building", "sensor")]
    assert len(b) == 5 and sum(f["detected"] for f in b) == 5 and ev["n_false_alarms"] == 0


def test_a6_data_faults_are_qc_not_fdd():
    ev = json.load(open(RES / "fdd_evaluation.json"))
    for f in ev["faults"]:
        if f["category"] == "data":
            assert f["detected"] and f["by"].startswith("QC:")


def test_robustness_and_negative_control():
    rob = json.load(open(RES / "robustness.json"))
    assert all(r["false_alarms"] == 0 and r["recall_building"] == "5/5" for r in rob)
    neg = json.load(open(RES / "negative_control_no_faults.json"))
    assert neg["fdd_findings"] == 0 and neg["qc_outages"] == 0 and neg["qc_flatlines"] == 0


# ---- A7 geometry ----------------------------------------------------------------------------------
def test_a7_every_monitored_room_has_a_mesh():
    trimesh = pytest.importorskip("trimesh")
    scene = trimesh.load(ROOT / "web" / "building.glb")
    nodes = {n for n in scene.graph.nodes if str(n).startswith("R_")}
    design = json.load(open(ROOT / "data" / "room_design.json"))
    assert all("R_" + rid.replace(".", "_") in nodes for rid in design)


def test_a8_dashboard_is_static():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert "building.glb" in html and "fetch(" in html and "localhost" not in html
