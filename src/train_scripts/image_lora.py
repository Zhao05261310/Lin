"""AI 協作：用自己的圖片訓練圖片模型的 LoRA（Stable Diffusion 1.5／SDXL），訓練完可以在「圖片生成」套用。
資料：一個資料夾放圖片（png、jpg、webp），可以在旁邊放同名的 .txt 寫描述；沒有描述的圖片只用「觸發詞」。
做法（8 GB 顯示卡也能跑）：先把圖片編碼成 latent、描述編碼成文字向量並存在記憶體裡（之後就不需要 VAE 與文字編碼器），
再只把 UNet 放進顯示卡，用梯度檢查點、8-bit AdamW 訓練 LoRA；訓練完用 LoRA 生成一張預覽圖。
用法：python image_lora.py --config config.json [--smoke]"""
import glob
import os
import random
import time

# @@COMMON@@

BASES = {"sd15": ("stable-diffusion-v1-5/stable-diffusion-v1-5", "sd", 512),
         "sdxl": ("stabilityai/stable-diffusion-xl-base-1.0", "sdxl", 768)}
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp")


def list_images(folder, trigger=""):
    """[(圖片路徑, 描述)]：有同名 .txt 就用「觸發詞＋描述」，沒有就只用觸發詞。"""
    items, no_caption = [], 0
    for path in sorted(glob.glob(os.path.join(folder, "*"))):
        if os.path.splitext(path)[1].lower() not in IMAGE_EXT:
            continue
        cap_path = os.path.splitext(path)[0] + ".txt"
        caption = open(cap_path, "r", encoding="utf-8").read().strip() if os.path.isfile(cap_path) else ""
        if not caption:
            no_caption += 1
        text = ", ".join(x for x in (trigger.strip(), caption) if x)
        if not text:
            raise ValueError(f"{os.path.basename(path)} 沒有描述，也沒有設定觸發詞：至少要有一個，模型才知道要學什麼")
        items.append((path, text))
    if not items:
        raise ValueError("資料夾裡沒有圖片（支援 png、jpg、webp、bmp）")
    if no_caption:
        log(f"{no_caption} 張圖片沒有 .txt 描述，只用觸發詞「{trigger}」")
    return items


def load_image(path, size, flip=False):
    """短邊縮放到 size 再從中間裁成 size×size；回傳 (3, size, size) 的 -1～1 張量、原始尺寸 (h, w)、裁切左上角 (top, left)。"""
    import numpy as np
    import torch
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    w, h = im.size
    scale = size / min(w, h)
    nw, nh = max(size, round(w * scale)), max(size, round(h * scale))
    im = im.resize((nw, nh), Image.BICUBIC)
    left, top = (nw - size) // 2, (nh - size) // 2
    im = im.crop((left, top, left + size, top + size))
    if flip:
        im = ImageOps.mirror(im)
    t = torch.from_numpy(np.asarray(im).copy()).permute(2, 0, 1).float() / 127.5 - 1.0
    return t, (h, w), (top, left)


def load_base(key, repo, kind, cuda):
    import torch
    half = torch.float16 if cuda else torch.float32
    if kind == "sdxl":
        from diffusers import StableDiffusionXLPipeline
        try:
            return StableDiffusionXLPipeline.from_pretrained(repo, torch_dtype=half, variant="fp16" if cuda else None)
        except (OSError, ValueError):
            return StableDiffusionXLPipeline.from_pretrained(repo, torch_dtype=half)
    from diffusers import StableDiffusionPipeline
    return StableDiffusionPipeline.from_pretrained(repo, torch_dtype=half, safety_checker=None, requires_safety_checker=False)


