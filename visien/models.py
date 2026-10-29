"""AI models for Visien's own stages (SeedVR2, RIFE, Face Restore): what is installed, and installing it.

Everything goes into the Visien folder:
    ai/site-packages   PyTorch, OpenCV, spandrel and the other packages the runners need
    models/            model weights, downloaded from their official sources

PyTorch comes in two builds: CUDA 12.8 for NVIDIA GeForce RTX, and AMD's ROCm build for Radeon RX 7000/9000 (and
Ryzen AI Max). Visien picks the one that matches the graphics card and can switch an installed runtime over.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from .config import CACHE_DIR, ROOT, TOOLS_DIR

AI_DIR = ROOT / "ai"
AI_SITE = AI_DIR / "site-packages"
MODELS_DIR = ROOT / "models"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
HF = "https://huggingface.co"
GH_RIFE = "https://github.com/Fannovel16/ComfyUI-Frame-Interpolation/releases/download/models/"
GH_FACE = "https://github.com/facefusion/facefusion-assets/releases/download/models-3.0.0/"

TORCH = ["torch==2.11.0+cu128", "torchvision==0.26.0+cu128"]
CUDA_INDEX = "https://download.pytorch.org/whl/cu128"
ROCM = "7.14.1"
ROCM_INDEX = "https://repo.amd.com/rocm/whl-multi-arch/"
# AMD graphics cards AMD builds PyTorch for on Windows (name pattern -> LLVM target).
AMD_ARCH = [(r"RX\s*90[67]0", "gfx1201"), (r"RX\s*9060", "gfx1200"), (r"RX\s*7900", "gfx1100"),
            (r"RX\s*7[78]00", "gfx1101"), (r"RX\s*7[56]00", "gfx1102"), (r"80[56]0S|Ryzen AI Max", "gfx1151"),
            (r"8[89]0M", "gfx1150")]
TORCH_DIRS = ("torch", "torchgen", "functorch", "torchvision", "rocm", "_rocm", "amd_torch", "amd-torch")


def torch_specs(backend: str, arch: str = "") -> list[str]:
    if backend == "rocm":
        return [f"torch[device-{arch}]==2.11.0+rocm{ROCM}", f"torchvision[device-{arch}]==0.26.0+rocm{ROCM}",
                f"rocm[libraries,device-{arch}]=={ROCM}"]
    return list(TORCH)
PACKAGES = ["numpy", "opencv-python-headless", "pillow", "safetensors", "einops", "omegaconf>=2.3.0",
            "diffusers>=0.33.1", "peft>=0.17.0", "rotary_embedding_torch>=0.5.3", "gguf", "tqdm", "psutil",
            "spandrel==0.4.2"]
# Small packages added after the first release; installed on top of an existing runtime without touching PyTorch.
ADDED_PACKAGES = {"spandrel": "spandrel==0.4.2"}

COMPONENTS: list[dict] = [
    {"id": "runtime", "title": "AI runtime", "group": "Required",
     "detail": "PyTorch 2.11 with CUDA 12.8, OpenCV and spandrel. Needed by every AI stage.",
     "size": 4_900_000_000, "kind": "pip", "license": "BSD-3 (PyTorch), Apache 2.0 (OpenCV), MIT (spandrel)"},
    {"id": "seedvr2_vae", "title": "SeedVR2 VAE", "group": "SeedVR2", "file": "seedvr2/ema_vae_fp16.safetensors",
     "url": f"{HF}/numz/SeedVR2_comfyUI/resolve/main/ema_vae_fp16.safetensors", "size": 501_000_000,
     "sha256": "20678548f420d98d26f11442d3528f8b8c94e57ee046ef93dbb7633da8612ca1", "license": "Apache 2.0",
     "detail": "Shared by every SeedVR2 model."},
    {"id": "seedvr2_3b_fp8", "title": "SeedVR2 3B · FP8", "group": "SeedVR2",
     "file": "seedvr2/seedvr2_ema_3b_fp8_e4m3fn.safetensors",
     "url": f"{HF}/numz/SeedVR2_comfyUI/resolve/main/seedvr2_ema_3b_fp8_e4m3fn.safetensors", "size": 3_400_000_000,
     "sha256": "3bf1e43ebedd570e7e7a0b1b60d6a02e105978f505c8128a241cde99a8240cff", "license": "Apache 2.0",
     "detail": "Recommended. Fast; fits 12-16 GB GPUs."},
    {"id": "seedvr2_3b_fp16", "title": "SeedVR2 3B · FP16", "group": "SeedVR2",
     "file": "seedvr2/seedvr2_ema_3b_fp16.safetensors",
     "url": f"{HF}/numz/SeedVR2_comfyUI/resolve/main/seedvr2_ema_3b_fp16.safetensors", "size": 6_800_000_000,
     "sha256": "2fd0e03a3dad24e07086750360727ca437de4ecd456f769856e960ae93e2b304", "license": "Apache 2.0",
     "detail": "Same model at full precision."},
    {"id": "seedvr2_7b_fp8", "title": "SeedVR2 7B · FP8", "group": "SeedVR2",
     "file": "seedvr2/seedvr2_ema_7b_fp8_e4m3fn_mixed_block35_fp16.safetensors",
     "url": f"{HF}/AInVFX/SeedVR2_comfyUI/resolve/main/seedvr2_ema_7b_fp8_e4m3fn_mixed_block35_fp16.safetensors",
     "size": 8_300_000_000, "sha256": "3d68b5ec0b295ae28092e355c8cad870edd00b817b26587d0cb8f9dd2df19bb2",
     "license": "Apache 2.0", "detail": "More detail, slower; uses Block Swap on 16 GB GPUs."},
    {"id": "seedvr2_7b_sharp_fp8", "title": "SeedVR2 7B sharp · FP8", "group": "SeedVR2",
     "file": "seedvr2/seedvr2_ema_7b_sharp_fp8_e4m3fn_mixed_block35_fp16.safetensors",
     "url": f"{HF}/AInVFX/SeedVR2_comfyUI/resolve/main/seedvr2_ema_7b_sharp_fp8_e4m3fn_mixed_block35_fp16.safetensors",
     "size": 8_300_000_000, "sha256": "0d2c5b8be0fda94351149c5115da26aef4f4932a7a2a928c6f184dda9186e0be",
     "license": "Apache 2.0", "detail": "7B tuned for crisper detail."},
    {"id": "rife426", "title": "RIFE 4.26", "group": "RIFE", "file": "rife/rife426.pth", "url": GH_RIFE + "rife426.pth",
     "size": 24_620_531, "sha256": "606421fe2148a9fdeca14e58d94dc339e87b87e0ebcc5dec84a50d6f488cfe7b",
     "license": "MIT", "detail": "Most accurate interpolation."},
    {"id": "rife417", "title": "RIFE 4.17", "group": "RIFE", "file": "rife/rife417.pth", "url": GH_RIFE + "rife417.pth",
     "size": 21_497_983, "sha256": "f6b1561354dda3b31606190cba1d1009ea001558c1b9c9cef2d03939bb381ee5",
     "license": "MIT", "detail": ""},
    {"id": "rife49", "title": "RIFE 4.9", "group": "RIFE", "file": "rife/rife49.pth", "url": GH_RIFE + "rife49.pth",
     "size": 21_345_274, "sha256": "e55fd00f3cc184e3c65961f4bb827a9da022e78eed36b055242c0ac30000d533",
     "license": "MIT", "detail": "Fastest."},
    {"id": "yunet", "title": "YuNet face detector", "group": "Face Restore",
     "file": "face/face_detection_yunet_2023mar.onnx",
     "url": "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/"
            "face_detection_yunet_2023mar.onnx", "size": 232_589,
     "sha256": "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4", "license": "MIT",
     "detail": "Finds faces and their landmarks. Needed by Face Restore."},
    {"id": "gfpgan", "title": "GFPGAN 1.4", "group": "Face Restore", "file": "face/GFPGANv1.4.pth",
     "url": "https://github.com/TencentARC/GFPGAN/releases/download/v1.3.0/GFPGANv1.4.pth", "size": 348_632_874,
     "sha256": "e2cd4703ab14f4d01fd1383a8a8b266f9a5833dacee8e6a79d3bf21a1b6be5ad", "license": "Apache 2.0",
     "replaces": ["face/gfpgan_1.4.onnx"], "detail": "Commercial use allowed."},
    {"id": "codeformer", "title": "CodeFormer", "group": "Face Restore", "file": "face/codeformer.pth",
     "url": "https://github.com/sczhou/CodeFormer/releases/download/v0.1.0/codeformer.pth", "size": 376_637_898,
     "sha256": "1009e537e0c2a07d4cabce6355f53cb66767cd4b4297ec7a4a64ca4b8a5684b7",
     "license": "NTU S-Lab License 1.0 · non-commercial use only", "accept": True,
     "pip": ["spandrel_extra_arches==0.2.0"], "pip_check": "spandrel_extra_arches",
     "replaces": ["face/codeformer.onnx"],
     "detail": "Most natural faces. Not allowed for commercial or client work without a licence from its authors."},
]
BY_ID = {c["id"]: c for c in COMPONENTS}
SEEDVR2_FILES = {Path(c["file"]).name: c["id"] for c in COMPONENTS if c["group"] == "SeedVR2" and c["id"] != "seedvr2_vae"}
RIFE_FILES = {Path(c["file"]).name: c["id"] for c in COMPONENTS if c["group"] == "RIFE"}
LICENCE_PATH = MODELS_DIR / "accepted-licences.json"

_lock = threading.Lock()
_jobs: dict[str, dict] = {}
_runtime_cache: dict = {}


# ---------------------------------------------------------------- status


INSTALLING = AI_SITE / ".visien-installing"  # present while an install runs or after one was interrupted
ROCM_SIZE = 1_500_000_000  # download for the AMD build of PyTorch (ROCm libraries for one GPU family)
_gpu_cache: dict = {}


def gpu() -> dict:
    """The graphics card the AI runtime should target: {"vendor": "nvidia"|"amd"|"", "name", "arch"}."""
    if "info" in _gpu_cache:
        return _gpu_cache["info"]
    names: list[str] = []
    if os.name == "nt":
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                                  "(Get-CimInstance Win32_VideoController).Name"], capture_output=True, text=True,
                                 timeout=30, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
            names = [n.strip() for n in out.stdout.splitlines() if n.strip()]
        except (OSError, subprocess.TimeoutExpired):
            names = []
    names += [n for n in os.environ.get("VISIEN_FAKE_GPU", "").split(";") if n]
    info = {"vendor": "", "name": "", "arch": ""}
    nvidia = next((n for n in names if "NVIDIA" in n.upper()), "")
    if nvidia:
        info.update(vendor="nvidia", name=nvidia)
    else:
        for name in names:
            arch = next((a for pattern, a in AMD_ARCH if re.search(pattern, name, re.I)), "")
            if arch:
                info.update(vendor="amd", name=name, arch=arch)
                break
        else:
            amd = next((n for n in names if "RADEON" in n.upper()), "")
            if amd:
                info.update(vendor="amd", name=amd)
    _gpu_cache["info"] = info
    return info


def wanted_backend() -> str:
    """rocm on a supported AMD card without an NVIDIA card next to it, otherwise cuda."""
    card = gpu()
    return "rocm" if card["vendor"] == "amd" and card["arch"] else "cuda"


def runtime_backend() -> str:
    """Build of the installed PyTorch: cuda, rocm, cpu, or "" when none is installed."""
    for info in AI_SITE.glob("torch-*.dist-info"):
        version = info.name[len("torch-"):-len(".dist-info")]
        return "rocm" if "+rocm" in version else "cuda" if "+cu" in version else "cpu"
    return ""


def backend_mismatch() -> bool:
    """The installed PyTorch was built for the other GPU vendor (e.g. a package copied from an NVIDIA PC)."""
    have = runtime_backend()
    return bool(gpu()["vendor"]) and have in ("cuda", "rocm") and have != wanted_backend()


def runtime_installed() -> bool:
    return (AI_SITE / "torch").is_dir() and (AI_SITE / "cv2").is_dir() and not INSTALLING.exists() and \
        all((AI_SITE / name).is_dir() for name in ADDED_PACKAGES) and not backend_mismatch()


def installed(component_id: str) -> bool:
    item = BY_ID[component_id]
    if item.get("kind") == "pip":
        return runtime_installed()
    if item.get("pip_check") and not (AI_SITE / item["pip_check"]).is_dir():
        return False
    return (MODELS_DIR / item["file"]).is_file()


def accepted() -> set[str]:
    try:
        return set(json.loads(LICENCE_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return set()


def status() -> dict:
    with _lock:
        jobs = {k: dict(v) for k, v in _jobs.items()}
    items = []
    for item in COMPONENTS:
        entry = {k: v for k, v in item.items() if k not in ("url", "sha256")}
        entry["installed"] = installed(item["id"])
        entry["job"] = jobs.get(item["id"])
        extra = [name for name in ADDED_PACKAGES if not (AI_SITE / name).is_dir()]
        if item.get("kind") == "pip":
            card = gpu()
            if wanted_backend() == "rocm":
                entry.update(size=ROCM_SIZE + 600_000_000, detail=(
                    f"PyTorch 2.11 for AMD Radeon (ROCm {ROCM}, {card['arch']}), OpenCV and spandrel. "
                    f"Needed by every AI stage. Your GPU: {card['name']}."))
            elif card["vendor"] == "amd":
                entry.update(detail=f"Visien sets up AMD's PyTorch for Radeon RX 7000/9000 and Ryzen AI Max. On "
                                    f"{card['name']} the AI stages would run on the CPU (very slow).")
            if not entry["installed"] and backend_mismatch() and (AI_SITE / "cv2").is_dir() \
                    and not INSTALLING.exists():
                target = "AMD Radeon (ROCm)" if wanted_backend() == "rocm" else "NVIDIA (CUDA)"
                entry.update(update=True, size=ROCM_SIZE if wanted_backend() == "rocm" else 3_300_000_000,
                             detail=f"Update: switches PyTorch to the {target} build for {card['name'] or 'this GPU'}. "
                                    "Models stay installed.")
            elif not entry["installed"] and (AI_SITE / "torch").is_dir() and extra and not INSTALLING.exists():
                # an older runtime: only small packages are missing
                entry.update(size=2_000_000, update=True,
                             detail="Update: adds " + ", ".join(extra) + " to the installed runtime (a few MB).")
        if entry["installed"] and item.get("file"):
            entry["size"] = (MODELS_DIR / item["file"]).stat().st_size
        items.append(entry)
    return {"components": items, "runtime": _runtime_cache.get("info"), "accepted": sorted(accepted()), "busy": any(
        j["state"] in ("queued", "downloading", "installing") for j in jobs.values()), "gpu": gpu(),
        "backend": runtime_backend(), "wanted_backend": wanted_backend()}


def required(settings: dict, kind: str) -> list[str]:
    """Components the enabled AI stages need."""
    from .stages import active_stages  # noqa: WPS433

    needed: list[str] = []
    stages_ = [s for s in active_stages(settings, kind) if s in ("seedvr2", "rife", "face_restore", "color_match")]
    if stages_:
        needed.append("runtime")
    if "seedvr2" in stages_:
        needed += ["seedvr2_vae", SEEDVR2_FILES.get(settings.get("seedvr2_model"), "seedvr2_3b_fp8")]
    if "rife" in stages_:
        needed.append(RIFE_FILES.get(settings.get("rife_model"), "rife426"))
    if "face_restore" in stages_:
        needed += ["yunet", "codeformer" if settings.get("face_model", "gfpgan") == "codeformer" else "gfpgan"]
    return needed


def missing(settings: dict, kind: str) -> list[str]:
    return [c for c in required(settings, kind) if not installed(c)]


def missing_message(ids: list[str]) -> str:
    names = ", ".join(BY_ID[i]["title"] for i in ids)
    total = sum(BY_ID[i]["size"] for i in ids) / 1024 ** 3
    return f"Install {names} (about {total:.1f} GB) in Settings › AI models to use this stage."


# ---------------------------------------------------------------- python for the AI runners


def ai_python() -> str:
    candidates = [ROOT / "runtime" / "python" / "python.exe", ROOT / ".venv" / "Scripts" / "python.exe",
                  Path(sys.executable).with_name("python.exe"), Path(sys.executable)]
    for path in candidates:
        if path.is_file():
            return str(path)
    return sys.executable


def ai_env() -> dict:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(AI_SITE), str(ROOT)])
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONNOUSERSITE"] = "1"
    env["OPENCV_LOG_LEVEL"] = "ERROR"
    if runtime_backend() == "rocm":
        # MIOpen's exhaustive kernel search makes the first run of every new image size very slow
        env.setdefault("MIOPEN_FIND_MODE", "FAST")
    return env


def runtime_check(refresh: bool = False) -> dict:
    if _runtime_cache.get("info") and not refresh:
        return _runtime_cache["info"]
    if not runtime_installed():
        return {"ok": False, "error": "AI runtime not installed"}
    try:
        out = subprocess.run([ai_python(), "-m", "visien.ai.run", "check"], cwd=str(ROOT), env=ai_env(),
                             capture_output=True, text=True, timeout=300, creationflags=NO_WINDOW)
        line = next((l for l in out.stdout.splitlines() if l.startswith("@@VZ-RESULT ")), "")
        info = json.loads(line[len("@@VZ-RESULT "):]) if line else {"error": (out.stderr or out.stdout)[-400:]}
        info["ok"] = bool(line)
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        info = {"ok": False, "error": str(exc)}
    _runtime_cache["info"] = info
    return info


# ---------------------------------------------------------------- installing


def _set(component_id: str, **values) -> None:
    with _lock:
        _jobs.setdefault(component_id, {"state": "queued", "progress": 0.0, "message": "", "error": ""}).update(values)


def _uv() -> str | None:
    for path in (TOOLS_DIR / "uv" / "uv.exe", ROOT.parent / "tools" / "uv" / "uv.exe"):
        if path.is_file():
            return str(path)
    return shutil.which("uv")


def _uv_install(component_id: str, packages: list[str], *, full: bool, index: str = "cuda") -> None:
    """uv pip install into ai/site-packages. full=False adds small packages next to an existing PyTorch.

    index: cuda (PyTorch's CUDA wheels + PyPI), rocm (AMD's ROCm wheels + PyPI) or pypi.
    """
    uv = _uv()
    if not uv:
        raise RuntimeError("uv was not found. Run install.bat once, then try again.")
    AI_SITE.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    cache = ROOT.parent / "tools" / "uv-cache"
    env["UV_CACHE_DIR"] = str(cache if cache.is_dir() else TOOLS_DIR / "uv-cache")
    env["UV_LINK_MODE"] = "copy"
    env["UV_HTTP_TIMEOUT"] = "600"
    cmd = [uv, "pip", "install", "--python", ai_python(), "--target", str(AI_SITE), *packages]
    if full and index in ("cuda", "rocm"):
        cmd += ["--index-url", CUDA_INDEX if index == "cuda" else ROCM_INDEX, "--extra-index-url",
                "https://pypi.org/simple", "--index-strategy", "unsafe-best-match"]
    elif full:
        pass
    else:
        cmd += ["--no-deps"]
    proc = subprocess.Popen(cmd, cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            creationflags=NO_WINDOW, text=True, encoding="utf-8", errors="replace")
    tail: list[str] = []
    for line in proc.stdout:
        line = line.strip()
        if line:
            tail.append(line)
            del tail[:-40]
            low = line.lower()
            if "downloading" in low or "prepared" in low or "installed" in low or "resolved" in low:
                _set(component_id, message=line[:160])
            if full and "prepared" in low:
                _set(component_id, progress=0.7)
            if full and "installed" in low:
                _set(component_id, progress=0.95)
    if proc.wait() != 0:
        raise RuntimeError("Package installation failed:\n" + "\n".join(tail[-12:]))


def _remove_torch() -> None:
    """Delete the installed PyTorch build (and AMD's ROCm libraries) before installing the other one."""
    for path in AI_SITE.iterdir():
        name = path.name.lower()
        if name.startswith(TORCH_DIRS) or name.startswith(("rocm_sdk", "rocm-sdk")):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)


