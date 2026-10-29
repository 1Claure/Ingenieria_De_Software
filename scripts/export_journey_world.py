"""Export the continuous Blender world as one optimized, textured glTF scene.

Run with Blender 4.5 --background --python scripts/export_journey_world.py.
The source .blend is read only; no render, server, GUI or watcher is started.
"""
from pathlib import Path
import hashlib
import json
import math
import random
import runpy
import struct
import sys
import time

import bpy
import bmesh
from mathutils import Vector, noise

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets/journey-render/v3/patagonia-realistic-90.blend"
TEXTURES = SOURCE.parent / "textures"
OUT = ROOT / "static/journey/world"
SOURCE_OUT = ROOT / "assets/journey-world"
RNG = random.Random(41271)


def rgb(value):
    c = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in c)


def three(point):
    return [round(float(point[0]), 5), round(float(point[2]), 5), round(float(-point[1]), 5)]


def add_operational_detail():
    helpers = runpy.run_path(str(ROOT / "scripts/render_journey.py"))
    box, cylinder, beam, curve = [helpers[n] for n in ("cube", "cylinder", "beam", "curve")]
    mats = bpy.data.materials
    steel = mats["Galvanized structural steel"]
    pale = mats["Weathered tank off-white enamel"]
    dark = mats["Dark oxidized structural metal"]
    blue = mats["Scratched blue machinery coating CC0"]
    rubber = mats.get("Protective pipe jacket") or helpers["material"]("Protective pipe jacket", "30383A", .8, .02)
    glass = mats["Deep blue glazing"]
    ochre = mats["Weathered safety coating"]
    # Long modules, low equipment, parked vehicles and pipe racks are drawn
    # from the distribution visible in official photos, not copied textures.
    for x, y in [(-15, 17), (-15, 24), (-15, 31), (-15, 38), (2, 38), (17, 39), (34, 40)]:
        box("Operations service module", (x, y, 1.65), (11.5, 3.4, 3.0), pale, .06)
        box("Service module roof", (x, y, 3.2), (11.7, 3.6, .16), dark)
        for step in range(13):
            box("Module corrugated rib", (x - 5.3 + step * .88, y - 1.72, 1.65), (.045, .05, 2.8), steel, 0)
        box("Module door", (x + 4.2, y - 1.76, 1.5), (.95, .06, 2.35), blue)
        for offset in (-3.6, -.8, 2):
            box("Module window", (x + offset, y - 1.77, 2), (1.3, .05, .85), glass)
        for offset in (-4.5, 4.5):
            box("Module support skid", (x + offset, y, .16), (.3, 4, .3), dark, .02)
    for x in (34, 40, 46, 52, 58, 64):
        y = 1.3
        box("Mobile pump trailer chassis", (x, y, .7), (3.1, 10.8, .35), dark)
        box("Mobile pump engine enclosure", (x, y + 2, 1.8), (2.8, 4.1, 1.8), pale)
        box("Pump power unit", (x, y - 2.2, 1.4), (2.7, 3.1, 1.2), blue)
        for dx in (-1.52, 1.52):
            for dy in (-3.6, -2.4, 3.5):
                wheel = cylinder("Trailer heavy tire", (x + dx, y + dy, .6), .57, .3, rubber, 12)
                wheel.rotation_euler.y = math.pi / 2
                hub = cylinder("Trailer wheel hub", (x + dx * 1.1, y + dy, .6), .27, .07, steel, 10)
                hub.rotation_euler.y = math.pi / 2
        for dx in (-.7, 0, .7):
            beam("Pump radiator grille", (x + dx, y + 4.1, 1.05), (x + dx, y + 4.1, 2.5), .035, dark, 6)
        curve("Mobile pressure line", [(x, y - 5.5, .9), (x, -4.8, .7), (x - 1, -5.3, .7), (20, -5.3, .7)], .08, steel)
    # Pipe racks and slender stored drill-pipe bundles establish industrial scale.
    for y in (31, 33.3):
        for x in (-2, 4, 10):
            box("Pipe rack upright", (x, y, .6), (.18, 1.5, 1.2), dark, .01)
        for i in range(8):
            beam("Stored drill pipe", (-4, y - .55 + i * .16, 1.18), (13, y - .55 + i * .16, 1.18), .065, steel, 8)
    for x, y in [(-4, 46), (4, 46), (15, 46)]:
        box("Service pickup body", (x, y, .8), (2, 4.5, .8), pale, .09)
        box("Service pickup cabin", (x, y + .5, 1.55), (1.9, 2, .95), pale, .12)
        box("Service pickup windshield", (x, y - .52, 1.6), (1.7, .04, .65), glass, .02)
        for dx in (-1, 1):
            for dy in (-1.4, 1.4):
                wheel = cylinder("Pickup tire", (x + dx, y + dy, .45), .42, .27, rubber, 12)
                wheel.rotation_euler.y = math.pi / 2
    for x, y in [(-8, 8), (21, 20), (56, 18)]:
        box("Operational electrical cabinet", (x, y, 1.05), (.9, .65, 1.9), pale, .04)
        beam("Cabinet conduit", (x, y + .2, .2), (x, y + 3, .2), .04, dark)
    # A few irregular low gravel berms, rendered as terrain, avoid a pristine slab.
    for x in range(-60, 100, 8):
        for y in (-3, 58):
            bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=1, location=(x, y + RNG.uniform(-1, 1), .08))
            obj = bpy.context.object
            obj.name = "Irregular pad gravel berm"
            obj.scale = (3.8, .6, .23)
            obj.data.materials.append(mats["Photographic dry gravel ground CC0"])


