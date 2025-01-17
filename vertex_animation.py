# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

# <pep8 compliant>


bl_info = {
    "name": "Vertex Animation",
    "author": "Joshua Bogart,Skylake",
    "version": (1, 0),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > VAT Tab",
    "description": "A tool for storing per frame vertex data for use in a vertex shader.",
    "warning": "",
    "doc_url": "",
    "category": "VAT",
}


import bpy
import bmesh


class RigidSettings(bpy.types.PropertyGroup):
    reference_frame: bpy.props.IntProperty(
        name="ReferenceFrame",
        description="The reference frame of mesh",
        default=0
    )


def get_per_frame_mesh_data(context, data, objects, ref_frame):
    """Return a list of combined mesh data per frame"""
    meshes = []
    for i in frame_range(context.scene):

        context.scene.frame_set(i)
        depsgraph = context.evaluated_depsgraph_get()
        bm = bmesh.new()
        for ob in objects:
            eval_object = ob.evaluated_get(depsgraph)
            me = data.meshes.new_from_object(eval_object)
            me.transform(ob.matrix_world)
            bm.from_mesh(me)
            data.meshes.remove(me)
        me = data.meshes.new("mesh")
        bm.to_mesh(me)
        bm.free()
        me.calc_normals()
        meshes.append(me)
        if i == ref_frame:
            export_mesh = me.copy()

    meshes.remove(meshes[len(meshes)-1])
    return meshes, export_mesh


def create_export_mesh_object(context, data, me):
    """Return a mesh object with correct UVs"""
    while len(me.uv_layers) < 2:
        me.uv_layers.new()
    uv_layer = me.uv_layers[1]
    uv_layer.name = "vertex_anim"

    for loop in me.loops:
        uv_layer.data[loop.index].uv = (
            (loop.vertex_index + 0.5)/len(me.vertices), 128/255
        )
    ob = data.objects.new("export_mesh", me)
    context.scene.collection.objects.link(ob)
    return ob


def get_vertex_data(data, meshes, refmesh):
    """Return lists of vertex offsets and normals from a list of mesh data"""
    offsets = []
    normals = []
    for me in reversed(meshes):
        for v in me.vertices:
            # Use the default scene scale instead since the send2UE plugin will fix that.
            offset = (v.co - refmesh.vertices[v.index].co)*100.0
            x, y, z = offset
            offsets.extend((x, -y, z, 1))
            x, y, z = v.normal
            normals.extend(((x + 1) * 0.5, (-y + 1) * 0.5, (z + 1) * 0.5, 1))
        if not me.users:
            data.meshes.remove(me)
    return offsets, normals


def frame_range(scene):
    """Return a range object with scene's frame start, end, and step"""
    return range(scene.frame_start, scene.frame_end + scene.frame_step, scene.frame_step)


def bake_vertex_data(context, data, offsets, normals, size):
    """Stores vertex offsets and normals in separate image textures"""
    width, height = size
    offset_texture = data.images.new(
        name="offsets",
        width=width,
        height=height,
        alpha=True,
        float_buffer=True
    )
    offset_texture.pixels = offsets
    normal_texture = data.images.new(
        name="normals",
        width=width,
        height=height,
        alpha=True
    )
    normal_texture.pixels = normals


class OBJECT_OT_ProcessAnimMeshes(bpy.types.Operator):
    """Store combined per frame vertex offsets and normals for all
    selected mesh objects into seperate image textures"""
    bl_idname = "object.process_anim_meshes"
    bl_label = "Process Anim Meshes"

    @property
    def allowed_modifiers(self):
        return [
            'ARMATURE', 'CAST', 'CURVE', 'DISPLACE', 'HOOK',
            'LAPLACIANDEFORM', 'LATTICE', 'MESH_DEFORM',
            'SHRINKWRAP', 'SIMPLE_DEFORM', 'SMOOTH',
            'CORRECTIVE_SMOOTH', 'LAPLACIANSMOOTH',
            'SURFACE_DEFORM', 'WARP', 'WAVE',
            'CLOTH', 'COLLISION'
        ]

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob and ob.type == 'MESH' and ob.mode == 'OBJECT'

    def execute(self, context):
        ref_frame = context.scene.rigid_settings.reference_frame
        units = context.scene.unit_settings
        data = bpy.data
        objects = [ob for ob in context.selected_objects if ob.type == 'MESH']
        vertex_count = sum([len(ob.data.vertices) for ob in objects])
        frange = frame_range(context.scene)
        frame_count = len(frange)-1
        if ref_frame not in frange:
            ref_frame = frange.start
        for ob in objects:
            for mod in ob.modifiers:
                if mod.type not in self.allowed_modifiers:
                    self.report(
                        {'ERROR'},
                        f"Objects with {mod.type.title()} modifiers are not allowed!"
                    )
                    return {'CANCELLED'}

        # Use the default scene scale instead since the send2UE plugin will fix that
        #if units.system != 'METRIC' or round(units.scale_length, 2) != 0.01:
        #   self.report(
        #      {'ERROR'},
        #      "Scene Unit must be Metric with a Unit Scale of 0.01!"
        #   )
        #return {'CANCELLED'}
        if vertex_count > 8192:
            self.report(
                {'ERROR'},
                f"Vertex count of {vertex_count :,}, execedes limit of 8,192!"
            )
            return {'CANCELLED'}
        if frame_count > 8192:
            self.report(
                {'ERROR'},
                f"Frame count of {frame_count :,}, execedes limit of 8,192!"
            )
            return {'CANCELLED'}

        meshes, export_mesh_data = get_per_frame_mesh_data(context, data, objects, ref_frame)
        create_export_mesh_object(context, data, export_mesh_data)
        offsets, normals = get_vertex_data(data, meshes, export_mesh_data)
        texture_size = vertex_count, frame_count
        bake_vertex_data(context, data, offsets, normals, texture_size)
        return {'FINISHED'}


class VIEW3D_PT_VertexAnimation(bpy.types.Panel):
    """Creates a Panel in 3D Viewport"""
    bl_label = "Vertex Animation"
    bl_idname = "VIEW3D_PT_vertex_animation"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "VAT"

    def draw(self, context):
        layout = self.layout
        layout.use_property_decorate = False
        scene = context.scene
        layout.prop(scene, "frame_start", text="Frame Start")
        layout.prop(scene, "frame_end", text="End")
        layout.prop(scene, "frame_step", text="Step")
        rigid_prop = context.scene.rigid_settings
        layout.prop(rigid_prop, "reference_frame", text="ReferenceFrame")
        row1 = layout.row()
        row1.operator("object.process_anim_meshes")


def register():
    bpy.utils.register_class(RigidSettings)
    bpy.utils.register_class(OBJECT_OT_ProcessAnimMeshes)
    bpy.utils.register_class(VIEW3D_PT_VertexAnimation)
    bpy.types.Scene.rigid_settings = bpy.props.PointerProperty(
        type=RigidSettings
    )


def unregister():
    bpy.utils.unregister_class(RigidSettings)
    bpy.utils.unregister_class(OBJECT_OT_ProcessAnimMeshes)
    bpy.utils.unregister_class(VIEW3D_PT_VertexAnimation)
    del bpy.types.Scene.rigid_settings


if __name__ == "__main__":
    register()
