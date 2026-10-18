return {
  client: eda.sys_Environment.isClient(),
  halfOffline: eda.sys_Environment.isHalfOfflineMode(),
  version: eda.sys_Environment.getEditorCurrentVersion(),
  projects: await eda.sys_FileSystem.getProjectsPaths(),
  project: await eda.dmt_Project.getCurrentProjectInfo(),
  stack: await eda.pcb_Layer.getCurrentPhysicalStackingConfiguration(),
  copperLayers: await eda.pcb_Layer.getTheNumberOfCopperLayers()
};