def optimize_world():
    foreground = bpy.data.objects.get("Foreground ground before cutaway")
    if foreground:
        bpy.data.objects.remove(foreground, do_unlink=True)
    # Keep all six strata in the fixed scene. A shorter lateral extent and real
    # relief close to the camera replace the render-only 4.6 km wall mesh.
    depths = [.04, -7, -17, -28, -36, -52, -150]
    for layer in range(6):
        obj = bpy.data.objects[f"Continuous deep formation {layer}"]
        material = obj.data.materials[0]
        nx, nz = 220, 12 if layer < 5 else 8
        vertices, faces = [], []
        for j in range(nz + 1):
            for i in range(nx + 1):
                x = -180 + 440 * i / nx
                high = depths[layer] + (0 if layer == 0 else math.sin(x * .07) * .85)
                low = depths[layer + 1] + math.sin(x * .07) * .85
                z = high + (low - high) * j / nz
                rough = noise.noise(Vector((x * .16, z * .23, 4.2))) * .65
                rough += noise.noise(Vector((x * .75, z * .82, 2.8))) * .16
                vertices.append((x, -5.38 + rough, z))
        for j in range(nz):
            for i in range(nx):
                a = j * (nx + 1) + i
                faces.append((a, a + nx + 1, a + nx + 2, a + 1))
        mesh = bpy.data.meshes.new(f"Relief stratum {layer}")
        mesh.from_pydata(vertices, [], faces)
        mesh.materials.append(material)
        mesh.update()
        for polygon in mesh.polygons:
            polygon.use_smooth = True
        obj.data = mesh
    terrain = bpy.data.objects["Extensive steppe landscape"]
    decimate = terrain.modifiers.new("Distant terrain budget", "DECIMATE")
    decimate.ratio = .36
    decimate.use_collapse_triangulate = True


def material_spec(name):
    if "cliff layer" in name:
        layer = int(name.rsplit(" ", 1)[-1])
        tint = [(1, .98, .90), (1, .93, .82), (.78, .70, .63), (.96, .94, .88), (.57, .63, .64), (.47, .51, .52)][layer]
        return "cliff_side", .09, tint, 0, .9
    if "ground" in name.lower() or "concrete ring" in name.lower():
        return "dry_ground_rocks", .32, (1, 1, 1), 0, .95
    if "checker" in name:
        return "metal_plate", 1.4, (.68, .72, .75), .72, .55
    if "blue machinery" in name:
        return "blue_metal_plate", .8, (.72, .82, .9), .55, .52
    specs = {
        "Galvanized structural steel": (None, .65, (.92, .96, 1), .82, .47),
        "Weathered tank off-white enamel": (None, .28, (.81, .87, .85), .06, .67),
        "Dark oxidized structural metal": (None, .65, (.91, .95, 1), .65, .64),
        "Weathered safety coating": (None, .65, (1, .94, .87), .08, .63),
        "Stained cast concrete": ("dry_ground_rocks", .5, (.64, .64, .59), 0, .94),
    }
    return specs.get(name, (None, 1, (1, 1, 1), None, None))


