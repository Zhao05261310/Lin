

# ═════════════════════════ 3f. v6.14：訓練工作室（語言模型蒸餾、語音、影片）── 程式內只用標準函式庫 ═════════════════════════
# 重的工作（PyTorch 訓練、生成）交給「訓練腳本」：TRAIN_SCRIPTS（build.py 從 src/train_scripts/ 嵌進來），
# 執行時寫到 訓練/工作名稱/ 再用使用者的 Python（例如 conda 環境）執行，腳本用 @@PROGRESS 等 JSON 行回報。
# 同一份腳本也打包給雲端 GPU（Colab、RunPod）使用，訓練完把結果 zip 匯入回來。

TRAIN_DIR = os.path.join(APP_DIR, "訓練")
TRAIN_REGISTRY = os.path.join(TRAIN_DIR, "模型清單.json")

TRAIN_TASKS = {
    "llm": {"label": "語言模型蒸餾／微調", "script": "train_llm",
            "modules": ["torch", "transformers", "peft", "accelerate", "safetensors", "sentencepiece"], "cuda_modules": ["bitsandbytes"]},
    "tts": {"label": "語音生成與聲音訓練", "script": "tts",
            "modules": ["torch", "torchaudio", "f5_tts", "soundfile"], "cuda_modules": ["bitsandbytes"]},
    "video": {"label": "影片生成", "script": "video_gen",
              "modules": ["torch", "diffusers", "transformers", "accelerate", "safetensors", "sentencepiece", "ftfy", "imageio",
                          "imageio_ffmpeg", "peft"], "cuda_modules": []},
    "image": {"label": "圖片生成", "script": "image_gen",
              "modules": ["torch", "diffusers", "transformers", "accelerate", "safetensors", "sentencepiece", "peft"],
              "cuda_modules": ["bitsandbytes"]},
    "image_lora": {"label": "圖片 LoRA 訓練", "script": "image_lora",
                   "modules": ["torch", "diffusers", "transformers", "accelerate", "safetensors", "peft"],
                   "cuda_modules": ["bitsandbytes"]},
    "video_lora": {"label": "影片模型 LoRA 訓練", "script": "video_lora",
                   "modules": ["torch", "diffusers", "transformers", "accelerate", "safetensors", "sentencepiece", "ftfy",
                               "imageio", "imageio_ffmpeg", "peft"], "cuda_modules": []},
}
PIP_NAMES = {"imageio_ffmpeg": "imageio-ffmpeg", "f5_tts": "f5-tts", "bitsandbytes": "bitsandbytes>=0.43"}
# 太舊不能用的版本（v6.16.1：使用者的 diffusers 太舊，沒有 Wan 的 AutoencoderKLWan，影片 LoRA 在本機檢測失敗）
MIN_VERSIONS = {"diffusers": (0, 33), "peft": (0, 13), "transformers": (4, 46)}


def _ver_tuple(v):
    nums = re.findall(r"\d+", str(v or ""))
    return tuple(int(x) for x in nums[:3]) if nums else ()


def outdated_modules(probe):
    """已經裝了但版本太舊的套件：{模組: (目前版本, 最低版本字串)}。"""
    pk = (probe or {}).get("packages") or {}
    out = {}
    for mod, need in MIN_VERSIONS.items():
        have = pk.get(mod)
        if have and _ver_tuple(have) and _ver_tuple(have) < need:
            out[mod] = (have, ".".join(map(str, need)))
    return out

LLM_BASE_MODELS = [
    ("Qwen/Qwen2.5-1.5B-Instruct", "1.5B：8 GB 顯示卡最穩，約 30 分鐘～數小時"),
    ("Qwen/Qwen2.5-3B-Instruct", "3B：8 GB 可以（4-bit），品質較好"),
    ("Qwen/Qwen2.5-7B-Instruct", "7B：8 GB 勉強（最長長度要調小），建議用雲端 GPU"),
    ("Qwen/Qwen2.5-0.5B-Instruct", "0.5B：最快，適合先試流程"),
]
# 圖片模型：(鍵, 說明, 授權提醒)。8 GB 顯示卡建議從 SDXL-Turbo 開始
IMAGE_MODELS = [("sdxl-turbo", "SDXL-Turbo：最快，4 步就出圖（512×512 約 2～5 秒），8 GB 很穩", "非商業授權"),
                ("sdxl", "SDXL 1.0：品質好、生態最完整（LoRA 很多），1024×1024 約 30～60 秒", "可商用（OpenRAIL++）"),
                ("sd15", "Stable Diffusion 1.5：最省記憶體，512×512，社群模型與 LoRA 最多", "可商用（OpenRAIL）"),
                ("sd35-medium", "SD 3.5 Medium：文字與構圖較好；8 GB 會自動不載入 T5", "需在 Hugging Face 同意授權"),
                ("flux-schnell", "FLUX.1 schnell：品質很好、4 步；8 GB 自動用 4-bit 量化，在邊緣（建議 768×768）",
                 "可商用（Apache 2.0）；第一次下載約 30 GB"),
                ("flux-dev", "FLUX.1 dev：目前開源最好的品質之一，28 步；8 GB 在邊緣，很慢",
                 "非商業授權、需在 Hugging Face 同意授權")]
# 圖片 LoRA 訓練的底模：(鍵, 說明, 預設解析度, 預設步數)
IMAGE_LORA_BASES = [("sdxl", "SDXL 1.0：品質好；8 GB 在邊緣，建議 768×768，約 1～3 小時（1500 步）", 768, 1500),
                    ("sd15", "Stable Diffusion 1.5：8 GB 很穩、最快，512×512，約 20～40 分鐘（1000 步）", 512, 1000)]
IMAGE_DEFAULTS = {"sdxl-turbo": (512, 512, 4, 0.0), "sdxl": (1024, 1024, 30, 6.0), "sd15": (512, 512, 30, 7.0),
                  "sd35-medium": (1024, 1024, 28, 4.5), "flux-schnell": (768, 768, 4, 0.0), "flux-dev": (768, 768, 28, 3.5)}
VIDEO_MODELS = [("wan-1.3b", "Wan2.1 1.3B：品質好，8 GB 可跑（480×272、33 格約 5～15 分鐘）"),
                ("ltx", "LTX-Video 2B：速度快"), ("cogvideox-2b", "CogVideoX 2B：較舊，8 GB 可跑")]


def train_script_text(name):
    """組出可以單獨執行的訓練腳本（把共用的程式碼放進去）。"""
    body = TRAIN_SCRIPTS[name]
    if "# @@COMMON@@" in body:
        body = body.replace("# @@COMMON@@", TRAIN_SCRIPTS["common"], 1)
    return body


def write_train_script(name, folder):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{name}.py")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(train_script_text(name))
    return path


def find_train_python(prefs=None):
    """訓練用的 Python：使用者指定的 → 目前執行本程式的 Python（例如 conda 環境）→ PATH 上的 python。"""
    p = (prefs or {}).get("train_python") or ""
    if p and os.path.isfile(p):
        return p
    exe = sys.executable or ""
    if FROZEN:
        exe = ""
    if exe and os.path.basename(exe).lower().startswith("pythonw"):
        alt = os.path.join(os.path.dirname(exe), "python.exe")
        exe = alt if os.path.isfile(alt) else exe
    if exe:
        return exe
    return shutil.which("python") or shutil.which("python3") or ""


