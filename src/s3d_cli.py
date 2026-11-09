

# ══════════════════════════════════════════════════════════════════════
#  訂閱 CLI：Claude Code（claude）與 OpenAI Codex（codex）
#  v6.10.0：用使用者已登入的命令列工具呼叫，花的是訂閱額度（Claude Pro/Max、ChatGPT Plus/Pro），不需要 API 金鑰。
#  服務網址寫成 cli://claude 或 cli://codex；模型留「claude-code」／「codex」＝用 CLI 的預設模型。
# ══════════════════════════════════════════════════════════════════════
CLI_KINDS = {
    "claude": {"label": "Claude Code", "default": "claude-code", "login": "claude",
               "models": ["claude-code", "sonnet", "opus", "haiku"],
               "plan": "Claude 訂閱（Pro／Max）"},
    "codex": {"label": "Codex", "default": "codex", "login": "codex login",
              "models": ["codex", "gpt-5.5", "gpt-5.5-codex", "gpt-5.4-mini"],
              "plan": "ChatGPT 訂閱（Plus／Pro／Business）"},
}
CLI_AGENT_IDLE = 900            # Agent 一輪：這麼久完全沒有輸出才當成卡住
CLI_TEXT_IDLE = 300             # 討論／紅隊：等待輸出的秒數上限
CLI_SNAPSHOT_FILES = 200000     # 改檔追蹤：最多記這麼多個檔案（超過時不把沒記到的檔案當成新檔）
CLI_SNAPSHOT_FILE_MAX = 1_000_000
CLI_SNAPSHOT_TOTAL = 96_000_000
CLI_HISTORY_CHARS = 24000       # Codex（不保留工作階段）每輪附上的對話歷史上限
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
CLI_FORCE_UNELEVATED = [False]      # 測試用：非 Windows 也加上 unelevated 參數


def cli_kind(url):
    m = re.match(r"^\s*cli://(claude|codex)\b", url or "", re.I)
    return m.group(1).lower() if m else ""


def cli_label(url):
    kind = cli_kind(url)
    return CLI_KINDS[kind]["label"] if kind else ""


def cli_model_arg(kind, model):
    """模型名稱是預設值（claude-code／codex／空白／預設）就不傳 --model，交給 CLI 自己決定。"""
    model = (model or "").strip()
    if not kind or model.lower() in ("", "預設", "default", CLI_KINDS[kind]["default"]):
        return ""
    return model


def find_cli(kind):
    """找 claude.exe／codex.exe：先看 PATH，再看官方安裝程式與 npm 的常見位置。找不到回傳空字串。"""
    names = {"claude": ("claude",), "codex": ("codex",)}[kind]
    for n in names:
        found = shutil.which(n)
        if found:
            return found
    home = os.path.expanduser("~")
    local = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
    roaming = os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
    if kind == "claude":
        cands = [os.path.join(home, ".local", "bin", "claude.exe"), os.path.join(home, ".local", "bin", "claude"),
                 os.path.join(roaming, "npm", "claude.cmd"), os.path.join(local, "Programs", "claude", "claude.exe")]
    else:
        cands = [os.path.join(local, "Programs", "OpenAI", "Codex", "bin", "codex.exe"),
                 os.path.join(roaming, "npm", "codex.cmd"), os.path.join(home, ".local", "bin", "codex")]
    return next((c for c in cands if os.path.isfile(c)), "")


def cli_env(kind):
    """子程序的環境變數。Claude Code 看到 ANTHROPIC_API_KEY 會改用 API 計費，這裡拿掉，確保用的是訂閱額度。"""
    # v6.10.1 紅隊：CLI 當 Agent 時會自己執行指令，不能讓它拿到 NVIDIA_API_KEY 等金鑰（跟一般 Agent 的指令一樣去掉）
    env = scrubbed_env()
    if kind == "claude":
        for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
            env.pop(k, None)
    else:
        for k in ("CODEX_API_KEY",):
            env.pop(k, None)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env["NO_COLOR"] = "1"
    return env


