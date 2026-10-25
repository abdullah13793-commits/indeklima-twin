"""Blender (Cycles) signature render: exploded storeys of Building 308 at night, every monitored room glowing
with its measured CO2 (or temperature) at one moment (default: the winter morning the stuck-damper room
peaks); rooms with a diagnosed building fault get a status-red frame. Run:
  blender -b -P src/render_hero.py -- [period] [index] [metric] [out.png] [samples]
"""
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
PERIOD = argv[0] if len(argv) > 0 else "winter"
IDX = int(argv[1]) if len(argv) > 1 else -1          # -1: the moment the stuck-damper room peaks
METRIC = argv[2] if len(argv) > 2 else "co2"
OUT = argv[3] if len(argv) > 3 else str(ROOT / "renders" / "hero.png")
SAMPLES = int(argv[4]) if len(argv) > 4 else 96
EXPLODE = 11.0

series = json.load(open(ROOT / "web" / "data" / f"series_{PERIOD}.json"))
rooms = json.load(open(ROOT / "web" / "data" / "rooms.json"))
findings = json.load(open(ROOT / "web" / "data" / "findings.json"))
FAULTY = {f["room"] for f in findings if f["period"] == PERIOD and f["category"] == "building" and not f["room"].startswith("storey")}
if IDX < 0:
    r1 = next(f["room"] for f in findings if f["type"] == "airflow_insufficient")
    s = series["rooms"][r1]["co2"]
    IDX = max((i for i in range(len(s)) if s[i] is not None and 36 <= i % 96 <= 64), key=lambda i: s[i])
print("frame index", IDX, "faulty", FAULTY)


def hexrgb(h):
    h = h.lstrip("#")
    srgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb]   # to linear


def lerp(a, b, t):
    return [x * (1 - t) + y * t for x, y in zip(a, b)]


COLD, MID, WARM = hexrgb("#3987e5"), hexrgb("#3a3a38"), hexrgb("#e66767")
SEQ = [hexrgb(h) for h in ("#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4", "#cde2fb")]


def colour(rid):
    s = series["rooms"].get(rid)
    if not s:
        return None
    if METRIC == "t":
        v = s["t"][IDX]
        if v is None:
            return None
        mid = 24.5 if PERIOD == "summer" else 22.0
        t = max(-1, min(1, (v / 10 - mid) / 2.5))
        return lerp(MID, WARM, t) if t >= 0 else lerp(MID, COLD, -t)
    v = s["co2"][IDX]
    if v is None:
        return None
    t = max(0, min(1, (v - 420) / 1100)) * 5
    i = min(4, int(t))
    return lerp(SEQ[i], SEQ[i + 1], t - i)


# ------------------------------------------------------------------ scene
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(ROOT / "web" / "building.glb"))
objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
# the glTF importer converts glTF Y-up to Blender Z-up; our file already holds IFC Z-up coordinates, so the
# import lies the building on its side. Rotate -90 deg about X to restore, then un-parent keeping world transforms.
from mathutils import Matrix  # noqa: E402
fix = Matrix.Rotation(-math.pi / 2, 4, "X")
bpy.context.view_layer.update()
world = {o: o.matrix_world.copy() for o in objs}
for o in objs:
    o.parent = None
    o.matrix_world = fix @ world[o]
bpy.context.view_layer.update()


def mat_emit(name, rgb, strength):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*[c * 0.35 for c in rgb], 1)
    b.inputs["Roughness"].default_value = 0.35
    b.inputs["Emission Color"].default_value = (*rgb, 1)
    b.inputs["Emission Strength"].default_value = strength
    b.inputs["Alpha"].default_value = 0.93
    return m


def mat_glass(name, rgb, alpha):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*rgb, 1)
    b.inputs["Alpha"].default_value = alpha
    b.inputs["Roughness"].default_value = 0.6
    return m


