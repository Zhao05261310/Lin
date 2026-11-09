"""AI 協作：文字轉圖片（本機開源模型：Stable Diffusion 1.5、SDXL、SDXL-Turbo、SD 3.5 Medium、FLUX.1 schnell／dev）。
用法：python image_gen.py --config config.json [--smoke]
記憶體模式：
  auto   ：依顯示卡自動決定。顯存不到 16 GB 時，FLUX 用 4-bit（NF4）量化，SD3.5 不載入 T5 文字編碼器，並開 CPU 卸載。
  normal ：整個模型放進顯示卡（最快，需要大顯存）。
  lowest ：逐層卸載（很慢，但 6～8 GB 顯示卡也跑得動大部分模型；需要較多系統記憶體）。"""
import os
import time

# @@COMMON@@

# 鍵：(Hugging Face 名稱, 種類, 預設寬, 預設高, 預設步數, 預設引導強度)
MODELS = {
    "sdxl-turbo": ("stabilityai/sdxl-turbo", "sdxl", 512, 512, 4, 0.0),
    "sdxl": ("stabilityai/stable-diffusion-xl-base-1.0", "sdxl", 1024, 1024, 30, 6.0),
    "sd15": ("stable-diffusion-v1-5/stable-diffusion-v1-5", "sd", 512, 512, 30, 7.0),
    "sd35-medium": ("stabilityai/stable-diffusion-3.5-medium", "sd3", 1024, 1024, 28, 4.5),
    "flux-schnell": ("black-forest-labs/FLUX.1-schnell", "flux", 768, 768, 4, 0.0),
    "flux-dev": ("black-forest-labs/FLUX.1-dev", "flux", 768, 768, 28, 3.5),
}


def dkw(fn, dtype):
    """diffusers 新舊版的 dtype 參數名稱不同。"""
    import inspect
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        params = {}
    return {"dtype": dtype} if "dtype" in params and "torch_dtype" not in params else {"torch_dtype": dtype}


def plan_memory(kind, cuda, vram_gb, mode):
    """決定怎麼放進顯示卡：回傳 {"offload": none／model／sequential, "quantize": bool, "drop_t5": bool}。"""
    if not cuda:
        return {"offload": "none", "quantize": False, "drop_t5": kind == "sd3"}
    if mode == "lowest":
        return {"offload": "sequential", "quantize": False, "drop_t5": False}
    if mode == "normal":
        return {"offload": "none", "quantize": False, "drop_t5": False}
    big = vram_gb >= 16
    if kind == "flux":
        return {"offload": "none" if vram_gb >= 30 else "model", "quantize": not big, "drop_t5": False}
    if kind == "sd3":
        return {"offload": "none" if big else "model", "quantize": False, "drop_t5": not big}
    if kind == "sdxl":
        return {"offload": "none" if vram_gb >= 12 else "model", "quantize": False, "drop_t5": False}
    return {"offload": "none" if vram_gb >= 6 else "model", "quantize": False, "drop_t5": False}


def _nf4(cls_module):
    """4-bit（NF4）量化設定；cls_module 是 diffusers 或 transformers（兩邊各有自己的 BitsAndBytesConfig）。"""
    import torch
    return cls_module.BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16)


