# ═════════════════════════ 3. API 連線 ═════════════════════════

class ServiceError(Exception):
    """服務端在內容中回報錯誤（HTTP 狀態正常，但內容是 error）。"""


class Cancelled(Exception):
    """使用者按下停止。"""


# ───────────────────────── 網址 ─────────────────────────
def chat_url(value):
    value = (value or "").strip().rstrip("/")
    return value if value.endswith("/chat/completions") else value + "/chat/completions"


def models_url(value):
    value = (value or "").strip().rstrip("/")
    if value.endswith("/chat/completions"):
        value = value[: -len("/chat/completions")]
    return value if value.endswith("/models") else value + "/models"


# ───────────────────────── <think> 過濾 ─────────────────────────
class ThinkFilter:
    """把串流內容中的 <think>…</think> 區塊濾掉（標籤可能被切在兩個片段之間）。"""

    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self, enabled=True):
        self.enabled = enabled
        self.inside = False
        self.pending = ""
        self.skip_ws = False
        self.saw_think = False

    @staticmethod
    def _partial_suffix(data, tag):
        for size in range(min(len(tag) - 1, len(data)), 0, -1):
            if tag.startswith(data[-size:]):
                return size
        return 0

    def _emit(self, text, out):
        if self.skip_ws:
            text = text.lstrip()
            if text:
                self.skip_ws = False
        if text:
            out.append(text)

    def feed(self, chunk):
        if not self.enabled:
            return chunk
        data = self.pending + chunk
        self.pending = ""
        out = []
        while data:
            if not self.inside:
                idx = data.find(self.OPEN)
                if idx >= 0:
                    self._emit(data[:idx], out)
                    data = data[idx + len(self.OPEN):]
                    self.inside = self.saw_think = True
                    continue
                keep = self._partial_suffix(data, self.OPEN)
                self._emit(data[: len(data) - keep], out)
                self.pending = data[len(data) - keep:] if keep else ""
                break
            idx = data.find(self.CLOSE)
            if idx >= 0:
                data = data[idx + len(self.CLOSE):]
                self.inside = False
                self.skip_ws = True
                continue
            keep = self._partial_suffix(data, self.CLOSE)
            self.pending = data[len(data) - keep:] if keep else ""
            break
        return "".join(out)

    def flush(self):
        rest, self.pending = ("" if self.inside else self.pending), ""
        return rest


# ───────────────────────── 錯誤說明 ─────────────────────────
def read_error_body(exc, limit=2000):
    if "已拒絕" in str(getattr(exc, "msg", "")) or "已阻擋" in str(getattr(exc, "msg", "")):
        return str(exc.msg)                  # 程式自己擋下的轉址：直接說明原因
    try:
        return exc.read(limit).decode("utf-8", errors="replace")
    except Exception:
        return ""


def error_text(err):
    if isinstance(err, dict):
        return str(err.get("message") or json.dumps(err, ensure_ascii=False))
    return str(err)


def context_length_error(code, detail):
    """這個錯誤是不是「內容超過上下文長度上限」。"""
    return code in (400, 413, 422) and bool(re.search(
        r"(?i)context length|context window|maximum context|too (long|many tokens)|reduce.{0,20}(length|tokens)|"
        r"exceeds?.{0,20}(context|token|length)|輸入過長|超過.{0,6}長度", detail or ""))


def friendly_http_error(code, url, detail, key_note="", retry_after=None):
    reply = "\n\n服務回覆：" + (detail or "（沒有額外訊息）")
    if key_note and code in (401, 403):
        reply += "\n" + key_note
    is_nvidia = NVIDIA_HOST in (url or "").lower()
    if code == 401:
        if is_nvidia:
            return ("NVIDIA 未接受這把 API 金鑰。請確認內容是 NVIDIA API Catalog 金鑰且仍有效；"
                    "環境變數存在不代表金鑰已通過驗證。" + reply)
        return "服務未接受這把 API 金鑰。請確認金鑰正確、尚未過期，且屬於這個服務。" + reply
    if code == 403:
        if is_nvidia:
            return ("NVIDIA 拒絕此請求的授權。請確認帳戶可使用這個模型／端點，"
                    "可先在 NVIDIA API Catalog 的同一模型頁測試。" + reply)
        return "服務拒絕了這個請求。請確認帳戶有權限使用這個模型／端點。" + reply
    if code == 404:
        if is_nvidia and ("Function" in (detail or "") or "Not found for account" in (detail or "")):
            return ("NVIDIA 找不到這個模型可用的部署：模型可能已下架、改名，或你的帳號沒有使用權限。"
                    "注意「抓取模型」清單裡的模型不一定都能呼叫，請按端點卡片的「測試」確認，或改選其他模型。" + reply)
        return "找不到這個網址或模型。請確認 API 基底網址（通常以 /v1 結尾）與模型名稱正確，並用「測試」確認。" + reply
    if context_length_error(code, detail):
        return ("這次送出的內容超過模型的上下文長度上限。討論時可在「設定 → AI 討論」調低「引用總字數上限」；"
                "Agent 很長的對話可以開新對話，或讓它先整理摘要。" + reply)
    if code == 422 or (code == 400 and "model" in (detail or "").lower()):
        return "服務不接受這個請求，常見原因是模型名稱錯誤或此模型不支援聊天（Chat Completions）。" + reply
    if code == 429:
        wait = f"建議約 {retry_after} 秒後再試。" if retry_after else "請稍候再試，或降低同時呼叫的數量。"
        return "請求過於頻繁或超過額度（HTTP 429）。" + wait + reply
    if code in (500, 502, 503, 504):
        return f"服務端暫時發生問題（HTTP {code}），通常稍後重試即可。" + reply
    return (detail or f"HTTP {code}")


def parse_retry_after(value):
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return None


# ───────────────────────── 抓取模型 ─────────────────────────
def auth_headers(key):
    """有金鑰才送 Authorization；本機模型不送，避免有些伺服器拒絕空白的 Bearer。"""
    return {"Authorization": f"Bearer {key}"} if key else {}


