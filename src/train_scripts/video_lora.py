"""AI 協作：訓練影片模型的 LoRA（Wan2.1 T2V 1.3B）。
資料：一個資料夾，放影片（mp4、mov、webm、gif）或圖片（png、jpg、webp），每個檔案旁邊放同名的 .txt 寫這段內容的描述。
做法：先把影片與描述編碼成 latent 與文字向量並存起來（之後就不需要 VAE 與文字編碼器），
再只把主模型放進顯示卡訓練 LoRA（flow matching：預測「雜訊 − 原始 latent」）。
用法：python video_lora.py --config config.json [--smoke]"""
import glob
import math
import os
import random
import time

# @@COMMON@@

VIDEO_EXT = (".mp4", ".mov", ".webm", ".mkv", ".avi", ".gif")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp")


def dkw(fn, dtype):
    import inspect
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        params = {}
    return {"dtype": dtype} if "dtype" in params and "torch_dtype" not in params else {"torch_dtype": dtype}


def tf_dtype(dtype):
    """transformers 4.56 起改用 dtype=，舊版是 torch_dtype=。"""
    import transformers
    major, minor = (int(x) for x in transformers.__version__.split(".")[:2])
    return {"dtype": dtype} if (major, minor) >= (4, 56) else {"torch_dtype": dtype}


def list_samples(folder, trigger=""):
    items = []
    for path in sorted(glob.glob(os.path.join(folder, "*"))):
        ext = os.path.splitext(path)[1].lower()
        if ext not in VIDEO_EXT + IMAGE_EXT:
            continue
        cap_path = os.path.splitext(path)[0] + ".txt"
        caption = open(cap_path, "r", encoding="utf-8").read().strip() if os.path.isfile(cap_path) else ""
        if not caption:
            log(f"{os.path.basename(path)} 沒有同名的 .txt 描述，略過")
            continue
        items.append((path, (trigger + " " + caption).strip() if trigger else caption))
    if not items:
        raise ValueError("資料夾裡沒有可以用的影片或圖片（每個檔案旁邊要有同名的 .txt 描述）")
    return items


def read_frames(path, width, height, num_frames):
    """讀成 (3, F, H, W)、數值 -1～1；圖片當成 1 格。影片從頭均勻取 num_frames 格（不夠就取全部，再補到 4k+1）。"""
    import numpy as np
    import torch
    import imageio.v3 as iio
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE_EXT:
        frames = [iio.imread(path)]
    else:
        frames = list(iio.imiter(path))
        if len(frames) > num_frames:
            idx = np.linspace(0, len(frames) - 1, num_frames).round().astype(int)
            frames = [frames[i] for i in idx]
        keep = (len(frames) - 1) // 4 * 4 + 1          # 影片要 4k+1 格
        frames = frames[:keep]
    out = []
    for f in frames:
        f = np.asarray(f)
        if f.ndim == 2:
            f = np.stack([f] * 3, -1)
        f = f[..., :3]
        t = torch.from_numpy(f.copy()).permute(2, 0, 1).float() / 127.5 - 1.0
        h, w = t.shape[1:]
        scale = max(width / w, height / h)              # 等比放大到蓋滿，再從中間裁切
        t = torch.nn.functional.interpolate(t[None], size=(max(height, round(h * scale)), max(width, round(w * scale))),
                                            mode="bilinear", align_corners=False)[0]
        top, left = (t.shape[1] - height) // 2, (t.shape[2] - width) // 2
        out.append(t[:, top:top + height, left:left + width])
    return torch.stack(out, 1)


def tiny_parts():
    import torch
    from diffusers import AutoencoderKLWan, WanTransformer3DModel
    from transformers import AutoTokenizer, T5EncoderModel
    torch.manual_seed(0)
    vae = AutoencoderKLWan(base_dim=3, z_dim=16, dim_mult=[1, 1, 1, 1], num_res_blocks=1, temperal_downsample=[False, True, True])
    tr = WanTransformer3DModel(patch_size=(1, 2, 2), num_attention_heads=2, attention_head_dim=12, in_channels=16,
                               out_channels=16, text_dim=32, freq_dim=256, ffn_dim=32, num_layers=2, cross_attn_norm=True,
                               qk_norm="rms_norm_across_heads", rope_max_seq_len=32)
    return vae, T5EncoderModel.from_pretrained("hf-internal-testing/tiny-random-t5"), \
        AutoTokenizer.from_pretrained("hf-internal-testing/tiny-random-t5"), tr


