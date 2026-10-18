"""厚长方条摇杆支座的独立概念预览，不替换交付文件。"""
from pathlib import Path

import build_gen2_quick_preview as current
from preview_layout import BODY_MOUNT_HOLES

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "shell/长方条支座方案"
SHIFT_X = -3.2
PREVIEW_LOCAL = (-36.5, -4.0)
SHARED_SEAT_Y = 5.34
SHARED_NUT_Y = (-14.06, -12.46)


def rectangular_support(m, xmin=-54.3, pocket_left=-49, xmax=None, relieve_bottom=True):
    """整体矩形包络；功能避让只从螺孔和内侧凹腔进入。"""
    block = m.box(xmin, -20.35+SHIFT_X if xmax is None else xmax, m.TOP, 7.44, -9.9, m.JOY_BOARD[4])
    block = m.cq.Workplane().add(block).edges("|Y").fillet(.5).val()
    if relieve_bottom:
        # 旧布局需要内侧共用凹腔；元件移出后可保留完整平整底面。
        pocket = m.box(pocket_left, -23.45, m.TOP-.1, .4, -10, -.5)
        pocket = pocket.cut(m.cy(*PREVIEW_LOCAL, 2.6, m.TOP-.2, .5))
        block = block.cut(pocket)
    pins = [pad["xz"][0]+SHIFT_X for pad in m.JOYSTICK["pads"]]
    block = block.cut(m.box(min(pins)-1.4, max(pins)+1.4, .04, 2.84, .6, m.JOY_BOARD[4]+.1))
    for i, (x, old_y) in enumerate(m.JOY_MOUNT_HOLES):
        x += SHIFT_X
        y = m.FACE_Y_SUM-old_y
        block = block.cut(m.cz(x, y, 2.15, -10, -3.8))
        if i == 0:
            block = block.cut(m.cz(x, y, 1.2, -4, m.JOY_BOARD[4]+.1))
        else:
            block = block.cut(m.fuse([
                m.cz(x-.6, y, 1.2, -4, m.JOY_BOARD[4]+.1),
                m.cz(x+.6, y, 1.2, -4, m.JOY_BOARD[4]+.1),
                m.box(x-.6, x+.6, y-1.2, y+1.2, -4, m.JOY_BOARD[4]+.1)]))
    for x, z in [PREVIEW_LOCAL]:
        block = block.cut(m.cy(x, z, 1.2, m.TOP-.1, 7.5))
        block = block.cut(m.cy(x, z, 2.2, 4.6, 7.5))
    x, z = BODY_MOUNT_HOLES["H3"]
    block = block.cut(m.cy(x, z, 1.2, m.TOP-.1, 7.5))
    block = block.cut(m.cy(x, z, 2.2, SHARED_SEAT_Y, 7.5))
    return block.clean()


def preview_body(m):
    body = current.build_body(m)
    x, z = BODY_MOUNT_HOLES["H3"]
    # 共用螺丝改从长方条正面装入；螺母藏在主体柱侧槽。
    body = body.fuse(m.cy(x, z, 2.2, m.BATTERY_FLOOR_Y, -18.0))
    body = body.cut(m.cy(x, z, 1.2, m.BATTERY_FLOOR_Y-.1, m.BACK+.1))
    return body.cut(m.box(x-6, x+2.5, -14.26, -12.46, z-2.15, z+2.15)).clean()


def preview_hardware():
    m = current.m
    refs, seats = current.preview_hardware()
    for name in list(refs):
        if name.startswith(("摇杆1-", "摇杆2-")):
            refs[name] = refs[name].translate((SHIFT_X, 0, 0))
        elif name.startswith("摇杆就近固定"):
            refs.pop(name)
    x, z = PREVIEW_LOCAL
    head = m.cy(x, z, 2, 4.6, 6.7).cut(m.hex_y(x, z, 1.5, 5.6, 6.8))
    refs["支座固定-螺钉"] = head.fuse(m.cy(x, z, 1, -5.4, 4.6))
    refs["支座固定-螺母"] = m.hex_y(x, z, 4, m.BACK-1.6, m.BACK).cut(m.cy(x, z, 1.05, m.BACK-1.7, m.BACK+.1))
    x, z = BODY_MOUNT_HOLES["H3"]
    head = m.cy(x, z, 2, SHARED_SEAT_Y, SHARED_SEAT_Y+2.1).cut(m.hex_y(x, z, 1.5, SHARED_SEAT_Y+.9, SHARED_SEAT_Y+2.2))
    refs["H3-螺钉"] = head.fuse(m.cy(x, z, 1, SHARED_SEAT_Y-20, SHARED_SEAT_Y))
    refs["H3-螺母"] = m.hex_y(x, z, 4, *SHARED_NUT_Y).cut(m.cy(x, z, 1.05, SHARED_NUT_Y[0]-.1, SHARED_NUT_Y[1]+.1))
    return refs, seats