class _SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    """帶金鑰的請求只允許轉址到同一個網站（同協定、主機、埠）。
    v6.6 紅隊：urllib 預設轉址到別的網站時會把 Authorization（金鑰）一起帶過去。"""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        a, b = urllib.parse.urlsplit(req.full_url), urllib.parse.urlsplit(newurl)
        if (a.scheme, a.hostname, a.port) != (b.scheme, b.hostname, b.port):
            raise urllib.error.HTTPError(req.full_url, code, f"服務要求轉址到其他網站（{b.hostname}），為了保護金鑰已拒絕",
                                         headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_API_OPENER = urllib.request.build_opener(_SameOriginRedirect)


def api_open(req, timeout):
    """送出帶金鑰的 API 請求（不跟隨跨網站轉址）。"""
    return _API_OPENER.open(req, timeout=timeout)


def _is_local_or_private_url(url):
    import ipaddress
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if host in ("localhost",) or host.endswith((".local", ".lan", ".localhost", ".internal", ".home.arpa")):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except ValueError:
        return "." not in host               # 區網主機名稱（例如 http://gpu-server:8000）


ALLOW_INSECURE_HTTP = [False]      # 設定 → Agent → 進階功能：允許雲端 API 用 http://（使用者手動開啟）


def validate_api_url(url):
    """檢查 API 網址；回傳錯誤說明（空字串＝沒問題）。"""
    url = (url or "").strip()
    if not url:
        return "請填 API 網址"
    if cli_kind(url):                       # cli://claude、cli://codex：用已登入的命令列工具（訂閱額度）
        return ""
    if re.match(r"^https?://[^/\s]+", url, re.I):
        if url.lower().startswith("http://") and not _is_local_or_private_url(url) and not ALLOW_INSECURE_HTTP[0]:
            return (f"「{url}」用 http://（沒有加密），金鑰和對話會以明文經過網路。"
                    "雲端服務請改用 https://；只有本機或區網的服務可以用 http://。"
                    "（確定要用的話，可在「設定 → Agent → 進階功能」手動開啟。）")
        return ""
    if re.match(r"^[A-Za-z]:[\\/]|^\\\\|^/|^~", url):
        return (f"「{url}」是資料夾路徑，不是 API 網址。模型資料夾（例如 OLLAMA_MODELS）要交給 Ollama 讀取；"
                "這裡請按上方「本機模型」，網址用 http://localhost:11434/v1。")
    return f"API 網址要用 http:// 或 https:// 開頭（例如 http://localhost:11434/v1），目前是「{url}」。"


LOCAL_SERVERS = (       # (名稱, 預設 OpenAI 相容網址)
    ("Ollama", "http://localhost:11434/v1"),
    ("LM Studio", "http://localhost:1234/v1"),
    ("llama.cpp／llamafile／LocalAI", "http://localhost:8080/v1"),
    ("vLLM／SGLang", "http://localhost:8000/v1"),
    ("Jan", "http://localhost:1337/v1"),
    ("text-generation-webui", "http://localhost:5000/v1"),
)


def is_local_url(url):
    m = re.match(r"^https?://\[?([^/:\]]+)", (url or "").strip(), re.I)
    host = (m.group(1) if m else "").lower()
    return (host in ("localhost", "127.0.0.1", "0.0.0.0", "::1", "host.docker.internal") or host.startswith("127.")
            or host.startswith("192.168.") or host.startswith("10.") or bool(re.match(r"172\.(1[6-9]|2\d|3[01])\.", host))
            or host.endswith(".local"))


def ollama_url():
    """依 OLLAMA_HOST 決定 Ollama 網址（預設 http://localhost:11434/v1）。"""
    host = (os.environ.get("OLLAMA_HOST") or read_windows_env("OLLAMA_HOST")[0] or "").strip()
    if not host:
        return "http://localhost:11434/v1"
    if not re.match(r"^https?://", host, re.I):
        host = "http://" + host
    host = re.sub(r"//0\.0\.0\.0", "//127.0.0.1", host.rstrip("/"))
    if not re.search(r":\d+$", host.split("//", 1)[1]):
        host += ":11434"
    return host + "/v1"


def ollama_models_dir():
    value = (os.environ.get("OLLAMA_MODELS") or read_windows_env("OLLAMA_MODELS")[0] or "").strip().strip('"')
    return value or os.path.join(os.path.expanduser("~"), ".ollama", "models")


def ollama_installed_models(models_dir=None):
    """不用啟動 Ollama，直接從模型資料夾的 manifests 讀出已下載的模型名稱（例如 llama3.2:3b）。"""
    root = os.path.join(models_dir or ollama_models_dir(), "manifests")
    names = set()
    if not os.path.isdir(root):
        return []
    for dirpath, _dirs, files in os.walk(root):
        for tag in files:
            parts = os.path.relpath(os.path.join(dirpath, tag), root).replace("\\", "/").split("/")
            if len(parts) < 4:
                continue
            host, ns, model = parts[0], "/".join(parts[1:-2]), parts[-2]
            if host == "registry.ollama.ai":
                names.add((model if ns == "library" else f"{ns}/{model}") + ":" + tag)
            else:
                names.add(f"{host}/{ns}/{model}:{tag}")
    return sorted(names)


def probe_local_servers(timeout=1.5):
    """同時探測常見的本機模型服務；回傳 [(名稱, 網址, 模型清單, 錯誤)]。"""
    servers = [(n, ollama_url() if n == "Ollama" else u) for n, u in LOCAL_SERVERS]
    results = [None] * len(servers)

    def one(i, name, url):
        models, err = fetch_models(url, "", timeout=timeout)
        results[i] = (name, url, models, err)

    threads = [threading.Thread(target=one, args=(i, n, u), daemon=True) for i, (n, u) in enumerate(servers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout + 1)
    return [r for r in results if r]


def fetch_models(url, key, timeout=MODELS_TIMEOUT):
    """回傳 (模型清單, 錯誤訊息)。Ollama 沒在執行時，改從模型資料夾列出已安裝的模型（附提醒）。"""
    bad = validate_api_url(url)
    if bad:
        return [], bad
    if cli_kind(url):
        return list(CLI_KINDS[cli_kind(url)]["models"]), ""
    try:
        req = urllib.request.Request(models_url(url), method="GET",
                                     headers={**auth_headers(key), "Accept": "application/json"})
        with api_open(req, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        rows = data.get("data", []) if isinstance(data, dict) else data
        models = []
        if isinstance(rows, list):
            models = sorted({str(item.get("id", "")).strip() for item in rows if isinstance(item, dict) and item.get("id")})
        return models, ("" if models else "服務回傳的清單沒有可用模型")
    except urllib.error.HTTPError as exc:
        detail = read_error_body(exc, 1200)
        return [], f"HTTP {exc.code}" + (f"：{detail}" if detail else "")
    except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, OSError) as exc:
        if is_local_url(url):
            if ":11434" in url:
                installed = ollama_installed_models()
                if installed:
                    return installed, ("Ollama 沒有在執行（連不到 " + url + "）。以下是模型資料夾裡已下載的模型；"
                                       "要使用前請先啟動 Ollama（開啟 Ollama 程式或執行 ollama serve）。")
                return [], f"連不到 Ollama（{url}）。請先啟動 Ollama；模型資料夾 {ollama_models_dir()} 裡也沒有找到已下載的模型。"
            return [], f"連不到本機服務 {url}：請確認程式已啟動並開啟「本機伺服器／API」功能。（{exc}）"
        return [], f"連線或資料解析失敗：{exc}"


def health_check(services, key_priority=None, timeout=15, include_local=False, probe=False, probe_timeout=40):
    """檢查雲端服務的金鑰與模型還能不能用。只讀各服務的「模型清單」（GET /models），不送出任何對話內容、不產生用量。
    回傳 [(服務, 種類「金鑰」或「模型」, 說明, 建議替代模型)]；連不上或服務不提供清單時不判斷（避免誤報）。"""
    groups = {}
    for sv in services:
        if not sv.get("enabled", True) or not sv.get("model") or not sv.get("url"):
            continue
        if cli_kind(sv.get("url")):          # 訂閱 CLI 沒有金鑰與模型清單可查
            continue
        if is_local_url(sv.get("url")) and not include_local:      # 本機模型不需要金鑰，預設不檢查
            continue
        cred = sv.get("credential") or sv.get("credential_env") or ""
        groups.setdefault((sv["url"].strip().rstrip("/"), cred), []).append(sv)
    problems = []
    for (url, cred), svs in groups.items():
        info = resolve_credential(cred, key_priority) if key_priority else resolve_credential(cred)
        if info.get("error"):
            problems += [(sv, "金鑰", info["error"], "") for sv in svs]
            continue
        models, err = fetch_models(url, info.get("key", ""), timeout=timeout)
        if err.startswith(("HTTP 401", "HTTP 403")):
            problems += [(sv, "金鑰", f"金鑰無效、過期或沒有權限（{err.split('：')[0]}）", "") for sv in svs]
            continue
        if not models:
            continue
        ids = set(models)
        for sv in svs:
            if sv["model"] not in ids:
                alt = [m for m in recommend_models(sv.get("role") or DEFAULT_ROLE, models, 3) if m != sv["model"]]
                problems.append((sv, "模型", "服務的模型清單裡找不到這個模型（可能已下架或改名）", alt[0] if alt else ""))
            elif probe:
                # 清單上「有」不代表帳號能呼叫（NVIDIA 常見「Function not found for account」）：
                # 送 1 個 token 的最小測試（不含任何對話內容）。只把「確定的失敗」當問題；逾時、429、5xx 等
                # 可能只是暫時或冷啟動太慢，不報，避免誤報。
                ep = {"url": url, "model": sv["model"], "key": info.get("key", ""), "key_note": info.get("hint", ""),
                      "max_tokens": "1"}
                r = stream_chat(ep, [{"role": "user", "content": "hi"}], threading.Event(),
                                options={"auto_retry": 0, "include_usage": False, "filter_think": True,
                                         "timeout": probe_timeout}, register=None)
                label = r.get("label") or ""
                if label in ("HTTP 404", "HTTP 400", "HTTP 422") and r.get("status") == "error":
                    alt = [m for m in recommend_models(sv.get("role") or DEFAULT_ROLE, models, 3) if m != sv["model"]]
                    problems.append((sv, "模型", "這個模型列在清單上，但你的帳號實際無法呼叫（例如 NVIDIA 的"
                                     "「Function not found for account」）", alt[0] if alt else ""))
                elif label in ("HTTP 401", "HTTP 403"):
                    problems.append((sv, "金鑰", "金鑰無法呼叫這個模型（可能沒有權限或已失效）", ""))
    return problems


# ───────────────────────── 串流聊天 ─────────────────────────
_no_stream_options = set()          # 不接受 stream_options 的網址（第一次被拒後記住）
_no_stream_options_lock = threading.Lock()


def _wait(seconds, cancel_event):
    """可被「停止」中斷的等待。"""
    if cancel_event.wait(seconds):
        raise Cancelled()


def _number(value, cast):
    value = str(value or "").strip()
    if not value:
        return None
    try:
        return cast(value)
    except ValueError:
        return None


# 思考強度（OpenAI 相容的 reasoning_effort；Ollama 也支援）。本機的思考模型（例如 qwen3.5）預設會先「想」上千字，
# 實測回一句招呼要 2 分鐘；設成 none 只要 3 秒。空白＝不送這個參數，用模型預設。
REASONING_LEVELS = ("none", "low", "medium", "high")
REASONING_LABELS = {"": "模型預設", "none": "關閉思考（最快）", "low": "少量思考", "medium": "中等思考", "high": "深入思考（最慢）"}


def reasoning_style(model, url=""):
    """各模型「思考」參數的實際行為（2026-10-26 在 NVIDIA 的服務上實測）：
    levels：reasoning_effort 的 none／low／medium／high 照送
    no_off：不能完全關閉，送 none 會 HTTP 400（gpt-oss）→ 關閉改送 low
    low_is_off：送 low 才會關閉、送 none 沒用（NVIDIA 上的 GLM）→ 只能開或關
    onoff：low／high 沒有作用、none 才有效（NVIDIA 上的 DeepSeek）→ 只能開或關"""
    m, u = (model or "").lower(), (url or "").lower()
    if "gpt-oss" in m:
        return "no_off"
    if "nvidia.com" in u and "glm" in m:
        return "low_is_off"
    if "nvidia.com" in u and "deepseek" in m:
        return "onoff"
    return "levels"


REASONING_STYLE_HINTS = {
    "no_off": "這個模型不能完全關閉思考：選「關閉思考」會改成最少思考。",
    "low_is_off": "這個模型在 NVIDIA 只能開或關思考：少量／中等／深入都等於模型預設。",
    "onoff": "這個模型在 NVIDIA 只能開或關思考：少量／中等／深入都等於模型預設。",
}


_no_reasoning = set()          # 送 reasoning_effort 會 HTTP 400 的「網址｜模型」（第一次被拒後記住，之後不送）
_no_reasoning_lock = threading.Lock()


def _reasoning_key(endpoint):
    return f"{chat_url(endpoint.get('url', ''))}|{endpoint.get('model', '')}"


def reasoning_rejected(detail):
    """錯誤內容是不是在抱怨 reasoning_effort／思考參數（用來判斷要不要拿掉它重試）。"""
    return bool(re.search(r"(?i)reasoning|thinking|chat_template", detail or ""))


def reasoning_params(endpoint):
    """依模型把「思考」設定轉成實際要送的參數。換了服務或新模型不吃這個參數時，第一次被拒後就不再送。"""
    level = endpoint.get("reasoning")
    if level not in REASONING_LEVELS:
        return {}
    with _no_reasoning_lock:
        if _reasoning_key(endpoint) in _no_reasoning:
            return {}
    style = reasoning_style(endpoint.get("model"), endpoint.get("url"))
    if style == "no_off":
        return {"reasoning_effort": "low" if level == "none" else level}
    if style == "low_is_off":
        return {"reasoning_effort": "low"} if level == "none" else {}
    if style == "onoff":
        return {"reasoning_effort": "none"} if level == "none" else {}
    return {"reasoning_effort": level}


def build_payload(endpoint, messages, include_usage):
    payload = {"model": endpoint["model"], "messages": messages, "stream": True}
    temperature = _number(endpoint.get("temperature"), float)
    if temperature is not None:
        payload["temperature"] = temperature
    max_tokens = _number(endpoint.get("max_tokens"), int)
    if max_tokens:
        payload["max_tokens"] = max_tokens
    payload.update(reasoning_params(endpoint))
    if include_usage:
        payload["stream_options"] = {"include_usage": True}
    return payload


class ThinkTooLong(Exception):
    """思考超過時間上限還沒開始回答。"""


def _join_continuation(prev, nxt):
    """接續時去掉重複：如果新段落開頭和前文結尾有一大段重疊（模型從頭重寫），就只接沒重複的部分。"""
    if not prev or not nxt:
        return prev + nxt
    window = prev[-800:]
    for n in range(min(len(window), len(nxt)), 40, -1):      # 從長到短找最長的重疊；太短（<40）不算，避免誤刪
        if nxt[:n] == window[-n:]:
            return prev + nxt[n:]
    return prev + nxt


CONTINUE_PROMPT = ("你的回答因為長度上限被截斷了。請從中斷的地方「直接接著寫」，不要重複已經寫過的內容，"
                   "也不要加任何開場白或說明；如果中斷在程式碼區塊裡，就直接接著寫程式碼。")


def _add_usage(total, usage):
    if not isinstance(usage, dict):
        return total
    total = dict(total or {})
    for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
        if usage.get(k) is not None:
            total[k] = int(total.get(k) or 0) + int(usage.get(k) or 0)
    return total


def stream_chat(endpoint, messages, cancel_event, on_event=None, register=None, options=None):
    """對單一端點發出串流請求。

    endpoint：dict，需有 url、model、key，可有 temperature、max_tokens、reasoning、key_note。
    on_event(kind, payload)：kind 為 thinking（payload＝目前思考字數或 None）／generating／delta／retry_wait／
    think_cut（思考太久，改成不思考重來）／continue（被長度上限截斷，自動接續第 n 次）。
    register(response or None)：登記進行中的連線，讓「停止」可以立即關閉。
    回傳 dict：status（done/stopped/error/timeout）、text、error、ttft、elapsed、usage、label，
    另有 finish（結束原因）、truncated（仍被截斷）、think_cut、continued。
    """
    if cli_kind(endpoint.get("url")):     # Claude Code／Codex：走命令列（訂閱額度）
        return cli_chat(endpoint, messages, cancel_event, on_event, register, options)
    options = options or {}
    on_event = on_event or (lambda *_a: None)
    register = register or (lambda _r: None)
    native = ollama_native_base(endpoint["url"])
    url = native + "/api/chat" if native else chat_url(endpoint["url"])
    started = time.monotonic()
    result = {"status": "error", "text": "", "error": "", "ttft": None, "elapsed": 0.0, "usage": None, "label": "",
              "finish": ""}
    include_usage = options.get("include_usage", True)
    retries_left = options.get("auto_retry", 2)
    think_limit = options.get("think_limit", THINK_LIMIT_DEFAULT) or 0
    user_max = _number(endpoint.get("max_tokens"), int)
    usage_retry_done = think_cut_done = False
    carried, continues, usage_sum, msgs = "", 0, None, messages

    while True:
        with _no_stream_options_lock:
            use_usage = include_usage and url not in _no_stream_options
        think = ThinkFilter(options.get("filter_think", True))
        pieces = []
        result["finish"] = ""
        result["usage"] = None
        limit = think_limit if (not think_cut_done and endpoint.get("reasoning") not in ("none", "high")) else 0
        try:
            if cancel_event.is_set():
                raise Cancelled()
            payload = build_payload(endpoint, msgs, use_usage)
            if native:
                payload = ollama_native_payload(endpoint, payload)
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=body, method="POST", headers={
                **auth_headers(endpoint["key"]), "Content-Type": "application/json",
                "Accept": "text/event-stream",
            })
            wait = options.get("timeout", REQUEST_TIMEOUT)
            response = api_open(req, timeout=max(wait, LOCAL_LOAD_TIMEOUT) if native else wait)
            register(response)
            try:
                _consume(OllamaStream(response) if native else response, cancel_event, on_event, think, pieces, result,
                         started, limit)
            finally:
                register(None)
                try:
                    response.close()
                except Exception:
                    pass
            if cancel_event.is_set():
                raise Cancelled()
            tail = think.flush()
            if tail:
                pieces.append(tail)
                on_event("delta", tail)
            text = "".join(pieces)
            usage_sum = _add_usage(usage_sum, result.get("usage"))
            if result.get("finish") == "length" and not user_max and continues < 2 and text.strip():
                # 服務預設的長度上限很小（例如 diffusiongemma 只給 1000 token）：把已寫的內容送回去，請它接著寫
                continues += 1
                carried = _join_continuation(carried, text) if carried else text
                msgs = list(msgs) + [{"role": "assistant", "content": text}, {"role": "user", "content": CONTINUE_PROMPT}]
                endpoint = dict(endpoint, max_tokens=LONG_MAX_TOKENS)
                result["continued"] = continues
                on_event("continue", continues)
                continue
            result["text"] = _join_continuation(carried, text) if carried else text
            if result.get("finish") == "length":
                result["truncated"] = True
            if not result["text"].strip():
                result["text"] = ""
                result["error"] = ("模型只輸出了思考內容，沒有最終回答。" if think.saw_think
                                   else "服務已結束，但沒有回傳任何文字內容。")
                result["status"] = "empty"
            else:
                result["status"] = "done"
            break
        except ThinkTooLong:
            # 思考太久還沒開始回答（實測 glm、deepseek 可以想 10 分鐘以上）：改成「不思考」重新回答一次
            think_cut_done = True
            result["think_cut"] = True
            endpoint = dict(endpoint, reasoning="none")
            on_event("think_cut", limit)
            continue
        except Cancelled:
            result.update(status="stopped", text=carried + "".join(pieces))
            break
        except urllib.error.HTTPError as exc:
            detail = read_error_body(exc)
            if cancel_event.is_set():
                result.update(status="stopped")
                break
            if exc.code in (400, 422) and reasoning_params(endpoint) and reasoning_rejected(detail):
                # 服務不接受思考參數（換了別家或新模型）：拿掉它重試一次，記住這個模型以後不送
                with _no_reasoning_lock:
                    _no_reasoning.add(_reasoning_key(endpoint))
                continue
            if exc.code in (400, 422) and use_usage and not usage_retry_done:
                # 有些服務不接受 stream_options：先拿掉它重試一次，成功就記住這個網址
                with _no_stream_options_lock:
                    _no_stream_options.add(url)
                usage_retry_done = True
                continue
            retry_after = parse_retry_after(exc.headers.get("Retry-After") if exc.headers else None)
            if exc.code in AUTO_RETRY_CODES and retries_left > 0:
                retries_left -= 1
                wait = min(retry_after if retry_after is not None else (3 if exc.code == 500 else 5), AUTO_RETRY_MAX_WAIT)
                on_event("retry_wait", (wait, f"HTTP {exc.code}"))
                try:
                    _wait(wait, cancel_event)
                except Cancelled:
                    result.update(status="stopped")
                    break
                continue
            result.update(status="error", label=f"HTTP {exc.code}",
                          error=(native and ollama_load_error(detail)) or
                          friendly_http_error(exc.code, url, detail, endpoint.get("key_note", ""), retry_after))
            break
        except ServiceError as exc:
            result.update(status="stopped" if cancel_event.is_set() else "error", label="服務回報錯誤",
                          error=str(exc), text=carried + "".join(pieces))
            break
        except Exception as exc:  # 連線中斷、逾時、被「停止」關閉的連線等
            if cancel_event.is_set():
                result.update(status="stopped", text=carried + "".join(pieces))
                break
            timeout = isinstance(exc, (TimeoutError, socket.timeout)) or isinstance(
                getattr(exc, "reason", None), (TimeoutError, socket.timeout))
            result.update(status="timeout" if timeout else "error", label="逾時" if timeout else "連線失敗",
                          error=f"{type(exc).__name__}：{exc}", text=carried + "".join(pieces))
            break
    if usage_sum:
        result["usage"] = usage_sum
    if result.get("error"):
        result["error"] = mask_secrets(result["error"])[0]       # 有些服務的錯誤訊息會帶出部分金鑰
    result["elapsed"] = time.monotonic() - started
    return result


def _consume(response, cancel_event, on_event, think, pieces, result, started, think_limit=0):
    reasoning_seen = content_seen = sse_seen = False
    plain_lines, plain_size = [], 0
    attempt_start = last_progress = time.monotonic()
    think_chars = 0

    def thinking_more(n):
        nonlocal think_chars, last_progress
        think_chars += n
        now = time.monotonic()
        if now - last_progress >= 2:                 # 每 2 秒回報一次思考字數，讓畫面知道它還活著
            last_progress = now
            on_event("thinking", think_chars)
        if think_limit and now - attempt_start > think_limit:
            raise ThinkTooLong()
    for raw in response:
        if cancel_event.is_set():
            return
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        if not line.startswith("data:"):
            if plain_size < MAX_PLAIN_CHARS:
                plain_lines.append(line)
                plain_size += len(line)
            continue
        sse_seen = True
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            continue
        if not isinstance(chunk, dict):
            continue
        if chunk.get("error"):
            raise ServiceError(error_text(chunk["error"]))
        if isinstance(chunk.get("usage"), dict):
            result["usage"] = chunk["usage"]
        choices = chunk.get("choices") or []
        if not choices:
            continue
        if (choices[0] or {}).get("finish_reason"):
            result["finish"] = choices[0]["finish_reason"]
        delta = (choices[0] or {}).get("delta") or {}
        content = delta.get("content")
        reasoning = delta.get("reasoning_content") or delta.get("reasoning")
        if reasoning and not reasoning_seen and not content_seen:
            reasoning_seen = True
            on_event("thinking", None)
        if isinstance(reasoning, str) and reasoning and not content_seen:
            thinking_more(len(reasoning))
        if isinstance(content, str) and content:
            if result["ttft"] is None:
                result["ttft"] = time.monotonic() - started
            visible = think.feed(content)
            if think.inside and not reasoning_seen and not content_seen:
                reasoning_seen = True
                on_event("thinking", None)
            if think.inside and not content_seen:
                thinking_more(len(content))
            if visible:
                if not content_seen:
                    content_seen = True
                    on_event("generating", None)
                pieces.append(visible)
                on_event("delta", visible)

    if cancel_event.is_set() or sse_seen or not plain_lines:
        return
    # 服務沒有用串流格式：把內容當成完整 JSON 解析
    text = "\n".join(plain_lines)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise ServiceError("服務回傳的格式無法辨識：" + text[:500])
    if isinstance(data, dict) and data.get("error"):
        raise ServiceError(error_text(data["error"]))
    try:
        message = (data.get("choices") or [{}])[0].get("message") or {}
        content = message.get("content")
    except (AttributeError, IndexError, TypeError):
        content = None
    if not isinstance(content, str) or not content:
        raise ServiceError("服務回傳的 JSON 中找不到回答內容：" + text[:500])
    if isinstance(data.get("usage"), dict):
        result["usage"] = data["usage"]
    try:
        result["finish"] = data["choices"][0].get("finish_reason") or ""
    except (KeyError, IndexError, TypeError, AttributeError):
        pass
    result["ttft"] = time.monotonic() - started
    visible = think.feed(content) + think.flush()
    if visible:
        on_event("generating", None)
        pieces.append(visible)
        on_event("delta", visible)


# ───────────────────────── 本機大模型：Ollama 原生 API（顯卡＋記憶體連動） ─────────────────────────
# v6.7.0 實測（Ollama 0.40、8 GB 顯示卡、32 GB 記憶體）：經 OpenAI 相容端點（/v1）呼叫時，Ollama 把上下文開到模型上限
# （262,144），連 4B 小模型都膨脹到 13.3 GB、8 GB 被擠到記憶體；/v1 也不吃 num_ctx。改走原生 /api/chat 並指定上下文後只要 3.4 GB。
# 顯卡放不下的部分由 Ollama 自動放到系統記憶體（MoE 模型會把專家權重放記憶體、注意力層留在顯卡）。
OLLAMA_DEFAULT_CTX = 16384
OLLAMA_CTX_CHOICES = (("自動（16K）", ""), ("8K", "8192"), ("16K", "16384"), ("32K", "32768"), ("64K", "65536"))
OLLAMA_KEEP_CHOICES = (("30 分鐘（預設）", ""), ("5 分鐘", "5m"), ("2 小時", "2h"), ("一直保持", "-1"))
OLLAMA_KEEP_ALIVE = "30m"           # 大模型載入很久：用完先留在記憶體，下一題不用重新載入
LOCAL_LOAD_TIMEOUT = 1200           # 第一次載入大模型時，Ollama 讀完權重前不會送任何資料
_GIB = 1024 ** 3


def ollama_native_base(url):
    """網址是 Ollama（埠 11434，或 OLLAMA_HOST 指定的位置）就回傳原生 API 根網址（http://主機:埠），否則 None。"""
    m = re.match(r"^(https?://[^/]+)(/.*)?$", (url or "").strip().rstrip("/"), re.I)
    if not m:
        return None
    root, path = m.group(1), (m.group(2) or "")
    if path.endswith("/chat/completions"):
        path = path[: -len("/chat/completions")]
    if path not in ("", "/v1"):
        return None
    try:
        port = urllib.parse.urlparse(root).port
    except ValueError:
        return None
    configured = ollama_url()[: -len("/v1")].lower()
    return root if port == 11434 or root.lower() == configured else None


def _ollama_tag(model):
    model = (model or "").strip()
    return model if ":" in model.split("/")[-1] else model + ":latest"


def ollama_native_payload(endpoint, payload):
    """把 OpenAI 格式的請求（訊息、圖片、工具往返、溫度、上限、思考）轉成 Ollama /api/chat。"""
    names, msgs = {}, []
    for m in payload.get("messages") or []:
        role = m.get("role")
        item = {"role": role}
        content = m.get("content")
        if isinstance(content, list):
            texts, images = [], []
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    texts.append(str(part.get("text") or ""))
                elif part.get("type") == "image_url":
                    u = str((part.get("image_url") or {}).get("url") or "")
                    if u.startswith("data:") and "," in u:
                        images.append(u.split(",", 1)[1])
            item["content"] = "\n".join(texts)
            if images:
                item["images"] = images
        else:
            item["content"] = content if isinstance(content, str) else ""
        if role == "assistant" and m.get("tool_calls"):
            calls = []
            for tc in m["tool_calls"]:
                fn = tc.get("function") or {}
                args = fn.get("arguments")
                if isinstance(args, str):
                    try:
                        args = json.loads(args) if args.strip() else {}
                    except json.JSONDecodeError:
                        args = {}
                names[tc.get("id")] = fn.get("name", "")
                calls.append({"function": {"name": fn.get("name", ""), "arguments": args if isinstance(args, dict) else {}}})
            item["tool_calls"] = calls
        if role == "tool":
            name = names.get(m.get("tool_call_id")) or m.get("name")
            if name:
                item["tool_name"] = name
        msgs.append(item)
    options = {"num_ctx": _number(endpoint.get("num_ctx"), int) or OLLAMA_DEFAULT_CTX}
    if payload.get("temperature") is not None:
        options["temperature"] = payload["temperature"]
    if payload.get("max_tokens"):
        options["num_predict"] = payload["max_tokens"]
    body = {"model": payload.get("model"), "messages": msgs, "stream": True, "options": options,
            "keep_alive": str(endpoint.get("keep_alive") or OLLAMA_KEEP_ALIVE)}
    if body["keep_alive"].lstrip("-").isdigit():
        body["keep_alive"] = int(body["keep_alive"])
    if payload.get("tools"):
        body["tools"] = payload["tools"]
    effort = payload.get("reasoning_effort")
    if effort is not None:
        body["think"] = effort != "none"
    return body


class OllamaStream:
    """把 Ollama /api/chat 的 NDJSON 串流轉成 OpenAI 的 SSE 行（bytes），既有的解析程式不用改。"""

    def __init__(self, response):
        self.response = response
        self.calls = 0

    @staticmethod
    def _sse(obj):
        return ("data: " + json.dumps(obj, ensure_ascii=False)).encode("utf-8")

    def __iter__(self):
        saw_tools = False
        for raw in self.response:
            line = raw.decode("utf-8", errors="replace").strip() if isinstance(raw, bytes) else str(raw).strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            if obj.get("error"):
                yield self._sse({"error": obj["error"]})
                return
            msg = obj.get("message") or {}
            delta = {}
            if msg.get("thinking"):
                delta["reasoning_content"] = msg["thinking"]
            if msg.get("content"):
                delta["content"] = msg["content"]
            calls = []
            for tc in msg.get("tool_calls") or []:
                fn = tc.get("function") or {}
                args = fn.get("arguments", {})
                calls.append({"index": self.calls, "id": f"call_{uuid.uuid4().hex[:8]}", "type": "function",
                              "function": {"name": fn.get("name", ""),
                                           "arguments": args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)}})
                self.calls += 1
            if calls:
                delta["tool_calls"] = calls
                saw_tools = True
            chunk = {"choices": [{"index": 0, "delta": delta, "finish_reason": None}]}
            if obj.get("done"):
                reason = obj.get("done_reason") or "stop"
                chunk["choices"][0]["finish_reason"] = "tool_calls" if saw_tools and reason == "stop" else reason
                p, c = int(obj.get("prompt_eval_count") or 0), int(obj.get("eval_count") or 0)
                chunk["usage"] = {"prompt_tokens": p, "completion_tokens": c, "total_tokens": p + c}
                yield self._sse(chunk)
                yield b"data: [DONE]"
                return
            if delta:
                yield self._sse(chunk)


