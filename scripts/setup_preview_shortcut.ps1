# 使用原生 Windows 快捷方式提供双击查看入口；软件路径来自项目配置。
$ErrorActionPreference = 'Stop'
$previewProjectRoot = Split-Path -Parent $PSScriptRoot
$previewTools = Get-Content -LiteralPath (Join-Path $previewProjectRoot 'config\tools.json') -Raw | ConvertFrom-Json
if (-not (Test-Path -LiteralPath $previewTools.cq_editor_pythonw)) {
    throw '未找到三维查看环境，请先完成查看器安装。'
}
$previewShell = New-Object -ComObject WScript.Shell
$previewShortcut = $previewShell.CreateShortcut((Join-Path $previewProjectRoot '查看板和外壳.lnk'))
$previewShortcut.TargetPath = $previewTools.cq_editor_pythonw
$previewShortcut.Arguments = '"' + (Join-Path $previewProjectRoot 'scripts\open_preview.py') + '"'
$previewShortcut.WorkingDirectory = $previewProjectRoot
$previewShortcut.Description = '查看实际电路板与外壳装配；支持旋转、缩放、分别隐藏和自动刷新。'
$previewShortcut.Save()
Write-Output (Join-Path $previewProjectRoot '查看板和外壳.lnk')