ghost = mat_glass("ghost", (0.55, 0.6, 0.7), 0.05)
dim = mat_glass("dim", (0.20, 0.21, 0.24), 0.55)
plates_min = {}
ring_boxes = []
for o in objs:
    nm = o.name.split(".")[0]
    if nm.startswith("R_"):
        _, a, b = nm.split("_")[:3]
        rid = f"{a}.{b}"
        storey = int(a)
        o.location.z += storey * EXPLODE
        bpy.context.view_layer.update()
        c = colour(rid) if rid in rooms else None
        o.data.materials.clear()
        if c is None:
            o.data.materials.append(dim)
        else:
            o.data.materials.append(mat_emit(f"m_{rid}", c, 2.4))
            if rid in FAULTY:
                ring_boxes.append([o.matrix_world @ Vector(v) for v in o.bound_box])
        bb = [o.matrix_world @ Vector(v) for v in o.bound_box]
        p = plates_min.setdefault(storey, [1e9, 1e9, 1e9, -1e9, -1e9])
        p[0] = min(p[0], min(v.x for v in bb)); p[1] = min(p[1], min(v.y for v in bb))
        p[2] = min(p[2], min(v.z for v in bb)); p[3] = max(p[3], max(v.x for v in bb)); p[4] = max(p[4], max(v.y for v in bb))
    else:
        o.hide_render = True          # context hidden: the exploded storeys read better on their own

plate_mat = bpy.data.materials.new("plate")
plate_mat.use_nodes = True
pb = plate_mat.node_tree.nodes["Principled BSDF"]
pb.inputs["Base Color"].default_value = (0.05, 0.055, 0.065, 1)
pb.inputs["Roughness"].default_value = 0.25
pb.inputs["Coat Weight"].default_value = 0.6
for s, (x0, y0, z0, x1, y1) in plates_min.items():
    bpy.ops.mesh.primitive_cube_add(size=1, location=((x0 + x1) / 2, (y0 + y1) / 2, z0 - 0.18))
    pl = bpy.context.object
    pl.scale = ((x1 - x0) + 5, (y1 - y0) + 5, 0.3)
    pl.data.materials.append(plate_mat)

# status-critical frame around rooms that break their promise (fault diagnosed)
ring = bpy.data.materials.new("ring"); ring.use_nodes = True
rb = ring.node_tree.nodes["Principled BSDF"]; rb.inputs["Base Color"].default_value = (*hexrgb("#d03b3b"), 1)
rb.inputs["Emission Color"].default_value = (*hexrgb("#d03b3b"), 1); rb.inputs["Emission Strength"].default_value = 12
for bb in ring_boxes:
    lo = Vector([min(v[i] for v in bb) for i in range(3)]) - Vector((0.6, 0.6, 0.3)); hi = Vector([max(v[i] for v in bb) for i in range(3)]) + Vector((0.6, 0.6, 0.3))
    bpy.ops.mesh.primitive_cube_add(size=1, location=(lo + hi) / 2); fr = bpy.context.object; fr.scale = hi - lo
    w = fr.modifiers.new("wire", "WIREFRAME"); w.thickness = 0.22; fr.data.materials.append(ring)

# ------------------------------------------------------------------ camera, light, world
allbb = [o.matrix_world @ Vector(v) for o in bpy.context.scene.objects if o.type == "MESH" and not o.hide_render for v in o.bound_box]
cen = Vector([(min(v[i] for v in allbb) + max(v[i] for v in allbb)) / 2 for i in range(3)])
size = max(max(v[i] for v in allbb) - min(v[i] for v in allbb) for i in range(3))
cam_data = bpy.data.cameras.new("cam")
cam_data.lens = 50
cam = bpy.data.objects.new("cam", cam_data)
bpy.context.scene.collection.objects.link(cam)
cam.location = cen + Vector((-1.05, -1.3, 0.70)) * size * 1.32
cam.rotation_euler = (cen - cam.location).to_track_quat("-Z", "Y").to_euler()
bpy.context.scene.camera = cam
key = bpy.data.lights.new("key", "AREA"); key.energy = 9000; key.size = 40; key.color = (0.75, 0.82, 1.0)
ko = bpy.data.objects.new("key", key); bpy.context.scene.collection.objects.link(ko)
ko.location = cen + Vector((-30, -10, 60)); ko.rotation_euler = (cen - ko.location).to_track_quat("-Z", "Y").to_euler()
world = bpy.data.worlds.new("w"); bpy.context.scene.world = world; world.use_nodes = True
bg = world.node_tree.nodes["Background"]; bg.inputs[0].default_value = (0.006, 0.008, 0.014, 1); bg.inputs[1].default_value = 1.0
sc = bpy.context.scene
sc.render.engine = "CYCLES"; sc.cycles.samples = SAMPLES; sc.cycles.use_denoising = True; sc.cycles.device = "CPU"
sc.render.resolution_x, sc.render.resolution_y = 1600, 1200
sc.view_settings.view_transform = "AgX"; sc.view_settings.look = "AgX - Medium High Contrast"
sc.render.film_transparent = False
sc.render.filepath = OUT
bpy.ops.render.render(write_still=True)
print("rendered", OUT)