def ollama_load_error(detail):
    """Ollama 載入失敗的白話說明；不是載入問題回傳空字串。"""
    text = (detail or "").lower()
    if "timed out waiting for llama-server" in text or "timed out waiting for llama runner" in text:
        return ("Ollama 在 5 分鐘內沒有把模型載入完成就放棄了。大模型的權重要從磁碟全部讀進顯卡與記憶體；"
                "模型放在慢的磁碟（例如接在 USB 2.0 的外接硬碟，約 40 MB/s，17 GB 要 7 分鐘以上）時一定會逾時。"
                "請把外接硬碟改插 USB 3 的孔（通常是藍色或標 SS 的孔），或把模型移到內建 SSD；"
                "也可以設定環境變數 OLLAMA_LOAD_TIMEOUT=20m 後重新啟動 Ollama。")
    if "out of memory" in text or "unable to allocate" in text or "requires more system memory" in text:
        return ("顯卡加系統記憶體放不下這個模型（含上下文）。請關閉其他佔記憶體的程式，或在設定把這個模型的「本機上下文」調小。")
    return ""


def free_memory_bytes():
    """目前可用的系統記憶體；偵測不到回傳 None。"""
    try:
        if sys.platform == "win32":
            import ctypes

            class _MemStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            status = _MemStatus()
            status.dwLength = ctypes.sizeof(_MemStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullAvailPhys)
            return None
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, AttributeError):
        return None
    return None


