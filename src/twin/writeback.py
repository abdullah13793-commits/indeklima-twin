"""Write the twin's results back into the open formats the project already uses: no new file format.

1. IFC: the project's own model, with every monitored IfcSpace enriched
   - design intent in the standard IFC4 property sets (Pset_SpaceOccupancyRequirements, Pset_SpaceThermalRequirements,
     Pset_SpaceThermalDesign), so any IFC tool shows it without configuration
   - operation results in IndeklimaTwin_Operation (custom set, no reserved "Pset_" prefix)
2. BCF 2.1: one topic per finding, with the room(s) selected and a camera on them (Solibri, BIMcollab, Revit,
   Archicad, Dalux read it)
3. Brick schema (Turtle): rooms, VAVs, AHU zones and sensor points, each point linked to its MQTT topic and each
   room to its IFC GlobalId, the semantic model BMS / IoT platforms import
"""
import datetime
import json
import sys
import uuid
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import ifcopenshell
import ifcopenshell.api

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "out"
SRC_IFC = Path(json.load(open(Path(__file__).resolve().parents[2] / "config" / "local_paths.json"))["source_ifc"])
TITLES = {"airflow_insufficient": "Airflow not responding to demand", "co2_sensor_drift": "CO2 sensor drifting",
          "ahu_out_of_hours": "AHU zone running out of hours", "solar_gain_increase": "Solar shading not deploying",
          "heating_no_setback": "Heating ignores night setback", "flatline": "Sensor frozen (data)",
          "gateway_outage": "Gateway offline (data)"}


def load():
    rooms = {r["id"]: r for r in json.load(open(ROOT / "data" / "rooms.json"))}
    web = json.load(open(ROOT / "web" / "data" / "rooms.json"))
    findings = json.load(open(ROOT / "web" / "data" / "findings.json"))
    return rooms, web, findings


# ------------------------------------------------------------------ IFC
def write_ifc(rooms, web, findings, path=None):
    path = path or OUT / "Building308_IndeklimaTwin.ifc"
    m = ifcopenshell.open(str(SRC_IFC))
    now = datetime.date.today().isoformat()
    # neutral header: the source file's header carries the authoring machine's local path and names
    fn = m.header.file_name
    fn.name = path.name if hasattr(path, "name") else "Building308_IndeklimaTwin.ifc"
    fn.time_stamp = datetime.datetime.now().replace(microsecond=0).isoformat()
    fn.author, fn.organization = ("",), ("",)
    fn.preprocessor_version = "IfcOpenShell"
    fn.originating_system = "Indeklima Twin (write-back of design intent and operation results)"
    fn.authorization = ""
    n = 0
    for rid, w in web.items():
        sp = m.by_guid(rooms[rid]["ifc_guid"])
        rf = [f for f in findings if f["room"] in (rid, f"storey:{w['storey']}") and f["category"] != "data"]
        api = lambda name, props: ifcopenshell.api.run("pset.edit_pset", m,
                                                       pset=ifcopenshell.api.run("pset.add_pset", m, product=sp, name=name),
                                                       properties=dict(props))
        api("Pset_SpaceOccupancyRequirements", {"OccupancyType": w["kind"], "OccupancyNumber": int(w["persons"]),
                                                "AreaPerOccupant": round(w["area_m2"] / w["persons"], 2)})
        api("Pset_SpaceThermalRequirements", {"SpaceTemperatureWinterMin": 20.0, "SpaceTemperatureWinterMax": 24.0,
                                              "SpaceTemperatureSummerMin": 23.0, "SpaceTemperatureSummerMax": 26.0,
                                              "MechanicalVentilationRate": round(w["q_design_ls"] / 1000 * 3600 / w["volume_m3"], 2)})
        api("Pset_SpaceThermalDesign", {"VentilationAirFlowrate": round(w["q_design_ls"] / 1000, 4)})
        props = {"Standard": "EN 16798-1 cat. II", "DesignCO2_ppm": int(w["promise"]["co2_design_ppm"]),
                 "EvaluatedOn": now, "OpenFindings": "; ".join(f"{f['rule']} {TITLES.get(f['type'], f['type'])}" for f in rf) or "none"}
        for p, k in w["kpi"].items():
            v = w["promise"]["verdict"][p]
            props.update({f"{p.title()}CO2P95_ppm": int(k["co2_p95"]), f"{p.title()}TempWithinCatII": float(k["t_within_II"]),
                          f"{p.title()}HoursAbove26": float(k["hours_above_26"]),
                          f"{p.title()}PromiseKept": bool(v["co2_kept"] and v["t_kept"])})
        api("IndeklimaTwin_Operation", props)
        n += 1
    OUT.mkdir(exist_ok=True)
    m.write(str(path))
    return n


