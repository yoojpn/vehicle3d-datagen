"""
Blender(bpy)内で実行するスクリプト。
操作列(JSON)を読み込み、実際にメッシュを構築し、
複数視点でレンダリング、GLBとしてエクスポートする。

実行例:
blender --background --python build_and_render.py -- ops.json output_dir/
"""
import bpy
import sys
import json
import math
import os
import mathutils


def clear_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for mesh in list(bpy.data.meshes):
        bpy.data.meshes.remove(mesh)


def add_box(op):
    size = op["params"]["size"]
    pos = op["params"]["position"]
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=pos)
    obj = bpy.context.object
    obj.scale = size
    obj.name = op["id"]
    bpy.ops.object.transform_apply(scale=True)
    return obj


def add_cylinder(op):
    size = op["params"]["size"]
    pos = op["params"]["position"]
    bpy.ops.mesh.primitive_cylinder_add(radius=1.0, depth=1.0, location=pos)
    obj = bpy.context.object
    obj.scale = size
    obj.name = op["id"]
    bpy.ops.object.transform_apply(scale=True)
    return obj


def add_sphere(op):
    size = op["params"]["size"]
    pos = op["params"]["position"]
    bpy.ops.mesh.primitive_uv_sphere_add(radius=1.0, location=pos)
    obj = bpy.context.object
    obj.scale = size
    obj.name = op["id"]
    bpy.ops.object.transform_apply(scale=True)
    return obj


def add_cone(op):
    size = op["params"]["size"]
    pos = op["params"]["position"]
    bpy.ops.mesh.primitive_cone_add(radius1=1.0, depth=1.0, location=pos)
    obj = bpy.context.object
    obj.scale = size
    obj.name = op["id"]
    bpy.ops.object.transform_apply(scale=True)
    return obj


def add_torus(op):
    size = op["params"]["size"]  # [major_radius, minor_radius, height(未使用)]
    pos = op["params"]["position"]
    bpy.ops.mesh.primitive_torus_add(
        location=pos, major_radius=size[0], minor_radius=size[1]
    )
    obj = bpy.context.object
    obj.name = op["id"]
    return obj


def add_plane(op):
    size = op["params"]["size"]  # [width, depth, thickness(未使用)]
    pos = op["params"]["position"]
    bpy.ops.mesh.primitive_plane_add(size=1.0, location=pos)
    obj = bpy.context.object
    obj.scale = [size[0], size[1], 1.0]
    obj.name = op["id"]
    bpy.ops.object.transform_apply(scale=True)
    return obj


def add_wedge(op):
    """くさび形(翼の断面等に使用)。立方体を編集して片側を潰す"""
    size = op["params"]["size"]
    pos = op["params"]["position"]
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=pos)
    obj = bpy.context.object
    obj.name = op["id"]
    obj.scale = size
    bpy.ops.object.transform_apply(scale=True)

    bpy.ops.object.mode_set(mode='EDIT')
    import bmesh
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    # +X側の上部2頂点をZ中心に潰してくさび形にする
    max_x = max(v.co.x for v in bm.verts)
    for v in bm.verts:
        if abs(v.co.x - max_x) < 1e-5 and v.co.z > 0:
            v.co.z = 0
    bmesh.update_edit_mesh(obj.data)
    bpy.ops.object.mode_set(mode='OBJECT')
    return obj


def add_tube(op):
    """パイプ状(円柱の内側をくり抜いたもの)。エンジン吸気口等に使用"""
    size = op["params"]["size"]  # [outer_radius, wall_ratio(0-1), height]
    pos = op["params"]["position"]
    outer_r, wall_ratio, height = size[0], size[1], size[2]
    inner_r = outer_r * (1 - min(max(wall_ratio, 0.05), 0.9))

    bpy.ops.mesh.primitive_cylinder_add(radius=outer_r, depth=height, location=pos)
    outer = bpy.context.object
    bpy.ops.mesh.primitive_cylinder_add(radius=inner_r, depth=height * 1.2, location=pos)
    inner = bpy.context.object

    bpy.context.view_layer.objects.active = outer
    mod = outer.modifiers.new("Hollow", 'BOOLEAN')
    mod.operation = 'DIFFERENCE'
    mod.object = inner
    bpy.ops.object.modifier_apply(modifier=mod.name)
    bpy.data.objects.remove(inner, do_unlink=True)
    outer.name = op["id"]
    return outer