# ───────────────────────── 電腦狀況監控（v6.8.0） ─────────────────────────
def memory_status():
    """(總記憶體, 可用記憶體) bytes；偵測不到回傳 (None, None)。"""
    try:
        if sys.platform == "win32":
            import ctypes

            class _MemStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            status = _MemStatus()
            status.dwLength = ctypes.sizeof(_MemStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullTotalPhys), int(status.ullAvailPhys)
            return None, None
        info = {}
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                key, _sep, rest = line.partition(":")
                info[key] = int(rest.split()[0]) * 1024
        return info.get("MemTotal"), info.get("MemAvailable")
    except (OSError, ValueError, AttributeError, IndexError):
        return None, None


def cpu_times():
    """(閒置, 總計) 的累計時間；用兩次的差算使用率。偵測不到回傳 None。"""
    try:
        if sys.platform == "win32":
            import ctypes

            idle, kernel, user = ctypes.c_ulonglong(), ctypes.c_ulonglong(), ctypes.c_ulonglong()
            if ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
                return idle.value, kernel.value + user.value          # kernel 時間已經包含 idle
            return None
        with open("/proc/stat", encoding="ascii") as f:
            parts = [int(x) for x in f.readline().split()[1:]]
        return parts[3] + (parts[4] if len(parts) > 4 else 0), sum(parts)
    except (OSError, ValueError, AttributeError, IndexError):
        return None


