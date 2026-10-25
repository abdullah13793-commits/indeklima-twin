# Positioning: where Indeklima Twin sits next to existing tools

**Short version:** Indeklima Twin is not a new platform. It is the missing link between two things a building
already has: the design (IFC model + MEP calculations, made before construction) and the sensors (installed after).
It reads both, checks every room against its own design promise, and writes the answer back into the IFC, BCF
and Brick files the existing tools already open.

## What incumbents already do well (and we do not try to replace)
| Tool | Strong at | Source |
|---|---|---|
| **Autodesk Tandem** | Digital-twin platform: maps IoT streams to model elements, threshold alerts, heatmaps, facility monitoring at scale (free tier: 200 streams, 14 days history) | autodesk.com/products/tandem/product-details; aecmag.com/digital-twin/autodesk-tandem-digital-twin-update |
| **Airthings for Business** | Sensor hardware + dashboard; a "Ventilation Rate" virtual sensor estimating air changes per hour from CO2 (since 2024); mould / virus-risk indices | airthings.com/business; hvacinsider.com (Ventilation Rate launch, AHR 2024) |
| **BMS / analytics suites** (Siemens, Schneider, SkySpark, etc.) | Live control, alarms, energy dashboards, large rule libraries | vendor documentation |
| **Solibri / BIMcollab** | Model checking and issue management through BCF | vendor documentation |

We do **not** claim to be first with: room-level CO2 dashboards, an ACH estimate from CO2 (Airthings has one),
IFC-linked sensor views (Tandem has them), or FDD rules in general (BMS analytics suites have large libraries).

## Where Indeklima Twin differs
1. **Judged against the design, not a generic threshold.** Each room's promise (design occupants, design airflow,
   EN 16798-1 category, the CO2 level the design itself predicts) comes from the project's MEP design and IFC.
   "CO2 2,293 ppm vs a promised 1,027 ppm" is a commissioning finding. "CO2 > 1,000" is just an alarm.
2. **Writes back into the formats the project already uses.** Results go into the project's own IFC (standard IFC4
   property sets for design intent, plus one operations set), findings into BCF 2.1 topics with viewpoints, and
   the sensor model into Brick. Nobody has to adopt a new tool to see the result.
3. **Evidence, not only alerts.** Every finding carries the measured evidence and a physical diagnosis, e.g. an
   inverse energy balance showing a room's solar aperture tripled while its peers stayed flat.
4. **Validated in the open.** Planted faults with ground truth: 5/5 building/sensor faults and 2/2 data faults on
   16 seeds, including 5 held-out seeds, plus a fault-free negative control. CO2-decay airflow is checked against
   the true airflow (median error ~9 %). The numbers are in `results/`, and the method can be re-run.
5. **You can ask it.** An MCP server lets any AI assistant answer "which rooms break their promise, and why?"
   from the twin's own evidence, with read-only, sandboxed tools. Few building-analytics tools offer an open MCP
   interface today; the data it serves is the same open IFC / BCF / Brick / Parquet the project already has.
6. **Data faults are not building faults.** A frozen sensor or an offline gateway is reported as QC, so it does
   not send a technician to a healthy VAV.

## Honest gaps (and roadmap)
| Gap | Plan |
|---|---|
| Demonstrated on **simulated** sensor data (physics-based) | Run on a real feed: the ingest takes MQTT/JSONL/CSV unchanged; a pilot building is the next step |
| 5 rule families, not a library of hundreds | Add ASHRAE G36 / Brick-driven rules (economiser, simultaneous heating/cooling) |
| Batch analysis (minutes), not live control | Stream mode (DuckDB incremental), still read-only by design |
| 1R1C thermal model for the synthetic feed | Not used by the detectors, which only see sensor data |
| No hosted service, user management or SLA | Positioned as an engineering deliverable / add-on, complementing Tandem or a BMS |

## One-line pitches
- *Facility manager:* "Your building came with a design that promised each room fresh air and comfort. This
  checks, every week, which rooms keep that promise, and tells you why the others don't."
- *Commissioning engineer:* "Retro-commissioning findings with evidence, exported as BCF into the model you
  already coordinate in."
- *Proptech / IoT team:* "An open analytics layer for your sensor feed: Brick in, IFC and BCF out."
