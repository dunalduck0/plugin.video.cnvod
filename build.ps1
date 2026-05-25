# Build a Kodi-installable zip of this addon.
#
# Kodi requires the zip to contain a single top-level folder named exactly
# `<addon-id>` (here: plugin.video.cnvod) holding addon.xml + default.py.
# We zip from the parent dir so the folder name is included.

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

$xml = [xml](Get-Content addon.xml)
$id = $xml.addon.id
$version = $xml.addon.version
$out = Join-Path $here "dist"
New-Item -ItemType Directory -Path $out -Force | Out-Null

$zip = Join-Path $out "$id-$version.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }

# Stage in a temp folder so the zip has the required `<id>/` top-level dir.
$stage = Join-Path $env:TEMP "cnvod-build-$(Get-Random)"
New-Item -ItemType Directory -Path $stage -Force | Out-Null
$dest = Join-Path $stage $id
New-Item -ItemType Directory -Path $dest -Force | Out-Null

$exclude = @("dist", "tools", ".git", ".github", "__pycache__", "build.ps1", ".vscode")
Get-ChildItem -Force | Where-Object {
    $exclude -notcontains $_.Name -and -not $_.Name.StartsWith(".")
} | ForEach-Object {
    Copy-Item $_.FullName -Destination $dest -Recurse -Force
}

# Strip __pycache__ recursively
Get-ChildItem -Path $dest -Recurse -Directory -Filter "__pycache__" |
    Remove-Item -Recurse -Force

Compress-Archive -Path $dest -DestinationPath $zip -Force
Remove-Item -Recurse -Force $stage

Write-Host "Built: $zip"