def _install_runtime() -> None:
    _set("runtime", state="installing", message="Downloading and installing packages (several GB)", progress=0.05)
    AI_SITE.mkdir(parents=True, exist_ok=True)
    interrupted = INSTALLING.exists()
    want, arch = wanted_backend(), gpu()["arch"]
    switch = backend_mismatch()
    INSTALLING.write_text("1", encoding="utf-8")
    if not interrupted and switch and (AI_SITE / "cv2").is_dir():
        # same packages, PyTorch built for the other GPU vendor
        _set("runtime", message="Removing the previous PyTorch build", progress=0.08)
        _remove_torch()
        _uv_install("runtime", torch_specs(want, arch), full=True, index=want)
    elif not interrupted and (AI_SITE / "torch").is_dir() and (AI_SITE / "cv2").is_dir():
        # existing runtime: only add what newer Visien versions need
        extra = [spec for name, spec in ADDED_PACKAGES.items() if not (AI_SITE / name).is_dir()]
        if extra:
            _set("runtime", message="Adding " + ", ".join(extra), progress=0.5)
            _uv_install("runtime", extra, full=False)
    elif want == "rocm":
        if interrupted:
            _remove_torch()
        _uv_install("runtime", torch_specs("rocm", arch), full=True, index="rocm")
        _uv_install("runtime", PACKAGES, full=True, index="pypi")
    else:
        _uv_install("runtime", [*TORCH, *PACKAGES] + (["--reinstall"] if interrupted else []), full=True)
    INSTALLING.unlink(missing_ok=True)
    _runtime_cache.pop("info", None)
    info = runtime_check(refresh=True)
    if not info.get("ok"):
        INSTALLING.write_text("1", encoding="utf-8")
        raise RuntimeError("The AI runtime was installed but does not start: " + str(info.get("error", ""))[:400])


