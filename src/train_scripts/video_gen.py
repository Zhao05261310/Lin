"""AI 協作：文字轉影片（本機開源模型：Wan2.1 1.3B、LTX-Video、CogVideoX-2B；可以套用自己訓練的 LoRA）。
用法：python video_gen.py --config config.json [--smoke]
8 GB 顯示卡：一律開 CPU 卸載與 VAE 分塊；解析度與格數越大越慢、越吃記憶體。"""
import os
import time

# @@COMMON@@

MODELS = {
    "wan-1.3b": ("Wan-AI/Wan2.1-T2V-1.3B-Diffusers", "wan"),
    "ltx": ("Lightricks/LTX-Video", "ltx"),
    "cogvideox-2b": ("THUDM/CogVideoX-2b", "cog"),
}


def dkw(fn, dtype):
    """diffusers 新舊版的 dtype 參數名稱不同。"""
    import inspect
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        params = {}
    return {"dtype": dtype} if "dtype" in params and "torch_dtype" not in params else {"torch_dtype": dtype}


def tiny_wan_pipeline():
    """--smoke：照 diffusers 自己的測試，用極小的隨機 Wan 模型組出整條管線（只檢查流程，畫面是雜訊）。"""
    import torch
    from diffusers import AutoencoderKLWan, FlowMatchEulerDiscreteScheduler, WanPipeline, WanTransformer3DModel
    from transformers import AutoTokenizer, T5EncoderModel
    torch.manual_seed(0)
    vae = AutoencoderKLWan(base_dim=3, z_dim=16, dim_mult=[1, 1, 1, 1], num_res_blocks=1,
                           temperal_downsample=[False, True, True])
    transformer = WanTransformer3DModel(patch_size=(1, 2, 2), num_attention_heads=2, attention_head_dim=12, in_channels=16,
                                        out_channels=16, text_dim=32, freq_dim=256, ffn_dim=32, num_layers=2,
                                        cross_attn_norm=True, qk_norm="rms_norm_across_heads", rope_max_seq_len=32)
    te = T5EncoderModel.from_pretrained("hf-internal-testing/tiny-random-t5")
    tok = AutoTokenizer.from_pretrained("hf-internal-testing/tiny-random-t5")
    return WanPipeline(transformer=transformer, vae=vae, text_encoder=te, tokenizer=tok,
                       scheduler=FlowMatchEulerDiscreteScheduler(shift=7.0))


def load_pipeline(key, cuda):
    import torch
    repo, kind = MODELS[key]
    dtype = torch.bfloat16 if cuda else torch.float32
    if kind == "wan":
        from diffusers import AutoencoderKLWan, WanPipeline
        vae = AutoencoderKLWan.from_pretrained(repo, subfolder="vae", **dkw(AutoencoderKLWan.from_pretrained, torch.float32))
        pipe = WanPipeline.from_pretrained(repo, vae=vae, **dkw(WanPipeline.from_pretrained, dtype))
    elif kind == "ltx":
        from diffusers import LTXPipeline
        pipe = LTXPipeline.from_pretrained(repo, **dkw(LTXPipeline.from_pretrained, dtype))
    else:
        from diffusers import CogVideoXPipeline
        pipe = CogVideoXPipeline.from_pretrained(repo, **dkw(CogVideoXPipeline.from_pretrained,
                                                             torch.float16 if cuda else torch.float32))
    return pipe


def main():
    cfg = load_config()
    import torch
    from diffusers.utils import export_to_video
    smoke = cfg["smoke"]
    cuda = torch.cuda.is_available() and (not smoke or bool(cfg.get("smoke_gpu")))   # 本機檢測：快速測試也用顯示卡
    key = cfg.get("model", "wan-1.3b")
    if key not in MODELS:
        raise ValueError(f"不認得的影片模型：{key}（可用：{', '.join(MODELS)}）")
    emit("PROGRESS", stage="載入模型", msg=f"{MODELS[key][0]}（第一次會下載好幾 GB）" if not smoke else "極小的測試模型")
    pipe = tiny_wan_pipeline() if smoke else load_pipeline(key, cuda)
    if cuda:
        pipe.enable_model_cpu_offload()            # 8 GB 顯示卡：只把正在用的部分放進顯示卡
        for fn in ("enable_tiling", "enable_slicing"):
            if hasattr(pipe.vae, fn):
                getattr(pipe.vae, fn)()
    lora = cfg.get("lora_path") or ""
    if lora:
        emit("PROGRESS", stage="載入 LoRA", msg=lora)
        pipe.load_lora_weights(lora, adapter_name="custom")
        try:
            loaded = {a for names in (pipe.get_list_adapters() or {}).values() for a in names}
        except Exception:
            loaded = {"custom"}
        if "custom" not in loaded:
            raise RuntimeError("LoRA 跟這個影片模型不相容：檔案裡沒有它用得上的權重（例如選到圖片模型的 LoRA，"
                               "或 LoRA 是用別的影片模型訓練的）。")
        pipe.set_adapters(["custom"], adapter_weights=[float(cfg.get("lora_scale", 1.0))])
    width, height = (32, 32) if smoke else (int(cfg.get("width", 480)), int(cfg.get("height", 272)))
    frames = 5 if smoke else int(cfg.get("num_frames", 33))
    frames = (frames - 1) // 4 * 4 + 1                 # Wan／LTX 需要 4k+1 格
    steps = 2 if smoke else int(cfg.get("steps", 30))
    gen = torch.Generator(device="cpu").manual_seed(int(cfg.get("seed", 42)))
    started = time.time()

    def on_step(_pipe, i, _t, kwargs):
        spent = time.time() - started
        emit("PROGRESS", stage="生成", step=i + 1, total=steps, eta_min=round(spent / (i + 1) * (steps - i - 1) / 60, 1),
             vram=vram_text())
        return kwargs
    kw = dict(prompt=cfg["prompt"], negative_prompt=cfg.get("negative_prompt") or None, width=width, height=height,
              num_frames=frames, num_inference_steps=steps, guidance_scale=float(cfg.get("guidance", 5.0)), generator=gen,
              callback_on_step_end=on_step)
    if smoke:
        kw["max_sequence_length"] = 16
    out = pipe(**kw).frames[0]
    path = cfg.get("out_path") or os.path.join(cfg.get("out_dir", "."), f"影片_{time.strftime('%Y%m%d_%H%M%S')}.mp4")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    export_to_video(out, path, fps=int(cfg.get("fps", 16)))
    emit("RESULT", video=path, frames=len(out), seconds=round(time.time() - started, 1), model=key, lora=lora)


if __name__ == "__main__":
    run_main(main)
