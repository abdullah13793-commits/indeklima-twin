"""Indeklima Twin MCP server: lets any MCP client (Claude, Copilot, IDE agents) ask the building questions.

Tools answer from the twin's own results (design promise, verdicts, findings with evidence, sensor history).
Everything is read-only, except export_bcf, which writes one BCF file into out/.
The SQL tool runs on an in-memory copy of the data with file access switched off.

Run (stdio):   python src/mcp_server.py
Client config: {"mcpServers": {"indeklima-twin": {"command": "python", "args": ["<repo>/src/mcp_server.py"]}}}
"""
import json
import re
import sys
from pathlib import Path

import duckdb
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
WEB, RES, STORE = ROOT / "web" / "data", ROOT / "results", ROOT / "data" / "store"
READ = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)
NAMES = {"airflow_insufficient": "Airflow not responding to demand", "co2_sensor_drift": "CO2 sensor drifting",
         "ahu_out_of_hours": "AHU zone running out of hours", "solar_gain_increase": "Solar shading not deploying",
         "heating_no_setback": "Heating ignores night setback", "flatline": "Sensor frozen (data)",
         "gateway_outage": "Gateway offline (data)"}

server = MCPServer(
    name="indeklima-twin", title="Indeklima Twin",
    instructions=("Indoor-climate and ventilation twin of Building 308 (37 occupied rooms). Every room has a design "
                  "promise (design occupants, design airflow, EN 16798-1 category, the CO2 level the design predicts). "
                  "Use building_overview first, then list_rooms / room_promise / list_findings. Sensor data in this "
                  "demo are SIMULATED with planted faults; say so when you report results."),
    version="1.0.0")


def _load():
    return (json.load(open(WEB / "rooms.json")), json.load(open(WEB / "findings.json")),
            json.load(open(WEB / "summary.json")))


_db = None


def _con():
    """In-memory DuckDB with the sensor tables copied in, then external access disabled (read-only sandbox)."""
    global _db
    if _db is None:
        _db = duckdb.connect()
        _db.execute(f"CREATE TABLE sensors AS SELECT ts, period, storey, room, co2, t, rh, q_ls, occ "
                    f"FROM read_parquet('{(STORE / 'rooms_5min_clean.parquet').as_posix()}')")
        _db.execute(f"CREATE TABLE weather AS SELECT * FROM read_parquet('{(STORE / 'weather_5min.parquet').as_posix()}')")
        _db.execute("SET enable_external_access = false")
        _db.execute("SET lock_configuration = true")
    return _db


def _room_row(rid, w):
    v = w["promise"]["verdict"]
    return {"room": rid, "kind": w["kind"], "storey": w["storey"], "area_m2": w["area_m2"],
            "design_persons": w["persons"], "design_airflow_ls": w["q_design_ls"],
            "promised_co2_ppm": w["promise"]["co2_design_ppm"],
            "measured_co2_p95_ppm": {p: k["co2_p95"] for p, k in w["kpi"].items()},
            "co2_promise_kept": {p: v[p]["co2_kept"] for p in v}, "temperature_promise_kept": {p: v[p]["t_kept"] for p in v},
            "open_findings": w["findings"]}


@server.tool(annotations=READ)
def building_overview() -> dict:
    """Headline numbers: rooms, how many keep their design promise, findings, data quality and validation."""
    rooms, findings, s = _load()
    return {"building": "Building 308 (renovation design model)", "data": "SIMULATED sensor feed with planted faults",
            "rooms_monitored": s["rooms_monitored"], "promise": s["promise"],
            "findings": [{"rule": f.get("rule"), "title": NAMES.get(f["type"], f["type"]), "room": f["room"],
                          "period": f["period"], "category": f["category"]} for f in findings],
            "data_completeness": s["completeness"], "false_alarms_in_validation": s["false_alarms"],
            "airflow_from_co2_decay_median_error": s["ach"]["median_abs_err"]}


@server.tool(annotations=READ)
def list_rooms(storey: str | None = None, kind: str | None = None, broken_only: bool = False) -> list[dict]:
    """Rooms with their design promise and verdict. Filter by storey ('0'-'3'), kind (office, meeting,
    multipurpose, atrium, auditorium) or broken_only=True for rooms that break a promise in any season."""
    rooms, _, _ = _load()
    out = []
    for rid, w in rooms.items():
        if storey is not None and w["storey"] != str(storey):
            continue
        if kind and w["kind"] != kind:
            continue
        broken = any(not (v["co2_kept"] and v["t_kept"]) for v in w["promise"]["verdict"].values())
        if broken_only and not broken:
            continue
        out.append(_room_row(rid, w))
    return out


