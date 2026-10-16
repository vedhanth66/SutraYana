"""Blender Headless Builder script.
Invoked inside Blender via:
  blender --background --python tools/blender_builder.py -- --input payload.json --output model.blend [--render preview.png]
"""

import sys
import json
import math
from pathlib import Path

# Only import bpy if running inside Blender
try:
    import bpy
    import mathutils
except ImportError:
    bpy = None


def parse_cli_args():
    """Parse arguments passed after '--' in Blender's command line."""
    argv = sys.argv
    if "--" in argv:
        args = argv[argv.index("--") + 1:]
    else:
        args = []

    parsed = {
        "input": None,
        "output": None,
        "render": None,
        "glb": None,
        "top_render": None,
        "wall_height": 1.4,
        "floor_thickness": 0.05,
    }

    it = iter(args)
    for arg in it:
        if arg == "--input":
            parsed["input"] = next(it, None)
        elif arg == "--output":
            parsed["output"] = next(it, None)
        elif arg == "--render":
            parsed["render"] = next(it, None)
        elif arg == "--glb":
            parsed["glb"] = next(it, None)
        elif arg == "--top-render":
            parsed["top_render"] = next(it, None)
        elif arg == "--wall-height":
            parsed["wall_height"] = float(next(it, 1.4))
        elif arg == "--floor-thickness":
            parsed["floor_thickness"] = float(next(it, 0.05))

    return parsed


def get_or_create_collection(name, parent_coll=None):
    """Retrieve or create a collection under a parent collection."""
    if name in bpy.data.collections:
        coll = bpy.data.collections[name]
    else:
        coll = bpy.data.collections.new(name)
        if parent_coll is None:
            bpy.context.scene.collection.children.link(coll)
        else:
            parent_coll.children.link(coll)
    return coll


def create_pbr_material(name, color_rgba, roughness=0.4, metallic=0.0, transmission=0.0, emission_color=None, emission_strength=0.0):
    """Create a Principled BSDF material with specified physical properties."""
    if name in bpy.data.materials:
        return bpy.data.materials[name]

    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        if "Base Color" in bsdf.inputs:
            bsdf.inputs["Base Color"].default_value = color_rgba
        if "Roughness" in bsdf.inputs:
            bsdf.inputs["Roughness"].default_value = roughness
        if "Metallic" in bsdf.inputs:
            bsdf.inputs["Metallic"].default_value = metallic
        if "Transmission Weight" in bsdf.inputs:
            bsdf.inputs["Transmission Weight"].default_value = transmission
        elif "Transmission" in bsdf.inputs:
            bsdf.inputs["Transmission"].default_value = transmission
        if emission_color and "Emission Color" in bsdf.inputs:
            bsdf.inputs["Emission Color"].default_value = emission_color
            if "Emission Strength" in bsdf.inputs:
                bsdf.inputs["Emission Strength"].default_value = emission_strength

    mat.diffuse_color = color_rgba
    return mat


