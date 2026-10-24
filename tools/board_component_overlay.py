"""在本次主板查看窗口中显示所选器件的中文名称，不修改全局设置。"""
import bpy
import blf


def selected_component():
    obj = bpy.context.view_layer.objects.active
    if obj is None or not obj.select_get() or not obj.get("器件名称"):
        return ("点击板上元件，查看名称", "中键拖动旋转，滚轮缩放", "")
    return (obj["器件名称"], obj.get("器件编号", "") + "    " + obj.get("器件值", ""),
            obj.get("用途", ""))


def register_overlay():
    if bpy.app.background:
        return
    key = "gunmouse_component_name_overlay"
    previous = bpy.app.driver_namespace.get(key)
    if previous:
        bpy.types.SpaceView3D.draw_handler_remove(previous, "WINDOW")
    font = blf.load(r"C:\Windows\Fonts\simhei.ttf")

    def draw():
        region = bpy.context.region
        if region is None:
            return
        for row, (text, size) in enumerate(zip(selected_component(), (30, 19, 18))):
            blf.size(font, size)
            blf.position(font, 28, region.height - 98 - row * 34, 0)
            blf.color(font, .98, .98, .98, 1)
            blf.enable(font, blf.SHADOW)
            blf.shadow(font, 5, 0, 0, 0, 1)
            blf.shadow_offset(font, 1, -1)
            blf.draw(font, text)

    bpy.app.driver_namespace[key] = bpy.types.SpaceView3D.draw_handler_add(draw, (), "WINDOW", "POST_PIXEL")
    print("GUNMOUSE_COMPONENT_OVERLAY_READY", selected_component(), flush=True)


register_overlay()