def normalize_material(material):
    name = material.name
    family, scale, tint, metallic, roughness = material_spec(name)
    old = material.node_tree.nodes.get("Principled BSDF")
    base = tuple(old.inputs["Base Color"].default_value) if old else (.4, .4, .4, 1)
    if metallic is None:
        metallic = old.inputs["Metallic"].default_value if old else 0
        roughness = old.inputs["Roughness"].default_value if old else .8
    emission = tuple(old.inputs["Emission Color"].default_value) if old else (0, 0, 0, 1)
    strength = old.inputs["Emission Strength"].default_value if old else 0
    material.animation_data_clear()
    material.node_tree.animation_data_clear()
    nodes, links = material.node_tree.nodes, material.node_tree.links
    nodes.clear()
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = base
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Emission Color"].default_value = emission
    bsdf.inputs["Emission Strength"].default_value = min(strength, .18)
    output = nodes.new("ShaderNodeOutputMaterial")
    links.new(bsdf.outputs[0], output.inputs["Surface"])
    material.use_backface_culling = True
    material.diffuse_color = base
    if family:
        for kind, socket in [("diff", "Base Color"), ("rough", "Roughness"), ("metal", "Metallic"), ("nor_gl", "Normal")]:
            path = TEXTURES / family / f"{family}_{kind}_1k.jpg"
            if not path.exists() or (kind == "metal" and metallic < .6) or (kind == "rough" and family == "blue_metal_plate"):
                continue
            texture = nodes.new("ShaderNodeTexImage")
            texture.image = bpy.data.images.load(str(path), check_existing=True)
            texture.image.colorspace_settings.name = "sRGB" if kind == "diff" else "Non-Color"
            texture.extension = "REPEAT"
            if kind == "nor_gl":
                normal = nodes.new("ShaderNodeNormalMap")
                normal.inputs["Strength"].default_value = .6 if family == "cliff_side" else .35
                links.new(texture.outputs["Color"], normal.inputs["Color"])
                links.new(normal.outputs[0], bsdf.inputs[socket])
            else:
                links.new(texture.outputs["Color"], bsdf.inputs[socket])
    # Vertex color multiplies the photographed albedo, retaining variation
    # between manufactured parts without unsupported procedural shader nodes.
    material["textureFamily"] = family or "solid"
    material["sourceLicense"] = "CC0-1.0" if family else "project-generated"
    return scale, tint


def convert_and_group(specs):
    groups = {}
    geometry = [obj for obj in bpy.context.scene.objects if obj.type in {"MESH", "CURVE"}]
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    # Snapshot the entire graph before creating or removing scene objects.
    # Blender 4.5 can invalidate evaluated curve pointers during bulk convert.
    snapshots = []
    for i, obj in enumerate(geometry):
        mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
        snapshots.append((obj.name, mesh, obj.matrix_world.copy()))
        if i % 300 == 0:
            print(f"WORLD evaluated {i}/{len(geometry)}", flush=True)
    for name, mesh, matrix in snapshots:
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.collection.objects.link(obj)
        obj.matrix_world = matrix
    for obj in geometry:
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.context.view_layer.update()
    print("WORLD assigning explicit UVs", flush=True)
    for index, obj in enumerate(list(bpy.context.scene.objects)):
        if obj.type != "MESH":
            continue
        mesh = obj.data
        name = obj.name
        matrix = obj.matrix_world.copy()
        material = mesh.materials[0] if mesh.materials else None
        if not material:
            continue
        role = "infrastructure"
        if "formation" in name:
            role = "geology"
        elif "landscape" in name or "berm" in name or "scrub" in name:
            role = "terrain"
        elif "casing" in name.lower() or "Well casing" in name:
            role = "well"
        if "Water reflection" in material.name:
            role = "water"
        scale, tint = specs[material.name]
        if not mesh.uv_layers.get("UVMap"):
            mesh.uv_layers.new(name="UVMap")
        mesh.color_attributes.new(name="Color", type="BYTE_COLOR", domain="CORNER")
        # Both layers use corner CustomData. Adding Color can reallocate the
        # UV descriptor, so reacquire RNA wrappers only after both exist.
        mesh.color_attributes.active_color = mesh.color_attributes["Color"]
        uv_values = [0.0] * (len(mesh.loops) * 2)
        color_values = [0.0] * (len(mesh.loops) * 4)
        variation = .89 + (index * .61803398875 % 1) * .13
        for poly in mesh.polygons:
            axis = max(range(3), key=lambda a: abs(poly.normal[a]))
            for loop_index in poly.loop_indices:
                vertex = mesh.vertices[mesh.loops[loop_index].vertex_index].co
                world = matrix @ vertex
                if role == "geology":
                    u, v = world.x, world.z
                elif "ground" in material.name.lower() or role == "terrain":
                    u, v = world.x, world.y
                elif axis == 2:
                    u, v = vertex.x, vertex.y
                elif axis == 1:
                    u, v = vertex.x, vertex.z
                else:
                    u, v = vertex.y, vertex.z
                uv_values[loop_index * 2:loop_index * 2 + 2] = [u * scale, v * scale]
                color_values[loop_index * 4:loop_index * 4 + 4] = [*[min(1, c * variation) for c in tint], 1]
        mesh.uv_layers["UVMap"].data.foreach_set("uv", uv_values)
        mesh.color_attributes["Color"].data.foreach_set("color", color_values)
        groups.setdefault((role, material.name), []).append(obj)
    print("WORLD merging material groups", flush=True)
    # One mesh per role/material means ~25 draw calls instead of 1,400.
    result = []
    for (role, material), objects in groups.items():
        bpy.ops.object.select_all(action="DESELECT")
        for obj in objects:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = objects[0]
        if len(objects) > 1:
            bpy.ops.object.join()
        obj = bpy.context.view_layer.objects.active
        obj.name = f"{role}__{material.lower().replace(' ', '_')}"
        obj["renderRole"] = role
        obj["sourceMaterial"] = material
        obj.data.calc_loop_triangles()
        result.append(obj)
    return result


