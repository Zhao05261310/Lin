"""AI 協作：語音生成與聲音訓練（F5-TTS：中文、英文；可以用一段參考錄音模仿聲音，也可以用多段錄音微調）。
只能使用你本人或已經取得同意的聲音。
模式（config 的 mode）：
  generate：用參考錄音（ref_audio＋ref_text）把 gen_text 念出來 → wav
  finetune：用資料夾裡的錄音（wav／mp3／flac，旁邊放同名 .txt 逐字稿）微調模型 → model.safetensors
用法：python tts.py --config config.json [--smoke]"""
import glob
import os
import random
import time

# @@COMMON@@

AUDIO_EXT = (".wav", ".mp3", ".flac", ".ogg", ".m4a")
SMOKE_ARCH = dict(dim=64, depth=2, heads=2, ff_mult=2, text_dim=32, text_mask_padding=True, qk_norm=None, conv_layers=1,
                  pe_attn_head=None, attn_backend="torch", attn_mask_enabled=False, checkpoint_activations=False)


def model_arch(name, smoke, checkpoint_activations=False):
    from importlib.resources import files
    from omegaconf import OmegaConf
    if smoke:
        return dict(SMOKE_ARCH)
    cfg = OmegaConf.load(str(files("f5_tts").joinpath(f"configs/{name}.yaml")))
    arch = OmegaConf.to_container(cfg.model.arch, resolve=True)
    arch["checkpoint_activations"] = bool(checkpoint_activations)
    return arch


def pretrained_ckpt(name="F5TTS_v1_Base"):
    from cached_path import cached_path
    step = 1250000 if name == "F5TTS_v1_Base" else 1200000
    return str(cached_path(f"hf://SWivid/F5-TTS/{name}/model_{step}.safetensors"))


def build_model(arch, device, vocab_file=""):
    """跟 F5-TTS 推論時一樣組出 CFM 模型（還沒載權重）。"""
    from importlib.resources import files
    from f5_tts.model import CFM, DiT
    from f5_tts.model.utils import get_tokenizer
    vocab_file = vocab_file or str(files("f5_tts").joinpath("infer/examples/vocab.txt"))
    vocab_map, vocab_size = get_tokenizer(vocab_file, "custom")
    return CFM(transformer=DiT(**arch, text_num_embeds=vocab_size, mel_dim=100),
               mel_spec_kwargs=dict(n_fft=1024, hop_length=256, win_length=1024, n_mel_channels=100,
                                    target_sample_rate=24000, mel_spec_type="vocos"),
               odeint_kwargs=dict(method="euler"), vocab_char_map=vocab_map).to(device), vocab_file


def sf_load(path, *_a, **_k):
    """用 soundfile 讀音檔，回傳 (聲道, 取樣) 的 tensor 與取樣率。
    新版 torchaudio.load 改交給 torchcodec，需要另外裝 FFmpeg 函式庫，在 Windows 常常載入失敗。"""
    import soundfile as sf
    import torch
    data, rate = sf.read(path, dtype="float32", always_2d=True)
    return torch.from_numpy(data.T.copy()), rate


def patch_torchaudio():
    import torchaudio
    torchaudio.load = sf_load                  # F5-TTS 讀參考錄音也用這個


def load_audio(path, sr=24000):
    import torch
    import torchaudio
    wav, rate = sf_load(path)
    wav = wav.mean(0, keepdim=True)
    if rate != sr:
        wav = torchaudio.functional.resample(wav, rate, sr)
    return wav.clamp(-1, 1).to(torch.float32)


def list_clips(folder):
    clips = []
    for path in sorted(glob.glob(os.path.join(folder, "*"))):
        if os.path.splitext(path)[1].lower() not in AUDIO_EXT:
            continue
        txt = os.path.splitext(path)[0] + ".txt"
        text = open(txt, "r", encoding="utf-8").read().strip() if os.path.isfile(txt) else ""
        if not text:
            log(f"{os.path.basename(path)} 沒有同名的 .txt 逐字稿，略過")
            continue
        clips.append((path, text))
    if not clips:
        raise ValueError("資料夾裡沒有可以用的錄音（每段錄音旁邊要有同名的 .txt 逐字稿）")
    return clips