# ------------------------------------------------------------------ BCF (same writer pattern as Ildfast)
def _vp(camera, target, guids):
    cx, cy, cz = camera
    dx, dy, dz = (target[0] - cx, target[1] - cy, target[2] - cz)
    nrm = (dx * dx + dy * dy + dz * dz) ** 0.5 or 1
    comps = "".join(f'<Component IfcGuid="{g}"/>' for g in guids)
    return (f'<?xml version="1.0" encoding="UTF-8"?><VisualizationInfo Guid="{uuid.uuid4()}"><Components>'
            f'<Selection>{comps}</Selection><Visibility DefaultVisibility="true"/></Components>'
            f'<PerspectiveCamera><CameraViewPoint><X>{cx:.3f}</X><Y>{cy:.3f}</Y><Z>{cz:.3f}</Z></CameraViewPoint>'
            f'<CameraDirection><X>{dx / nrm:.4f}</X><Y>{dy / nrm:.4f}</Y><Z>{dz / nrm:.4f}</Z></CameraDirection>'
            f'<CameraUpVector><X>0</X><Y>0</Y><Z>1</Z></CameraUpVector><FieldOfView>60</FieldOfView></PerspectiveCamera>'
            f'</VisualizationInfo>')


def write_bcf(rooms, web, findings, path=None):
    path = path or OUT / "IndeklimaTwin_findings.bcfzip"
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
    OUT.mkdir(exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("bcf.version", '<?xml version="1.0" encoding="UTF-8"?><Version VersionId="2.1"><DetailedVersion>2.1</DetailedVersion></Version>')
        z.writestr("project.bcfp", f'<?xml version="1.0" encoding="UTF-8"?><ProjectExtension><Project ProjectId="{uuid.uuid4()}">'
                                   f'<Name>Building 308 - Indeklima Twin</Name></Project><ExtensionSchema></ExtensionSchema></ProjectExtension>')
        for f in findings:
            ids = [r for r, w in web.items() if f["room"] in (r, f"storey:{w['storey']}")]
            guids = [rooms[r]["ifc_guid"] for r in ids]
            cs = [rooms[r]["centroid"] for r in ids]
            target = [sum(c[i] for c in cs) / len(cs) for i in range(3)]
            cam = (target[0] - 14, target[1] - 18, target[2] + 12)
            tid = str(uuid.uuid4())
            ttype = "Issue" if f["category"] != "data" else "Request"
            prio = {"building": "Major", "sensor": "Normal", "data": "Minor"}[f["category"]]
            desc = (f"{f['evidence']}\n\nDiagnosis: {f['diagnosis']}\nPeriod: {f['period']}, from {f['start']}\n"
                    f"Detected by: Indeklima Twin {f['rule']} (simulated sensor data, Building 308 demo)")
            markup = (f'<?xml version="1.0" encoding="UTF-8"?><Markup><Topic Guid="{tid}" TopicType="{ttype}" TopicStatus="Open">'
                      f'<Title>{escape(TITLES.get(f["type"], f["type"]) + " - " + f["room"].replace("storey:", "storey "))}</Title>'
                      f'<Priority>{prio}</Priority><Labels>IEQ</Labels><Labels>{escape(f["category"])}</Labels>'
                      f'<CreationDate>{now}</CreationDate><CreationAuthor>Indeklima Twin</CreationAuthor>'
                      f'<Description>{escape(desc)}</Description></Topic>'
                      f'<Viewpoints Guid="{uuid.uuid4()}"><Viewpoint>viewpoint.bcfv</Viewpoint></Viewpoints></Markup>')
            z.writestr(f"{tid}/markup.bcf", markup)
            z.writestr(f"{tid}/viewpoint.bcfv", _vp(cam, target, guids))
    return len(findings)


# ------------------------------------------------------------------ Brick
def write_brick(rooms, web, path=None):
    path = path or OUT / "Building308_brick.ttl"
    L = ["@prefix brick: <https://brickschema.org/schema/Brick#> .", "@prefix ref: <https://brickschema.org/schema/Brick/ref#> .",
         "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .", "@prefix unit: <http://qudt.org/vocab/unit/> .",
         "@prefix b308: <urn:site:b308#> .", "",
         'b308:building a brick:Building ; rdfs:label "Building 308" .',
         'b308:weather_station a brick:Weather_Station ; brick:hasLocation b308:building ;',
         '    brick:hasPoint b308:t_out , b308:ghi .',
         'b308:t_out a brick:Outside_Air_Temperature_Sensor ; brick:hasUnit unit:DEG_C ;',
         '    ref:hasExternalReference [ a ref:TimeseriesReference ; ref:hasTimeseriesId "site/b308/roof/weather#t_out" ] .',
         'b308:ghi a brick:Solar_Irradiance_Sensor ; brick:hasUnit unit:W-PER-M2 ;',
         '    ref:hasExternalReference [ a ref:TimeseriesReference ; ref:hasTimeseriesId "site/b308/roof/weather#ghi" ] .']
    storeys = sorted({w["storey"] for w in web.values()})
    for s in storeys:
        L += [f'b308:floor_{s} a brick:Floor ; rdfs:label "Storey {s}" ; brick:isPartOf b308:building .',
              f'b308:ahu_{s} a brick:AHU ; rdfs:label "AHU zone storey {s}" .']
    pts = [("co2", "CO2_Sensor", "PPM", "env#co2"), ("t", "Air_Temperature_Sensor", "DEG_C", "env#t"),
           ("rh", "Relative_Humidity_Sensor", "PERCENT_RH", "env#rh"), ("occ", "Occupancy_Count_Sensor", None, "occ#count")]
    for rid, w in web.items():
        k = "r_" + rid.replace(".", "_")
        top = f"site/b308/{w['storey']}/{rid}"
        L += [f'b308:{k} a brick:Room ; rdfs:label "Room {rid} ({w["kind"]})" ; brick:isPartOf b308:floor_{w["storey"]} ;',
              f'    brick:area [ brick:value "{w["area_m2"]}"^^<http://www.w3.org/2001/XMLSchema#decimal> ; brick:hasUnit unit:M2 ] ;',
              f'    ref:hasExternalReference [ a ref:IFCReference ; ref:hasIfcProjectReference [ ref:hasIfcProjectID "Building308_renovation" ] ;',
              f'        ref:ifcGlobalID "{rooms[rid]["ifc_guid"]}" ; ref:ifcName "{rooms[rid]["ifc_name"]}" ] ;',
              f'    brick:hasPoint ' + " , ".join(f"b308:{k}_{p[0]}" for p in pts) + " ."]
        for p, cls, unit, tail in pts:
            u = f" brick:hasUnit unit:{unit} ;" if unit else ""
            L.append(f'b308:{k}_{p} a brick:{cls} ;{u} ref:hasExternalReference [ a ref:TimeseriesReference ; '
                     f'ref:hasTimeseriesId "{top}/{tail}" ] .')
        L += [f'b308:{k}_vav a brick:VAV ; brick:feeds b308:{k} ; brick:isFedBy b308:ahu_{w["storey"]} ;',
              f'    brick:hasPoint b308:{k}_q .',
              f'b308:{k}_q a brick:Supply_Air_Flow_Sensor ; brick:hasUnit unit:L-PER-SEC ; ref:hasExternalReference '
              f'[ a ref:TimeseriesReference ; ref:hasTimeseriesId "{top}/vav#q_ls" ] .',
              f'b308:{k}_q_sp a brick:Supply_Air_Flow_Setpoint ; brick:hasUnit unit:L-PER-SEC ; brick:isPointOf b308:{k}_vav ;'
              f' rdfs:comment "design {w["q_design_ls"]} L/s, minimum {w["q_min_ls"]} L/s (EN 16798-1 cat. II)" .']
    OUT.mkdir(exist_ok=True)
    path.write_text("\n".join(L) + "\n", encoding="utf-8")
    import rdflib
    g = rdflib.Graph().parse(path, format="turtle")
    return len(g)


def main():
    rooms, web, findings = load()
    n_ifc = write_ifc(rooms, web, findings)
    n_bcf = write_bcf(rooms, web, findings)
    n_ttl = write_brick(rooms, web)
    res = dict(ifc_spaces_enriched=n_ifc, bcf_topics=n_bcf, brick_triples=n_ttl)
    json.dump(res, open(ROOT / "results" / "writeback.json", "w"), indent=1)
    print(res)


if __name__ == "__main__":
    main()
