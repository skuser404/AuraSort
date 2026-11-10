<#
.SYNOPSIS
  Installs AuraSort for the current user (no administrator rights needed).
.DESCRIPTION
  Downloads a tagged release ZIP from GitHub, checks its SHA-256 against the release's SHA256SUMS file, unpacks it to
  your user folder and adds Start Menu (and optionally Desktop) shortcuts. Nothing is sent anywhere else, and nothing
  outside the install folder and the shortcuts is changed.
.EXAMPLE
  irm https://raw.githubusercontent.com/skuser404/aurasort/v1.0.0/scripts/install.ps1 | iex
.EXAMPLE
  .\install.ps1 -Version v1.0.0 -WhatIf        # show what would happen, change nothing
.EXAMPLE
  .\install.ps1 -Source C:\Downloads\aurasort   # install from a folder holding the ZIP and SHA256SUMS (offline)
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
  [string]$Version = 'v1.0.0',
  [string]$Repo = 'skuser404/aurasort',
  [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'Programs\AuraSort'),
  [string]$Source = '',
  [string]$StartMenuDir = (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'),
  [switch]$DesktopShortcut
)
$ErrorActionPreference = 'Stop'
$zipName = "aurasort-$Version.zip"

function Find-Python {
  # Why: AuraSort needs Python 3.10+ from python.org (or the Microsoft Store); the 'py' launcher is preferred.
  foreach ($cmd in @(@('py', '-3'), @('python'))) {
    $exe = Get-Command $cmd[0] -ErrorAction SilentlyContinue
    if (-not $exe) { continue }
    $args2 = @($cmd | Select-Object -Skip 1) + @('-c', 'import sys; print(sys.version_info[0] * 100 + sys.version_info[1])')
    try { $v = [int](& $exe.Source @args2 2>$null) } catch { continue }
    if ($v -ge 310) { return $exe.Source }
  }
  return $null
}

function Get-Release([string]$work) {
  # Why: a tagged release only, verified against its published SHA-256 before anything is unpacked.
  $zip = Join-Path $work $zipName; $sums = Join-Path $work 'SHA256SUMS'
  if ($Source) {
    Copy-Item (Join-Path $Source $zipName) $zip -WhatIf:$false; Copy-Item (Join-Path $Source 'SHA256SUMS') $sums -WhatIf:$false
  } else {
    $base = "https://github.com/$Repo/releases/download/$Version"
    Write-Host "Downloading $zipName from github.com/$Repo ..."
    Invoke-WebRequest -UseBasicParsing "$base/$zipName" -OutFile $zip
    Invoke-WebRequest -UseBasicParsing "$base/SHA256SUMS" -OutFile $sums
  }
  $want = (Get-Content $sums | Where-Object { $_ -match "\s\*?$([regex]::Escape($zipName))$" } | Select-Object -First 1)
  if (-not $want) { throw "SHA256SUMS has no line for $zipName. Not installing." }
  $want = ($want -split '\s+')[0].ToLower()
  $fs = [IO.File]::OpenRead($zip)   # .NET hashing works the same with -WhatIf
  try { $got = ([BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($fs)) -replace '-', '').ToLower() } finally { $fs.Dispose() }
  if ($got -ne $want) { Remove-Item $zip -Force -WhatIf:$false; throw "Checksum mismatch for $zipName (expected $want, got $got). The download was deleted. Not installing." }
  Write-Host "Checksum OK ($got)."
  return $zip
}

function New-Shortcut([string]$path, [string]$target, [string]$workdir) {
  $sh = New-Object -ComObject WScript.Shell
  $lnk = $sh.CreateShortcut($path)
  $lnk.TargetPath = $target; $lnk.WorkingDirectory = $workdir; $lnk.Description = 'AuraSort - Make your files easier.'
  $lnk.Save()
}

$py = Find-Python
if (-not $py) {
  Write-Warning 'Python 3.10 or newer was not found. Install it from https://www.python.org/downloads/ (tick "Add python.exe to PATH"), or run: winget install Python.Python.3.12'
  if (-not $WhatIfPreference) { exit 1 }
}
$work = Join-Path ([IO.Path]::GetTempPath()) ("aurasort-install-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Path $work -WhatIf:$false | Out-Null   # temp work folder: real even with -WhatIf, so the checksum is still verified
try {
  $zip = Get-Release $work
  $unpacked = Join-Path $work 'unpacked'
  Expand-Archive -Path $zip -DestinationPath $unpacked -WhatIf:$false
  # GitHub ZIPs contain one top folder (aurasort-v1.0.0\...). Use what is inside it, so there is no nested folder.
  $top = Get-ChildItem $unpacked
  $root = if ($top.Count -eq 1 -and $top[0].PSIsContainer) { $top[0].FullName } else { $unpacked }
  if (-not (Test-Path (Join-Path $root 'server.py'))) { throw 'The release does not look like AuraSort (no server.py). Not installing.' }
  if ($PSCmdlet.ShouldProcess($InstallDir, 'Install AuraSort files')) {
    if (Test-Path $InstallDir) { Remove-Item -Recurse -Force (Join-Path $InstallDir '*') -ErrorAction SilentlyContinue }   # the app folder only; your data lives in %USERPROFILE%\.aurasort
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    Copy-Item -Recurse -Force (Join-Path $root '*') $InstallDir
  }
  $launcher = Join-Path $InstallDir 'start.bat'
  if ($PSCmdlet.ShouldProcess($StartMenuDir, 'Add the AuraSort Start Menu shortcut')) {
    New-Item -ItemType Directory -Force -Path $StartMenuDir | Out-Null
    New-Shortcut (Join-Path $StartMenuDir 'AuraSort.lnk') $launcher $InstallDir
  }
  if ($DesktopShortcut -and $PSCmdlet.ShouldProcess('Desktop', 'Add an AuraSort shortcut')) {
    New-Shortcut (Join-Path ([Environment]::GetFolderPath('Desktop')) 'AuraSort.lnk') $launcher $InstallDir
  }
  if ($WhatIfPreference) { Write-Host 'WhatIf: nothing was installed.'; return }
  Write-Host ''
  Write-Host "AuraSort $Version is installed in $InstallDir"
  Write-Host 'Start it from the Start Menu (AuraSort), or run start.bat in that folder. It opens in your browser at http://localhost:8765/'
  Write-Host "To remove it: powershell -ExecutionPolicy Bypass -File `"$InstallDir\scripts\uninstall.ps1`""
} finally {
  Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue -WhatIf:$false
}