def cli_status(kind, timeout=20):
    """(是否找到, 是否已登入, 說明)。Codex 有 login status；Claude Code 沒有，送一句極短的訊息試試看。"""
    exe = find_cli(kind)
    label = CLI_KINDS[kind]["label"]
    if not exe:
        return False, False, f"找不到 {label}（{kind}）。請先安裝，裝好後重新開啟本程式。"
    try:
        if kind == "codex":
            p = subprocess.run([exe, "login", "status"], capture_output=True, timeout=timeout, env=cli_env(kind),
                               creationflags=_NO_WINDOW, stdin=subprocess.DEVNULL)
            out = (p.stdout + p.stderr).decode("utf-8", "replace").strip()
            ok = p.returncode == 0 and "logged in" in out.lower() and "not logged" not in out.lower()
            return True, ok, (out.splitlines() or [""])[-1][:200] if ok else cli_login_hint(kind)
        ok, msg, _secs = cli_test(kind, exe, "", timeout=max(timeout, 60))
        return True, ok, msg
    except (OSError, subprocess.SubprocessError) as exc:
        return True, False, f"無法執行 {label}：{exc}"


def cli_login_hint(kind):
    if kind == "claude":
        return ("Claude Code 沒有登入或登入已過期。請開「命令提示字元」輸入 claude，進去後打 /login，"
                "選用 Claude 訂閱帳號登入；完成後回來再試一次。")
    return "Codex 沒有登入。請開「命令提示字元」輸入 codex login，用 ChatGPT 帳號登入；完成後回來再試一次。"


def cli_friendly_error(kind, text):
    """把 CLI 的英文錯誤翻成白話；認不出來就原樣（截短）回傳。"""
    low = (text or "").lower()
    if any(k in low for k in ("authenticate", "oauth", "not logged in", "login", "unauthorized", "401",
                              "invalid api key", "credentials")):
        return cli_login_hint(kind)
    if any(k in low for k in ("usage limit", "rate limit", "limit reached", "quota", "429", "out of credits",
                              "credit balance")):
        return (f"{CLI_KINDS[kind]['label']} 的訂閱額度暫時用完了（或被限速）。等額度重置後再試，"
                "或先換別的模型。原始訊息：" + (text or "").strip()[:200])
    if "model" in low and any(k in low for k in ("not found", "not supported", "invalid", "does not exist", "unknown")):
        return f"{CLI_KINDS[kind]['label']} 不接受這個模型名稱，請改成預設（{CLI_KINDS[kind]['default']}）。原始訊息：" + text.strip()[:200]
    return (text or "").strip()[:600] or "沒有回傳任何內容"


def _content_text(content):
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, dict) and p.get("type") == "text":
                parts.append(p.get("text", ""))
            elif isinstance(p, dict) and p.get("type") in ("image_url", "image"):
                parts.append("[圖片：CLI 模式看不到圖片]")
        return "\n".join(parts)
    return str(content or "")


def flatten_messages(messages, limit=0):
    """把 OpenAI 格式的對話壓成 (系統提示, 一段文字)。只有一則使用者訊息時直接用它的內容。"""
    system = "\n\n".join(_content_text(m.get("content")) for m in messages if m.get("role") == "system").strip()
    rest = [m for m in messages if m.get("role") != "system"]
    if len(rest) == 1 and rest[0].get("role") == "user":
        return system, _content_text(rest[0].get("content"))
    names = {"user": "使用者", "assistant": "助理", "tool": "工具結果"}
    lines = []
    for m in rest:
        text = _content_text(m.get("content")).strip()
        if text:
            lines.append(f"【{names.get(m.get('role'), m.get('role'))}】\n{text}")
    body = "\n\n".join(lines)
    if limit and len(body) > limit:
        body = "…（較早的對話省略）\n\n" + body[-limit:]
    return system, body + "\n\n請接著回覆最後一則使用者訊息。"


def _is_batch(exe):
    """npm 裝的 claude.cmd／codex.cmd 要經過 cmd.exe：參數裡的換行會把後面的參數截掉，指令長度也只有 8191 字。"""
    return (exe or "").lower().endswith((".cmd", ".bat"))


CLI_MODEL_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/\[\]\-]{0,80}$")
_BATCH_UNSAFE = re.compile(r'[&|<>^%!"`\r\n]')