def _download(component_id: str) -> None:
    item = BY_ID[component_id]
    target = MODELS_DIR / item["file"]
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    request = urllib.request.Request(item["url"], headers={"User-Agent": "Visien/1.0"})
    digest = hashlib.sha256()
    started = time.time()
    with urllib.request.urlopen(request, timeout=60) as response, open(partial, "wb") as handle:
        total = int(response.headers.get("Content-Length") or item["size"])
        done = 0
        while True:
            chunk = response.read(1 << 20)
            if not chunk:
                break
            handle.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            speed = done / max(time.time() - started, 0.1)
            _set(component_id, state="downloading", progress=done / max(total, 1),
                 message=f"{done / 1e9:.2f} / {total / 1e9:.2f} GB · {speed / 1e6:.0f} MB/s")
    if item.get("sha256") and digest.hexdigest() != item["sha256"]:
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"{item['title']}: the download is damaged (checksum mismatch). Try again.")
    partial.replace(target)


def _worker(ids: list[str]) -> None:
    for component_id in ids:
        if installed(component_id):
            _set(component_id, state="done", progress=1.0, message="Installed")
            continue
        _set(component_id, state="downloading", progress=0.0, message="Starting", error="")
        item = BY_ID[component_id]
        try:
            if item.get("kind") == "pip":
                _install_runtime()
            else:
                if not (MODELS_DIR / item["file"]).is_file():
                    _download(component_id)
                if item.get("pip") and not (AI_SITE / item["pip_check"]).is_dir():
                    _set(component_id, state="installing", message="Adding " + ", ".join(item["pip"]), progress=0.99)
                    _uv_install(component_id, item["pip"], full=False)
                for old in item.get("replaces", []):
                    (MODELS_DIR / old).unlink(missing_ok=True)
            _set(component_id, state="done", progress=1.0, message="Installed")
        except Exception as exc:  # noqa: BLE001 - shown in Settings
            _set(component_id, state="error", message="Failed", error=str(exc)[:800])


