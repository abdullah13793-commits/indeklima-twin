"""Extract rooms (IfcSpace) and building context geometry from the Building 308 IFC.

Outputs
  data/rooms.json        room registry: id, name, type, storey, floor area, volume, centroid, bbox
  web/building.glb       glTF scene: one node per room (name = room id) + context layers per IFC class
"""
import json
import multiprocessing
import sys
from pathlib import Path

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element as ue
import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parents[1]
IFC = Path(json.load(open(Path(__file__).resolve().parents[1] / "config" / "local_paths.json"))["source_ifc"])   # local path to the source IFC (config/local_paths.json)
CONTEXT = ["IfcWall", "IfcSlab", "IfcCurtainWall", "IfcWindow", "IfcDoor", "IfcStair", "IfcRoof", "IfcColumn",
           "IfcBeam", "IfcPlate", "IfcMember", "IfcRailing", "IfcCovering"]
SKIP_TYPES = {"SHAFT"}


def shapes(model, types):
    s = ifcopenshell.geom.settings()
    s.set("use-world-coords", True)
    s.set("weld-vertices", True)
    elems = [e for t in types for e in model.by_type(t)]
    it = ifcopenshell.geom.iterator(s, model, multiprocessing.cpu_count(), include=elems)
    if it.initialize():
        while True:
            sh = it.get()
            v = np.array(sh.geometry.verts).reshape(-1, 3)
            f = np.array(sh.geometry.faces).reshape(-1, 3)
            if len(f):
                yield model.by_id(sh.id), v, f
            if not it.next():
                break


def main():
    model = ifcopenshell.open(str(IFC))
    unit = ifcopenshell.util.unit.calculate_unit_scale(model)
    rooms, room_meshes = [], {}
    counter = {}
    for el, v, f in shapes(model, ["IfcSpace"]):
        typ = (el.LongName or el.Name or "SPACE").strip().upper()
        if typ in SKIP_TYPES:
            continue
        storey = getattr(ue.get_container(el) or ue.get_aggregate(el), "Name", "?")
        mesh = trimesh.Trimesh(v, f, process=True)
        if mesh.volume <= 0:
            mesh.invert()
        vol = float(abs(mesh.volume))
        z0 = mesh.bounds[0][2]
        # floor area = projected area of the faces whose normal points down at the bottom of the space
        down = (mesh.face_normals[:, 2] < -0.9) & (mesh.triangles_center[:, 2] < z0 + 0.05)
        area = float(mesh.area_faces[down].sum())
        if vol < 3 or area < 1.5:
            continue
        rooms.append(dict(ifc_guid=el.GlobalId, ifc_name=el.Name, type=typ, storey=storey,
                          area_m2=round(area, 2), volume_m3=round(vol, 1),
                          height_m=round(float(mesh.bounds[1][2] - z0), 2),
                          centroid=[round(float(c), 2) for c in mesh.centroid],
                          bbox=[[round(float(c), 2) for c in b] for b in mesh.bounds]))
        room_meshes[el.GlobalId] = mesh
    # deterministic room numbers (the geometry iterator is multi-threaded, so its order is not stable):
    # per storey, north to south, then west to east, like a floor-plan reading order
    rooms.sort(key=lambda r: (r["storey"], -round(r["centroid"][1], 1), round(r["centroid"][0], 1), r["ifc_guid"]))
    counter = {}
    for r in rooms:
        counter[r["storey"]] = counter.get(r["storey"], 0) + 1
        r["id"] = f"{r['storey']}.{counter[r['storey']]:02d}"
    room_meshes = {r["id"]: room_meshes[r["ifc_guid"]] for r in rooms}
    rooms = [{"id": r.pop("id"), **r} for r in rooms]
    print(f"rooms: {len(rooms)} (unit scale {unit})")

    scene = trimesh.Scene()
    for rid, m in room_meshes.items():
        name = "R_" + rid.replace(".", "_")          # glTF loaders sanitise ":" and "."
        scene.add_geometry(m, node_name=name, geom_name=name)
    lo = np.min([m.bounds[0] for m in room_meshes.values()], axis=0) - 6
    hi = np.max([m.bounds[1] for m in room_meshes.values()], axis=0) + 6
    for cls in CONTEXT:
        parts = [trimesh.Trimesh(v, f, process=False) for _, v, f in shapes(model, [cls])]
        parts = [p for p in parts if np.all(p.centroid[:2] > lo[:2]) and np.all(p.centroid[:2] < hi[:2])]
        if not parts:
            continue
        merged = trimesh.util.concatenate(parts)
        merged.merge_vertices()
        scene.add_geometry(merged, node_name=f"C_{cls}", geom_name=f"C_{cls}")
        print(f"  {cls}: {len(parts)} elements, {len(merged.faces)} faces")
    (ROOT / "data").mkdir(exist_ok=True)
    json.dump(rooms, open(ROOT / "data" / "rooms.json", "w"), indent=1)
    scene.export(ROOT / "web" / "building.glb")
    print("glb MB", round((ROOT / "web" / "building.glb").stat().st_size / 1e6, 1))


if __name__ == "__main__":
    import ifcopenshell.util.unit  # noqa: E402
    main()
