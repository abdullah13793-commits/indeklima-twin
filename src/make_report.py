"""Building performance report (PDF): design promise vs operation, findings with evidence, validation, limits."""
import json
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, KeepTogether

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "renders"
S = json.load(open(ROOT / "web" / "data" / "summary.json"))
W = json.load(open(ROOT / "web" / "data" / "rooms.json"))
F = json.load(open(ROOT / "web" / "data" / "findings.json"))
WB = json.load(open(ROOT / "results" / "writeback.json"))
ROB = S["robustness"]
NEG = json.load(open(ROOT / "results" / "negative_control_no_faults.json"))

ss = getSampleStyleSheet()
INK, INK2, ACC = colors.HexColor("#0b0b0b"), colors.HexColor("#52514e"), colors.HexColor("#2a78d6")
H1 = ParagraphStyle("h1", parent=ss["Heading1"], fontSize=19, leading=23, textColor=INK, spaceAfter=4)
H2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=12.5, textColor=ACC, spaceBefore=10, spaceAfter=4)
B = ParagraphStyle("b", parent=ss["BodyText"], fontSize=9.2, leading=12.6, textColor=INK)
SM = ParagraphStyle("sm", parent=B, fontSize=8, leading=10.4)
MU = ParagraphStyle("mu", parent=SM, textColor=INK2)
TAG = ParagraphStyle("tag", parent=SM, textColor=colors.HexColor("#a35f00"), fontName="Helvetica-Bold")
NAMES = {"airflow_insufficient": "Airflow not responding to demand", "co2_sensor_drift": "CO2 sensor drifting",
         "ahu_out_of_hours": "AHU zone running out of hours", "solar_gain_increase": "Solar shading not deploying",
         "heating_no_setback": "Heating ignores night setback", "flatline": "Sensor frozen", "gateway_outage": "Gateway offline"}


def tbl(rows, widths, head=True, size=7.8):
    st = ParagraphStyle("t", parent=SM, fontSize=size, leading=size + 2.2)
    t = Table([[Paragraph(str(c), st) for c in r] for r in rows], colWidths=widths, repeatRows=1 if head else 0, hAlign="LEFT")
    style = [("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e1e0d9")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]
    if head:
        style.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef3fb")))
    t.setStyle(TableStyle(style))
    return t


def img(p, w):
    from PIL import Image as PI
    iw, ih = PI.open(p).size
    return Image(str(p), width=w, height=w * ih / iw)