def cli_command(kind, exe, model="", system="", agent=None, workdir=None, resume=""):
    """組出命令列。agent＝None：純文字（不給任何工具）；agent＝"plan"／"edit"／"auto"：在 workdir 裡當 Agent。

    v6.10.1 紅隊：
    - 模型名稱只接受一般字元、不能以「-」開頭（否則會被 CLI 當成參數，例如偷加權限旗標）。
    - 經過 cmd.exe 的 .cmd／.bat：cmd.exe 會解讀參數裡的 & | < > ^ % 等符號（可以接著執行別的指令），
      所以不放任何自由文字（系統提示由呼叫端改放進 stdin、工作資料夾改用 cwd），剩下的參數再檢查一次。"""
    model = cli_model_arg(kind, model)
    if model and not CLI_MODEL_OK.match(model):
        raise ValueError(f"模型名稱「{model[:40]}」含有不允許的字元（只能用英數字與 . _ : / - [ ]，且不能以 - 開頭）。")
    batch = _is_batch(exe)
    if resume and not re.fullmatch(r"[A-Za-z0-9\-]{1,80}", resume):
        resume = ""
    if kind == "claude":
        cmd = [exe, "-p", "--output-format", "stream-json", "--verbose"]
        if agent is None:
            cmd += ["--tools", "", "--no-session-persistence", "--permission-mode", "plan"]
        else:
            mode = {"plan": "plan", "edit": "acceptEdits", "auto": "auto"}.get(agent, "acceptEdits")
            cmd += ["--permission-mode", mode, "--permission-prompts", "none"]
            if resume:
                cmd += ["--resume", resume]
        if model:
            cmd += ["--model", model]
        if system and not batch:
            cmd += ["--system-prompt" if agent is None else "--append-system-prompt", system]
    else:
        sandbox = "read-only" if agent in (None, "plan") else "workspace-write"
        cmd = [exe, "exec", "--json", "--ephemeral", "--skip-git-repo-check", "-s", sandbox]
        if agent in ("edit", "auto") and (os.name == "nt" or CLI_FORCE_UNELEVATED[0]):
            # 實測（Windows，Codex 設定 sandbox = "elevated"）：提升權限的沙盒以另一個帳號執行，
            # 讀不到使用者 AppData 裡的 Python（測試跑不起來），某些資料夾裡新建的檔案擁有者也不是使用者。
            # 改用一般權限的沙盒：仍只能寫工作資料夾，但用使用者自己的帳號執行。
            cmd += ["-c", 'windows.sandbox=unelevated' if batch else 'windows.sandbox="unelevated"']
        if workdir and not batch:
            cmd += ["-C", workdir]
        if model:
            cmd += ["-m", model]
        cmd += ["-"]
    if batch and any(_BATCH_UNSAFE.search(a) for a in cmd[1:]):
        raise ValueError("命令列參數含有 cmd.exe 會特別解讀的符號，為了安全不執行。")
    return cmd


def cli_system_in_stdin(kind, exe):
    """系統提示要不要改放在 stdin（Codex 一律；Claude 經過 cmd.exe 時）。"""
    return kind == "codex" or _is_batch(exe)


class CliProcess:
    """執行一次 CLI：stdin 送 UTF-8 提示、逐行讀 JSON 事件。close() 會把整個程序樹結束（給「停止」用）。"""

    def __init__(self, cmd, stdin_text, cwd=None, env=None):
        kwargs = {"creationflags": _NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     cwd=cwd, env=env, **kwargs)
        self.lines = queue.Queue()
        self.stderr = []
        self.closed = False
        threading.Thread(target=self._feed, args=(stdin_text,), daemon=True).start()
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._read_err, daemon=True).start()

    def _feed(self, text):
        try:
            self.proc.stdin.write((text or "").encode("utf-8"))
            self.proc.stdin.close()
        except (OSError, ValueError):
            pass

    def _read(self):
        try:
            for raw in self.proc.stdout:
                self.lines.put(raw.decode("utf-8", "replace").strip())
        except (OSError, ValueError):
            pass
        self.lines.put(None)

    def _read_err(self):
        try:
            for raw in self.proc.stderr:
                if len(self.stderr) < 400:
                    self.stderr.append(raw.decode("utf-8", "replace").rstrip())
        except (OSError, ValueError):
            pass

    def events(self, cancel, idle):
        """逐一產生 JSON 事件（dict）。取消或超過 idle 秒沒有輸出時結束程序並丟出 Cancelled／TimeoutError。"""
        last = time.monotonic()
        while True:
            if cancel.is_set():
                self.close()
                raise Cancelled()
            try:
                line = self.lines.get(timeout=0.25)
            except queue.Empty:
                if time.monotonic() - last > idle:
                    self.close()
                    raise TimeoutError(f"超過 {idle} 秒沒有任何輸出")
                continue
            if line is None:
                return
            last = time.monotonic()
            if line.startswith("{"):
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict):
                    yield data

    def wait(self, timeout=10):
        try:
            return self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.close()
            return None

    def close(self):
        if self.closed or self.proc.poll() is not None:
            self.closed = True
            return
        self.closed = True
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.proc.pid)], capture_output=True,
                               timeout=15, creationflags=_NO_WINDOW)
            else:
                os.killpg(self.proc.pid, 9)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass


