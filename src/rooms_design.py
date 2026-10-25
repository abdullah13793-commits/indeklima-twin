"""Room design intent: occupants, design airflow (EN 16798-1 cat. II, method as in the project's MEP design),
facade exposure and thermal parameters, derived from data/rooms.json.

Design airflow q = 0.7 L/s/m2 (low-polluting building) + 7 L/s/person (cat. II), the values used in the
project's MEP calculations (ventilation sheet, DS/EN 16798-1 tables B.7/B.8).
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MONITORED = {"CELLULAR OFFICE (6P)": "office", "MEETINGROOM (15P)": "meeting",
             "MULTI PURPOSE SPACE": "multipurpose", "ATRIUM": "atrium", "BELOW AUDITORIUM": "auditorium"}
Q_AREA, Q_PERS = 0.7, 7.0          # L/s/m2, L/s/person
U_WALL, U_WIN, WIN_SHARE = 0.20, 0.90, 0.40   # project envelope (roof 0.10-0.15, walls ~0.2)
SHGC = 0.35                         # glazing with external shading in use; failed shading -> 0.6 (fault)


def persons(kind, area):
    return {"office": max(6, round(area / 10)), "meeting": 15, "multipurpose": max(10, round(area / 4)),
            "atrium": round(area / 15), "auditorium": max(20, round(area / 2))}[kind]


def load():
    rooms = json.load(open(ROOT / "data" / "rooms.json"))
    xs = [r["bbox"][0][0] for r in rooms] + [r["bbox"][1][0] for r in rooms]
    ys = [r["bbox"][0][1] for r in rooms] + [r["bbox"][1][1] for r in rooms]
    X0, X1, Y0, Y1 = min(xs), max(xs), min(ys), max(ys)
    out = []
    for r in rooms:
        kind = MONITORED.get(r["type"])
        (x0, y0, z0), (x1, y1, z1) = r["bbox"]
        h = r["height_m"]
        # exterior facades: room bbox edge within 1.5 m of the building outline (axis-aligned plan)
        fac = {}
        if y1 > Y1 - 1.5: fac["N"] = (x1 - x0) * h
        if y0 < Y0 + 1.5: fac["S"] = (x1 - x0) * h
        if x1 > X1 - 1.5: fac["E"] = (y1 - y0) * h
        if x0 < X0 + 1.5: fac["W"] = (y1 - y0) * h
        if r["storey"] == "0":
            fac = {}                        # basement: below ground
        d = dict(r, kind=kind, monitored=kind is not None, facades={k: round(v, 1) for k, v in fac.items()})
        if kind:
            n = persons(kind, r["area_m2"])
            d.update(persons=n, q_design_ls=round(Q_AREA * r["area_m2"] + Q_PERS * n, 1),
                     q_min_ls=round(Q_AREA * r["area_m2"], 1))
        out.append(d)
    return out


if __name__ == "__main__":
    R = load()
    mon = [r for r in R if r["monitored"]]
    print(len(mon), "monitored rooms;", sum(r["q_design_ls"] for r in mon), "L/s design total")
    for r in mon[:8]:
        print(r["id"], r["kind"], r["area_m2"], r["persons"], r["q_design_ls"], r["facades"])