def nvidia_driver_cuda():
    """顯示卡驅動支援的最高 CUDA 版本（nvidia-smi 表頭的「CUDA Version」）；沒有 NVIDIA 顯示卡回傳 None。"""
    try:
        out = subprocess.run(["nvidia-smi"], capture_output=True, text=True, timeout=15,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"CUDA Version:\s*(\d+)\.(\d+)", out or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def torch_index_for(driver):
    """依驅動能支援的 CUDA 版本挑 PyTorch 的下載來源。"""
    if not driver:
        return "https://download.pytorch.org/whl/cpu"
    for need, tag in (((12, 8), "cu128"), ((12, 6), "cu126"), ((12, 4), "cu124"), ((12, 1), "cu121"), ((11, 8), "cu118")):
        if driver >= need:
            return f"https://download.pytorch.org/whl/{tag}"
    return "https://download.pytorch.org/whl/cpu"


def install_plan(probe, task, driver=None):
    """要讓這個工作能跑，還要裝哪些套件：回傳 [(說明, 指令參數清單)]（不含 python -m pip）。"""
    pk = (probe or {}).get("packages") or {}
    info = TRAIN_TASKS[task]
    plan = []
    want_cuda = bool(driver)
    torch_ok = bool(pk.get("torch")) and (probe.get("cuda") or not want_cuda)
    need_audio = "torchaudio" in info["modules"] and not pk.get("torchaudio")
    if torch_ok and need_audio:
        # PyTorch 已經可以用：只補 torchaudio，並把 torch 固定在現在的版本（不然 pip 可能順便換掉 PyTorch、重新下載好幾 GB）
        ver = str(pk.get("torch"))
        tag = ver.split("+", 1)[1] if "+" in ver else ""
        idx = f"https://download.pytorch.org/whl/{tag}" if re.fullmatch(r"cu\d+|cpu|rocm[\d.]+", tag) else torch_index_for(driver)
        plan.append((f"安裝跟 PyTorch {ver} 相符的 torchaudio（PyTorch 不變）", ["install", "torchaudio", f"torch=={ver}",
                                                                         "--index-url", idx]))
    elif not torch_ok or need_audio:
        idx = torch_index_for(driver)
        pkgs = ["torch", "torchaudio"] if (need_audio or "torchaudio" in info["modules"]) else ["torch"]
        extra = ["--upgrade", "--force-reinstall"] if pk.get("torch") and want_cuda and not probe.get("cuda") else []
        why = ("安裝 GPU 版 PyTorch（" + idx.rsplit("/", 1)[-1] + "）" if want_cuda else "安裝 PyTorch（沒有 NVIDIA 顯示卡，用 CPU 版）")
        if pk.get("torch") and want_cuda and not probe.get("cuda"):
            why = "目前的 PyTorch 是 CPU 版，換成 GPU 版（" + idx.rsplit("/", 1)[-1] + "）"
        plan.append((why, ["install", *extra, *pkgs, "--index-url", idx]))
    missing = [m for m in info["modules"] if m not in ("torch", "torchaudio") and not pk.get(m)]
    if want_cuda:
        missing += [m for m in info["cuda_modules"] if not pk.get(m)]
    if missing:
        plan.append(("安裝 " + "、".join(PIP_NAMES.get(m, m) for m in missing), ["install", *(PIP_NAMES.get(m, m) for m in missing)]))
    old = {m: v for m, v in outdated_modules(probe).items() if m in info["modules"]}
    if old:
        plan.append(("更新 " + "、".join(f"{m}（目前 {have}，需要 {need} 以上）" for m, (have, need) in old.items()),
                     ["install", "--upgrade", *(f"{m}>={need}" for m, (_h, need) in old.items())]))
    return plan


def full_install_plan(probe, driver=None, tasks=None):
    """所有（或指定）功能需要的安裝步驟，去掉重複。"""
    plan, seen = [], set()
    for task in tasks or TRAIN_TASKS:
        for why, args in install_plan(probe, task, driver):
            if tuple(args) not in seen:
                seen.add(tuple(args))
                plan.append((why, args))
    return plan


def execute_install_plan(python, plan, on_line=None, cwd=None):
    """依序執行 pip 安裝（介面的「安裝缺少的套件」與 --train-setup 共用）。回傳 (成功, 失敗的說明)。"""
    on_line = on_line or (lambda *_a: None)
    for i, (why, args) in enumerate(plan, 1):
        on_line("step", f"[{i}/{len(plan)}] {why}", (i - 1) / max(len(plan), 1) * 100)
        output, status, code, sec, _n = run_process_tree([python, "-m", "pip", *args, "--disable-pip-version-check"],
                                                         cwd or (TRAIN_DIR if os.path.isdir(TRAIN_DIR) else APP_DIR),
                                                         dict(scrubbed_env(), PYTHONIOENCODING="utf-8"), timeout=7200, shell=False)
        tail = "\n".join(output.strip().splitlines()[-6:])
        if status is not None or code != 0:
            on_line("fail", f"✘ 失敗（{status or f'結束代碼 {code}'}）：\n{tail}", None)
            return False, f"{why}：{status or f'結束代碼 {code}'}"
        on_line("ok", f"✔ {why}（{sec:.0f} 秒）", None)
    return True, ""


def missing_after_probe(probe, driver=None):
    """各功能還缺哪些套件：{功能: [缺的]}；空字典代表都好了。"""
    pk = (probe or {}).get("packages") or {}
    out = {}
    old = outdated_modules(probe)
    for task, info in TRAIN_TASKS.items():
        miss = [m for m in info["modules"] + (info["cuda_modules"] if driver else []) if not pk.get(m)]
        miss += [f"{m}（太舊）" for m in info["modules"] if m in old]
        if miss:
            out[task] = miss
    return out


def run_train_setup(python=None):
    """--train-setup：檢查環境 → 算出安裝步驟 → 實際安裝 → 再檢查一次（GitHub 自動測試用來模擬使用者按「安裝缺少的套件」）。"""
    python = python or sys.executable
    driver = nvidia_driver_cuda()
    probe = probe_train_env(python)
    print(describe_env(probe, driver), flush=True)
    if probe.get("error"):
        return False
    plan = full_install_plan(probe, driver)
    print("安裝步驟：" + ("（不需要）" if not plan else ""), flush=True)
    for why, args in plan:
        print(f"  • {why}\n    python -m pip {' '.join(args)}", flush=True)
    ok, why = execute_install_plan(python, plan, on_line=lambda kind, text, _p: print(text, flush=True))
    probe = probe_train_env(python)
    print(describe_env(probe, driver), flush=True)
    missing = missing_after_probe(probe, driver)
    if missing:
        print("仍然缺少：" + json.dumps(missing, ensure_ascii=False), flush=True)
    return ok and not missing


def requirements_text(task, cuda=True):
    info = TRAIN_TASKS[task]
    mods = [m for m in info["modules"] if m not in ("torch", "torchaudio")] + (info["cuda_modules"] if cuda else [])
    return "\n".join(PIP_NAMES.get(m, m) for m in dict.fromkeys(mods)) + "\n"


TRAIN_LOG_LIMIT = 20_000_000


class TrainJob:
    """執行一個訓練腳本：解析 @@PROGRESS／@@RESULT／@@ERROR／@@LOG，完整輸出寫進 訓練紀錄.txt。"""

    def __init__(self, python, script, config_path, smoke=False, on_event=None, extra_env=None):
        self.python, self.script, self.config_path, self.smoke = python, script, config_path, smoke
        self.on_event = on_event or (lambda *_a: None)
        self.extra_env = extra_env or {}
        self.tree = None
        self.result = None
        self.error = None
        self.cancelled = False
        self.log_path = os.path.join(os.path.dirname(config_path), "訓練紀錄.txt")

    def run(self):
        """在目前的執行緒跑完（請放在背景執行緒呼叫）。回傳 result dict 或 None。"""
        env = dict(scrubbed_env(keep=("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN")), PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1",
                   PYTHONUTF8="1", **self.extra_env)
        cmd = [self.python, "-u", self.script, "--config", self.config_path] + (["--smoke"] if self.smoke else [])
        self.tree = ProcessTree(cmd, os.path.dirname(self.config_path), env, shell=False)
        written = 0
        with open(self.log_path, "a", encoding="utf-8") as log_f:
            log_f.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} {' '.join(cmd)}\n")
            while True:
                # v6.14.2 紅隊：輸出 300 MB 不換行會整行讀進記憶體（多吃 1.1 GB）→ 每次最多讀 64 KB，太長的行只留前段
                raw = self.tree.proc.stdout.readline(65536)
                if not raw:
                    break
                if len(raw) >= 65536 and not raw.endswith(b"\n"):
                    while raw and not raw.endswith(b"\n"):
                        raw = self.tree.proc.stdout.readline(65536)
                    line = "（這一行超過 64 KB，已略過）"
                else:
                    line = raw.decode("utf-8", "replace").rstrip("\r\n")
                if written < TRAIN_LOG_LIMIT or line.startswith("@@"):
                    text = mask_secrets(line[:4000])[0] + "\n"
                    log_f.write(text)
                    log_f.flush()
                    written += len(text)
                    if written >= TRAIN_LOG_LIMIT:
                        log_f.write("…（紀錄超過 20 MB，之後只記進度與結果）\n")
                self._handle(line)
        code = self.tree.proc.wait()
        self.tree.close()
        if self.cancelled:
            self.error = self.error or {"error": "已停止", "hint": ""}
        elif code and not self.error and not self.result:
            self.error = {"error": f"訓練程式結束代碼 {code}", "hint": f"詳細內容在 {self.log_path}"}
        self.on_event("done", {"result": self.result, "error": self.error})
        return self.result

    def _handle(self, line):
        m = re.match(r"^@@(PROGRESS|RESULT|ERROR|LOG) (\{.*\})\s*$", line)
        if not m:
            text = re.sub(r"\x1b\[[0-9;]*m", "", line).strip()
            noise = re.search(r"warnings\.warn\(|Warning:|DeprecationWarning|FutureWarning|^\s*(warn|return )|it/s\]", text)
            if text and not noise and "%|" not in text and not text.startswith(("Loading", "Fetching", "Downloading")):
                self.on_event("raw", {"msg": mask_secrets(text)[0][:500]})
            return
        try:
            data = json.loads(m.group(2))
        except ValueError:
            return
        kind = m.group(1).lower()
        if kind == "progress":
            # v6.14.3 壓力測試：訓練程式狂印進度時，每一行都更新畫面會卡 → 每秒最多 10 次（最後一步一定送）
            now = time.monotonic()
            last_step = data.get("step") is not None and data.get("step") == data.get("total")
            if not last_step and not data.get("msg") and now - getattr(self, "_last_progress", 0) < 0.1:
                return
            self._last_progress = now
        if kind == "result":
            self.result = data
        elif kind == "error":
            self.error = data
        self.on_event(kind, data)

    def stop(self):
        self.cancelled = True
        if self.tree:
            self.tree.kill()


