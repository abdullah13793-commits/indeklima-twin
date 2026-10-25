"""Publish pack images: 1600x1200 cover from the hero render, and a write-back card built from what the enriched
IFC and the BCF file actually contain (read back, not typed)."""
import json
import zipfile
import re
from pathlib import Path

import ifcopenshell
import ifcopenshell.util.element as ue
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
PUB = ROOT / "publish"; PUB.mkdir(exist_ok=True)
S = json.load(open(ROOT / "web" / "data" / "summary.json"))
F = json.load(open(ROOT / "web" / "data" / "findings.json"))
ROB = S["robustness"]


def font(size, bold=False):
    for name in (["segoeuib.ttf", "arialbd.ttf"] if bold else ["segoeui.ttf", "arial.ttf"]):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def cover():
    im = Image.open(ROOT / "renders" / "hero.png").convert("RGB").resize((1600, 1200))
    # darken the top band for the title
    grad = Image.new("L", (1600, 1200), 0)
    gd = ImageDraw.Draw(grad)
    for y in range(420):
        gd.line([(0, y), (1600, y)], fill=int(215 * (1 - y / 420) ** 1.4))
    im = Image.composite(Image.new("RGB", im.size, (6, 8, 14)), im, grad)
    d = ImageDraw.Draw(im)
    d.text((70, 62), "INDEKLIMA TWIN", font=font(30, True), fill=(110, 167, 236))
    d.text((70, 106), "Does every room keep its design promise?", font=font(58, True), fill=(240, 239, 236))
    d.text((70, 186), "IFC + MEP design intent  ×  sensor feed  →  diagnosis back into IFC · BCF · Brick", font=font(27), fill=(195, 194, 183))
    held = [x for x in ROB if x.get("held_out")]
    chips = [f"{S['promise']['winter']['co2_kept']}/{S['promise']['winter']['rooms']} rooms keep the CO₂ promise",
             f"{S['building_faults']} faults diagnosed · {S['false_alarms']} false alarms",
             f"{len(ROB)} validation runs · {len(held)} held-out",
             f"airflow from CO₂ decay ±{S['ach']['median_abs_err'] * 100:.0f} %"]
    x, y = 70, 1092
    for c in chips:
        w = d.textlength(c, font=font(23)) + 34
        d.rounded_rectangle([x, y, x + w, y + 48], radius=24, fill=(22, 26, 34), outline=(70, 78, 92))
        d.text((x + 17, y + 10), c, font=font(23), fill=(240, 239, 236))
        x += w + 14
    d.text((1530, 1050), "simulated sensor data", font=font(18), fill=(250, 178, 25), anchor="ra")
    d.rounded_rectangle([1180, 286, 1540, 330], radius=8, fill=(22, 26, 34))
    d.rectangle([1192, 300, 1208, 316], outline=(208, 59, 59), width=3)
    d.text((1220, 296), "breaks its promise: fault diagnosed", font=font(19), fill=(240, 239, 236))
    im.save(PUB / "01_cover.png", optimize=True)
    im.convert("RGB").save(PUB / "01_cover.jpg", quality=92)


def writeback_card():
    m = ifcopenshell.open(str(ROOT / "out" / "Building308_IndeklimaTwin.ifc"))
    rooms = {r["id"]: r for r in json.load(open(ROOT / "data" / "rooms.json"))}
    r1 = next(f["room"] for f in F if f["type"] == "airflow_insufficient")
    sp = m.by_guid(rooms[r1]["ifc_guid"])
    ps = ue.get_psets(sp)
    W, H = 1600, 1200
    im = Image.new("RGB", (W, H), (13, 13, 13)); d = ImageDraw.Draw(im)
    d.text((70, 60), "WRITE-BACK", font=font(28, True), fill=(110, 167, 236))
    d.text((70, 100), "The verdict lands in the files the project already opens", font=font(48, True), fill=(240, 239, 236))
    d.text((70, 168), f"Read back from Building308_IndeklimaTwin.ifc · IfcSpace {sp.GlobalId} (room {r1})", font=font(22), fill=(195, 194, 183))
    y = 230
    for name in ("Pset_SpaceOccupancyRequirements", "Pset_SpaceThermalDesign", "Pset_SpaceThermalRequirements", "IndeklimaTwin_Operation"):
        props = {k: v for k, v in ps.get(name, {}).items() if k != "id"}
        if name == "Pset_SpaceThermalRequirements":
            props = {k: props[k] for k in ("SpaceTemperatureWinterMin", "SpaceTemperatureSummerMax", "MechanicalVentilationRate") if k in props}
        if name == "IndeklimaTwin_Operation":
            props = {k: props[k] for k in ("Standard", "DesignCO2_ppm", "WinterCO2P95_ppm", "WinterPromiseKept", "OpenFindings") if k in props}
        std = name.startswith("Pset_")
        d.text((70, y), name, font=font(25, True), fill=(110, 167, 236) if std else (250, 178, 25))
        d.text((70 + d.textlength(name, font=font(25, True)) + 14, y + 4), "IFC4 standard" if std else "operation results", font=font(19), fill=(137, 135, 129))
        y += 40
        for k, v in props.items():
            v = str(v)
            if len(v) > 60:
                v = v[:57] + "..."
            col = (208, 59, 59) if (k.endswith("PromiseKept") and v == "False") else (240, 239, 236)
            d.text((100, y), k, font=font(21), fill=(195, 194, 183)); d.text((560, y), v, font=font(21), fill=col)
            y += 31
        y += 14
    # BCF topics
    x0 = 1030
    d.text((x0, 230), "IndeklimaTwin_findings.bcfzip", font=font(25, True), fill=(110, 167, 236))
    d.text((x0, 266), "BCF 2.1 topics, room selected, camera set", font=font(19), fill=(137, 135, 129))
    z = zipfile.ZipFile(ROOT / "out" / "IndeklimaTwin_findings.bcfzip")
    titles = []
    for n in z.namelist():
        if n.endswith("markup.bcf"):
            x = z.read(n).decode("utf8")
            titles.append((re.search(r"<Title>(.*?)</Title>", x).group(1), re.search(r"<Priority>(.*?)</Priority>", x).group(1)))
    yy = 310
    for t, p in sorted(titles, key=lambda t: {"Major": 0, "Normal": 1, "Minor": 2}[t[1]]):
        col = {"Major": (208, 59, 59), "Normal": (236, 131, 90), "Minor": (250, 178, 25)}[p]
        d.rounded_rectangle([x0, yy, 1540, yy + 70], radius=10, fill=(26, 26, 25), outline=(44, 44, 42))
        d.ellipse([x0 + 16, yy + 25, x0 + 36, yy + 45], fill=col)
        d.text((x0 + 50, yy + 10), t.replace("&amp;", "&")[:46], font=font(21), fill=(240, 239, 236))
        d.text((x0 + 50, yy + 38), f"priority {p}", font=font(17), fill=(137, 135, 129))
        yy += 82
    wb = json.load(open(ROOT / "results" / "writeback.json"))
    d.text((70, 1110), f"{wb['ifc_spaces_enriched']} IfcSpaces enriched · {wb['bcf_topics']} BCF topics · Brick model "
                       f"with {wb['brick_triples']:,} triples (parsed with rdflib)", font=font(23), fill=(195, 194, 183))
    im.save(PUB / "05_writeback.png", optimize=True)


if __name__ == "__main__":
    cover(); writeback_card(); print("publish images ok")