def preview_board(m):
    board = m.prism(m.P["outline_xz"], m.BACK, m.TOP)
    for h in m.P["mount_holes"]:
        board = board.cut(m.cy(*h["xz"], h["d"]/2, m.BACK-.1, m.TOP+.1))
    board = board.cut(m.cy(*PREVIEW_LOCAL, 1.2, m.BACK-.1, m.TOP+.1))
    for part in m.C["parts"]:
        for pad in part.get("pads", []) + part.get("npth", []):
            if not pad.get("drill") or (part["ref"] == "SW2" and pad.get("number") == "3"):
                continue
            x, z = pad["xz"]
            if part["ref"] == "SW1":
                x += SHIFT_X
            elif part["ref"] == "J_GY":
                z += current.IMU_TRANSLATION_Z
            elif part["ref"] == "J_SWITCH":
                x += current.POWER_TRANSLATION[0]
                z += current.POWER_TRANSLATION[2]
            board = board.cut(m.cy(x, z, min(pad["drill"])/2, m.BACK-.1, m.TOP+.1))
    return board.clean()


def board_mesh(board, bounds):
    import vtk
    m = current.m
    vertices, faces = board.tessellate(.05)
    points, cells = vtk.vtkPoints(), vtk.vtkCellArray()
    for p in vertices:
        points.InsertNextPoint(p.x-bounds.xmin, bounds.zmax-p.z, p.y-m.BASE[0])
    for face in faces:
        cells.InsertNextCell(3, face)
    mesh = vtk.vtkPolyData()
    mesh.SetPoints(points)
    mesh.SetPolys(cells)
    return [("主板-孔位布局预览", "布局预览绿板", mesh)], {"布局预览绿板": (.10, .36, .23)}


def main():
    m = current.m
    support = rectangular_support(m)
    base = preview_body(m)
    board = preview_board(m)
    current.SUPPORT = support
    original_details = current.preview_details
    def details(module, refs):
        refs, colors, wires = original_details(module, refs)
        refs["载板"] = board
        for name in refs:
            if name.startswith(("SW1-", "摇杆-")):
                refs[name] = refs[name].translate((SHIFT_X, 0, 0))
        return refs, colors, wires
    refs, colors, _ = details(m, m.references())
    refs.update(preview_hardware()[0])
    for part, shape in (("主体底座", base), ("独立摇杆支座", support)):
        hits = {name: round(shape.intersect(v).Volume(), 5) for name, v in refs.items()
                if name != part and shape.intersect(v).Volume() > .001}
        if hits or not shape.isValid() or len(shape.Solids()) != 1:
            raise RuntimeError((part, hits))
    OUT.mkdir(parents=True, exist_ok=True)
    for folder in ("step", "stl"):
        (OUT/folder).mkdir(exist_ok=True)
    m.cq.exporters.export(base, str(OUT/"step/engineering_mount.step"))
    m.cq.exporters.export(support, str(OUT/"step/长方条支座_预览.step"))
    m.cq.exporters.export(support, str(OUT/"stl/长方条支座_仅供预览.stl"), tolerance=.03, angularTolerance=.1)
    m.OUT = OUT
    current.detail.assembled_details = details
    m.hardware = preview_hardware
    m.routed_pcb_meshes = lambda bounds: board_mesh(board, bounds)
    report_path = OUT/"assembly-check.json"
    report_path.write_text("{}", encoding="utf-8")
    m.export_assembled_stl(render_preview=False)
    report_path.unlink()
    print("预览完成；摇杆向主板内侧平移3.2毫米，主板仅显示孔位布局，尚未重布线。", flush=True)


if __name__ == "__main__":
    main()