def apply_extrude_face(op, objects):
    """指定面(現状は+Z面で簡略化)を押し出す"""
    obj = objects[op["target"]]
    bpy.context.view_layer.objects.active = obj
    import bmesh
    bpy.ops.object.mode_set(mode='EDIT')
    bm = bmesh.from_edit_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    # 法線がもっとも+Zに近い面を選ぶ(簡略化した面選択ロジック)
    target_face = max(bm.faces, key=lambda f: f.normal.z)
    bmesh.ops.delete(bm, geom=[], context='FACES')  # no-op、bmeshの状態更新用
    bpy.ops.mesh.select_all(action='DESELECT')
    target_face.select = True
    bmesh.update_edit_mesh(obj.data)
    distance = op["params"].get("distance", 0.2)
    bpy.ops.mesh.extrude_region_move(
        TRANSFORM_OT_translate={"value": (0, 0, distance)}
    )
    bpy.ops.object.mode_set(mode='OBJECT')


def apply_inset_face(op, objects):
    obj = objects[op["target"]]
    bpy.context.view_layer.objects.active = obj
    import bmesh
    bpy.ops.object.mode_set(mode='EDIT')
    bm = bmesh.from_edit_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    target_face = max(bm.faces, key=lambda f: f.normal.z)
    bpy.ops.mesh.select_all(action='DESELECT')
    target_face.select = True
    bmesh.update_edit_mesh(obj.data)
    thickness = op["params"].get("thickness", 0.1)
    bpy.ops.mesh.inset(thickness=thickness)
    bpy.ops.object.mode_set(mode='OBJECT')


def apply_bevel(op, objects):
    obj = objects[op["target"]]
    bpy.context.view_layer.objects.active = obj
    mod = obj.modifiers.new("Bevel", 'BEVEL')
    mod.width = op["params"]["width"]
    mod.segments = op["params"]["segments"]
    bpy.ops.object.modifier_apply(modifier=mod.name)


def apply_taper(op, objects):
    obj = objects[op["target"]]
    bpy.context.view_layer.objects.active = obj
    mod = obj.modifiers.new("Taper", 'SIMPLE_DEFORM')
    mod.deform_method = 'TAPER'
    mod.factor = op["params"]["factor"]
    axis_map = {"x": "X", "y": "Y", "z": "Z"}
    mod.deform_axis = axis_map[op["params"]["axis"]]
    bpy.ops.object.modifier_apply(modifier=mod.name)


def apply_subdivide(op, objects):
    obj = objects[op["target"]]
    bpy.context.view_layer.objects.active = obj
    mod = obj.modifiers.new("Subsurf", 'SUBSURF')
    mod.levels = op["params"]["levels"]
    mod.render_levels = op["params"]["levels"]
    bpy.ops.object.modifier_apply(modifier=mod.name)


def apply_bend(op, objects):
    obj = objects[op["target"]]
    bpy.context.view_layer.objects.active = obj
    mod = obj.modifiers.new("Bend", 'SIMPLE_DEFORM')
    mod.deform_method = 'BEND'
    mod.factor = op["params"]["angle"]  # ラジアン
    axis_map = {"x": "X", "y": "Y", "z": "Z"}
    mod.deform_axis = axis_map[op["params"].get("axis", "z")]
    bpy.ops.object.modifier_apply(modifier=mod.name)


def apply_twist(op, objects):
    obj = objects[op["target"]]
    bpy.context.view_layer.objects.active = obj
    mod = obj.modifiers.new("Twist", 'SIMPLE_DEFORM')
    mod.deform_method = 'TWIST'
    mod.factor = op["params"]["angle"]
    axis_map = {"x": "X", "y": "Y", "z": "Z"}
    mod.deform_axis = axis_map[op["params"].get("axis", "z")]
    bpy.ops.object.modifier_apply(modifier=mod.name)


