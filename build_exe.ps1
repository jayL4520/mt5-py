# 该脚本用于将当前系统打包为 Windows 可执行文件。

$ErrorActionPreference = "Stop"

Write-Host "==> 开始检查 PyInstaller"
py -3.13 -m PyInstaller --version | Out-Null

Write-Host "==> 清理旧的构建产物"
if (Test-Path ".\build") {
    Remove-Item -LiteralPath ".\build" -Recurse -Force
}
if (Test-Path ".\dist") {
    Remove-Item -LiteralPath ".\dist" -Recurse -Force
}

Write-Host "==> 开始打包 mt5_quant.1.0.6.exe"
py -3.13 -m PyInstaller --noconfirm --clean ".\mt5_quant.spec"

Write-Host "==> 打包完成"
Write-Host "输出目录: $((Resolve-Path '.\dist').Path)"