def cpu_percent(previous, current):
    if not previous or not current:
        return None
    d_idle, d_total = current[0] - previous[0], current[1] - previous[1]
    if d_total <= 0:
        return None
    return max(0.0, min(100.0, 100.0 * (1 - d_idle / d_total)))


def gpu_status():
    """第一張 NVIDIA 顯卡：使用率、顯存、溫度（nvidia-smi，不載入 CUDA）；沒有回傳 None。"""
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5, creationflags=flags)
        lines = (out.stdout or "").strip().splitlines()
        if out.returncode != 0 or not lines:
            return None
        return parse_gpu_line(lines[0])
    except (OSError, subprocess.SubprocessError):
        return None


def parse_gpu_line(line):
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 5:
        return None

    def num(value):
        try:
            return float(value)
        except ValueError:          # 某些顯卡回報 [N/A]
            return None
    used, total = num(parts[2]), num(parts[3])
    return {"name": parts[0], "util": num(parts[1]),
            "mem_used": int(used * 1024 * 1024) if used is not None else None,
            "mem_total": int(total * 1024 * 1024) if total is not None else None, "temp": num(parts[4])}


def ollama_running_models(timeout=1):
    """Ollama 目前載入的模型：[{name, size, vram}]；Ollama 沒開回傳 None。"""
    # Windows 的 localhost 會先試 IPv6（::1），Ollama 只聽 IPv4，每次多卡約 1 秒；監控直接用 127.0.0.1
    base = re.sub(r"(?i)://localhost(?=[:/]|$)", "://127.0.0.1", ollama_url()[: -len("/v1")])
    try:
        models = _ollama_get(base, "/api/ps", timeout=timeout).get("models") or []
    except Exception:
        return None
    return [{"name": m.get("name") or m.get("model") or "", "size": int(m.get("size") or 0),
             "vram": int(m.get("size_vram") or 0)} for m in models]


