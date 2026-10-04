// 工具验证专用；只允许在独立示例工程的空电路板中执行。
const geometry = __CLI__.args;
if (geometry.coordinates.units !== 'mm' || geometry.coordinates.origin !== 'board_center_bottom') {
    throw new Error('需要毫米单位和板中心底面原点');
}
const project = await eda.dmt_Project.getCurrentProjectInfo();
if (!project || project.friendlyName !== 'toolchain-demo') {
    throw new Error('只允许修改 toolchain-demo 验证工程');
}
const boardItem = project.data.find(item => item.itemType === 'Board' && item.name === 'Board1');
if (!boardItem || !boardItem.pcb) throw new Error('验证工程没有默认电路板');
await eda.dmt_EditorControl.openDocument(boardItem.pcb.uuid);
await new Promise(resolve => setTimeout(resolve, 2500));
const existingOutlines = await eda.pcb_PrimitivePolyline.getAllPrimitiveId();
const existingPads = await eda.pcb_PrimitivePad.getAllPrimitiveId();
if (existingOutlines.length || existingPads.length) {
    throw new Error('验证电路板已有图元，拒绝重复生成；请使用新的独立示例工程');
}

// 嘉立创图元接口使用密耳；Y 方向向下。共享机械参数使用毫米，Y 向上。
const mil = mm => mm / 0.0254;
const halfX = mil(geometry.board.width_mm / 2);
const halfY = mil(geometry.board.depth_mm / 2);
const polygon = eda.pcb_MathPolygon.createPolygon([
    -halfX, -halfY, 'L', halfX, -halfY, halfX, halfY,
    -halfX, halfY, -halfX, -halfY
]);
const outline = await eda.pcb_PrimitivePolyline.create('', 11, polygon, mil(0.2), false);
if (!outline) throw new Error('创建板框失败');
const holes = [];
for (let index = 0; index < geometry.board.mounting_holes.length; index++) {
    const hole = geometry.board.mounting_holes[index];
    const diameter = mil(hole.diameter_mm);
    const pad = await eda.pcb_PrimitivePad.create(
        12, String(index + 1), mil(hole.x_mm), -mil(hole.y_mm), 0,
        ['ELLIPSE', diameter, diameter], '', ['ROUND', diameter],
        0, 0, 0, false, 0
    );
    if (!pad) throw new Error('创建安装孔失败：' + (index + 1));
    holes.push({primitiveId: pad.getState_PrimitiveId(), ...hole});
}
await eda.pcb_Document.save();
return {
    purpose: geometry.purpose,
    pcbUuid: boardItem.pcb.uuid,
    outlineId: outline.getState_PrimitiveId(),
    boardDimensionsMm: geometry.board,
    holes,
    coordinateConversion: '嘉立创坐标=毫米/0.0254，机械Y轴转换为负的嘉立创Y轴',
    electricalDesignTested: false
};
