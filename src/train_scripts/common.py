# ── 訓練腳本共用（由 AI 協作產生；每個腳本開頭都會帶一份，所以可以單獨在雲端執行）──
import json as _json
import os as _os
import sys as _sys
import time as _time
import traceback as _traceback
import warnings as _warnings

# 新版 diffusers 會對 torch_dtype 印「之後改名」的提醒（不影響結果），在紀錄裡看起來像錯誤 → 不顯示
_warnings.filterwarnings("ignore", message=r"(?s).*torch_dtype.*")


def emit(kind, **data):
    """回報給 AI 協作：@@PROGRESS／@@RESULT／@@ERROR 開頭的一行 JSON。"""
    print("@@" + kind + " " + _json.dumps(data, ensure_ascii=False, default=str), flush=True)


def log(msg):
    emit("LOG", msg=str(msg))


def load_config():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--smoke", action="store_true", help="用極小的模型在 CPU 上快速跑完整個流程（檢查環境用）")
    args = ap.parse_args()
    with open(args.config, "r", encoding="utf-8") as f:
        cfg = _json.load(f)
    cfg["smoke"] = bool(args.smoke or cfg.get("smoke"))
    base = _os.path.dirname(_os.path.abspath(args.config))
    for k, v in list(cfg.items()):            # 相對路徑一律以 config.json 所在的資料夾為準（雲端解壓後也能用）
        if k.endswith(("_dir", "_path", "_file")) and isinstance(v, str) and v and not _os.path.isabs(v):
            cfg[k] = _os.path.join(base, v)
    return cfg


def vram_text():
    try:
        import torch
        if torch.cuda.is_available():
            used = torch.cuda.max_memory_allocated() / 2 ** 30
            total = torch.cuda.get_device_properties(0).total_memory / 2 ** 30
            return f"{used:.1f}/{total:.1f} GB"
    except Exception:
        pass
    return ""


def friendly_error(exc):
    text = f"{type(exc).__name__}: {exc}"
    low = text.lower()
    if "out of memory" in low or "outofmemory" in low:
        return text, ("顯示卡記憶體不夠：調小「最長長度」「批次大小」或解析度，或改用較小的模型、改用雲端 GPU。"
                      "圖片生成可以把寬高調成 768×768 或 512×512，或把記憶體模式改成「極省」。")
    if "bitsandbytes" in low:
        return text, "4-bit 量化需要 bitsandbytes（Windows 請用 0.43 以上版本）：在訓練工作室按「安裝缺少的套件」。"
    if "401" in low or "gated" in low or "access to model" in low:
        return text, "這個模型需要在 Hugging Face 網站同意授權並設定權杖（HF_TOKEN），或改選不需要授權的模型。"
    if "no module named" in low:
        return text, "缺少套件：在訓練工作室按「檢查環境」，再按「安裝缺少的套件」。"
    if "connection" in low or "resolve" in low or "timed out" in low:
        return text, "下載模型時網路連線失敗：確認能連到 huggingface.co，或先把模型下載到本機再填資料夾路徑。"
    return text, ""


def run_main(main):
    started = _time.time()
    try:
        main()
    except KeyboardInterrupt:
        emit("ERROR", error="已停止", hint="")
        _sys.exit(130)
    except Exception as exc:
        text, hint = friendly_error(exc)
        emit("ERROR", error=text, hint=hint, trace=_traceback.format_exc()[-4000:])
        _sys.exit(1)
    finally:
        emit("LOG", msg=f"總共 {(_time.time() - started) / 60:.1f} 分鐘")


def tiny_sd_pipeline():
    """--smoke：照 diffusers 自己的測試，用極小的隨機 Stable Diffusion 組出整條管線（只檢查流程，畫面是雜訊）。"""
    import torch
    from diffusers import AutoencoderKL, DDIMScheduler, StableDiffusionPipeline, UNet2DConditionModel
    from transformers import CLIPTextConfig, CLIPTextModel, CLIPTokenizer
    torch.manual_seed(0)
    unet = UNet2DConditionModel(block_out_channels=(32, 64), layers_per_block=2, sample_size=32, in_channels=4, out_channels=4,
                                down_block_types=("DownBlock2D", "CrossAttnDownBlock2D"),
                                up_block_types=("CrossAttnUpBlock2D", "UpBlock2D"), cross_attention_dim=32)
    vae = AutoencoderKL(block_out_channels=[32, 64], in_channels=3, out_channels=3,
                        down_block_types=["DownEncoderBlock2D", "DownEncoderBlock2D"],
                        up_block_types=["UpDecoderBlock2D", "UpDecoderBlock2D"], latent_channels=4)
    te = CLIPTextModel(CLIPTextConfig(bos_token_id=0, eos_token_id=2, hidden_size=32, intermediate_size=37, layer_norm_eps=1e-05,
                                      num_attention_heads=4, num_hidden_layers=5, pad_token_id=1, vocab_size=1000))
    tok = CLIPTokenizer.from_pretrained("hf-internal-testing/tiny-random-clip")
    sched = DDIMScheduler(beta_start=0.00085, beta_end=0.012, beta_schedule="scaled_linear", clip_sample=False,
                          set_alpha_to_one=False)
    return StableDiffusionPipeline(unet=unet, vae=vae, text_encoder=te, tokenizer=tok, scheduler=sched, safety_checker=None,
                                   feature_extractor=None, requires_safety_checker=False)
