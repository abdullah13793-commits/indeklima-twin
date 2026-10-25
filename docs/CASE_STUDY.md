# Case study: Indeklima Twin on Building 308

## The problem nobody owns
Every ventilated building is designed room by room. The MEP engineer decides how many people each room is for, how
much outdoor air it gets, and which indoor-climate category it must meet. Then the building is handed over, and that
reasoning is gone. Sensors are installed later and compared with generic thresholds ("CO2 above 1,000 ppm"), so a
meeting room designed for 15 people and a corridor are judged by the same line. When something breaks, nobody asks
the right question: *is this room still doing what it was designed to do?*

## The idea
Use what the building already has. The renovation design model of Building 308 contains every room as an IfcSpace;
the MEP design gives each room its design airflow (EN 16798-1 cat. II: 0.7 L/s per m² + 7 L/s per person). From those
two, every room gets a **design promise**: occupants, airflow, category, and the CO2 level the design itself
predicts at full occupancy (N·G/q above outdoor). The sensors are then judged against that promise, room by room.

## What it does
1. **Ingest.** MQTT-style messages (CO2, temperature, RH, VAV airflow, occupancy, weather) into Parquet with DuckDB.
   About 900,000 messages for four weeks are processed in under ten seconds.
2. **Quality control.** Range checks, a Hampel spike filter, gaps, flatlines, storey-wide outages. Data problems are
   labelled as data problems.
3. **Comfort.** EN 16798-1 categories over occupied hours, and the Danish summer criterion (≤ 100 h/yr > 26 °C).
4. **Ventilation.** Outdoor-air change rate inferred from CO2 decay whenever a room empties, then compared with the
   VAV airflow sensor.
5. **Diagnosis.** Five rule families, each with the evidence a commissioning engineer would want to see.
6. **Write-back.** The verdict goes into the project's own IFC (standard IFC4 property sets for the design intent, an
   operations set for the results), into BCF 2.1 topics, and into a Brick model of the sensor points.

## What it found (simulated feed with planted faults)
- One meeting room promised ~1,030 ppm and measured ~2,400 ppm. Diagnosis: the VAV airflow stayed at its minimum while
  CO2 climbed, i.e. a damper/actuator not responding.
- One office's CO2 sensor drifted: its empty-room night baseline rose day by day while the other offices on the
  storey stayed at outdoor level. The room *appeared* to break its CO2 promise; the twin shows it is the sensor, not
  the room (the VAV was even over-ventilating on the false reading).
- Storey 3's AHU zone ran all night with nobody in (summer night cooling is recognised and excluded); the fan
  energy wasted is estimated.
- One room's external shading stopped deploying. An inverse daily energy balance showed its effective solar aperture
  roughly tripled from one day to the next, while 36 other rooms stayed flat.
- One office's radiator valve stuck open: it stayed ~8 K warmer than every other room at night.
- A frozen temperature sensor and a six-hour gateway outage were reported as data issues, not as building faults.
- In summer, about half the rooms exceed the overheating criterion. These are mostly small, dense west and south
  rooms, a design-stage risk the IDA ICE simulations also showed. It is reported as a comfort finding, not a fault.

## How we know it works
The feed is simulated with a physics model, so the truth is known and the detectors never see it.
- 16 runs with different occupancy, noise, device offsets and message loss: all 7 planted faults found, 0 false
  alarms, every time. 5 of those seeds were held out and never used while the rules were designed.
- A fault-free building: 0 findings, 0 QC alarms.
- CO2-decay airflow vs the true airflow: median error about 10 % over ~400 decay windows, with a stated bias of
  about −7 %.
- The CO2 balance is integrated exactly and tested against the closed-form solution.

Two detector weaknesses surfaced during validation and were fixed for physical reasons, not by tuning thresholds:
1. **Shading rule.** A peak-temperature rule missed the shading fault because the VAV hid it by cooling harder. It
   was replaced with the inverse energy balance.
2. **Setback rule.** A rule comparing night temperature with the setpoint raised false alarms on heavy rooms that
   stay warm overnight. It now compares each room with the other rooms on the same night.

## What it is not
Not measured data yet, not a control system, not a platform. It is an analytics layer that sits between a project's
design files and its sensor feed, and it answers in the project's own formats.