def install(ids: list[str], accept_licence: bool = False) -> dict:
    ids = [i for i in ids if i in BY_ID]
    needs_accept = [i for i in ids if BY_ID[i].get("accept") and i not in accepted()]
    if needs_accept and not accept_licence:
        names = ", ".join(BY_ID[i]["title"] for i in needs_accept)
        raise ValueError(f"{names}: accept the licence first ({BY_ID[needs_accept[0]]['license']}).")
    if needs_accept:
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        LICENCE_PATH.write_text(json.dumps(sorted(accepted() | set(needs_accept))), encoding="utf-8")
    with _lock:  # check and mark in one step, so a double click cannot start two installs of the same file
        busy = [i for i, j in _jobs.items() if j["state"] in ("queued", "downloading", "installing")]
        ids = [i for i in ids if i not in busy]
        # runtime first, then small files, then the big ones
        ids.sort(key=lambda i: (BY_ID[i].get("kind") != "pip", BY_ID[i]["size"]))
        for component_id in ids:
            _jobs[component_id] = {"state": "queued", "progress": 0.0, "message": "Waiting", "error": ""}
    if ids:
        threading.Thread(target=_worker, args=(ids,), name="visien-models", daemon=True).start()
    return status()


def remove(component_id: str) -> dict:
    item = BY_ID[component_id]
    from .ai_engine import active  # noqa: WPS433

    if active():
        raise ValueError("An AI stage is running. Remove models when previews and renders have finished.")
    with _lock:
        job = _jobs.get(component_id)
        if job and job["state"] in ("queued", "downloading", "installing"):
            raise ValueError("This item is being installed.")
        _jobs.pop(component_id, None)
    if item.get("kind") == "pip":
        shutil.rmtree(AI_SITE, ignore_errors=True)
        _runtime_cache.pop("info", None)
    else:
        (MODELS_DIR / item["file"]).unlink(missing_ok=True)
    return status()


def cache_dir() -> Path:
    path = CACHE_DIR / "ai"
    path.mkdir(parents=True, exist_ok=True)
    return path