def main():
    cfg = load_config()
    import torch
    from peft import LoraConfig
    from peft.utils import get_peft_model_state_dict
    smoke = cfg["smoke"]
    cuda = torch.cuda.is_available() and (not smoke or bool(cfg.get("smoke_gpu")))   # 本機檢測：快速測試也用顯示卡
    dev = torch.device("cuda" if cuda else "cpu")
    dtype = torch.bfloat16 if cuda else torch.float32
    repo = cfg.get("model_repo", "Wan-AI/Wan2.1-T2V-1.3B-Diffusers")
    out_dir = cfg["out_dir"]
    cache_dir = os.path.join(out_dir, "快取")
    os.makedirs(cache_dir, exist_ok=True)
    width, height = (32, 32) if smoke else (int(cfg.get("width", 416)), int(cfg.get("height", 240)))
    num_frames = 5 if smoke else int(cfg.get("num_frames", 17))
    max_seq = 16 if smoke else 512
    samples = list_samples(cfg["data_dir"], cfg.get("trigger", ""))
    log(f"資料 {len(samples)} 筆；解析度 {width}x{height}、最多 {num_frames} 格")

    # 1. 編碼並存起來
    emit("PROGRESS", stage="編碼資料", msg="把影片與描述轉成 latent 與文字向量（只做一次）")
    if smoke:
        vae, te, tok, transformer = tiny_parts()
    else:
        from diffusers import AutoencoderKLWan
        from transformers import AutoTokenizer, UMT5EncoderModel
        vae = AutoencoderKLWan.from_pretrained(repo, subfolder="vae", **dkw(AutoencoderKLWan.from_pretrained, torch.float32))
        te = UMT5EncoderModel.from_pretrained(repo, subfolder="text_encoder", low_cpu_mem_usage=True, **tf_dtype(dtype))
        tok = AutoTokenizer.from_pretrained(repo, subfolder="tokenizer")
        transformer = None
    vae.to(dev).eval()
    te.to(dev).eval()
    mean = torch.tensor(vae.config.latents_mean).view(1, -1, 1, 1, 1).to(dev)
    std = torch.tensor(vae.config.latents_std).view(1, -1, 1, 1, 1).to(dev)
    cached = []
    with torch.no_grad():
        for i, (path, caption) in enumerate(samples):
            px = read_frames(path, width, height, num_frames)[None].to(dev, torch.float32)
            lat = (vae.encode(px).latent_dist.sample() - mean) / std
            t = tok([caption], padding="max_length", max_length=max_seq, truncation=True, add_special_tokens=True,
                    return_attention_mask=True, return_tensors="pt")
            emb = te(t.input_ids.to(dev), t.attention_mask.to(dev)).last_hidden_state
            emb = emb * t.attention_mask.to(dev)[..., None]          # 跟 WanPipeline 一樣：描述以外的位置補 0
            f = os.path.join(cache_dir, f"{i:05d}.pt")
            torch.save({"latent": lat.cpu().to(torch.bfloat16 if cuda else torch.float32), "emb": emb.cpu().to(dtype)}, f)
            cached.append(f)
            emit("PROGRESS", stage="編碼資料", step=i + 1, total=len(samples))
    del vae, te
    if cuda:
        torch.cuda.empty_cache()

    # 2. 訓練 LoRA
    emit("PROGRESS", stage="載入主模型", msg=repo if not smoke else "極小的測試模型")
    if transformer is None:
        from diffusers import WanTransformer3DModel
        transformer = WanTransformer3DModel.from_pretrained(repo, subfolder="transformer",
                                                            **dkw(WanTransformer3DModel.from_pretrained, dtype))
    transformer.requires_grad_(False)
    transformer.to(dev)
    if cuda and cfg.get("gradient_checkpointing", True):
        transformer.enable_gradient_checkpointing()
    rank = int(cfg.get("lora_r", 32))
    transformer.add_adapter(LoraConfig(r=rank, lora_alpha=int(cfg.get("lora_alpha", rank)), init_lora_weights=True,
                                       target_modules=["to_q", "to_k", "to_v", "to_out.0"]))
    params = [p for p in transformer.parameters() if p.requires_grad]
    for p in params:
        p.data = p.data.float()                                   # LoRA 權重用 fp32 訓練比較穩
    log(f"可訓練參數 {sum(p.numel() for p in params) / 1e6:.2f} M")
    steps = int(cfg.get("smoke_steps", 3)) if smoke else int(cfg.get("steps", 1000))
    opt = torch.optim.AdamW(params, lr=float(cfg.get("lr", 1e-4)), weight_decay=1e-4)
    save_every = int(cfg.get("save_every", 250))
    transformer.train()
    started, losses = time.time(), []

    def save(tag):
        from diffusers import WanPipeline
        path = os.path.join(out_dir, tag)
        WanPipeline.save_lora_weights(path, transformer_lora_layers=get_peft_model_state_dict(transformer))
        return path
    for step in range(1, steps + 1):
        item = torch.load(random.choice(cached))
        x0 = item["latent"].to(dev, dtype)
        emb = item["emb"].to(dev, dtype)
        noise = torch.randn_like(x0)
        sigma = torch.sigmoid(torch.randn(1, device=dev))          # logit-normal：中間的雜訊程度多練一些
        noisy = (1 - sigma.view(1, 1, 1, 1, 1)) * x0 + sigma.view(1, 1, 1, 1, 1) * noise
        with torch.autocast("cuda", dtype=dtype, enabled=cuda):
            pred = transformer(hidden_states=noisy, timestep=(sigma * 1000).to(dtype), encoder_hidden_states=emb,
                               return_dict=False)[0]
        loss = torch.nn.functional.mse_loss(pred.float(), (noise - x0).float())
        loss.backward()
        torch.nn.utils.clip_grad_norm_(params, 1.0)
        opt.step()
        opt.zero_grad(set_to_none=True)
        losses.append(loss.item())
        if step % 5 == 0 or step == steps or smoke:
            spent = time.time() - started
            emit("PROGRESS", stage="訓練", step=step, total=steps, loss=round(sum(losses[-20:]) / len(losses[-20:]), 4),
                 eta_min=round(spent / step * (steps - step) / 60, 1), vram=vram_text())
        if save_every and step % save_every == 0 and step < steps:
            log(f"中途存檔：{save(f'第{step}步')}")
    final = save("lora")
    emit("RESULT", lora=final, steps=steps, loss=round(sum(losses[-20:]) / len(losses[-20:]), 4),
         minutes=round((time.time() - started) / 60, 1), width=width, height=height, num_frames=num_frames)


if __name__ == "__main__":
    run_main(main)