def finalize_glb(path):
    """Deduplicate identical texture references and verify embedded glTF data."""
    data = path.read_bytes()
    length = struct.unpack_from("<I", data, 12)[0]
    gltf = json.loads(data[20:20 + length])
    textures, lookup, remap = [], {}, {}
    for index, texture in enumerate(gltf.get("textures", [])):
        key = json.dumps(texture, sort_keys=True)
        if key not in lookup:
            lookup[key] = len(textures)
            textures.append(texture)
        remap[index] = lookup[key]
    for material in gltf["materials"]:
        pbr = material.get("pbrMetallicRoughness", {})
        for key in ("baseColorTexture", "metallicRoughnessTexture"):
            if key in pbr:
                pbr[key]["index"] = remap[pbr[key]["index"]]
        for key in ("normalTexture", "occlusionTexture", "emissiveTexture"):
            if key in material:
                material[key]["index"] = remap[material[key]["index"]]
    gltf["textures"] = textures
    encoded = json.dumps(gltf, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    encoded += b" " * ((-len(encoded)) % 4)
    tail = data[20 + length:]
    final = struct.pack("<III", 0x46546C67, 2, 20 + len(encoded) + len(tail))
    final += struct.pack("<II", len(encoded), 0x4E4F534A) + encoded + tail
    path.write_bytes(final)
    primitives = [p for m in gltf["meshes"] for p in m["primitives"]]
    assert all("uri" not in image and "bufferView" in image for image in gltf["images"])
    assert all(all(a in p["attributes"] for a in ("POSITION", "NORMAL", "TEXCOORD_0", "COLOR_0")) for p in primitives)
    return {"vertices": sum(gltf["accessors"][p["attributes"]["POSITION"]]["count"] for p in primitives),
            "textures": len(textures), "images": len(gltf["images"]), "materials": len(gltf["materials"])}


def main():
    start = time.perf_counter()
    OUT.mkdir(parents=True, exist_ok=True)
    SOURCE_OUT.mkdir(parents=True, exist_ok=True)
    prepared = "--prepared" in sys.argv
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE_OUT / "patagonia-web.blend" if prepared else SOURCE))
    if prepared:
        groups = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    else:
        bpy.context.scene.frame_set(45)
        print("WORLD optimizing fixed geometry", flush=True)
        add_operational_detail()
        optimize_world()
        used = {m for obj in bpy.context.scene.objects if obj.type in {"MESH", "CURVE"} for m in obj.data.materials}
        specs = {m.name: normalize_material(m) for m in used}
        print("WORLD converting explicit UV/PBR meshes", flush=True)
        groups = convert_and_group(specs)
    for obj in groups:
        mesh = bmesh.new()
        mesh.from_mesh(obj.data)
        bmesh.ops.triangulate(mesh, faces=list(mesh.faces))
        mesh.to_mesh(obj.data)
        mesh.free()
        obj.data.update()
        obj.data.calc_loop_triangles()
    # Camera/environment belong to the renderer; no animation tracks or lights
    # are exported. All content remains in one static scene for real camera travel.
    for obj in list(bpy.context.scene.objects):
        if obj.type != "MESH":
            bpy.data.objects.remove(obj, do_unlink=True)
    bpy.ops.object.select_all(action="SELECT")
    path = OUT / "patagonia.glb"
    print("WORLD exporting glTF", flush=True)
    bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB", use_selection=True,
        export_animations=False, export_cameras=False, export_lights=False,
        export_yup=True, export_extras=True, export_materials="EXPORT",
        export_texcoords=True, export_normals=True, export_tangents=True,
        export_image_format="JPEG", export_image_quality=88, export_vertex_color="NAME", export_vertex_color_name="Color",
        export_draco_mesh_compression_enable=False)
    exported = finalize_glb(path)
    metadata = []
    for obj in groups:
        corners = [three(obj.matrix_world @ Vector(c)) for c in obj.bound_box]
        metadata.append({"name": obj.name, "role": obj["renderRole"], "material": obj["sourceMaterial"],
            "vertices": len(obj.data.vertices), "triangles": len(obj.data.loop_triangles),
            "bounds": {"min": [min(c[i] for c in corners) for i in range(3)], "max": [max(c[i] for c in corners) for i in range(3)]}})
    # Four chapters; intermediate samples refine the same continuous trajectory.
    shots = [
        (0, (100, 30, 5), (18, 20, 10), 43, "superficie"),
        (.08, (100, 3, 12), (20.5, 14, 5), 43, "salida_elevada"),
        (.16, (99, -28, 11), (23, 8, 0), 43, "aproximacion"),
        (1 / 3, (91, -50, 2), (27, -3, -15), 44, "descenso"),
        (.5, (87, -76, -10), (33, -6, -25), 45, "curva"),
        (2 / 3, (85, -69, -25), (43, -6, -36), 48, "etapas"),
        (.84, (122, -102, 18), (34, 2, -16), 43, "ascenso"),
        (1, (175, -132, 64), (29, 9, -5), 40, "conjunto"),
    ]
    camera = [{"progress": p, "position": three(eye), "target": three(target),
               "fov": round(math.degrees(2 * math.atan(36 / (2 * lens * (16 / 9)))), 5),
               "lens": lens, "filmOffset": -8.64, "name": name} for p, eye, target, lens, name in shots]
    wy = -6.63
    water = [(9, wy, -.1), (9, wy, -28)]
    water += [(9 + 9 * (1 - math.cos(math.pi / 2 * i / 40)), wy, -28 - 9 * math.sin(math.pi / 2 * i / 40)) for i in range(1, 41)]
    water.append((68, wy, -37))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    camera_digest = hashlib.sha256(json.dumps(camera, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:8]
    manifest = {"version": "continuous-world-" + digest[:16] + "-camera-" + camera_digest, "model": "patagonia.glb", "bytes": path.stat().st_size,
        "sha256": digest, "coordinateSystem": "Three.js/glTF Y-up; Blender (x,y,z) -> (x,z,-y)",
        "note": "Instalación industrial y corte geológico ilustrativos, sin escala estratigráfica validada; no es una simulación física.",
        "source": str(SOURCE.relative_to(ROOT)).replace('\\', '/'), "cameraStops": camera,
        "chapterProgress": [0, 1 / 3, 2 / 3, 1], "waterPath3D": [three(p) for p in water],
        "waterStages": [three((x, wy, -37)) for x in (27, 36, 45, 54, 63)],
        "cutPlane": {"axis": "z", "position": 5.38, "surfaceSide": "negative"},
        "rigCenter": [9, 14, -15], "operationBounds": {"min": [-30, -52, -62], "max": [80, 31, 7]},
        "groups": metadata, "triangles": sum(g['triangles'] for g in metadata),
        "vertices": exported["vertices"], "sourceVertices": sum(g['vertices'] for g in metadata), "drawCalls": len(metadata),
        "textureCount": exported["textures"], "imageCount": exported["images"], "materialCount": exported["materials"],
        "textureLicense": "CC0-1.0", "textureSources": ["https://polyhaven.com/a/" + s for s in ('dry_ground_rocks', 'metal_plate', 'blue_metal_plate', 'cliff_side')],
        "exportSeconds": round(time.perf_counter() - start, 2)}
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding="utf-8")
    bpy.ops.wm.save_as_mainfile(filepath=str(SOURCE_OUT / "patagonia-web.blend"))
    print("WORLD_DONE " + json.dumps({k: manifest[k] for k in ('version', 'bytes', 'triangles', 'vertices', 'drawCalls', 'exportSeconds')}), flush=True)


if __name__ == "__main__":
    main()