def load_pipeline(kind, repo, cuda, plan):
    import torch
    half = (torch.bfloat16 if kind in ("flux", "sd3") else torch.float16) if cuda else torch.float32
    if kind == "sd":
        from diffusers import StableDiffusionPipeline
        return StableDiffusionPipeline.from_pretrained(repo, **dkw(StableDiffusionPipeline.from_pretrained, half))
    if kind == "sdxl":
        from diffusers import StableDiffusionXLPipeline
        kw = dkw(StableDiffusionXLPipeline.from_pretrained, half)
        if cuda:
            try:                                   # 官方有 fp16 版本的檔案：下載量少一半
                return StableDiffusionXLPipeline.from_pretrained(repo, variant="fp16", **kw)
            except (OSError, ValueError):
                pass
        return StableDiffusionXLPipeline.from_pretrained(repo, **kw)
    if kind == "sd3":
        from diffusers import StableDiffusion3Pipeline
        kw = dkw(StableDiffusion3Pipeline.from_pretrained, half)
        if plan["drop_t5"]:                        # 不載入 T5（約 9 GB）：省很多記憶體，長描述的理解會差一點
            kw.update(text_encoder_3=None, tokenizer_3=None)
        return StableDiffusion3Pipeline.from_pretrained(repo, **kw)
    if kind == "flux":
        from diffusers import FluxPipeline
        kw = dkw(FluxPipeline.from_pretrained, half)
        if plan["quantize"]:
            import diffusers
            import transformers
            from diffusers import FluxTransformer2DModel
            from transformers import T5EncoderModel
            emit("PROGRESS", stage="載入模型", msg="FLUX 用 4-bit（NF4）量化，讓 8 GB 顯示卡放得下（第一次要下載約 30 GB）")
            transformer = FluxTransformer2DModel.from_pretrained(
                repo, subfolder="transformer", quantization_config=_nf4(diffusers),
                **dkw(FluxTransformer2DModel.from_pretrained, torch.bfloat16))
            te2 = T5EncoderModel.from_pretrained(repo, subfolder="text_encoder_2", quantization_config=_nf4(transformers),
                                                 torch_dtype=torch.bfloat16)
            kw.update(transformer=transformer, text_encoder_2=te2)
        return FluxPipeline.from_pretrained(repo, **kw)
    raise ValueError(f"不認得的模型種類：{kind}")


def check_lora_loaded(pipe, kind):
    """diffusers 找不到對得上的權重時什麼都不載入、只印警告，後面才丟出看不懂的錯誤 → 這裡直接說清楚。"""
    try:
        loaded = {a for names in (pipe.get_list_adapters() or {}).values() for a in names}
    except Exception:                              # 舊版 diffusers 沒有這個方法：照舊
        return
    if "custom" not in loaded:
        raise RuntimeError(f"LoRA 跟這個模型（{kind.upper()}）不相容：檔案裡沒有這個模型用得上的權重。"
                           "影片 LoRA 不能用在圖片模型；SD 1.5、SDXL、FLUX 的 LoRA 也不能互用。")