def probe_train_env(python, folder=None, timeout=180):
    """在訓練用的 Python 裡執行 env_probe，回傳 dict（失敗時有 error）。"""
    folder = folder or os.path.join(TRAIN_DIR, "_環境檢查")
    script = write_train_script("env_probe", folder)
    try:
        out = subprocess.run([python, script], capture_output=True, timeout=timeout, cwd=folder, env=scrubbed_env(),
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as exc:
        return {"error": f"沒辦法執行 {python}：{exc}"}
    text = out.stdout.decode("utf-8", "replace")
    m = re.search(r"^@@RESULT (\{.*\})\s*$", text, re.M)
    if not m:
        return {"error": (out.stderr.decode("utf-8", "replace") or text)[-800:] or "檢查程式沒有回報結果"}
    return json.loads(m.group(1))


def describe_env(probe, driver=None):
    """環境檢查結果的白話說明（多行）。"""
    if probe.get("error"):
        return "⚠ " + probe["error"]
    pk = probe.get("packages") or {}
    lines = [f"Python {probe.get('python')}（{probe.get('executable')}）"]
    if probe.get("cuda"):
        lines.append(f"✔ 顯示卡：{probe.get('gpu')}（{probe.get('vram_gb')} GB），PyTorch {pk.get('torch')}（CUDA {probe.get('torch_cuda')}）")
    elif driver:
        lines.append(f"⚠ 有 NVIDIA 顯示卡（驅動支援 CUDA {driver[0]}.{driver[1]}），但 PyTorch "
                     + (f"{pk.get('torch')} 是 CPU 版" if pk.get("torch") else "還沒安裝") + "：訓練會非常慢，請按「安裝缺少的套件」")
    else:
        lines.append("⚠ 沒有偵測到 NVIDIA 顯示卡：只能用 CPU（很慢），建議改用雲端 GPU")
    if probe.get("disk_free_gb") is not None:
        lines.append(f"硬碟剩下 {probe['disk_free_gb']} GB" + ("（模型很大，建議至少 30 GB）" if probe["disk_free_gb"] < 30 else ""))
    old = outdated_modules(probe)
    for task, info in TRAIN_TASKS.items():
        miss = [m for m in info["modules"] + (info["cuda_modules"] if driver else []) if not pk.get(m)]
        stale = [f"{m} {old[m][0]} 太舊（需要 {old[m][1]} 以上）" for m in info["modules"] if m in old]
        problems = (["缺 " + "、".join(PIP_NAMES.get(m, m) for m in miss)] if miss else []) + stale
        lines.append(("✔ " if not problems else "✘ ") + info["label"] + ("" if not problems else "：" + "；".join(problems)))
    return "\n".join(lines)


# ── 語言模型蒸餾：老師產生資料 ──
DISTILL_SYSTEM = "你是專業、精確的助理。一律用台灣繁體中文與台灣用語回答，不要用簡體字與大陸用語；回答要正確、完整、有條理。"


def _extract_json_array(text):
    m = re.search(r"\[.*\]", text or "", re.S)
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
    except ValueError:
        return []
    return [str(x).strip() for x in arr if isinstance(x, (str, int, float)) and str(x).strip()]


def _norm_q(q):
    return re.sub(r"[\s\W_]+", "", (q or "").lower())


def generate_questions(chat, topic, count, existing=(), batch=20, cancel=None, on_progress=None):
    """請老師針對主題出 count 個不重複的問題。chat(messages) → 文字。"""
    seen = {_norm_q(q) for q in existing}
    out, tries = [], 0
    while len(out) < count and tries < count // max(1, batch // 2) + 6:
        if cancel is not None and cancel.is_set():
            break
        tries += 1
        need = min(batch, count - len(out))
        sample = "\n".join(f"- {q}" for q in (list(existing) + out)[-15:])
        prompt = (f"請針對主題「{topic}」出 {need} 個彼此不同、具體、難度從基礎到進階都有的問題（真的會有人問的那種），"
                  "涵蓋不同面向；用台灣繁體中文。" + (f"\n不要跟這些重複：\n{sample}" if sample else "")
                  + "\n只輸出 JSON 字串陣列，例如 [\"問題一\", \"問題二\"]，不要其他文字。")
        for q in _extract_json_array(chat([{"role": "user", "content": prompt}])):
            k = _norm_q(q)
            if len(q) >= 4 and k and k not in seen:
                seen.add(k)
                out.append(q[:500])
        if on_progress:
            on_progress(len(out), count)
    return out[:count]


def check_distill_answer(answer):
    """老師的回答能不能拿來訓練：回傳空字串（可以）或原因。"""
    a = (answer or "").strip()
    if len(a) < 15:
        return "回答太短"
    n_simp, _ex, terms = language_drift(a)
    cjk = sum(1 for c in a if "一" <= c <= "鿿") or 1
    if n_simp >= 5 and n_simp / cjk >= 0.01:
        return f"有 {n_simp} 個簡體字"
    if len(terms) >= 2:
        return "大陸用語"
    if mask_secrets(a)[1]:
        return "含有像金鑰的字串"
    return ""


def build_distill_dataset(chat, questions, out_path, system=DISTILL_SYSTEM, eval_ratio=0.1, workers=3, cancel=None,
                          on_progress=None):
    """請老師回答每個問題，通過檢查的寫進 JSONL（訓練）與 評測.jsonl（保留不訓練，用來比較學生和老師）。
    回傳 {"train": n, "eval": n, "rejected": [(問題, 原因)]}。"""
    import concurrent.futures as cf
    results, rejected = {}, []
    done = [0]
    lock = threading.Lock()

    def work(i, q):
        if cancel is not None and cancel.is_set():
            return
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": q}]
        try:
            ans = chat(msgs)
        except Exception as exc:                    # 個別題目失敗不影響其他題
            ans, why = "", f"老師回答失敗：{exc}"
        else:
            why = check_distill_answer(ans)
        with lock:
            if why:
                rejected.append((q, why))
            else:
                results[i] = msgs + [{"role": "assistant", "content": ans.strip()}]
            done[0] += 1
            if on_progress:
                on_progress(done[0], len(questions))
    with cf.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        list(pool.map(lambda a: work(*a), enumerate(questions)))
    rows = [results[i] for i in sorted(results)]
    random.Random(42).shuffle(rows)
    n_eval = max(1, int(len(rows) * eval_ratio)) if len(rows) >= 10 else 0
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    eval_path = os.path.join(os.path.dirname(os.path.abspath(out_path)), "評測.jsonl")
    for path, part in ((eval_path, rows[:n_eval]), (out_path, rows[n_eval:])):
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            for r in part:
                f.write(json.dumps({"messages": r}, ensure_ascii=False) + "\n")
    return {"train": len(rows) - n_eval, "eval": n_eval, "rejected": rejected, "eval_path": eval_path}


def read_jsonl(path, limit=None):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
                if limit and len(rows) >= limit:
                    break
    return rows


JUDGE_PROMPT = ("你是嚴格的評審。下面有一個問題、一份參考答案（老師），和一份學生答案。"
                "請只根據學生答案的正確性、完整性與表達，給 1～10 分（10 分＝和參考答案一樣好）。"
                "只輸出 JSON：{\"score\": 分數, \"reason\": \"一句話理由\"}\n\n問題：{q}\n\n參考答案：{ref}\n\n學生答案：{ans}")


def evaluate_student(student_chat, judge_chat, eval_rows, cancel=None, on_progress=None):
    """用保留的評測題比較學生與老師：學生回答 → 老師評分。回傳 {"avg": 平均分, "items": [...]}。"""
    items = []
    for i, row in enumerate(eval_rows, 1):
        if cancel is not None and cancel.is_set():
            break
        msgs = row["messages"]
        q, ref = msgs[-2]["content"], msgs[-1]["content"]
        try:
            ans = student_chat(msgs[:-1])
            raw = judge_chat([{"role": "user", "content": JUDGE_PROMPT.replace("{q}", q).replace("{ref}", ref[:3000])
                               .replace("{ans}", (ans or "")[:3000])}])
            m = re.search(r"\{.*\}", raw or "", re.S)
            data = json.loads(m.group(0)) if m else {}
            score = float(data.get("score", 0))
            if not math.isfinite(score):                # v6.14.2 紅隊：評審回 NaN／Infinity 會被算成滿分
                raise ValueError(f"評分不是正常的數字：{data.get('score')!r}")
            score = max(0.0, min(10.0, score))
            items.append({"question": q, "answer": ans, "score": score, "reason": str(data.get("reason", ""))[:200]})
        except Exception as exc:                        # 單題失敗記下來，不中斷
            items.append({"question": q, "answer": "", "score": None, "reason": f"失敗：{exc}"})
        if on_progress:
            on_progress(i, len(eval_rows))
    scored = [x["score"] for x in items if x["score"] is not None]
    return {"avg": round(sum(scored) / len(scored), 2) if scored else None, "items": items}


# ── 匯入 Ollama ──
def find_ollama():
    exe = shutil.which("ollama")
    if exe:
        return exe
    if os.name == "nt":
        cand = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe")
        if os.path.isfile(cand):
            return cand
    return ""


def ollama_model_name(text):
    name = re.sub(r"[^a-z0-9._-]+", "-", (text or "").lower()).strip("-.")
    return (name or "my-model")[:60]


def clean_terminal(text):
    """去掉終端機的控制碼與進度列覆寫（ollama 的輸出全是這些，真正的錯誤會被蓋掉）。"""
    text = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text or "").replace("\r", "\n")
    return "\n".join(l.rstrip() for l in text.splitlines() if l.strip())