def setup_materials():
    """Create architectural and MEP infrastructure PBR materials palette."""
    palette = {
        "Mat_Wall": create_pbr_material("Mat_Wall", (0.95, 0.95, 0.95, 1.0), roughness=0.55),
        "Mat_Plinth": create_pbr_material("Mat_Plinth", (0.86, 0.87, 0.88, 1.0), roughness=0.75),
        "living": create_pbr_material("Mat_Floor_Living", (0.72, 0.54, 0.38, 1.0), roughness=0.35),
        "bedroom": create_pbr_material("Mat_Floor_Bedroom", (0.42, 0.56, 0.70, 1.0), roughness=0.42),
        "kitchen": create_pbr_material("Mat_Floor_Kitchen", (0.46, 0.64, 0.50, 1.0), roughness=0.28),
        "bathroom": create_pbr_material("Mat_Floor_Bathroom", (0.48, 0.68, 0.78, 1.0), roughness=0.20),
        "storage": create_pbr_material("Mat_Floor_Storage", (0.48, 0.48, 0.52, 1.0), roughness=0.50),
        "balcony": create_pbr_material("Mat_Floor_Balcony", (0.58, 0.50, 0.42, 1.0), roughness=0.65),
        "default": create_pbr_material("Mat_Floor_Default", (0.65, 0.65, 0.68, 1.0), roughness=0.40),

        # Phase 2: Openings & Terminals
        "Mat_Window_Frame": create_pbr_material("Mat_Window_Frame", (0.14, 0.15, 0.17, 1.0), roughness=0.25, metallic=0.85),
        "Mat_Window_Glass": create_pbr_material("Mat_Window_Glass", (0.70, 0.85, 0.96, 0.45), roughness=0.05, transmission=0.88),
        "Mat_Door_Threshold": create_pbr_material("Mat_Door_Threshold", (0.28, 0.22, 0.18, 1.0), roughness=0.45, metallic=0.40),
        "Mat_Door_Wood": create_pbr_material("Mat_Door_Wood", (0.68, 0.52, 0.38, 1.0), roughness=0.38),
        "Mat_Terminal_Base": create_pbr_material("Mat_Terminal_Base", (0.18, 0.20, 0.24, 1.0), roughness=0.22, metallic=0.90),
        "Mat_Terminal_Glow": create_pbr_material(
            "Mat_Terminal_Glow",
            (0.0, 0.85, 1.0, 1.0),
            roughness=0.1,
            emission_color=(0.0, 0.85, 1.0, 1.0),
            emission_strength=5.0,
        ),
        "Mat_Terminal_Text": create_pbr_material(
            "Mat_Terminal_Text",
            (0.95, 1.0, 1.0, 1.0),
            roughness=0.1,
            emission_color=(0.95, 1.0, 1.0, 1.0),
            emission_strength=3.0,
        ),

        # Phase 3: Hub Infrastructure & Cable Conduit Circuits
        "Mat_Hub_Base": create_pbr_material("Mat_Hub_Base", (0.16, 0.18, 0.22, 1.0), roughness=0.20, metallic=0.90),
        "Mat_Hub_Cabinet": create_pbr_material("Mat_Hub_Cabinet", (0.12, 0.13, 0.15, 1.0), roughness=0.35, metallic=0.75),
        "Mat_Hub_LED_Power": create_pbr_material(
            "Mat_Hub_LED_Power",
            (0.0, 0.90, 0.45, 1.0),
            roughness=0.1,
            emission_color=(0.0, 0.90, 0.45, 1.0),
            emission_strength=6.0,
        ),
        "Mat_Hub_LED_Port": create_pbr_material(
            "Mat_Hub_LED_Port",
            (0.0, 0.75, 1.0, 1.0),
            roughness=0.1,
            emission_color=(0.0, 0.75, 1.0, 1.0),
            emission_strength=5.0,
        ),
        "Mat_Hub_Text": create_pbr_material(
            "Mat_Hub_Text",
            (1.0, 0.75, 0.15, 1.0),
            roughness=0.1,
            emission_color=(1.0, 0.75, 0.15, 1.0),
            emission_strength=3.5,
        ),

        # Circuit Conduits (Architectural Matte Black MEP Conduits)
        "Mat_Cable_1": create_pbr_material("Mat_Cable_Circuit_1", (0.10, 0.11, 0.13, 1.0), roughness=0.35, metallic=0.20),
        "Mat_Cable_2": create_pbr_material("Mat_Cable_Circuit_2", (0.10, 0.11, 0.13, 1.0), roughness=0.35, metallic=0.20),
        "Mat_Cable_3": create_pbr_material("Mat_Cable_Circuit_3", (0.10, 0.11, 0.13, 1.0), roughness=0.35, metallic=0.20),
        "Mat_Cable_4": create_pbr_material("Mat_Cable_Circuit_4", (0.10, 0.11, 0.13, 1.0), roughness=0.35, metallic=0.20),
    }
    return palette