def apply_shear(op, objects):
    obj = objects[op["target"]]
    bpy.context.view_layer.objects.active = obj
    mod = obj.modifiers.new("Shear", 'SIMPLE_DEFORM')
    mod.deform_method = 'TAPER'  # Blenderにshear専用がないためtaperで近似
    mod.factor = op["params"].get("factor", 0.2)
    bpy.ops.object.modifier_apply(modifier=mod.name)


def apply_solidify(op, objects):
    obj = objects[op["target"]]
    bpy.context.view_layer.objects.active = obj
    mod = obj.modifiers.new("Solidify", 'SOLIDIFY')
    mod.thickness = op["params"].get("thickness", 0.05)
    bpy.ops.object.modifier_apply(modifier=mod.name)


def apply_displace(op, objects):
    obj = objects[op["target"]]
    bpy.context.view_layer.objects.active = obj
    tex = bpy.data.textures.new(f"disp_{op['id']}", type='CLOUDS')
    mod = obj.modifiers.new("Displace", 'DISPLACE')
    mod.texture = tex
    mod.strength = op["params"].get("strength", 0.05)
    bpy.ops.object.modifier_apply(modifier=mod.name)


def apply_remesh(op, objects):
    obj = objects[op["target"]]
    bpy.context.view_layer.objects.active = obj
    mod = obj.modifiers.new("Remesh", 'REMESH')
    mod.mode = 'VOXEL'
    mod.voxel_size = op["params"].get("voxel_size", 0.05)
    bpy.ops.object.modifier_apply(modifier=mod.name)


def apply_decimate(op, objects):
    obj = objects[op["target"]]
    bpy.context.view_layer.objects.active = obj
    mod = obj.modifiers.new("Decimate", 'DECIMATE')
    mod.ratio = op["params"].get("ratio", 0.5)
    bpy.ops.object.modifier_apply(modifier=mod.name)


def apply_smooth(op, objects):
    obj = objects[op["target"]]
    bpy.context.view_layer.objects.active = obj
    mod = obj.modifiers.new("Smooth", 'SMOOTH')
    mod.factor = op["params"].get("factor", 0.5)
    mod.iterations = op["params"].get("iterations", 2)
    bpy.ops.object.modifier_apply(modifier=mod.name)


def apply_mirror(op, objects):
    obj = objects[op["target"]]
    bpy.context.view_layer.objects.active = obj
    mod = obj.modifiers.new("Mirror", 'MIRROR')
    axis_map = {"x": (True, False, False), "y": (False, True, False), "z": (False, False, True)}
    mod.use_axis = axis_map[op["params"]["axis"]]
    bpy.ops.object.modifier_apply(modifier=mod.name)


def apply_array(op, objects):
    obj = objects[op["target"]]
    bpy.context.view_layer.objects.active = obj
    mod = obj.modifiers.new("Array", 'ARRAY')
    mod.count = op["params"]["count"]
    offset = op["params"]["offset"]
    axis = op["params"]["axis"]
    rel = [0.0, 0.0, 0.0]
    idx_map = {"x": 0, "y": 1, "z": 2}
    rel[idx_map[axis]] = offset
    mod.use_relative_offset = False
    mod.use_constant_offset = True
    mod.constant_offset_displace = rel
    bpy.ops.object.modifier_apply(modifier=mod.name)


BUILDERS = {
    "add_box": add_box,
    "add_cylinder": add_cylinder,
    "add_sphere": add_sphere,
    "add_cone": add_cone,
    "add_torus": add_torus,
    "add_plane": add_plane,
    "add_wedge": add_wedge,
    "add_tube": add_tube,
}

MODIFIERS = {
    "bevel": apply_bevel,
    "taper": apply_taper,
    "subdivide": apply_subdivide,
    "mirror": apply_mirror,
    "array": apply_array,
    "bend": apply_bend,
    "twist": apply_twist,
    "shear": apply_shear,
    "solidify": apply_solidify,
    "displace": apply_displace,
    "remesh": apply_remesh,
    "decimate": apply_decimate,
    "smooth": apply_smooth,
    "extrude": apply_extrude_face,
    "inset": apply_inset_face,
}