def system_snapshot(previous_cpu=None, include_gpu=True):
    """一次收集：CPU、記憶體、顯卡、Ollama 載入的模型。回傳 (snapshot, 這次的 cpu_times 給下一次算使用率)。"""
    now = cpu_times()
    total, avail = memory_status()
    snap = {"cpu": cpu_percent(previous_cpu, now), "ram_total": total, "ram_avail": avail,
            "gpu": gpu_status() if include_gpu else None, "ollama": ollama_running_models()}
    return snap, now


def describe_models_in_use(services, loaded):
    """「目前使用的模型」各在哪裡跑：雲端不佔本機資源；本機 Ollama 顯示實際用了多少顯卡與記憶體。

    services：這段對話用到的服務設定；loaded：ollama_running_models() 的結果（None＝Ollama 沒開）。
    回傳 (使用中的說明行, 其他已載入但這段對話沒用到的模型行)。"""
    G = _GIB
    by_tag = {_ollama_tag(m.get("name")): m for m in (loaded or [])}
    used, lines = set(), []
    for s in services:
        if not s or not s.get("model"):
            continue
        name = short_model(s.get("model")) or s.get("name") or s.get("model")
        url = s.get("url", "")
        if cli_kind(url):
            where = f"雲端（{cli_label(url)} 訂閱，用 {CLI_KINDS[cli_kind(url)]['plan']} 的額度），不佔這台電腦的顯卡和記憶體"
            lines.append(f"・{name}：{where}")
            continue
        if ollama_native_base(url):
            tag = _ollama_tag(s.get("model"))
            used.add(tag)
            m = by_tag.get(tag)
            if m:
                where = f"本機，顯卡 {m['vram'] / G:.1f}＋記憶體 {max(0, m['size'] - m['vram']) / G:.1f} GB"
            elif loaded is None:
                where = "本機，Ollama 沒有執行"
            else:
                where = "本機，目前沒有載入（下次使用時才載入）"
        elif is_local_url(url):
            where = "本機（不是 Ollama，查不到用量）"
        else:
            host = (urllib.parse.urlparse(url).hostname or "").lower()
            label = "NVIDIA" if host.endswith("nvidia.com") else host or "雲端服務"
            where = f"雲端（{label}），在遠端伺服器跑，不佔這台電腦的顯卡和記憶體"
        lines.append(f"・{name}：{where}")
    others = [f"・{m['name']}：顯卡 {m['vram'] / G:.1f}＋記憶體 {max(0, m['size'] - m['vram']) / G:.1f} GB"
              for tag, m in by_tag.items() if tag not in used]
    return lines, others


def monitor_warnings(snap):
    """電腦狀況需要注意的地方（白話）；都正常回傳空清單。"""
    warns = []
    total, avail = snap.get("ram_total"), snap.get("ram_avail")
    if avail is not None and avail < 1.5 * _GIB:
        warns.append(f"記憶體快用完了（只剩 {avail / _GIB:.1f} GB），電腦會變慢；請關閉不用的程式或卸載本機模型。")
    gpu = snap.get("gpu") or {}
    if gpu.get("mem_used") and gpu.get("mem_total") and gpu["mem_used"] / gpu["mem_total"] > 0.97:
        warns.append("顯存幾乎全滿：再載入別的模型會被擠到系統記憶體、速度變慢。")
    if gpu.get("temp") is not None and gpu["temp"] >= 85:
        warns.append(f"顯卡溫度偏高（{gpu['temp']:.0f}°C），請確認機殼通風。")
    if snap.get("cpu") is not None and snap["cpu"] >= 95:
        warns.append("CPU 幾乎滿載：本機模型放在記憶體的部分由 CPU 計算，回答會變慢。")
    return warns


def free_vram_bytes():
    """第一張 NVIDIA 顯卡的可用顯存（用 nvidia-smi 查，不載入 CUDA）；沒有或查不到回傳 None。"""
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5, creationflags=flags)
        first = (out.stdout or "").strip().splitlines()
        return int(float(first[0])) * 1024 * 1024 if out.returncode == 0 and first else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _ollama_get(base, path, timeout=5):
    with api_open(urllib.request.Request(base + path), timeout=timeout) as resp:
        return json.loads(resp.read())


def ollama_loaded(endpoint):
    """這個模型目前在 Ollama 的載入狀態：{"size","vram","ctx"}；沒載入或不是 Ollama 回傳 None。"""
    base = ollama_native_base(endpoint.get("url"))
    if not base:
        return None
    try:
        models = _ollama_get(base, "/api/ps").get("models") or []
    except Exception:
        return None
    want = _ollama_tag(endpoint.get("model"))
    for m in models:
        if _ollama_tag(m.get("name") or m.get("model")) == want:
            return {"size": int(m.get("size") or 0), "vram": int(m.get("size_vram") or 0),
                    "ctx": int(m.get("context_length") or 0)}
    return None


def describe_local_split(status):
    """把載入狀態寫成一句話：顯卡多少、記憶體多少、上下文多長。"""
    size, vram = status.get("size", 0), status.get("vram", 0)
    cpu = max(0, size - vram)
    ctx = f"，上下文 {status['ctx']:,}" if status.get("ctx") else ""
    if cpu < 0.1 * _GIB:
        return f"全部在顯卡（{vram / _GIB:.1f} GB）{ctx}"
    return (f"顯卡 {vram / _GIB:.1f} GB＋系統記憶體 {cpu / _GIB:.1f} GB（顯卡佔 {100 * vram / max(1, size):.0f}%）{ctx}；"
            "放在記憶體的部分由 CPU 計算，回答會比較慢")


# 上下文（KV cache）與執行緩衝粗估：每個 token 約 0.1 MB。v6.7.1 依實測校正：qwen3-coder（模型檔 17.3 GB）＋上下文 16K
# 實際佔 19.0 GB（多 1.7 GB）；v6.7.0 用 0.16 MB 再乘 1.05、記憶體保留 2 GB，在剛好放得下時誤報「可能放不下」。
KV_BYTES_PER_TOKEN = 100 * 1024


def local_fit_warning(endpoint, model_size=None, vram=None, ram=None):
    """本機大模型送出前的檢查：顯卡＋記憶體可能放不下時回傳說明，放得下（或已載入、不是 Ollama）回傳空字串。"""
    base = ollama_native_base(endpoint.get("url"))
    if not base:
        return ""
    if model_size is None:
        if ollama_loaded(endpoint):
            return ""
        try:
            tags = _ollama_get(base, "/api/tags").get("models") or []
        except Exception:
            return ""
        want = _ollama_tag(endpoint.get("model"))
        model_size = next((int(m.get("size") or 0) for m in tags if _ollama_tag(m.get("name")) == want), 0)
    if not model_size:
        return ""
    vram = free_vram_bytes() if vram is None else vram
    ram = free_memory_bytes() if ram is None else ram
    if ram is None:
        return ""
    ctx = _number(endpoint.get("num_ctx"), int) or OLLAMA_DEFAULT_CTX
    need = int(model_size) + ctx * KV_BYTES_PER_TOKEN
    usable = (vram or 0) + max(0, ram - int(1.5 * _GIB))
    if need <= usable:
        return ""
    return (f"「{endpoint.get('model')}」約需 {need / _GIB:.1f} GB（模型 {model_size / _GIB:.1f} GB＋上下文 {ctx:,}），"
            f"目前可用顯存約 {(vram or 0) / _GIB:.1f} GB、記憶體約 {ram / _GIB:.1f} GB，可能放不下：載入會非常慢、"
            "拖慢整台電腦或失敗。建議先關閉其他佔記憶體的程式（瀏覽器、其他 AI 程式），或把這個模型的「本機上下文」調小。")


