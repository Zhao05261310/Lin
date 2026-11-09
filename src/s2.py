# ═════════════════════════ 2. 金鑰與環境變數 ═════════════════════════
# 金鑰本體永遠不寫入任何檔案。兩種來源：執行環境（$env: 臨時設定）與 Windows 系統設定（setx／編輯環境變數）。

ENV_NAME_PATTERN = re.compile(r"[A-Z][A-Z0-9_]*")
NO_KEY = "NO_KEY"          # 特殊值：這個端點不需要金鑰（本機模型）

PRIORITY_SYSTEM = "system"      # 系統設定值優先（預設，避免改了環境變數後仍用到舊值）
PRIORITY_PROCESS = "process"    # 執行環境優先（尊重 $env: 臨時設定）
PRIORITY_LABELS = {
    PRIORITY_SYSTEM: "系統設定值優先（setx／編輯環境變數）",
    PRIORITY_PROCESS: "執行環境優先（$env: 臨時設定）",
}

_registry_cache = {}
_CACHE_SECONDS = 2.0


def read_windows_env(name):
    """從 Windows 登錄檔讀取目前的使用者／系統環境變數。回傳 (值, 範圍) 或 (None, None)。

    結果快取 2 秒，避免打字時每個按鍵都去讀登錄檔。
    """
    if sys.platform != "win32" or not name:
        return None, None
    now = time.monotonic()
    cached = _registry_cache.get(name)
    if cached and now - cached[0] < _CACHE_SECONDS:
        return cached[1]
    result = (None, None)
    try:
        import winreg
        places = [
            (winreg.HKEY_CURRENT_USER, r"Environment", "使用者"),
            (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment", "系統"),
        ]
        for root, path, scope in places:
            try:
                with winreg.OpenKey(root, path) as key:
                    value, kind = winreg.QueryValueEx(key, name)
            except OSError:
                continue
            if isinstance(value, str):
                if kind == winreg.REG_EXPAND_SZ:
                    value = os.path.expandvars(value)
                result = (value, scope)
                break
    except ImportError:
        pass
    _registry_cache[name] = (now, result)
    return result


def clean_key(value):
    """去掉環境變數常見殘留：前後空白、換行、成對引號。"""
    return (value or "").strip().strip("\"'").strip()


def fingerprint(key):
    """金鑰 SHA-256 前 8 碼：可比對是否同一把，但無法還原金鑰。"""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:8] if key else "—"


def lookup_env(name, priority=PRIORITY_SYSTEM):
    """回傳 dict：value（採用的值，可能為 None）、source（說明）、other（另一來源的值，若不同）。"""
    process_value = os.environ.get(name)
    system_value, scope = read_windows_env(name)
    info = {"value": None, "source": "", "other": None, "other_source": ""}
    candidates = []
    if system_value is not None:
        candidates.append((system_value, f"系統{scope}變數"))
    if process_value is not None:
        candidates.append((process_value, "執行環境變數"))
    if priority == PRIORITY_PROCESS:
        candidates.reverse()
    if not candidates:
        return info
    info["value"], info["source"] = candidates[0]
    if len(candidates) > 1 and clean_key(candidates[1][0]) != clean_key(candidates[0][0]):
        info["other"], info["other_source"] = candidates[1]
    return info