held = [x for x in ROB if x.get("held_out")]
dev = [x for x in ROB if not x.get("held_out")]
ok = lambda xs: sum(x["recall_building"] == "5/5" and x["recall_data"] == "2/2" and x["false_alarms"] == 0 for x in xs)
kept_both = sum(all(v["co2_kept"] and v["t_kept"] for v in w["promise"]["verdict"].values()) for w in W.values())
story = [
    Paragraph("SIMULATED SENSOR DATA · physics-based feed with planted faults · Building 308 renovation design model", TAG),
    Paragraph("Indeklima Twin: does every room keep its design promise?", H1),
    Paragraph("Abdallah Alhussein · MSc Architectural Engineering · indoor climate, building physics, data pipelines", MU),
    Spacer(1, 4), img(FIG / "hero.png", 182 * mm),
    Paragraph("The renovation design already states what each room should do: how many people, how much outdoor air, which "
              "EN 16798-1 category. Indeklima Twin reads that promise from the project's IFC model and MEP design, runs the "
              "sensor feed through quality control, comfort analysis, CO<sub>2</sub>-decay airflow inference and fault diagnosis, "
              "and writes the verdict back into the IFC, BCF and Brick files the project already works with.", B),
    tbl([["Rooms twinned", "Keep the CO2 promise (winter)", "Keep both promises (both seasons)", "Faults diagnosed", "False alarms", "Airflow error"],
         [S["rooms_monitored"], f"{S['promise']['winter']['co2_kept']}/{S['promise']['winter']['rooms']}", f"{kept_both}/{S['rooms_monitored']}",
          f"{S['building_faults']} + 2 data", S["false_alarms"], f"{S['ach']['median_abs_err'] * 100:.1f} %"]],
        [30 * mm] * 6, size=8.4),
    PageBreak(),
    Paragraph("1. How it works", H2), img(FIG / "fig_pipeline.png", 182 * mm),
    Paragraph(f"<b>Design.</b> {S['rooms_monitored']} occupied rooms (offices, meeting rooms, multipurpose rooms, atrium, "
              "auditorium) are taken from the project's IFC4 model (IfcSpace geometry, areas, volumes). Design airflow follows the "
              "project's MEP method: 0.7 L/s·m² + 7 L/s per person (EN 16798-1 cat. II). The promised CO<sub>2</sub> level is the "
              "steady state at design occupancy, C = C<sub>out</sub> + N·G/q. "
              f"<b>Sensors.</b> {S['messages']:,} MQTT-style messages (CO<sub>2</sub>, temperature, RH, VAV airflow, occupancy, "
              "weather) for two winter and two summer weeks. <b>QC.</b> Range checks, a Hampel spike filter, gap and "
              f"flatline detection ({S['spikes_removed']} spikes removed, completeness {S['completeness'] * 100:.1f} %). "
              "<b>Analytics.</b> EN 16798-1 categories over occupied hours; outdoor-air change rate from CO<sub>2</sub> decay when "
              "a room empties. <b>Diagnosis.</b> Five rule families with evidence. <b>Write-back.</b> "
              f"{WB['ifc_spaces_enriched']} IfcSpaces enriched (standard IFC4 property sets for the design intent plus an operations "
              f"set), {WB['bcf_topics']} BCF 2.1 topics, a Brick model of {WB['brick_triples']} triples.", B),
    Paragraph("2. Promise vs operation", H2), img(FIG / "fig_promise.png", 150 * mm),
    Paragraph("Every room is judged against what its own design promised, not a generic threshold. Two rooms break the "
              "winter CO<sub>2</sub> promise, and the diagnosis separates them: room " + next(f["room"] for f in F if f["type"] == "airflow_insufficient")
              + " really is under-ventilated (VAV not responding), while room " + next(f["room"] for f in F if f["type"] == "co2_sensor_drift")
              + " only <i>appears</i> to be: its CO<sub>2</sub> sensor is drifting. The temperature promise is stricter: in summer "
              "many small west and south rooms exceed the Danish practice of at most 100 h/year above 26 °C, the same design-stage "
              "risk the IDA ICE study flagged.", B),
    img(FIG / "fig_comfort.png", 140 * mm),
    PageBreak(),
    Paragraph("3. Findings, each with its evidence", H2), img(FIG / "fig_evidence.png", 182 * mm),
    tbl([["#", "Finding", "Room", "Evidence", "Diagnosis"]] +
        [[f.get("rule", "QC"), NAMES.get(f["type"], f["type"]), f["room"].replace("storey:", "storey "), f["evidence"], f["diagnosis"]] for f in F],
        [10 * mm, 34 * mm, 16 * mm, 74 * mm, 48 * mm], size=7.2),
    Paragraph("Data problems (a frozen sensor, an offline gateway) are reported by QC and are never presented as building "
              "faults, so nobody is sent to inspect a healthy VAV.", MU),
    PageBreak(),
    Paragraph("4. Validation", H2),
    Paragraph(f"The sensor feed is simulated, so the truth is known. The detectors never see it. <b>Faults:</b> five building / "
              f"sensor faults and two data faults are planted per run. On {len(dev)} development runs, {ok(dev)}/{len(dev)} found all "
              f"seven with no false alarm. On {len(held)} <b>held-out</b> seeds, never used while designing the rules, "
              f"{ok(held)}/{len(held)} did. A fault-free building raised {NEG['fdd_findings']} findings and "
              f"{NEG['qc_outages'] + NEG['qc_flatlines']} QC alarms. <b>Airflow:</b> CO<sub>2</sub>-decay estimates vs the "
              f"true outdoor-air rate: median error {S['ach']['median_abs_err'] * 100:.1f} %, P90 {S['ach']['p90_abs_err'] * 100:.0f} %, "
              f"bias {S['ach']['bias'] * 100:+.1f} % (the CO<sub>2</sub> sensor's lag and gain error, both stated). "
              "<b>Physics:</b> the CO<sub>2</sub> balance is integrated exactly and tested against the closed-form solution "
              "(< 1 ppm) and the steady state (< 0.5 %).", B),
    img(FIG / "fig_ach.png", 105 * mm),
    tbl([["Seed", "Held out", "Building / sensor faults", "Data faults", "False alarms", "Airflow error"]] +
        [[x["seed"], "yes" if x.get("held_out") else "", x["recall_building"], x["recall_data"], x["false_alarms"],
          f"{x['ach_median_abs_err'] * 100:.1f} %"] for x in ROB], [18 * mm, 18 * mm, 38 * mm, 26 * mm, 24 * mm, 26 * mm], size=7.4),
    Paragraph("5. Limits", H2),
    Paragraph("Simulated, not measured data: the pipeline accepts a real MQTT / CSV feed unchanged, and a pilot building is the "
              "next step. The synthetic feed uses a single-zone (1R1C) thermal model per room; the detectors do not depend on it. "
              "Detector thresholds were developed on this building and are stated in the code. Five rule families, not a full "
              "rule library. Read-only: it diagnoses and does not control equipment.", B),
]
doc = SimpleDocTemplate(str(ROOT / "reports" / "Indeklima_Twin_Building308_report.pdf"), pagesize=A4, leftMargin=14 * mm,
                        rightMargin=14 * mm, topMargin=12 * mm, bottomMargin=12 * mm, title="Indeklima Twin - Building 308",
                        author="Abdallah Alhussein")
doc.build(story)
print("report ok")