def execute_operations(ops):
    objects = {}
    for op in ops:
        try:
            if op["type"] in BUILDERS:
                obj = BUILDERS[op["type"]](op)
                objects[op["id"]] = obj
            elif op["type"] in MODIFIERS:
                MODIFIERS[op["type"]](op, objects)
                objects[op["id"]] = objects[op["target"]]
            else:
                print(f"WARNING: unknown op type {op['type']}, skipping")
        except Exception as e:
            print(f"WARNING: failed op {op.get('id')} ({op['type']}): {e}")
    return objects


def join_all_meshes():
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    if not meshes:
        return None
    bpy.ops.object.select_all(action='DESELECT')
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    obj = bpy.context.object

    # 近接頂点をマージして、接触面が正しく1つのメッシュとして繋がるようにする
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.remove_doubles(threshold=0.001)
    bpy.ops.object.mode_set(mode='OBJECT')

    return obj


def setup_camera_and_light():
    bpy.ops.object.camera_add(location=(0, -6, 2))
    cam = bpy.context.object
    bpy.context.scene.camera = cam

    bpy.ops.object.light_add(type='SUN', location=(4, -4, 6))
    light = bpy.context.object
    light.data.energy = 3.0

    world = bpy.context.scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs[0].default_value = (0.9, 0.9, 0.9, 1.0)
    return cam


def point_camera_at(cam, target=(0, 0, 0.7)):
    direction = (
        target[0] - cam.location.x,
        target[1] - cam.location.y,
        target[2] - cam.location.z,
    )
    import mathutils
    dirv = mathutils.Vector(direction)
    rot_quat = dirv.to_track_quat('-Z', 'Y')
    cam.rotation_euler = rot_quat.to_euler()


def compute_auto_distance(obj, base_fov=40.0, margin=1.6):
    # オブジェクトのバウンディングボックス対角線から、画角に収まるカメラ距離を逆算
    bbox_corners = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
    xs = [c.x for c in bbox_corners]
    ys = [c.y for c in bbox_corners]
    zs = [c.z for c in bbox_corners]
    diag = ((max(xs)-min(xs))**2 + (max(ys)-min(ys))**2 + (max(zs)-min(zs))**2) ** 0.5
    import math as _m
    half_fov_rad = _m.radians(base_fov / 2)
    distance = (diag / 2) / _m.tan(half_fov_rad) * margin
    center = mathutils.Vector(((max(xs)+min(xs))/2, (max(ys)+min(ys))/2, (max(zs)+min(zs))/2))
    return max(distance, 1.5), center


def render_views(cam, output_dir, obj, num_views=6, elevation=25.0):
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE_NEXT'
    scene.render.resolution_x = 256
    scene.render.resolution_y = 256
    scene.render.film_transparent = False
    scene.eevee.taa_render_samples = 8

    distance, center = compute_auto_distance(obj)

    for i in range(num_views):
        azimuth = (360.0 / num_views) * i
        rad_az = math.radians(azimuth)
        rad_el = math.radians(elevation)
        x = center.x + distance * math.cos(rad_el) * math.sin(rad_az)
        y = center.y - distance * math.cos(rad_el) * math.cos(rad_az)
        z = center.z + distance * math.sin(rad_el)
        cam.location = (x, y, z)
        point_camera_at(cam, target=(center.x, center.y, center.z))

        scene.render.filepath = os.path.join(output_dir, f"view_{i:02d}.png")
        bpy.ops.render.render(write_still=True)


def main():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:]
    ops_path = argv[0]
    output_dir = argv[1]

    os.makedirs(output_dir, exist_ok=True)

    with open(ops_path) as f:
        data = json.load(f)
    ops = data["operations"]

    clear_scene()
    execute_operations(ops)
    joined = join_all_meshes()

    if joined is None:
        print("ERROR: no mesh produced")
        return

    cam = setup_camera_and_light()
    render_views(cam, output_dir, joined, num_views=6)

    export_path = os.path.join(output_dir, "mesh.glb")
    bpy.ops.object.select_all(action='DESELECT')
    joined.select_set(True)
    bpy.ops.export_scene.gltf(filepath=export_path, use_selection=True)

    print(f"DONE: {output_dir}")


main()