def _cli_usage(kind, raw):
    raw = raw or {}
    if kind == "claude":
        prompt = sum(int(raw.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
        out = int(raw.get("output_tokens") or 0)
    else:
        prompt, out = int(raw.get("input_tokens") or 0), int(raw.get("output_tokens") or 0)
    return {"prompt_tokens": prompt, "completion_tokens": out, "total_tokens": prompt + out}


class CliTurn:
    """把兩種 CLI 的事件整理成同一套：text／thinking／tool_start／tool_end／session；結束後看 text、error、usage。"""

    def __init__(self, kind, on=None):
        self.kind = kind
        self.on = on or (lambda *_a: None)
        self.texts, self.error, self.usage, self.session, self.cost = [], "", None, "", None
        self.final = None
        self.tools = {}

    def feed(self, ev):
        t = ev.get("type")
        if self.kind == "claude":
            if t == "system" and ev.get("subtype") == "init":
                self.session = ev.get("session_id") or ""
                self.on("session", self.session)
            elif t == "assistant":
                for part in (ev.get("message") or {}).get("content") or []:
                    pt = part.get("type")
                    if pt == "text" and part.get("text"):
                        self.texts.append(part["text"])
                        self.on("text", part["text"])
                    elif pt in ("thinking", "redacted_thinking"):
                        self.on("thinking", None)
                    elif pt == "tool_use":
                        self.tools[part.get("id")] = part.get("name")
                        self.on("tool_start", part.get("id") or "", part.get("name") or "", part.get("input") or {})
            elif t == "user":
                for part in (ev.get("message") or {}).get("content") or []:
                    if isinstance(part, dict) and part.get("type") == "tool_result":
                        out = part.get("content")
                        if isinstance(out, list):
                            out = "\n".join(p.get("text", "") for p in out if isinstance(p, dict))
                        self.on("tool_end", part.get("tool_use_id") or "", not part.get("is_error"), str(out or ""))
            elif t == "result":
                self.usage = _cli_usage("claude", ev.get("usage"))
                self.cost = ev.get("total_cost_usd")
                if ev.get("is_error") or (ev.get("subtype") or "success") != "success":
                    self.error = str(ev.get("result") or ev.get("subtype") or "執行失敗")
                elif isinstance(ev.get("result"), str):
                    self.final = ev["result"]
            return
        item = ev.get("item") or {}
        it = item.get("type")
        if t == "thread.started":
            self.session = ev.get("thread_id") or ""
            self.on("session", self.session)
        elif t in ("item.started", "item.updated", "item.completed"):
            if it == "agent_message" and t == "item.completed" and item.get("text"):
                self.texts.append(item["text"])
                self.on("text", item["text"])
            elif it == "reasoning":
                self.on("thinking", None)
            elif it in ("command_execution", "file_change", "mcp_tool_call", "web_search"):
                iid = item.get("id") or ""
                if iid not in self.tools:
                    self.tools[iid] = it
                    if it == "command_execution":
                        args = {"command": item.get("command", "")}
                    elif it == "file_change":
                        args = {"paths": [c.get("path", "") for c in item.get("changes") or []]}
                    else:
                        args = {k: item.get(k) for k in ("server", "tool", "query") if item.get(k)}
                    self.on("tool_start", iid, it, args)
                if t == "item.completed":
                    status = item.get("status") or "completed"
                    ok = status == "completed" and (item.get("exit_code") in (None, 0))
                    out = item.get("aggregated_output") or ""
                    if it == "file_change":
                        out = "\n".join(f"{c.get('kind', '')} {c.get('path', '')}" for c in item.get("changes") or [])
                    self.on("tool_end", iid, ok, str(out))
            elif it == "error" and item.get("message"):
                self.on("notice", item["message"])
        elif t == "turn.completed":
            self.usage = _cli_usage("codex", ev.get("usage"))
        elif t == "turn.failed":
            self.error = str(((ev.get("error") or {}).get("message")) or "執行失敗")
        elif t == "error":
            self.error = str(ev.get("message") or "執行失敗")

    @property
    def text(self):
        if self.final is not None and self.final.strip():
            return self.final
        return "\n\n".join(x.strip() for x in self.texts if x.strip())


def cli_chat(endpoint, messages, cancel_event, on_event=None, register=None, options=None):
    """stream_chat 的 CLI 版本（AI 討論、紅隊、摘要…）：不給工具，只要文字。回傳格式同 stream_chat。"""
    options = options or {}
    on_event = on_event or (lambda *_a: None)
    register = register or (lambda _r: None)
    kind = cli_kind(endpoint.get("url"))
    started = time.monotonic()
    result = {"status": "error", "text": "", "error": "", "ttft": None, "elapsed": 0.0, "usage": None,
              "label": CLI_KINDS[kind]["label"], "finish": ""}
    exe = find_cli(kind)
    if not exe:
        result["error"] = f"找不到 {CLI_KINDS[kind]['label']}（{kind}），請先安裝並登入。"
        return result
    system, prompt = flatten_messages(messages, CLI_HISTORY_CHARS * 2)
    tmp = None
    try:
        workdir = None
        if kind == "codex":            # 純文字也給一個空的唯讀資料夾，避免 Codex 去讀目前目錄
            tmp = tempfile.mkdtemp(prefix="aic_codex_")
            workdir = tmp
        if cli_system_in_stdin(kind, exe) or (system and len(system) > 6000):
            if system:
                prompt = f"[系統指示]\n{system}\n\n[任務]\n{prompt}"
            system = ""
        cmd = cli_command(kind, exe, endpoint.get("model"), system, None, workdir)
        proc = CliProcess(cmd, prompt, cwd=workdir, env=cli_env(kind))
        register(proc)

        def on(k, *p):
            if k == "text":
                if result["ttft"] is None:
                    result["ttft"] = time.monotonic() - started
                    on_event("generating", None)
                on_event("delta", mask_secrets(p[0])[0] + "\n")
            elif k == "thinking":
                on_event("thinking", None)

        turn = CliTurn(kind, on)
        try:
            for ev in proc.events(cancel_event, int(options.get("timeout") or 0) + CLI_TEXT_IDLE):
                turn.feed(ev)
            code = proc.wait()
        finally:
            register(None)
            proc.close()
        result["usage"] = turn.usage
        text = turn.text
        if turn.error or (not text and code not in (0, None)):
            raw = turn.error or "\n".join(proc.stderr[-8:])
            result.update(status="error", error=cli_friendly_error(kind, raw), text=text)
        elif not text.strip():
            result.update(status="empty", error="CLI 結束了，但沒有回傳文字。" + ("\n".join(proc.stderr[-3:])[:300]))
        else:
            text, hidden = mask_secrets(text)      # v6.10.1：Codex 唯讀沙盒仍能讀整台電腦，回答裡的金鑰不轉給其他 AI
            result.update(status="done", text=text, finish="stop", masked=hidden)
    except Cancelled:
        result.update(status="stopped")
    except TimeoutError as exc:
        result.update(status="timeout", error=f"{CLI_KINDS[kind]['label']} {exc}")
    except ValueError as exc:
        result.update(status="error", error=str(exc))
    except OSError as exc:
        result.update(status="error", error=f"無法啟動 {CLI_KINDS[kind]['label']}：{exc}")
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
        result["elapsed"] = time.monotonic() - started
    return result


def cli_test(kind, exe=None, model="", timeout=TEST_TIMEOUT):
    """「測試」按鈕：真的送一句「請只回覆 OK」（會用掉一點點訂閱額度）。回傳 (是否可用, 說明, 秒數)。"""
    started = time.monotonic()
    if not (exe or find_cli(kind)):
        return False, f"找不到 {CLI_KINDS[kind]['label']}（{kind}）。", 0.0
    r = cli_chat({"url": f"cli://{kind}", "model": model}, [{"role": "user", "content": "請只回覆：OK"}],
                 threading.Event(), options={"timeout": max(0, timeout - CLI_TEXT_IDLE)})
    secs = time.monotonic() - started
    if r["status"] == "done":
        return True, f"可以正常呼叫（{CLI_KINDS[kind]['plan']}）", secs
    return False, r.get("error") or r["status"], secs


# ── Agent：讓 CLI 直接在工作資料夾裡讀寫、執行 ──
class Snapshot(dict):
    truncated = False


def snapshot_files(root):
    """記下工作資料夾裡每個檔案的 (修改時間, 大小, 內容)；內容只存小檔、總量有上限，用來事後備份與 diff。

    v6.10.1 紅隊（壓力測試）：原本超過 2 萬個檔案就停止記錄，事後比對時把沒記到的上萬個檔案當成「新建」，
    按「復原」會把它們全部搬走。現在檔案資訊一律記到 20 萬個，超過時標記 truncated，比對時不認定新檔。"""
    snap, total, count = Snapshot(), 0, 0
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            count += 1
            if count > CLI_SNAPSHOT_FILES:
                snap.truncated = True
                return snap
            full = os.path.join(current, name)
            try:
                st = os.lstat(full)
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode):
                continue          # v6.10.1：捷徑／連結不讀（避免把工作資料夾外的檔案讀進備份，復原時也不能寫穿出去）
            data = None
            if st.st_size <= CLI_SNAPSHOT_FILE_MAX and total + st.st_size <= CLI_SNAPSHOT_TOTAL:
                try:
                    with open(full, "rb") as f:
                        data = f.read()
                    total += len(data)
                except OSError:
                    data = None
            snap[os.path.relpath(full, root).replace("\\", "/")] = (st.st_mtime_ns, st.st_size, data)
    return snap


def diff_snapshot(root, before):
    """回傳 [(相對路徑, 種類, 舊內容 or None, 有沒有舊內容)]；種類：新增／修改／刪除。"""
    after = {}
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            full = os.path.join(current, name)
            try:
                st = os.lstat(full)
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode):
                continue
            after[os.path.relpath(full, root).replace("\\", "/")] = (st.st_mtime_ns, st.st_size)
    out = []
    for rel, (mt, size) in sorted(after.items()):
        old = before.get(rel)
        if old is None:
            if not getattr(before, "truncated", False):
                out.append((rel, "新增", None, True))
        elif (old[0], old[1]) != (mt, size):
            if old[2] is not None:
                try:
                    with open(os.path.join(root, rel), "rb") as f:
                        if f.read() == old[2]:
                            continue          # 只有時間變了，內容一樣
                except OSError:
                    pass
            out.append((rel, "修改", old[2], old[2] is not None))
    for rel, old in sorted(before.items()):
        if rel not in after:
            out.append((rel, "刪除", old[2], old[2] is not None))
    return out