# 送到雲端模型、存進對話紀錄之前，先把像金鑰的字串遮起來（只認格式很明確的金鑰，避免把一般程式碼遮掉）
SECRET_PATTERNS = [
    (r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?(-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)", "私鑰"),
    (r"\bnvapi-[A-Za-z0-9_\-]{20,}", "NVIDIA 金鑰"),
    (r"\bsk-ant-[A-Za-z0-9_\-]{20,}", "Anthropic 金鑰"),
    (r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{20,}", "OpenAI 類金鑰"),
    (r"\bgsk_[A-Za-z0-9]{30,}", "Groq 金鑰"),
    (r"\bhf_[A-Za-z0-9]{30,}", "Hugging Face 金鑰"),
    (r"\bgh[pousr]_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{40,}", "GitHub 金鑰"),
    (r"\bglpat-[A-Za-z0-9_\-]{20,}", "GitLab 金鑰"),
    (r"\bAIza[0-9A-Za-z_\-]{35}", "Google 金鑰"),
    (r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b", "AWS 金鑰"),
    (r"\bxox[abposr]-[A-Za-z0-9\-]{10,}", "Slack 金鑰"),
    (r"\b(?:sk|rk)_live_[A-Za-z0-9]{20,}", "Stripe 金鑰"),
    (r"(?i)(aws_secret_access_key\s*[=:]\s*[\"']?)[A-Za-z0-9/+=]{40}", "AWS 密鑰"),
    (r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}", "登入權杖（JWT）"),
]
_SECRET_RE = [(re.compile(p), label) for p, label in SECRET_PATTERNS]
SECRET_MARK = "已遮蔽"


def mask_secrets(text):
    """回傳 (遮蔽後的文字, 遮蔽了幾個)。金鑰換成「‹已遮蔽的 XX 金鑰›」，模型與存檔都看不到本體。"""
    if not text or not isinstance(text, str):
        return text, 0
    count = 0

    def repl_for(label):
        def repl(m):
            nonlocal count
            count += 1
            if label == "AWS 密鑰":
                return m.group(1) + f"‹{SECRET_MARK}的{label}›"
            return f"‹{SECRET_MARK}的{label}›"
        return repl
    for rx, label in _SECRET_RE:
        text = rx.sub(repl_for(label), text)
    for value in sorted(_KNOWN_SECRETS, key=len, reverse=True):      # 程式實際用到的金鑰：不管格式，原文一律遮
        if value in text:
            count += text.count(value)
            text = text.replace(value, f"‹{SECRET_MARK}的金鑰›")
    return text, count


_KNOWN_SECRETS = set()


def register_secret(value):
    """記下程式實際使用的金鑰本體（只在記憶體裡），之後任何輸出含有它都會被遮蔽。"""
    value = (value or "").strip()
    if len(value) >= 12 and not value.isspace():
        _KNOWN_SECRETS.add(value)


def looks_like_env_name(value):
    """判斷欄位內容是「環境變數名稱」還是「金鑰本體」。

    先用格式判斷（全大寫英數底線、含底線、長度合理），格式不符才去查環境變數，
    減少讀取登錄檔次數；這樣貼上的金鑰不會被誤存進設定檔或明碼顯示。
    """
    value = (value or "").strip()
    if not value:
        return False
    if ENV_NAME_PATTERN.fullmatch(value) and "_" in value and len(value) <= 64:
        return True
    if len(value) <= 64 and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        return os.environ.get(value) is not None or read_windows_env(value)[0] is not None
    return False


def resolve_credential(field_value, priority=PRIORITY_SYSTEM):
    """欄位內容 → 金鑰資訊 dict。

    key：實際金鑰（找不到時為空字串）；error：錯誤說明；hint：給畫面顯示的短摘要；note：詳細診斷。
    """
    field_value = (field_value or "").strip()
    out = {"key": "", "error": "", "hint": "", "note": "", "from_env": False, "env_name": ""}
    if field_value == NO_KEY:               # 本機模型（Ollama、LM Studio…）不需要金鑰
        out.update(hint="不需要金鑰（本機模型）", note="這個端點設定為不需要金鑰")
        return out
    if not field_value:
        out["error"] = "請填寫金鑰或環境變數名稱。"
        return out
    env = lookup_env(field_value, priority) if looks_like_env_name(field_value) else {"value": None}
    if env["value"] is not None:
        key = clean_key(env["value"])
        out.update(from_env=True, env_name=field_value)
        source = f"環境變數 {field_value}（{env['source']}）"
    elif looks_like_env_name(field_value):
        out["error"] = f"找不到環境變數「{field_value}」，請先設定或直接貼上 API 金鑰。"
        return out
    else:
        key = clean_key(field_value)
        source = "欄位中直接貼上的金鑰"
    if not key:
        out["error"] = f"環境變數「{field_value}」是空值。"
        return out
    fp = fingerprint(key)
    register_secret(key)
    out["key"] = key
    out["hint"] = f"金鑰：{env.get('source') or '直接貼上'}｜指紋 {fp}"
    note = f"本次使用的金鑰來源：{source}；長度 {len(key)}；指紋 {fp}"
    non_ascii = sum(1 for ch in key if ord(ch) > 127)
    if non_ascii:
        note += f"；含 {non_ascii} 個非 ASCII 字元（金鑰通常不該有，請檢查是否貼錯）"
    if env.get("other") is not None:
        other_fp = fingerprint(clean_key(env["other"]))
        out["hint"] += f"｜另有{env['other_source']} {other_fp}"
        note += (f"；注意：{env['other_source']}是另一把金鑰（指紋 {other_fp}），目前依設定採用{env['source']}，"
                 "可在「設定」分頁調整金鑰來源優先順序")
    out["note"] = note
    return out




# ── 從環境變數找出可用的 AI 金鑰，並猜測對應的 OpenAI 相容網址 ──
PROVIDER_HINTS = (      # (環境變數名稱開頭, API 網址)
    ("NVIDIA", "https://integrate.api.nvidia.com/v1"),
    ("NGC", "https://integrate.api.nvidia.com/v1"),
    ("OPENROUTER", "https://openrouter.ai/api/v1"),
    ("OPENAI", "https://api.openai.com/v1"),
    ("ANTHROPIC", "https://api.anthropic.com/v1"),
    ("CLAUDE", "https://api.anthropic.com/v1"),
    ("GROQ", "https://api.groq.com/openai/v1"),
    ("DEEPSEEK", "https://api.deepseek.com/v1"),
    ("GEMINI", "https://generativelanguage.googleapis.com/v1beta/openai"),
    ("GOOGLE", "https://generativelanguage.googleapis.com/v1beta/openai"),
    ("MISTRAL", "https://api.mistral.ai/v1"),
    ("TOGETHER", "https://api.together.xyz/v1"),
    ("XAI", "https://api.x.ai/v1"),
    ("FIREWORKS", "https://api.fireworks.ai/inference/v1"),
    ("CEREBRAS", "https://api.cerebras.ai/v1"),
    ("DASHSCOPE", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"),
    ("MOONSHOT", "https://api.moonshot.ai/v1"),
    ("SILICONFLOW", "https://api.siliconflow.cn/v1"),
    ("PERPLEXITY", "https://api.perplexity.ai"),
)
KEY_ENV_PATTERN = re.compile(r"(API_?KEY|_KEY|_TOKEN)$")
NOT_AI_ENV = re.compile(r"^(CLAUDE_CODE|CLOUDSDK|GCLOUD|GOOGLE_APPLICATION|GITHUB|GH_|GITLAB|AWS|AZURE_(?!OPENAI)|NPM|PYPI|PIP|DOCKER|SSH|GPG|VSCODE|CHOCOLATEY|HOMEBREW|SENTRY|SLACK|DISCORD|TELEGRAM|STRIPE)")


def guess_provider_url(env_name):
    name = (env_name or "").upper()
    for prefix, url in PROVIDER_HINTS:
        if name.startswith(prefix):
            return url
    return ""


def _windows_env_names():
    names = set()
    if sys.platform != "win32":
        return names
    try:
        import winreg
        for root, path in ((winreg.HKEY_CURRENT_USER, r"Environment"),
                           (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
            try:
                with winreg.OpenKey(root, path) as key:
                    for i in range(winreg.QueryInfoKey(key)[1]):
                        names.add(winreg.EnumValue(key, i)[0])
            except OSError:
                continue
    except ImportError:
        pass
    return names


def list_key_env_names(extra=()):
    """回傳看起來像 AI 金鑰的環境變數名稱（只回傳名稱，不讀出金鑰內容）；已知服務排前面。"""
    names = {n.upper() for n in set(os.environ) | _windows_env_names()} - {NO_KEY}
    found = {n for n in names if KEY_ENV_PATTERN.search(n) and not NOT_AI_ENV.match(n)}
    found |= {n for n in extra if n and looks_like_env_name(n)}
    return sorted(found, key=lambda n: (0 if guess_provider_url(n) else 1, n))