def create_extruded_polygon_mesh(name, exterior_coords, interiors_coords, height, z_bottom, target_coll):
    """Extrude a 2D polygon with optional holes to a 3D mesh."""
    curve_data = bpy.data.curves.new(name=f"Curve_{name}", type="CURVE")
    curve_data.dimensions = "2D"
    curve_data.fill_mode = "BOTH"
    curve_data.extrude = height / 2.0

    # Exterior ring
    pts = exterior_coords[:-1] if (len(exterior_coords) > 1 and exterior_coords[0] == exterior_coords[-1]) else exterior_coords
    if len(pts) < 3:
        return None

    s_out = curve_data.splines.new("POLY")
    s_out.points.add(len(pts) - 1)
    for i, (x, y) in enumerate(pts):
        s_out.points[i].co = (float(x), float(y), 0.0, 1.0)
    s_out.use_cyclic_u = True

    # Interior rings (holes)
    for hole in interiors_coords:
        hpts = hole[:-1] if (len(hole) > 1 and hole[0] == hole[-1]) else hole
        if len(hpts) < 3:
            continue
        s_in = curve_data.splines.new("POLY")
        s_in.points.add(len(hpts) - 1)
        for i, (x, y) in enumerate(hpts):
            s_in.points[i].co = (float(x), float(y), 0.0, 1.0)
        s_in.use_cyclic_u = True

    obj = bpy.data.objects.new(name, curve_data)
    target_coll.objects.link(obj)

    # Convert to mesh
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.convert(target="MESH")

    # Shift vertices along Z so bottom is at z_bottom
    dz = z_bottom + (height / 2.0)
    for v in obj.data.vertices:
        v.co.z += dz

    return obj


def create_door_leaf_mesh(name, hx, hy, L, t, H, z0, angle_deg, coll):
    """Create a 3D door leaf oriented at angle_deg from hinge (hx, hy)."""
    theta = math.radians(angle_deg)
    cos_t, sin_t = math.cos(theta), math.sin(theta)

    verts = [
        (hx, hy, z0),
        (hx + L * cos_t, hy + L * sin_t, z0),
        (hx + L * cos_t - t * sin_t, hy + L * sin_t + t * cos_t, z0),
        (hx - t * sin_t, hy + t * cos_t, z0),
        (hx, hy, z0 + H),
        (hx + L * cos_t, hy + L * sin_t, z0 + H),
        (hx + L * cos_t - t * sin_t, hy + L * sin_t + t * cos_t, z0 + H),
        (hx - t * sin_t, hy + t * cos_t, z0 + H),
    ]
    faces = [
        (0, 3, 2, 1),
        (4, 5, 6, 7),
        (0, 1, 5, 4),
        (1, 2, 6, 5),
        (2, 3, 7, 6),
        (3, 0, 4, 7),
    ]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()

    obj = bpy.data.objects.new(name, mesh)
    coll.objects.link(obj)
    return obj


