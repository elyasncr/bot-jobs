"""GPU memory via nvidia-smi (stdlib only). `ollama ps` under-reports some models (gemma4)."""

import shutil
import subprocess


def gpu_memory_used_gb() -> float | None:
    """Memory in use on GPU 0, or None without nvidia-smi."""
    exe = shutil.which("nvidia-smi")
    if exe is None:
        return None
    try:
        out = subprocess.run(
            [exe, "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout
        return round(float(out.splitlines()[0]) / 1024, 1)
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None
