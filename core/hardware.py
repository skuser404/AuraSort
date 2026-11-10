"""Hardware facts for choosing a local model size (no third-party packages)."""
import os
import shutil
import subprocess  # nosec B404  # fixed argument lists only

from . import config

TIMEOUT_S = 4


def ram_bytes():
    """Why: model size suggestions depend on installed memory (Windows API, macOS sysctl, Linux /proc/meminfo)."""
    try:
        if config.WIN:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            st = MEMORYSTATUSEX()
            st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            return int(st.ullTotalPhys) if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)) else 0
        if config.MAC:
            out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=TIMEOUT_S, check=False)  # nosec B603 B607
            return int(out.stdout.strip() or 0)
        with open("/proc/meminfo", encoding="ascii") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return 0


def gpu():
    """Why: an NVIDIA GPU (if nvidia-smi is present) makes larger models practical; nothing else is probed."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=TIMEOUT_S, check=False)  # nosec B603
        name, mem = [x.strip() for x in out.stdout.splitlines()[0].split(",")[:2]]
        return dict(name=name, vram_mb=int(float(mem)))
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def recommend(ram_gb):
    """Why: a simple, honest table: the biggest class that fits comfortably in memory."""
    best = None
    for min_gb, label, examples in config.AI_MODEL_TIERS:
        if ram_gb >= min_gb:
            best = dict(min_gb=min_gb, label=label, examples=list(examples))
    return best


def facts():
    """Why: one call for the setup screen."""
    ram = ram_bytes()
    gb = round(ram / 1024 ** 3, 1) if ram else 0
    return dict(ram_bytes=ram, ram_gb=gb, cores=os.cpu_count() or 1, gpu=gpu(), tier=recommend(gb),
                tiers=[dict(min_gb=a, label=b, examples=list(c)) for a, b, c in config.AI_MODEL_TIERS],
                vision_ok=gb >= config.AI_VISION_MIN_RAM_GB)
