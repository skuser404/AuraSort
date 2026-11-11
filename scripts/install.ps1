<#
.SYNOPSIS
  Installs (or updates) AuraSort for the signed-in user, with administrator permission (Windows asks once).
.DESCRIPTION
  Administrator permission is used so Windows lets AuraSort read your folders and install the prerequisites. AuraSort never
  touches Windows system folders. Without it (you decline the Windows prompt, or -NoElevate) it installs in standard mode.
  1. Lists what it will install and asks once. Then: Python 3.12 if no Python 3.10+ is found (winget, or the official
     python.org installer checked against a pinned SHA-256), pip and the optional packages (Pillow, pypdf).
  2. Downloads the latest GitHub release (aurasort.zip) and checks its SHA-256 against the release's SHA256SUMS.
  3. Installs it to %LOCALAPPDATA%\AuraSort of the signed-in user (your files and AuraSort's data in
     %USERPROFILE%\.aurasort are kept), adds Start Menu and Desktop shortcuts, runs a self-test and starts AuraSort.
  Safe to run again: that is how you update. Nothing outside the install folder and the two shortcuts is changed.
.EXAMPLE
  irm https://raw.githubusercontent.com/skuser404/AuraSort/main/scripts/install.ps1 | iex
.EXAMPLE
  irm https://raw.githubusercontent.com/skuser404/AuraSort/main/scripts/install.ps1 -OutFile install.ps1; powershell -ExecutionPolicy Bypass -File install.ps1 -WhatIf