def round_size(v, kind):
    step = 16 if kind in ("flux", "sd3") else 8
    return max(step * 4, int(v) // step * step)


def main():
    cfg = load_config()
    import torch
    smoke = cfg["smoke"]
    cuda = torch.cuda.is_available() and (not smoke or bool(cfg.get("smoke_gpu")))
    key = cfg.get("model", "sdxl-turbo")
    if key not in MODELS:
        raise ValueError(f"不認得的圖片模型：{key}（可用：{', '.join(MODELS)}）")
    repo, kind, dw, dh, dsteps, dguide = MODELS[key]
    repo = cfg.get("repo") or repo               # 進階：換成其他同架構的模型（例如社群微調版）
    vram = torch.cuda.get_device_properties(0).total_memory / 2 ** 30 if cuda else 0
    plan = plan_memory(kind, cuda, vram, cfg.get("memory", "auto"))
    if kind == "flux" and not cuda and not smoke and not cfg.get("allow_cpu"):
        raise RuntimeError("FLUX 沒有 NVIDIA 顯示卡跑不動（CPU 生成一張要好幾個小時）。請改用 SD 1.5／SDXL-Turbo，或用雲端 GPU。")
    if smoke and not cfg.get("repo"):
        emit("PROGRESS", stage="載入模型", msg="極小的測試模型")
        pipe, kind = tiny_sd_pipeline(), "sd"
    else:
        emit("PROGRESS", stage="載入模型", msg=f"{repo}（第一次會下載好幾 GB）")
        pipe = load_pipeline(kind, repo, cuda, plan)
    if cuda:
        if plan["offload"] == "sequential":
            pipe.enable_sequential_cpu_offload()
        elif plan["offload"] == "model":
            pipe.enable_model_cpu_offload()     # 8 GB 顯示卡：只把正在用的部分放進顯示卡
        else:
            pipe.to("cuda")
        vae = getattr(pipe, "vae", None)
        for fn in ("enable_tiling", "enable_slicing"):
            if vae is not None and hasattr(vae, fn):
                getattr(vae, fn)()
    if hasattr(pipe, "set_progress_bar_config"):
        pipe.set_progress_bar_config(disable=True)
    emit("LOG", msg=f"記憶體配置：{'顯示卡 ' + format(vram, '.1f') + ' GB' if cuda else 'CPU'}；卸載＝{plan['offload']}"
                    f"{'，4-bit 量化' if plan['quantize'] else ''}{'，不載入 T5' if plan['drop_t5'] else ''}")
    lora = cfg.get("lora_path") or ""
    if lora:
        emit("PROGRESS", stage="載入 LoRA", msg=lora)
        if os.path.isfile(lora):
            pipe.load_lora_weights(os.path.dirname(lora), weight_name=os.path.basename(lora), adapter_name="custom")
        else:
            pipe.load_lora_weights(lora, adapter_name="custom")
        check_lora_loaded(pipe, kind)
        pipe.set_adapters(["custom"], adapter_weights=[float(cfg.get("lora_scale", 1.0))])
    width = 64 if smoke else round_size(cfg.get("width") or dw, kind)
    height = 64 if smoke else round_size(cfg.get("height") or dh, kind)
    steps = 2 if smoke else max(1, int(cfg.get("steps") or dsteps))
    guidance = float(dguide if cfg.get("guidance") in (None, "") else cfg["guidance"])
    count = max(1, min(8, int(cfg.get("count", 1))))
    seed = int(cfg.get("seed", 42))
    out_dir = cfg.get("out_dir", ".")
    os.makedirs(out_dir, exist_ok=True)
    started = time.time()
    total = steps * count
    done = [0]

    def on_step(_pipe, _i, _t, kwargs):
        done[0] += 1
        spent = time.time() - started
        emit("PROGRESS", stage="生成", step=done[0], total=total, eta_min=round(spent / done[0] * (total - done[0]) / 60, 1),
             vram=vram_text())
        return kwargs
    paths = []
    stamp = time.strftime("%Y%m%d_%H%M%S")
    for n in range(count):                       # 一張一張生成：顯存只要一張的量，每張的種子都記下來
        kw = dict(prompt=cfg.get("prompt") or "test", width=width, height=height, num_inference_steps=steps,
                  guidance_scale=guidance, generator=torch.Generator(device="cpu").manual_seed(seed + n),
                  callback_on_step_end=on_step)
        if kind != "flux" and cfg.get("negative_prompt") and guidance > 1:
            kw["negative_prompt"] = cfg["negative_prompt"]
        if kind == "flux":
            kw["max_sequence_length"] = 256 if key == "flux-schnell" else 512
        image = pipe(**kw).images[0]
        path = os.path.join(out_dir, f"圖片_{stamp}_{n + 1}.png")
        meta = {"prompt": kw["prompt"], "negative_prompt": kw.get("negative_prompt", ""), "model": repo, "seed": seed + n,
                "steps": steps, "guidance": guidance, "width": width, "height": height, "lora": lora}
        try:
            from PIL import PngImagePlugin
            info = PngImagePlugin.PngInfo()
            info.add_text("parameters", _json.dumps(meta, ensure_ascii=False))
            image.save(path, pnginfo=info)
        except ImportError:
            image.save(path)
        paths.append(path)
        emit("LOG", msg=f"第 {n + 1}／{count} 張完成：{path}")
    with open(os.path.join(out_dir, f"生成設定_{stamp}.json"), "w", encoding="utf-8") as f:
        _json.dump({"model": repo, "prompt": cfg.get("prompt"), "negative_prompt": cfg.get("negative_prompt", ""),
                    "seed": seed, "count": count, "steps": steps, "guidance": guidance, "width": width, "height": height,
                    "lora": lora, "memory": plan, "images": [os.path.basename(p) for p in paths]}, f, ensure_ascii=False, indent=2)
    emit("RESULT", images=paths, image=paths[0], seconds=round(time.time() - started, 1), model=key, width=width, height=height)


if __name__ == "__main__":
    run_main(main)
