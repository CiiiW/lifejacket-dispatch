"""Check this environment can actually run the aerial detector work.

    python doctor.py            # report
    python doctor.py --fix      # and try to install what is missing

    # from a notebook
    import doctor; doctor.check(fix=True)

Written because three separate environment assumptions broke in a row on a
GCP Workbench instance -- a missing Jupyter kernel, Python 3.10 rather than
3.11, and no FFmpeg -- each surfacing several cells into a notebook as an
unrelated-looking traceback. One preflight beats three mysteries.

Everything is checked independently, so one failure does not hide the rest.
"""

from __future__ import annotations

import argparse
import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent

OK, WARN, FAIL = "ok", "warn", "fail"
MARK = {OK: "  ok  ", WARN: " warn ", FAIL: " FAIL "}


def _run(args: list[str], timeout: int = 600) -> tuple[bool, str]:
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    return done.returncode == 0, (done.stdout or done.stderr or "").strip()


def install_ffmpeg() -> tuple[bool, str]:
    """apt if sudo works, else conda. conda ships ffprobe too, which matters."""
    if shutil.which("sudo") and shutil.which("apt-get"):
        env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
        subprocess.run(
            ["sudo", "-n", "apt-get", "update", "-qq"],
            capture_output=True, text=True, env=env, timeout=600, check=False,
        )
        done = subprocess.run(
            ["sudo", "-n", "apt-get", "install", "-y", "-qq", "ffmpeg"],
            capture_output=True, text=True, env=env, timeout=900, check=False,
        )
        if done.returncode == 0 and shutil.which("ffprobe"):
            return True, "installed with apt-get"
    if shutil.which("conda"):
        ok, out = _run(["conda", "install", "-y", "-q", "-c", "conda-forge", "ffmpeg"], 1800)
        if ok and shutil.which("ffprobe"):
            return True, "installed with conda"
        return False, out[-400:]
    return False, "neither sudo+apt-get nor conda is available"


def check(fix: bool = False) -> bool:
    rows: list[tuple[str, str, str]] = []

    # --- Python ---------------------------------------------------------
    version = sys.version_info
    rows.append((
        OK if version >= (3, 10) else FAIL,
        "python",
        f"{version.major}.{version.minor}.{version.micro}  ({sys.executable})",
    ))

    # --- the kernel actually running this -------------------------------
    in_venv = sys.prefix != sys.base_prefix
    rows.append((
        OK if in_venv else WARN,
        "virtualenv",
        sys.prefix if in_venv else
        "running in the base environment. In JupyterLab pick the kernel "
        '"Python (aerial detector)"',
    ))

    # --- ffmpeg ---------------------------------------------------------
    for binary in ("ffmpeg", "ffprobe"):
        found = shutil.which(binary)
        if not found and fix:
            installed, detail = install_ffmpeg()
            found = shutil.which(binary)
            if not found:
                rows.append((FAIL, binary, f"install failed: {detail}"))
                continue
        if found:
            ok, out = _run([binary, "-version"], 30)
            rows.append((OK, binary, out.splitlines()[0] if ok and out else found))
        else:
            rows.append((
                FAIL, binary,
                "missing. sudo apt-get install -y ffmpeg   (or "
                "conda install -c conda-forge ffmpeg)",
            ))

    # --- python packages ------------------------------------------------
    required = ["torch", "rfdetr", "supervision", "PIL", "numpy", "matplotlib", "yaml"]
    optional = ["ipywidgets", "pycocotools", "requests"]
    for name in required + optional:
        try:
            module = importlib.import_module(name)
            rows.append((OK, name, getattr(module, "__version__", "installed")))
        except ImportError as exc:
            rows.append((
                FAIL if name in required else WARN,
                name,
                f"{exc}. pip install -r research/aerial_detector/requirements.txt",
            ))

    # --- GPU ------------------------------------------------------------
    try:
        import torch

        if torch.cuda.is_available():
            free, total = torch.cuda.mem_get_info()
            rows.append((
                OK, "gpu",
                f"{torch.cuda.get_device_name(0)}  "
                f"{free / 1e9:.1f}/{total / 1e9:.1f} GB free",
            ))
        else:
            rows.append((
                WARN, "gpu",
                "no CUDA. Inference will run on CPU, roughly 20x slower. "
                "Fine for a short clip",
            ))
    except ImportError:
        rows.append((WARN, "gpu", "torch not installed, cannot check"))

    # --- DroneMegaDetector ----------------------------------------------
    try:
        sys.path.insert(0, str(HERE))
        import dmd

        cached = Path.home() / "aerial-data" / "weights" / Path(dmd.DMD_RELEASE_URL).name
        if cached.exists():
            info = dmd.describe_checkpoint(cached)
            names = tuple(info.get("class_names") or ())
            rows.append((
                OK if names == dmd.DMD_CLASSES else FAIL,
                "dmd weights",
                f"{cached.name}  classes={list(names)}  res={info.get('resolution')}",
            ))
        elif fix:
            path = dmd.ensure_dmd_weights()
            rows.append((OK, "dmd weights", f"downloaded {path}"))
        else:
            rows.append((
                WARN, "dmd weights",
                "not downloaded yet. doctor.py --fix, or the notebook fetches it",
            ))
    except Exception as exc:  # a broken import here should not hide the rest
        rows.append((FAIL, "dmd weights", str(exc)))

    width = max(len(name) for _, name, _ in rows)
    print()
    for status, name, detail in rows:
        print(f"[{MARK[status]}] {name:{width}}  {detail}")

    failures = [name for status, name, _ in rows if status == FAIL]
    warnings = [name for status, name, _ in rows if status == WARN]
    print()
    if failures:
        print(f"  {len(failures)} blocking problem(s): {', '.join(failures)}")
        if not fix:
            print("  Try: python doctor.py --fix")
    elif warnings:
        print(f"  usable, with {len(warnings)} warning(s): {', '.join(warnings)}")
    else:
        print("  everything checks out")
    return not failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fix", action="store_true", help="try to install what is missing"
    )
    args = parser.parse_args()
    return 0 if check(fix=args.fix) else 1


if __name__ == "__main__":
    sys.exit(main())
