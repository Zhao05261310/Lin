

# ═════════════════════════ 3c. MCP（Model Context Protocol）用戶端 ═════════════════════════
# 讓 Agent 使用外部工具：瀏覽器（Playwright）、桌面操作、Gmail／Google Drive、資料庫……任何 MCP 伺服器。
# 只用標準函式庫：以子程序啟動伺服器（stdio），一行一個 JSON-RPC 2.0 訊息。
# 設定檔「MCP伺服器.json」與 Claude Desktop 的格式相同：{"mcpServers": {"名稱": {"command", "args", "env", "enabled"}}}
# env 的值可以寫 "${環境變數名稱}"，程式啟動伺服器時才去讀，金鑰不必寫進檔案。

MCP_CONFIG_PATH = os.path.join(APP_DIR, "MCP伺服器.json")
MCP_PROTOCOL_VERSION = "2025-06-18"
MCP_EXAMPLE = {
    "mcpServers": {
        "playwright": {"command": "npx", "args": ["-y", "@playwright/mcp@latest"], "enabled": False,
                       "說明": "操作瀏覽器（開網頁、點擊、填表、截圖）。需要 Node.js。"},
        "filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:\\Users\\你的名字\\Documents"],
                       "enabled": False, "說明": "讓 Agent 讀寫工作資料夾以外、你指定的一個資料夾。需要 Node.js。"},
        "windows-desktop": {"command": "uvx", "args": ["windows-mcp"], "enabled": False,
                            "說明": "操作 Windows 桌面程式（點擊、輸入、讀畫面）。需要 Python 的 uv。"},
        "github": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"],
                   "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_TOKEN}"}, "enabled": False,
                   "說明": "GitHub 儲存庫、Issue、PR。金鑰的環境變數在下方選擇。"},
    }
}


# 設定頁表單：範例伺服器需要填的欄位（其他伺服器只有「啟用」勾選）
MCP_FORM_FIELDS = {
    "filesystem": {"kind": "folder", "label": "允許存取的資料夾"},
    "github": {"kind": "key_env", "label": "GitHub 金鑰的環境變數", "target": "GITHUB_PERSONAL_ACCESS_TOKEN"},
}


def mcp_form_rows(config):
    """設定頁要列出的伺服器：範例（還沒加入設定檔的也列，預設不啟用）＋設定檔裡的其他伺服器。
    回傳 [{"name","spec","enabled","folder","key_env","needs"}]。"""
    servers = dict(config.get("mcpServers") or {})
    rows = []
    for name in list(MCP_EXAMPLE["mcpServers"]) + [n for n in servers if n not in MCP_EXAMPLE["mcpServers"]]:
        spec = servers.get(name)
        enabled = bool(isinstance(spec, dict) and spec.get("enabled", True))
        spec = json.loads(json.dumps(spec if isinstance(spec, dict) else MCP_EXAMPLE["mcpServers"][name]))
        field = MCP_FORM_FIELDS.get(name, {})
        folder = key_env = ""
        if field.get("kind") == "folder":
            args = [str(a) for a in spec.get("args") or []]
            folder = args[-1] if args and not args[-1].startswith(("-", "@")) and "你的名字" not in args[-1] else ""
        elif field.get("kind") == "key_env":
            m = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", str((spec.get("env") or {}).get(field["target"], "")))
            key_env = m.group(1) if m else ""
        command = str(spec.get("command") or "")
        rows.append({"name": name, "spec": spec, "enabled": enabled, "folder": folder, "key_env": key_env,
                     "needs": "" if not command or shutil.which(command) else
                     ("需要先安裝 Node.js" if command in ("npx", "node") else
                      "需要先安裝 uv（pip install uv）" if command in ("uvx", "uv") else f"找不到 {command}")})
    return rows