def _ollama_create(exe, name, modelfile, cwd, quantize):
    cmd = [exe, "create", name, "-f", modelfile] + (["--quantize", quantize] if quantize else [])
    output, status, code, _sec, _note = run_process_tree(cmd, cwd, scrubbed_env(), timeout=3600, shell=False)
    return status is None and code == 0, clean_terminal(output)


def read_gguf_info(path):
    """只用標準函式庫讀 GGUF 的檔頭：回傳 {"version","meta","tensors"}；格式不對時丟出 ValueError。
    也檢查每個張量都在檔案範圍內、彼此不重疊（快速測試與 GitHub 自動測試用來確認轉出來的檔案）。"""
    import struct
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        if f.read(4) != b"GGUF":
            raise ValueError("不是 GGUF 檔")
        ver, nt, nkv = struct.unpack("<IQQ", f.read(20))
        if nt > 100000 or nkv > 100000:
            raise ValueError("GGUF 檔頭的數量不合理")

        def rs():
            n, = struct.unpack("<Q", f.read(8))
            if n > 50_000_000:
                raise ValueError("GGUF 字串太長")
            return f.read(n).decode("utf-8", "replace")
        sizes = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}
        fmt = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i", 6: "f", 7: "?", 10: "Q", 11: "q", 12: "d"}

        def rv(t):
            if t == 8:
                return rs()
            if t == 9:
                et, n = struct.unpack("<IQ", f.read(12))
                if et == 8:
                    return [rs() for _ in range(n)]
                return list(struct.unpack(f"<{n}{fmt[et]}", f.read(n * sizes[et])))
            return struct.unpack("<" + fmt[t], f.read(sizes[t]))[0]
        meta = {}
        for _ in range(nkv):
            k = rs()
            t, = struct.unpack("<I", f.read(4))
            meta[k] = rv(t)
        tensors = []
        for _ in range(nt):
            name = rs()
            nd, = struct.unpack("<I", f.read(4))
            dims = struct.unpack(f"<{nd}Q", f.read(8 * nd))
            typ, off = struct.unpack("<IQ", f.read(12))
            tensors.append((name, dims, typ, off))
        align = int(meta.get("general.alignment", 32))
        base = (f.tell() + align - 1) // align * align
    spans = []
    for name, dims, typ, off in tensors:
        cnt = 1
        for d_ in dims:
            cnt *= d_
        nbytes = {0: cnt * 4, 1: cnt * 2, 8: cnt // 32 * 34}.get(typ)
        if nbytes is None:
            continue
        spans.append((base + off, base + off + nbytes, name))
    spans.sort()
    for a, b in zip(spans, spans[1:]):
        if a[1] > b[0]:
            raise ValueError(f"GGUF 的張量位置重疊：{a[2]}、{b[2]}")
    if spans and spans[-1][1] > size:
        raise ValueError("GGUF 檔不完整（張量超出檔案範圍）")
    return {"version": ver, "meta": meta, "tensors": tensors}


def convert_to_gguf(python, merged_dir, on_line=None):
    """用訓練用的 Python 跑 export_gguf，把合併後的模型轉成 GGUF（Q8_0）。回傳 (GGUF 路徑或空字串, 錯誤)。"""
    job = os.path.dirname(os.path.abspath(merged_dir))
    out = os.path.join(job, "model-q8_0.gguf")
    cfg_path = os.path.join(job, "gguf_config.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({"model_dir": os.path.abspath(merged_dir), "out_path": out}, f, ensure_ascii=False)
    job_obj = TrainJob(python, write_train_script("export_gguf", job), cfg_path,
                       on_event=lambda k, d: on_line and k in ("progress", "log") and on_line(json.dumps(d, ensure_ascii=False)))
    res = job_obj.run()
    if not res:
        return "", (job_obj.error or {}).get("error", "轉換失敗")
    try:
        read_gguf_info(out)
    except (OSError, ValueError) as exc:
        return "", f"轉出來的 GGUF 檢查沒過：{exc}"
    return out, ""


def ollama_import(merged_dir, name, system="", quantize="q4_K_M", on_line=None, python=None):
    """把合併後的模型（safetensors）匯入 Ollama。回傳 (成功, 訊息)。
    v6.16 實測：Ollama 0.40 起量化參數改名（q4_K_M → int4／int8），而且匯入 safetensors 要 MLX 元件；
    所以依序試：指定的量化 → Ollama 說支援的量化（優先 int4）→ 不量化，失敗時說出真正的原因。"""
    exe = find_ollama()
    if not exe:
        return False, "找不到 Ollama（ollama.exe）。請先安裝並開啟 Ollama。"
    if not os.path.isfile(os.path.join(merged_dir, "config.json")):
        return False, f"{merged_dir} 不是完整的模型資料夾（沒有 config.json）"
    name = ollama_model_name(name)
    modelfile = os.path.join(merged_dir, "Modelfile")
    with open(modelfile, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"FROM {os.path.abspath(merged_dir)}\n")
        if system:
            f.write('SYSTEM """' + system.replace('"""', "'''") + '"""\n')
    tried, last = [], ""
    plan = [quantize] if quantize else []
    while True:
        q = plan.pop(0) if plan else ""
        if q in tried:
            if not plan:
                break
            continue
        tried.append(q)
        ok, out = _ollama_create(exe, name, modelfile, merged_dir, q)
        if on_line:
            on_line(out[-2000:])
        if ok:
            return True, f"已匯入 Ollama：{name}" + (f"（量化：{q}）" if q else "（沒有量化）")
        last = out
        if "mlx" in out.lower():
            break                       # 新版 Ollama 缺 MLX：換量化方式也沒用，直接改用 GGUF
        m = re.search(r"unsupported --quantize[^\n]*supported types are ([^\n]+)", out, re.I)
        if m:
            types = [t.strip(" .") for t in m.group(1).split(",")]
            plan += [t for t in ("int4", "q4_K_M", "int8", "q8_0") if t in types and t not in tried]
        if "" not in tried and "" not in plan:
            plan.append("")
        if not plan:
            break
    if python:
        # v6.16.1：Windows 實測，新版 Ollama 沒有 MLX、不能直接匯入 safetensors → 自己轉成 GGUF（每一版 Ollama 都能讀）
        if on_line:
            on_line("直接匯入不行，改成先轉成 GGUF…")
        gguf, err = convert_to_gguf(python, merged_dir, on_line)
        if gguf:
            gfile = os.path.join(merged_dir, "Modelfile.gguf")
            with open(gfile, "w", encoding="utf-8", newline="\n") as f:
                f.write(f"FROM {gguf}\n")
                if system:
                    f.write('SYSTEM """' + system.replace('"""', "'''") + '"""\n')
            ok, out = _ollama_create(exe, name, gfile, merged_dir, "")
            if on_line:
                on_line(out[-2000:])
            if ok:
                return True, f"已匯入 Ollama：{name}（先轉成 GGUF，Q8_0）"
            last = out
            tried.append("GGUF")
        else:
            last = f"轉成 GGUF 失敗：{err}"
            tried.append("GGUF（轉換失敗）")
    tail = "\n".join(last.splitlines()[-4:])
    low = last.lower()
    if "mlx" in low:
        hint = "這個 Ollama 版本匯入 safetensors 模型需要的元件（MLX）沒有安裝或載入失敗：請更新、或重新安裝完整版的 Ollama 後再試。"
    elif "unsupported architecture" in low or "unknown architecture" in low:
        hint = "這個模型架構 Ollama 不能直接匯入，請改選 Qwen2.5 或 Llama 系列的底模。"
    elif "connection refused" in low or "could not connect" in low:
        hint = "Ollama 沒有在執行：請先開啟 Ollama。"
    else:
        hint = ""
    tries = "、".join(t or "不量化" for t in tried)
    return False, f"ollama create 失敗（試過：{tries}）{('：' + hint) if hint else ''}\n{tail}"


# ── 雲端訓練包 ──
COLAB_STEPS = [
    ("markdown", "# AI 協作：雲端 GPU 訓練\n1. 上方選單「執行階段 → 變更執行階段類型」選 **T4 GPU**（或更好的 GPU）\n"
                 "2. 依序執行下面每一格\n3. 最後會下載 `結果.zip`，回到 AI 協作的訓練工作室按「匯入雲端結果」"),
    ("code", "!nvidia-smi"),
    ("code", "from google.colab import files\nup = files.upload()   # 選擇 AI 協作產生的 訓練包.zip\n"
             "import zipfile, os\nname = list(up)[0]\nzipfile.ZipFile(name).extractall('job')\nos.chdir('job')\nprint(os.listdir('.'))"),
    ("code", "!pip install -q -r requirements.txt"),
    ("code", "!python {script} --config config.json"),
    ("code", "import shutil\nshutil.make_archive('/content/結果', 'zip', 'out')\nfiles.download('/content/結果.zip')"),
]


def make_notebook(script_name):
    cells = []
    for kind, src in COLAB_STEPS:
        src = src.replace("{script}", script_name)
        cell = {"cell_type": kind, "metadata": {}, "source": src.splitlines(True)}
        if kind == "code":
            cell.update(execution_count=None, outputs=[])
        cells.append(cell)
    return {"nbformat": 4, "nbformat_minor": 5, "cells": cells,
            "metadata": {"accelerator": "GPU", "colab": {"provenance": []}, "kernelspec": {"name": "python3", "display_name": "Python 3"}}}


def make_cloud_package(task, config, data_paths, dest_zip):
    """打包給雲端 GPU：腳本＋config.json（路徑改成相對）＋資料＋requirements.txt＋Colab 筆記本＋說明＋run.sh。
    data_paths：{config 的鍵: 本機路徑（檔案或資料夾）}。回傳 zip 路徑。"""
    import zipfile
    script = TRAIN_TASKS[task]["script"]
    cfg = dict(config)
    cfg["out_dir"] = "out"
    cfg.pop("out_path", None)
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for key, path in data_paths.items():
            if not path:
                continue
            base = os.path.basename(os.path.normpath(path))
            if os.path.isdir(path):
                for cur, _dirs, names in os.walk(path):
                    for n in names:
                        full = os.path.join(cur, n)
                        if os.path.islink(full):
                            continue
                        z.write(full, "data/" + base + "/" + os.path.relpath(full, path).replace("\\", "/"))
                cfg[key] = f"data/{base}"
            elif os.path.isfile(path):
                z.write(path, f"data/{base}")
                cfg[key] = f"data/{base}"
        z.writestr(f"{script}.py", train_script_text(script))
        z.writestr("config.json", json.dumps(cfg, ensure_ascii=False, indent=2))
        z.writestr("requirements.txt", requirements_text(task, cuda=True))
        z.writestr("雲端訓練.ipynb", json.dumps(make_notebook(f"{script}.py"), ensure_ascii=False, indent=1))
        z.writestr("run.sh", f"#!/bin/bash\nset -e\npip install -q -r requirements.txt\npython {script}.py --config config.json\n"
                             "python -c \"import shutil; shutil.make_archive('結果', 'zip', 'out')\"\necho 完成：下載 結果.zip\n")
        z.writestr("說明.md", f"# AI 協作雲端訓練包：{TRAIN_TASKS[task]['label']}\n\n"
                              "## Google Colab\n1. 打開 https://colab.research.google.com ，「上傳」`雲端訓練.ipynb`\n"
                              "2. 執行階段選 GPU，依序執行每一格；第三格上傳這個 zip\n3. 最後下載 `結果.zip`\n\n"
                              "## RunPod／其他有 GPU 的 Linux 主機\n```\nunzip 訓練包.zip -d job && cd job && bash run.sh\n```\n\n"
                              "## 回到 AI 協作\n訓練工作室 →「匯入雲端結果」→ 選 `結果.zip`。\n")
    return dest_zip


def zipfile_error():
    import zipfile
    return zipfile.BadZipFile


PICKLE_EXT = (".bin", ".pt", ".pth", ".pkl", ".pickle", ".ckpt", ".joblib")


def import_cloud_result(zip_path, dest_dir, max_bytes=80_000_000_000, max_files=20000, skipped=None):
    """安全地解開雲端訓練的結果：不允許絕對路徑、..、連結；總大小與檔案數有上限；
    pickle 格式的權重檔（.bin、.pt…，載入時可以執行任意程式碼）不解開，本程式產生的都是 safetensors。回傳解開的檔案數。"""
    import zipfile
    real_dest = os.path.realpath(dest_dir)
    os.makedirs(real_dest, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        infos = z.infolist()
        if sum(i.file_size for i in infos) > max_bytes:
            raise ValueError("結果檔解開後太大")
        if len(infos) > max_files:
            raise ValueError(f"結果檔裡有 {len(infos):,} 個檔案，超過上限 {max_files:,}")
        n = 0
        for info in infos:
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or re.match(r"^[A-Za-z]:", name) or ".." in name.split("/"):
                raise ValueError(f"結果檔裡有不安全的路徑：{name}")
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                continue                                   # 符號連結：不解開
            target = os.path.realpath(os.path.join(real_dest, name))
            if not _inside(target, real_dest):
                raise ValueError(f"結果檔裡有不安全的路徑：{name}")
            if name.endswith("/"):
                os.makedirs(target, exist_ok=True)
                continue
            if name.lower().endswith(PICKLE_EXT):
                if skipped is not None:
                    skipped.append(name)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            n += 1
    return n


# ── 產出的模型清單 ──
def load_registry():
    """模型清單；格式不對、種類不認得、或指到 pickle 格式檔案的項目都略過（清單檔可能被改過）。"""
    try:
        with open(TRAIN_REGISTRY, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, dict) and x.get("kind") in ("llm", "voice", "video_lora", "image_lora")
            and isinstance(x.get("path"), str) and isinstance(x.get("name"), str)
            and not x["path"].lower().endswith(PICKLE_EXT)]


def register_artifact(kind, name, path, **extra):
    """kind：llm（Ollama 模型名稱）、voice（F5-TTS 模型）、video_lora（影片 LoRA）。"""
    items = [x for x in load_registry() if not (x.get("kind") == kind and x.get("path") == path)]
    items.append(dict(kind=kind, name=name, path=path, created=time.strftime("%Y-%m-%d %H:%M"), **extra))
    os.makedirs(TRAIN_DIR, exist_ok=True)
    tmp = TRAIN_REGISTRY + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    os.replace(tmp, TRAIN_REGISTRY)
    return items


def new_job_dir(kind, name="", root=None):
    """建立一個工作資料夾。root＝使用者指定的「工作與成果資料夾」（v6.19.1；沒指定就用程式資料夾底下的 訓練/）。"""
    safe = re.sub(r'[\\/:*?"<>|\s]+', "_", name or "").strip("_")[:30]
    path = os.path.join(root or TRAIN_DIR, f"{time.strftime('%Y%m%d_%H%M%S')}_{kind}" + (f"_{safe}" if safe else ""))
    os.makedirs(path, exist_ok=True)
    return path


def check_output_dir(path):
    """使用者指定的資料夾能不能用：回傳 (錯誤說明或 "", 剩餘空間 GB 或 None)。不存在會建立；會實際寫一個暫存檔測試。"""
    import tempfile as _tf
    path = (path or "").strip()
    if not path:
        return "沒有選擇資料夾", None
    if not os.path.isabs(path):
        return "請用完整路徑（例如 D:\\AI訓練）", None
    try:
        os.makedirs(path, exist_ok=True)
        with _tf.NamedTemporaryFile(dir=path, prefix=".寫入測試_", delete=True) as f:
            f.write(b"ok")
    except OSError as exc:
        return f"不能寫入這個資料夾：{exc}", None
    try:
        return "", shutil.disk_usage(path).free / 2 ** 30
    except OSError:
        return "", None


def default_hf_home():
    """Hugging Face 預設把模型下載到哪裡（系統已經設了 HF_HOME 就是那裡）。"""
    return os.environ.get("HF_HOME") or os.path.join(os.path.expanduser("~"), ".cache", "huggingface")


def run_train_smoke(python=None, folder=None, tasks=None):
    """--train-smoke：用極小的模型在 CPU 上把四條流程各跑一次（GitHub 自動測試也用這個）。回傳失敗的項目清單。"""
    import struct
    import tempfile as _tf
    import wave
    import zlib
    python = python or sys.executable
    folder = folder or _tf.mkdtemp(prefix="ai協作訓練測試_")
    data = os.path.join(folder, "資料")
    os.makedirs(os.path.join(data, "錄音"), exist_ok=True)
    os.makedirs(os.path.join(data, "影片"), exist_ok=True)
    with open(os.path.join(data, "llm.jsonl"), "w", encoding="utf-8") as f:
        for i in range(12):
            f.write(json.dumps({"messages": [{"role": "system", "content": DISTILL_SYSTEM}, {"role": "user", "content": f"1+{i}=?"},
                                             {"role": "assistant", "content": f"答案是 {1 + i}。"}]}, ensure_ascii=False) + "\n")
    for i, text in enumerate(("你好，今天天氣很好。", "這是測試錄音。")):
        with wave.open(os.path.join(data, "錄音", f"c{i}.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            w.writeframes(b"".join(struct.pack("<h", int(6000 * math.sin(2 * math.pi * (200 + 40 * i) * n / 24000)))
                                   for n in range(48000)))
        with open(os.path.join(data, "錄音", f"c{i}.txt"), "w", encoding="utf-8") as f:
            f.write(text)
    rows = b"".join(b"\x00" + b"".join(bytes([(x * 16) % 256, (y * 16) % 256, 128]) for x in range(16)) for y in range(16))

    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)
    with open(os.path.join(data, "影片", "a.png"), "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 16, 16, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))
    with open(os.path.join(data, "影片", "a.txt"), "w", encoding="utf-8") as f:
        f.write("測試圖片")
    plan = [("llm", "train_llm", {"base_model": "x", "data_path": os.path.join(data, "llm.jsonl")}),
            ("tts", "tts", {"mode": "finetune", "consent": True, "data_dir": os.path.join(data, "錄音")}),
            ("video_lora", "video_lora", {"data_dir": os.path.join(data, "影片"), "trigger": "t"}),
            ("video", "video_gen", {"model": "wan-1.3b", "prompt": "test"}),
            ("image_lora", "image_lora", {"base": "sd15", "data_dir": os.path.join(data, "影片"), "trigger": "zhtest"}),
            ("image", "image_gen", {"model": "sdxl-turbo", "prompt": "test", "count": 2})]
    failed = []
    for key, script, cfg in plan:
        if tasks and key not in tasks:
            continue
        job = os.path.join(folder, key)
        os.makedirs(job, exist_ok=True)
        cfg = dict(cfg, out_dir=os.path.join(job, "out"))
        if key == "image" and os.path.isdir(os.path.join(folder, "image_lora", "out", "lora")):
            cfg["lora_path"] = os.path.join(folder, "image_lora", "out", "lora")     # 順便測「套用自己訓練的圖片 LoRA」
        if key == "video" and os.path.isdir(os.path.join(folder, "video_lora", "out", "lora")):
            cfg["lora_path"] = os.path.join(folder, "video_lora", "out", "lora")     # 順便測「套用自己訓練的 LoRA」
        path = os.path.join(job, "config.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False)
        started = time.time()
        msgs = []
        jobobj = TrainJob(python, write_train_script(script, job), path, smoke=True,
                          on_event=lambda k, d, m=msgs: m.append((k, d)) if k in ("error", "result") else None)
        result = jobobj.run()
        ok = bool(result)
        print(f"{'✔' if ok else '✘'} {TRAIN_TASKS[key]['label']}（{time.time() - started:.0f} 秒）"
              + ("" if ok else f"：{(jobobj.error or {}).get('error', '')}"), flush=True)
        if not ok:
            failed.append(key)
            print((jobobj.error or {}).get("trace", "")[-3000:], flush=True)
        elif key == "image_lora":                  # LoRA 要存成生成看得懂的格式，預覽圖要是真的 PNG
            lora = result.get("lora") or ""
            arch = lora_arch(lora)
            prev = media_info(result.get("preview") or "")
            good = os.path.isfile(os.path.join(lora, "pytorch_lora_weights.safetensors")) and arch in ("sd", "sd15") \
                and (prev.get("width"), prev.get("height")) == (64, 64)
            print(f"{'✔' if good else '✘'} 圖片 LoRA 檢查：判斷為 {arch or '看不出來'}、預覽圖 {prev.get('width')}×{prev.get('height')}",
                  flush=True)
            if not good:
                failed.append("image_lora_files")
        elif key == "image":                       # 生成的圖要真的是讀得到的 PNG、張數對、尺寸對
            imgs = result.get("images") or []
            sizes = [(media_info(p).get("width"), media_info(p).get("height")) for p in imgs]
            good = len(imgs) == 2 and all(sz == (64, 64) for sz in sizes) and imgs[0] != imgs[1]
            print(f"{'✔' if good else '✘'} 圖片檔檢查：{len(imgs)} 張，尺寸 {sizes}", flush=True)
            if not good:
                failed.append("image_files")
        elif key == "llm" and result.get("merged"):
            t0 = time.time()
            gguf, err = convert_to_gguf(python, result["merged"])
            info = read_gguf_info(gguf) if gguf else None
            good = bool(info) and info["meta"].get("general.architecture") == "llama" and len(info["tensors"]) > 10
            print(f"{'✔' if good else '✘'} 轉成 GGUF 給 Ollama（{time.time() - t0:.0f} 秒）"
                  + (f"：{len(info['tensors'])} 個張量" if good else f"：{err}"), flush=True)
            if not good:
                failed.append("gguf")
    return failed


# ───────────────────────── v6.15：訓練前預估顯存 ─────────────────────────
# 粗略的經驗公式（對照公開的 QLoRA／diffusers 實測數字定的），只用來在開始前提醒「可能不夠」，不是精確值。
def estimate_vram(task, cfg):
    """回傳 (預估 GB, [可以怎麼省的建議])。"""
    tips = []
    if task == "llm":
        b = model_size_b(cfg.get("base_model")) or 1.5          # 用程式原本的判斷；看不出參數量時當成 1.5B
        max_len, bsz = int(cfg.get("max_len", 1024)), int(cfg.get("batch_size", 1))
        q = cfg.get("qlora", True)
        weights = b * (0.6 if q else 2.1)
        act = 0.9 * (b ** 0.5) * (max_len / 1024) * bsz
        gb = weights + 1.2 + act
        if max_len > 512:
            tips.append(f"「最長長度」從 {max_len} 調成 512")
        if b >= 3:
            tips.append("改用較小的底模（例如 Qwen2.5-1.5B）")
    elif task == "tts":
        gb = 5.5 if cfg.get("mode") == "finetune" else 3.0
        if cfg.get("mode") == "finetune":
            tips.append("縮短每段錄音（3～10 秒）")
    elif task == "video":
        tokens = ((int(cfg.get("num_frames", 33)) - 1) // 4 + 1) * (int(cfg.get("height", 272)) // 16) * (int(cfg.get("width", 480)) // 16)
        base = {"wan-1.3b": 3.5, "ltx": 4.0, "cogvideox-2b": 5.0}.get(cfg.get("model"), 4.0)
        gb = base + 1.5 * tokens / 4590
        tips += ["調小寬高（例如 416×240）", "減少格數（例如 17 格）"]
    elif task == "image":
        model = cfg.get("model", "sdxl-turbo")
        w, h = IMAGE_DEFAULTS.get(model, (1024, 1024, 0, 0))[:2]
        mp = int(cfg.get("width") or w) * int(cfg.get("height") or h) / 1048576          # 百萬像素
        memory = cfg.get("memory", "auto")
        if memory == "lowest":
            gb = 2.5 + 0.8 * mp
        elif model == "sd15":
            gb = 2.6 + 1.4 * mp
        elif model in ("sdxl", "sdxl-turbo"):
            gb = (7.5 if memory == "normal" else 4.8) + 1.6 * mp
        elif model == "sd35-medium":
            gb = (14.0 if memory == "normal" else 4.6) + 1.6 * mp
        else:                                    # FLUX：4-bit 量化的主模型約 6.7 GB 要整個放進顯示卡
            gb = (24.0 if memory == "normal" else 6.7) + 1.3 * mp
        if memory == "normal":
            tips.append("記憶體模式改成「自動」（會自動用 CPU 卸載）")
        if mp > 0.6:
            tips.append("調小寬高（例如 768×768 或 512×512）")
        if model.startswith("flux"):
            tips.append("改用 SDXL-Turbo 或 SDXL")
        tips += ["記憶體模式選「極省」（很慢但放得下）", "改用雲端 GPU"]
    elif task == "image_lora":
        base = cfg.get("base", "sdxl")
        res = int(cfg.get("resolution") or (768 if base == "sdxl" else 512))
        mp = res * res / 1048576
        ckpt = cfg.get("gradient_checkpointing", True)
        # LoRA 本身：r=16 時 SDXL 約 2300 萬、SD 1.5 約 800 萬個參數；fp32 權重＋梯度＋8-bit 優化器狀態 ≈ 每個參數 10 位元組
        if base == "sdxl":                       # UNet 2.6B（bf16 約 5.1 GB）一定要整個放進顯示卡
            gb = 5.7 + (2.3 if ckpt else 9.0) * mp + 0.012 * int(cfg.get("lora_r", 16))
        else:
            gb = 2.4 + (2.0 if ckpt else 7.0) * mp + 0.005 * int(cfg.get("lora_r", 16))
        if res > (768 if base == "sdxl" else 512):
            tips.append(f"解析度改成 {768 if base == 'sdxl' else 512}")
        if base == "sdxl":
            tips.append("改用 SD 1.5（8 GB 很穩）")
        tips += ["LoRA r 調小（例如 8）", "改用雲端 GPU"]
    elif task == "video_lora":
        tokens = ((int(cfg.get("num_frames", 17)) - 1) // 4 + 1) * (int(cfg.get("height", 240)) // 16) * (int(cfg.get("width", 416)) // 16)
        gb = 4.0 + 2.0 * tokens / 1950 + 0.02 * int(cfg.get("lora_r", 32))
        tips += ["調小寬高（例如 320×192）", "減少格數（例如 9 格）", "改用雲端 GPU"]
    else:
        return 0.0, []
    return round(gb, 1), tips


def vram_verdict(task, cfg, total_gb):
    """跟顯示卡比較：回傳 (等級 ok／tight／over, 說明)。total_gb 為 None（沒有顯示卡）時回傳 ("none", 說明)。"""
    gb, tips = estimate_vram(task, cfg)
    if not total_gb:
        return "none", f"預估需要約 {gb} GB 顯存；沒有偵測到 NVIDIA 顯示卡，會用 CPU（非常慢），建議改用雲端 GPU。"
    if gb <= total_gb * 0.8:
        return "ok", f"預估顯存約 {gb} GB（你的顯示卡 {total_gb:.0f} GB）：應該夠用。"
    if gb <= total_gb * 0.9:
        return "tight", f"預估顯存約 {gb} GB（你的顯示卡 {total_gb:.0f} GB）：有點緊，同時開其他吃顯示卡的程式可能會不夠。"
    return "over", (f"預估顯存約 {gb} GB，{'超過' if gb > total_gb else '幾乎用滿'}你的顯示卡（{total_gb:.0f} GB），很可能會記憶體不足。建議："
                    + "、".join(tips[:3]) + "。")


def gpu_total_gb():
    st = gpu_status()
    if st and st.get("mem_total"):
        return st["mem_total"] / 2 ** 30
    return None


def unregister_artifact(kind, path):
    """從模型清單拿掉（檔案不刪）。"""
    items = [x for x in load_registry() if not (x.get("kind") == kind and x.get("path") == path)]
    os.makedirs(TRAIN_DIR, exist_ok=True)
    tmp = TRAIN_REGISTRY + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    os.replace(tmp, TRAIN_REGISTRY)
    return items


# ───────────────────────── 生成的作品：辨識、資訊、清單（v6.18.1） ─────────────────────────
# v6.18.0 以前：生成完只自動開一次，之後沒有地方再開；工作區雙擊圖片／影片／音檔只顯示「二進位檔，無法預覽」；
# Windows 沒有替 .mp4／.wav 設定預設程式時，os.startfile 直接失敗。
MEDIA_EXTS = {"video": (".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v"),
              "audio": (".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".opus"),
              "image": (".png", ".gif", ".jpg", ".jpeg", ".webp", ".bmp", ".ppm", ".pgm")}
MEDIA_LABELS = {"video": "影片", "audio": "語音", "image": "圖片"}


def media_kind(path):
    ext = os.path.splitext(path or "")[1].lower()
    return next((k for k, exts in MEDIA_EXTS.items() if ext in exts), "")


def _mp4_duration(f, size):
    """讀 mp4／mov 的 moov/mvhd 取得長度（秒）；讀不到回傳 None。只看方塊標頭，不載入整個檔案。"""
    import struct

    def boxes(start, end):
        pos = start
        while pos + 8 <= end:
            f.seek(pos)
            head = f.read(8)
            if len(head) < 8:
                return
            n, kind = struct.unpack(">I4s", head)
            hdr = 8
            if n == 1:
                n = struct.unpack(">Q", f.read(8))[0]
                hdr = 16
            elif n == 0:
                n = end - pos
            if n < hdr:
                return
            yield kind, pos + hdr, pos + n
            pos += n
    for kind, a, b in boxes(0, size):
        if kind == b"moov":
            for k2, a2, _b2 in boxes(a, b):
                if k2 == b"mvhd":
                    f.seek(a2)
                    version = f.read(1)[0]
                    f.read(3)
                    if version == 1:
                        f.read(16)
                        scale, dur = struct.unpack(">IQ", f.read(12))
                    else:
                        f.read(8)
                        scale, dur = struct.unpack(">II", f.read(8))
                    return dur / scale if scale else None
    return None


def media_info(path):
    """{"kind", "size", "seconds", "width", "height", "note"}：盡量只用標準函式庫讀出長度與尺寸。"""
    import struct
    info = {"kind": media_kind(path), "size": 0, "seconds": None, "width": None, "height": None, "note": ""}
    try:
        info["size"] = os.path.getsize(path)
    except OSError:
        info["note"] = "找不到檔案（可能被移動或刪除）"
        return info
    if info["size"] == 0:
        info["note"] = "檔案是空的（0 bytes），生成可能沒有成功"
        return info
    try:
        ext = os.path.splitext(path)[1].lower()
        if ext == ".wav":
            import wave
            try:
                with wave.open(path, "rb") as w:
                    info["seconds"] = w.getnframes() / float(w.getframerate() or 1)
            except (wave.Error, EOFError):         # 浮點數格式的 wav：wave 不支援，改從檔頭算
                with open(path, "rb") as f:
                    head = f.read(4096)
                fmt, data = head.find(b"fmt "), head.find(b"data")
                if fmt >= 0 and data >= 0:
                    rate, = struct.unpack("<I", head[fmt + 12:fmt + 16])
                    block, = struct.unpack("<H", head[fmt + 20:fmt + 22])
                    length, = struct.unpack("<I", head[data + 4:data + 8])
                    info["seconds"] = length / float(rate * block) if rate and block else None
        elif ext in (".mp4", ".mov", ".m4v", ".m4a"):
            with open(path, "rb") as f:
                info["seconds"] = _mp4_duration(f, info["size"])
        elif ext == ".png":
            with open(path, "rb") as f:
                head = f.read(24)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                info["width"], info["height"] = struct.unpack(">II", head[16:24])
        elif ext == ".gif":
            with open(path, "rb") as f:
                head = f.read(10)
            if head[:3] == b"GIF":
                info["width"], info["height"] = struct.unpack("<HH", head[6:10])
    except (OSError, struct.error, IndexError, ValueError):
        pass
    return info


def media_summary(path):
    i = media_info(path)
    if i["note"]:
        return i["note"]
    parts = [MEDIA_LABELS.get(i["kind"], "檔案"), f"{i['size'] / 1048576:.1f} MB" if i["size"] >= 1048576 else f"{i['size'] / 1024:.0f} KB"]
    if i["seconds"]:
        parts.append(f"{i['seconds']:.1f} 秒")
    if i["width"]:
        parts.append(f"{i['width']}×{i['height']}")
    return "，".join(parts)


def list_generated_media(folder=None, limit=500):
    """訓練工作室生成的作品（每個工作資料夾的 out/ 底下的影片、語音、圖片），新的在前。
    訓練資料、參考錄音、模型檔不算作品。folder 可以是一個資料夾或多個（換過「工作與成果資料夾」時，舊的也要列出來）。"""
    folders = [folder] if isinstance(folder, str) else list(folder or [TRAIN_DIR])
    out, seen = [], set()
    for one in folders:
        real = os.path.realpath(one) if one else ""
        if not real or real in seen or not os.path.isdir(real):
            continue
        seen.add(real)
        out += _media_in(one)
    out.sort(key=lambda x: -x["mtime"])
    return out[:limit]


def _media_in(folder):
    out = []
    for job in os.listdir(folder):
        out_dir = os.path.join(folder, job, "out")
        if not os.path.isdir(out_dir):
            continue
        for root, dirs, files in os.walk(out_dir):
            if root.count(os.sep) - out_dir.count(os.sep) >= 2:
                dirs[:] = []
            for name in files:
                kind = media_kind(name)
                if not kind:
                    continue
                full = os.path.join(root, name)
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                out.append({"path": full, "kind": kind, "name": name, "job": job, "size": st.st_size, "mtime": st.st_mtime,
                            "smoke": "_測試" in job})
    return out


# ───────────────────────── LoRA 跟模型相不相容（v6.19.2） ─────────────────────────
# 使用者把「影片 LoRA 訓練」的成果（Wan）選給 SDXL 用：diffusers 找不到任何對得上的權重、什麼都沒載入，
# 接著只丟出「Adapter name(s) {'custom'} not in the list of present adapters」。開始前就先看檔案裡的權重名稱。
LORA_ARCH_LABELS = {"sd15": "Stable Diffusion 1.5", "sd2": "Stable Diffusion 2.x", "sdxl": "SDXL", "sd": "SD 1.5 或 SDXL",
                    "sd3": "SD 3.x", "flux": "FLUX", "sd3_or_flux": "SD 3.x 或 FLUX", "wan": "Wan 影片模型",
                    "video": "影片模型（LTX／CogVideoX）"}
IMAGE_MODEL_ARCH = {"sd15": {"sd15", "sd"}, "sdxl": {"sdxl", "sd"}, "sdxl-turbo": {"sdxl", "sd"},
                    "sd35-medium": {"sd3", "sd3_or_flux"}, "flux-schnell": {"flux", "sd3_or_flux"}, "flux-dev": {"flux", "sd3_or_flux"}}


def safetensors_header(path, limit=100_000_000):
    """只讀 safetensors 的檔頭（8 位元組長度＋JSON），不載入權重。格式不對丟出 ValueError。"""
    import struct
    with open(path, "rb") as f:
        raw = f.read(8)
        if len(raw) != 8:
            raise ValueError("不是 safetensors 檔")
        n = struct.unpack("<Q", raw)[0]
        if not 2 <= n <= limit:
            raise ValueError("不是 safetensors 檔（檔頭長度不對）")
        try:
            head = json.loads(f.read(n).decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise ValueError("不是 safetensors 檔（檔頭不是 JSON）")
    if not isinstance(head, dict):
        raise ValueError("不是 safetensors 檔")
    head.pop("__metadata__", None)
    return head


def _lora_file(path):
    if os.path.isdir(path):
        names = sorted(n for n in os.listdir(path) if n.endswith(".safetensors"))
        names.sort(key=lambda n: n != "pytorch_lora_weights.safetensors")
        return os.path.join(path, names[0]) if names else ""
    return path


def lora_arch(path):
    """看 LoRA 檔裡的權重名稱與形狀，判斷它是給哪種模型用的。回傳 LORA_ARCH_LABELS 的鍵，看不出來回傳 ""。"""
    path = os.path.realpath(path or "")
    for item in load_registry():                      # 自己訓練的影片 LoRA：清單裡就知道是 Wan
        root = os.path.realpath(item.get("path") or "")
        if item.get("kind") in ("video_lora", "image_lora") and root and (path == root or path.startswith(root + os.sep)):
            return "wan" if item["kind"] == "video_lora" else (item.get("arch") or "sd")
    f = _lora_file(path)
    if not f or not os.path.isfile(f):
        return ""
    try:
        head = safetensors_header(f)
    except (OSError, ValueError):
        return ""
    keys = list(head)

    def has(pat):
        rx = re.compile(pat)
        return any(rx.search(k) for k in keys)
    if has(r"^(transformer\.|diffusion_model\.)?blocks\.\d+\.(attn1|attn2|self_attn|cross_attn|ffn)"):
        return "wan"
    if has(r"single_transformer_blocks|lora_unet_single_blocks|(^|\.)single_blocks\.\d+|(^|\.)double_blocks\.\d+|lora_unet_double_blocks"):
        return "flux"
    if has(r"^(transformer\.)?transformer_blocks\.\d+\.attn[12]\."):
        return "video"
    if has(r"^(transformer\.)?transformer_blocks\.\d+\.|joint_blocks"):
        return "sd3_or_flux"
    if has(r"^(unet\.|lora_unet_|text_encoder|lora_te)"):
        if has(r"text_encoder_2|lora_te2_"):
            return "sdxl"
        for k, v in head.items():                     # 交叉注意力的輸入維度：768＝SD 1.5、1024＝SD 2、2048＝SDXL
            if re.search(r"attn2.*to_k.*(lora_A|lora_down|lora\.down)", k) and isinstance(v, dict) and len(v.get("shape") or []) == 2:
                dim = v["shape"][1]
                return {768: "sd15", 1024: "sd2", 2048: "sdxl"}.get(dim, "sd")
        return "sd"
    return ""


def lora_compat(model_key, path):
    """(True／False／None, 說明)：None＝看不出來是給哪種模型的（讓它試，但先提醒）。"""
    arch = lora_arch(path)
    need = IMAGE_MODEL_ARCH.get(model_key, set())
    model_label = next((d.split("：")[0] for m, d, _l in IMAGE_MODELS if m == model_key), model_key)
    if not arch:
        return None, "看不出這個 LoRA 是給哪種模型用的，會直接試著套用；如果失敗，代表它跟這個模型不相容。"
    if arch in need:
        return True, f"LoRA 是給 {LORA_ARCH_LABELS[arch]} 用的，跟 {model_label} 相容。"
    hint = ("影片 LoRA 只能用在「影片生成」分頁。" if arch in ("wan", "video") else
            "請改選同一種模型，或換一個給這個模型用的 LoRA（SD 1.5、SDXL、FLUX 的 LoRA 不能互用）。")
    return False, f"這個 LoRA 是給 {LORA_ARCH_LABELS[arch]} 用的，不能用在 {model_label}。{hint}"
