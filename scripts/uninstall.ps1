<#
.SYNOPSIS
  Removes AuraSort (the app folder and its shortcuts). Your own files are never touched.
.DESCRIPTION
  -Purge also removes AuraSort's data folder (%USERPROFILE%\.aurasort: file index, History/Undo logs, settings,
  thumbnails) and any API key saved in Windows Credential Manager. Files that AuraSort moved stay where they are.
.EXAMPLE
  .\uninstall.ps1 -WhatIf
.EXAMPLE
  .\uninstall.ps1 -Purge
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File uninstall.ps1 -Yes
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
  [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'Programs\AuraSort'),
  [string]$StartMenuDir = (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'),
  [switch]$Purge,
  [switch]$Yes   # do not ask for confirmation (handy with: powershell -File uninstall.ps1 -Yes)
)
$ErrorActionPreference = 'Stop'
if ($Yes) { $ConfirmPreference = 'None' }
$shortcuts = @((Join-Path $StartMenuDir 'AuraSort.lnk'), (Join-Path ([Environment]::GetFolderPath('Desktop')) 'AuraSort.lnk'))
foreach ($s in $shortcuts) { if ((Test-Path $s) -and $PSCmdlet.ShouldProcess($s, 'Remove shortcut')) { Remove-Item -Force $s } }
if ((Test-Path (Join-Path $InstallDir 'server.py')) -and $PSCmdlet.ShouldProcess($InstallDir, 'Remove the AuraSort app folder')) {
  Set-Location $env:TEMP
  Remove-Item -Recurse -Force $InstallDir
} elseif (Test-Path $InstallDir) {
  Write-Warning "$InstallDir does not look like an AuraSort folder (no server.py). Left as it is."
}
if ($Purge) {
  $data = Join-Path $env:USERPROFILE '.aurasort'
  if ((Test-Path $data) -and $PSCmdlet.ShouldProcess($data, 'Delete AuraSort data (index, History/Undo logs, settings, thumbnails)')) {
    Remove-Item -Recurse -Force $data
  }
  if ($PSCmdlet.ShouldProcess('Windows Credential Manager', 'Remove the saved cloud API key (if any)')) {
    & cmdkey.exe /delete:"AuraSort cloud AI key" 2>$null | Out-Null
  }
}
Write-Host 'AuraSort was removed. Files it moved for you stay where they are.'