def build_scene(payload, wall_height=1.4, floor_thickness=0.05):
    """Assemble complete 3D digital twin scene in Blender."""
    # Reset scene to empty
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # Collections
    root_coll = get_or_create_collection("SutraYana_DigitalTwin")
    arch_coll = get_or_create_collection("Architecture", root_coll)
    floors_coll = get_or_create_collection("Floors", arch_coll)
    walls_coll = get_or_create_collection("Walls", arch_coll)
    windows_coll = get_or_create_collection("Windows", arch_coll)
    doors_coll = get_or_create_collection("Doors", arch_coll)
    base_coll = get_or_create_collection("Base", arch_coll)

    infra_coll = get_or_create_collection("Infrastructure", root_coll)
    hubs_coll = get_or_create_collection("Hubs", infra_coll)
    cables_coll = get_or_create_collection("Cables", infra_coll)

    fixtures_coll = get_or_create_collection("Fixtures", root_coll)
    terminals_coll = get_or_create_collection("Terminals", fixtures_coll)

    studio_coll = get_or_create_collection("Studio", root_coll)
    lighting_coll = get_or_create_collection("Lighting", studio_coll)
    camera_coll = get_or_create_collection("Cameras", studio_coll)

    # Materials
    materials = setup_materials()

    bounds = payload.get("bounds", [0, 0, 10, 10])
    w = bounds[2] - bounds[0]
    d = bounds[3] - bounds[1]
    diag = math.sqrt(w * w + d * d)

    # 1. Base Plinth (Foundation Slab)
    plinth_poly = [
        (-w / 2.0 - 0.8, -d / 2.0 - 0.8),
        (w / 2.0 + 0.8, -d / 2.0 - 0.8),
        (w / 2.0 + 0.8, d / 2.0 + 0.8),
        (-w / 2.0 - 0.8, d / 2.0 + 0.8),
    ]
    plinth_obj = create_extruded_polygon_mesh("Plinth_Foundation", plinth_poly, [], 0.08, -0.13, base_coll)
    if plinth_obj:
        plinth_obj.data.materials.append(materials["Mat_Plinth"])

    # 2. Rooms (Floor Slabs)
    rooms_data = payload.get("rooms", [])
    for room in rooms_data:
        rid = room.get("id", "Room")
        rtype = room.get("type", "default").lower()
        mat = materials.get(rtype, materials["default"])

        room_objs = []
        for p_idx, poly in enumerate(room.get("polygons", [])):
            name = f"Floor_{rid}" if p_idx == 0 else f"Floor_{rid}_{p_idx}"
            ext = poly.get("exterior", [])
            holes = poly.get("interiors", [])
            obj = create_extruded_polygon_mesh(name, ext, holes, floor_thickness, -floor_thickness, floors_coll)
            if obj:
                obj.data.materials.append(mat)
                room_objs.append(obj)

        if len(room_objs) > 1:
            bpy.ops.object.select_all(action="DESELECT")
            for o in room_objs:
                o.select_set(True)
            bpy.context.view_layer.objects.active = room_objs[0]
            bpy.ops.object.join()
            room_objs[0].name = f"Floor_{rid}"

    # 3. Walls
    walls_data = payload.get("walls", [])
    wall_objs = []
    for w_idx, poly in enumerate(walls_data):
        ext = poly.get("exterior", [])
        holes = poly.get("interiors", [])
        w_obj = create_extruded_polygon_mesh(f"Wall_Part_{w_idx}", ext, holes, wall_height, 0.0, walls_coll)
        if w_obj:
            wall_objs.append(w_obj)

    if wall_objs:
        bpy.ops.object.select_all(action="DESELECT")
        for o in wall_objs:
            o.select_set(True)
        bpy.context.view_layer.objects.active = wall_objs[0]
        bpy.ops.object.join()
        main_wall = wall_objs[0]
        main_wall.name = "Building_Walls"
        main_wall.data.materials.append(materials["Mat_Wall"])

    # 4. Windows (Phase 2)
    windows_data = payload.get("windows", [])
    for win_idx, poly in enumerate(windows_data):
        ext = poly.get("exterior", [])
        holes = poly.get("interiors", [])
        sill_obj = create_extruded_polygon_mesh(f"Window_Sill_{win_idx}", ext, holes, 0.45, 0.0, walls_coll)
        if sill_obj:
            sill_obj.data.materials.append(materials["Mat_Wall"])

        glass_height = min(0.80, max(0.40, wall_height - 0.45))
        glass_obj = create_extruded_polygon_mesh(f"Window_Glass_{win_idx}", ext, holes, glass_height, 0.45, windows_coll)
        if glass_obj:
            glass_obj.data.materials.append(materials["Mat_Window_Glass"])

    # 5. Doors (Phase 2)
    doors_data = payload.get("doors", [])
    for d_idx, poly in enumerate(doors_data):
        ext = poly.get("exterior", [])
        holes = poly.get("interiors", [])
        if not ext:
            continue

        thresh_obj = create_extruded_polygon_mesh(f"Door_Threshold_{d_idx}", ext, holes, 0.015, 0.0, doors_coll)
        if thresh_obj:
            thresh_obj.data.materials.append(materials["Mat_Door_Threshold"])

        xs = [pt[0] for pt in ext]
        ys = [pt[1] for pt in ext]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        dx = max_x - min_x
        dy = max_y - min_y

        leaf_height = min(1.25, wall_height * 0.88)
        if dx >= dy:
            door_len = max(0.6, dx * 0.90)
            leaf_obj = create_door_leaf_mesh(
                f"Door_Leaf_{d_idx}",
                hx=min_x + 0.02,
                hy=min_y,
                L=door_len,
                t=0.035,
                H=leaf_height,
                z0=0.015,
                angle_deg=45.0,
                coll=doors_coll,
            )
        else:
            door_len = max(0.6, dy * 0.90)
            leaf_obj = create_door_leaf_mesh(
                f"Door_Leaf_{d_idx}",
                hx=min_x,
                hy=min_y + 0.02,
                L=door_len,
                t=0.035,
                H=leaf_height,
                z0=0.015,
                angle_deg=135.0,
                coll=doors_coll,
            )
        if leaf_obj:
            leaf_obj.data.materials.append(materials["Mat_Door_Wood"])

    # 6. Terminals / Fixed Electrical Outlets (Phase 2)
    terminals_data = payload.get("terminals", [])
    for term in terminals_data:
        tid = term.get("id", "N")
        tx = term.get("x", 0.0)
        ty = term.get("y", 0.0)

        # Base station plate
        bpy.ops.mesh.primitive_cylinder_add(radius=0.18, depth=0.025, location=(tx, ty, 0.0125))
        base_obj = bpy.context.active_object
        base_obj.name = f"Terminal_Base_{tid}"
        base_obj.data.materials.append(materials["Mat_Terminal_Base"])
        bpy.context.scene.collection.objects.unlink(base_obj)
        terminals_coll.objects.link(base_obj)

        # Glowing core / status ring
        bpy.ops.mesh.primitive_cylinder_add(radius=0.11, depth=0.018, location=(tx, ty, 0.032))
        glow_obj = bpy.context.active_object
        glow_obj.name = f"Terminal_Glow_{tid}"
        glow_obj.data.materials.append(materials["Mat_Terminal_Glow"])
        bpy.context.scene.collection.objects.unlink(glow_obj)
        terminals_coll.objects.link(glow_obj)

        # 3D Floating text label
        font_curve = bpy.data.curves.new(f"Font_{tid}", type="FONT")
        font_curve.body = str(tid)
        font_curve.size = 0.24
        font_curve.align_x = "CENTER"
        font_curve.align_y = "CENTER"
        font_curve.extrude = 0.025

        text_obj = bpy.data.objects.new(f"Text_{tid}", font_curve)
        text_obj.location = (tx, ty, 0.22)
        text_obj.rotation_euler = (math.radians(35), 0, math.radians(-15))
        text_obj.data.materials.append(materials["Mat_Terminal_Text"])
        terminals_coll.objects.link(text_obj)
        # Convert font curve to real mesh so it exports cleanly in glTF/GLB
        bpy.context.view_layer.objects.active = text_obj
        text_obj.select_set(True)
        bpy.ops.object.convert(target="MESH")

    # 7. Hub Infrastructure Stations (Phase 3)
    hubs_data = payload.get("hubs", [])
    for h_idx, hub in enumerate(hubs_data):
        hid = hub.get("id", f"H{h_idx + 1}")
        hx = hub.get("x", 0.0)
        hy = hub.get("y", 0.0)

        # Hub floor mounting plinth
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(hx, hy, 0.015))
        h_plinth = bpy.context.active_object
        h_plinth.scale = (0.46, 0.36, 0.03)
        bpy.ops.object.transform_apply(scale=True)
        h_plinth.name = f"Hub_Plinth_{hid}"
        h_plinth.data.materials.append(materials["Mat_Hub_Base"])
        bpy.context.scene.collection.objects.unlink(h_plinth)
        hubs_coll.objects.link(h_plinth)

        # Main Server / Distribution Enclosure
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(hx, hy, 0.355))
        h_cab = bpy.context.active_object
        h_cab.scale = (0.40, 0.30, 0.65)
        bpy.ops.object.transform_apply(scale=True)
        h_cab.name = f"Hub_Cabinet_{hid}"
        h_cab.data.materials.append(materials["Mat_Hub_Cabinet"])
        bpy.context.scene.collection.objects.unlink(h_cab)
        hubs_coll.objects.link(h_cab)

        # Front Status LEDs
        bpy.ops.mesh.primitive_cylinder_add(radius=0.018, depth=0.01, location=(hx - 0.10, hy - 0.155, 0.58))
        led_pwr = bpy.context.active_object
        led_pwr.rotation_euler = (math.radians(90), 0, 0)
        led_pwr.name = f"Hub_LED_Power_{hid}"
        led_pwr.data.materials.append(materials["Mat_Hub_LED_Power"])
        bpy.context.scene.collection.objects.unlink(led_pwr)
        hubs_coll.objects.link(led_pwr)

        bpy.ops.mesh.primitive_cylinder_add(radius=0.018, depth=0.01, location=(hx + 0.10, hy - 0.155, 0.58))
        led_port = bpy.context.active_object
        led_port.rotation_euler = (math.radians(90), 0, 0)
        led_port.name = f"Hub_LED_Port_{hid}"
        led_port.data.materials.append(materials["Mat_Hub_LED_Port"])
        bpy.context.scene.collection.objects.unlink(led_port)
        hubs_coll.objects.link(led_port)

        # 3D Floating Holographic Label
        hub_fc = bpy.data.curves.new(f"Font_{hid}", type="FONT")
        hub_fc.body = f"HUB {hid}"
        hub_fc.size = 0.26
        hub_fc.align_x = "CENTER"
        hub_fc.align_y = "CENTER"
        hub_fc.extrude = 0.03

        hub_text = bpy.data.objects.new(f"Text_{hid}", hub_fc)
        hub_text.location = (hx, hy, 0.85)
        hub_text.rotation_euler = (math.radians(35), 0, math.radians(-15))
        hub_text.data.materials.append(materials["Mat_Hub_Text"])
        hubs_coll.objects.link(hub_text)
        # Convert font curve to real mesh so it exports in glTF/GLB
        bpy.context.view_layer.objects.active = hub_text
        hub_text.select_set(True)
        bpy.ops.object.convert(target="MESH")

    # 8. 3D Cable Route Conduit Networks (Phase 3)
    cable_mat_keys = ["Mat_Cable_1", "Mat_Cable_2", "Mat_Cable_3", "Mat_Cable_4"]
    for h_idx, hub in enumerate(hubs_data):
        hid = hub.get("id", f"H{h_idx + 1}")
        circuit_mat = materials[cable_mat_keys[h_idx % len(cable_mat_keys)]]

        for s_idx, seg in enumerate(hub.get("segments", [])):
            pts = seg.get("polyline", [])
            if len(pts) < 2:
                continue

            curve_data = bpy.data.curves.new(name=f"Cable_{hid}_{seg['from']}_{seg['to']}_{s_idx}", type="CURVE")
            curve_data.dimensions = "3D"
            curve_data.bevel_depth = 0.045  # 4.5cm radius conduit raceway (9cm diameter solid pipe)
            curve_data.bevel_resolution = 6

            spline = curve_data.splines.new("POLY")
            spline.points.add(len(pts) - 1)

            for p_idx, pt in enumerate(pts):
                # Elevation 0.04m (above floor slab)
                spline.points[p_idx].co = (float(pt[0]), float(pt[1]), 0.04, 1.0)

            cable_obj = bpy.data.objects.new(f"Cable_{hid}_{seg['from']}_{seg['to']}_{s_idx}", curve_data)
            cable_obj.data.materials.append(circuit_mat)
            cables_coll.objects.link(cable_obj)

            # Convert curve to mesh for reliable glTF 3D export
            bpy.context.view_layer.objects.active = cable_obj
            cable_obj.select_set(True)
            bpy.ops.object.convert(target="MESH")

    # 9. Studio Lighting
    sun_data = bpy.data.lights.new(name="Sun_Key", type="SUN")
    sun_data.energy = 2.4
    sun_data.angle = 0.08  # Soft shadow edges
    sun_data.color = (1.0, 0.98, 0.94)
    sun_obj = bpy.data.objects.new(name="Sun_Key", object_data=sun_data)
    sun_obj.location = (diag * 0.7, -diag * 0.9, diag * 1.4)
    sun_obj.rotation_euler = (math.radians(45), math.radians(25), math.radians(35))
    lighting_coll.objects.link(sun_obj)

    fill_data = bpy.data.lights.new(name="Fill_Soft", type="AREA")
    fill_data.energy = 45.0
    fill_data.size = diag * 0.8
    fill_data.color = (0.92, 0.95, 1.0)
    fill_obj = bpy.data.objects.new(name="Fill_Soft", object_data=fill_data)
    fill_obj.location = (-diag * 0.8, diag * 0.8, diag * 1.0)
    lighting_coll.objects.link(fill_obj)

    # 10. Studio Camera
    target_empty = bpy.data.objects.new("Target_Center", None)
    target_empty.location = (0.0, 0.0, wall_height * 0.4)
    studio_coll.objects.link(target_empty)

    cam_data = bpy.data.cameras.new("Studio_Camera")
    cam_data.lens = 55.0  # Natural architectural perspective
    cam_data.clip_start = 0.1
    cam_data.clip_end = 200.0
    cam_obj = bpy.data.objects.new("Studio_Camera", cam_data)

    cam_dist = max(diag * 1.25, 12.0)
    cam_obj.location = (cam_dist * 0.75, -cam_dist * 0.95, cam_dist * 0.75)
    camera_coll.objects.link(cam_obj)
    bpy.context.scene.camera = cam_obj

    track = cam_obj.constraints.new(type="TRACK_TO")
    track.target = target_empty
    track.track_axis = "TRACK_NEGATIVE_Z"
    track.up_axis = "UP_Y"

    # World background
    if bpy.data.worlds:
        world = bpy.data.worlds[0]
    else:
        world = bpy.data.worlds.new("Studio_World")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (0.95, 0.96, 0.95, 1.0)
        bg.inputs["Strength"].default_value = 1.0

    # Render settings
    scene = bpy.context.scene
    scene.render.resolution_x = 1920
    scene.render.resolution_y = 1080
    scene.render.resolution_percentage = 100