def main():
    cfg = load_config()
    import math
    import torch
    import torch.nn.functional as F
    from diffusers import DDPMScheduler
    from diffusers.utils import convert_state_dict_to_diffusers
    from peft import LoraConfig
    from peft.utils import get_peft_model_state_dict
    smoke = cfg["smoke"]
    cuda = torch.cuda.is_available() and (not smoke or bool(cfg.get("smoke_gpu")))
    dev = torch.device("cuda" if cuda else "cpu")
    wdtype = (torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16) if cuda else torch.float32
    key = cfg.get("base", "sdxl")
    if key not in BASES:
        raise ValueError(f"不認得的底模：{key}（可用：{', '.join(BASES)}）")
    repo, kind, default_size = BASES[key]
    repo = cfg.get("repo") or repo
    size = 64 if smoke else int(cfg.get("resolution") or default_size) // 64 * 64
    trigger = cfg.get("trigger", "").strip()
    samples = list_images(cfg["data_dir"], trigger)
    out_dir = cfg["out_dir"]
    os.makedirs(out_dir, exist_ok=True)
    log(f"資料 {len(samples)} 張；底模 {key}；解析度 {size}×{size}；{'顯示卡 ' + str(wdtype).replace('torch.', '') if cuda else 'CPU'}")

    # 1. 載入底模，把圖片與描述編碼好存在記憶體裡
    emit("PROGRESS", stage="載入底模", msg=repo if not smoke else "極小的測試模型")
    if smoke and not cfg.get("repo"):
        pipe, kind = tiny_sd_pipeline(), "sd"
    else:
        pipe = load_base(key, repo, kind, cuda)
    if hasattr(pipe, "set_progress_bar_config"):
        pipe.set_progress_bar_config(disable=True)
    vae = pipe.vae
    vae.to(dev, dtype=torch.float32)            # VAE 用 fp32 編碼（SDXL 的 VAE 在 fp16 會變成 NaN）
    text_encoders = [m for m in (pipe.text_encoder, getattr(pipe, "text_encoder_2", None)) if m is not None]
    for m in text_encoders:
        m.to(dev)
    flip = bool(cfg.get("flip", True))
    cached = []
    emit("PROGRESS", stage="編碼資料", msg="把圖片與描述轉成 latent 與文字向量（只做一次）")
    with torch.no_grad():
        for i, (path, caption) in enumerate(samples):
            if kind == "sdxl":
                emb, _neg, pooled, _negp = pipe.encode_prompt(caption, device=dev, num_images_per_prompt=1,
                                                              do_classifier_free_guidance=False)
            else:
                emb, _neg = pipe.encode_prompt(caption, dev, 1, False)
                pooled = None
            for flipped in ((False, True) if flip else (False,)):
                px, orig, crop = load_image(path, size, flipped)
                lat = vae.encode(px[None].to(dev, torch.float32)).latent_dist.sample() * vae.config.scaling_factor
                item = {"lat": lat.cpu(), "emb": emb.cpu(), "pooled": pooled.cpu() if pooled is not None else None,
                        "time_ids": torch.tensor([[orig[0], orig[1], crop[0], crop[1], size, size]], dtype=torch.float32)}
                cached.append(item)
            emit("PROGRESS", stage="編碼資料", step=i + 1, total=len(samples))
    vae.to("cpu")
    for m in text_encoders:
        m.to("cpu")
    if cuda:
        torch.cuda.empty_cache()

    # 2. 訓練 LoRA（只有 UNet 在顯示卡上）
    emit("PROGRESS", stage="準備訓練", msg="UNet 放進顯示卡、加上 LoRA")
    unet = pipe.unet
    unet.requires_grad_(False)
    unet.to(dev, dtype=wdtype)
    if cuda and cfg.get("gradient_checkpointing", True):
        unet.enable_gradient_checkpointing()
    rank = int(cfg.get("lora_r", 16))
    unet.add_adapter(LoraConfig(r=rank, lora_alpha=int(cfg.get("lora_alpha", rank)), init_lora_weights="gaussian",
                                target_modules=["to_q", "to_k", "to_v", "to_out.0"]))
    params = [p for p in unet.parameters() if p.requires_grad]
    for p in params:
        p.data = p.data.float()                 # LoRA 權重用 fp32 訓練比較穩
    log(f"可訓練參數 {sum(p.numel() for p in params) / 1e6:.2f} M")
    lr = float(cfg.get("lr", 1e-4))
    opt = None
    if cuda and cfg.get("adam8bit", True):
        try:
            import bitsandbytes as bnb
            opt = bnb.optim.AdamW8bit(params, lr=lr, weight_decay=1e-2)
            log("優化器：8-bit AdamW（省顯存）")
        except Exception as exc:                 # noqa: BLE001  沒裝或這台電腦不支援就用一般的
            log(f"8-bit AdamW 不能用（{type(exc).__name__}），改用一般 AdamW")
    if opt is None:
        opt = torch.optim.AdamW(params, lr=lr, weight_decay=1e-2)
    sched = DDPMScheduler.from_config(pipe.scheduler.config)
    pred_type = sched.config.get("prediction_type", "epsilon")
    steps = int(cfg.get("smoke_steps", 3)) if smoke else int(cfg.get("steps", 1000))
    save_every = int(cfg.get("save_every", 500))
    pipe_cls = type(pipe)
    unet.train()
    started, losses = time.time(), []

    def save(tag):
        path = os.path.join(out_dir, tag)
        pipe_cls.save_lora_weights(path, unet_lora_layers=convert_state_dict_to_diffusers(get_peft_model_state_dict(unet)))
        with open(os.path.join(path, "模型資訊.json"), "w", encoding="utf-8") as f:
            _json.dump({"base": key, "repo": repo, "arch": "sdxl" if kind == "sdxl" else "sd15", "trigger": trigger,
                        "resolution": size, "steps": step, "rank": rank, "lr": lr}, f, ensure_ascii=False, indent=2)
        return path

    step = 0
    for step in range(1, steps + 1):
        item = random.choice(cached)
        latents = item["lat"].to(dev, wdtype)
        noise = torch.randn_like(latents)
        if cfg.get("noise_offset", 0.05):
            noise = noise + float(cfg.get("noise_offset", 0.05)) * torch.randn(latents.shape[0], latents.shape[1], 1, 1,
                                                                              device=dev, dtype=wdtype)
        t = torch.randint(0, sched.config.num_train_timesteps, (latents.shape[0],), device=dev).long()
        noisy = sched.add_noise(latents, noise, t)
        kw = {"encoder_hidden_states": item["emb"].to(dev, wdtype)}
        if kind == "sdxl":
            kw["added_cond_kwargs"] = {"text_embeds": item["pooled"].to(dev, wdtype), "time_ids": item["time_ids"].to(dev, wdtype)}
        with torch.autocast("cuda", dtype=wdtype, enabled=cuda):
            pred = unet(noisy, t, **kw).sample
        target = noise if pred_type == "epsilon" else sched.get_velocity(latents, noise, t)
        loss = F.mse_loss(pred.float(), target.float())
        if not math.isfinite(loss.item()):
            raise RuntimeError(f"第 {step} 步的損失變成 {loss.item()}（訓練發散）：請把學習率調小（例如 5e-5）再試")
        loss.backward()
        torch.nn.utils.clip_grad_norm_(params, 1.0)
        opt.step()
        opt.zero_grad(set_to_none=True)
        losses.append(loss.item())
        spent = time.time() - started
        emit("PROGRESS", stage="訓練", step=step, total=steps, loss=round(sum(losses[-20:]) / len(losses[-20:]), 4),
             eta_min=round(spent / step * (steps - step) / 60, 1), vram=vram_text())
        if save_every and step % save_every == 0 and step < steps:
            log(f"已存檔：{save(f'checkpoint-{step}')}")
    final = save("lora")
    loss_avg = round(sum(losses[-20:]) / len(losses[-20:]), 4) if losses else None
    minutes = round((time.time() - started) / 60, 1)

    # 3. 用剛訓練好的 LoRA 生成一張預覽圖（失敗不影響訓練結果）
    preview = ""
    if cfg.get("preview", True):
        emit("PROGRESS", stage="生成預覽", msg="用剛訓練好的 LoRA 畫一張")
        try:
            del opt
            unet.eval()
            unet.requires_grad_(False)
            if cuda:
                unet.disable_gradient_checkpointing()
                torch.cuda.empty_cache()
                vae.to(dtype=torch.float32)
                pipe.enable_model_cpu_offload()
            prompt = cfg.get("preview_prompt") or samples[0][1]
            image = pipe(prompt=prompt, height=size, width=size, num_inference_steps=2 if smoke else 25,
                         guidance_scale=6.0 if kind == "sdxl" else 7.0,
                         generator=torch.Generator(device="cpu").manual_seed(int(cfg.get("seed", 42)))).images[0]
            preview = os.path.join(out_dir, f"預覽_{time.strftime('%Y%m%d_%H%M%S')}.png")
            image.save(preview)
            log(f"預覽圖：{preview}（描述：{prompt}）")
        except Exception as exc:                 # noqa: BLE001
            log(f"預覽圖沒有生成成功（{type(exc).__name__}: {exc}）；LoRA 已經存好，可以到「圖片生成」試")
            preview = ""
    emit("RESULT", lora=final, preview=preview, steps=steps, loss=loss_avg, minutes=minutes,
         arch="sdxl" if kind == "sdxl" else "sd15", base=key, trigger=trigger, images=len(samples))


if __name__ == "__main__":
    run_main(main)
