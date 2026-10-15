"""将 KiCad 导出的二进制三维模型转换成毫米单位的 OBJ 和材质文件。

先以 kicad-cli pcb export glb 导出铜线、焊盘、覆铜、阻焊、丝印。
运行：CadQuery 环境的 Python 本脚本 输入.glb 输出.obj。
"""
from pathlib import Path
import sys

import vtk


def export(source, target):
    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    importer = vtk.vtkGLTFImporter()
    importer.SetFileName(str(source))
    importer.SetRenderWindow(window)
    importer.Update()
    actors = importer.GetRenderer().GetActors()
    actors.InitTraversal()
    # 原格式单位为米、Y轴朝上；输出毫米、Z轴朝上。
    matrix = vtk.vtkMatrix4x4()
    matrix.Zero()
    for row, col, value in [(0, 0, 1000), (1, 2, -1000), (2, 1, 1000), (3, 3, 1)]:
        matrix.SetElement(row, col, value)
    grouped = {}
    for _ in range(actors.GetNumberOfItems()):
        actor = actors.GetNextActor()
        prop = actor.GetProperty()
        material = (prop.GetColor(), prop.GetOpacity())
        combined = vtk.vtkMatrix4x4()
        vtk.vtkMatrix4x4.Multiply4x4(matrix, actor.GetMatrix(), combined)
        transform = vtk.vtkTransform()
        transform.SetMatrix(combined)
        converted = vtk.vtkTransformPolyDataFilter()
        converted.SetTransform(transform)
        converted.SetInputData(actor.GetMapper().GetInput())
        converted.Update()
        grouped.setdefault(material, vtk.vtkAppendPolyData()).AddInputData(converted.GetOutput())
    output = vtk.vtkRenderer()
    result_window = vtk.vtkRenderWindow()
    result_window.SetOffScreenRendering(1)
    result_window.AddRenderer(output)
    for (color, opacity), geometry in grouped.items():
        geometry.Update()
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(geometry.GetOutput())
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(*color)
        actor.GetProperty().SetOpacity(opacity)
        output.AddActor(actor)
    target.parent.mkdir(parents=True, exist_ok=True)
    writer = vtk.vtkOBJExporter()
    writer.SetRenderWindow(result_window)
    writer.SetFilePrefix(str(target.with_suffix("")))
    writer.Write()
    data = target.read_text(encoding="utf-8")
    data = "\n".join("mtllib " + target.with_suffix(".mtl").name if line.startswith("mtllib ") else line
                     for line in (line.rstrip() for line in data.splitlines()))
    target.write_text("# 单位：毫米；Z轴朝上；来源：当前KiCad工程\n" + data + "\n", encoding="utf-8", newline="\n")
    material_file = target.with_suffix(".mtl")
    # 此导出器把不透明度写进 Tr；改为标准的不透明度字段 d。
    material_file.write_text(material_file.read_text(encoding="utf-8").replace("\nTr ", "\nd "), encoding="utf-8", newline="\n")
    print("输出：", target)
    print("范围（毫米）：", output.ComputeVisiblePropBounds())


if __name__ == "__main__":
    export(Path(sys.argv[1]), Path(sys.argv[2]))
