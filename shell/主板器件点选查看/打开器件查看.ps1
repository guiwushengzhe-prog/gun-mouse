$ErrorActionPreference = 'Stop'
$componentScene = Join-Path $PSScriptRoot '主板_点选查看元件值.blend'
$componentClass = (Get-ItemProperty -LiteralPath 'Registry::HKEY_CLASSES_ROOT\.blend').'(default)'
$componentCommand = (Get-ItemProperty -LiteralPath ('Registry::HKEY_CLASSES_ROOT\' + $componentClass + '\shell\open\command')).'(default)'
if ($componentCommand -match '^"([^"]+)"') {
    $componentExecutable = $Matches[1]
} elseif ($componentCommand -match '^(.+?\.exe)') {
    $componentExecutable = $Matches[1]
} else {
    throw '找不到Blender程序，请先安装或关联Blender。'
}
Start-Process -FilePath $componentExecutable -ArgumentList @('--enable-autoexec', ('"' + $componentScene + '"')) -WindowStyle Normal
