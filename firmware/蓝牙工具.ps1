param(
    [string]$Action = 'menu',
    [string]$Address = '90:DA:72:73:98:25',
    [string]$Image = ''
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimePython = $env:GUNMOUSE_BLE_PYTHON
if (-not $runtimePython) {
    $runtimePython = Join-Path $projectRoot '.venv\ble-updater\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $runtimePython)) {
        Write-Host '首次使用，正在准备本项目的蓝牙工具环境。'
        python -m venv (Join-Path $projectRoot '.venv\ble-updater')
        if ($LASTEXITCODE -ne 0) { throw '无法创建环境，请先安装Python。' }
    }
}
& $runtimePython -c 'import importlib.metadata; assert importlib.metadata.version("bleak") == "3.0.2"' 2>$null
if ($LASTEXITCODE -ne 0) {
    & $runtimePython -m pip install -r (Join-Path $PSScriptRoot 'requirements-ble.txt')
    if ($LASTEXITCODE -ne 0) { throw '蓝牙依赖安装未完成。' }
}
$toolArgs = @('-X', 'utf8', (Join-Path $PSScriptRoot 'ble_tool.py'), '--action', $Action, '--address', $Address)
if ($Image) { $toolArgs += @('--image', $Image) }
& $runtimePython @toolArgs
if ($LASTEXITCODE -ne 0) { throw '本次操作未完成，请查看上面的原因。' }