def finetune(cfg):
    import torch
    from f5_tts.model.utils import convert_char_to_pinyin
    smoke = cfg["smoke"]
    cuda = torch.cuda.is_available() and (not smoke or bool(cfg.get("smoke_gpu")))   # 本機檢測：快速測試也用顯示卡
    device = "cuda" if cuda else "cpu"
    name = cfg.get("base", "F5TTS_v1_Base")
    arch = model_arch(name, smoke, checkpoint_activations=cuda)
    model, vocab = build_model(arch, device, cfg.get("vocab_file", ""))
    if not smoke:
        from f5_tts.infer.utils_infer import load_checkpoint
        emit("PROGRESS", stage="載入預訓練模型", msg="第一次會下載約 1.3 GB")
        model = load_checkpoint(model, cfg.get("init_ckpt") or pretrained_ckpt(name), device, dtype=torch.float32)
    model.float().train()
    clips = list_clips(cfg["data_dir"])
    max_sec = float(cfg.get("max_seconds", 20))
    data = []
    for path, text in clips:
        wav = load_audio(path)
        sec = wav.shape[-1] / 24000
        if sec < 1 or sec > max_sec:
            log(f"{os.path.basename(path)} 長度 {sec:.1f} 秒，不在 1～{max_sec:.0f} 秒之間，略過")
            continue
        data.append((wav, convert_char_to_pinyin([text])[0]))
    if not data:
        raise ValueError("沒有長度合適的錄音（每段 1～20 秒最好）")
    total_sec = sum(w.shape[-1] for w, _ in data) / 24000
    log(f"可用錄音 {len(data)} 段，共 {total_sec / 60:.1f} 分鐘")
    steps = int(cfg.get("smoke_steps", 3)) if smoke else int(cfg.get("steps", 2000))
    accum = 1 if smoke else int(cfg.get("grad_accum", 4))
    params = [p for p in model.parameters() if p.requires_grad]
    opt = None
    if cuda and cfg.get("adam8bit", True):
        try:
            import bitsandbytes as bnb
            opt = bnb.optim.AdamW8bit(params, lr=float(cfg.get("lr", 1e-5)))      # 8 GB 顯示卡：省下約一半的優化器記憶體
        except Exception:
            log("沒有 bitsandbytes，改用一般的 AdamW（比較吃記憶體）")
    opt = opt or torch.optim.AdamW(params, lr=float(cfg.get("lr", 1e-5)))
    dtype = torch.bfloat16 if cuda and torch.cuda.is_bf16_supported() else torch.float16
    started, losses = time.time(), []
    for step in range(1, steps + 1):
        for _ in range(accum):
            wav, text = random.choice(data)
            with torch.autocast("cuda", dtype=dtype, enabled=cuda):
                loss, _cond, _pred = model(wav.to(device), text=[text])
            (loss / accum).backward()
            losses.append(loss.item())
        torch.nn.utils.clip_grad_norm_(params, 1.0)
        opt.step()
        opt.zero_grad(set_to_none=True)
        if step % 10 == 0 or step == steps or smoke:
            spent = time.time() - started
            emit("PROGRESS", stage="訓練", step=step, total=steps, loss=round(sum(losses[-40:]) / len(losses[-40:]), 4),
                 eta_min=round(spent / step * (steps - step) / 60, 1), vram=vram_text())
    from safetensors.torch import save_file
    out_dir = cfg["out_dir"]
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "model.safetensors")
    save_file({k: v.detach().to(torch.float32 if smoke else torch.float16).contiguous().cpu()
               for k, v in model.state_dict().items()}, path)
    with open(os.path.join(out_dir, "模型資訊.json"), "w", encoding="utf-8") as f:
        _json.dump({"base": name, "arch": arch, "vocab_file": vocab, "smoke": smoke}, f, ensure_ascii=False, indent=2)
    emit("RESULT", model=path, steps=steps, loss=round(sum(losses[-40:]) / len(losses[-40:]), 4),
         minutes=round((time.time() - started) / 60, 1), clips=len(data))


def generate(cfg):
    import torch
    from f5_tts.infer.utils_infer import infer_process, load_checkpoint, load_vocoder, preprocess_ref_audio_text
    import soundfile as sf
    smoke = cfg["smoke"]
    device = "cuda" if torch.cuda.is_available() and (not smoke or cfg.get("smoke_gpu")) else "cpu"
    ckpt = cfg.get("model_path") or ""
    info = {}
    if ckpt and os.path.isfile(os.path.join(os.path.dirname(ckpt), "模型資訊.json")):
        info = _json.load(open(os.path.join(os.path.dirname(ckpt), "模型資訊.json"), encoding="utf-8"))
    name = info.get("base", cfg.get("base", "F5TTS_v1_Base"))
    arch = info.get("arch") or model_arch(name, smoke)
    model, _vocab = build_model(arch, device, info.get("vocab_file", ""))
    emit("PROGRESS", stage="載入模型", msg=ckpt or "F5-TTS 預訓練模型（第一次會下載約 1.3 GB）")
    if ckpt or not smoke:
        model = load_checkpoint(model, ckpt or pretrained_ckpt(name), device)
    model.eval()
    vocoder = load_vocoder("vocos", device=device)
    ref_audio, ref_text = preprocess_ref_audio_text(cfg["ref_audio"], cfg.get("ref_text", ""), show_info=log)
    emit("PROGRESS", stage="生成", msg=cfg["gen_text"][:40])
    wav, sr, _spec = infer_process(ref_audio, ref_text, cfg["gen_text"], model, vocoder, show_info=log, progress=None,
                                   nfe_step=4 if smoke else int(cfg.get("nfe_step", 32)), speed=float(cfg.get("speed", 1.0)),
                                   device=device)
    out = cfg.get("out_path") or os.path.join(cfg.get("out_dir", "."), f"語音_{time.strftime('%Y%m%d_%H%M%S')}.wav")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    sf.write(out, wav, sr)
    emit("RESULT", audio=out, seconds=round(len(wav) / sr, 1), model=ckpt or name)


def main():
    cfg = load_config()
    if not cfg.get("consent"):
        raise ValueError("請先確認：參考錄音或訓練用的聲音是你本人，或已經取得聲音主人的同意")
    patch_torchaudio()
    (finetune if cfg.get("mode") == "finetune" else generate)(cfg)


if __name__ == "__main__":
    run_main(main)