def main():
    args = parse_cli_args()
    if not args["input"] or not args["output"]:
        print("Usage: blender --background --python blender_builder.py -- --input <in.json> --output <out.blend> [--render <preview.png>]")
        sys.exit(1)

    in_path = Path(args["input"]).resolve()
    out_blend = Path(args["output"]).resolve()
    out_blend.parent.mkdir(parents=True, exist_ok=True)

    with open(in_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    print(f"Building 3D Digital Twin scene for plan: {payload.get('plan_id', 'Unknown')}")
    build_scene(payload, wall_height=args["wall_height"], floor_thickness=args["floor_thickness"])

    # Save .blend
    bpy.ops.wm.save_mainfile(filepath=str(out_blend))
    print(f"Saved .blend file to: {out_blend}")

    # Optional GLB export (Phase 4)
    if args.get("glb"):
        glb_path = Path(args["glb"]).resolve()
        glb_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"Exporting web-ready GLB to: {glb_path}...")
        bpy.ops.export_scene.gltf(
            filepath=str(glb_path),
            export_format="GLB",
            export_apply=True,
            export_materials="EXPORT",
        )
        print("GLB export complete!")

    # Optional render
    if args.get("render"):
        render_path = Path(args["render"]).resolve()
        render_path.parent.mkdir(parents=True, exist_ok=True)
        bpy.context.scene.render.filepath = str(render_path)
        print(f"Rendering beauty preview to: {render_path}...")
        bpy.ops.render.render(write_still=True)
        print("Render complete!")

    # Optional top-down architectural plan render (Phase 4)
    if args.get("top_render"):
        top_render_path = Path(args["top_render"]).resolve()
        top_render_path.parent.mkdir(parents=True, exist_ok=True)
        bounds = payload.get("bounds", [0, 0, 10, 10])
        max_dim = max(bounds[2] - bounds[0], bounds[3] - bounds[1])
        cam = bpy.data.objects.get("Studio_Camera")
        if cam:
            for c in cam.constraints:
                c.mute = True
            cam.location = (0.0, 0.0, max(max_dim * 1.6, 15.0))
            cam.rotation_euler = (0.0, 0.0, 0.0)
            bpy.context.scene.render.filepath = str(top_render_path)
            print(f"Rendering top-down 3D blueprint to: {top_render_path}...")
            bpy.ops.render.render(write_still=True)
            print("Top-down render complete!")


if __name__ == "__main__":
    main()