def mcp_apply_form(config, rows):
    """把設定頁表單的選擇寫回設定（回傳新的設定 dict；不會改動傳入的物件）。
    回傳 (設定, 問題清單)：啟用了但缺少必要欄位的會列在問題清單，並維持不啟用。"""
    data = json.loads(json.dumps(config or {"mcpServers": {}}))
    servers = data.setdefault("mcpServers", {})
    problems = []
    for row in rows:
        name = row["name"]
        spec = json.loads(json.dumps(servers.get(name) or row.get("spec") or MCP_EXAMPLE["mcpServers"].get(name) or {}))
        if not spec:
            continue
        field = MCP_FORM_FIELDS.get(name, {})
        enabled = bool(row.get("enabled"))
        if field.get("kind") == "folder":
            folder = (row.get("folder") or "").strip()
            base = [a for a in (spec.get("args") or []) if str(a).startswith(("-", "@"))]
            spec["args"] = base + ([folder] if folder else [])
            if enabled and not (folder and os.path.isdir(folder)):
                problems.append(f"{name}：請選擇存在的資料夾")
                enabled = False
        elif field.get("kind") == "key_env":
            env_name = (row.get("key_env") or "").strip()
            spec.setdefault("env", {})
            if env_name:
                spec["env"][field["target"]] = "${" + env_name + "}"
            if enabled and not env_name:
                problems.append(f"{name}：請選擇存放金鑰的環境變數")
                enabled = False
        if not enabled and name not in servers and name in MCP_EXAMPLE["mcpServers"]:
            continue                          # 沒用到的範例不寫進設定檔
        spec["enabled"] = enabled
        servers[name] = spec
    return data, problems


