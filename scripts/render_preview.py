"""从实际三维模型生成静态预览图片，不读取或截取用户桌面。"""

from io import BytesIO
from pathlib import Path

import vtk
from PIL import Image, ImageDraw, ImageFont

from view_assembly import load_models, output_directory


def actor(model, color, opacity):
    shape = model.val()
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(shape.toVtkPolyData(tolerance=0.01, angularTolerance=0.08, normals=True))
    item = vtk.vtkActor()
    item.SetMapper(mapper)
    item.GetProperty().SetColor(*color)
    item.GetProperty().SetOpacity(opacity)
    item.GetProperty().SetInterpolationToPhong()
    return item


def render_panel(board, shell, assembly):
    renderer = vtk.vtkRenderer()
    renderer.SetBackground(0.96, 0.97, 0.98)
    renderer.SetUseDepthPeeling(True)
    renderer.SetMaximumNumberOfPeels(100)
    renderer.SetOcclusionRatio(0.01)
    renderer.AddActor(actor(shell, (0.48, 0.63, 0.75), 0.28 if assembly else 1.0))
    if assembly:
        renderer.AddActor(actor(board, (0.12, 0.52, 0.28), 1.0))
    camera = renderer.GetActiveCamera()
    camera.SetPosition(*(60, -75, 100) if assembly else (20, -30, 180))
    camera.SetFocalPoint(0, 0, 3)
    camera.SetViewUp(0, 0, 1)
    camera.ParallelProjectionOn()
    renderer.ResetCamera()
    camera.Zoom(1.15)
    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(True)
    window.SetAlphaBitPlanes(True)
    window.SetMultiSamples(0)
    window.SetSize(760, 540)
    window.AddRenderer(renderer)
    try:
        window.Render()
        capture = vtk.vtkWindowToImageFilter()
        capture.SetInput(window)
        capture.ReadFrontBufferOff()
        capture.Update()
        writer = vtk.vtkPNGWriter()
        writer.SetWriteToMemory(True)
        writer.SetInputConnection(capture.GetOutputPort())
        writer.Write()
        return Image.open(BytesIO(memoryview(writer.GetResult()).tobytes())).convert("RGB")
    finally:
        window.Finalize()


def main():
    board, shell = load_models()
    preview = Image.new("RGB", (1600, 790), "#f5f7fa")
    preview.paste(render_panel(board, shell, True), (30, 160))
    preview.paste(render_panel(board, shell, False), (810, 160))
    regular = Path("C:/Windows/Fonts/msyh.ttc")
    bold = Path("C:/Windows/Fonts/msyhbd.ttc")
    title_font = ImageFont.truetype(str(bold), 38)
    label_font = ImageFont.truetype(str(regular), 25)
    small_font = ImageFont.truetype(str(regular), 21)
    draw = ImageDraw.Draw(preview)
    draw.text((40, 30), "工具联动示例", fill="#17354b", font=title_font)
    draw.text((42, 88), "真实嘉立创裸板 + 同一坐标生成的外壳", fill="#577086", font=label_font)
    draw.text((45, 132), "装配：绿色裸板 / 半透明外壳", fill="#294b61", font=label_font)
    draw.text((825, 132), "外壳单独显示：四个固定柱及贯穿孔", fill="#294b61", font=label_font)
    draw.text((45, 715), "实际模型直接导入，板壳保持装配坐标；可单独查看固定柱和安装孔。", fill="#405f73", font=small_font)
    draw.text((45, 750), "仅用于验证工具配合；尚未定义真实飞鼠硬件、枪形外观或生产设计。", fill="#687f91", font=small_font)
    output = output_directory() / "assembly-preview.png"
    preview.save(output)
    print(f"已从实际模型生成静态预览：{output}")


if __name__ == "__main__":
    main()
