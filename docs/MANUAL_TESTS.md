# Manual tests on clean machines

CI runs the unit, install and browser tests on Windows, macOS and Linux runners. These checks need a real person on a
real, clean machine. Each one takes 5 to 15 minutes. Write down anything that differs from "You should see".

Before you start, publish a release (see the README, *For developers*), so the one-line installers have something to
download.

## 1. Windows Sandbox (a fresh Windows every time)

Windows 10/11 Pro: *Turn Windows features on or off* > **Windows Sandbox**, then start it from the Start menu.

1. In the Sandbox, open **PowerShell** normally (not "Run as administrator"). Run `cd $HOME`.
   You should see a prompt like `C:\Users\WDAGUtilityAccount>`, not `C:\WINDOWS\System32`.
2. `winget install --id Python.Python.3.12 --exact --scope user`. (winget may be missing in the Sandbox: download Python
   from python.org instead and tick *Add python.exe to PATH*.) Close PowerShell and open a new one.
3. `irm https://github.com/skuser404/AuraSort/releases/latest/download/install.ps1 | iex`
   You should see: *Checksum OK*, *Installing AuraSort 1.1.0 to ...\AppData\Local\AuraSort*, the self-test lines with
   `[OK  ]` (a `[WARN]` for *Free space* or *Drives* is fine), and *Start AuraSort now? [Y/n]*. Press Enter.
4. The browser opens: *Before you start* > tick > Continue > *This computer* (device name and user name) > set a PIN.
5. Quick Scan. You should see a result with more than 0 files, or a card explaining why (an empty Sandbox may truly have
   no files: put a few into Downloads first).
6. Check the Start Menu and Desktop shortcuts both start AuraSort.
7. Run the installer line again. You should see the same steps and *installed*; your PIN still works (data kept).

## 2. A new Windows user with a space and a non-English letter in the name

Settings > Accounts > Other users > *Add account* > "I don't have this person's sign-in information" > local user
`Test Ünï`, **Standard user** (not administrator). Sign in as that user.

1. Steps 1 to 5 of test 1.
2. Open Settings > Diagnostics > *Run diagnostics*. You should see *Administrator / root: normal user*, the Quick Scan
   folders under `~\...` with your user name shown as `<user>`, and *Test scan: N files*.
3. Put 3 files in Downloads, Quick Scan again: you should see 3 more files and the Images/Documents numbers adding up to
   the total on the dashboard (no percentage above 100%).

## 3. OneDrive (the "0 files" case)

On a PC signed in with a Microsoft account and OneDrive backing up Desktop/Documents/Pictures, with **Files On-Demand**
on (some files show a cloud icon in Explorer):

1. Quick Scan. You should see the OneDrive files counted (Scan page: *Exactly which folders* shows `...\OneDrive\Documents`
   with a *OneDrive* badge) and, on the dashboard, online-only files counted but not as space on this PC.
2. Preview an online-only file: you should see "online-only" and **no download** starts (the cloud icon stays).
3. `py server.py --doctor` in `%LOCALAPPDATA%\AuraSort`: *Quick Scan folder: Documents ... in OneDrive*, *Test scan: N
   files* with N > 0.

## 4. A Mac (Apple Silicon or Intel), a fresh user account

1. Terminal: `cd ~`, then `brew install python git` (install Homebrew first if needed).
2. `curl -fsSL https://github.com/skuser404/AuraSort/releases/latest/download/install.sh | sh`
   You should see *Checksum OK*, *Installing optional packages ... Done*, the self-test, *Start AuraSort now?*.
3. First scan of Desktop/Documents/Downloads: macOS asks for permission. Click *Allow*. Deny it once on purpose: the scan
   should show *macOS blocked access to these folders* with the Full Disk Access instructions, not silent zeros.
4. Double-click `~/Applications/AuraSort.command`: it starts without a Gatekeeper warning.
5. Send a file to the Trash from AuraSort: it is in Finder's Trash with *Put Back*.

## 5. Linux (Ubuntu or Fedora live USB is enough)

1. `sudo apt install python3 python3-venv git` (or `sudo dnf install python3 git`).
2. The `curl ... install.sh | sh` line. Then `aurasort` in a new terminal, and the *AuraSort* entry in the app menu.
3. Run once as root (`sudo -i`, then the doctor): you should see the administrator warning, and the scan still finds the
   files in `/root/Downloads` (a home inside a "system" folder used to give 0 files).

## 6. PIN and name clashes (any machine)

1. Wrong PIN 5 times on the unlock screen: you should see "Too many wrong PINs. Try again in 30 s" with a countdown.
   Close AuraSort (Ctrl+C), start it again: the wait is still there.
2. Settings > PIN lock > *Lock after 1 minute*. Leave it for 70 seconds: the unlock screen appears by itself.
3. Copy `photo.jpg` into a folder that already has a different `photo.jpg`. You should see "1 file already exists in this
   folder" with both sizes and dates. Choose *Replace*, enter the PIN. Then History > Undo: the old `photo.jpg` is back.
4. *Forgot PIN?* > type RESET: History and the index are empty, your files are where they were, setup starts again.

## 7. Android (Termux, experimental)

1. Install Termux from F-Droid. Run the one command from the README (*Android (Termux)*).
2. Allow storage access when asked. You should see "OK: your shared storage is readable" and the browser opening
   `http://localhost:8765/`.
3. Quick Scan finds files in Download and DCIM. Delete one file: it is in Settings > AuraSort trash, and Restore puts it
   back.

## If the friend's PC still shows 0 files

Ask them to open PowerShell normally (not as administrator) and run:

```powershell
cd $env:LOCALAPPDATA\AuraSort
py server.py --doctor
```

(or, for a git clone: `cd $HOME\AuraSort` then `py server.py --doctor`; for one folder:
`py server.py --doctor --folder "C:\Users\them\Downloads"`). Send back the whole output. It contains no file names; the
home folder is shown as `~` and the user name as `<user>`. The lines to look at first: *Python*, *Data folder*,
*Quick Scan folder: ...* (exists, readable, in OneDrive) and *Test scan* (files found, and every reason something was
skipped, with OS error codes such as `WinError 5`).