@server.tool(annotations=READ)
def room_promise(room_id: str) -> dict:
    """Everything about one room: design intent, measured performance per season, verdict, and the findings that
    explain any broken promise (with evidence and diagnosis)."""
    rooms, findings, _ = _load()
    if room_id not in rooms:
        return {"error": f"unknown room {room_id}", "rooms": sorted(rooms)}
    w = rooms[room_id]
    rel = [f for f in findings if f["room"] in (room_id, f"storey:{w['storey']}")]
    return {**_room_row(room_id, w), "kpi": w["kpi"], "ventilation_from_co2_decay": w.get("ventilation", {}),
            "explanations": [{"title": NAMES.get(f["type"], f["type"]), "evidence": f["evidence"],
                              "diagnosis": f["diagnosis"], "period": f["period"], "since": str(f["start"])} for f in rel]}


@server.tool(annotations=READ)
def list_findings(period: str | None = None, category: str | None = None) -> list[dict]:
    """Diagnosed findings with evidence. period: 'winter' | 'summer'; category: 'building' | 'sensor' | 'data'."""
    _, findings, _ = _load()
    return [{"rule": f.get("rule"), "title": NAMES.get(f["type"], f["type"]), "room": f["room"], "period": f["period"],
             "category": f["category"], "since": str(f["start"]), "evidence": f["evidence"], "diagnosis": f["diagnosis"]}
            for f in findings if (period is None or f["period"] == period) and (category is None or f["category"] == category)]


@server.tool(annotations=READ)
def room_timeseries(room_id: str, period: str = "winter", day: str | None = None, resolution_min: int = 60) -> dict:
    """Sensor history for one room: CO2 (ppm), temperature (C), RH (%), airflow (L/s), occupants.
    period 'winter' (Feb) or 'summer' (Jun); day 'YYYY-MM-DD' to zoom on one day; resolution 15-240 min."""
    res = max(15, min(240, int(resolution_min)))
    where = "room = ? AND period = ?" + (" AND CAST(ts AS DATE) = CAST(? AS DATE)" if day else "")
    args = [room_id, period] + ([day] if day else [])
    rows = _con().execute(f"""SELECT time_bucket(INTERVAL '{res} minutes', ts) AS t, round(avg(co2)) co2, round(avg(t), 1) temp,
        round(avg(rh), 1) rh, round(avg(q_ls), 1) airflow_ls, round(avg(occ), 1) occupants
        FROM sensors WHERE {where} GROUP BY 1 ORDER BY 1 LIMIT 400""", args).fetchall()
    return {"room": room_id, "period": period, "resolution_min": res,
            "columns": ["time", "co2_ppm", "temp_c", "rh_pct", "airflow_ls", "occupants"],
            "rows": [[str(r[0])] + list(r[1:]) for r in rows]}


@server.tool(annotations=READ)
def query(sql: str) -> dict:
    """Read-only SQL (DuckDB) over tables sensors(ts, period, storey, room, co2, t, rh, q_ls, occ) and
    weather(ts, t_out, rh_out, ghi). One SELECT/WITH statement; max 500 rows."""
    s = sql.strip().rstrip(";")
    if not re.match(r"(?is)^\s*(select|with)\b", s) or ";" in s:
        return {"error": "only a single SELECT / WITH statement is allowed"}
    try:
        cur = _con().execute(f"SELECT * FROM ({s}) LIMIT 500")
        cols = [d[0] for d in cur.description]
        return {"columns": cols, "rows": [[str(v) if not isinstance(v, (int, float, type(None))) else v for v in r]
                                         for r in cur.fetchall()]}
    except Exception as e:  # noqa: BLE001 - report the DuckDB message to the client
        return {"error": str(e)}


@server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def export_bcf() -> dict:
    """Write the current findings as a BCF 2.1 file (out/IndeklimaTwin_findings.bcfzip) for Solibri, BIMcollab,
    Revit, Archicad or Dalux. Returns the path and the topic titles."""
    from twin import writeback
    rooms, web, findings = writeback.load()
    n = writeback.write_bcf(rooms, web, findings)
    return {"path": str(ROOT / "out" / "IndeklimaTwin_findings.bcfzip"), "topics": n,
            "titles": [f"{NAMES.get(f['type'], f['type'])} - {f['room']}" for f in findings]}


if __name__ == "__main__":
    server.run("stdio")
