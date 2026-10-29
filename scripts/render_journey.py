"""Build and render the Inicio cinematic from one Blender scene.

blender --background --python scripts/render_journey.py -- --mode first
blender --background --python scripts/render_journey.py -- --mode previews --existing
blender --background --python scripts/render_journey.py -- --mode sequence --existing

The geology, fractures and water paths are illustrative, not a physical simulation.
"""
from pathlib import Path
import argparse
import json
import math
import random
import sys
import time

import bpy
from mathutils import Vector, noise
from bpy_extras.object_utils import world_to_camera_view

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "journey-render"
BLEND = OUT / "patagonia-water-journey.blend"
RNG = random.Random(38411)


def args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["first", "previews", "sequence"], default="first")
    parser.add_argument("--existing", action="store_true")
    parser.add_argument("--frames", type=int, default=60)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--samples", type=int, default=32)
    parser.add_argument("--realistic", action="store_true")
    parser.add_argument("--engine", choices=["EEVEE", "CYCLES"], default="EEVEE")
    parser.add_argument("--only-frame", type=int, default=None, help="Render one zero-based frame for visual verification")
    tail = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(tail)


def srgb_hex(value):
    channels = [int(value.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in channels) + (1,)


def material(name, color, roughness=.6, metallic=0, emission=None, rock=0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = srgb_hex(color)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    if emission:
        bsdf.inputs["Emission Color"].default_value = srgb_hex(emission)
        bsdf.inputs["Emission Strength"].default_value = .55
    if rock:
        coords = nodes.new("ShaderNodeTexCoord")
        noise = nodes.new("ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = 5.8
        noise.inputs["Detail"].default_value = 4.5
        noise.inputs["Roughness"].default_value = .8
        links.new(coords.outputs["Object"], noise.inputs["Vector"])
        ramp = nodes.new("ShaderNodeValToRGB")
        base = srgb_hex(color)
        ramp.color_ramp.elements[0].position = .18
        ramp.color_ramp.elements[0].color = tuple(v * .48 for v in base[:3]) + (1,)
        ramp.color_ramp.elements[1].position = .82
        ramp.color_ramp.elements[1].color = tuple(min(1, v * 1.37) for v in base[:3]) + (1,)
        links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
        links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
        fine = nodes.new("ShaderNodeTexNoise")
        fine.inputs["Scale"].default_value = 95
        fine.inputs["Detail"].default_value = 2
        links.new(coords.outputs["Object"], fine.inputs["Vector"])
        bump = nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = .45
        bump.inputs["Distance"].default_value = .075 * rock
        links.new(fine.outputs["Fac"], bump.inputs["Height"])
        broad_bump = nodes.new("ShaderNodeBump")
        broad_bump.inputs["Strength"].default_value = .5
        broad_bump.inputs["Distance"].default_value = .16 * rock
        links.new(noise.outputs["Fac"], broad_bump.inputs["Height"])
        links.new(bump.outputs["Normal"], broad_bump.inputs["Normal"])
        links.new(broad_bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def assign(obj, mat):
    obj.data.materials.append(mat)
    return obj


def cube(name, loc, scale, mat, bevel=.025):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    assign(obj, mat)
    if bevel:
        modifier = obj.modifiers.new("Manufactured edge", "BEVEL")
        modifier.width = bevel
        modifier.segments = 2
        obj.modifiers.new("Weighted normals", "WEIGHTED_NORMAL")
    return obj


def cylinder(name, loc, radius, depth, mat, vertices=24, radius2=None):
    if radius2 is not None:
        bpy.ops.mesh.primitive_cone_add(vertices=vertices, radius1=radius, radius2=radius2, depth=depth, location=loc)
    else:
        bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=loc)
    obj = bpy.context.object
    obj.name = name
    assign(obj, mat)
    for poly in obj.data.polygons:
        poly.use_smooth = True
    bevel = obj.modifiers.new("Edge glint", "BEVEL")
    bevel.width = min(.025, radius * .15)
    bevel.segments = 2
    obj.modifiers.new("Weighted normals", "WEIGHTED_NORMAL")
    return obj


def beam(name, a, b, radius, mat, vertices=10):
    a, b = Vector(a), Vector(b)
    obj = cylinder(name, (a + b) / 2, radius, (b - a).length, mat, vertices)
    obj.rotation_euler = (b - a).to_track_quat("Z", "Y").to_euler()
    return obj


def curve(name, points, radius, mat, resolution=2):
    data = bpy.data.curves.new(name, "CURVE")
    data.dimensions = "3D"
    data.resolution_u = resolution
    data.bevel_depth = radius
    data.bevel_resolution = 2
    spline = data.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for point, value in zip(spline.points, points):
        point.co = (*value, 1)
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    assign(obj, mat)
    return obj


def ground_height(x, y):
    return .2 + .075 * math.sin(x * .71) + .065 * math.cos(y * .82 + x * .2)


def boundary(x, level):
    return level + math.sin(x * .36 + level * .16) * .17 + math.sin(x * 1.11) * .025


def geology(mats):
    xmin, xmax, front, back = -8, 20, -4.1, 9
    depths = [.12, -1.2, -3.05, -4.8, -6.15, -9.1]
    n = 104
    for layer, mat in enumerate(mats):
        verts, faces = [], []
        for index in range(n + 1):
            x = xmin + (xmax - xmin) * index / n
            y = front + .065 * math.sin(x * 1.41) + .025 * math.sin(x * 3.2)
            top, bottom = boundary(x, depths[layer]), boundary(x, depths[layer + 1])
            verts.extend([(x, y, top), (x, y, bottom), (x, back, top), (x, back, bottom)])
        for index in range(n):
            a, b = index * 4, (index + 1) * 4
            faces.extend([(a, a + 1, b + 1, b), (a + 2, b + 2, b + 3, a + 3),
                          (a, b, b + 2, a + 2), (a + 1, a + 3, b + 3, b + 1)])
        faces.extend([(0, 2, 3, 1), (4 * n, 4 * n + 1, 4 * n + 3, 4 * n + 2)])
        data = bpy.data.meshes.new(f"Geological formation {layer + 1}")
        data.from_pydata(verts, [], faces)
        data.update()
        obj = bpy.data.objects.new(data.name, data)
        bpy.context.collection.objects.link(obj)
        assign(obj, mat)
        bevel = obj.modifiers.new("Weathered section edge", "BEVEL")
        bevel.width = .075
        bevel.segments = 2
    return xmin, xmax, front, back


def terrain(name, bounds, subdivisions, mat, height_fn):
    x0, x1, y0, y1 = bounds
    nx, ny = subdivisions
    verts, faces = [], []
    for j in range(ny + 1):
        y = y0 + (y1 - y0) * j / ny
        for i in range(nx + 1):
            x = x0 + (x1 - x0) * i / nx
            verts.append((x, y, height_fn(x, y)))
    for j in range(ny):
        for i in range(nx):
            a = j * (nx + 1) + i
            faces.append((a, a + 1, a + nx + 2, a + nx + 1))
    data = bpy.data.meshes.new(name)
    data.from_pydata(verts, [], faces)
    data.update()
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    assign(obj, mat)
    for p in data.polygons:
        p.use_smooth = True
    return obj


def pbr_material(name, asset, scale=.3, metallic=0):
    folder = OUT / "textures" / asset
    mat = material(name, "A9A39A", .65, metallic)
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    coordinates = nodes.new("ShaderNodeTexCoord")
    mapping = nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (scale, scale, scale)
    links.new(coordinates.outputs["Object"], mapping.inputs["Vector"])
    for kind, socket in [("diff", "Base Color"), ("rough", "Roughness"), ("metal", "Metallic")]:
        path = folder / f"{asset}_{kind}_1k.jpg"
        if not path.exists():
            continue
        image = nodes.new("ShaderNodeTexImage")
        image.image = bpy.data.images.load(str(path), check_existing=True)
        if kind != "diff":
            image.image.colorspace_settings.name = "Non-Color"
        image.projection = "BOX"
        image.projection_blend = .2
        links.new(mapping.outputs["Vector"], image.inputs["Vector"])
        links.new(image.outputs["Color"], bsdf.inputs[socket])
    path = folder / f"{asset}_nor_gl_1k.jpg"
    if path.exists():
        image = nodes.new("ShaderNodeTexImage")
        image.image = bpy.data.images.load(str(path), check_existing=True)
        image.image.colorspace_settings.name = "Non-Color"
        image.projection = "BOX"
        image.projection_blend = .2
        links.new(mapping.outputs["Vector"], image.inputs["Vector"])
        normal = nodes.new("ShaderNodeNormalMap")
        normal.inputs["Strength"].default_value = .55
        links.new(image.outputs["Color"], normal.inputs["Color"])
        links.new(normal.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def weathered_paint(name, color, metal=.55):
    mat = material(name, color, .42, metal)
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    coords = nodes.new("ShaderNodeTexCoord")
    mapping = nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (1.4, 1.4, .045)
    links.new(coords.outputs["Object"], mapping.inputs["Vector"])
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 5
    noise.inputs["Detail"].default_value = 4
    links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
    ramp = nodes.new("ShaderNodeValToRGB")
    color = srgb_hex(color)
    ramp.color_ramp.elements[0].position = .18
    ramp.color_ramp.elements[0].color = tuple(c * .45 for c in color[:3]) + (1,)
    ramp.color_ramp.elements[1].position = .72
    ramp.color_ramp.elements[1].color = color
    links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    fine = nodes.new("ShaderNodeTexNoise")
    fine.inputs["Scale"].default_value = 65
    fine.inputs["Detail"].default_value = 2
    links.new(coords.outputs["Object"], fine.inputs["Vector"])
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = .22
    bump.inputs["Distance"].default_value = .012
    links.new(fine.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def build_realistic(count):
    """A full-scale installation in continuous terrain, without a display block."""
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    soil = pbr_material("Photographic dry gravel ground CC0", "dry_ground_rocks", .32)
    deck = pbr_material("Worn checker steel plate CC0", "metal_plate", 1.4, .7)
    blue = pbr_material("Scratched blue machinery coating CC0", "blue_metal_plate", .8, .6)
    steel = weathered_paint("Galvanized structural steel", "8F969A", .86)
    pale = weathered_paint("Weathered tank off-white enamel", "BFC2BC", .52)
    iron = weathered_paint("Dark oxidized structural metal", "343D40", .68)
    ochre = weathered_paint("Weathered safety coating", "A76C35", .48)
    rubber = material("Protective pipe jacket", "30383A", .7, .12)
    glass = material("Deep blue glazing", "40565E", .12, .65)
    light = material("Warm practical lamps", "E5BC7C", .2, .2, "FFD099")
    water = material("Water reflection in section", "42899D", .16, .3, "32768B")
    def land(x, y):
        local = .09 * math.sin(x * .37) * math.cos(y * .28) + .025 * math.sin(x * 1.1 + y * .5)
        distance = max(0, abs(x - 15) - 65, y - 70)
        relief = min(1, distance / 95) * (3.8 + 2.5 * math.sin(x * .018) * math.cos(y * .022)
                 + 1.6 * math.sin(x * .043 + y * .027) + .45 * math.sin(x * .11))
        return local + relief
    terrain("Extensive steppe landscape", (-360, 400, -6, 460), (230, 170), soil, land)
    foreground = terrain("Foreground ground before cutaway", (-360, 400, -240, -6), (150, 95), soil.copy(), land)
    foreground.data.materials[0].name = "Foreground ground transition"
    # Future descent reveals a full-width geological face, never a freestanding box.
    depths = [0, -7, -17, -28, -36, -52, -90]
    shades = ["A08F76", "B19D7E", "8E7059", "ADA28D", "65625A", "514E49"]
    for index, color in enumerate(shades):
        verts, faces = [], []
        for j in range(181):
            x = -260 + 560 * j / 180
            y = -6.1 + .12 * math.sin(x * .46)
            verts.extend([(x, y, boundary(x * .28, depths[index])),
                          (x, y, boundary(x * .28, depths[index + 1]))])
        for j in range(180):
            faces.append((j * 2, j * 2 + 1, j * 2 + 3, j * 2 + 2))
        data = bpy.data.meshes.new(f"Continuous deep formation {index}")
        data.from_pydata(verts, [], faces)
        data.update()
        obj = bpy.data.objects.new(data.name, data)
        bpy.context.collection.objects.link(obj)
        assign(obj, material(f"Weathered geological rock {index}", color, .98, rock=2.5))

    # Low, irregular gravel berms and plant tufts break the horizon naturally.
    plant = material("Dry silvery steppe foliage", "787A5E", .98)
    for i in range(85):
        x, y = RNG.uniform(-65, 110), RNG.uniform(-4, 130)
        if -7 < x < 57 and 0 < y < 40:
            continue
        z = land(x, y)
        for branch in range(4):
            angle = branch * math.pi / 2 + i * .63
            radius, high = RNG.uniform(.16, .42), RNG.uniform(.18, .5)
            curve("Steppe scrub stem", [(x, y, z), (x + math.cos(angle) * radius, y + math.sin(angle) * radius, z + high)], .018, plant)
    # Industrial foundation and drilling floor at credible full-size proportions.
    rx, ry = 9, 15
    cube("Rig concrete foundation", (rx, ry, .24), (10.4, 9.2, .48), material("Stained cast concrete", "8D8C82", .92, rock=.45), .12)
    for x in [-3.3, 3.3]:
        for y in [-2.7, 2.7]:
            cube("Heavy rig substructure", (rx + x, ry + y, 1.95), (.5, .5, 3.4), iron, .035)
    cube("Drilling floor plate", (rx, ry, 3.7), (9, 7.5, .3), deck, .04)
    for x in [-3.7, 3.7]:
        beam("Substructure diagonal", (rx + x, ry - 3, .5), (rx - x, ry - 3, 3.55), .12, iron)
    mast_base, mast_top = 3.9, 28.5
    corners = [(-2.8, -2.15), (2.8, -2.15), (2.8, 2.15), (-2.8, 2.15)]
    for side, (dx, dy) in enumerate(corners):
        beam("Main mast steel chord", (rx + dx, ry + dy, mast_base), (rx + dx * .22, ry + dy * .22, mast_top), .12, steel, 12)
        nx, ny = corners[(side + 1) % 4]
        for level in range(10):
            z0, z1 = mast_base + level * 2.46, mast_base + (level + 1) * 2.46
            s0, s1 = 1 - (z0 - mast_base) / 24.6 * .78, 1 - (z1 - mast_base) / 24.6 * .78
            beam("Mast cross brace", (rx + dx * s0, ry + dy * s0, z0), (rx + nx * s1, ry + ny * s1, z1), .065, steel)
            beam("Mast transverse member", (rx + dx * s0, ry + dy * s0, z0), (rx + nx * s0, ry + ny * s0, z0), .075, steel)
            if level % 2 == 0:
                beam("Counter diagonal brace", (rx + nx * s0, ry + ny * s0, z0), (rx + dx * s1, ry + dy * s1, z1), .045, iron)
    cube("Crown block frame", (rx, ry, 28.8), (2.2, 1.7, .65), iron)
    for dx in [-.55, -.2, .2, .55]:
        wheel = cylinder("Crown sheave", (rx + dx, ry, 29.2), .55, .18, steel, 24)
        wheel.rotation_euler.y = math.pi / 2
    for dx in [-.3, -.1, .1, .3]:
        beam("Hoisting wire rope", (rx + dx, ry, 28.5), (rx + dx, ry, 17.4), .025, iron, 8)
    cube("Traveling block housing", (rx, ry, 17.3), (1.2, .7, 1.4), ochre, .12)
    beam("Drill string steel", (rx, ry, 4), (rx, ry, 16.8), .12, steel)
    for anchor in [(-7, -5), (7, -5), (7, 6), (-7, 6)]:
        beam("Mast guy tension cable", (rx + anchor[0], ry + anchor[1], .4), (rx, ry, 23.5), .018, iron, 8)
    # Monkey board, fixed ladder and full handrails: small details anchor scale.
    cube("Monkey board deck", (rx, ry - 1.35, 20), (4.2, 3.5, .16), deck)
    for z in [4.7, 5.35]:
        for side in [-1, 1]:
            beam("Drilling floor handrail", (rx - 4.3, ry + side * 3.6, z), (rx + 4.3, ry + side * 3.6, z), .045, ochre)
    for x in range(-4, 5, 2):
        for side in [-1, 1]:
            beam("Rail upright", (rx + x, ry + side * 3.6, 3.85), (rx + x, ry + side * 3.6, 5.4), .045, ochre)
    for z in [20.65, 21.2]:
        for side in [-1, 1]:
            beam("High platform safety rail", (rx + side * 2, ry - 3, z), (rx + side * 2, ry + .3, z), .035, ochre)
    for dx in [-.3, .3]:
        beam("Mast ladder rail", (rx + 2.8 + dx, ry + 2.2, 3.8), (rx + .65 + dx, ry + .5, 28.3), .032, steel)
    for i in range(64):
        z = 4 + i * .37
        f = (z - 3.8) / 24.5
        x, y = rx + 2.8 - f * 2.15, ry + 2.2 - f * 1.7
        beam("Ladder rung", (x - .3, y, z), (x + .3, y, z), .024, steel, 8)
    for i in range(16):
        cube("Steel access stair tread", (rx - 7.5 + i * .22, ry - 2.6, .35 + i * .22), (.42, 1.25, .08), deck, .005)
    for y in [-3.3, -1.9]:
        beam("Access stair handrail", (rx - 7.7, ry + y, 1.45), (rx - 3.8, ry + y, 5.1), .045, ochre)

    # Storage vessels: rivet/weld rings, access rails, roof vents and ladders.
    for tx, ty, radius, high in [(28, 24, 3.15, 8.6), (38, 25, 3.35, 8.9), (49, 25, 3.3, 8.7)]:
        cylinder("Tank concrete ring", (tx, ty, .28), radius + .45, .55, soil, 64)
        cylinder("Full size storage vessel", (tx, ty, .55 + high / 2), radius, high, pale, 64)
        cylinder("Shallow conical tank roof", (tx, ty, high + .8), radius + .04, .5, steel, 64, .25)
        for z in [1.3, 3.5, 5.7, 7.8]:
            cylinder("Circumferential welded seam", (tx, ty, z), radius + .015, .035, steel, 64)
        for dx in [-.32, .32]:
            beam("Tank access ladder", (tx + dx, ty - radius - .2, .5), (tx + dx, ty - radius - .2, high + 1), .036, iron)
        for i in range(28):
            beam("Tank ladder rung", (tx - .32, ty - radius - .2, .6 + i * .32), (tx + .32, ty - radius - .2, .6 + i * .32), .027, steel, 8)
        for z in [high + 1, high + 1.6]:
            pts = [(tx + (radius - .18) * math.cos(i * math.tau / 64), ty + (radius - .18) * math.sin(i * math.tau / 64), z) for i in range(65)]
            curve("Tank roof circular safety rail", pts, .035, steel)
        for i in range(16):
            a = i * math.tau / 16
            beam("Tank roof rail post", (tx + (radius - .18) * math.cos(a), ty + (radius - .18) * math.sin(a), high + .65),
                 (tx + (radius - .18) * math.cos(a), ty + (radius - .18) * math.sin(a), high + 1.6), .03, steel, 8)
        beam("Tank roof vent", (tx, ty, high + 1.05), (tx, ty, high + 2.1), .17, steel)
        curve("Storage outlet elbow", [(tx, ty - radius, 1.45), (tx, ty - radius - 1.5, 1.45), (tx, 17, 1.05)], .2, steel)

    # Manifold assembly with flanges and bolts, valve stems and real pipe supports.
    pipe_y = 10
    curve("Water supply header", [(51, pipe_y, 1.1), (22, pipe_y, 1.1), (20, pipe_y - 2, 1.1), (12, pipe_y - 2, 1.1)], .26, iron)
    for tx in [23, 29, 35, 41, 47]:
        curve("Branch supply pipe", [(tx, pipe_y, 1.1), (tx, 17, 1.1), (tx, 17, 1.8)], .17, steel)
        cube("Concrete pipe support", (tx, pipe_y, .36), (.9, 1.1, .7), soil, .035)
        valve = cylinder("Flanged isolation valve", (tx, 13.2, 1.1), .39, .65, blue, 24)
        valve.rotation_euler.x = math.pi / 2
        for y in [12.85, 13.55]:
            flange = cylinder("Bolted flange", (tx, y, 1.1), .47, .10, steel, 24)
            flange.rotation_euler.x = math.pi / 2
            for i in range(8):
                angle = i * math.tau / 8
                bolt = cylinder("Flange bolt", (tx + .37 * math.cos(angle), y - .07, 1.1 + .37 * math.sin(angle)), .043, .11, iron, 6)
                bolt.rotation_euler.x = math.pi / 2
        beam("Valve stem", (tx, 13.2, 1.35), (tx, 13.2, 2.2), .06, steel)
        bpy.ops.mesh.primitive_torus_add(major_radius=.36, minor_radius=.035, major_segments=24, minor_segments=8, location=(tx, 13.2, 2.2))
        assign(bpy.context.object, ochre)
        bpy.context.object.name = "Industrial valve handwheel"
    # Pump motors, service cabin and corrugated enclosures.
    for tx in [18, 22, 26]:
        cube("Pump skid frame", (tx, 4, .45), (3.4, 2.4, .45), blue, .035)
        motor = cylinder("Finned pump motor", (tx, 4, 1.4), .65, 2.5, iron, 32)
        motor.rotation_euler.x = math.pi / 2
        for i in range(12):
            ring = cylinder("Motor cooling fin", (tx, 3 + i * .17, 1.4), .69, .035, steel, 24)
            ring.rotation_euler.x = math.pi / 2
        curve("Pump elbow", [(tx, 5.6, 1.4), (tx, 6.6, 1.4), (tx, 7, .9), (tx, 10, .9)], .16, steel)
    cube("Weathered control cabin", (-2, 26, 2.15), (12, 4.5, 4.1), pale, .06)
    cube("Cabin roof lip", (-2, 26, 4.27), (12.3, 4.8, .18), iron)
    for x in [-6, -3, 0, 3]:
        cube("Control cabin glazing", (x, 23.73, 2.7), (1.5, .045, 1.25), glass, .04)
    for i in range(32):
        cube("Corrugated cabin wall", (-7.8 + i * .37, 28.27, 2.15), (.045, .05, 3.9), steel, .008)
    for tx, ty in [(2, 9), (16, 14), (32, 18), (47, 18)]:
        beam("Service light mast", (tx, ty, .2), (tx, ty, 7.6), .07, steel)
        beam("Lamp cantilever", (tx, ty, 7.6), (tx + .8, ty - .35, 7.6), .045, steel)
        cube("Practical work light", (tx + .8, ty - .35, 7.5), (.7, .35, .16), light, .05)

    # Large geological section; first surface shot conceals all subsurface assets.
    wy = -6.38
    points = [(9, wy, -.1), (9, wy, -28)]
    points += [(9 + 9 * (1 - math.cos(math.pi / 2 * i / 40)), wy, -28 - 9 * math.sin(math.pi / 2 * i / 40)) for i in range(1, 41)]
    points.append((68, wy, -37))
    curve("Actual scale well casing exposed by cut", points, .28, steel)
    curve("Subtle reflected water inside casing", [(x, y - .25, z) for x, y, z in points], .075, water)
    for z in range(-2, -28, -2):
        cylinder("Well casing threaded coupling", (9, wy, z), .33, .16, iron, 24)
    for x in [27, 36, 45, 54, 63]:
        for sign in [-1, 1]:
            branch = [(x, wy - .27, -37), (x - .3, wy - .29, -37 + sign * 1.8),
                      (x + .2, wy - .3, -37 + sign * 3.8), (x - .6, wy - .31, -37 + sign * 6.3)]
            curve("Reservoir water fissure", branch, .045, water)
    world = bpy.data.worlds.new("Physical Patagonian dawn sky")
    world.use_nodes = True
    nodes = world.node_tree.nodes
    sky = nodes.new("ShaderNodeTexSky")
    sky.sky_type = "NISHITA"
    sky.sun_elevation = math.radians(14)
    sky.sun_rotation = math.radians(125)
    sky.altitude = .7
    sky.air_density = 1
    sky.dust_density = 1.5
    sky.ozone_density = 1
    world.node_tree.links.new(sky.outputs["Color"], nodes["Background"].inputs["Color"])
    nodes["Background"].inputs["Strength"].default_value = .42
    bpy.context.scene.world = world
    bpy.ops.object.camera_add(location=(48, -67, 3.5))
    camera = bpy.context.object
    camera.name = "Human height cinematic camera"
    camera.data.lens = 40
    camera.data.sensor_width = 36
    camera.data.clip_end = 1200
    camera.data.shift_x = -.10
    camera.data.dof.use_dof = True
    camera.data.dof.focus_distance = 83
    camera.data.dof.aperture_fstop = 11
    camera.rotation_euler = (Vector((20, 18, 10)) - camera.location).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = camera
    scene = bpy.context.scene
    scene["asset_note"] = "Full-scale industrial visualization, illustrative subsurface cutaway."
    scene["frames"] = count
    for image in bpy.data.images:
        if image.source == "FILE" and not image.packed_file:
            image.pack()


def build(count):
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for block in (bpy.data.meshes, bpy.data.curves, bpy.data.materials, bpy.data.cameras, bpy.data.lights):
        for item in list(block):
            if item.users == 0:
                block.remove(item)

    steel = material("Weathered galvanized steel", "B6BBC0", .35, .75)
    enamel = material("Warm ivory industrial enamel", "D6D0C4", .42, .3)
    dark = material("Petroleum blue structural steel", "344954", .42, .68)
    rust = material("Safety ochre coating", "B86A3D", .5, .3)
    rubber = material("Pipe protective coating", "26333A", .66, .1)
    glass = material("Control room glazing", "3C5C66", .19, .45)
    water = material("Water exposed by section", "49A1B9", .19, .24, "3D9FBC")
    fracture = material("Water in reservoir fissures", "7BB7BF", .35, .08, "5399A6")
    soil = material("Dry Patagonian ground", "9B8F75", .95, 0, rock=.7)
    shrub_mat = material("Drought adapted low vegetation", "686E50", .98)
    rock_mats = [material("Weathered sandy overburden", "A89B7F", .98, rock=.8),
                 material("Fine sandstone formation", "B7A78C", .96, rock=1),
                 material("Ochre siltstone formation", "94765D", .98, rock=1.2),
                 material("Pale compact sediment", "ADA18D", .96, rock=.8),
                 material("Dark reservoir shale", "625B53", .98, rock=1.4)]
    geology(rock_mats)
    terrain("Upper surveyed terrain", (-8, 20, -4.08, 9), (90, 42), soil, ground_height)
    terrain("Continuous distant steppe", (-100, 110, 9, 150), (120, 95), soil,
            lambda x, y: .1 + max(0, y - 12) * .005 + .35 * math.sin(x * .095) * math.sin(y * .13)
            + max(0, y - 36) * .025 * (math.sin(x * .061) + math.sin(y * .035)))
    base = material("Unexposed rock in shadow", "4C5559", 1, rock=.4)
    terrain("Dark geological continuation", (-120, 120, -100, 140), (40, 40), base, lambda x, y: -9.35 + .08 * math.sin(x * .2))
    # A compact, correctly scaled working pad, edged gravel and an access road.
    cube("Compacted industrial working pad", (5.8, 2.4, .24), (22, 8.4, .22), soil, .15)
    road = material("Compacted access road", "756F61", .98, rock=.6)
    terrain("Access to the installation", (-1.2, 2.2, 6.6, 75), (6, 65), road,
            lambda x, y: .15 + max(0, y - 12) * .005 + .035 * math.sin(y * .13))
    for i in range(70):
        x, y = RNG.uniform(-7.5, 19.5), RNG.uniform(-3.8, 8.7)
        if -4.7 < x < 17 and -1.8 < y < 6.6:
            continue
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=1, location=(x, y, ground_height(x, y) + .08))
        shrub = bpy.context.object
        shrub.name = "Low steppe scrub"
        shrub.scale = (RNG.uniform(.13, .4), RNG.uniform(.14, .35), RNG.uniform(.08, .22))
        assign(shrub, shrub_mat)

    # Drilling rig: mast, diagonal steel braces, deck, stairs and handrails.
    rx, ry, rz = 1.2, .7, .45
    cube("Rig load bearing base", (rx, ry, rz + .3), (3.6, 2.7, .6), dark, .06)
    cube("Rig platform", (rx, ry, 1.45), (3.5, 2.7, .14), steel, .025)
    corners = [(-1.25, -.92), (1.25, -.92), (1.25, .92), (-1.25, .92)]
    for i, (dx, dy) in enumerate(corners):
        beam("Mast main chord", (rx + dx, ry + dy, 1.5), (rx + dx * .25, ry + dy * .25, 8.25), .062, enamel)
        nx, ny = corners[(i + 1) % 4]
        for level in range(6):
            z0, z1 = 1.55 + level * 1.08, 2.63 + level * 1.08
            s0, s1 = 1 - (z0 - 1.5) / 6.75 * .75, 1 - (z1 - 1.5) / 6.75 * .75
            beam("Mast diagonal bracing", (rx + dx * s0, ry + dy * s0, z0), (rx + nx * s1, ry + ny * s1, z1), .028, steel, 8)
            beam("Mast horizontal bracing", (rx + dx * s0, ry + dy * s0, z0), (rx + nx * s0, ry + ny * s0, z0), .032, enamel, 8)
    cube("Crown assembly", (rx, ry, 8.25), (1.05, .8, .27), rust)
    beam("Drill string", (rx, ry, .8), (rx, ry, 8.15), .035, steel)
    cylinder("Traveling block", (rx, ry, 5.15), .17, .62, rust)
    for side in [-1, 1]:
        for i in range(5):
            x = rx - 1.65 + i * .82
            beam("Deck handrail upright", (x, ry + side * 1.31, 1.48), (x, ry + side * 1.31, 2.25), .025, rust, 8)
        beam("Deck handrail", (rx - 1.65, ry + side * 1.31, 2.25), (rx + 1.65, ry + side * 1.31, 2.25), .025, rust, 8)
    for i in range(7):
        cube("Access stair", (rx - 2.6 + i * .14, ry, .42 + i * .145), (.5, .8, .11), steel, .008)
    beam("Stair handrail", (rx - 2.8, ry - .45, 1.3), (rx - 1.55, ry - .45, 2.35), .025, rust)
    # Control cabin with real windows, roof lip, ribs and equipment housings.
    cube("Operations cabin", (-2.2, 3.6, 1.3), (4.3, 2.3, 2.1), enamel, .045)
    cube("Cabin roof", (-2.2, 3.6, 2.4), (4.5, 2.5, .15), dark)
    for x in [-3.5, -2.3, -1.1]:
        cube("Recessed control glazing", (x, 2.427, 1.65), (.82, .028, .67), glass, .025)
    for i in range(13):
        cube("Cabin metal rib", (-4.2 + i * .32, 4.76, 1.3), (.028, .028, 1.85), steel, 0)
    cube("Electrical cabinet", (-4.2, .6, 1.04), (.85, .7, 1.35), dark)
    cube("Pump skid", (5.3, -.1, .65), (3.2, 1.7, .4), dark)
    for x in [4.5, 5.7, 6.6]:
        engine = cylinder("Pump motor", (x, -.1, 1.1), .3, .8, steel)
        engine.rotation_euler.y = math.pi / 2
        cube("Motor feet", (x, -.1, .9), (.65, .7, .12), rust)

    # Tanks include roof cones, weld bands, ladders, service pipes and inlet valves.
    for tx in [8.1, 11.4, 14.7]:
        ty = 3.7
        cylinder("Tank foundation", (tx, ty, .47), 1.36, .25, dark, 48)
        cylinder("Water storage tank", (tx, ty, 1.9), 1.21, 2.65, enamel, 48)
        cylinder("Tank roof", (tx, ty, 3.34), 1.22, .27, steel, 48, .1)
        for z in [1, 2, 2.75]:
            cylinder("Welded tank seam", (tx, ty, z), 1.222, .035, steel, 48)
        beam("Roof breather", (tx, ty, 3.45), (tx, ty, 3.78), .085, steel)
        for dx in [-.21, .21]:
            beam("Service ladder rail", (tx + dx, ty - 1.28, .58), (tx + dx, ty - 1.28, 3.35), .022, dark)
        for rung in range(11):
            beam("Ladder rung", (tx - .21, ty - 1.28, .65 + rung * .25), (tx + .21, ty - 1.28, .65 + rung * .25), .018, steel, 8)
        curve("Tank outlet", [(tx, ty - 1.17, .85), (tx, 1.8, .85), (tx, 1.55, .65)], .1, steel)
    curve("Main supply manifold", [(15, 1.55, .65), (7, 1.55, .65), (6.3, .2, .65), (3.4, -.8, .65), (1.2, -.8, .65)], .13, rubber)
    for tx in [8.1, 11.4, 14.7]:
        cylinder("Manifold isolation valve", (tx, 1.55, .81), .16, .24, rust)
        bpy.ops.mesh.primitive_torus_add(major_radius=.22, minor_radius=.025, major_segments=16, minor_segments=6, location=(tx, 1.55, 1.02))
        assign(bpy.context.object, dark)
        bpy.context.object.name = "Valve handwheel"

    # Well geometry is exposed by the geological cut, with a broad heel radius.
    wy = -4.32
    points = [(1.2, wy, .7), (1.2, wy, -4.65)]
    for i in range(1, 25):
        theta = math.pi / 2 * i / 24
        points.append((1.2 + 2.1 * (1 - math.cos(theta)), wy, -4.65 - 2.1 * math.sin(theta)))
    points.append((17.5, wy, -6.75))
    curve("Continuous steel well casing", points, .15, rubber)
    curve("Visible water path in section", [(x, y - .14, z) for x, y, z in points], .057, water)
    curve("Wellhead connection", [(rx, ry, .85), (rx, -.9, .85), (rx, -3.2, .85), (rx, wy, .7)], .12, steel)
    for z in [.2 - .65 * i for i in range(8)]:
        cylinder("Casing coupling", (1.2, wy, z), .18, .075, steel, 16)
    for stage, x in enumerate([5.5, 8, 10.5, 13, 15.5]):
        for direction in [-1, 1]:
            z0 = -6.75
            spread = 1.1 if direction < 0 else 1.65
            branch = [(x, wy - .17, z0), (x - .12, wy - .18, z0 + direction * .45),
                      (x + .12, wy - .19, z0 + direction * .92), (x - .18, wy - .18, z0 + direction * spread)]
            curve("Water-bearing fracture", branch, .025, fracture)
            for fork in [1, 2]:
                bx, by, bz = branch[fork]
                dx = (-1 if fork == 1 else 1) * (.4 + stage * .018)
                curve("Secondary reservoir fissure", [(bx, by, bz), (bx + dx, by - .01, bz + direction * .24),
                                                       (bx + dx * 1.45, by - .01, bz + direction * .5)], .012, fracture)
        collar = cylinder("Completion stage sleeve", (x, wy, -6.75), .19, .2, steel, 18)
        collar.rotation_euler.y = math.pi / 2

    # Practical light: cool open sky, broad soft key and warm low sun.
    world = bpy.data.worlds.new("Blue hour Patagonian sky") if not bpy.data.worlds else bpy.data.worlds[0]
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = srgb_hex("859BAB")
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = .42
    bpy.context.scene.world = world
    bpy.ops.object.light_add(type="SUN", location=(-20, -30, 35))
    sun = bpy.context.object
    sun.name = "Late afternoon sun"
    sun.data.energy = 2.3
    sun.data.angle = math.radians(12)
    sun.rotation_euler = (math.radians(28), math.radians(-24), math.radians(-32))
    bpy.ops.object.light_add(type="AREA", location=(1, -22, 19))
    soft = bpy.context.object
    soft.name = "Broad sky reflection"
    soft.data.energy = 2200
    soft.data.shape = "DISK"
    soft.data.size = 22
    soft.rotation_euler = (Vector((7, 0, -2)) - soft.location).to_track_quat("-Z", "Y").to_euler()
    bpy.ops.object.camera_add()
    camera = bpy.context.object
    camera.name = "Continuous journey camera"
    camera.data.sensor_width = 36
    camera.data.clip_end = 500
    camera.data.shift_x = -.16
    camera.data.dof.use_dof = False
    bpy.context.scene.camera = camera
    animate_camera(camera, count)
    scene = bpy.context.scene
    scene["asset_note"] = "Illustrative industrial and geological scene; not a physical fluid or fracture simulation."
    scene["generation_seed"] = 38411
    scene["frames"] = count


STOPS = [
    ((28, -40, 18), (5.5, 1.2, 1.5), 49),
    ((25, -36, 7.0), (6, -.5, -2.1), 49),
    ((23, -31, .6), (8.8, -2.2, -5.2), 51),
    ((20, -27, -.2), (11.3, -3.8, -6.3), 54),
    ((35, -46, 21), (6.5, .1, -1.5), 48),
]

REALISTIC_STOPS = [
    ((110, -2, 3.7), (18, 20, 8), 43),
    ((91, -50, 9), (27, -1, -6), 43),
    ((87, -76, -10), (33, -6, -25), 45),
    ((85, -69, -25), (43, -6, -36), 48),
    ((175, -132, 64), (29, 9, -5), 40),
]


def catmull(values, position):
    segment = min(len(values) - 2, int(position))
    t = position - segment
    a, b, c, d = [Vector(values[max(0, min(len(values) - 1, segment + k))]) for k in [-1, 0, 1, 2]]
    return .5 * ((2 * b) + (-a + c) * t + (2 * a - 5 * b + 4 * c - d) * t * t + (-a + 3 * b - 3 * c + d) * t * t * t)


def animate_camera(camera, count):
    camera.animation_data_clear()
    camera.data.animation_data_clear()
    camera.rotation_mode = "QUATERNION"
    poses = []
    for index in range(count):
        p = index / max(1, count - 1) * (len(STOPS) - 1)
        eye = catmull([s[0] for s in STOPS], p)
        look = catmull([s[1] for s in STOPS], p)
        segment = min(len(STOPS) - 2, int(p))
        f = p - segment
        camera.location = eye
        camera.rotation_quaternion = (look - eye).to_track_quat("-Z", "Y")
        camera.data.lens = STOPS[segment][2] * (1 - f) + STOPS[segment + 1][2] * f
        frame = index + 1
        camera.keyframe_insert("location", frame=frame)
        camera.keyframe_insert("rotation_quaternion", frame=frame)
        camera.data.keyframe_insert("lens", frame=frame)
        poses.append({"frame": index, "progress": index / max(1, count - 1), "position": list(eye), "target": list(look), "lens": camera.data.lens})
    name = "camera.json" if count == 60 else f"camera-{count}.json"
    (OUT / name).write_text(json.dumps(poses, indent=2), encoding="utf-8")


def animate_realistic(count):
    scene = bpy.context.scene
    camera = scene.camera
    camera.animation_data_clear()
    camera.data.animation_data_clear()
    camera.rotation_mode = "QUATERNION"
    camera.data.shift_x = -.24
    improve_geological_face()
    # Weathered tank steel retains highlight detail instead of white enamel glare.
    tank = bpy.data.materials.get("Weathered tank off-white enamel")
    if tank:
        bsdf = tank.node_tree.nodes.get("Principled BSDF")
        bsdf.inputs["Metallic"].default_value = .68
        bsdf.inputs["Roughness"].default_value = .46
        for node in tank.node_tree.nodes:
            if node.type == "VALTORGB":
                color = srgb_hex("96A0A0")
                node.color_ramp.elements[0].color = tuple(c * .5 for c in color[:3]) + (1,)
                node.color_ramp.elements[1].color = color
    foreground = bpy.data.objects.get("Foreground ground before cutaway")
    mat = foreground.data.materials[0]
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    blend = nodes.get("Geological reveal")
    if not blend:
        blend = nodes.new("ShaderNodeMixShader")
        blend.name = "Geological reveal"
        transparent = nodes.new("ShaderNodeBsdfTransparent")
        links.new(transparent.outputs[0], blend.inputs[1])
        links.new(nodes.get("Principled BSDF").outputs[0], blend.inputs[2])
        links.new(blend.outputs[0], nodes.get("Material Output").inputs["Surface"])
    mat.node_tree.animation_data_clear()
    rock_visibility = []
    for i in range(6):
        rock_mat = bpy.data.materials.get(f"Photographic fractured cliff layer {i}")
        nodes, links = rock_mat.node_tree.nodes, rock_mat.node_tree.links
        visibility = nodes.get("Surface cutaway visibility")
        if not visibility:
            visibility = nodes.new("ShaderNodeMixShader")
            visibility.name = "Surface cutaway visibility"
            transparent = nodes.new("ShaderNodeBsdfTransparent")
            links.new(transparent.outputs[0], visibility.inputs[1])
            links.new(nodes.get("Principled BSDF").outputs[0], visibility.inputs[2])
            links.new(visibility.outputs[0], nodes.get("Material Output").inputs["Surface"])
        rock_mat.node_tree.animation_data_clear()
        rock_visibility.append(visibility)
    poses = []
    for index in range(count):
        progress = index / max(1, count - 1)
        p = progress * 4
        eye = catmull([s[0] for s in REALISTIC_STOPS], p)
        look = catmull([s[1] for s in REALISTIC_STOPS], p)
        segment = min(3, int(p))
        f = p - segment
        camera.location = eye
        camera.rotation_quaternion = (look - eye).to_track_quat("-Z", "Y")
        camera.data.lens = REALISTIC_STOPS[segment][2] * (1 - f) + REALISTIC_STOPS[segment + 1][2] * f
        camera.data.dof.focus_distance = (look - eye).length
        frame = index + 1
        camera.keyframe_insert("location", frame=frame)
        camera.keyframe_insert("rotation_quaternion", frame=frame)
        camera.data.keyframe_insert("lens", frame=frame)
        camera.data.dof.keyframe_insert("focus_distance", frame=frame)
        reveal = max(0, min(1, (progress - .1) / .2))
        blend.inputs[0].default_value = 1 - reveal * reveal * (3 - 2 * reveal)
        blend.inputs[0].keyframe_insert("default_value", frame=frame)
        for visibility in rock_visibility:
            visibility.inputs[0].default_value = reveal * reveal * (3 - 2 * reveal)
            visibility.inputs[0].keyframe_insert("default_value", frame=frame)
        poses.append({"frame": index, "progress": progress, "position": list(eye), "target": list(look), "lens": camera.data.lens})
    name = "camera.json" if count == 60 else f"camera-{count}.json"
    (OUT / name).write_text(json.dumps(poses, indent=2), encoding="utf-8")


def improve_geological_face():
    """Continuous weathered rock with photographed fissures, not smooth bands."""
    landscape = bpy.data.objects.get("Extensive steppe landscape")
    if not landscape.get("extended_horizon"):
        for vertex in landscape.data.vertices:
            if vertex.co.x < -160:
                vertex.co.x = -160 + (vertex.co.x + 160) * 10
            elif vertex.co.x > 160:
                vertex.co.x = 160 + (vertex.co.x - 160) * 10
            if vertex.co.y > 120:
                vertex.co.y = 120 + (vertex.co.y - 120) * 10
        landscape.data.update()
        landscape["extended_horizon"] = True
    depths = [.04, -7, -17, -28, -36, -52, -400]
    tints = [(1.0, .98, .9), (1.04, .95, .81), (.83, .69, .59),
             (1.08, 1.02, .92), (.58, .64, .65), (.47, .51, .52)]
    for layer in range(6):
        obj = bpy.data.objects.get(f"Continuous deep formation {layer}")
        if not obj:
            continue
        material_name = f"Photographic fractured cliff layer {layer}"
        mat = bpy.data.materials.get(material_name)
        if not mat:
            mat = pbr_material(material_name, "cliff_side", .09)
            nodes, links = mat.node_tree.nodes, mat.node_tree.links
            bsdf = nodes.get("Principled BSDF")
            source = bsdf.inputs["Base Color"].links[0].from_socket
            tint = nodes.new("ShaderNodeMixRGB")
            tint.blend_type = "MULTIPLY"
            tint.inputs[0].default_value = 1
            tint.inputs[2].default_value = (*tints[layer], 1)
            links.new(source, tint.inputs[1])
            links.new(tint.outputs[0], bsdf.inputs["Base Color"])
        verts, faces = [], []
        nx, nz = 600, 18
        for j in range(nz + 1):
            v = j / nz
            for i in range(nx + 1):
                x = -2200 + 4600 * i / nx
                upper = depths[layer] if layer == 0 else depths[layer] + math.sin(x * .07) * .85
                lower = depths[layer + 1] + math.sin(x * .07) * .85
                z = upper * (1 - v) + lower * v
                rough = noise.noise(Vector((x * .16, z * .23, 4.2))) * .65
                rough += noise.noise(Vector((x * .75, z * .82, 2.8))) * .16
                y = -5.38 + rough
                verts.append((x, y, z))
        for j in range(nz):
            for i in range(nx):
                a = j * (nx + 1) + i
                faces.append((a, a + nx + 1, a + nx + 2, a + 1))
        data = bpy.data.meshes.new(f"Weathered geological relief {layer}")
        data.from_pydata(verts, [], faces)
        data.update()
        uv = data.uv_layers.new(name="UVMap")
        for polygon in data.polygons:
            polygon.use_smooth = True
            for loop in polygon.loop_indices:
                vertex = data.vertices[data.loops[loop].vertex_index].co
                uv.data[loop].uv = (vertex.x * .09, vertex.z * .09)
        previous = obj.data
        obj.data = data
        assign(obj, mat)
        if previous.users == 0:
            bpy.data.meshes.remove(previous)
    # Retain the same five completion stages, adding only physically small forks.
    if not bpy.data.objects.get("Reservoir fine fissure"):
        water = bpy.data.materials.get("Water reflection in section")
        for x in [27, 36, 45, 54, 63]:
            for direction in [-1, 1]:
                for depth, side in [(1.8, -1), (3.8, 1)]:
                    z = -37 + direction * depth
                    curve("Reservoir fine fissure", [(x, -6.68, z), (x + side * 1.2, -6.7, z + direction * .9),
                          (x + side * 1.9, -6.7, z + direction * 1.9)], .025, water)


def configure(options):
    scene = bpy.context.scene
    if options.engine == "CYCLES":
        scene.render.engine = "CYCLES"
        scene.cycles.device = "CPU"
        scene.cycles.samples = options.samples
        scene.cycles.use_denoising = True
        scene.cycles.use_adaptive_sampling = True
        scene.cycles.adaptive_threshold = .07
        scene.cycles.max_bounces = 6
        scene.cycles.diffuse_bounces = 3
        scene.cycles.glossy_bounces = 3
        scene.cycles.transmission_bounces = 4
    else:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
        scene.eevee.taa_render_samples = options.samples
    scene.render.resolution_x = options.width
    scene.render.resolution_y = options.height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.image_settings.color_depth = "8"
    scene.render.image_settings.compression = 30
    scene.render.film_transparent = False
    scene.render.fps = 24
    scene.frame_start = 1
    scene.frame_end = options.frames
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.view_settings.exposure = -.85 if options.realistic else 0
    scene.render.use_file_extension = True


def export_manifest(options):
    scene = bpy.context.scene
    if options.realistic:
        points = [Vector((9, -6.63, -.1)), Vector((9, -6.63, -28))]
        for i in range(1, 41):
            angle = math.pi / 2 * i / 40
            points.append(Vector((9 + 9 * (1 - math.cos(angle)), -6.63, -28 - 9 * math.sin(angle))))
        points.append(Vector((68, -6.63, -37)))
    else:
        points = [Vector((1.2, -4.46, .7)), Vector((1.2, -4.46, -4.65))]
        for i in range(1, 25):
            angle = math.pi / 2 * i / 24
            points.append(Vector((1.2 + 2.1 * (1 - math.cos(angle)), -4.46, -4.65 - 2.1 * math.sin(angle))))
        points.append(Vector((17.5, -4.46, -6.75)))
    distances = [0]
    for previous, current in zip(points, points[1:]):
        distances.append(distances[-1] + (current - previous).length)
    samples = []
    for i in range(24):
        target = distances[-1] * i / 23
        segment = next((j for j in range(len(distances) - 1) if distances[j + 1] >= target), len(distances) - 2)
        t = (target - distances[segment]) / (distances[segment + 1] - distances[segment])
        samples.append(points[segment].lerp(points[segment + 1], t))
    frames = []
    for index in range(options.frames):
        scene.frame_set(index + 1)
        bpy.context.view_layer.update()
        projected = [world_to_camera_view(scene, scene.camera, point) for point in samples]
        progress = index / max(1, options.frames - 1)
        reveal = max(0, min(1, (progress - .15) / .17)) if options.realistic else 1
        frames.append({"index": index, "progress": round(progress, 6),
                       "waterOpacity": round(reveal * reveal * (3 - 2 * reveal), 6),
                       "waterPath2D": [[round(point.x, 6), round(1 - point.y, 6)] for point in projected]})
    suffix = "" if options.frames == 60 else f"-{options.frames}"
    frame_folder = f"frames{suffix}"
    blend_name = f"{BLEND.stem}{suffix}.blend"
    manifest = {"version": "patagonia-blender-v3" if options.realistic else "patagonia-blender-v1", "frameCount": options.frames, "fps": 24,
                "width": options.width, "height": options.height,
                "pattern": frame_folder + "/frame-{frame:04d}.png", "poster": frame_folder + "/frame-0000.png",
                "source": blend_name, "renderer": "Blender 4.5 " + options.engine, "samples": options.samples,
                "coordinateSystem": "normalized image UV, origin top-left; out-of-frame coordinates retained",
                "keyposes": [{"name": name, "progress": i / 4, "index": round((options.frames - 1) * i / 4)}
                             for i, name in enumerate(["surface", "geology", "lateral", "water", "overview"])],
                "frames": frames}
    (OUT / f"manifest{suffix}.json").write_text(json.dumps(manifest, separators=(",", ":")), encoding="utf-8")


def main():
    global OUT, BLEND
    options = args()
    if options.realistic:
        OUT = OUT / "v3"
        BLEND = OUT / "patagonia-realistic.blend"
    OUT.mkdir(parents=True, exist_ok=True)
    begin = time.perf_counter()
    suffix = "" if options.frames == 60 else f"-{options.frames}"
    output_blend = OUT / f"{BLEND.stem}{suffix}.blend"
    if options.existing and BLEND.exists():
        bpy.ops.wm.open_mainfile(filepath=str(output_blend if output_blend.exists() else BLEND))
        if not options.realistic:
            animate_camera(bpy.context.scene.camera, options.frames)
        bpy.context.scene["frames"] = options.frames
    else:
        if options.realistic:
            build_realistic(options.frames)
        else:
            build(options.frames)
    configure(options)
    if options.realistic:
        animate_realistic(options.frames)
    export_manifest(options)
    bpy.context.scene.frame_set(1)
    if options.realistic:
        for image in bpy.data.images:
            if image.source == "FILE" and not image.packed_file:
                image.pack()
    bpy.ops.wm.save_as_mainfile(filepath=str(output_blend))
    if options.mode == "first":
        indices, folder = [0], OUT / f"previews{suffix}"
    elif options.mode == "previews":
        indices, folder = sorted({0, round((options.frames - 1) * .25), round((options.frames - 1) * .5), round((options.frames - 1) * .75), options.frames - 1}), OUT / f"previews{suffix}"
    else:
        indices, folder = range(options.frames), OUT / f"frames{suffix}"
    if options.only_frame is not None:
        if not 0 <= options.only_frame < options.frames:
            raise ValueError("only-frame must be within frameCount")
        indices = [options.only_frame]
    folder.mkdir(exist_ok=True)
    timings = []
    for index in indices:
        start = time.perf_counter()
        bpy.context.scene.frame_set(index + 1)
        path = folder / f"frame-{index:04d}.png"
        bpy.context.scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        elapsed = time.perf_counter() - start
        timings.append({"frame": index, "seconds": round(elapsed, 3), "file": str(path)})
        print("JOURNEY_RENDER " + json.dumps(timings[-1]), flush=True)
    manifest = {"version": "patagonia-blender-v3" if options.realistic else "patagonia-blender-v1",
                "source": output_blend.name, "renderer": "Blender 4.5 " + options.engine,
                "width": options.width, "height": options.height, "samples": options.samples,
                "frameCount": options.frames, "mode": options.mode, "timings": timings,
                "elapsedSeconds": round(time.perf_counter() - begin, 3)}
    (OUT / f"render-{options.mode}{suffix}.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("JOURNEY_DONE " + json.dumps(manifest), flush=True)


if __name__ == "__main__":
    main()