.EXAMPLE
  .\install.ps1 -Source C:\Downloads\aurasort-release -Yes      # offline: a folder holding aurasort.zip and SHA256SUMS
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
  [string]$Version = 'latest',                 # 'latest' or a tag such as v1.1.0
  [string]$Repo = 'skuser404/AuraSort',        # exactly as GitHub shows it
  [string]$InstallDir = '',                    # default: %LOCALAPPDATA%\AuraSort of the signed-in user
  [string]$Source = '',
  [switch]$Yes,                                # answer "yes" to every question (unattended / CI)
  [switch]$NoStart,
  [switch]$NoShortcuts,
  [switch]$NoPackages,
  [switch]$NoElevate,                          # standard mode: do not ask Windows for administrator permission
  # Set by the installer itself when it restarts with administrator permission: the signed-in user's folders, which
  # differ from the administrator account's when someone else approved the Windows prompt.
  [string]$UserProfile = '', [string]$UserLocalAppData = '', [string]$UserAppData = '', [string]$UserDesktop = '',
  [switch]$PauseAtEnd
)
if ($null -eq $PSCmdlet) {
  # Why: "irm ... | iex" runs this text without a script around it: $PSCmdlet is null (every ShouldProcess call failed with
  # "You cannot call a method on a null-valued expression") and "exit" closed your PowerShell window, message and all.
  # So save the installer and run it as a real script in a child PowerShell; this window stays open.
  try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch { }
  $ProgressPreference = 'SilentlyContinue'
  $self = Join-Path ([IO.Path]::GetTempPath()) 'aurasort-install.ps1'
  $from = if ($env:AURASORT_INSTALLER_URL) { $env:AURASORT_INSTALLER_URL } else { "https://raw.githubusercontent.com/$Repo/main/scripts/install.ps1" }
  Invoke-WebRequest -UseBasicParsing $from -OutFile $self
  $extra = @(); if ($env:AURASORT_INSTALL_ARGS) {   # tests / CI only; "quoted values" may contain spaces
    $extra = @([regex]::Matches($env:AURASORT_INSTALL_ARGS, '"([^"]*)"|(\S+)') | ForEach-Object { if ($_.Groups[1].Success) { $_.Groups[1].Value } else { $_.Groups[2].Value } })
  }
  Push-Location $HOME   # never System32
  try { & (Get-Process -Id $PID).Path -NoProfile -ExecutionPolicy Bypass -File $self @extra } finally { Pop-Location }
  $code = $LASTEXITCODE
  Remove-Item $self -Force -ErrorAction SilentlyContinue
  Write-Host "The installer finished (exit code $code). You can close this window."
  $global:LASTEXITCODE = $code
  return
}
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
try { [Net.WebRequest]::DefaultWebProxy.Credentials = [Net.CredentialCache]::DefaultNetworkCredentials } catch { }   # company proxies
$isAdmin = $false
try { $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) } catch { }
# The app is for the signed-in user, also when an administrator account approved the Windows prompt.
if (-not $UserProfile) { $UserProfile = $env:USERPROFILE }
if (-not $UserLocalAppData) { $UserLocalAppData = $env:LOCALAPPDATA }
if (-not $UserAppData) { $UserAppData = $env:APPDATA }
if (-not $UserDesktop) { $UserDesktop = [Environment]::GetFolderPath('Desktop') }   # the real Desktop, also when OneDrive moved it
$otherAccount = -not ($UserProfile.TrimEnd('\') -ieq "$env:USERPROFILE".TrimEnd('\'))
if ($otherAccount) { $env:USERPROFILE = $UserProfile }   # the self-test and the first start use the user's home, not the administrator's
if (-not $InstallDir) { $InstallDir = Join-Path $UserLocalAppData 'AuraSort' }
Push-Location $UserProfile   # never C:\Windows\System32, where an administrator window starts

function Invoke-Elevated([string]$exe, [string]$argLine) {
  if ($env:AURASORT_FAKE_UAC -eq 'decline') { throw 'The operation was canceled by the user.' }   # tests only
  return Start-Process -FilePath $exe -Verb RunAs -ArgumentList $argLine -Wait -PassThru
}
if (-not $isAdmin -and -not $NoElevate -and -not $env:AURASORT_NO_ELEVATE -and -not $WhatIfPreference -and $PSCommandPath) {
  Step 'What this installer will do'
  Say "  - AuraSort into $InstallDir, with Start Menu and Desktop shortcuts, then start it in your browser"
  Say '  - Python 3.12, only if no Python 3.10 or newer is installed (winget, or the official python.org installer)'
  Say '  - pip and two optional packages, Pillow and pypdf (AuraSort also runs without them)'
  Say '  Windows asks for administrator permission next, so AuraSort can read your folders and install Python.'
  Say '  AuraSort never touches Windows system folders. If you decline, it installs in standard mode.'
  if (-not (Ask 'Continue?' $true)) { exit 1 }
  $q = { param($v) '"' + $v + '"' }
  $pass = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (& $q $PSCommandPath), '-Yes', '-PauseAtEnd',
    '-UserProfile', (& $q $UserProfile), '-UserLocalAppData', (& $q $UserLocalAppData), '-UserAppData', (& $q $UserAppData),
    '-UserDesktop', (& $q $UserDesktop), '-InstallDir', (& $q $InstallDir), '-Version', $Version, '-Repo', $Repo)
  if ($Source) { $pass += @('-Source', (& $q $Source)) }
  foreach ($s in 'NoStart', 'NoShortcuts', 'NoPackages') { if ($PSBoundParameters[$s]) { $pass += "-$s" } }
  try {
    $child = Invoke-Elevated (Get-Process -Id $PID).Path ($pass -join ' ')
    Say "  The administrator window finished (exit code $($child.ExitCode))."
    exit $child.ExitCode
  } catch {
    Say '  Administrator permission was not given. Installing in standard mode: AuraSort works the same; folders that'
    Say '  Windows protects (other users, some system places) are skipped during scans. Run the command again to change that.'
  }
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
  foreach ($root in @((Join-Path $UserLocalAppData 'Programs\Python'), (Join-Path $env:LOCALAPPDATA 'Programs\Python'), $env:ProgramFiles, ${env:ProgramFiles(x86)})) {
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
function Install-PythonOrg([string]$scope) {
  # Why: no winget (older Windows 10, Windows Server, LTSC). The official installer, checked against pinned SHA-256
  # values (python.org signs these files with Sigstore; the hashes were taken from verified downloads).
  $arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'arm64' } else { 'amd64' }
  $want = @{ amd64 = '67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb'; arm64 = '377ac8fd478987940088e879441e702a71b53164d2a1e6f1d51ff77a7e470258' }[$arch]
  $url = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-$arch.exe"
  $exe = Join-Path ([IO.Path]::GetTempPath()) "python-3.12.10-$arch.exe"
  Say "  Downloading $url"
  try { Invoke-WebRequest -UseBasicParsing $url -OutFile $exe } catch { Say "  The download failed ($($_.Exception.Message))."; return $null }
  $fs = [IO.File]::OpenRead($exe)
  try { $got = ([BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($fs)) -replace '-', '').ToLower() } finally { $fs.Dispose() }
  if ($got -ne $want) { Remove-Item $exe -Force; Say "  Checksum mismatch for the Python installer (expected $want, got $got). Not running it."; return $null }
  Say "  Checksum OK. Installing Python 3.12.10 (a minute or two, no window)"
  $all = if ($scope -eq 'machine') { 1 } else { 0 }
  $p = Start-Process -FilePath $exe -ArgumentList "/quiet InstallAllUsers=$all PrependPath=1 Include_launcher=1 Include_test=0" -Wait -PassThru
  Remove-Item $exe -Force -ErrorAction SilentlyContinue
  if ($p.ExitCode -ne 0) { Say "  The Python installer stopped with exit code $($p.ExitCode)."; return $null }
  Update-SessionPath
  return Find-Python
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
  # Installed for everyone when another account approved the Windows prompt (a per-user Python would land in that account).
  $scope = if ($otherAccount) { 'machine' } else { 'user' }
  $winget = Get-Command winget -ErrorAction SilentlyContinue
  if (Ask '  Python 3.10+ is not installed. Install Python 3.12 now?' $true) {
    if ($winget -and $PSCmdlet.ShouldProcess('Python 3.12', 'winget install')) {
      & $winget.Source install -e --id Python.Python.3.12 --scope $scope --accept-package-agreements --accept-source-agreements --silent
      Update-SessionPath
      $py = Find-Python
    }
    if (-not $py -and $PSCmdlet.ShouldProcess('Python 3.12.10', 'install from python.org')) { $py = Install-PythonOrg $scope }
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
    $released = $false
    try {
      Invoke-WebRequest -UseBasicParsing "$base/$zipName" -OutFile $zip
      Invoke-WebRequest -UseBasicParsing "$base/SHA256SUMS" -OutFile $sums
      $released = $true
    } catch { Say "  No release download ($($_.Exception.Message))." }
    if (-not $released) {
      # Why: no published release (or no release asset yet): fall back to GitHub's own source ZIP; Git is not needed.
      $ref = if ($Version -eq 'latest') { 'refs/heads/main' } else { "refs/tags/$Version" }
      $src = "https://github.com/$Repo/archive/$ref.zip"
      Say "  Downloading the source code instead: $src"
      Write-Warning 'There is no release checksum for this download, so it is not checksum-checked (it still comes from github.com over HTTPS).'
      try { Invoke-WebRequest -UseBasicParsing $src -OutFile $zip } catch {
        Manual "The download failed ($($_.Exception.Message)). Check your internet connection, or that https://github.com/$Repo exists." ''
        Say '  Manual alternative (needs Git):  cd $HOME;  git clone https://github.com/skuser404/AuraSort.git;  cd AuraSort;  py -m pip install --user -r requirements.txt;  py server.py'
        throw
      }
      return $zip
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
  # stays open on an error, so the message can be read. Installed with administrator permission, it starts AuraSort the
  # same way (Windows asks each time); for another approving account it also names the signed-in user's home folder.
  New-Item -ItemType Directory -Force (Split-Path $path) | Out-Null
  $sh = New-Object -ComObject WScript.Shell
  $lnk = $sh.CreateShortcut($path)
  $lnk.TargetPath = $env:ComSpec
  $setHome = if ($otherAccount) { "set `"USERPROFILE=$UserProfile`" && " } else { '' }
  $lnk.Arguments = "/c `"$setHome`"$python`" server.py || pause`""
  $lnk.WorkingDirectory = $workdir; $lnk.Description = 'AuraSort - a local file organizer'
  $lnk.IconLocation = "$python,0"
  $lnk.Save()
  if ($isAdmin) {   # the "Run as administrator" flag of a .lnk file: bit 0x20 of byte 0x15
    $b = [IO.File]::ReadAllBytes($path); $b[0x15] = $b[0x15] -bor 0x20; [IO.File]::WriteAllBytes($path, $b)
  }
}
function Wait-Server([int]$seconds) {
  # Why: say "running" only once it answers; the port is the one the server wrote down.
  $portFile = Join-Path $UserProfile '.aurasort\server.port'
  for ($i = 0; $i -lt $seconds * 4; $i++) {
    try {
      $port = (Get-Content $portFile -Raw -ErrorAction Stop | ConvertFrom-Json).port
      if ($port -and (Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$port/" -TimeoutSec 2).StatusCode -eq 200) { return [int]$port }
    } catch { }
    Start-Sleep -Milliseconds 250
  }
  return 0
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
      # An old pip cannot read newer wheels. Its warnings go to stderr, which PowerShell 5.1 would turn into a stopping error.
      $eap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
      & $py.exe -m pip install --user --disable-pip-version-check --quiet --upgrade pip 2>&1 | Out-Null
      $ErrorActionPreference = $eap
      & $py.exe -m pip install --user --disable-pip-version-check --quiet -r (Join-Path $InstallDir 'requirements.txt')
      if ($LASTEXITCODE -ne 0) { Manual 'The optional packages could not be installed. AuraSort works without them.' "`"$($py.exe)`" -m pip install --user -r `"$InstallDir\requirements.txt`"" }
      else { Say '  Done.' }
    }
  }

  # ---- 5. shortcuts ----
  if (-not $NoShortcuts) {
    Step 'Adding Start Menu and Desktop shortcuts'
    $startMenu = Join-Path $UserAppData 'Microsoft\Windows\Start Menu\Programs'
    if ($PSCmdlet.ShouldProcess($startMenu, 'Add the AuraSort shortcut')) { New-Shortcut (Join-Path $startMenu 'AuraSort.lnk') $py.exe $InstallDir }
    $desk = $UserDesktop
    if ($desk -and $PSCmdlet.ShouldProcess($desk, 'Add the AuraSort shortcut')) { New-Shortcut (Join-Path $desk 'AuraSort.lnk') $py.exe $InstallDir }
  }
  if ($WhatIfPreference) { Say ''; Say 'WhatIf: nothing was installed or changed.'; return }

  # ---- 6. self-test: a real 3-second scan of a temporary folder of known files ----
  Step 'Self-test'
  Push-Location $InstallDir
  try { & $py.exe server.py --self-test | ForEach-Object { Say "  $_" }; $selfTest = $LASTEXITCODE } finally { Pop-Location }
  if ($selfTest -ne 0) {
    $report = Join-Path $env:TEMP 'aurasort-doctor.txt'
    Push-Location $InstallDir
    try { & $py.exe server.py --doctor | Out-File -Encoding utf8 $report } finally { Pop-Location }
    Write-Warning "The self-test did not pass. A report is in $report (no file names in it)."
    Write-Warning "Send that file, or the output of this command, to the developer:  cd `"$InstallDir`"; py server.py --doctor"
  }

  Say ''
  Write-Host "AuraSort $ver is installed in $InstallDir" -ForegroundColor Green
  Say "  Mode: $(if ($isAdmin) { 'administrator (Windows asks when the shortcut starts it)' } else { 'standard' })"
  Say '  Start it from the Start Menu or the Desktop (AuraSort).'
  Say "  Update: run the same install command again.   Remove: powershell -ExecutionPolicy Bypass -File `"$InstallDir\scripts\uninstall.ps1`""
  if (-not $NoStart) {
    Step 'Starting AuraSort'
    Start-Process -FilePath $py.exe -ArgumentList 'server.py' -WorkingDirectory $InstallDir   # its own window; it opens the browser
    $port = Wait-Server 30
    if ($port) { Say "  AuraSort is running at http://localhost:$port/ . The first start scans your usual folders by itself." }
    else { Manual 'AuraSort did not answer within 30 seconds. Start it from the Desktop shortcut.' '' }
  }
} finally {
  Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue -WhatIf:$false
  if ($PauseAtEnd -and [Environment]::UserInteractive) { try { Read-Host 'Press Enter to close this window' | Out-Null } catch { } }
}
# Why: an explicit result. Without it, the exit code of the last program run inside the script leaks out (that made
# every CI install "fail"). 0 = installed and the self-test passed; 2 = installed, but the self-test needs a look.
if ($WhatIfPreference) { exit 0 }
exit $(if ($selfTest -eq 0) { 0 } else { 2 })