def test_model(url, key, model, timeout=TEST_TIMEOUT):
    """快速確認「這個模型現在能不能呼叫」：送出極短的串流請求，收到第一筆資料就關閉。

    回傳 (是否可用, 說明, 秒數)。不需要等模型講完，也不受推理型模型思考時間影響太多。
    """
    if cli_kind(url):
        return cli_test(cli_kind(url), model=model, timeout=max(timeout, 120))
    started = time.monotonic()
    native = ollama_native_base(url)
    if native:
        # 本機大模型：用原生 API 指定上下文（/v1 會開到模型上限而塞爆記憶體），第一次載入可能要好幾分鐘
        body = json.dumps({"model": model, "messages": [{"role": "user", "content": "請只回覆：OK"}], "stream": True,
                           "options": {"num_ctx": OLLAMA_DEFAULT_CTX, "num_predict": 16},
                           "keep_alive": OLLAMA_KEEP_ALIVE}).encode("utf-8")
        timeout = max(timeout, LOCAL_LOAD_TIMEOUT)
    else:
        body = json.dumps({"model": model, "messages": [{"role": "user", "content": "請只回覆：OK"}],
                           "stream": True, "max_tokens": 16}).encode("utf-8")
    req = urllib.request.Request(native + "/api/chat" if native else chat_url(url), data=body, method="POST", headers={
        **auth_headers(key), "Content-Type": "application/json", "Accept": "text/event-stream"})
    try:
        with api_open(req, timeout=timeout) as response:
            for raw in response:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                if line.startswith("data:"):
                    data = line[5:].strip()
                    if data != "[DONE]":
                        try:
                            chunk = json.loads(data)
                            if isinstance(chunk, dict) and chunk.get("error"):
                                return False, "服務回報錯誤：" + error_text(chunk["error"])[:200], time.monotonic() - started
                        except json.JSONDecodeError:
                            pass
                    break
                if line.startswith("{"):
                    try:
                        data = json.loads(line)
                        if isinstance(data, dict) and data.get("error"):
                            return False, "服務回報錯誤：" + error_text(data["error"])[:200], time.monotonic() - started
                    except json.JSONDecodeError:
                        pass
                    break
        return True, "可以正常呼叫", time.monotonic() - started
    except urllib.error.HTTPError as exc:
        detail = read_error_body(exc, 1200)
        message = ollama_load_error(detail) if native else ""
        message = message or friendly_http_error(exc.code, url, detail).split("\n")[0]
        return False, f"HTTP {exc.code}：" + message, time.monotonic() - started
    except Exception as exc:
        timeout_hit = isinstance(exc, (TimeoutError, socket.timeout)) or isinstance(
            getattr(exc, "reason", None), (TimeoutError, socket.timeout))
        return False, ("逾時：模型沒有在時間內回應" if timeout_hit else f"連線失敗：{exc}"), time.monotonic() - started


# ── 模型種類：依名稱判斷（服務的 /models 清單不會告訴你種類，只能從命名慣例推測） ──
MODEL_KINDS = ("對話", "視覺", "語音", "圖像", "嵌入", "其他")
MODEL_KIND_HELP = {
    "對話": "一般文字對話，可當 Agent／討論成員",
    "視覺": "能看圖片的對話模型（也能文字對話）",
    "語音": "語音辨識（ASR）、語音合成（TTS）等，不能用在這裡的對話",
    "圖像": "產生圖片或影片的模型，不能用在這裡的對話",
    "嵌入": "嵌入向量、重排序、檢索用，不能對話",
    "其他": "安全審查、獎勵模型、OCR 等專用模型，不能一般對話",
}
_KIND_RULES = (
    ("語音", re.compile(r"whisper|\btts\b|-tts|tts-|\basr\b|-asr|parakeet|canary|riva|fastpitch|hifigan|magpie|"
                       r"audio2face|speech|voice|fugatto|maxine|studiovoice|sortformer|-audio|audio-", re.I)),
    ("圖像", re.compile(r"stable-diffusion|sdxl|\bsd3|sd-3|flux|dall-?e|imagen|gpt-image|edify|bria|consistory|"
                       r"kandinsky|playground-v|cosmos(?!-reason)|trellis|image-gen|txt2img|text-to-image|video-gen|veo|sana", re.I)),
    ("嵌入", re.compile(r"embed|rerank|retriever|nemoretriever|\bbge|e5-|arctic-embed|nv-?ingest|nvclip|"
                       r"(^|/)clip|colbert|gte-|minilm", re.I)),
    ("其他", re.compile(r"guard|safety|reward|shieldgemma|nemoguard|paddleocr|\bocr|-ocr|deplot|topic-control|"
                       r"jailbreak|pii|grounding-dino|nemotron-parse|-parse\b|nv-yolox|yolox|page-elements|table-structure|graphic-elements|ocdr|florence|sam-?2|depth|detector|ocdrnet|changenet|visual-changenet|nv-dinov|segformer", re.I)),
)
VISION_HINT = re.compile(r"vision|\bvlm|-vl\b|-vl-|vl-|llava|vila|neva|kosmos|fuyu|pixtral|multimodal|"
                         r"phi-4-multimodal|omni|llama-4|gemma-3-(4|12|27)b|gemma-3n|qwen2\.5-vl|qwen3-vl|"
                         r"internvl|molmo|paligemma|nemotron-nano-vl|cosmos-reason|mistral-small-3\.[12]|"
                         r"mistral-medium-3|gpt-4o|qwen2\.5vl|qwen3-?vl|minicpm-v|moondream|bakllava|granite3\.2-vision|llama4|gemma3:(4|12|27)b|mistral-small3\.[12]|gpt-4\.1|gpt-5|gemini|claude|grok-4|grok-2-vision", re.I)


def model_size_b(model_id):
    """從模型名稱抓出參數量（單位：十億），例如 gpt-oss-20b → 20、nemotron-3-ultra-550b-a55b → 550；抓不到回傳 None。
    「a55b」這種是每次啟用的參數量，不算。"""
    name = (model_id or "").lower().split("/")[-1]
    found = [float(x) for x in re.findall(r"(?<![a-z0-9.])(\d+(?:\.\d+)?)b(?![a-z0-9])", name)]
    return max(found) if found else None


def model_tags(model_id):
    """回傳模型種類標籤，例如 ["對話"]、["對話", "視覺"]、["語音"]。"""
    mid = model_id or ""
    for kind, pattern in _KIND_RULES:
        if pattern.search(mid):
            return [kind]
    return ["對話", "視覺"] if VISION_HINT.search(mid) else ["對話"]


def model_kind_label(model_id):
    tags = model_tags(model_id)
    return "視覺" if "視覺" in tags else tags[0]


# ── 依身分推薦模型：只從服務實際提供的清單裡挑，依名稱特徵打分（可用、但不一定是唯一好選擇） ──
_REASONING = r"r1\b|-r1|reason|qwq|think|gpt-oss|deepseek-v[34]|nemotron-(3-)?ultra|nemotron-(3\.5-)?super|kimi-k2|o[134]-|qwen3-235b|magistral"
ROLE_MODEL_HINTS = {
    "程式專家": ((r"coder|codestral|devstral|starcoder|codegemma|codellama|code\b", 6),
              (r"qwen3-coder|kimi-k2|deepseek-v[34]|glm-[45]|gpt-oss|nemotron-(3-)?ultra|nemotron-(3\.5-)?super", 4),
              (r"llama-?4|qwen3|mistral-large", 1)),
    "研究分析": ((_REASONING, 6), (r"llama-?4|mistral-large|glm-[45]|qwen3", 2)),
    "審查批判": ((_REASONING, 6), (r"llama-?4|mistral-large|glm-[45]|qwen3", 2)),
    "資料處理": ((r"coder|deepseek-v[34]|gpt-oss|qwen3|qwen2\.5", 5), (r"nemotron|llama-?4|glm-[45]", 2)),
    "文件撰寫": ((r"llama-?(3\.3|4)|mistral-(large|medium)|gemma-?3|qwen3|glm-[45]|kimi", 5), (r"nemotron|deepseek-v", 2)),
    "對話溝通": ((r"llama|gemma|mistral|qwen|kimi|glm|chat", 4), (r"nemotron|deepseek-v", 1)),
    "一般助理": ((r"llama-?4|deepseek-v[34]|qwen3|nemotron-(3-)?ultra|nemotron-(3\.5-)?super|mistral-large|kimi-k2|glm-[45]|gpt-oss", 5),
              (r"llama|gemma|mistral|qwen", 2)),
}
ROLE_MODEL_NOTE = {
    "程式專家": "寫程式、除錯：優先 coder 類與擅長推理的大模型",
    "研究分析": "查證、推理：優先推理型（R1、gpt-oss、ultra、kimi-k2 等）大模型",
    "審查批判": "挑錯、找漏洞：優先推理型大模型",
    "資料處理": "資料結構、計算：優先 coder 類與推理型模型",
    "文件撰寫": "文字品質：優先 Llama、Mistral、Gemma、Qwen 等語言表達好的模型",
    "對話溝通": "說明與語氣：一般對話模型即可，速度快的較好",
    "一般助理": "綜合能力：優先各家旗艦大模型",
}


# ── 每個身分的預設模型（實測挑出）──
# 2026-10-30 在 NVIDIA 的服務上實測 24 個模型：每個身分一題可自動評分的題目（程式跑測試、計算有標準答案、
# 審查有埋好的錯、公告字數與要點、三句話解釋、JSON 格式），另測工具呼叫給 Agent。分數相同時取較快的。
# 每個身分依序是首選、備用；只用在 NVIDIA 服務，且只挑服務清單裡真的有的（模型被下架就自動換下一個）。
# 值是 (模型, 思考設定)，思考設定同 REASONING_LABELS 的鍵。
_SVL, _ULTRA, _NANO = ("nvidia/nemotron-3.5-super-vl-120b-a12b", "nvidia/nemotron-3-ultra-550b-a55b",
                       "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning")