def load_mcp_config():
    try:
        with open(MCP_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {"mcpServers": {}}
    except (OSError, ValueError) as exc:
        raise ValueError(f"MCP伺服器.json 格式錯誤：{exc}")
    if not isinstance(data, dict) or not isinstance(data.get("mcpServers", {}), dict):
        raise ValueError("MCP伺服器.json 需要有 mcpServers 物件")
    data.setdefault("mcpServers", {})
    return data


def save_mcp_config(text):
    """存設定前先檢查 JSON；舊檔備份到 備份/設定/。"""
    data = json.loads(text)
    if not isinstance(data, dict) or not isinstance(data.get("mcpServers"), dict):
        raise ValueError("需要有 mcpServers 物件")
    if os.path.exists(MCP_CONFIG_PATH):
        os.makedirs(SETTINGS_BACKUP_DIR, exist_ok=True)
        shutil.copy2(MCP_CONFIG_PATH, os.path.join(SETTINGS_BACKUP_DIR, time.strftime("MCP伺服器_%Y%m%d_%H%M%S.json")))
    with open(MCP_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


MCP_LINE_LIMIT = 32_000_000           # MCP 伺服器一行最多 32 MB（截圖等大型結果也放得下）


def _expand_env(value):
    def sub(m):
        name = m.group(1)
        return os.environ.get(name) or read_windows_env(name)[0] or ""
    return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", sub, str(value))


def mcp_tool_name(server, tool):
    """組成 OpenAI 允許的工具名稱（英數、底線、連字號，最長 64）。"""
    clean = lambda s: re.sub(r"[^A-Za-z0-9_-]", "_", s)
    name = f"mcp_{clean(server)}_{clean(tool)}"
    return name if len(name) <= 64 else name[:55] + "_" + hashlib.sha1(name.encode()).hexdigest()[:8]


class MCPServer:
    """一個 MCP 伺服器（stdio）。執行緒安全：可以同時送多個請求，用 id 對應回應。"""

    def __init__(self, name, spec):
        self.name = name
        self.spec = spec
        self.proc = None
        self.pending = {}
        self.lock = threading.Lock()
        self.next_id = 0
        self.tools = []
        self.error = ""
        self.stderr_tail = []
        self.server_info = {}

    @property
    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, timeout=60):
        command = str(self.spec.get("command") or "").strip()
        if not command:
            raise ServiceError("沒有填 command")
        exe = shutil.which(command) or command
        args = [_expand_env(a) for a in (self.spec.get("args") or [])]
        env = scrubbed_env()                # 不把你的 AI 金鑰交給外部工具；需要的金鑰請在 env 裡用 ${名稱} 指定
        env.setdefault("PYTHONIOENCODING", "utf-8")      # Python 寫的 MCP 伺服器在 Windows 預設用 cp950 讀 stdin，會讓中文變亂碼
        env.setdefault("PYTHONUTF8", "1")
        for k, v in (self.spec.get("env") or {}).items():
            env[str(k)] = _expand_env(v)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self.proc = subprocess.Popen([exe] + args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, env=env, cwd=self.spec.get("cwd") or None,
                                         creationflags=flags, bufsize=0,
                                         **({} if os.name == "nt" else {"start_new_session": True}))
        except FileNotFoundError:
            raise ServiceError(f"找不到指令「{command}」。"
                               + ("請先安裝 Node.js（npx）。" if command in ("npx", "node") else
                                  "請先安裝 uv（pip install uv）。" if command in ("uvx", "uv") else "請確認已安裝並在 PATH 中。"))
        threading.Thread(target=self._read_loop, daemon=True).start()
        threading.Thread(target=self._stderr_loop, daemon=True).start()
        info = self.request("initialize", {"protocolVersion": MCP_PROTOCOL_VERSION, "capabilities": {},
                                           "clientInfo": {"name": "AI協作工作台", "version": APP_VERSION}}, timeout)
        self.server_info = info.get("serverInfo") or {}
        self.notify("notifications/initialized")
        tools, cursor = [], None
        for _ in range(20):
            res = self.request("tools/list", {"cursor": cursor} if cursor else {}, timeout)
            tools += [t for t in res.get("tools") or [] if isinstance(t, dict) and t.get("name")]
            cursor = res.get("nextCursor")
            if not cursor:
                break
        self.tools = tools
        return tools

    def _send(self, message):
        if not self.alive:
            raise ServiceError(f"MCP 伺服器「{self.name}」沒有在執行" + (f"：{self.stderr_tail[-1]}" if self.stderr_tail else ""))
        data = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
        with self.lock:
            self.proc.stdin.write(data)
            self.proc.stdin.flush()

    def notify(self, method, params=None):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self._send(msg)

    def request(self, method, params=None, timeout=120, cancel=None):
        with self.lock:
            self.next_id += 1
            rid = self.next_id
            slot = {"event": threading.Event(), "result": None, "error": None}
            self.pending[rid] = slot
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        end = time.monotonic() + timeout
        while not slot["event"].wait(0.2):
            if cancel is not None and cancel.is_set():
                self.pending.pop(rid, None)
                try:
                    self.notify("notifications/cancelled", {"requestId": rid, "reason": "使用者停止"})
                except ServiceError:
                    pass
                raise ToolError("使用者已停止")
            if time.monotonic() > end:
                self.pending.pop(rid, None)
                raise ServiceError(f"MCP 伺服器「{self.name}」{timeout} 秒內沒有回應（{method}）")
            if not self.alive:
                self.pending.pop(rid, None)
                raise ServiceError(f"MCP 伺服器「{self.name}」已結束" + (f"：{self.stderr_tail[-1]}" if self.stderr_tail else ""))
        if slot["error"]:
            err = slot["error"]
            raise ServiceError(f"{err.get('message', err)}" if isinstance(err, dict) else str(err))
        return slot["result"] or {}

    def _read_loop(self):
        import io
        stream = self.proc.stdout
        if not hasattr(stream, "peek"):           # bufsize=0 是未緩衝的串流：逐位元組讀太慢，包一層緩衝
            stream = io.BufferedReader(stream, 1 << 16)
        while True:
            raw = stream.readline(MCP_LINE_LIMIT)
            if not raw:
                break
            if len(raw) >= MCP_LINE_LIMIT and not raw.endswith(b"\n"):
                # v6.11：一行超過上限（沒有換行的巨量資料會把記憶體塞爆）：整行丟掉
                while raw and not raw.endswith(b"\n"):
                    raw = stream.readline(MCP_LINE_LIMIT)
                self.stderr_tail = (self.stderr_tail + [f"（伺服器送來超過 {MCP_LINE_LIMIT // 1_000_000} MB 的一行，已丟棄）"])[-20:]
                continue
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if not isinstance(msg, dict):
                continue
            if "id" in msg and ("result" in msg or "error" in msg):
                slot = self.pending.pop(msg["id"], None)
                if slot:
                    slot["result"], slot["error"] = msg.get("result"), msg.get("error")
                    slot["event"].set()
            elif "id" in msg and msg.get("method"):          # 伺服器發來的請求（例如 ping）：簡單回覆
                try:
                    self._send({"jsonrpc": "2.0", "id": msg["id"], "result": {}})
                except ServiceError:
                    pass

    def _stderr_loop(self):
        for raw in iter(lambda: self.proc.stderr.readline(65536), b""):
            line = raw.decode("utf-8", errors="replace").strip()
            if line:
                self.stderr_tail = (self.stderr_tail + [line])[-20:]

    def call_tool(self, tool, args, cancel=None, timeout=300):
        res = self.request("tools/call", {"name": tool, "arguments": args or {}}, timeout, cancel)
        parts = []
        for item in res.get("content") or []:
            kind = item.get("type")
            if kind == "text":
                parts.append(item.get("text", ""))
            elif kind == "image":
                parts.append(f"[圖片：{item.get('mimeType', '')}，{len(item.get('data', '')) * 3 // 4:,} bytes]")
            elif kind == "resource":
                r = item.get("resource") or {}
                parts.append(r.get("text") or f"[資源：{r.get('uri', '')}]")
            elif kind == "resource_link":
                parts.append(f"[連結：{item.get('uri', '')}]")
        if res.get("structuredContent") and not parts:
            parts.append(json.dumps(res["structuredContent"], ensure_ascii=False, indent=1))
        text = "\n".join(p for p in parts if p) or "（工具沒有回傳內容）"
        if res.get("isError"):
            raise ToolError(text)
        return text

    def stop(self):
        if self.proc is None:
            return
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(3)
        except Exception:
            pass
        kill_process_tree(self.proc)          # v6.11：連伺服器自己開的子程序一起結束
        self.proc = None


class MCPManager:
    """管理設定檔裡所有啟用的 MCP 伺服器，提供給 Agent 的工具清單。"""

    def __init__(self):
        self.servers = {}
        self.status = {}          # 名稱 → 說明文字
        self.lock = threading.Lock()

    def start_all(self, on_status=None):
        self.stop_all()
        try:
            config = load_mcp_config()
        except ValueError as exc:
            self.status = {"（設定檔）": f"✘ {exc}"}
            return
        for name, spec in config["mcpServers"].items():
            if not isinstance(spec, dict) or not spec.get("enabled", True):
                self.status[name] = "未啟用"
                continue
            server = MCPServer(name, spec)
            self.status[name] = "啟動中…"
            if on_status:
                on_status()
            try:
                tools = server.start()
                self.servers[name] = server
                self.status[name] = f"✔ 已連線，{len(tools)} 個工具"
            except Exception as exc:
                server.stop()
                tail = f"（{server.stderr_tail[-1][:200]}）" if server.stderr_tail else ""
                self.status[name] = f"✘ {exc}{tail}"
            if on_status:
                on_status()

    def stop_all(self):
        for server in list(self.servers.values()):
            server.stop()
        self.servers = {}
        self.status = {}

    def agent_tools(self):
        """→ {工具名稱: {"category": "mcp", "schema": OpenAI 格式, "call": fn(args, cancel)}}"""
        tools = {}
        for sname, server in self.servers.items():
            if not server.alive:
                continue
            for t in server.tools:
                name = mcp_tool_name(sname, t["name"])
                params = t.get("inputSchema") if isinstance(t.get("inputSchema"), dict) else {}
                params = dict(params) or {"type": "object", "properties": {}}
                params.setdefault("type", "object")
                params.setdefault("properties", {})
                desc = f"[{sname}] " + str(t.get("description") or t.get("title") or t["name"])[:900]
                tools[name] = {"category": "mcp", "server": sname, "tool": t["name"],
                               "schema": {"type": "function", "function": {"name": name, "description": desc,
                                                                           "parameters": params}},
                               "call": (lambda a, cancel, s=server, tn=t["name"]: s.call_tool(tn, a, cancel))}
        return tools