CLI_TOOL_NAMES = {"Read": "read_file", "Write": "write_file", "Edit": "edit_file", "MultiEdit": "edit_file",
                  "NotebookEdit": "edit_file", "Bash": "run_command", "PowerShell": "run_command", "Glob": "glob",
                  "Grep": "search", "LS": "list_dir", "WebFetch": "web_fetch", "WebSearch": "web_search",
                  "TodoWrite": "todo_write", "command_execution": "run_command", "file_change": "edit_file",
                  "web_search": "web_search"}


def cli_tool_title(name, args):
    args = args or {}
    for k in ("command", "file_path", "path", "pattern", "url", "query", "description"):
        v = args.get(k)
        if v:
            return f"{name}：{str(v)[:80]}"
    if args.get("paths"):
        return f"{name}：" + "、".join(os.path.basename(p) for p in args["paths"][:4])
    return name


class CliAgentRunner:
    """Agent 主模型是 Claude Code／Codex 時用這個取代 AgentRunner（屬性與事件相同，畫面不用改）。

    CLI 自己讀檔、改檔、跑指令（Claude Code：acceptEdits／auto／plan；Codex：workspace-write／read-only 沙盒），
    本程式在每輪前後比對資料夾，把改過的檔案備份到 .ai協作/備份，記進修改清單，所以「復原這一輪」與自主研發的 diff 照常可用。"""

    def __init__(self, endpoint, workspace, emit, approve, ask, council=None, mode="build", permissions=None,
                 options=None, messages=None, global_prompt="", extra_tools=None):
        self.endpoint = endpoint
        self.kind = cli_kind(endpoint.get("url"))
        self.ws = workspace
        self.emit = emit
        self.approve = approve
        self.ask = ask
        self.council = council
        self.mode = mode
        self.permissions = dict(DEFAULT_PERMISSIONS, **(permissions or {}))
        self.session_allow = set()
        self.options = options or {}
        self.messages = messages if messages is not None else []
        self.global_prompt = global_prompt
        self.extra_tools = dict(extra_tools or {})
        self.cancel = threading.Event()
        self.usage = {"prompt": 0, "completion": 0, "calls": 0}
        self.todos = []
        self.session = ""              # Claude Code 的工作階段（接續上一輪；程式重開後改用對話歷史）
        self.text_protocol = False

    def agent_level(self):
        """plan：只讀；auto：可以跑指令（自主研發、驗證專案、或指令權限設為「允許」）；edit：只自動改檔、指令會被擋。"""
        if self.mode == "plan":
            return "plan"
        if "shell" in self.session_allow or self.permissions.get("shell") == "allow":
            return "auto"
        return "edit"

    def _instructions(self):
        level = self.agent_level()
        rule = {"plan": "目前是「規劃」模式：只能讀檔與分析，不要修改任何檔案、不要執行會改變東西的指令。",
                "edit": "目前可以直接修改這個資料夾裡的檔案；執行指令可能會被擋下，被擋就說明需要使用者自己執行什麼。",
                "auto": "目前可以修改檔案並執行測試等指令；刪除大量檔案、改系統設定、連外上傳等高風險動作不要做，改成說明給使用者決定。"}[level]
        parts = [f"你在使用者電腦上的「AI 協作工作台」裡被呼叫，工作資料夾是：{self.ws.root}。只在這個資料夾裡工作。",
                 rule, "一律用台灣繁體中文回答，避免簡體字與中國大陸用語。完成後用幾句話說明改了什麼、怎麼驗證。"]
        if self.global_prompt:
            parts.append(self.global_prompt)
        return "\n".join(parts)

    def _prompt(self, user_text, in_stdin=None):
        """in_stdin：系統指示要不要放在 stdin（Codex，或經過 cmd.exe 的 claude.cmd）。"""
        if in_stdin is None:
            in_stdin = self.kind == "codex"
        if self.kind == "claude" and self.session:
            return user_text
        head = f"[系統指示]\n{self._instructions()}\n\n" if in_stdin else ""
        earlier = [m for m in self.messages[:-1] if m.get("role") in ("user", "assistant")]
        if not earlier:
            return f"{head}[任務]\n{user_text}" if head else user_text
        _sys, history = flatten_messages(earlier, CLI_HISTORY_CHARS)
        history = history.rsplit("\n\n請接著回覆最後一則使用者訊息。", 1)[0]
        return f"{head}[先前的對話]\n{history}\n\n[這次的訊息]\n{user_text}"

    def run(self, user_text, images=None):
        self.cancel.clear()
        self.ws.turn += 1
        self.messages.append({"role": "user", "content": user_text})
        label = CLI_KINDS[self.kind]["label"]
        status, shown = "done", ""
        if images:
            self.emit("notice", f"{label} 模式看不到附加的圖片，這一輪只送文字。")
        reason = USAGE.over_budget()
        if reason:                       # v6.11 紅隊：CLI 當 Agent 原本不受預算上限限制
            self.emit("error", f"{reason}。到「設定 → Agent → 用量與預算」可以調高或取消上限。")
            self.emit("turn_done", "error", dict(self.usage))
            return
        exe = find_cli(self.kind)
        if not exe:
            self.emit("error", f"找不到 {label}（{self.kind}），請先安裝並登入。")
            self.emit("turn_done", "error", dict(self.usage))
            return
        self.emit("step", 1)
        before = snapshot_files(self.ws.root)
        level = self.agent_level()
        in_stdin = cli_system_in_stdin(self.kind, exe)
        proc = None
        streamed = []
        try:
            cmd = cli_command(self.kind, exe, self.endpoint.get("model"), "" if in_stdin else self._instructions(),
                              level, self.ws.root, self.session if self.kind == "claude" else "")
            proc = CliProcess(cmd, self._prompt(user_text, in_stdin), cwd=self.ws.root, env=cli_env(self.kind))
            self.emit("register", proc)
            step = [1]

            def on(k, *p):
                if k in ("text", "tool_end"):          # v6.10.1：CLI 讀到的金鑰不顯示、不存進對話、不轉給別的 AI
                    p = list(p)
                    i = 0 if k == "text" else 2
                    p[i], hidden = mask_secrets(p[i])
                    if hidden:
                        self.emit("notice", f"🔒 {label} 的輸出裡有 {hidden} 個像金鑰的字串，已遮蔽。")
                if k == "text":
                    streamed.append(p[0])
                    self.emit("text", p[0] + "\n")
                elif k == "thinking":
                    self.emit("thinking", None)
                elif k == "tool_start":
                    call_id, raw, args = p
                    if streamed:
                        self.emit("assistant_end", "\n\n".join(streamed))
                        streamed.clear()
                    step[0] += 1
                    self.emit("step", step[0])
                    name = CLI_TOOL_NAMES.get(raw, raw)
                    if raw == "TodoWrite" and isinstance(args.get("todos"), list):
                        self.todos = [{"content": t.get("content", ""), "status": t.get("status", "pending")}
                                      for t in args["todos"] if isinstance(t, dict)]
                        self.emit("todo", list(self.todos))
                    self.emit("tool_start", call_id, name, args, cli_tool_title(raw, args))
                elif k == "tool_end":
                    self.emit("tool_end", p[0], p[1], p[2][:6000])
                elif k == "session":
                    if self.kind == "claude" and p[0]:
                        self.session = p[0]
                elif k == "notice":
                    self.emit("notice", f"{label}：{p[0]}")

            turn = CliTurn(self.kind, on)
            for ev in proc.events(self.cancel, CLI_AGENT_IDLE):
                turn.feed(ev)
            code = proc.wait()
            if turn.usage:
                self.usage["calls"] += 1
                self.usage["prompt"] += turn.usage["prompt_tokens"]
                self.usage["completion"] += turn.usage["completion_tokens"]
                self.emit("usage", dict(self.usage))
                USAGE.add(self.endpoint, [], {"usage": turn.usage, "text": ""})
            shown = "\n\n".join(streamed)
            self.emit("assistant_end", shown)
            text = mask_secrets(turn.text)[0]
            if turn.error or (not text and code not in (0, None)):
                raw = turn.error or "\n".join(proc.stderr[-8:])
                if self.kind == "claude" and self.session and "session" in raw.lower():
                    self.session = ""          # 工作階段失效：下一輪改用對話歷史重新開始
                status = "error"
                self.emit("error", cli_friendly_error(self.kind, raw))
            if text:
                self.messages.append({"role": "assistant", "content": text})
        except Cancelled:
            status = "stopped"
            self.emit("assistant_end", "\n\n".join(streamed))
        except TimeoutError as exc:
            status = "error"
            self.emit("assistant_end", "\n\n".join(streamed))
            self.emit("error", f"{label} {exc}，已停止。")
        except ValueError as exc:
            status = "error"
            self.emit("error", str(exc))
        except OSError as exc:
            status = "error"
            self.emit("error", f"無法啟動 {label}：{exc}")
        finally:
            if proc:
                self.emit("register", None)
                proc.close()
            try:
                self._record_changes(before)
            except Exception as exc:          # 記錄失敗不影響這一輪的結果
                self.emit("notice", f"整理改檔紀錄時出錯：{exc}")
        self.emit("turn_done", status, dict(self.usage))

    def _record_changes(self, before):
        stamp = time.strftime("%Y%m%d_%H%M%S")
        nobackup = []
        if getattr(before, "truncated", False):
            self.emit("notice", f"工作資料夾超過 {CLI_SNAPSHOT_FILES:,} 個檔案，這一輪新建的檔案無法完整列入「變更的檔案」。")
        for rel, kind, old, has_old in diff_snapshot(self.ws.root, before):
            full = os.path.join(self.ws.root, rel)
            backup = None
            if kind != "新增" and has_old:
                backup = os.path.join(self.ws.agent_dir("備份", self.ws.session_id), stamp, rel)
                os.makedirs(os.path.dirname(backup), exist_ok=True)
                with open(backup, "wb") as f:
                    f.write(old)
            item = self.ws.record_change(full, backup, {"新增": "新建", "修改": "編輯", "刪除": "刪除"}[kind])
            if kind != "新增" and not has_old:
                item["no_backup"] = True       # 太大沒有留內容：復原時跳過，不能把它搬走
                nobackup.append(rel)
            self.emit("file_changed", item)
        if nobackup:
            self.emit("notice", "這些檔案太大，改之前沒有留備份（無法用「復原」還原）：" + "、".join(nobackup[:8]))
