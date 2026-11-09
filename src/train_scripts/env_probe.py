"""AI 協作：檢查訓練環境（Python、PyTorch、CUDA、顯示卡、已安裝的套件、硬碟空間）。"""
import importlib
import json
import platform
import shutil
import sys

info = {"python": sys.version.split()[0], "executable": sys.executable, "platform": platform.platform(), "packages": {}}
for name in ("torch", "transformers", "peft", "accelerate", "datasets", "bitsandbytes", "safetensors", "sentencepiece",
             "diffusers", "imageio", "imageio_ffmpeg", "ftfy", "f5_tts", "soundfile", "torchaudio", "huggingface_hub"):
    try:
        mod = importlib.import_module(name)
        info["packages"][name] = getattr(mod, "__version__", "已安裝")
    except Exception as exc:                       # noqa: BLE001  任何載入失敗都當成沒裝好
        info["packages"][name] = None if isinstance(exc, ImportError) else f"載入失敗：{type(exc).__name__}"
try:
    import torch
    info["cuda"] = bool(torch.cuda.is_available())
    info["torch_cuda"] = getattr(torch.version, "cuda", None)
    if info["cuda"]:
        p = torch.cuda.get_device_properties(0)
        info["gpu"] = p.name
        info["vram_gb"] = round(p.total_memory / 2 ** 30, 1)
        info["bf16"] = bool(torch.cuda.is_bf16_supported())
except Exception as exc:                           # noqa: BLE001
    info["cuda"] = False
    info["torch_error"] = f"{type(exc).__name__}: {exc}"
try:
    info["disk_free_gb"] = round(shutil.disk_usage(".").free / 2 ** 30, 1)
except OSError:
    pass
print("@@RESULT " + json.dumps(info, ensure_ascii=False), flush=True)
