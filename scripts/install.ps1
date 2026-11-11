<#
.SYNOPSIS
  Installs (or updates) AuraSort for the current user. No administrator rights are needed: do not use "Run as administrator".
.DESCRIPTION
  1. Checks for Python 3.10+ (offers to install Python 3.12 with winget, only if you say yes).
  2. Downloads the latest GitHub release (aurasort.zip) and checks its SHA-256 against the release's SHA256SUMS.
  3. Installs it to %LOCALAPPDATA%\AuraSort (your files and AuraSort's data in %USERPROFILE%\.aurasort are kept).
  4. Installs the optional packages (Pillow, pypdf) for your user, adds Start Menu and Desktop shortcuts,
     runs a self-test (server.py --doctor) and offers to start AuraSort.
  Safe to run again: that is how you update. Nothing outside the install folder and the two shortcuts is changed.
.EXAMPLE
  irm https://github.com/skuser404/AuraSort/releases/latest/download/install.ps1 | iex
.EXAMPLE
  & ([scriptblock]::Create((irm https://github.com/skuser404/AuraSort/releases/latest/download/install.ps1))) -WhatIf
.EXAMPLE
  .\install.ps1 -Source C:\Downloads\aurasort-release -Yes      # offline: a folder holding aurasort.zip and SHA256SUMS
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
  [string]$Version = 'latest',                 # 'latest' or a tag such as v1.1.0
  [string]$Repo = 'skuser404/AuraSort',        # exactly as GitHub shows it
  [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'AuraSort'),
  [string]$Source = '',
  [switch]$Yes,                                # answer "yes" to every question (unattended / CI)
  [switch]$NoStart,
  [switch]$NoShortcuts,
  [switch]$NoPackages
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'      # Invoke-WebRequest is many times slower on PowerShell 5.1 with the progress bar
$zipName = 'aurasort.zip'
$minPy = 310

function Say([string]$m) { Write-Host $m }
function Step([string]$m) { Write-Host ''; Write-Host "== $m" -ForegroundColor Cyan }
function Manual([string]$why, [string]$cmd) { Write-Host "  $why" -ForegroundColor Yellow; if ($cmd) { Write-Host "  Run this yourself:  $cmd" -ForegroundColor Yellow } }
function Ask([string]$q, [bool]$default) {
  if ($Yes) { return $true }
  if (-not [Environment]::UserInteractive) { return $default }
  $suffix = if ($default) { '[Y/n]' } else { '[y/N]' }
  try { $a = Read-Host "$q $suffix" } catch { return $default }
  if ([string]::IsNullOrWhiteSpace($a)) { return $default }
  return $a.Trim().ToLower().StartsWith('y')
}

# ---- 0. a safe starting point ----
# Old Windows/PowerShell 5.1 may not offer TLS 1.2 by default; GitHub requires it.
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch { }
$isAdmin = $false
try { $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) } catch { }
if ($isAdmin) {
  Write-Warning 'This PowerShell runs as Administrator. AuraSort does not need that, and it would be installed for the administrator account.'
  Write-Warning 'Close this window, open PowerShell normally (not "Run as administrator") and run the command again.'
  if (-not (Ask 'Continue anyway?' $false)) { exit 1 }
}
$full = [IO.Path]::GetFullPath($InstallDir)
foreach ($bad in @($env:WINDIR, (Join-Path $env:WINDIR 'System32'), $env:ProgramFiles, ${env:ProgramFiles(x86)})) {
  if ($bad -and ($full.TrimEnd('\') -ieq $bad.TrimEnd('\') -or $full.StartsWith($bad.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase))) {
    throw "Refusing to install into $full (a Windows system folder). Use the default, $env:LOCALAPPDATA\AuraSort."
  }
}

# ---- 1. Python 3.10+ ----
function Test-Python([string]$exe, [string[]]$pre) {
  try { $v = & $exe @pre -c 'import sys; print(sys.version_info[0] * 100 + sys.version_info[1])' 2>$null; return ([int]"$v".Trim()) -ge $minPy } catch { return $false }
}
function Find-Python {
  # Why: real installs first (full paths work even before PATH is refreshed). The Microsoft Store "python" alias in
  # WindowsApps opens the Store instead of running Python when Python is not installed, so it is never used blindly.
  $cands = @()
  if ($env:AURASORT_PYTHON) { $cands += $env:AURASORT_PYTHON }   # an exact interpreter (CI, or a Python in an unusual place)
  foreach ($root in @((Join-Path $env:LOCALAPPDATA 'Programs\Python'), $env:ProgramFiles, ${env:ProgramFiles(x86)})) {
    if ($root -and (Test-Path $root)) {
      $cands += Get-ChildItem -Path $root -Filter 'Python3*' -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending |
        ForEach-Object { Join-Path $_.FullName 'python.exe' } | Where-Object { Test-Path $_ }
    }
  }
  foreach ($c in $cands) { if (Test-Python $c @()) { return @{ exe = $c; pre = @() } } }
  $py = Get-Command py -ErrorAction SilentlyContinue
  if ($py -and (Test-Python $py.Source @('-3'))) {
    $real = & $py.Source -3 -c 'import sys; print(sys.executable)' 2>$null
    if ($real) { return @{ exe = "$real".Trim(); pre = @() } }
  }
  $p = Get-Command python -ErrorAction SilentlyContinue
  # The Store stub only prints "Python was not found" when given arguments, so testing it is safe; a real Store Python passes.
  if ($p -and (Test-Python $p.Source @())) { return @{ exe = $p.Source; pre = @() } }
  return $null
}
function Update-SessionPath {
  # Why: winget changes PATH for new windows only; this window must see the new Python too.
  $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
}

Step 'Checking for Python 3.10 or newer'
$py = Find-Python
if (-not $py) {
  $store = Get-Command python -ErrorAction SilentlyContinue
  if ($store -and $store.Source -like '*\WindowsApps\*') {
    Say '  Only the Microsoft Store "python" shortcut was found (it opens the Store; it is not Python).'
  }
  $winget = Get-Command winget -ErrorAction SilentlyContinue
  if ($winget -and (Ask '  Python 3.10+ is not installed. Install Python 3.12 now with winget (for your user only)?' $true)) {
    if ($PSCmdlet.ShouldProcess('Python 3.12', 'winget install')) {
      & $winget.Source install --id Python.Python.3.12 --exact --scope user --accept-package-agreements --accept-source-agreements --silent
      Update-SessionPath
      $py = Find-Python
    }
  }
  if (-not $py) {
    Manual 'Python 3.10 or newer is needed and was not found.' 'winget install --id Python.Python.3.12 --exact --scope user'
    Say '  Or download it from https://www.python.org/downloads/ and tick "Add python.exe to PATH". Then open a NEW PowerShell window and run the installer again.'
    if (-not $WhatIfPreference) { exit 1 }
  }
}
if ($py) { Say "  Using $($py.exe) ($(& $py.exe -c 'import sys; print(sys.version.split()[0])'))" }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  Say '  Git is not installed. It is NOT needed for this installer (only for the manual "git clone" method).'
  $winget = Get-Command winget -ErrorAction SilentlyContinue
  if ($winget -and -not $Yes -and (Ask '  Install Git as well (optional)?' $false) -and $PSCmdlet.ShouldProcess('Git', 'winget install')) {
    & $winget.Source install --id Git.Git --exact --scope user --accept-package-agreements --accept-source-agreements --silent
    Update-SessionPath
  }
}

# ---- 2. download and verify ----
function Get-Release([string]$work) {
  $zip = Join-Path $work $zipName; $sums = Join-Path $work 'SHA256SUMS'
  if ($Source) {
    Copy-Item (Join-Path $Source $zipName) $zip -WhatIf:$false; Copy-Item (Join-Path $Source 'SHA256SUMS') $sums -WhatIf:$false
  } else {
    $base = if ($Version -eq 'latest') { "https://github.com/$Repo/releases/latest/download" } else { "https://github.com/$Repo/releases/download/$Version" }
    Say "  Downloading $base/$zipName"
    try {
      Invoke-WebRequest -UseBasicParsing "$base/$zipName" -OutFile $zip
      Invoke-WebRequest -UseBasicParsing "$base/SHA256SUMS" -OutFile $sums
    } catch {
      Manual "The download failed ($($_.Exception.Message)). Check your internet connection, or that a release exists at https://github.com/$Repo/releases" ''
      Say '  Manual alternative (needs Git):  cd $HOME;  git clone https://github.com/skuser404/AuraSort.git;  cd AuraSort;  py -m pip install --user -r requirements.txt;  py server.py'
      throw
    }
  }
  $want = Get-Content $sums | Where-Object { $_ -match "\s\*?$([regex]::Escape($zipName))$" } | Select-Object -First 1
  if (-not $want) { throw "SHA256SUMS has no line for $zipName. Not installing." }
  $want = ($want -split '\s+')[0].ToLower()
  $fs = [IO.File]::OpenRead($zip)
  try { $got = ([BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($fs)) -replace '-', '').ToLower() } finally { $fs.Dispose() }
  if ($got -ne $want) { Remove-Item $zip -Force -WhatIf:$false; throw "Checksum mismatch for $zipName (expected $want, got $got). The download was removed. Not installing." }
  Say "  Checksum OK ($got)"
  return $zip
}

function New-Shortcut([string]$path, [string]$python, [string]$workdir) {
  # Why: the shortcut runs the exact Python found above (Unicode-safe: .lnk files store Unicode paths) in a window that
  # stays open on an error, so the message can be read.
  $sh = New-Object -ComObject WScript.Shell
  $lnk = $sh.CreateShortcut($path)
  $lnk.TargetPath = $env:ComSpec
  $lnk.Arguments = "/c `"`"$python`" server.py || pause`""
  $lnk.WorkingDirectory = $workdir; $lnk.Description = 'AuraSort - a local file organizer'
  $lnk.IconLocation = "$python,0"
  $lnk.Save()
}

$work = Join-Path ([IO.Path]::GetTempPath()) ('aurasort-install-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Path $work -WhatIf:$false | Out-Null   # a real temp folder even with -WhatIf, so the checksum is still verified
try {
  Step 'Downloading AuraSort'
  $zip = Get-Release $work
  $unpacked = Join-Path $work 'unpacked'
  Expand-Archive -Path $zip -DestinationPath $unpacked -WhatIf:$false
  $top = @(Get-ChildItem $unpacked)
  $root = if ($top.Count -eq 1 -and $top[0].PSIsContainer) { $top[0].FullName } else { $unpacked }   # no nested folder
  if (-not (Test-Path (Join-Path $root 'server.py'))) { throw 'The download does not look like AuraSort (no server.py). Not installing.' }
  $ver = (Select-String -Path (Join-Path $root 'core\config.py') -Pattern '^APP_VERSION = "(.+)"' | Select-Object -First 1).Matches.Groups[1].Value

  # ---- 3. install (staged, so a failure never leaves half an app) ----
  Step "Installing AuraSort $ver to $InstallDir"
  if ((Test-Path $InstallDir) -and -not (Test-Path (Join-Path $InstallDir 'server.py')) -and @(Get-ChildItem $InstallDir -Force).Count -gt 0) {
    throw "$InstallDir already exists and is not an AuraSort install. Not touching it. Choose another folder with -InstallDir."
  }
  if ($PSCmdlet.ShouldProcess($InstallDir, 'Install AuraSort files')) {
    $stage = "$InstallDir.new"; $old = "$InstallDir.old"
    foreach ($p in @($stage, $old)) { if (Test-Path $p) { Remove-Item -Recurse -Force $p } }   # leftovers of an earlier interrupted run (app files only)
    Copy-Item -Recurse $root $stage
    if (Test-Path $InstallDir) { Rename-Item $InstallDir (Split-Path $old -Leaf) }
    Rename-Item $stage (Split-Path $InstallDir -Leaf)
    if (Test-Path $old) { Remove-Item -Recurse -Force $old }   # the previous version's program files; your data is in %USERPROFILE%\.aurasort
    # A plain launcher for terminals (ASCII only: cmd.exe misreads non-English paths inside .cmd files).
    $cmd = "@echo off`r`ntitle AuraSort`r`ncd /d `"%~dp0`"`r`npy -3 server.py %* 2>nul || python server.py %*`r`nif errorlevel 1 pause`r`n"
    [IO.File]::WriteAllText((Join-Path $InstallDir 'AuraSort.cmd'), $cmd, (New-Object Text.ASCIIEncoding))
  }
  $legacy = Join-Path $env:LOCALAPPDATA 'Programs\AuraSort'
  if (Test-Path (Join-Path $legacy 'server.py')) { Say "  Note: an older copy is still in $legacy. You can remove it with its scripts\uninstall.ps1." }

  # ---- 4. optional packages ----
  if (-not $NoPackages -and $py) {
    Step 'Installing optional packages (Pillow, pypdf) for your user'
    if ($PSCmdlet.ShouldProcess('requirements.txt', 'pip install --user')) {
      & $py.exe -m pip install --user --disable-pip-version-check --quiet -r (Join-Path $InstallDir 'requirements.txt')
      if ($LASTEXITCODE -ne 0) { Manual 'The optional packages could not be installed. AuraSort works without them.' "`"$($py.exe)`" -m pip install --user -r `"$InstallDir\requirements.txt`"" }
      else { Say '  Done.' }
    }
  }

  # ---- 5. shortcuts ----
  if (-not $NoShortcuts) {
    Step 'Adding Start Menu and Desktop shortcuts'
    $startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
    if ($PSCmdlet.ShouldProcess($startMenu, 'Add the AuraSort shortcut')) { New-Shortcut (Join-Path $startMenu 'AuraSort.lnk') $py.exe $InstallDir }
    $desk = [Environment]::GetFolderPath('Desktop')   # the real Desktop, also when OneDrive moved it
    if ($desk -and $PSCmdlet.ShouldProcess($desk, 'Add the AuraSort shortcut')) { New-Shortcut (Join-Path $desk 'AuraSort.lnk') $py.exe $InstallDir }
  }
  if ($WhatIfPreference) { Say ''; Say 'WhatIf: nothing was installed or changed.'; return }

  # ---- 6. self-test ----
  Step 'Self-test (server.py --doctor)'
  Push-Location $InstallDir
  try { & $py.exe server.py --doctor | Select-Object -First 30 | ForEach-Object { Say "  $_" }; $doc = $LASTEXITCODE } finally { Pop-Location }
  if ($doc -ne 0) { Say '  The self-test found a problem (see FAIL above). AuraSort may still work; the README troubleshooting table explains each line.' }

  Say ''
  Say "AuraSort $ver is installed in $InstallDir" -ForegroundColor Green
  Say '  Start it from the Start Menu or the Desktop (AuraSort). It opens in your browser at http://localhost:8765/'
  Say "  Update: run the same install command again.   Remove: powershell -ExecutionPolicy Bypass -File `"$InstallDir\scripts\uninstall.ps1`""
  if (-not $NoStart -and (Ask 'Start AuraSort now?' $true)) { Start-Process -FilePath $py.exe -ArgumentList 'server.py' -WorkingDirectory $InstallDir }
} finally {
  Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue -WhatIf:$false
}
