// 只查询程序接口，不修改任何设计。
return {
    isClient: eda.sys_Environment.isClient(),
    editorVersion: eda.sys_Environment.getEditorCurrentVersion(),
    projectPaths: await eda.sys_FileSystem.getProjectsPaths(),
    capabilities: {
        createProject: typeof eda.dmt_Project.createProject === 'function',
        schematicComponent: typeof eda.sch_PrimitiveComponent.create === 'function',
        schematicWire: typeof eda.sch_PrimitiveWire.create === 'function',
        pcbOutline: typeof eda.pcb_PrimitivePolyline.create === 'function',
        pcbPad: typeof eda.pcb_PrimitivePad.create === 'function',
        autoRouting: typeof eda.pcb_Document.autoRouting === 'function',
        designRules: typeof eda.pcb_Drc.check === 'function',
        export3D: typeof eda.pcb_ManufactureData.get3DFile === 'function',
        savePcb: typeof eda.pcb_Document.save === 'function'
    }
};