_GLM, _LIGHT = "z-ai/glm-5.3-flash", "nvidia/nemotron-3.5-lightning-30b-a3b"
ROLE_DEFAULT_MODELS = {
    # 兩輪 14 題全對、用語最乾淨、速度快（程式 7～22 秒）
    "程式專家": ((_SVL, ""), (_ULTRA, ""), (_NANO, "")),
    # 「1～1000 有幾個含 7」：super-vl、glm、nano 都對；ultra 算成 272（錯）。首選用不同家族的 glm，討論時觀點更多元
    "研究分析": ((_GLM, ""), (_SVL, ""), (_NANO, "")),
    # 兩個埋好的錯（lo=mid 無窮迴圈、可變預設參數）全部找到，用語最接近台灣
    "審查批判": ((_ULTRA, ""), (_SVL, ""), (_GLM, "")),
    # 去重複、空值當 0 的彙總兩輪全對，4 秒內完成（輸出是 JSON，用語影響小）
    "資料處理": ((_NANO, ""), (_SVL, ""), (_GLM, "")),
    # 大陸用語改寫成台灣用語＋三條列＋字數：最高分（0.92），沒有殘留「優化、信息」等
    "文件撰寫": ((_SVL, ""), (_ULTRA, ""), (_LIGHT, "")),
    # 三句話內、比喻清楚、不夾英文，11～27 秒
    "對話溝通": ((_ULTRA, ""), (_SVL, ""), (_NANO, "")),
    # 格式要求（只輸出 JSON）兩輪全對、2 秒內回答
    "一般助理": ((_ULTRA, ""), (_SVL, ""), (_LIGHT, "")),
    # 主持：要整合多人意見，用最大的 ultra；Agent：工具呼叫最快（0.5～1 秒），且曾實測 33 步修好整個專案
    "主持": ((_ULTRA, ""), (_SVL, "")),
    "Agent": ((_SVL, ""), (_ULTRA, ""), (_LIGHT, "")),
}
ROLE_DEFAULT_SOURCE = "2026-10-30 實測"


def role_default_model(role, models=None, url=""):
    """這個身分的預設模型 → (模型, 思考設定)；沒有適用的回傳 None。
    models：服務提供的模型清單；None 表示還沒抓到清單（不檢查）。url：不是 NVIDIA 服務時不套用。"""
    if url and NVIDIA_HOST not in url:
        return None
    for model, reasoning in ROLE_DEFAULT_MODELS.get(role) or ():
        if models is None or model in models:
            return model, reasoning
    return None


def tested_rank(role, model):
    """模型在這個身分的實測排名：0＝首選、1＝備用…；沒有列入回傳 None。"""
    for i, (m, _r) in enumerate(ROLE_DEFAULT_MODELS.get(role) or ()):
        if m == model:
            return i
    return None


def _model_size_b(model_id):
    m = re.search(r"(\d+(?:\.\d+)?)b\b", (model_id or "").lower())
    return float(m.group(1)) if m else None


def recommend_models(role, models, limit=6):
    """依身分從可用模型中挑出推薦清單（由高到低）。"""
    hints = ROLE_MODEL_HINTS.get(role) or ROLE_MODEL_HINTS[DEFAULT_ROLE]
    scored = []
    for m in models:
        if not likely_chat_model(m):
            continue
        low = m.lower()
        score = 0
        for pattern, pts in hints:
            if re.search(pattern, low):
                score = max(score, pts)
        if not score:
            continue
        size = _model_size_b(low)
        if size is not None:
            score += 2 if size >= 100 else 1 if size >= 30 else -3 if size <= 4 else 0
        if re.search(r"mini|nano|tiny|small|lite|-1b|-2b|:1b|:2b", low):
            score -= 2
        if re.search(r"base\b|-base", low):
            score -= 3
        if score > 0:
            scored.append((score, m))
    scored.sort(key=lambda x: (-x[0], x[1]))
    tested = list(dict.fromkeys(m for m, _r in ROLE_DEFAULT_MODELS.get(role) or () if m in models))   # 實測過的排最前面
    return (tested + [m for _s, m in scored if m not in tested])[:limit]


def likely_chat_model(model_id):
    """能不能用在對話／Agent（語音、圖像、嵌入、安全等專用模型不行）。"""
    return "對話" in model_tags(model_id)


# ── 圖片與語音附件 ──
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
               ".webp": "image/webp", ".bmp": "image/bmp"}
AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".webm", ".mp4", ".mpeg", ".mpga", ".aac")
IMAGE_MAX_BYTES = 8_000_000
IMAGE_MAX_COUNT = 6


def load_image(path):
    """讀取圖片成 data URL（給視覺模型）。回傳 {"name", "data", "bytes"}。"""
    ext = os.path.splitext(path)[1].lower()
    mime = IMAGE_TYPES.get(ext)
    if not mime:
        raise ValueError("不支援的圖片格式（支援 png、jpg、gif、webp、bmp）")
    size = os.path.getsize(path)
    if size > IMAGE_MAX_BYTES:
        raise ValueError(f"圖片太大（{size / 1e6:.1f} MB，上限 {IMAGE_MAX_BYTES / 1e6:.0f} MB），請先縮小")
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode("ascii")
    return {"name": os.path.basename(path), "data": f"data:{mime};base64,{data}", "bytes": size}


def supports_vision(model_id):
    return "視覺" in model_tags(model_id)


def user_content(text, images, model_id):
    """有附圖時：視覺模型收到「文字＋圖片」；其他模型收到文字和一句說明。"""
    if not images:
        return text
    if supports_vision(model_id):
        return [{"type": "text", "text": text}] + [{"type": "image_url", "image_url": {"url": im["data"]}} for im in images]
    names = "、".join(im["name"] for im in images)
    return (text + f"\n\n（使用者附了 {len(images)} 張圖片：{names}。你目前使用的模型看不到圖片，請只依文字回答；"
                   "如果問題需要看圖，請說明需要換成能看圖的視覺模型。）")


def content_text(content):
    """訊息內容（字串或 OpenAI 的內容陣列）→ 純文字（計算長度、顯示用）。"""
    if isinstance(content, list):
        return "\n".join(p.get("text", "") if p.get("type") == "text" else "[圖片]" for p in content if isinstance(p, dict))
    return str(content or "")


def strip_images(content):
    """把內容陣列裡的圖片換成文字標記（存檔與之後的回合不再重送圖片）。"""
    if not isinstance(content, list):
        return content
    texts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
    n = sum(1 for p in content if isinstance(p, dict) and p.get("type") == "image_url")
    return "\n".join(texts) + (f"\n（這一輪附了 {n} 張圖片，已在當時提供給模型）" if n else "")


def audio_url(value):
    base = (value or "").strip().rstrip("/")
    if base.endswith("/chat/completions"):
        base = base[: -len("/chat/completions")]
    return base + "/audio/transcriptions"


def transcribe_audio(url, key, model, path, language="zh", timeout=600):
    """把語音檔送到 OpenAI 相容的 /audio/transcriptions（OpenAI、Groq 等的 whisper），回傳文字。"""
    bad = validate_api_url(url)
    if bad:
        raise ServiceError(bad)
    size = os.path.getsize(path)
    if size > 25_000_000:
        raise ServiceError(f"語音檔太大（{size / 1e6:.1f} MB），大部分服務上限是 25 MB，請先切成小段")
    boundary = "----AIWorkbench" + uuid.uuid4().hex
    with open(path, "rb") as f:
        audio = f.read()
    parts = []
    for name, value in (("model", model), ("language", language), ("response_format", "json")):
        if value:
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8"))
    fname = os.path.basename(path).encode("utf-8", "replace").decode("ascii", "replace")
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{fname}"\r\n'
                  f"Content-Type: application/octet-stream\r\n\r\n").encode("utf-8") + audio + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(parts)
    req = urllib.request.Request(audio_url(url), data=body, method="POST", headers={
        **auth_headers(key), "Content-Type": f"multipart/form-data; boundary={boundary}", "Accept": "application/json"})
    try:
        with api_open(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = read_error_body(exc, 600)
        hint = "（這個服務可能沒有語音轉文字功能；NVIDIA 的語音模型不走這個介面，請改用 OpenAI 或 Groq 的 whisper）" \
            if exc.code in (404, 405) else ""
        raise ServiceError(f"HTTP {exc.code}：{detail}{hint}")
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
        raise ServiceError(f"連線失敗：{exc}")
    try:
        data = json.loads(raw)
        return str(data.get("text") or "").strip()
    except ValueError:
        return raw.strip()
