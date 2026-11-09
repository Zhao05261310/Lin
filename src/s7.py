
# ═════════════════════════ 7. 主視窗（對話為主的版面） ═════════════════════════
# 版面參考 opencode／Claude／ChatGPT／llm-council 等：左邊是對話清單，中間是對話串，
# 每次工具呼叫是一張可展開的小卡、危險動作會跳出核准卡；右邊是任務清單與變更的檔案。
log_app = logging.getLogger("ai_collab.app")
STATUS_FROM_RESULT = {"done": "done", "stopped": "stopped", "error": "error", "timeout": "timeout", "empty": "empty"}

def enable_high_dpi():
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def open_path(path, parent=None):
    """用系統預設的程式開啟檔案或資料夾。回傳是否成功。
    v6.18.1：先確認檔案存在、不是空的；Windows 沒有替這種副檔名設定預設程式時（os.startfile 會失敗），
    改在檔案總管選取它，並說明怎麼設定，不再只丟出「無法開啟」。"""
    opts = {"parent": parent} if parent is not None else {}
    if not path or not os.path.exists(path):
        messagebox.showerror(APP_NAME, f"找不到：{path or '（沒有路徑）'}\n可能已經被移動或刪除。", **opts)
        return False
    if os.path.isfile(path) and os.path.getsize(path) == 0:
        messagebox.showerror(APP_NAME, f"這個檔案是空的（0 bytes），通常表示生成沒有成功：\n{path}", **opts)
        return False
    try:
        if sys.platform == "win32":
            os.startfile(os.path.normpath(path))
        else:
            import subprocess
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])
        return True
    except Exception as exc:
        if sys.platform == "win32" and os.path.isfile(path) and reveal_in_folder(path):
            ext = os.path.splitext(path)[1] or "這種"
            messagebox.showinfo(APP_NAME, f"這台電腦還沒有設定用什麼程式開啟 {ext} 檔（{exc}）。\n\n"
                                          "已經在檔案總管選取這個檔案：在它上面按右鍵 →「開啟檔案」→「選擇其他應用程式」，"
                                          "選「媒體播放器」「相片」等，並勾選「一律使用此應用程式」。", **opts)
            return False
        messagebox.showerror(APP_NAME, f"無法開啟：{path}\n{exc}", **opts)
        return False


def reveal_in_folder(path):
    """在檔案總管（Finder）裡選取這個檔案；不支援選取時開啟所在資料夾。"""
    try:
        import subprocess
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select," + os.path.normpath(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path) or "."])
        return True
    except Exception:
        return False


def _make_app_class():
    TopologyView = _make_topology_class()

    class ScrollFrame(ttk.Frame):
        """可垂直捲動的容器（內容放在 self.inner）。"""

        def __init__(self, app, master):
            super().__init__(master, style="Surface.TFrame")
            self.canvas = tk.Canvas(self, highlightthickness=0, bd=0)
            app._register_tk(self.canvas, "surface")
            self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
            self.inner = ttk.Frame(self.canvas, style="Surface.TFrame")
            self.inner.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
            self.window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
            self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.window, width=e.width))
            self.canvas.configure(yscrollcommand=self.bar.set)
            self.canvas.pack(side="left", fill="both", expand=True)
            self.bar.pack(side="right", fill="y")
            self.canvas._scroll_frame = self.inner._scroll_frame = self

    class EndpointEditor:
        """「端點」分頁中的一張 AI 設定卡。"""

        def __init__(self, app, parent, service, index):
            self.app = app
            self.service = service
            self.frame = ttk.Frame(parent, style="Card.TFrame", padding=(12, 10))
            self.frame.pack(fill="x", pady=(0, 10), padx=(0, 6))
            f = self.frame
            f.columnconfigure(1, weight=3)
            f.columnconfigure(3, weight=1)
            self.vars = {k: tk.StringVar(value=service.get(k, "")) for k in
                         ("name", "role", "url", "model", "credential", "temperature", "max_tokens", "task")}
            self.reasoning_var = tk.StringVar(value=REASONING_LABELS.get(service.get("reasoning", ""), "模型預設"))
            if not self.vars["credential"].get():
                self.vars["credential"].set(service.get("credential_env", ""))
            self.enabled = tk.BooleanVar(value=service.get("enabled", True))

            # 第 1 列：色點、編號、名稱、參與
            head = ttk.Frame(f, style="Surface.TFrame")
            head.grid(row=0, column=0, columnspan=4, sticky="ew")
            self.dot = tk.Canvas(head, width=16, height=16, highlightthickness=0)
            app._register_tk(self.dot, "surface")
            self.dot.pack(side="left", padx=(0, 6))
            ttk.Label(head, text=f"#{index + 1}", style="Muted.TLabel").pack(side="left", padx=(0, 6))
            ttk.Entry(head, textvariable=self.vars["name"], width=8).pack(side="left", fill="x", expand=True)
            ttk.Checkbutton(head, text="參與", variable=self.enabled, command=self._changed).pack(side="left", padx=(8, 0))
            # 第 2 列：操作按鈕
            tools = ttk.Frame(f, style="Surface.TFrame")
            tools.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(6, 6))
            ttk.Button(tools, text="選擇模型…", style="Ghost.TButton",
                       command=lambda: app.open_model_picker(self)).pack(side="left")
            self.test_button = ttk.Button(tools, text="測試", style="Ghost.TButton",
                                          command=lambda: app.test_service(self.service))
            self.test_button.pack(side="left", padx=(4, 0))
            self.remove_button = ttk.Button(tools, text="移除", style="Danger.TButton",
                                            command=lambda: app.remove_service(service))
            self.remove_button.pack(side="right")
            ttk.Button(tools, text="↓", width=2, style="Ghost.TButton",
                       command=lambda: app.move_service(service, 1)).pack(side="right", padx=(0, 6))
            ttk.Button(tools, text="↑", width=2, style="Ghost.TButton",
                       command=lambda: app.move_service(service, -1)).pack(side="right", padx=(0, 2))

            def label(row, col, text):
                ttk.Label(f, text=text, style="Muted.TLabel").grid(row=row, column=col, sticky="w", padx=(0, 6), pady=3)

            label(2, 0, "角色")
            role = ttk.Combobox(f, textvariable=self.vars["role"], values=list(ROLES), state="readonly", width=8)
            role.grid(row=2, column=1, sticky="ew", pady=3)
            role.bind("<<ComboboxSelected>>", lambda _e: self._changed())
            label(2, 2, "  溫度")
            ttk.Entry(f, textvariable=self.vars["temperature"], width=4).grid(row=2, column=3, sticky="ew", pady=3)
            label(3, 0, "網址")
            ttk.Entry(f, textvariable=self.vars["url"], width=10).grid(row=3, column=1, columnspan=3, sticky="ew", pady=3)
            label(4, 0, "模型")
            self.model_combo = ttk.Combobox(f, textvariable=self.vars["model"], width=10)
            self.model_combo.grid(row=4, column=1, columnspan=3, sticky="ew", pady=3)
            label(5, 0, "金鑰")
            self.key_entry = ttk.Entry(f, textvariable=self.vars["credential"], width=8)
            self.key_entry.grid(row=5, column=1, sticky="ew", pady=3)
            label(5, 2, "  上限")
            ttk.Entry(f, textvariable=self.vars["max_tokens"], width=4).grid(row=5, column=3, sticky="ew", pady=3)

            label(6, 0, "工作")
            ttk.Entry(f, textvariable=self.vars["task"], width=10).grid(row=6, column=1, columnspan=3, sticky="ew", pady=3)
            label(7, 0, "思考")
            rc = ttk.Combobox(f, textvariable=self.reasoning_var, values=list(REASONING_LABELS.values()), state="readonly", width=10)
            rc.grid(row=7, column=1, columnspan=3, sticky="ew", pady=3)
            rc.bind("<<ComboboxSelected>>", lambda _e: self._changed())
            self.reason_hint = ttk.Label(f, text="", style="Muted.TLabel", wraplength=300)
            self.reason_hint.grid(row=8, column=0, columnspan=4, sticky="w")
            # v6.7.0：本機大模型（Ollama）——上下文長度與保持載入；只有網址是 Ollama 時顯示
            self.ctx_var = tk.StringVar(value=next((lab for lab, v in OLLAMA_CTX_CHOICES if v == service.get("num_ctx", "")),
                                                   OLLAMA_CTX_CHOICES[0][0]))
            self.keep_var = tk.StringVar(value=next((lab for lab, v in OLLAMA_KEEP_CHOICES if v == service.get("keep_alive", "")),
                                                    OLLAMA_KEEP_CHOICES[0][0]))
            self.local_row = ttk.Frame(f, style="Surface.TFrame")
            self.local_row.grid(row=9, column=0, columnspan=4, sticky="ew", pady=3)
            ttk.Label(self.local_row, text="本機上下文", style="Muted.TLabel").pack(side="left", padx=(0, 6))
            cc = ttk.Combobox(self.local_row, textvariable=self.ctx_var, values=[lab for lab, _v in OLLAMA_CTX_CHOICES],
                              state="readonly", width=10)
            cc.pack(side="left")
            ttk.Label(self.local_row, text="  保持載入", style="Muted.TLabel").pack(side="left", padx=(0, 6))
            kc = ttk.Combobox(self.local_row, textvariable=self.keep_var, values=[lab for lab, _v in OLLAMA_KEEP_CHOICES],
                              state="readonly", width=12)
            kc.pack(side="left")
            for combo in (cc, kc):
                combo.bind("<<ComboboxSelected>>", lambda _e: self._changed())
            self.local_hint = ttk.Label(f, text="顯卡放不下的部分 Ollama 會自動放到系統記憶體；上下文越長越吃記憶體。",
                                        style="Muted.TLabel", wraplength=300)
            self.local_hint.grid(row=10, column=0, columnspan=4, sticky="w")
            self.status = ttk.Label(f, text=service.get("_status", ""), style="Muted.TLabel", wraplength=300)
            self.status.grid(row=11, column=0, columnspan=4, sticky="w", pady=(6, 0))

            def wrap(e):
                for w in (self.status, self.reason_hint, self.local_hint):
                    w.configure(wraplength=max(160, e.width - 30))
            f.bind("<Configure>", wrap)
            cache = app.model_cache.get(service.get("url", "").strip().rstrip("/"))
            if cache:
                self.model_combo.configure(values=cache)
            for var in self.vars.values():
                var.trace_add("write", lambda *_a: self._changed())
            self.key_entry.bind("<KeyRelease>", lambda _e: self.refresh_mask())
            self.refresh_mask()
            self.paint_dot()
            self.refresh_reason_hint()
            self.refresh_local_row()

        def refresh_local_row(self):
            try:
                if ollama_native_base(self.vars["url"].get()):
                    self.local_row.grid()
                    self.local_hint.grid()
                else:
                    self.local_row.grid_remove()
                    self.local_hint.grid_remove()
            except tk.TclError:
                pass

        def refresh_reason_hint(self):
            hint = REASONING_STYLE_HINTS.get(reasoning_style(self.vars["model"].get(), self.vars["url"].get()), "")
            try:
                self.reason_hint.configure(text=hint)
                if hint:
                    self.reason_hint.grid()
                else:
                    self.reason_hint.grid_remove()
            except tk.TclError:
                pass

        def paint_dot(self):
            self.dot.delete("all")
            color = self.app.theme.role_color(self.vars["role"].get()) if self.enabled.get() else self.app.theme["line"]
            self.dot.create_oval(2, 2, 14, 14, fill=color, outline="")

        def refresh_mask(self):
            text = self.vars["credential"].get()
            self.key_entry.configure(show="" if (not text or looks_like_env_name(text)) else "•")

        def set_status(self, text, kind="muted"):
            self.service["_status"] = text
            colors = {"muted": self.app.theme["muted"], "ok": self.app.theme["success"],
                      "bad": self.app.theme["danger"], "warn": self.app.theme["warning"]}
            try:
                self.status.configure(text=text, foreground=colors.get(kind, colors["muted"]))
            except tk.TclError:
                pass

        def _changed(self):
            s = self.service
            old_model, old_url, old_name = s.get("model", ""), s.get("url", ""), s.get("name", "")
            for key, var in self.vars.items():
                s[key] = var.get().strip() if key != "credential" else var.get()
            s["enabled"] = bool(self.enabled.get())
            rev = {v: k for k, v in REASONING_LABELS.items()}
            s["reasoning"] = rev.get(self.reasoning_var.get(), "")
            s["num_ctx"] = dict(OLLAMA_CTX_CHOICES).get(self.ctx_var.get(), "")
            s["keep_alive"] = dict(OLLAMA_KEEP_CHOICES).get(self.keep_var.get(), "")
            self.refresh_local_row()
            self.refresh_reason_hint()
            if not s["credential"].strip() and NVIDIA_HOST in s["url"].lower():
                s["credential"] = DEFAULT_NVIDIA_ENV
            if s.get("model") != old_model or s.get("url") != old_url:
                s.pop("_tested", None)          # 換了模型就要重新測試
                self.set_status("")
                cache = self.app.model_cache.get(s.get("url", "").strip().rstrip("/"))
                if cache:
                    self.model_combo.configure(values=cache)
                    if s.get("model") and s["model"] not in cache:
                        self.set_status("⚠ 這個模型名稱不在服務提供的清單中，請確認拼字或按「選擇模型…」挑選。", "warn")
                # 名稱自動跟著模型：名稱是空白、「AI 數字」或等於舊模型簡稱時，改成新模型簡稱
                if s.get("model") != old_model and (not old_name or re.fullmatch(r"AI\s*\d+", old_name)
                                                    or old_name == short_model(old_model)):
                    new_name = short_model(s.get("model"))
                    if new_name and new_name != old_name:
                        self.vars["name"].set(new_name)
                        return
            self.paint_dot()
            self.app.on_service_changed(s)

    INLINE_MD = re.compile(r"(\*\*[^*\n]+?\*\*|`[^`\n]+`|\[[^\]\n]+\]\([^)\s]+\))")

    class Transcript:
        """對話串：一個 tk.Text，用「區塊」（兩個 mark 夾住的範圍）組成訊息、工具卡、討論區段。

        - 每個區塊有 <id>_s（左黏）與 <id>_e（右黏）兩個 mark，在 _e 插入就會附加到區塊尾端。
        - 可摺疊的區塊用 elide 標籤隱藏內容；巢狀區塊會繼承祖先的摺疊標籤。
        - 回答先以原文串流，完成後再轉成 Markdown 排版（標題、粗體、清單、程式碼框、表格）。
        """

        def __init__(self, app, parent):
            self.app = app
            self.frame = ttk.Frame(parent, style="Chat.TFrame")
            self.text = tk.Text(self.frame, wrap="word", relief="flat", bd=0, padx=34, pady=20, cursor="arrow",
                                highlightthickness=0, spacing1=1, spacing3=1, undo=False, exportselection=True)
            app._register_tk(self.text, "chat")
            bar = ttk.Scrollbar(self.frame, orient="vertical", command=self.text.yview)
            self.text.configure(yscrollcommand=bar.set)
            self.text.pack(side="left", fill="both", expand=True)
            bar.pack(side="right", fill="y")
            self.text.bind("<Key>", self._key)
            self.text.bind("<<Paste>>", lambda _e: "break")
            self.text.bind("<<Copy>>", self._copy)
            self.text.bind("<Button-3>", self._menu)          # v6.6.3：右鍵選單（複製、全選、複製這則訊息）
            self.text.bind("<Configure>", lambda _e: self._resize_windows())
            # 使用者自己捲動時才重新判斷「要不要跟著最新內容捲到底」，寫入文字時不再每次都去算版面
            for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>", "<KeyRelease-Prior>", "<KeyRelease-Next>",
                        "<KeyRelease-Up>", "<KeyRelease-Down>", "<KeyRelease-Home>", "<KeyRelease-End>"):
                self.text.bind(seq, self._user_scrolled, add="+")
            for seq in ("<ButtonRelease-1>", "<B1-Motion>"):
                bar.bind(seq, self._user_scrolled, add="+")
            self.counter = 0
            self._follow = True
            self._scroll_job = None
            self._force_scroll = False
            self.configure_tags()
            self.clear()

        # ── 基本 ──
        def _key(self, event):
            if event.state & 0x4 and event.keysym.lower() in ("c", "a", "insert"):
                if event.keysym.lower() == "a":
                    self.text.tag_add("sel", "1.0", "end")
                    return "break"
                return None
            if event.keysym in ("Up", "Down", "Prior", "Next", "Home", "End"):
                return None
            return "break"

        def _copy(self, _event=None):
            try:
                text = self.text.get("sel.first", "sel.last")
            except tk.TclError:
                return "break"
            self.text.clipboard_clear()
            self.text.clipboard_append(text.replace("\u200b", ""))
            return "break"

        def _put_clipboard(self, text):
            text = (text or "").replace("\u200b", "").strip("\n")
            if text:
                self.text.clipboard_clear()
                self.text.clipboard_append(text)
                try:
                    self.app.status_label.configure(text="已複製")
                except (tk.TclError, AttributeError):
                    pass

        def message_at(self, index):
            """index 所在的那一則訊息（最上層區塊）的文字；不在任何訊息裡回傳空字串。"""
            for rid, parent in self.parent.items():
                if parent != "root":
                    continue
                try:
                    if self.text.compare(f"{rid}_s", "<=", index) and self.text.compare(index, "<", f"{rid}_e"):
                        return self.plain_text(rid)
                except tk.TclError:
                    continue
            return ""

        def _menu(self, event):
            index = self.text.index(f"@{event.x},{event.y}")
            try:
                selected = self.text.get("sel.first", "sel.last")
            except tk.TclError:
                selected = ""
            message = self.message_at(index)
            m = tk.Menu(self.text, tearoff=False)
            m.add_command(label="複製", accelerator="Ctrl+C", state="normal" if selected.strip() else "disabled",
                          command=lambda: self._put_clipboard(selected))
            m.add_command(label="複製這則訊息", state="normal" if message.strip() else "disabled",
                          command=lambda: self._put_clipboard(message))
            m.add_command(label="複製整段對話", command=lambda: self._put_clipboard(self.text.get("1.0", "end")))
            m.add_separator()
            m.add_command(label="全選", accelerator="Ctrl+A", command=lambda: self.text.tag_add("sel", "1.0", "end"))
            m.tk_popup(event.x_root, event.y_root)
            return "break"

        def plain_text(self, rid):
            return self.text.get(f"{rid}_s", f"{rid}_e").replace("\u200b", "")

        def clear(self):
            self.text.delete("1.0", "end")
            for name in list(self.text.mark_names()):
                if name not in ("insert", "current"):
                    self.text.mark_unset(name)
            self.parent, self.collapsible, self.windows, self.elided = {}, set(), [], {}
            self.on_open = {}          # 收合區塊第一次（或每次）展開時才把內容畫出來：收合的內容不放進 Text，畫面才不會越用越慢
            self.text.insert("1.0", "\n")
            self.text.mark_set("root_s", "1.0")
            self.text.mark_gravity("root_s", "left")
            self.text.mark_set("root_e", "1.0")
            self.text.mark_gravity("root_e", "right")

        def new_id(self, prefix="b"):
            self.counter += 1
            return f"{prefix}{self.counter}"

        def at_bottom(self):
            return self.text.yview()[1] >= 0.995

        def _user_scrolled(self, _e=None):
            self.text.after_idle(lambda: setattr(self, "_follow", self.at_bottom()))

        def scroll_end(self, force=False):
            """捲到最底。合併成每 80ms 最多一次：Text.see() 要重算整份版面，串流時每個字都呼叫會讓畫面卡住。"""
            if force:
                self._force_scroll = True
                self._follow = True
            if not (self._force_scroll or self._follow) or self._scroll_job:
                return
            self._scroll_job = self.text.after(80, self._do_scroll)

        def _do_scroll(self):
            self._scroll_job = None
            if self._force_scroll or self._follow:
                try:
                    self.text.see("end")
                except tk.TclError:
                    pass
            self._force_scroll = False

        def _chain(self, rid):
            tags = []
            while rid and rid != "root":
                if rid in self.collapsible:
                    tags.append(f"{rid}_body")
                rid = self.parent.get(rid)
            return tuple(tags)

        def region(self, parent="root", rid=None, prefix="b", nl_tags=()):
            """在 parent 區塊尾端建立子區塊，回傳 id。區塊後面放一個零寬字元，讓前後區塊的 mark 不會重疊。"""
            rid = rid or self.new_id(prefix)
            idx = self.text.index(f"{parent}_e")
            self.text.insert(idx, "\u200b", ("sep",) + tuple(nl_tags) + self._chain(parent))
            self.text.mark_set(f"{rid}_s", idx)
            self.text.mark_gravity(f"{rid}_s", "left")
            self.text.mark_set(f"{rid}_e", idx)
            self.text.mark_gravity(f"{rid}_e", "right")
            self.parent[rid] = parent
            return rid

        def write(self, rid, text, tags=()):
            if isinstance(tags, str):
                tags = (tags,)
            self.text.insert(f"{rid}_e", text, tuple(tags) + self._chain(rid))
            self.scroll_end()

        def clear_region(self, rid):
            self.text.delete(f"{rid}_s", f"{rid}_e")

        def set_collapsible(self, rid, collapsed):
            self.collapsible.add(rid)
            self.elided[rid] = collapsed
            self.text.tag_configure(f"{rid}_body", elide=collapsed)
            self.text.tag_raise("sep")

        def toggle(self, rid):
            self.elided[rid] = not self.elided.get(rid, False)
            self.text.tag_configure(f"{rid}_body", elide=self.elided[rid])
            return not self.elided[rid]

        def embed(self, rid, widget, pady=4):
            self.text.window_create(f"{rid}_e", window=widget, padx=0, pady=pady)
            idx = self.text.index(f"{rid}_e - 1c")
            for tag in self._chain(rid):
                self.text.tag_add(tag, idx)
            self.windows.append(widget)
            self.scroll_end()

        def _resize_windows(self):
            width = max(200, self.text.winfo_width() - 90)
            for w in list(self.windows):
                try:
                    if getattr(w, "_full_width", False):
                        w.configure(width=width)
                except tk.TclError:
                    self.windows.remove(w)

        def clickable(self, tag, callback):
            self.text.tag_bind(tag, "<Button-1>", lambda _e: callback())
            self.text.tag_bind(tag, "<Enter>", lambda _e: self.text.configure(cursor="hand2"))
            self.text.tag_bind(tag, "<Leave>", lambda _e: self.text.configure(cursor="arrow"))

        # ── 樣式 ──
        def configure_tags(self):
            t, F = self.app.theme, self.app.fonts
            w = self.text
            code_bg = mix(t["surface2"], t["text"], 0.06 if not t.dark else 0.10)
            cfg = {
                "who": dict(font=F["ui_bold"], foreground=t["muted"], spacing1=18, spacing3=4),
                "who_user": dict(font=F["ui_bold"], foreground=t["accent"], spacing1=18, spacing3=4),
                "user_text": dict(font=F["content"], foreground=t["text"], background=mix(t["accent"], t["canvas_chat"], 0.9),
                                  lmargin1=14, lmargin2=14, rmargin=60, spacing1=6, spacing3=6),
                "md_p": dict(font=F["content"], foreground=t["text"], spacing3=3),
                "md_h1": dict(font=F["h1"], foreground=t["text"], spacing1=12, spacing3=6),
                "md_h2": dict(font=F["h2"], foreground=t["text"], spacing1=10, spacing3=4),
                "md_h3": dict(font=F["h3"], foreground=t["text"], spacing1=8, spacing3=3),
                "md_bold": dict(font=F["content_bold"]),
                "md_icode": dict(font=F["mono"], background=code_bg, foreground=mix(t["accent"], t["text"], 0.35)),
                "md_code": dict(font=F["mono"], background=code_bg, foreground=t["text"], lmargin1=14, lmargin2=14,
                                rmargin=20, spacing1=0, spacing3=0),
                "md_li": dict(font=F["content"], foreground=t["text"], lmargin1=12, lmargin2=30, spacing3=2),
                "md_li2": dict(font=F["content"], foreground=t["text"], lmargin1=32, lmargin2=50, spacing3=2),
                "md_quote": dict(font=F["content"], foreground=t["muted"], lmargin1=16, lmargin2=16),
                "md_table": dict(font=F["mono"], foreground=t["text"], spacing3=0),
                "md_hr": dict(foreground=t["border"]),
                "md_link": dict(foreground=t["accent"], underline=True),
                "tool_head": dict(font=F["small"], foreground=t["muted"], background=t["surface2"], lmargin1=8,
                                  lmargin2=8, spacing1=3, spacing3=3),
                "tool_ok": dict(foreground=t["success"]),
                "tool_bad": dict(foreground=t["danger"]),
                "tool_run": dict(foreground=t["accent"]),
                "tool_out": dict(font=F["mono_small"], foreground=t["muted"], background=t["surface2"], lmargin1=26,
                                 lmargin2=26, rmargin=20, spacing1=0, spacing3=0),
                "card_title": dict(font=F["ui_bold"], foreground=t["text"], background=mix(t["warning"], t["canvas_chat"], 0.86),
                                   lmargin1=12, lmargin2=12, spacing1=8, spacing3=4),
                "card_body": dict(font=F["mono_small"], foreground=t["text"], background=mix(t["warning"], t["canvas_chat"], 0.92),
                                  lmargin1=12, lmargin2=12, rmargin=20, spacing1=0, spacing3=0),
                "card_done": dict(font=F["small"], foreground=t["muted"], lmargin1=12, spacing1=2, spacing3=6),
                "notice": dict(font=F["small"], foreground=t["muted"], lmargin1=0, spacing1=6, spacing3=6),
                "error": dict(font=F["ui"], foreground=t["danger"], spacing1=6, spacing3=6),
                "sec_head": dict(font=F["ui_bold"], foreground=t["text"], background=t["surface2"], lmargin1=8,
                                 lmargin2=8, spacing1=6, spacing3=6),
                "sec_meta": dict(font=F["small"], foreground=t["muted"]),
                "model_head": dict(font=F["ui_bold"], foreground=t["text"], lmargin1=14, spacing1=8, spacing3=2),
                "final_head": dict(font=F["h2"], foreground=t["accent"], spacing1=14, spacing3=6),
                "progress": dict(font=F["small"], foreground=t["muted"], spacing1=2, spacing3=2),
                "empty_title": dict(font=F["h1"], foreground=t["text"], justify="center", spacing1=60, spacing3=8),
                "empty_body": dict(font=F["content"], foreground=t["muted"], justify="center", spacing3=4),
            }
            for name, opts in cfg.items():
                w.tag_configure(name, **opts)
            w.tag_configure("sep", elide=True)          # 區塊之間的分隔字元：不顯示、不佔空間
            for name in ("md_bold", "md_icode", "md_link", "tool_ok", "tool_bad", "tool_run", "sec_meta"):
                w.tag_raise(name)
            # v6.6.3：選取的顏色要蓋過訊息底色。以前「你」的訊息、程式碼、工具輸出都有底色，選取時看不出反白，像是不能選。
            w.tag_raise("sel")

        # ── Markdown ──
        def render_markdown(self, rid, md, extra=()):
            in_code = False
            lines = (md or "").replace("\r\n", "\n").strip("\n").split("\n")
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("```"):
                    in_code = not in_code
                    continue
                if in_code:
                    self.write(rid, line + "\n", ("md_code",) + extra)
                    continue
                m = re.match(r"(#{1,6})\s+(.*)", stripped)
                if m:
                    level = len(m.group(1))
                    self._inline(rid, m.group(2), ("md_h1" if level == 1 else "md_h2" if level == 2 else "md_h3",) + extra)
                elif re.match(r"^\s*([-*_])\s*\1\s*\1[\s\1]*$", line):
                    self.write(rid, "─" * 40, ("md_hr",) + extra)
                elif re.match(r"[-*+]\s+", stripped):
                    indent = len(line) - len(line.lstrip())
                    tag = "md_li2" if indent >= 2 else "md_li"
                    self.write(rid, "•  ", (tag,) + extra)
                    self._inline(rid, re.sub(r"^[-*+]\s+", "", stripped), (tag,) + extra)
                elif re.match(r"\d+[.)]\s+", stripped):
                    indent = len(line) - len(line.lstrip())
                    tag = "md_li2" if indent >= 2 else "md_li"
                    num = re.match(r"(\d+[.)])\s+", stripped)
                    self.write(rid, num.group(1) + " ", (tag,) + extra)
                    self._inline(rid, stripped[num.end():], (tag,) + extra)
                elif stripped.startswith(">"):
                    self._inline(rid, "▍ " + stripped.lstrip("> "), ("md_quote",) + extra)
                elif stripped.startswith("|") and stripped.endswith("|"):
                    if re.fullmatch(r"\|?[\s:|-]+\|?", stripped):
                        continue
                    cells = [c.strip() for c in stripped.strip("|").split("|")]
                    self.write(rid, "  " + "  │  ".join(cells), ("md_table",) + extra)
                else:
                    self._inline(rid, line, ("md_p",) + extra)
                self.write(rid, "\n", ("md_p",) + extra)

        def _inline(self, rid, text, tags):
            pos = 0
            for m in INLINE_MD.finditer(text):
                if m.start() > pos:
                    self.write(rid, text[pos:m.start()], tags)
                token = m.group(0)
                if token.startswith("**"):
                    self.write(rid, token[2:-2], tags + ("md_bold",))
                elif token.startswith("`"):
                    self.write(rid, token[1:-1], tags + ("md_icode",))
                else:
                    label = re.match(r"\[([^\]]+)\]", token).group(1)
                    self.write(rid, label, tags + ("md_link",))
                pos = m.end()
            if pos < len(text):
                self.write(rid, text[pos:], tags)

        # ── 高階元件 ──
        def empty_state(self, title, lines):
            rid = self.region()
            self.write(rid, title + "\n", "empty_title")
            for line in lines:
                self.write(rid, line + "\n", "empty_body")
            return rid

        def user_message(self, text):
            rid = self.region()
            self.write(rid, "你\n", "who_user")
            self.write(rid, text.strip() + "\n", "user_text")
            self.scroll_end(force=True)
            return rid

        def assistant_message(self, who):
            rid = self.region()
            self._follow = True
            self.write(rid, who + "\n", "who")
            body = self.region(rid)
            return body

        def finish_markdown(self, body, md):
            self.clear_region(body)
            if md.strip():
                self.render_markdown(body, md)

        def notice(self, text, kind="notice"):
            rid = self.region()
            self.write(rid, text + "\n", kind)
            return rid

        def tool_card(self, title, icon="•"):
            rid = self.region(prefix="t")
            self._follow = True
            head = self.region(rid)
            body = self.region(rid)
            self.set_collapsible(body, True)
            tag = f"{head}_click"
            self.write(head, f"  ▸ {icon}  ", ("tool_head", tag))
            self.write(head, title, ("tool_head", tag))
            status = self.region(head, nl_tags=("tool_head", tag))
            self.write(head, "\n", ("tool_head", tag))
            self.clickable(tag, lambda: self._toggle_tool(head, body))
            return {"rid": rid, "head": head, "status": status, "body": body, "tag": tag}

        def _toggle_tool(self, head, body):
            if self.elided.get(body, False) and body in self.on_open:
                try:
                    self.on_open[body]()
                except Exception:
                    log_app.exception("展開區塊失敗")
            opened = self.toggle(body)
            ranges = self.text.tag_ranges(f"{head}_click")
            if ranges:
                start = ranges[0]
                arrow_idx = self.text.search("▸" if opened else "▾", start, f"{start} lineend")
                if arrow_idx:
                    self.text.delete(arrow_idx)
                    self.text.insert(arrow_idx, "▾" if opened else "▸", ("tool_head", f"{head}_click"))

        def set_tool_status(self, card, text, kind="tool_run"):
            self.clear_region(card["status"])
            self.write(card["status"], "   " + text, ("tool_head", kind, card["tag"]))

        def tool_output(self, card, text):
            body = card["body"]

            def fill():
                self.on_open.pop(body, None)
                self.clear_region(body)
                self.write(body, (text or "（沒有輸出）").rstrip() + "\n", "tool_out")

            if self.elided.get(body, False):
                self.clear_region(body)
                self.on_open[body] = fill
            else:
                fill()


    class AIWorkbench(tk.Tk):
        def __init__(self):
            super().__init__()
            self.withdraw()
            self.report_callback_exception = self._report_exception
            self.scale = max(1.0, min(2.5, self.winfo_fpixels("1i") / 96.0))
            self.title(f"{APP_NAME} {APP_VERSION}")
            try:                                   # 專屬圖示（原創 Q 版主持 AI 頭像）
                self._icons = [tk.PhotoImage(data=APP_ICON_PNG[n]) for n in (64, 32, 16)]
                self.iconphoto(True, *self._icons)
            except Exception:
                log_app.warning("設定視窗圖示失敗", exc_info=True)
            self.ui_state = load_ui_state()
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            w, h = min(int(1440 * self.scale), int(sw * 0.94)), min(int(900 * self.scale), int(sh * 0.9))
            geometry = self.ui_state.get("geometry") or ""
            m = re.fullmatch(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", geometry)
            if m and int(m.group(1)) <= sw + 50 and int(m.group(2)) <= sh + 50 \
                    and -100 < int(m.group(3)) < sw - 100 and -50 < int(m.group(4)) < sh - 100:
                self.geometry(geometry)
            else:
                self.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 3)}")
            self.minsize(int(900 * min(self.scale, sw / 1200)), int(560 * min(self.scale, sh / 760)))

            imported = ""
            if FROZEN:
                src = find_importable_settings()
                if src and messagebox.askyesno(APP_NAME, f"這是打包版第一次在這個資料夾啟動。\n\n"
                                               f"發現既有設定：\n{src}\n\n要沿用它（AI 團隊、偏好）嗎？"
                                               "\n（金鑰本體不會被複製，仍從環境變數讀取。）"):
                    if import_settings_from(src):
                        imported = src
            settings, warning = load_settings_file()
            self._imported_settings = imported
            self._settings_digest = settings_file_digest()     # 用來發現「另一個程式改過設定檔」
            self.instance_owner = True                         # main() 會依單一執行鎖改寫
            self.settings = settings
            self.services = settings["services"]
            fix_service_names(self.services)
            for s in self.services:
                s.setdefault("credential", s.get("credential_env", ""))
                if not s["credential"] and NVIDIA_HOST in s.get("url", "").lower():
                    s["credential"] = DEFAULT_NVIDIA_ENV
            self.prefs = settings["preferences"]
            self._apply_advanced_prefs()
            self.theme = Theme(self.prefs)
            self._tk_widgets = []
            self.model_cache = {}
            self.mcp = MCPManager()
            self._unattended = None           # 正在執行的排程（沒有人在旁邊核准）
            self._sched_running = None
            self._launched_schedule = None
            self.ui_queue = queue.Queue()
            self.active, self.active_lock = {}, threading.Lock()
            self.key_hints = {}
            self.editors = {}
            self.dirty = False
            self._graph_job = None
            self.busy = False
            self.token = None
            # Agent
            self.runner = None
            self.runner_key = None
            self.agent_body = None
            self.agent_buffer = []
            self.agent_text = ""
            self.tool_cards = {}
            self.cat_last_card = {}
            self.current_tool = None
            self.pending_cards = []
            self.agent_step = 0
            self.agent_usage = {}
            # AI 討論
            self.session = None              # 進行中的討論（Session 物件）
            self.cancel_event = None
            self.run = {}
            self.buffers = {}
            self.council_ui = None
            self.last_record = None
            self.last_record_path = ""
            self.expected = self.done_calls = 0
            self.usage = {}
            self.phase_text = ""
            self.run_started = 0.0
            self.call_started = {}

            self._init_fonts()
            self._style()
            self._build()
            self._refresh_templates()
            self._rebuild_editors()
            self._refresh_hub_choices()
            self._refresh_model_choices()
            self._apply_theme()
            self.refresh_sessions()
            self.new_conversation(self.prefs.get("new_chat_type", "agent"))
            self.protocol("WM_DELETE_WINDOW", self._on_close)
            for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                self.bind_all(seq, self._on_mousewheel, add="+")
            self.bind("<Control-s>", lambda _e: self.save_settings())
            self.bind("<Control-n>", lambda _e: self.new_conversation())
            self.bind("<Control-e>", lambda _e: self.export_conversation())
            self.bind("<Escape>", lambda _e: self.stop())
            self.bind("<F11>", lambda _e: self.toggle_panel())
            self.after(40, self._process_queue)
            self.after(300, self._install_file_drop)
            self.after(1000, self._tick)
            self.after(800, self.start_mcp)
            self._start_monitor()
            self.rd = None                      # 自主研發的狀態（沒有在跑時是 None）
            self.after(1500, self._report_interrupted)
            self.after(3000, self._check_schedule_paths)
            self.after(2000, self._report_previous_crash)
            self.after(10000, self._auto_update_check)
            self.after(6000, self._daily_health_check)
            self.deiconify()
            if self.ui_state.get("zoomed"):
                try:
                    self.state("zoomed")
                except tk.TclError:
                    pass
            if warning:
                self.after(300, lambda: messagebox.showwarning(APP_NAME, warning))

        # ───────────── 字體與主題 ─────────────
        def _font_sizes(self):
            size = int(self.prefs.get("font_size") or 10)
            rsize = int(self.prefs.get("reply_font_size") or 11)
            return {"ui": size - 1, "ui_bold": size - 1, "small": max(7, size - 2), "section": size,
                    "title": size + 3, "button": size - 1, "primary": size, "content": rsize, "content_bold": rsize,
                    "h1": rsize + 5, "h2": rsize + 3, "h3": rsize + 1, "mono": max(8, rsize - 1),
                    "mono_small": max(7, rsize - 2), "side": size - 1}

        def _init_fonts(self):
            self.fonts = {}
            for key in self._font_sizes():
                self.fonts[key] = tkfont.Font(self)
            self._update_fonts()

        def _update_fonts(self):
            fam = self.prefs.get("font_family") or DEFAULT_UI_FONT
            cfam = self.prefs.get("content_family") or fam
            bold = {"ui_bold", "section", "title", "primary", "content_bold", "h1", "h2", "h3"}
            for key, size in self._font_sizes().items():
                family = DEFAULT_MONO_FONT if key.startswith("mono") else (
                    cfam if key in ("content", "content_bold", "h1", "h2", "h3") else fam)
                self.fonts[key].configure(family=family, size=size, weight="bold" if key in bold else "normal")

        def _style(self):
            t, F = self.theme, self.fonts
            st = ttk.Style(self)
            st.theme_use("clam")
            st.configure(".", font=F["ui"], background=t["bg"], foreground=t["text"], bordercolor=t["border"],
                         lightcolor=t["surface"], darkcolor=t["surface"], troughcolor=t["surface2"],
                         focuscolor=t["accent"], selectbackground=t["accent_soft"], selectforeground=t["text"],
                         insertcolor=t["text"])
            st.configure("App.TFrame", background=t["bg"])
            st.configure("Surface.TFrame", background=t["surface"])
            for name in ("Card.TFrame", "Bar.TFrame"):
                st.configure(name, background=t["surface"], relief="solid", borderwidth=1, bordercolor=t["border"],
                             lightcolor=t["border"], darkcolor=t["border"])
            st.configure("Title.TLabel", background=t["surface"], foreground=t["text"], font=F["title"])
            st.configure("Sub.TLabel", background=t["surface"], foreground=t["muted"], font=F["small"])
            st.configure("Section.TLabel", background=t["surface"], foreground=t["text"], font=F["section"])
            st.configure("Muted.TLabel", background=t["surface"], foreground=t["muted"], font=F["ui"])
            st.configure("Value.TLabel", background=t["surface"], foreground=t["text"], font=F["ui"])
            st.configure("Card.TFrame", background=t["surface"], bordercolor=t["border"], relief="solid", borderwidth=1)
            st.configure("BgMuted.TLabel", background=t["bg"], foreground=t["muted"], font=F["small"])
            st.configure("TButton", background=t["surface"], foreground=t["text"], bordercolor=t["border"],
                         lightcolor=t["surface"], darkcolor=t["surface"], borderwidth=1, relief="flat",
                         padding=(10, 5), font=F["button"], focusthickness=0)
            st.map("TButton", background=[("active", t["hover"]), ("disabled", t["surface2"])],
                   foreground=[("disabled", t["muted"])], bordercolor=[("active", t["accent"])])
            st.configure("Ghost.TButton", background=t["surface"], bordercolor=t["border"], padding=(8, 3))
            st.map("Ghost.TButton", background=[("active", t["hover"])], foreground=[("disabled", t["muted"])],
                   bordercolor=[("active", t["accent"])])
            st.configure("Primary.TButton", background=t["accent"], foreground="#FFFFFF", bordercolor=t["accent"],
                         lightcolor=t["accent"], darkcolor=t["accent"], font=F["primary"], padding=(18, 9))
            st.map("Primary.TButton", background=[("active", t["accent_hover"]), ("disabled", mix(t["accent"], t["surface"], 0.55))],
                   bordercolor=[("active", t["accent_hover"])], foreground=[("disabled", "#FFFFFF")])
            st.configure("Danger.TButton", background=mix(t["danger"], t["surface"], 0.9), foreground=t["danger"],
                         bordercolor=mix(t["danger"], t["surface"], 0.7), padding=(8, 4))
            st.map("Danger.TButton", background=[("active", mix(t["danger"], t["surface"], 0.8)), ("disabled", t["surface2"])],
                   foreground=[("disabled", t["muted"])])
            st.configure("Tab.TButton", background=t["surface"], foreground=t["muted"], bordercolor=t["surface"],
                         lightcolor=t["surface"], darkcolor=t["surface"], padding=(8, 5), font=F["ui_bold"])
            st.map("Tab.TButton", background=[("active", t["hover"])], foreground=[("active", t["text"])])
            st.configure("TabOn.TButton", background=t["accent_soft"], foreground=t["accent"],
                         bordercolor=t["accent_soft"], lightcolor=t["accent_soft"], darkcolor=t["accent_soft"],
                         padding=(8, 5), font=F["ui_bold"])
            st.map("TabOn.TButton", background=[("active", t["accent_soft"])])
            for name in ("TEntry", "TCombobox", "TSpinbox"):
                st.configure(name, padding=5, fieldbackground=t["surface2"], foreground=t["text"],
                             bordercolor=t["border"], lightcolor=t["surface2"], darkcolor=t["surface2"],
                             arrowcolor=t["muted"], background=t["surface"], insertcolor=t["text"])
                st.map(name, bordercolor=[("focus", t["accent"])], lightcolor=[("focus", t["accent"])],
                       fieldbackground=[("readonly", t["surface2"]), ("disabled", t["surface"])],
                       foreground=[("disabled", t["muted"])])
            self.option_add("*TCombobox*Listbox.background", t["surface"])
            self.option_add("*TCombobox*Listbox.foreground", t["text"])
            self.option_add("*TCombobox*Listbox.selectBackground", t["accent_soft"])
            self.option_add("*TCombobox*Listbox.selectForeground", t["text"])
            self.option_add("*TCombobox*Listbox.font", F["ui"])
            for name in ("TCheckbutton", "TRadiobutton"):
                st.configure(name, background=t["surface"], foreground=t["text"], indicatorbackground=t["surface2"],
                             indicatorforeground=t["accent"], font=F["ui"])
                st.map(name, background=[("active", t["surface"])], indicatorbackground=[("selected", t["accent_soft"])])
            st.configure("Horizontal.TProgressbar", troughcolor=t["surface2"], background=t["accent"],
                         bordercolor=t["surface2"], lightcolor=t["accent"], darkcolor=t["accent"])
            st.configure("TScrollbar", background=t["surface2"], troughcolor=t["surface"], bordercolor=t["surface"],
                         arrowcolor=t["muted"], lightcolor=t["surface2"], darkcolor=t["surface2"], arrowsize=11)
            st.map("TScrollbar", background=[("active", t["line"])])
            st.configure("TPanedwindow", background=t["bg"])
            st.configure("Sash", sashthickness=6, gripcount=0, background=t["bg"])


        def _style_extra(self):
            t, F = self.theme, self.fonts
            st = ttk.Style(self)
            side = t["side"]
            st.configure("Side.TFrame", background=side)
            st.configure("Chat.TFrame", background=t["canvas_chat"])
            st.configure("Header.TFrame", background=t["canvas_chat"])
            st.configure("Line.TFrame", background=t["border"])
            st.configure("Graph.TFrame", background=t["canvas"])
            for tv in ("Picker.Treeview", "Files.Treeview"):
                st.configure(tv, background=t["surface"] if tv == "Picker.Treeview" else t["side"],
                             fieldbackground=t["surface"] if tv == "Picker.Treeview" else t["side"],
                             foreground=t["text"], bordercolor=t["border"], borderwidth=0, font=F["ui"],
                             rowheight=int(F["ui"].metrics("linespace") * 1.45))
                st.map(tv, background=[("selected", t["accent_soft"])], foreground=[("selected", t["text"])])
            st.configure("Treeview.Heading", background=t["surface2"], foreground=t["muted"], font=F["small"],
                         bordercolor=t["border"], relief="flat")
            st.configure("GraphBold.TLabel", background=t["canvas"], foreground=t["text"], font=F["ui_bold"])
            st.configure("GraphMuted.TLabel", background=t["canvas"], foreground=t["muted"], font=F["small"])
            st.configure("Graph.TCheckbutton", background=t["canvas"], foreground=t["text"], font=F["small"])
            st.map("Graph.TCheckbutton", background=[("active", t["canvas"])])
            st.configure("SideTitle.TLabel", background=side, foreground=t["text"], font=F["title"])
            st.configure("SideMuted.TLabel", background=side, foreground=t["muted"], font=F["small"])
            st.configure("HeaderTitle.TLabel", background=t["canvas_chat"], foreground=t["text"], font=F["section"])
            st.configure("HeaderMuted.TLabel", background=t["canvas_chat"], foreground=t["muted"], font=F["small"])
            st.configure("Status.TLabel", background=t["canvas_chat"], foreground=t["muted"], font=F["small"])
            st.configure("Side.TButton", background=side, foreground=t["text"], bordercolor=side, lightcolor=side,
                         darkcolor=side, anchor="w", padding=(10, 6), font=F["ui"])
            st.map("Side.TButton", background=[("active", t["hover"])], bordercolor=[("active", t["hover"])])
            st.configure("New.TButton", background=t["accent"], foreground="#FFFFFF", bordercolor=t["accent"],
                         lightcolor=t["accent"], darkcolor=t["accent"], padding=(10, 8), font=F["ui_bold"])
            st.map("New.TButton", background=[("active", t["accent_hover"])])
            for name, bg, fg in (("Seg.TButton", t["surface"], t["muted"]), ("SegOn.TButton", t["accent_soft"], t["accent"])):
                st.configure(name, background=bg, foreground=fg, bordercolor=t["border"], lightcolor=bg, darkcolor=bg,
                             padding=(10, 4), font=F["ui_bold"])
                st.map(name, background=[("active", t["hover"] if name == "Seg.TButton" else bg)])
            st.configure("Composer.TFrame", background=t["surface"], relief="solid", borderwidth=1,
                         bordercolor=t["border"], lightcolor=t["border"], darkcolor=t["border"])
            st.configure("Icon.TButton", background=t["surface"], foreground=t["muted"], bordercolor=t["surface"],
                         lightcolor=t["surface"], darkcolor=t["surface"], padding=(6, 3), font=F["ui"])
            st.map("Icon.TButton", background=[("active", t["hover"])], foreground=[("active", t["text"])])
            st.configure("HeaderIcon.TButton", background=t["canvas_chat"], foreground=t["muted"],
                         bordercolor=t["border"], lightcolor=t["canvas_chat"], darkcolor=t["canvas_chat"],
                         padding=(8, 4), font=F["ui"])
            st.map("HeaderIcon.TButton", background=[("active", t["hover"])], foreground=[("active", t["text"])])
            st.configure("Chip.TButton", background=t["surface2"], foreground=t["text"], bordercolor=t["border"],
                         lightcolor=t["surface2"], darkcolor=t["surface2"], padding=(10, 4), font=F["ui"])
            st.map("Chip.TButton", background=[("active", t["hover"])], bordercolor=[("active", t["accent"])])
            st.configure("Ghost.TButton", background=t["surface2"], bordercolor=t["border"], lightcolor=t["surface2"],
                         darkcolor=t["surface2"], padding=(8, 3))
            st.map("Ghost.TButton", background=[("active", t["hover"])], bordercolor=[("active", t["accent"])])
            st.configure("Panel.TFrame", background=t["side"])
            st.configure("PanelLink.TLabel", background=t["side"], foreground=t["accent"], font=F["small"])
            st.configure("Panel.TNotebook", background=t["side"], borderwidth=0, tabmargins=(0, 0, 0, 0))
            st.configure("Panel.TNotebook.Tab", background=t["side"], foreground=t["muted"], padding=(10, 5),
                         font=F["ui_bold"], borderwidth=0)
            st.map("Panel.TNotebook.Tab", background=[("selected", t["surface"])], foreground=[("selected", t["accent"])])
            st.configure("Panel.TMenubutton", background=t["surface"], foreground=t["text"], bordercolor=t["border"],
                         arrowcolor=t["muted"], font=F["small"], padding=(8, 4))
            st.map("Panel.TMenubutton", background=[("active", t["hover"])])
            st.configure("PanelTitle.TLabel", background=t["side"], foreground=t["text"], font=F["ui_bold"])
            st.configure("PanelText.TLabel", background=t["side"], foreground=t["text"], font=F["small"])
            st.configure("PanelMuted.TLabel", background=t["side"], foreground=t["muted"], font=F["small"])
            st.configure("Panel.TButton", background=t["surface"], foreground=t["text"], bordercolor=t["border"],
                         padding=(8, 3), font=F["small"])
            st.map("Panel.TButton", background=[("active", t["hover"])])

        def _register_tk(self, widget, kind):
            self._tk_widgets.append((widget, kind))
            self._theme_widget(widget, kind)
            return widget


        def _theme_widget(self, widget, kind):
            t = self.theme
            try:
                if kind == "text":
                    widget.configure(bg=t["surface2"], fg=t["text"], insertbackground=t["text"],
                                     highlightbackground=t["border"], highlightcolor=t["accent"],
                                     selectbackground=t["accent_soft"], selectforeground=t["text"],
                                     font=self.fonts["content"])
                elif kind == "composer":
                    widget.configure(bg=t["surface"], fg=t["text"], insertbackground=t["text"],
                                     selectbackground=t["accent_soft"], selectforeground=t["text"],
                                     font=self.fonts["content"], highlightthickness=0)
                elif kind == "chat":
                    widget.configure(bg=t["canvas_chat"], fg=t["text"], selectbackground=t["accent_soft"],
                                     selectforeground=t["text"], inactiveselectbackground=t["accent_soft"],
                                     font=self.fonts["content"], insertbackground=t["canvas_chat"])
                elif kind == "listbox":
                    widget.configure(bg=t["surface2"], fg=t["text"], highlightbackground=t["border"],
                                     highlightcolor=t["accent"], selectbackground=t["accent_soft"],
                                     selectforeground=t["text"], font=self.fonts["ui"])
                elif kind == "surface":
                    widget.configure(bg=t["surface"])
                elif kind == "side":
                    widget.configure(bg=t["side"])
                elif kind == "chatbg":
                    widget.configure(bg=t["canvas_chat"])
            except tk.TclError:
                pass

        def _apply_theme(self):
            self.theme.update(self.prefs)
            self._update_fonts()
            self._style()
            self._style_extra()
            self.configure(bg=self.theme["bg"])
            alive = []
            for widget, kind in self._tk_widgets:
                try:
                    if widget.winfo_exists():
                        self._theme_widget(widget, kind)
                        alive.append((widget, kind))
                except tk.TclError:
                    pass
            self._tk_widgets = alive
            self._draw_logo()
            self.transcript.configure_tags()
            self.graph.set_theme(self.theme, self.fonts["ui"].cget("family"))
            for editor in self.editors.values():
                editor.paint_dot()
            if hasattr(self, "swatches"):
                self._refresh_swatches()
            self.refresh_sessions()
            self._update_mode_buttons()
            if getattr(self, "_parts_args", None):           # 參與者清單是 tk 元件，換主題時重建
                states = {pid: self.graph.states.get(pid) for pid in self.part_rows}
                details = {pid: self.graph.details.get(pid, "") for pid in self.part_rows}
                self._build_parts(*self._parts_args)
                for pid, st in states.items():
                    if st:
                        self._set_state(pid, st, details.get(pid, ""))

        def _text(self, parent, height=10, readonly=True):
            frame = ttk.Frame(parent, style="Surface.TFrame")
            text = tk.Text(frame, height=height, wrap="word", relief="flat", bd=0, padx=12, pady=10,
                           undo=not readonly, highlightthickness=1, spacing1=2, spacing3=2)
            self._register_tk(text, "text")
            bar = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
            text.configure(yscrollcommand=bar.set)
            text.pack(side="left", fill="both", expand=True)
            bar.pack(side="right", fill="y")
            if readonly:
                text.configure(state="disabled")
            return frame, text

        @staticmethod
        def _set_text(widget, value):
            state = widget.cget("state")
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            widget.insert("1.0", value or "")
            widget.configure(state=state)


        # ───────────── 版面 ─────────────
        def _build(self):
            root = ttk.Frame(self, style="App.TFrame")
            root.pack(fill="both", expand=True)
            # 左：對話清單
            compact = self.winfo_screenwidth() < 1500 * self.scale
            self.sidebar = ttk.Frame(root, style="Side.TFrame", width=int((215 if compact else 250) * self.scale))
            self.sidebar.pack(side="left", fill="y")
            self.sidebar.pack_propagate(False)
            ttk.Frame(root, style="Line.TFrame", width=1).pack(side="left", fill="y")
            self._build_sidebar(self.sidebar)
            # 右：任務清單／變更的檔案（或討論流程圖）
            self.panel = ttk.Frame(root, style="Panel.TFrame", width=int((260 if compact else 300) * self.scale))
            self.panel_line = ttk.Frame(root, style="Line.TFrame", width=1)
            self.panel.pack(side="right", fill="y")
            self.panel_line.pack(side="right", fill="y")
            self.panel.pack_propagate(False)
            self.panel_visible = True
            self._build_panel(self.panel)
            # 中：標題列、對話串、狀態列、輸入框
            main = ttk.Frame(root, style="Chat.TFrame")
            main.pack(side="left", fill="both", expand=True)
            self.main = main
            self.header = ttk.Frame(main, style="Header.TFrame", padding=(18, 10))
            self.header.pack(fill="x")
            self._build_header(self.header)
            ttk.Frame(main, style="Line.TFrame", height=1).pack(fill="x")
            bottom = ttk.Frame(main, style="Chat.TFrame", padding=(28, 6, 28, 14))
            bottom.pack(side="bottom", fill="x")
            self._build_composer(bottom)
            # 中央：上方是協作拓樸圖（Agent 與工具／各 AI 機器人），下方是對話串；中間分隔線可上下拖曳
            self.center = ttk.Panedwindow(main, orient="vertical")
            self.center.pack(fill="both", expand=True)
            self.graph_frame = ttk.Frame(self.center, style="Chat.TFrame")
            self.graph = TopologyView(self.graph_frame, self.theme, self.fonts["ui"].cget("family"), scale=self.scale,
                                      callbacks={"select": self._on_graph_select, "open": self._on_graph_open,
                                                 "menu": self._robot_menu})
            team_bar = ttk.Frame(self.graph_frame, style="Graph.TFrame", padding=(12, 4, 12, 0))
            team_bar.pack(side="top", fill="x")
            ttk.Label(team_bar, text="AI 團隊", style="GraphBold.TLabel").pack(side="left")
            self.team_spin = ttk.Spinbox(team_bar, from_=1, to=MAX_AGENTS, width=3, textvariable=self.count_var,
                                         command=self._on_count_changed)
            self.team_spin.pack(side="left", padx=(6, 2))
            self.team_spin.bind("<Return>", lambda _e: self._on_count_changed())
            ttk.Label(team_bar, text="位", style="GraphMuted.TLabel").pack(side="left")
            ttk.Button(team_bar, text="＋ 新增", style="Chip.TButton", command=self._add_robot).pack(side="left", padx=(10, 0))
            ttk.Button(team_bar, text="★ 依身分套用推薦", style="Chip.TButton",
                       command=self.apply_role_defaults).pack(side="left", padx=(6, 0))
            ttk.Button(team_bar, text="＋ Claude Code／Codex", style="Chip.TButton",
                       command=self.open_cli_dialog).pack(side="left", padx=(6, 0))
            self.web_research_var = tk.BooleanVar(value=self.prefs.get("web_research", True))
            self.web_research_check = ttk.Checkbutton(team_bar, text="討論前上網查證", variable=self.web_research_var,
                                                      style="Graph.TCheckbutton", command=self._on_web_research)
            self.web_research_check.pack(side="left", padx=(14, 0))
            ttk.Label(team_bar, text="點機器人換模型（從環境變數的金鑰抓清單）・雙擊開完整設定",
                      style="GraphMuted.TLabel").pack(side="right")
            self.graph.pack(fill="both", expand=True)
            self.transcript = Transcript(self, self.center)
            self.center.add(self.graph_frame, weight=2)
            self.center.add(self.transcript.frame, weight=3)
            self.graph_visible = True
            self._center_ready = False

            def place_center(_e=None):
                height = self.center.winfo_height()
                if not self._center_ready and height > 300 and self.graph_visible:
                    short = self.winfo_screenheight() < 900 * self.scale
                    ratio = float(self.ui_state.get("graph_ratio") or (0.52 if short else 0.46))
                    self.center.sashpos(0, int(height * min(0.75, max(0.2, ratio))))
                    self._center_ready = self.center.sashpos(0) > 0

            self.center.bind("<Configure>", place_center, add="+")

        def _build_sidebar(self, side):
            top = ttk.Frame(side, style="Side.TFrame", padding=(14, 14, 14, 8))
            top.pack(fill="x")
            self.logo = tk.Canvas(top, width=36, height=36, highlightthickness=0)
            self._register_tk(self.logo, "side")
            self.logo.pack(side="left")
            ttk.Label(top, text=" AI 協作", style="SideTitle.TLabel").pack(side="left")
            box = ttk.Frame(side, style="Side.TFrame", padding=(12, 4))
            box.pack(fill="x")
            ttk.Button(box, text="＋  新對話", style="New.TButton", command=lambda: self.new_conversation()).pack(fill="x")
            seg = ttk.Frame(box, style="Side.TFrame")
            seg.pack(fill="x", pady=(8, 0))
            seg.columnconfigure(0, weight=1)
            seg.columnconfigure(1, weight=1)
            self.kind_buttons = {}
            for i, (kind, label) in enumerate((("agent", "◆ Agent"), ("council", "◇ AI 討論"))):
                b = ttk.Button(seg, text=label, style="Seg.TButton", command=lambda k=kind: self.new_conversation(k))
                b.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 2, 0))
                self.kind_buttons[kind] = b
            ttk.Label(side, text="  最近的對話", style="SideMuted.TLabel").pack(anchor="w", padx=12, pady=(14, 2))
            self.session_query = tk.StringVar()
            search = ttk.Entry(side, textvariable=self.session_query)
            search.pack(fill="x", padx=(14, 12), pady=(0, 4))
            self._search_job = None

            def on_search(*_a):
                if self._search_job:
                    self.after_cancel(self._search_job)
                self._search_job = self.after(300, self.refresh_sessions)

            self.session_query.trace_add("write", on_search)
            self._placeholder(search, self.session_query, "搜尋對話（標題與內容）")
            bottom = ttk.Frame(side, style="Side.TFrame", padding=(10, 8))
            bottom.pack(side="bottom", fill="x")
            ttk.Button(bottom, text="⚙  設定", style="Side.TButton", command=self.open_settings).pack(fill="x")
            ttk.Button(bottom, text="▣  紀錄資料夾", style="Side.TButton",
                       command=lambda: self._open_dir(RECORDS_DIR)).pack(fill="x")
            self.session_scroll = ScrollFrame(self, side)
            self.session_scroll.configure(style="Side.TFrame")
            self.session_scroll.inner.configure(style="Side.TFrame")
            self._register_tk(self.session_scroll.canvas, "side")
            self.session_scroll.pack(fill="both", expand=True, padx=(6, 0))

        def refresh_sessions(self):
            if not hasattr(self, "session_scroll"):
                return
            inner = self.session_scroll.inner
            for child in inner.winfo_children():
                child.destroy()
            t = self.theme
            current = getattr(self, "conv", {}).get("id") if hasattr(self, "conv") else None
            q = self.session_query.get().strip() if hasattr(self, "session_query") else ""
            if q == getattr(self, "_placeholder_text", {}).get("session"):
                q = ""
            rows = search_sessions(q) if q else list_sessions()[:200]
            for sid, title, kind, updated in rows:
                active = sid == current
                bg = t["accent_soft"] if active else t["side"]
                row = tk.Frame(inner, bg=bg, cursor="hand2")
                row.pack(fill="x", padx=(6, 8), pady=1)
                icon = "◆" if kind == "agent" else "◇"
                lab = tk.Label(row, text=f"{icon}  {title[:22]}", anchor="w", bg=bg, fg=t["text"],
                               font=self.fonts["side"], padx=8, pady=5)
                lab.pack(fill="x")
                sub = tk.Label(row, text=updated[5:16], anchor="w", bg=bg, fg=t["muted"], font=self.fonts["small"], padx=30)
                sub.pack(fill="x")
                for w in (row, lab, sub):
                    w.bind("<Button-1>", lambda _e, s=sid: self.open_conversation(s))
                    w.bind("<Button-3>", lambda e, s=sid, ti=title: self._session_menu(e, s, ti))
                    if not active:
                        w.bind("<Enter>", lambda _e, r=row: self._hover_row(r, True))
                        w.bind("<Leave>", lambda _e, r=row: self._hover_row(r, False))
            if not inner.winfo_children():
                tk.Label(inner, text="找不到符合的對話" if q else "還沒有對話", bg=t["side"], fg=t["muted"],
                         font=self.fonts["small"]).pack(pady=10)

        def _hover_row(self, row, on):
            color = self.theme["hover"] if on else self.theme["side"]
            try:
                row.configure(bg=color)
                for child in row.winfo_children():
                    child.configure(bg=color)
            except tk.TclError:
                pass

        def _session_menu(self, event, sid, title):
            t = self.theme
            menu = tk.Menu(self, tearoff=0, font=self.fonts["ui"], bg=t["surface"], fg=t["text"],
                           activebackground=t["accent_soft"], activeforeground=t["text"])
            menu.add_command(label="重新命名…", command=lambda: self._rename_session(sid, title))
            menu.add_command(label="匯出成 Markdown…", command=lambda: self.export_conversation(sid))
            menu.add_command(label="匯出成 HTML…", command=lambda: self.export_conversation_as(sid, "html"))
            menu.add_command(label="匯出成 PDF…", command=lambda: self.export_conversation_as(sid, "pdf"))
            menu.add_command(label="發到 GitHub Issue…", command=lambda: self.export_conversation_as(sid, "issue"))
            menu.add_command(label="封存（移到 工作階段/封存，不刪除）", command=lambda: self._archive(sid))
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        def _placeholder(self, entry, var, text):
            """輸入框的灰色提示字（沒有內容時顯示）。"""
            self._placeholder_text = getattr(self, "_placeholder_text", {})
            self._placeholder_text["session"] = text

            def show(_e=None):
                if not var.get():
                    var.set(text)
                    entry.configure(foreground=self.theme["muted"])

            def hide(_e=None):
                if var.get() == text:
                    var.set("")
                entry.configure(foreground=self.theme["text"])

            entry.bind("<FocusIn>", hide)
            entry.bind("<FocusOut>", show)
            show()

        def export_conversation(self, sid=None):
            sid = sid or self.conv.get("id")
            try:
                data = self.conv if self.conv.get("id") == sid else load_session(sid)
            except (OSError, ValueError) as exc:
                messagebox.showerror(APP_NAME, f"讀不到這個對話：{exc}")
                return
            safe = re.sub(r'[\\/:*?"<>|]', "_", data.get("title") or "對話")[:40]
            path = filedialog.asksaveasfilename(title="匯出成 Markdown", defaultextension=".md",
                                                initialfile=f"{safe}.md", filetypes=[("Markdown", "*.md")])
            if path:
                self._write_file(path, session_to_markdown(data))

        def _rename_session(self, sid, title):
            name = simpledialog.askstring("重新命名", "新的名稱：", initialvalue=title, parent=self)
            if not name:
                return
            data = self.conv if self.conv.get("id") == sid else load_session(sid)
            data["title"] = name.strip()[:60]
            save_session(data)
            self.refresh_sessions()
            self._update_header()

        def _archive(self, sid):
            if self.busy and self.conv.get("id") == sid:
                return
            archive_session(sid)
            if self.conv.get("id") == sid:
                self.new_conversation(self.conv.get("type", "agent"))
            self.refresh_sessions()

        def _build_header(self, bar):
            self.header_title = ttk.Label(bar, text="新對話", style="HeaderTitle.TLabel")
            self.header_title.pack(side="left")
            self.header_sub = ttk.Label(bar, text="", style="HeaderMuted.TLabel")
            self.header_sub.pack(side="left", padx=(10, 0))
            ttk.Button(bar, text="☰", width=3, style="HeaderIcon.TButton", command=self.toggle_panel).pack(side="right")
            ttk.Button(bar, text="🧪 訓練工作室", style="HeaderIcon.TButton", command=self.open_training_studio).pack(side="right")
            ttk.Button(bar, text="📏 正確率實測", style="HeaderIcon.TButton", command=self.open_bench).pack(side="right")
            self.graph_button = ttk.Button(bar, text="◎ 收起圖", style="HeaderIcon.TButton", command=self.show_graph)
            self.graph_button.pack(side="right", padx=(0, 6))
            # Agent 專用
            self.agent_bar = ttk.Frame(bar, style="Header.TFrame")
            self.ws_button = ttk.Button(self.agent_bar, text="選擇工作資料夾", style="HeaderIcon.TButton",
                                        command=self.choose_workspace)
            self.ws_button.pack(side="left", padx=(0, 8))
            self.model_var = tk.StringVar()
            self.model_combo = ttk.Combobox(self.agent_bar, textvariable=self.model_var, state="readonly", width=12)
            self.model_combo.pack(side="left", padx=(0, 8))
            self.model_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_model_selected())
            self.mode_buttons = {}
            for key, label in (("plan", "規劃"), ("build", "執行")):
                b = ttk.Button(self.agent_bar, text=label, style="Seg.TButton", command=lambda k=key: self.set_agent_mode(k))
                b.pack(side="left")
                self.mode_buttons[key] = b
            ttk.Button(self.agent_bar, text="⟳ 自主研發", style="HeaderIcon.TButton",
                       command=self.open_rd_dialog).pack(side="left", padx=(8, 0))
            # AI 討論專用
            self.council_bar = ttk.Frame(bar, style="Header.TFrame")
            self.mode_var = tk.StringVar(value=self.prefs["mode"] if self.prefs["mode"] in MODES else MODE_SYNTH)
            cb = ttk.Combobox(self.council_bar, textvariable=self.mode_var, values=MODES, state="readonly", width=11)
            cb.pack(side="left", padx=(0, 8))
            cb.bind("<<ComboboxSelected>>", lambda _e: self._on_mode_changed())
            ttk.Label(self.council_bar, text="輪數", style="HeaderMuted.TLabel").pack(side="left")
            self.rounds_var = tk.StringVar(value=str(self.prefs.get("review_rounds", 1)))
            self.rounds_spin = ttk.Spinbox(self.council_bar, from_=1, to=5, width=3, textvariable=self.rounds_var,
                                           state="readonly", command=self._on_prefs_changed)
            self.rounds_spin.pack(side="left", padx=(4, 8))
            ttk.Label(self.council_bar, text="主持", style="HeaderMuted.TLabel").pack(side="left")
            self.hub_var = tk.StringVar()
            self.hub_combo = ttk.Combobox(self.council_bar, textvariable=self.hub_var, state="readonly", width=9)
            self.hub_combo.pack(side="left", padx=(4, 8))
            self.hub_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_hub_changed())
            ttk.Label(self.council_bar, text="AI 數", style="HeaderMuted.TLabel").pack(side="left")
            self.count_var = tk.StringVar(value=str(len(self.services)))
            spin = ttk.Spinbox(self.council_bar, from_=1, to=MAX_AGENTS, width=3, textvariable=self.count_var,
                               command=self._on_count_changed)
            spin.pack(side="left", padx=(4, 0))
            spin.configure(width=3)
            spin.bind("<Return>", lambda _e: self._on_count_changed())


        def _update_header(self):
            conv = self.conv
            title = conv.get("title") or "新對話"
            limit = 10 if self.winfo_width() < 1500 * self.scale else 22
            self.header_title.configure(text=title if len(title) <= limit else title[:limit - 1] + "…")
            if conv["type"] == "agent":
                self.council_bar.pack_forget()
                self.agent_bar.pack(side="right", padx=(0, 8))
                ws = conv.get("workspace")
                name = os.path.basename(ws.rstrip(os.sep)) or ws
                narrow = self.winfo_width() < 1500 * self.scale
                cut = 10 if narrow else 16
                self.ws_button.configure(text=("▣ " if narrow else "資料夾：") + (name if len(name) <= cut else name[:cut - 1] + "…")
                                         if ws else "選擇資料夾")
                self.header_sub.configure(text="" if ws else "尚未選擇工作資料夾")
            else:
                self.agent_bar.pack_forget()
                self.council_bar.pack(side="right", padx=(0, 8))
                n = len([s for s in self.services if s.get("enabled", True)])
                self.header_sub.configure(text="")
            self._update_mode_buttons()

        def _update_mode_buttons(self):
            if not hasattr(self, "conv"):
                return
            for key, b in self.mode_buttons.items():
                b.configure(style="SegOn.TButton" if self.conv.get("mode", "build") == key else "Seg.TButton")
            for key, b in self.kind_buttons.items():
                b.configure(style="SegOn.TButton" if self.conv.get("type") == key else "Seg.TButton")

        def _build_composer(self, parent):
            self.status_label = ttk.Label(parent, text="", style="Status.TLabel")
            self.status_label.pack(fill="x", pady=(0, 6))
            card = ttk.Frame(parent, style="Composer.TFrame", padding=(12, 10, 10, 8))
            card.pack(fill="x")
            lines = 3 if self.winfo_screenheight() >= 900 else 2
            self.prompt = tk.Text(card, height=lines, wrap="word", relief="flat", bd=0, undo=True, padx=4, pady=4)
            self._register_tk(self.prompt, "composer")
            self.prompt.pack(fill="x")
            self.prompt.bind("<Return>", self._on_enter)
            self.prompt.bind("<KeyRelease>", lambda _e: self._update_char_count())
            self.attach_images = []
            self.attach_bar = ttk.Frame(card, style="Surface.TFrame")          # 附加的圖片（有才顯示）
            row = ttk.Frame(card, style="Surface.TFrame")
            row.pack(fill="x", pady=(6, 0))
            self._attach_row = row
            ttk.Button(row, text="＋ 附加檔案", style="Icon.TButton", command=self.attach_files).pack(side="left")
            ttk.Button(row, text="📋 貼上圖片", style="Icon.TButton", command=self.paste_image).pack(side="left", padx=(4, 0))
            self.record_button = ttk.Button(row, text="🎤 錄音", style="Icon.TButton", command=self.toggle_recording)
            self.record_button.pack(side="left", padx=(4, 0))
            self.prompt.bind("<<Paste>>", self._on_paste)
            self.template_button = ttk.Button(row, text="範本 ▾", style="Icon.TButton", command=self._template_menu)
            self.template_button.pack(side="left", padx=(4, 0))
            self.char_label = ttk.Label(row, text="", style="Muted.TLabel")
            self.char_label.pack(side="left", padx=(10, 0))
            self.send_button = ttk.Button(row, text="送出  ➤", style="Primary.TButton", command=self.send)
            self.send_button.pack(side="right")
            self.skip_button = ttk.Button(row, text="⏭ 直接彙整", command=self.skip_to_synthesis)
            if self.winfo_screenheight() >= 900 * self.scale:     # 矮螢幕省略提示列，把高度留給拓樸圖與對話
                ttk.Label(parent, text="Enter 送出・Shift+Enter 換行・Esc 停止・Ctrl+N 新對話", style="Status.TLabel").pack(anchor="e", pady=(4, 0))

        def _on_enter(self, event):
            if event.state & 0x1:      # Shift+Enter → 換行
                return None
            self.send()
            return "break"

        # ───────────── 自主研發（v6.9.0）─────────────
        def open_rd_dialog(self):
            """設定自主研發：專案資料夾（自選）、方向、最多輪數、時間上限。"""
            if self.busy:
                messagebox.showinfo(APP_NAME, "目前還在執行中，請先停止或等它完成。")
                return
            win = tk.Toplevel(self)
            win.title("自主研發")
            win.transient(self)
            win.configure(bg=self.theme["surface"])
            body = ttk.Frame(win, style="Surface.TFrame", padding=(18, 16))
            body.pack(fill="both", expand=True)
            ttk.Label(body, text="讓 AI 自主推進專案研發", style="Title.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
            ttk.Label(body, text=("每一輪：盤點與提案 → 其他 AI 攻擊提案 → 回應攻擊並實作、跑測試 → 其他 AI 審查修改 → "
                                  "有嚴重問題就修正（最多 2 次）→ 記錄。記憶寫在專案的 .ai協作/ 資料夾（專案摘要、問題清單、研發計畫、研發日誌）。\n"
                                  "在這個資料夾裡會直接修改檔案與執行指令；刪除、覆寫、讀金鑰等高風險動作仍會先問你。改檔前會備份，可以復原。"),
                      style="Muted.TLabel", wraplength=int(520 * self.scale), justify="left").grid(
                row=1, column=0, columnspan=3, sticky="w", pady=(4, 12))
            folder = tk.StringVar(value=self.conv.get("workspace") or self.prefs.get("last_workspace", ""))
            ttk.Label(body, text="專案資料夾", style="Muted.TLabel").grid(row=2, column=0, sticky="w")
            ttk.Entry(body, textvariable=folder, width=46).grid(row=2, column=1, sticky="ew", padx=6)

            def pick():
                path = filedialog.askdirectory(title="選擇要自主研發的專案資料夾", initialdir=folder.get() or os.path.expanduser("~"),
                                               parent=win)
                if path:
                    folder.set(path)
            ttk.Button(body, text="選擇…", command=pick).grid(row=2, column=2)
            ttk.Label(body, text="研發方向（可空白）", style="Muted.TLabel").grid(row=3, column=0, sticky="nw", pady=(8, 0))
            goal = tk.Text(body, height=4, width=46, wrap="word")
            self._register_tk(goal, "text")
            goal.grid(row=3, column=1, columnspan=2, sticky="ew", padx=6, pady=(8, 0))
            goal.insert("1.0", self.prefs.get("rd_goal", ""))
            rounds = tk.StringVar(value=str(self.prefs.get("rd_rounds", 3)))
            minutes = tk.StringVar(value=str(self.prefs.get("rd_minutes", 60)))
            ttk.Label(body, text="最多輪數", style="Muted.TLabel").grid(row=4, column=0, sticky="w", pady=(8, 0))
            ttk.Spinbox(body, from_=1, to=100, textvariable=rounds, width=6).grid(row=4, column=1, sticky="w", padx=6, pady=(8, 0))
            ttk.Label(body, text="時間上限（分鐘）", style="Muted.TLabel").grid(row=5, column=0, sticky="w", pady=(6, 0))
            ttk.Spinbox(body, from_=5, to=1440, increment=5, textvariable=minutes, width=6).grid(row=5, column=1, sticky="w", padx=6, pady=(6, 0))
            main = self._service(self.conv.get("model_id"))
            attackers = [n for n, _e in self._rd_attackers(main, resolve=False)]
            ttk.Label(body, text=(f"Agent（提案、實作）：{short_model(main.get('model')) if main else '（右上角先選模型）'}\n"
                                  f"紅隊（攻擊、審查）：{'、'.join(attackers) or '（只有一個模型時由同一個模型扮演）'}\n"
                                  "要換紅隊，到設定勾選／取消各模型的「參與」。"),
                      style="Muted.TLabel", justify="left").grid(row=6, column=0, columnspan=3, sticky="w", pady=(10, 0))
            body.columnconfigure(1, weight=1)

            def go():
                try:
                    n, mins = int(rounds.get()), int(minutes.get())
                except ValueError:
                    messagebox.showerror(APP_NAME, "輪數與時間要填數字。", parent=win)
                    return
                path = folder.get().strip()
                if not path or not os.path.isdir(path):
                    messagebox.showerror(APP_NAME, "請選擇存在的專案資料夾。", parent=win)
                    return
                if not main:
                    messagebox.showinfo(APP_NAME, "請先在右上角選擇 Agent 的模型。", parent=win)
                    return
                text = goal.get("1.0", "end-1c").strip()
                self.prefs.update(rd_goal=text, rd_rounds=max(1, min(100, n)), rd_minutes=max(5, min(1440, mins)))
                win.destroy()
                self.start_rd(path, text, max(1, min(100, n)), max(5, min(1440, mins)))
            row = ttk.Frame(body, style="Surface.TFrame")
            row.grid(row=7, column=0, columnspan=3, sticky="e", pady=(14, 0))
            ttk.Button(row, text="取消", command=win.destroy).pack(side="right")
            ttk.Button(row, text="開始", style="Primary.TButton", command=go).pack(side="right", padx=(0, 8))
            win.grab_set()

        def _rd_attackers(self, main, resolve=True):
            """紅隊：有勾「參與」、且不是 Agent 主模型的 AI；沒有其他 AI 時由主模型自己扮演。"""
            team = [s for s in self.services if s.get("enabled", True) and (not main or s.get("id") != main.get("id"))]
            team = (team or ([main] if main else []))[:4]
            out = []
            for s in team:
                name = short_model(s.get("model")) or s.get("name") or "AI"
                if not resolve:
                    out.append((name, None))
                    continue
                endpoint, err = self._resolve(s)
                if not err:
                    out.append((name, endpoint))
            return out

        def start_rd(self, folder, goal, rounds, minutes):
            model_id = self.conv.get("model_id")
            self.new_conversation("agent")
            self.conv["model_id"] = model_id or self.conv.get("model_id")
            self.set_workspace(folder)
            if os.path.normcase(os.path.abspath(self.conv.get("workspace") or "")) != os.path.normcase(os.path.abspath(folder)):
                return                                     # 使用者在「過大的資料夾」提醒按了取消
            self.conv["mode"] = "build"
            self.conv["verify_allow"] = self.conv["workspace"]    # 只限這個資料夾：直接修改與執行（高風險動作仍會先問）
            self.conv["title"] = f"⟳ 自主研發：{os.path.basename(self.conv['workspace'].rstrip(os.sep)) or self.conv['workspace']}"
            self._update_mode_buttons()
            self._update_header()
            self.rd = {"goal": goal, "round": 1, "max_rounds": rounds, "minutes": minutes, "started": time.monotonic(),
                       "deadline": time.monotonic() + minutes * 60, "phase": "", "fix_tries": 0, "turns": set(),
                       "rounds_done": 0, "conv_id": self.conv["id"]}
            msg = f"⟳ 開始自主研發：最多 {rounds} 輪、{minutes} 分鐘。" + (f"方向：{goal}" if goal else "")
            self.transcript.notice(msg)
            self.conv["display"].append(["notice", msg])
            log_app.info("自主研發開始：%s，%d 輪，%d 分鐘", self.conv["workspace"], rounds, minutes)
            self._rd_phase("plan")

        def _rd_time_up(self):
            return time.monotonic() > self.rd["deadline"]

        def _rd_status(self, text):
            rd = self.rd
            left = max(0, int(rd["deadline"] - time.monotonic()) // 60)
            label = f"⟳ 第 {rd['round']}／{rd['max_rounds']} 輪：{text}（剩約 {left} 分鐘）"
            self.status_label.configure(text=label)
            self.transcript.notice(label)
            self.conv["display"].append(["notice", label])

        def _rd_agent(self, prompt, display):
            self.rd["turn_before"] = int(self.conv.get("turn") or 0)
            if not self.start_agent(prompt, display=display, raw=True):
                self._rd_finish("Agent 沒有開始（請確認模型與資料夾）")

        def _rd_same_conv(self):
            """自主研發只在開始時的那段對話進行；使用者在步驟之間切到別的對話就結束，不在別的對話裡動手。"""
            if self.rd and self.conv.get("id") != self.rd.get("conv_id"):
                rd, self.rd = self.rd, None
                log_app.info("自主研發結束：使用者切換了對話（完成 %d 輪）", rd["rounds_done"])
                return False
            return self.rd is not None

        def _rd_phase(self, phase):
            if not self._rd_same_conv():
                return
            rd = self.rd
            if self._rd_time_up() and phase not in ("record",) and rd["phase"] not in ("", "record"):
                phase, rd["stop_after_record"] = "record", True       # 時間到：先把這一輪記錄下來再停
            elif self._rd_time_up() and phase == "plan":
                self._rd_finish("時間到")
                return
            rd["phase"] = phase
            if phase == "plan":
                rd["fix_tries"], rd["turns"] = 0, set()
                self._rd_status("盤點與提案")
                self._rd_agent(rd_plan_prompt(rd["goal"], rd["round"], rd["max_rounds"]),
                               f"⟳ 第 {rd['round']} 輪：請盤點專案並提出這一輪要做的事")
            elif phase == "implement":
                self._rd_status("回應攻擊並實作")
                self._rd_agent(rd_implement_prompt(rd["attacks"]), "⟳ 請回應紅隊的攻擊，並實作與測試")
            elif phase == "fix":
                self._rd_status(f"依審查修正（第 {rd['fix_tries']} 次）")
                self._rd_agent(rd_fix_prompt(rd["reviews"], rd["fix_tries"]), "⟳ 請依紅隊審查修正")
            elif phase == "record":
                self._rd_status("記錄這一輪")
                self._rd_agent(rd_record_prompt(rd["round"], rd.get("unresolved", False)), "⟳ 請記錄這一輪的成果")

        def _rd_last_answer(self):
            return next((d[1] for d in reversed(self.conv.get("display") or []) if d[0] == "assistant"), "")

        def _rd_after_turn(self, status):
            if not self._rd_same_conv():
                return
            rd = self.rd
            if rd.get("timed_out"):
                self._rd_finish("超過時間上限")
                return
            if status == "stopped":
                self._rd_finish("你按了停止")
                return
            if status == "error":
                self._rd_finish("Agent 發生錯誤（見上方訊息）")
                return
            rd["turns"].update(range(rd.get("turn_before", 0) + 1, int(self.conv.get("turn") or 0) + 1))
            answer = self._rd_last_answer()
            phase = rd["phase"]
            if phase == "plan":
                if rd_needs_user(answer):
                    self._rd_finish("需要你決定一些事（見 Agent 的回覆），回答後可以再按「⟳ 自主研發」繼續")
                    return
                rd["plan"] = answer
                self._rd_attack("plan", answer)
            elif phase in ("implement", "fix"):
                diff = rd_changes_diff(self.conv["workspace"], self.conv.get("changes") or [], rd["turns"])
                self._rd_attack("review", f"【修改內容】\n{diff}\n\n【Agent 的說明與測試結果】\n{answer}")
            elif phase == "record":
                rd["rounds_done"] += 1
                if rd.get("stop_after_record"):
                    self._rd_finish("時間到")
                elif rd["round"] >= rd["max_rounds"]:
                    self._rd_finish(f"完成設定的 {rd['max_rounds']} 輪")
                else:
                    rd["round"] += 1
                    self._rd_phase("plan")

        def _rd_attack(self, kind, material):
            rd = self.rd
            main = self._service(self.conv.get("model_id"))
            attackers = self._rd_attackers(main)
            if not attackers:
                self._rd_finish("沒有可用的紅隊模型")
                return
            self._rd_status("紅隊攻擊提案" if kind == "plan" else "紅隊審查修改")
            context = ""
            if kind == "plan":
                try:
                    with open(os.path.join(self.conv["workspace"], AGENT_DIR_NAME, RD_FILES["summary"]), encoding="utf-8",
                              errors="replace") as f:
                        context = f.read(6000)
                except OSError:
                    context = ""
            messages = rd_attack_messages(kind, material, context)
            ev = threading.Event()
            self.cancel_event = ev
            self._set_busy(True)
            self.graph.set_phase("自主研發：紅隊" + ("攻擊提案" if kind == "plan" else "審查修改"))
            results = [None] * len(attackers)

            def one(i, name, endpoint):
                r = stream_chat(endpoint, messages, ev, register=lambda resp, k=i: self._register_response(ev, k, resp))
                results[i] = (name, r.get("text") if r.get("status") == "done" else f"（沒有完成：{r.get('error') or r.get('status')}）")

            def run_all():
                threads = [threading.Thread(target=one, args=(i, n, e), daemon=True) for i, (n, e) in enumerate(attackers)]
                for th in threads:
                    th.start()
                for th in threads:
                    th.join()
                self.ui_queue.put(("rd", None, "call", lambda: self._rd_attack_done(kind, results, ev)))
            threading.Thread(target=run_all, name="rd-attack", daemon=True).start()

        def _rd_attack_done(self, kind, results, ev):
            self._set_busy(False)
            self.cancel_event = None
            rd = self.rd
            if rd is None:
                return
            if ev.is_set():
                self._rd_finish("超過時間上限" if rd.get("timed_out") else "你按了停止")
                return
            results = [r for r in results if r]
            for name, text in results:
                who = f"🗡 紅隊・{name}"
                body = self.transcript.assistant_message(who)
                self.transcript.finish_markdown(body, text or "")
                self.conv["display"].append(["assistant", text or "", who])
            self._save_conv()
            if kind == "plan":
                rd["attacks"] = results
                self._rd_phase("implement")
                return
            rd["reviews"] = results
            blocking = rd_review_blocking(results)
            if blocking and rd["fix_tries"] < RD_MAX_FIX:
                rd["fix_tries"] += 1
                self._rd_phase("fix")
            else:
                rd["unresolved"] = blocking
                self._rd_phase("record")

        def _rd_finish(self, reason):
            rd = self.rd
            if rd is None:
                return
            self.rd = None
            mins = int((time.monotonic() - rd["started"]) // 60)
            msg = f"⟳ 自主研發結束：{reason}。完成 {rd['rounds_done']} 輪，用時約 {mins} 分鐘。紀錄在 .ai協作/{RD_FILES['log']}。"
            self.transcript.notice(msg)
            self.conv["display"].append(["notice", msg])
            self.status_label.configure(text=msg)
            self._save_conv()
            log_app.info("自主研發結束：%s（%d 輪）", reason, rd["rounds_done"])
            try:
                self.bell()
            except tk.TclError:
                pass

        # ───────────── 電腦狀況監控（v6.8.0）─────────────
        MONITOR_INTERVAL = 3            # 秒

        def _build_monitor(self, panel):
            """右側面板最下方：CPU、記憶體、顯卡、顯存與 Ollama 載入的模型；Agent 與 AI 討論都看得到。"""
            box = ttk.Frame(panel, style="Panel.TFrame", padding=(14, 8, 14, 10))
            box.pack(side="bottom", fill="x")
            ttk.Frame(panel, style="Line.TFrame", height=1).pack(side="bottom", fill="x")
            head = ttk.Frame(box, style="Panel.TFrame")
            head.pack(fill="x")
            ttk.Label(head, text="電腦狀況", style="PanelTitle.TLabel").pack(side="left")
            self.mon_toggle = ttk.Label(head, text="", style="PanelMuted.TLabel", cursor="hand2")
            self.mon_toggle.pack(side="right")
            self.mon_toggle.bind("<Button-1>", lambda _e: self._toggle_monitor())
            self.mon_body = ttk.Frame(box, style="Panel.TFrame")
            self.mon_rows = {}
            for i, (key, name) in enumerate((("cpu", "CPU"), ("ram", "記憶體"), ("gpu", "顯卡"), ("vram", "顯存"))):
                ttk.Label(self.mon_body, text=name, style="PanelText.TLabel").grid(row=i * 2, column=0, sticky="w", pady=(4, 0))
                value = ttk.Label(self.mon_body, text="收集中…", style="PanelMuted.TLabel")
                value.grid(row=i * 2, column=1, sticky="e", pady=(4, 0))
                bar = tk.Canvas(self.mon_body, height=max(5, int(6 * self.scale)), highlightthickness=0, bd=0)
                self._register_tk(bar, "side")
                bar.grid(row=i * 2 + 1, column=0, columnspan=2, sticky="ew", pady=(2, 0))
                self.mon_rows[key] = (bar, value)
            self.mon_body.columnconfigure(1, weight=1)
            wrap = int(250 * self.scale)
            self.mon_models = ttk.Label(self.mon_body, text="", style="PanelText.TLabel", wraplength=wrap, justify="left")
            self.mon_models.grid(row=8, column=0, columnspan=2, sticky="w", pady=(6, 0))
            self.mon_warn = ttk.Label(self.mon_body, text="", style="PanelText.TLabel", wraplength=wrap, justify="left")
            self.mon_warn.grid(row=9, column=0, columnspan=2, sticky="w", pady=(4, 0))
            self.mon_warn.grid_remove()
            self._show_monitor_body()

        def _show_monitor_body(self):
            collapsed = bool(self.prefs.get("monitor_collapsed"))
            if collapsed:
                self.mon_body.pack_forget()
            else:
                self.mon_body.pack(fill="x")
            self.mon_toggle.configure(text="展開 ▴" if collapsed else "收起 ▾")

        def _toggle_monitor(self):
            # 收起時停止收集（不再呼叫 nvidia-smi），只記在偏好，不算「未儲存的設定」
            self.prefs["monitor_collapsed"] = not self.prefs.get("monitor_collapsed")
            self._show_monitor_body()

        def _start_monitor(self):
            self._mon_stop = threading.Event()

            def loop():
                previous = cpu_times()
                while not self._mon_stop.wait(self.MONITOR_INTERVAL):
                    if self.prefs.get("monitor_collapsed"):
                        previous = cpu_times()
                        continue
                    try:
                        snap, previous = system_snapshot(previous)
                    except Exception:
                        log_app.exception("收集電腦狀況失敗")
                        continue
                    self.ui_queue.put(("monitor", None, "call", lambda s=snap: self._render_monitor(s)))
            threading.Thread(target=loop, name="monitor", daemon=True).start()

        def _draw_bar(self, key, pct, text):
            bar, value = self.mon_rows[key]
            t = self.theme
            value.configure(text=text)
            bar.delete("all")
            width, height = max(20, bar.winfo_width()), int(bar.cget("height"))
            bar.create_rectangle(0, 0, width, height, fill=t["line"], outline="")
            if pct is None:
                return
            color = t["success"] if pct < 70 else t["warning"] if pct < 90 else t["danger"]
            bar.create_rectangle(0, 0, max(2, int(width * min(100, pct) / 100)), height, fill=color, outline="")

        def _render_monitor(self, snap):
            G = 1024 ** 3
            try:
                cpu = snap.get("cpu")
                self._draw_bar("cpu", cpu, f"{cpu:.0f}%" if cpu is not None else "—")
                total, avail = snap.get("ram_total"), snap.get("ram_avail")
                if total and avail is not None:
                    used = total - avail
                    self._draw_bar("ram", 100 * used / total, f"{used / G:.1f}／{total / G:.0f} GB（可用 {avail / G:.1f}）")
                else:
                    self._draw_bar("ram", None, "偵測不到")
                gpu = snap.get("gpu")
                if gpu:
                    util, temp = gpu.get("util"), gpu.get("temp")
                    parts = [f"{util:.0f}%" if util is not None else "—"] + ([f"{temp:.0f}°C"] if temp is not None else [])
                    self._draw_bar("gpu", util, "　".join(parts))
                    mu, mt = gpu.get("mem_used"), gpu.get("mem_total")
                    if mu is not None and mt:
                        self._draw_bar("vram", 100 * mu / mt, f"{mu / G:.1f}／{mt / G:.0f} GB")
                    else:
                        self._draw_bar("vram", None, "—")
                else:
                    self._draw_bar("gpu", None, "沒有偵測到 NVIDIA 顯卡")
                    self._draw_bar("vram", None, "—")
                models = snap.get("ollama")
                # v6.8.1：先說「這段對話正在用的模型」在哪裡跑（以前只列 Ollama，用雲端模型時看起來像沒有模型）
                team = [s for s in self.services if s.get("enabled", True)][:8]
                if self.conv.get("type") == "agent":
                    # v6.8.2：Agent 會把問題交給 AI 團隊，所以主模型與團隊都要列（以前只列主模型，漏掉團隊裡的本機模型）
                    main = self._service(self.conv.get("model_id"))
                    head, _o = describe_models_in_use([main], models)
                    rest = [s for s in team if not main or s.get("id") != main.get("id")]
                    team_lines, others = describe_models_in_use([main] + rest, models)
                    team_lines = team_lines[len(head):]
                    parts = ["Agent 主模型：\n" + ("\n".join(head) if head else "・（還沒有選模型）")]
                    if team_lines:
                        parts.append("AI 團隊：\n" + "\n".join(team_lines))
                else:
                    in_use, others = describe_models_in_use(team, models)
                    parts = ["參與討論的模型：\n" + ("\n".join(in_use) if in_use else "・（沒有參與的 AI）")]
                if others:
                    parts.append("其他程式在 Ollama 載入的模型：\n" + "\n".join(others))
                self.mon_models.configure(text="\n".join(parts))
                warns = monitor_warnings(snap)
                if warns:
                    self.mon_warn.configure(text="⚠ " + "\n⚠ ".join(warns), foreground=self.theme["danger"])
                    self.mon_warn.grid()
                else:
                    self.mon_warn.grid_remove()
            except tk.TclError:
                pass

        def _build_panel(self, panel):
            self._build_monitor(panel)
            # Agent：兩個分頁。「進度」＝AI 團隊、任務清單、變更的檔案；「工作區」＝資料夾工具與檔案樹
            self.agent_panel = ttk.Frame(panel, style="Panel.TFrame", padding=(8, 8))
            self.agent_tabs = ttk.Notebook(self.agent_panel, style="Panel.TNotebook")
            self.agent_tabs.pack(fill="both", expand=True)
            prog = ttk.Frame(self.agent_tabs, style="Panel.TFrame", padding=(6, 10))
            files = ttk.Frame(self.agent_tabs, style="Panel.TFrame", padding=(6, 10))
            self.agent_tabs.add(prog, text="  進度  ")
            self.agent_tabs.add(files, text="  工作區  ")
            ttk.Label(prog, text="AI 團隊（點一下換模型）", style="PanelTitle.TLabel").pack(anchor="w")
            self.team_box = ttk.Frame(prog, style="Panel.TFrame")
            self.team_box.pack(fill="x", pady=(6, 14))
            ttk.Label(prog, text="任務清單", style="PanelTitle.TLabel").pack(anchor="w")
            self.todo_box = ttk.Frame(prog, style="Panel.TFrame")
            self.todo_box.pack(fill="x", pady=(6, 14))
            ttk.Label(prog, text="變更的檔案（點檔名看差異）", style="PanelTitle.TLabel").pack(anchor="w")
            self.change_box = ttk.Frame(prog, style="Panel.TFrame")
            self.change_box.pack(fill="x", pady=(6, 14))
            self._build_ws_tab(files)
            # AI 討論：參與者清單、名次、操作（流程圖改成獨立視窗，避免在窄面板裡擠成一團）
            self.council_panel = ttk.Frame(panel, style="Panel.TFrame", padding=(14, 14))
            ttk.Label(self.council_panel, text="參與的 AI", style="PanelTitle.TLabel").pack(anchor="w")
            self.part_box = ttk.Frame(self.council_panel, style="Panel.TFrame")
            self.part_box.pack(fill="x", pady=(6, 12))
            self.part_rows = {}
            self.rank_label = ttk.Label(self.council_panel, text="", style="PanelText.TLabel",
                                        wraplength=int(260 * self.scale), justify="left")
            self.rank_label.pack(anchor="w", pady=(0, 10))
            row = ttk.Frame(self.council_panel, style="Panel.TFrame")
            row.pack(fill="x")
            for i, (label, cmd) in enumerate((("並排比較", self.open_compare), ("重新彙整", self.resynthesize),
                                              ("討論設定…", lambda: self.open_settings("AI 討論")))):
                ttk.Button(row, text=label, style="Panel.TButton", command=cmd).grid(
                    row=0, column=i, sticky="ew", padx=(0 if i == 0 else 3, 0))
                row.columnconfigure(i, weight=1, uniform="cbtn")

        def show_graph(self):
            """顯示／隱藏中央的拓樸圖。"""
            if self.graph_visible:
                try:
                    self.ui_state["graph_ratio"] = round(self.center.sashpos(0) / max(1, self.center.winfo_height()), 3)
                except tk.TclError:
                    pass
                self.center.forget(self.graph_frame)
            else:
                self.center.insert(0, self.graph_frame, weight=2)
                self._center_ready = False
                self.after(50, lambda: self.center.event_generate("<Configure>"))
            self.graph_visible = not self.graph_visible
            self.graph_button.configure(text="◎ 收起圖" if self.graph_visible else "◎ 拓樸圖")

        AGENT_NODES = (("tool:read", "讀取檔案", "研究分析", "列目錄・讀檔・搜尋"),
                       ("tool:edit", "修改檔案", "文件撰寫", "新建・精確編輯（先備份）"),
                       ("tool:shell", "執行指令", "程式專家", "命令列（刪除類一律詢問）"),
                       ("tool:web", "上網查資料", "一般助理", "讀網頁・網路搜尋"),
                       ("tool:council", "AI 討論團", "對話溝通", "多模型匿名互評＋整合"),
                       ("tool:free", "任務與記憶", "資料處理", "任務清單・提問・記住"))

        def _graph_for_conversation(self):
            """依目前對話類型設定中央拓樸圖：Agent＝中央 Agent＋周圍工具；AI 討論＝主持 AI＋各參與 AI。"""
            g = self.graph
            self._build_team()
            if hasattr(self, "web_research_check"):
                if self.conv["type"] == "council":
                    self.web_research_check.pack(side="left", padx=(14, 0))
                else:
                    self.web_research_check.pack_forget()
            if self.conv["type"] == "agent":
                g.agent_view = True
                service = self._service(self.conv.get("model_id") or self.prefs.get("agent_model_id"))
                hub = {"name": service.get("name") or "Agent", "model": service.get("model", "")} if service else None
                # 周圍是你自訂的 AI 團隊（數量、模型都可改）；Agent 呼叫「AI 討論團」時就是找他們
                nodes = [{"id": x["id"], "name": x.get("name"), "role": x.get("role"), "model": x.get("model"),
                          "enabled": x.get("enabled", True)} for x in self.services]
                g.set_participants(nodes, hub, "規劃（唯讀）" if self.conv.get("mode") == "plan" else "執行")
            else:
                g.agent_view = False
                hub_service = self._service(self.prefs.get("hub_id"))
                agents = [{"id": x["id"], "name": x.get("name"), "role": x.get("role"), "model": x.get("model"),
                           "enabled": x.get("enabled", True)} for x in self.services]
                hub_info = {"name": hub_service.get("name"), "model": hub_service.get("model")} if hub_service else None
                g.set_participants(agents, hub_info, self.mode_var.get())
                if not self.busy:
                    self._build_parts(agents, hub_info)
            if not self.busy:
                g.reset_run()
                g.set_phase("待命")

        def _on_graph_select(self, pid):
            """點拓樸圖上的機器人：開「選擇模型」視窗（可從環境變數裡的金鑰抓該服務的可用模型）。"""
            if pid == FINAL_ID:
                ui = self.council_ui
                if ui and 99 in ui.get("sections", {}):
                    self.transcript.text.see(f"{ui['sections'][99]['head']}_s")
                else:
                    self.transcript.text.see("end")
                return
            if pid == CONTEXT_ID:
                return
            if pid == HUB_ID:
                if self.conv["type"] == "agent":
                    service = self._service(self.conv.get("model_id") or self.prefs.get("agent_model_id"))
                    hint = "Agent 模型"
                else:
                    service = self._service(self.prefs.get("hub_id"))
                    hint = "主持 AI"
                if service is None:
                    self.open_settings("模型與 API")
                    return
                self.open_model_picker(service=service, title_hint=f"{hint}（{service.get('name')}）")
                return
            service = self._service(pid)
            if service is not None:
                self.open_model_picker(service=service)

        def _robot_menu(self, pid, event):
            """在機器人上按右鍵：直接換身分、換模型與工作、切換是否參與。"""
            if pid in (FINAL_ID, CONTEXT_ID):
                return
            if pid == HUB_ID:
                self._on_graph_select(pid)
                return
            service = self._service(pid)
            if service is None:
                return
            m = tk.Menu(self, tearoff=False)
            role_menu = tk.Menu(m, tearoff=False)
            var = tk.StringVar(value=service.get("role") or DEFAULT_ROLE)
            for role in ROLES:
                role_menu.add_radiobutton(label=role, variable=var, value=role,
                                          command=lambda r=role: self._set_robot_role(service, r))
            m.add_cascade(label=f"身分：{service.get('role') or DEFAULT_ROLE}", menu=role_menu)
            m.add_command(label="換模型、身分與工作…", command=lambda: self.open_model_picker(service=service))
            m.add_separator()
            on = service.get("enabled", True)
            m.add_command(label="不參與討論" if on else "參與討論", command=lambda: self._toggle_robot(service))
            m._role_var = var
            m.tk_popup(event.x_root, event.y_root)

        def _set_robot_role(self, service, role):
            if self.busy:
                self.status_label.configure(text="執行中不能改身分，請等這一輪結束。")
                return
            self._apply_model_pick(service, None, None, None, service.get("model", ""), role, None)
            self.status_label.configure(text=f"「{service.get('name')}」的身分改為「{role}」（已儲存）。")

        def _toggle_robot(self, service):
            if self.busy:
                return
            service["enabled"] = not service.get("enabled", True)
            editor = self.editors.get(service["id"])
            if editor is not None:
                try:
                    editor.enabled.set(service["enabled"])
                except tk.TclError:
                    pass
            self.save_settings(quiet=True)
            self._build_team()
            self._graph_for_conversation()

        def _on_graph_open(self, pid):
            if pid in (FINAL_ID, CONTEXT_ID):
                return
            self.open_settings("模型與 API")
            editor = self.editors.get(pid)
            if editor is not None:
                try:
                    self.after(200, lambda: self.endpoint_scroll.canvas.yview_moveto(
                        max(0.0, list(self.editors).index(pid) / max(1, len(self.editors)))))
                except (tk.TclError, AttributeError, ValueError):
                    pass

        def _build_parts(self, agents, hub):
            for child in self.part_box.winfo_children():
                child.destroy()
            self.part_rows = {}
            t = self.theme
            items = [(a["id"], a["name"], a.get("role") or DEFAULT_ROLE, a.get("model", "")) for a in agents]
            if hub:
                items.append((HUB_ID, f"主持：{hub['name']}", "主持", hub.get("model", "")))
            self._parts_args = (agents, hub)
            for pid, name, role, model in items:
                row = tk.Frame(self.part_box, bg=t["side"])
                row.pack(fill="x", pady=3)
                dot = tk.Canvas(row, width=12, height=12, highlightthickness=0, bg=t["side"])
                color = t["accent"] if pid == HUB_ID else t.role_color(role)
                dot.create_oval(2, 2, 11, 11, fill=color, outline="")
                dot.grid(row=0, column=0, rowspan=2, sticky="n", pady=(4, 0), padx=(0, 8))
                tk.Label(row, text=name, bg=t["side"], fg=t["text"], font=self.fonts["ui_bold"], anchor="w").grid(
                    row=0, column=1, sticky="w")
                status = tk.Label(row, text="待命", bg=t["side"], fg=t["muted"], font=self.fonts["small"], anchor="e")
                status.grid(row=0, column=2, sticky="e")
                tk.Label(row, text=f"{role}・{short_model(model)}", bg=t["side"], fg=t["muted"], font=self.fonts["small"],
                         anchor="w").grid(row=1, column=1, columnspan=2, sticky="w")
                row.columnconfigure(1, weight=1)
                self.part_rows[pid] = status
                for w in row.winfo_children() + [row]:
                    w.bind("<Button-1>", lambda _e, p=pid: self._on_graph_select(p))
                    w.configure(cursor="hand2")

        def _set_state(self, pid, state, detail=""):
            self.graph.set_state(pid, state, detail)
            label = self.part_rows.get(pid)
            if label is not None:
                text, color = self.theme.status(state)
                try:
                    label.configure(text=text + (f" {detail}" if detail else ""), fg=color)
                except tk.TclError:
                    pass

        def _show_panel_for(self, kind):
            self.agent_panel.pack_forget()
            self.council_panel.pack_forget()
            (self.agent_panel if kind == "agent" else self.council_panel).pack(fill="both", expand=True)

        def toggle_panel(self):
            if self.panel_visible:
                self.panel.pack_forget()
                self.panel_line.pack_forget()
            else:
                self.panel.pack(side="right", fill="y", before=self.main)
                self.panel_line.pack(side="right", fill="y", before=self.main)
            self.panel_visible = not self.panel_visible

        def _draw_logo(self):
            """左上角品牌標誌：原創 Q 版主持 AI 頭像（光環上的三個節點是三種身分色，代表大家一起協作）。"""
            c, t = self.logo, self.theme
            c.delete("all")
            k = int(c.cget("width")) / 36

            def rr(x1, y1, x2, y2, r, **kw):
                c.create_polygon(rounded_points(x1 * k, y1 * k, x2 * k, y2 * k, r * k), smooth=True, **kw)

            rr(1, 1, 35, 35, 9, fill=t["accent"], outline="")
            for x in (6.8, 29.2):
                c.create_polygon([v for i in range(6) for v in ((x + 2.6 * math.cos(math.radians(60 * i))) * k,
                                                                (20 + 2.6 * math.sin(math.radians(60 * i))) * k)],
                                 fill=mix(t["accent"], "#FFFFFF", 0.65), outline="")
            rr(8, 11.5, 28, 30, 7, fill=t["robot"], outline=t["robot_line"])
            rr(10.5, 14, 25.5, 25.5, 4.5, fill=t["visor"], outline="")
            for ex in (14.9, 21.1):
                c.create_oval((ex - 1.9) * k, 16.4 * k, (ex + 1.9) * k, 21.6 * k, fill=t["eye"], outline="")
                c.create_oval((ex - 1.3) * k, 16.9 * k, (ex - 0.1) * k, 18.1 * k, fill="#FFFFFF", outline="")
            c.create_arc(16.4 * k, 20.6 * k, 19.6 * k, 23.6 * k, start=205, extent=130, style="arc",
                         outline=t["eye"], width=max(1, k))
            c.create_oval(9 * k, 4 * k, 27 * k, 9 * k, outline="#FFFFFF", width=max(1, 1.3 * k))
            for (x, y), role in zip(((9.4, 6.5), (26.6, 6.5), (18, 4)), ("程式專家", "研究分析", "文件撰寫")):
                c.create_oval((x - 2.2) * k, (y - 2.2) * k, (x + 2.2) * k, (y + 2.2) * k, fill=t.role_color(role),
                              outline="#FFFFFF", width=1)

        # ───────────── 對話管理 ─────────────
        def new_conversation(self, kind=None):
            if self.busy:
                messagebox.showinfo(APP_NAME, "目前還在執行中，請先停止或等它完成。")
                return
            kind = kind or (self.conv["type"] if hasattr(self, "conv") else "agent")
            self.prefs["new_chat_type"] = kind
            model_id = self.prefs.get("agent_model_id") or (self.services[0]["id"] if self.services else "")
            self.conv = new_session(kind, self.prefs.get("last_workspace", "") if kind == "agent" else "", model_id)
            self.conv["mode"] = self.prefs.get("agent_mode", "build")
            self.runner, self.runner_key = None, None
            self.run, self.last_record = {}, None
            self.cat_last_card = {}
            self._show_panel_for(kind)
            self._render_conversation()
            self._update_header()
            self._refresh_model_choices()
            self.refresh_sessions()
            self._graph_for_conversation()
            self.prompt.focus_set()

        def open_conversation(self, sid):
            if self.busy:
                messagebox.showinfo(APP_NAME, "目前還在執行中，請先停止或等它完成。")
                return
            try:
                self.conv = load_session(sid)
            except (OSError, ValueError) as exc:
                messagebox.showerror(APP_NAME, f"無法開啟這個對話：{exc}")
                return
            self.runner, self.runner_key = None, None
            self.run, self.last_record = {}, None
            for item in reversed(self.conv.get("display", [])):
                if item[0] == "council":
                    self.last_record = item[1]
                    break
            self._show_panel_for(self.conv["type"])
            self._render_conversation()
            self._update_header()
            self._refresh_model_choices()
            self.refresh_sessions()
            self._graph_for_conversation()
            if self.conv["type"] == "council" and self.last_record:
                rec = self.last_record
                self._build_parts(rec.get("agents", []), rec.get("hub"))
                for rnd in rec.get("rounds", [])[-1:]:
                    for pid, res in rnd["answers"].items():
                        st = STATUS_FROM_RESULT.get(res.get("status"), "error")
                        self._set_state(pid, st, f"{res.get('elapsed', 0):.0f}s" if st == "done" else "")
                if rec.get("hub_result"):
                    self._set_state(HUB_ID, STATUS_FROM_RESULT.get(rec["hub_result"].get("status"), "error"), "")

        def _render_conversation(self):
            tr = self.transcript
            tr.clear()
            self.tool_cards = {}
            display = self.conv.get("display", [])
            if not display:
                if self.conv["type"] == "agent":
                    tr.empty_state("Agent", [
                        "可以讀檔、修改檔案、執行指令、查網路，必要時請多個 AI 討論。",
                        "先在右上角選擇工作資料夾與模型；「規劃」模式只讀不改，「執行」模式才會動手（修改前會問你）。",
                        "", "試試看：", "「看一下這個資料夾，整理出一份說明文件」",
                        "「幫我找出程式裡可能的錯誤並修正，修改前先列計畫」",
                        "「查一下 Python 3.13 有哪些新功能，整理成重點」"])
                else:
                    tr.empty_state("AI 討論", [
                        "同一個問題交給多個 AI：各自回答 → 匿名互評 → 主持 AI 整合。",
                        "右上角可以選擇討論方式、互評輪數、主持 AI 與參與人數。", "",
                        "適合：需要多方意見、交叉驗證、方案比較的問題。"])
            for item in display:
                kind = item[0]
                if kind == "user":
                    tr.user_message(item[1])
                elif kind == "assistant":
                    body = tr.assistant_message(item[2] if len(item) > 2 else "Agent")
                    tr.finish_markdown(body, item[1])
                elif kind == "tool":
                    _k, name, title, ok, output = item[:5]
                    card = tr.tool_card(title, TOOL_ICONS.get(name, "•"))
                    tr.set_tool_status(card, "✓" if ok else "✗", "tool_ok" if ok else "tool_bad")
                    tr.tool_output(card, output)
                elif kind == "notice":
                    tr.notice(item[1])
                elif kind == "error":
                    tr.notice(item[1], "error")
                elif kind == "council":
                    self._render_council_record(item[1])
            tr.scroll_end(force=True)
            self._refresh_agent_panel()

        def _save_conv(self):
            if not self.conv.get("display"):
                return
            if self.conv.get("title") in (None, "", "新對話"):
                first = next((d[1] for d in self.conv["display"] if d[0] == "user"), "")
                # v6.11 紅隊：先截 40 字再遮蔽會把金鑰切斷（nvapi-ABCDE 認不出來），部分金鑰會留在標題裡
                self.conv["title"] = re.sub(r"\s+", " ", mask_secrets(first)[0]).strip()[:40] or "新對話"
            try:
                save_session(self.conv)
            except OSError:
                log_app.exception("儲存對話失敗")
            self.refresh_sessions()
            self._update_header()

        # ───────────── 送出 ─────────────
        def send(self):
            if self.busy:
                self.stop()
                return
            text = self.prompt.get("1.0", "end-1c").strip()
            if not text:
                return
            if self.conv["type"] == "agent":
                ok = self.start_agent(text)
            else:
                ok = self.start_council(text)
            if ok:
                self.prompt.delete("1.0", "end")
                self._update_char_count()
                self.attach_images = []
                self._render_attach_bar()

        def stop(self):
            if not self.busy:
                return
            if self.runner and self.conv["type"] == "agent":
                self.runner.cancel.set()
                for card in self.pending_cards:
                    card["holder"]["result"] = ("deny", "已停止")
                    card["holder"]["event"].set()
            if self.cancel_event:
                self.cancel_event.set()
            with self.active_lock:
                responses = list(self.active.values())
            for r in responses:
                try:
                    r.close()
                except Exception:
                    pass
            self.status_label.configure(text="正在停止…")

        def _set_busy(self, busy):
            if busy and not self.busy:
                USAGE.begin()
            elif not busy and self.busy:
                self._report_usage(USAGE.end())
            self.busy = busy
            keep_awake(busy)                     # 長時間的討論或 Agent 執行中，不讓 Windows 睡著而中斷
            if busy:
                self.send_button.configure(text="■  停止", style="Danger.TButton")
            else:
                self.send_button.configure(text="送出  ➤", style="Primary.TButton")
                self.skip_button.pack_forget()

        # ───────────── Agent ─────────────
        def choose_workspace(self):
            if self.busy:
                return
            path = filedialog.askdirectory(title="選擇 Agent 的工作資料夾", initialdir=self.conv.get("workspace") or
                                           self.prefs.get("last_workspace") or os.path.expanduser("~"))
            if not path:
                return
            self.set_workspace(path)

        def set_workspace(self, path):
            if self.busy or not path:
                return
            if not os.path.isdir(path):
                messagebox.showerror(APP_NAME, f"資料夾不存在：{path}")
                return
            broad = broad_workspace_reason(path)
            if broad and not messagebox.askyesno(
                    APP_NAME, f"「{path}」是{broad}。\n\nAgent 可以讀取、修改這個資料夾裡的所有檔案（讀到的內容會送到 AI 模型）。"
                              "建議改選只放這個專案的資料夾。\n\n仍要用這個資料夾嗎？", icon="warning"):
                return
            old = self.conv.get("workspace")
            self.conv["workspace"] = os.path.abspath(path)
            self.prefs["last_workspace"] = self.conv["workspace"]
            if self.conv.get("messages") and workspace_switch_note(old, self.conv["workspace"]):
                # 對話已經讀過舊資料夾：記住原本的資料夾，下一則訊息會告訴模型改看新資料夾（連續換只算第一個）
                self.conv.setdefault("workspace_before", old)
                msg = (f"📁 已換到「{self.conv['workspace']}」。這段對話前面的內容是舊資料夾的，"
                       "下一則訊息會提醒 Agent 改看新資料夾；想完全重來可以按「＋ 新對話」。")
                try:
                    self.transcript.notice(msg)
                    self.conv.setdefault("display", []).append(["notice", msg])
                except (tk.TclError, AttributeError):
                    pass
            recent = [p for p in (self.prefs.get("recent_workspaces") or []) if os.path.normcase(p) != os.path.normcase(self.conv["workspace"])]
            self.prefs["recent_workspaces"] = ([self.conv["workspace"]] + recent)[:8]
            self._mark_dirty()
            self.runner, self.runner_key = None, None
            self._update_header()
            self._refresh_agent_panel()

        def _open_workspace(self):
            if self.conv.get("workspace"):
                open_path(self.conv["workspace"])

        def _refresh_model_choices(self):
            labels = [self._label(s) for s in self.services]
            self.model_combo.configure(values=labels)
            mid = self.conv.get("model_id") if hasattr(self, "conv") else None
            service = self._service(mid) or self._service(self.prefs.get("agent_model_id")) or (self.services[0] if self.services else None)
            self.model_var.set(self._label(service) if service else "")
            if service and hasattr(self, "conv"):
                self.conv["model_id"] = service["id"]

        def _on_model_selected(self):
            i = self.model_combo.current()
            if 0 <= i < len(self.services):
                self.conv["model_id"] = self.services[i]["id"]
                self.prefs["agent_model_id"] = self.services[i]["id"]
                self._mark_dirty()
                self.runner_key = None
                self._graph_for_conversation()

        def set_agent_mode(self, mode):
            self.conv["mode"] = mode
            self.prefs["agent_mode"] = mode
            self._mark_dirty()
            if self.runner:
                self.runner.mode = mode
            self._update_mode_buttons()
            if not self.busy:
                self._graph_for_conversation()

        def _mask_outgoing(self, text):
            """送到雲端模型前，把訊息（含附上的檔案內容）裡像金鑰的字串遮起來，並告訴使用者。"""
            masked, n = mask_secrets(text)
            if n:
                msg = f"🔒 你的訊息或附上的檔案裡有 {n} 個像金鑰的字串，已遮蔽後才送出（模型與紀錄都看不到本體）。"
                try:
                    self.transcript.notice(msg)
                    self.conv["display"].append(["notice", msg])
                except (tk.TclError, KeyError, AttributeError):
                    pass
            return masked

        def _agent_options(self):
            p = self.prefs
            return {"filter_think": p.get("filter_think", True), "auto_retry": 2 if p.get("auto_retry", True) else 0,
                    "max_steps": p.get("agent_max_steps", AGENT_MAX_STEPS), "tool_mode": p.get("agent_tool_mode", "auto"),
                    "web_search": p.get("agent_web_search", True), "sandbox": bool(p.get("agent_sandbox", False)),
                    **({"max_steps": min(int(p.get("agent_max_steps", AGENT_MAX_STEPS)), int(p.get("schedule_max_steps", 30)))}
                       if self._unattended is not None else {}),
                    "trusted_agents_md": p.setdefault("trusted_agents_md", {}),     # 確認過的 AGENTS.md（路徑 → 內容雜湊）
                    "on_trust": lambda: self.ui_queue.put(("ui", None, "call", lambda: self.save_settings(quiet=True)))}

        def start_agent(self, text, display=None, raw=False):
            """display：對話裡顯示的文字（預設＝text）；raw：不展開 @引用（自主研發的指示裡可能有 @ 開頭的程式碼）。"""
            if not self.conv.get("workspace"):
                self.choose_workspace()
                if not self.conv.get("workspace"):
                    return False
            if not os.path.isdir(self.conv["workspace"]):
                messagebox.showerror(APP_NAME, f"工作資料夾不存在：{self.conv['workspace']}")
                return False
            service = self._service(self.conv.get("model_id"))
            if not service:
                messagebox.showinfo(APP_NAME, "請先在右上角選擇模型（或到「設定 → 模型與 API」新增）。")
                return False
            endpoint, err = self._resolve(service)
            if err:
                messagebox.showerror(APP_NAME, err)
                return False
            fit = local_fit_warning(endpoint)          # 本機大模型：顯卡＋記憶體可能放不下時先說
            if fit and not messagebox.askyesno(APP_NAME, fit + "\n\n仍要送出嗎？", icon="warning"):
                return False
            key = (endpoint["url"], endpoint["model"], endpoint["key"], self.conv["workspace"])
            if self.runner is None or self.runner_key != key:
                ws = Workspace(self.conv["workspace"], self.conv["id"])
                ws.changes = self.conv.setdefault("changes", [])
                ws.turn = int(self.conv.get("turn") or 0)
                runner_cls = CliAgentRunner if cli_kind(endpoint["url"]) else AgentRunner
                self.runner = runner_cls(endpoint, ws, emit=self._agent_emit, approve=self._approve_blocking,
                                          ask=self._ask_blocking, council=self._council_blocking,
                                          mode=self.conv.get("mode", "build"),
                                          permissions=self.prefs.get("agent_perms") or {}, options=self._agent_options(),
                                          messages=self.conv.setdefault("messages", []),
                                          global_prompt=self._prompt_with_context("agent"))
                self.runner.todos = self.conv.get("todos", [])
                saved = self.conv.get("cli_session") or {}
                if isinstance(self.runner, CliAgentRunner) and saved.get("root") == self.conv["workspace"] \
                        and saved.get("url") == endpoint["url"]:
                    self.runner.session = saved.get("id", "")     # 程式重開後接續同一個 Claude Code 工作階段
                self.runner_key = key
            else:
                self.runner.mode = self.conv.get("mode", "build")
                self.runner.permissions = dict(DEFAULT_PERMISSIONS, **(self.prefs.get("agent_perms") or {}))
                self.runner.options = self._agent_options()
                self.runner.global_prompt = self._prompt_with_context("agent")
            if self.conv.get("verify_allow") and self.conv.get("verify_allow") == self.conv.get("workspace"):
                # 驗證專案：使用者已同意在這個新資料夾裡直接修改與執行（刪除、覆寫、讀金鑰類仍會先問）
                self.runner.session_allow |= {"edit", "shell"}
            if not self.conv.get("display"):
                self.transcript.clear()
            shown_text = (display or text) + self._image_note()
            self.transcript.user_message(shown_text)
            self.conv["display"].append(["user", shown_text])
            if self.attach_images and not supports_vision(endpoint["model"]):
                self.transcript.notice(f"⚠ 你附了圖片，但 {short_model(endpoint['model'])} 看起來不是視覺模型，它看不到圖片。")
            self.agent_body, self.agent_buffer, self.agent_text = None, [], ""
            self.agent_who = f"Agent・{short_model(endpoint['model'])}"
            self.agent_step, self.agent_started = 0, time.monotonic()
            self.agent_state = "思考中"
            self.cat_last_card = getattr(self, "cat_last_card", {})
            self._graph_for_conversation()
            self.graph.set_running(True)
            self.graph.set_phase("Agent 思考中")
            self.graph.set_state(HUB_ID, "thinking", "")
            self.token = token = object()
            self._set_busy(True)
            self._agent_status()
            log_app.info("Agent 開始：模型=%s，資料夾=%s，模式=%s", endpoint["model"], self.conv["workspace"], self.conv.get("mode"))
            prompt_text, attached = (text, []) if raw else self._expand_mentions(text)
            if attached:
                tr = self.transcript
                tr.notice("＠ 已附上檔案內容：" + "、".join(attached))
                self.conv["display"].append(["notice", "＠ 已附上檔案內容：" + "、".join(attached)])
            note = workspace_switch_note(self.conv.pop("workspace_before", None), self.conv["workspace"])
            if note:
                prompt_text = note + "\n\n" + prompt_text
            prompt_text = self._mask_outgoing(prompt_text)
            self.runner.extra_tools = self.mcp.agent_tools() if self.prefs.get("mcp_enabled", True) else {}
            threading.Thread(target=self.runner.run, args=(prompt_text, list(self.attach_images)), daemon=True).start()
            return True

        def _agent_emit(self, kind, *payload):
            self.ui_queue.put(("agent", self.token, kind) + payload)

        def _agent_status(self):
            if not self.busy or self.conv["type"] != "agent":
                return
            u = self.agent_usage or {}
            tok = u.get("prompt", 0) + u.get("completion", 0)
            parts = [f"● Agent {self.agent_state}", f"第 {self.agent_step} 步",
                     f"已用 {self._fmt_secs(time.monotonic() - self.agent_started)}"]
            if tok:
                parts.append(f"{tok:,} tokens")
            self.status_label.configure(text="　".join(parts), foreground=self.theme["accent"])

        def _handle_agent(self, kind, payload):
            tr = self.transcript
            if kind == "register":
                with self.active_lock:
                    if payload[0] is None:
                        self.active.pop("agent", None)
                    else:
                        self.active["agent"] = payload[0]
                return
            if kind == "step":
                self.agent_step = payload[0]
                self.agent_state = "思考中"
                self.graph.set_state(HUB_ID, "thinking", f"第 {payload[0]} 步")
                self.graph.set_phase(f"Agent 第 {payload[0]} 步：思考中")
            elif kind == "thinking":
                self.agent_state = "思考中"
            elif kind == "text":
                if self.agent_body is None:
                    self.agent_body = tr.assistant_message(self.agent_who)
                    self.agent_text = ""
                self.agent_buffer.append(payload[0])
                if self.agent_state != "回覆中":
                    self.graph.set_state(HUB_ID, "generating", f"第 {self.agent_step} 步")
                self.agent_state = "回覆中"
            elif kind == "assistant_end":
                self._flush_agent()
                shown = payload[0] or ""
                if self.agent_body is not None:
                    if shown.strip():
                        tr.finish_markdown(self.agent_body, shown)
                    else:
                        tr.clear_region(tr.parent[self.agent_body])
                if shown.strip():
                    self.conv["display"].append(["assistant", shown, self.agent_who])
                    self.graph.set_final(shown)
                self.agent_body, self.agent_text = None, ""
            elif kind == "tool_start":
                call_id, name, args, title = payload
                card = tr.tool_card(title, TOOL_ICONS.get(name, "•"))
                tr.set_tool_status(card, "執行中…")
                self.tool_cards[call_id] = (card, name, title)
                self.current_tool = card
                self.agent_state = f"使用工具：{title[:30]}"
                self.cat_last_card["tool:" + (TOOLS.get(name, ("free",))[0])] = card
                self.graph.set_state(HUB_ID, "connecting", f"{TOOL_ICONS.get(name, '•')} {title[:18]}")
                if name == "consult_council":
                    for x in self.services:
                        if x.get("enabled", True):
                            self.graph.pulse_link(HUB_ID, x["id"], "plan")
                self.graph.set_phase(f"Agent 第 {self.agent_step} 步：{title[:40]}")
            elif kind == "tool_end":
                call_id, ok, output = payload
                card, name, title = self.tool_cards.get(call_id, (None, "", ""))
                first = (output or "").strip().splitlines()[:1]
                self.graph.set_preview(HUB_ID, f"{title}｜{first[0][:80] if first else ''}")
                self.graph.set_state(HUB_ID, "thinking" if ok else "error", f"第 {self.agent_step} 步")
                if card:
                    tr.set_tool_status(card, "✓" if ok else f"✗ {output.splitlines()[0][:60] if output else ''}",
                                       "tool_ok" if ok else "tool_bad")
                    tr.tool_output(card, output)
                self.conv["display"].append(["tool", name, title, ok, (output or "")[:6000]])
                self.agent_state = "思考中"
            elif kind == "todo":
                self.conv["todos"] = payload[0]
                self._refresh_agent_panel()
            elif kind == "file_changed":
                self.conv["changes"] = self.runner.ws.changes if self.runner else self.conv.get("changes", [])
                self.conv["turn"] = self.runner.ws.turn if self.runner else self.conv.get("turn", 0)
                self._refresh_agent_panel()
            elif kind == "notice":
                tr.notice("ℹ " + payload[0])
                self.conv["display"].append(["notice", "ℹ " + payload[0]])
            elif kind == "error":
                tr.notice("✗ " + payload[0], "error")
                self.conv["display"].append(["error", "✗ " + payload[0]])
            elif kind == "usage":
                self.agent_usage = payload[0]
            elif kind == "retry_wait":
                wait, reason = payload[0]
                self.agent_state = f"等待重試 {wait} 秒（{reason}）"
            elif kind == "turn_done":
                status, usage = payload
                if isinstance(self.runner, CliAgentRunner):
                    self.conv["cli_session"] = {"root": self.runner.ws.root, "url": self.runner.endpoint["url"],
                                                "id": self.runner.session}
                self._flush_agent()
                last = next((d[1] for d in reversed(self.conv.get("display") or []) if d[0] == "assistant"), "")
                drift = drift_notice(last) if status == "done" else ""
                if drift:
                    self.transcript.notice("ⓘ " + drift)
                self.transcript.scroll_end(force=True)
                self._set_busy(False)
                self.conv["turn"] = self.runner.ws.turn
                self.conv["changes"] = self.runner.ws.changes
                self.conv["usage"] = usage
                changed = [c for c in self.runner.ws.changes if c["turn"] == self.runner.ws.turn and not c.get("undone")]
                if changed:
                    msg = f"本輪修改了 {len(changed)} 個檔案（舊檔已備份，可在右側「變更的檔案」復原）"
                    tr.notice("✎ " + msg)
                    self.conv["display"].append(["notice", "✎ " + msg])
                ep = getattr(self.runner, "endpoint", None) or {}
                if status == "done" and ollama_native_base(ep.get("url")):
                    loaded = ollama_loaded(ep)           # 本機大模型：這次顯卡／記憶體怎麼分（變了才顯示）
                    desc = describe_local_split(loaded) if loaded else ""
                    if desc and self.conv.get("local_split") != desc:
                        self.conv["local_split"] = desc
                        tr.notice("🖥 本機模型：" + desc)
                        self.conv["display"].append(["notice", "🖥 本機模型：" + desc])
                label = {"done": "完成", "stopped": "已停止", "error": "發生錯誤", "max_steps": "達到步數上限"}.get(status, status)
                self.graph.set_running(False)
                self.graph.set_state(HUB_ID, "done" if status == "done" else "stopped" if status == "stopped" else "error",
                                     f"{self.agent_step} 步")
                self.graph.set_phase(f"{label}（{self.agent_step} 步）")
                tok = usage.get("prompt", 0) + usage.get("completion", 0)
                self.status_label.configure(
                    text=f"{label}　{self.agent_step} 步　{self._fmt_secs(time.monotonic() - self.agent_started)}"
                         + (f"　{tok:,} tokens" if tok else ""), foreground=self.theme["muted"])
                self._save_conv()
                self._refresh_agent_panel()
                self._refresh_ws_tab(force=True)
                log_app.info("Agent 結束：%s，%s 步", label, self.agent_step)
                self._schedule_finished(label)
                if getattr(self, "rd", None):
                    self.after(600, lambda s=status: self._rd_after_turn(s))
                return
            self._agent_status()

        def _flush_agent(self):
            if self.agent_buffer and self.agent_body is not None:
                chunk = "".join(self.agent_buffer)
                self.agent_buffer = []
                self.agent_text += chunk
                self.transcript.write(self.agent_body, chunk, "md_p")

        def _card_buttons(self, rid, buttons):
            frame = tk.Frame(self.transcript.text, bg=self.theme["canvas_chat"])
            for label, style, command in buttons:
                ttk.Button(frame, text=label, style=style, command=command).pack(side="left", padx=(0, 6))
            self.transcript.write(rid, "  ", "card_done")
            self.transcript.embed(rid, frame)
            self.transcript.write(rid, "\n", "card_done")
            return frame

        def _approve_blocking(self, category, title, detail):
            sch = self._unattended
            if sch is not None:              # 排程執行：沒有人可以按核准
                dangerous = "⚠" in (detail or "")
                if sch.get("approval") == "allow" and not dangerous and category not in ("mcp", "信任專案規則"):
                    self.ui_queue.put(("ui", None, "call", lambda: self.transcript.notice(f"⏰ 排程自動允許：{title}")))
                    return ("allow", "")
                self.ui_queue.put(("ui", None, "call", lambda: self.transcript.notice(f"⏰ 排程執行中沒有人核准，已拒絕：{title}")))
                return ("deny", "排程執行時沒有人可以核准這個動作；請改用不需要核准的做法，或在結果中說明需要使用者手動處理")
            holder = {"event": threading.Event(), "result": ("deny", "")}
            self.ui_queue.put(("ui", None, "call", lambda: self._show_approval(holder, category, title, detail)))
            while not holder["event"].wait(0.2):
                if self.runner is None or self.runner.cancel.is_set():
                    return ("deny", "已停止")
            return holder["result"]

        def _show_approval(self, holder, category, title, detail):
            tr = self.transcript
            rid = tr.region(prefix="a")
            tr.write(rid, f"  需要你的核准　{TOOL_CATEGORIES.get(category, category)}：{title}\n", "card_title")
            detail_rid = tr.region(rid)
            tr.set_collapsible(detail_rid, False)
            tr.write(detail_rid, (detail or "").rstrip() + "\n", "card_body")
            card = {"holder": holder}
            self.pending_cards.append(card)
            self.graph.set_state(HUB_ID, "paused", "等你核准")
            self.agent_state = "等待你的核准"
            self._agent_status()

            def decide(result, label):
                holder["result"] = (result, "")
                holder["event"].set()
                # v6.9.1：按下後立刻更新狀態（以前一直顯示「等待你的核准」，像是卡住；例如請 AI 討論團時要跑好幾分鐘）
                if not self.pending_cards or self.pending_cards == [card]:
                    self.agent_state = "已核准，執行中" if result != "deny" else "已拒絕，繼續思考"
                    self.graph.set_state(HUB_ID, "thinking", "")
                    self._agent_status()
                try:
                    frame.destroy()
                except tk.TclError:
                    pass
                tr.write(rid, f"  {label}\n", "card_done")
                tr.text.tag_configure(f"{detail_rid}_body", elide=True)   # 決定後把詳細內容收起來
                tr.elided[detail_rid] = True
                if card in self.pending_cards:
                    self.pending_cards.remove(card)
                self.conv["display"].append(["notice", f"{label}：{title}"])

            frame = self._card_buttons(rid, [
                ("允許", "Primary.TButton", lambda: decide("allow", "✓ 已允許")),
                (f"這次對話都允許「{TOOL_CATEGORIES.get(category, category)}」", "Chip.TButton",
                 lambda: decide("always", f"✓ 已允許（本次對話不再詢問{TOOL_CATEGORIES.get(category, '')}）")),
                ("拒絕", "Danger.TButton", lambda: decide("deny", "✗ 已拒絕"))])
            tr.scroll_end(force=True)
            self.bell()

        def _ask_blocking(self, question):
            if self._unattended is not None:
                return ""
            holder = {"event": threading.Event(), "result": ""}
            self.ui_queue.put(("ui", None, "call", lambda: self._show_question(holder, question)))
            while not holder["event"].wait(0.2):
                if self.runner is None or self.runner.cancel.is_set():
                    return ""
            return holder["result"]

        def _show_question(self, holder, question):
            tr = self.transcript
            rid = tr.region(prefix="q")
            tr.write(rid, f"  Agent 想問你：{question}\n", "card_title")
            var = tk.StringVar()
            frame = tk.Frame(tr.text, bg=self.theme["canvas_chat"])
            entry = ttk.Entry(frame, textvariable=var, width=60)
            entry.pack(side="left", padx=(0, 6))

            def answer(skip=False):
                holder["result"] = "" if skip else var.get().strip()
                holder["event"].set()
                try:
                    frame.destroy()
                except tk.TclError:
                    pass
                tr.write(rid, f"  {'（略過）' if skip or not holder['result'] else '你的回答：' + holder['result']}\n", "card_done")
                self.conv["display"].append(["notice", f"Agent 問：{question}　你答：{holder['result'] or '（略過）'}"])

            ttk.Button(frame, text="回答", style="Primary.TButton", command=answer).pack(side="left", padx=(0, 6))
            ttk.Button(frame, text="略過", command=lambda: answer(True)).pack(side="left")
            entry.bind("<Return>", lambda _e: answer())
            tr.write(rid, "  ", "card_done")
            tr.embed(rid, frame)
            tr.write(rid, "\n", "card_done")
            self.pending_cards.append({"holder": holder})
            entry.focus_set()
            tr.scroll_end(force=True)
            self.agent_state = "等待你的回答"
            self._agent_status()
            self.bell()

        def _council_blocking(self, question):
            """consult_council 工具：在 Agent 的背景執行緒中跑一次 AI 討論，回傳整合結論。"""
            # tkinter 只能在主執行緒操作：請主執行緒準備討論設定，這裡等結果
            holder = {"event": threading.Event(), "value": None}

            def prepare():
                try:
                    holder["value"] = self._prepare_council(interactive=False)
                except Exception as exc:          # noqa: 保底
                    holder["value"] = f"{type(exc).__name__}：{exc}"
                holder["event"].set()

            self.ui_queue.put(("ui", None, "call", prepare))
            while not holder["event"].wait(0.2):
                if self.runner is None or self.runner.cancel.is_set():
                    raise ToolError("已停止")
            prepared = holder["value"]
            if isinstance(prepared, str):
                raise ToolError(prepared)
            agents, hub, mode, rounds, _notes = prepared
            if mode == MODE_PLAN or mode == MODE_RELAY:
                mode = MODE_SYNTH

            names = {a["id"]: a.get("name") or a["id"] for a in agents}
            if hub:
                names.setdefault(hub["id"], hub.get("name") or hub["id"])
            prog = {"phase": "準備中", "running": [], "done": 0}

            def emit(kind, *payload):
                # v6.9.1：除了階段，也顯示幾位完成、誰還在回答（雲端模型思考可能要好幾分鐘，畫面要看得出它在動）
                if kind == "phase":
                    prog.update(phase=payload[0], done=0)
                    prog["running"] = []
                elif kind == "start":
                    if payload[0] not in prog["running"]:
                        prog["running"].append(payload[0])
                elif kind == "done":
                    if payload[0] in prog["running"]:
                        prog["running"].remove(payload[0])
                    prog["done"] += 1
                else:
                    return
                text = prog["phase"]
                if prog["done"] or prog["running"]:
                    running = "、".join(names.get(p, p) for p in prog["running"][:3]) + ("…" if len(prog["running"]) > 3 else "")
                    text += f"（{prog['done']} 位完成" + (f"，回答中：{running}" if running else "") + "）"
                self.ui_queue.put(("ui", None, "call", lambda t=text: self._council_tool_progress(t)))

            p = self.prefs
            s = Session(agents, hub, mode, question, emit, self.runner.cancel, lambda pid, r: None,
                        system_prompt=self._prompt_with_context("council"), review_rounds=rounds,
                        options={"filter_think": p.get("filter_think", True), "include_usage": p.get("include_usage", True),
                                 "quote_limit": p.get("quote_limit", QUOTE_LIMIT_DEFAULT),
                                 "revise_char_limit": p.get("revise_char_limit", 0), "max_concurrent": p.get("max_concurrent", 4),
                                 "max_rpm": p.get("max_rpm", 0), "auto_retry": 2,
                                 "think_limit": p.get("think_limit", THINK_LIMIT_DEFAULT)})
            s.run()
            try:
                save_record(s.record)
            except OSError:
                pass
            final = s.record.get("final")
            if final and final.get("text"):
                return f"AI 討論團（{len(agents)} 位，{mode}）的整合結論：\n\n{final['text']}"
            answers = s.record.get("latest_answers") or {}
            if answers:
                names = {a["id"]: a["name"] for a in agents}
                return "AI 討論團沒有產生整合結論，以下是各自的回答：\n\n" + "\n\n".join(
                    f"## {names.get(k, k)}\n{v}" for k, v in answers.items())
            raise ToolError(s.record.get("error") or "AI 討論團沒有成功的回答。")

        def _council_tool_progress(self, text):
            if self.current_tool:
                self.transcript.set_tool_status(self.current_tool, f"討論中：{text}")
            self.agent_state = f"等 AI 討論團：{text}"
            self._agent_status()

        def _refresh_agent_panel(self):
            t = self.theme
            for box in (self.todo_box, self.change_box):
                for child in box.winfo_children():
                    child.destroy()
            todos = self.conv.get("todos") or []
            if not todos:
                ttk.Label(self.todo_box, text="Agent 處理多步驟任務時，會在這裡列出計畫與進度。",
                          style="PanelMuted.TLabel", wraplength=int(260 * self.scale), justify="left").pack(anchor="w")
            for item in todos:
                mark = {"completed": "☑", "in_progress": "◐"}.get(item.get("status"), "☐")
                style = "PanelMuted.TLabel" if item.get("status") == "completed" else "PanelText.TLabel"
                ttk.Label(self.todo_box, text=f"{mark}  {item.get('content')}", style=style,
                          wraplength=int(260 * self.scale), justify="left").pack(anchor="w", pady=1)
            changes = self.conv.get("changes") or []
            if not changes:
                ttk.Label(self.change_box, text="還沒有修改任何檔案。修改前會自動備份。", style="PanelMuted.TLabel",
                          wraplength=int(260 * self.scale), justify="left").pack(anchor="w")
            turns = sorted({c["turn"] for c in changes}, reverse=True)
            for turn in turns[:8]:
                items = [c for c in changes if c["turn"] == turn]
                row = ttk.Frame(self.change_box, style="Panel.TFrame")
                row.pack(fill="x", pady=(4, 0))
                undone = all(c.get("undone") for c in items)
                ttk.Label(row, text=f"第 {turn} 輪" + ("（已復原）" if undone else ""), style="PanelTitle.TLabel").pack(side="left")
                if not undone:
                    ttk.Button(row, text="復原", style="Panel.TButton",
                               command=lambda tn=turn: self.undo_turn(tn)).pack(side="right")
                for c in items[:12]:
                    lab = ttk.Label(self.change_box, text=f"  {c['kind']}　{c['path']}", style="PanelMuted.TLabel" if c.get("undone")
                                    else "PanelLink.TLabel", wraplength=int(260 * self.scale), cursor="hand2")
                    lab.pack(anchor="w")
                    lab.bind("<Button-1>", lambda _e, cc=c: self.show_diff(cc))
            self._refresh_ws_tab()

        # ───────────── 工作區分頁：資料夾工具、Git 狀態、檔案樹、預覽、差異、@引用 ─────────────
        MENTION_RE = re.compile(r'@"([^"]+)"|@([^\s@"「」，。；]+)')
        MENTION_MAX = 20000
        TREE_LIMIT = 400

        def _build_ws_tab(self, parent):
            t = self.theme
            self.ws_tab_frame = parent                # 拖放時用來判斷是不是放在「工作區」
            self.ws_title = ttk.Label(parent, text="", style="PanelTitle.TLabel", wraplength=int(250 * self.scale), justify="left")
            self.ws_title.pack(anchor="w")
            row = ttk.Frame(parent, style="Panel.TFrame")
            row.pack(fill="x", pady=(6, 2))
            self.ws_menu_btn = ttk.Menubutton(row, text="換資料夾 ▾", style="Panel.TMenubutton")
            self.ws_menu = tk.Menu(self.ws_menu_btn, tearoff=False, postcommand=self._fill_ws_menu)
            self.ws_menu_btn.configure(menu=self.ws_menu)
            self.ws_menu_btn.pack(side="left")
            ttk.Button(row, text="開啟", style="Panel.TButton", command=self._open_workspace).pack(side="left", padx=3)
            ttk.Button(row, text="↻", width=3, style="Panel.TButton", command=lambda: self._refresh_ws_tab(force=True)).pack(side="left")
            ttk.Button(row, text="＋ 加入檔案…", style="Panel.TButton", command=self.add_files_to_workspace).pack(side="left", padx=3)
            self.ws_info = ttk.Label(parent, text="", style="PanelMuted.TLabel", wraplength=int(250 * self.scale), justify="left")
            self.ws_info.pack(anchor="w", pady=(4, 4))
            row2 = ttk.Frame(parent, style="Panel.TFrame")
            row2.pack(fill="x", pady=(0, 8))
            ttk.Button(row2, text="專案規則", style="Panel.TButton", command=lambda: self.edit_ws_file("AGENTS.md")).pack(side="left")
            ttk.Button(row2, text="記憶檔", style="Panel.TButton",
                       command=lambda: self.edit_ws_file(f"{AGENT_DIR_NAME}/記憶.md")).pack(side="left", padx=3)
            ttk.Button(row2, text="權限", style="Panel.TButton", command=lambda: self.open_settings("Agent")).pack(side="left")
            self.branch_btn = ttk.Menubutton(row2, text="⑂ 分支 ▾", style="Panel.TMenubutton")
            self.branch_menu = tk.Menu(self.branch_btn, tearoff=False, postcommand=self._fill_branch_menu)
            self.branch_btn.configure(menu=self.branch_menu)
            self.branch_btn.pack(side="left", padx=3)
            self.ws_filter = tk.StringVar()
            fe = ttk.Entry(parent, textvariable=self.ws_filter)
            fe.pack(fill="x")
            self.ws_filter.trace_add("write", lambda *_a: self._schedule_tree())
            ttk.Label(parent, text="↑ 篩選檔名・雙擊預覽・右鍵 @引用・把檔案拖進來＝複製到工作資料夾",
                      style="PanelMuted.TLabel", wraplength=int(250 * self.scale), justify="left").pack(anchor="w", pady=(2, 4))
            wrap = ttk.Frame(parent, style="Panel.TFrame")
            wrap.pack(fill="both", expand=True)
            self.file_tree = ttk.Treeview(wrap, show="tree", selectmode="browse", style="Files.Treeview")
            vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.file_tree.yview)
            self.file_tree.configure(yscrollcommand=vsb.set)
            self.file_tree.pack(side="left", fill="both", expand=True)
            vsb.pack(side="right", fill="y")
            self.file_tree.bind("<<TreeviewOpen>>", self._tree_open)
            self.file_tree.bind("<Double-Button-1>", lambda _e: self._tree_activate())
            self.file_tree.bind("<Return>", lambda _e: self._tree_activate())
            self.file_tree.bind("<Button-3>", self._tree_menu)
            self._tree_ws, self._tree_job, self._git_text = None, None, ""

        def _fill_ws_menu(self):
            m = self.ws_menu
            m.delete(0, "end")
            recent = [p for p in (self.prefs.get("recent_workspaces") or []) if os.path.isdir(p)]
            for p in recent:
                m.add_command(label=p, command=lambda pp=p: self.set_workspace(pp))
            if recent:
                m.add_separator()
            m.add_command(label="選擇其他資料夾…", command=self.choose_workspace)

        def _ws_root(self):
            ws = self.conv.get("workspace") if getattr(self, "conv", None) else ""
            return ws if ws and os.path.isdir(ws) else ""

        def _refresh_ws_tab(self, force=False):
            if not hasattr(self, "file_tree"):
                return
            ws = self._ws_root()
            if not ws:
                self.ws_title.configure(text="尚未選擇工作資料夾")
                self.ws_info.configure(text="Agent 只能存取這個資料夾內的檔案。按「換資料夾」選擇。")
                self.file_tree.delete(*self.file_tree.get_children())
                self._tree_ws = None
                return
            has_agents = os.path.isfile(os.path.join(ws, "AGENTS.md"))
            has_mem = os.path.isfile(os.path.join(ws, AGENT_DIR_NAME, "記憶.md"))
            self.ws_title.configure(text=os.path.basename(ws.rstrip("\\/")) or ws)
            self.ws_info.configure(text=f"{ws}\n{self._git_text or 'Git：檢查中…'}\n"
                                        f"專案規則 AGENTS.md：{'有，會自動讀入' if has_agents else '沒有（按「專案規則」建立）'}\n"
                                        f"記憶檔：{'有' if has_mem else '沒有'}　備份：{AGENT_DIR_NAME}/備份/")
            if force or self._tree_ws != ws:
                if self._tree_ws != ws:
                    self._git_text = ""
                self._tree_ws = ws
                self._reload_tree()
                self._check_git(ws)

        def _check_git(self, ws):
            def work():
                text = ""
                try:
                    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    risk = git_config_risk(ws)
                    if risk:                 # 惡意的 .git/config 能讓 git status 執行程式：不自動執行
                        log_app.warning("工作資料夾的 Git 設定有風險，略過自動 git status：%s", risk)
                        self.ui_queue.put(("ui", None, "call",
                                           lambda: self._git_done(ws, "Git：⚠ 這個儲存庫的設定會執行外部程式，未自動讀取")))
                        return
                    r = subprocess.run(["git", *SAFE_GIT_ARGS, "-C", ws, "status", "--porcelain=v1", "-b"],
                                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5,
                                       creationflags=flags, env=scrubbed_env(), stdin=subprocess.DEVNULL)
                    if r.returncode == 0:
                        lines = r.stdout.splitlines()
                        head = lines[0][3:] if lines and lines[0].startswith("## ") else "?"
                        branch = head.split("...")[0].replace("No commits yet on ", "")
                        n = len(lines) - 1
                        text = f"Git：{branch}・" + (f"{n} 個檔案有變更" if n else "沒有未提交的變更")
                    else:
                        text = "Git：不是 Git 儲存庫"
                except FileNotFoundError:
                    text = "Git：電腦上沒有安裝 Git"
                except Exception as exc:
                    text = f"Git：無法檢查（{exc.__class__.__name__}）"
                self.ui_queue.put(("ui", None, "call", lambda: self._git_done(ws, text)))

            threading.Thread(target=work, daemon=True).start()

        def _git_done(self, ws, text):
            if ws == self._ws_root():
                self._git_text = text
                self._refresh_ws_tab()

        def _schedule_tree(self):
            if self._tree_job:
                self.after_cancel(self._tree_job)
            self._tree_job = self.after(250, self._reload_tree)

        def _list_dir_sorted(self, full):
            try:
                names = os.listdir(full)
            except OSError:
                return [], []
            dirs = sorted((n for n in names if os.path.isdir(os.path.join(full, n)) and n not in SKIP_DIRS), key=str.lower)
            files = sorted((n for n in names if os.path.isfile(os.path.join(full, n))), key=str.lower)
            return dirs, files

        def _reload_tree(self):
            self._tree_job = None
            tree = self.file_tree
            tree.delete(*tree.get_children())
            ws = self._ws_root()
            if not ws:
                return
            q = self.ws_filter.get().strip().lower()
            if q:      # 篩選：平鋪列出符合的檔案
                count = 0
                for root, dirs, files in os.walk(ws):
                    dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
                    for name in sorted(files, key=str.lower):
                        rel = os.path.relpath(os.path.join(root, name), ws).replace("\\", "/")
                        if q in rel.lower():
                            tree.insert("", "end", iid="f:" + rel, text=rel)
                            count += 1
                            if count >= self.TREE_LIMIT:
                                tree.insert("", "end", iid="more", text=f"…超過 {self.TREE_LIMIT} 個，請縮小篩選")
                                return
                if not count:
                    tree.insert("", "end", iid="none", text="沒有符合的檔案")
                return
            self._fill_tree_level("", "")

        def _fill_tree_level(self, parent, rel_dir):
            ws = self._ws_root()
            dirs, files = self._list_dir_sorted(os.path.join(ws, rel_dir) if rel_dir else ws)
            for d in dirs:
                rel = f"{rel_dir}/{d}" if rel_dir else d
                node = self.file_tree.insert(parent, "end", iid="d:" + rel, text=d + "/", open=False)
                self.file_tree.insert(node, "end", iid="x:" + rel, text="…")
            for i, f in enumerate(files):
                if i >= self.TREE_LIMIT:
                    self.file_tree.insert(parent, "end", iid=f"more:{rel_dir}", text=f"…還有 {len(files) - i} 個檔案（請用篩選）")
                    break
                rel = f"{rel_dir}/{f}" if rel_dir else f
                self.file_tree.insert(parent, "end", iid="f:" + rel, text=f)

        def _tree_open(self, _e=None):
            node = self.file_tree.focus()
            if not node.startswith("d:"):
                return
            rel = node[2:]
            placeholder = "x:" + rel
            if self.file_tree.exists(placeholder):
                self.file_tree.delete(placeholder)
                self._fill_tree_level(node, rel)

        def _tree_selected_rel(self):
            node = self.file_tree.focus()
            return node[2:] if node.startswith("f:") else ""

        def _tree_activate(self):
            rel = self._tree_selected_rel()
            if rel:
                self.preview_file(rel)

        def _tree_menu(self, event):
            node = self.file_tree.identify_row(event.y)
            if not node or not node.startswith(("f:", "d:")):
                return
            self.file_tree.selection_set(node)
            self.file_tree.focus(node)
            rel, is_file = node[2:], node.startswith("f:")
            m = tk.Menu(self, tearoff=False)
            if is_file:
                m.add_command(label="加入對話（@引用，內容會附給 Agent）", command=lambda: self.mention_file(rel))
                m.add_command(label="預覽", command=lambda: self.preview_file(rel))
            else:
                m.add_command(label="加入對話（@引用資料夾，讓 Agent 去看）", command=lambda: self.mention_file(rel))
            m.add_command(label="用系統程式開啟", command=lambda: open_path(os.path.join(self._ws_root(), rel)))
            m.add_command(label="複製相對路徑", command=lambda: (self.clipboard_clear(), self.clipboard_append(rel)))
            m.tk_popup(event.x_root, event.y_root)

        def mention_file(self, rel):
            token = f'@"{rel}"' if re.search(r'[\s「」，。；]', rel) else f"@{rel}"
            self.prompt.insert("insert", token + " ")
            self.prompt.focus_set()

        def _safe_ws_path(self, rel):
            ws = self._ws_root()
            if not ws:
                return None
            root = os.path.realpath(ws)
            full = os.path.realpath(os.path.join(root, rel))
            if full != root and not full.startswith(root + os.sep):
                return None
            return full

        @staticmethod
        def _read_text_file(full, limit):
            with open(full, "rb") as f:
                raw = f.read(limit * 4 + 4)
            if b"\0" in raw[:4096]:
                return None, False
            for enc in ("utf-8", "utf-8-sig", "cp950", "latin-1"):
                try:
                    text = raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            truncated = len(text) > limit or os.path.getsize(full) > len(raw)
            return text[:limit], truncated

        def _expand_mentions(self, text):
            """把訊息中的 @檔案 換成「附上檔案內容」；@資料夾 則附上內容清單。回傳（給 Agent 的文字, 附上的路徑）。"""
            if "@" not in text or not self._ws_root():
                return text, []
            extra, attached = [], []
            for m in self.MENTION_RE.finditer(text):
                rel = (m.group(1) or m.group(2) or "").strip().rstrip(".,;:)）")
                full = self._safe_ws_path(rel)
                if not rel or rel in attached or full is None:
                    continue
                if os.path.isfile(full):
                    try:
                        content, truncated = self._read_text_file(full, self.MENTION_MAX)
                    except OSError:
                        continue
                    if content is None:
                        extra.append(f"\n\n[使用者引用的檔案：{rel}]（二進位檔，無法附上內容）")
                    else:
                        extra.append(f"\n\n[使用者引用的檔案：{rel}]\n```\n{content}\n```"
                                     + (f"\n（檔案過長，只附前 {self.MENTION_MAX} 字；需要時請用 read_file 分段讀取）" if truncated else ""))
                    attached.append(rel)
                elif os.path.isdir(full):
                    dirs, files = self._list_dir_sorted(full)
                    listing = "\n".join([d + "/" for d in dirs][:100] + files[:200])
                    extra.append(f"\n\n[使用者引用的資料夾：{rel}/]\n{listing}")
                    attached.append(rel + "/")
            return text + "".join(extra), attached

        def _text_window(self, title, text="", editable=False, mono=True, size=(760, 560)):
            t = self.theme
            win = tk.Toplevel(self)
            win.title(title)
            win.configure(bg=t["surface"])
            win.transient(self)
            win.geometry(f"{int(size[0] * self.scale)}x{int(size[1] * self.scale)}")
            bar = ttk.Frame(win, style="Surface.TFrame", padding=(10, 8))
            bar.pack(side="bottom", fill="x")
            frame = ttk.Frame(win, style="Surface.TFrame", padding=(10, 10, 10, 0))
            frame.pack(fill="both", expand=True)
            box = tk.Text(frame, wrap="none" if mono else "word", undo=editable, relief="flat", bd=0,
                          font=self.fonts["mono" if mono else "ui"], bg=t["surface2"], fg=t["text"],
                          insertbackground=t["text"], selectbackground=t["accent_soft"], padx=8, pady=6)
            vsb = ttk.Scrollbar(frame, orient="vertical", command=box.yview)
            hsb = ttk.Scrollbar(frame, orient="horizontal", command=box.xview)
            box.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
            vsb.pack(side="right", fill="y")
            hsb.pack(side="bottom", fill="x")
            box.pack(fill="both", expand=True)
            box.insert("1.0", text)
            if not editable:
                box.configure(state="disabled")
            return win, box, bar

        def preview_file(self, rel):
            full = self._safe_ws_path(rel)
            if not full or not os.path.isfile(full):
                return
            if media_kind(full):                  # 圖片、影片、音檔：用作品檢視（以前只顯示「二進位檔，無法預覽」）
                self.open_media(full)
                return
            try:
                content, truncated = self._read_text_file(full, 200000)
            except OSError as exc:
                messagebox.showerror(APP_NAME, f"無法讀取：{exc}")
                return
            size = os.path.getsize(full)
            if content is None:
                content = f"（二進位檔，{size:,} bytes，無法預覽。可用「用系統程式開啟」。）"
            elif truncated:
                content += "\n\n……（檔案過長，只預覽前 200,000 字）"
            win, box, bar = self._text_window(f"預覽：{rel}（{size:,} bytes）", content)
            ttk.Button(bar, text="加入對話（@引用）", style="Primary.TButton",
                       command=lambda: (self.mention_file(rel), win.destroy())).pack(side="right")
            ttk.Button(bar, text="用系統程式開啟", style="Ghost.TButton", command=lambda: open_path(full)).pack(side="right", padx=6)

        AGENTS_TEMPLATE = ("# 專案規則（AGENTS.md）\n\nAgent 每次對話都會先讀這個檔案。寫下這個資料夾的背景與規則。\n\n"
                           "## 專案說明\n- \n\n## 規則\n- 一律使用台灣繁體中文\n- 修改檔案前先說明計畫\n- 不要刪除任何檔案\n\n"
                           "## 常用指令\n- \n")

        def edit_ws_file(self, rel):
            """內建編輯器：專案規則 AGENTS.md、記憶檔。儲存前把舊版備份到 .ai協作/備份/。"""
            full = self._safe_ws_path(rel)
            if not full:
                messagebox.showinfo(APP_NAME, "請先選擇工作資料夾。")
                return
            exists = os.path.isfile(full)
            if exists:
                content, _t = self._read_text_file(full, 500000)
                content = content or ""
            else:
                content = self.AGENTS_TEMPLATE if rel == "AGENTS.md" else "# Agent 記憶\n\n"
            label = "專案規則" if rel == "AGENTS.md" else "記憶檔"
            win, box, bar = self._text_window(f"{label}：{rel}" + ("" if exists else "（新檔，儲存後建立）"), content,
                                              editable=True, mono=False, size=(720, 560))
            note = ttk.Label(bar, text="儲存前會自動備份舊版到 " + AGENT_DIR_NAME + "/備份/", style="Muted.TLabel")
            note.pack(side="left")

            def save():
                text = box.get("1.0", "end-1c")
                try:
                    if os.path.isfile(full):
                        bdir = os.path.join(self._ws_root(), AGENT_DIR_NAME, "備份")
                        os.makedirs(bdir, exist_ok=True)
                        shutil.copy2(full, os.path.join(bdir, time.strftime("%Y%m%d_%H%M%S_") + "手動編輯_" +
                                                        os.path.basename(full)))
                    os.makedirs(os.path.dirname(full), exist_ok=True)
                    with open(full, "w", encoding="utf-8", newline="\n") as f:
                        f.write(text)
                except OSError as exc:
                    messagebox.showerror(APP_NAME, f"無法儲存：{exc}", parent=win)
                    return
                note.configure(text=f"已儲存 {time.strftime('%H:%M:%S')}")
                self.runner_key = None          # 下一輪重新讀入專案規則與記憶
                self._refresh_ws_tab(force=True)

            ttk.Button(bar, text="儲存", style="Primary.TButton", command=save).pack(side="right")
            win.bind("<Control-s>", lambda _e: (save(), "break")[1])

        def show_diff(self, change):
            """顯示某個變更的差異：備份（修改前）↔ 目前的檔案。"""
            ws = self._ws_root()
            if not ws:
                return
            full = self._safe_ws_path(change["path"])
            backup = change.get("backup")

            def lines_of(path):
                if not path or not os.path.isfile(path):
                    return []
                text, _t = self._read_text_file(path, 400000)
                return (text or "（二進位檔）").splitlines(keepends=True)

            old, new = lines_of(backup), lines_of(full)
            diff = list(difflib.unified_diff(old, new, fromfile=f"修改前　{change['path']}",
                                             tofile=f"目前　{change['path']}" + ("（已復原）" if change.get("undone") else ""), n=3))
            if not diff:
                body = "（沒有差異：目前的檔案和修改前相同，可能已被復原或又改回去了）"
            else:
                body = "".join(x if x.endswith("\n") else x + "\n" for x in diff)
            if not os.path.isfile(full or ""):
                body = "（目前檔案已不存在；可能已復原，原檔在 .ai協作/已復原/）\n\n" + body
            win, box, bar = self._text_window(f"差異：{change['path']}（第 {change['turn']} 輪・{change['kind']}・{change.get('time', '')}）", "")
            t = self.theme
            box.configure(state="normal")
            box.tag_configure("add", background=mix(t["success"], t["surface2"], 0.82), foreground=t["text"])
            box.tag_configure("del", background=mix(t["danger"], t["surface2"], 0.82), foreground=t["text"])
            box.tag_configure("hunk", foreground=t["accent"])
            box.tag_configure("head", foreground=t["muted"])
            for line in body.splitlines(keepends=True):
                tag = ("head" if line.startswith(("---", "+++")) else "hunk" if line.startswith("@@")
                       else "add" if line.startswith("+") else "del" if line.startswith("-") else "")
                box.insert("end", line, (tag,) if tag else ())
            box.configure(state="disabled")
            ttk.Label(bar, text=f"＋ 新增 {sum(1 for x in diff if x.startswith('+') and not x.startswith('+++'))} 行　"
                                f"－ 刪除 {sum(1 for x in diff if x.startswith('-') and not x.startswith('---'))} 行",
                      style="Muted.TLabel").pack(side="left")
            if full and os.path.isfile(full):
                ttk.Button(bar, text="開啟檔案", style="Ghost.TButton", command=lambda: open_path(full)).pack(side="right")

        def undo_turn(self, turn):
            if self.busy:
                return
            ws = self.runner.ws if self.runner else Workspace(self.conv["workspace"], self.conv["id"])
            ws.changes = self.conv.setdefault("changes", [])
            if not messagebox.askyesno(APP_NAME, f"要復原第 {turn} 輪的檔案修改嗎？\n（目前的版本會先另存到 {AGENT_DIR_NAME}/已復原/，不會刪除）"):
                return
            try:
                restored = ws.undo_turn(turn)
            except (OSError, ToolError) as exc:
                messagebox.showerror(APP_NAME, f"復原失敗：{exc}")
                return
            elsewhere = sorted({c.get("root") for c in ws.changes if c.get("turn") == turn and not c.get("undone")
                                and c.get("root") and os.path.normcase(c["root"]) != os.path.normcase(ws.root)})
            if elsewhere:
                messagebox.showinfo(APP_NAME, f"第 {turn} 輪有修改是在「{'、'.join(elsewhere)}」做的，目前的工作資料夾不同，"
                                              "這些沒有復原（以免蓋掉新資料夾裡同名的檔案）。要復原請先換回那個資料夾。")
            if not restored:
                return
            msg = f"↺ 已復原第 {turn} 輪的修改：{'、'.join(restored)}"
            self.transcript.notice(msg)
            self.conv["display"].append(["notice", msg])
            if self.runner:
                self.runner.messages.append({"role": "user", "content": f"（系統通知：使用者已復原第 {turn} 輪對這些檔案的修改：{'、'.join(restored)}）"})
            self._save_conv()
            self._refresh_agent_panel()

        # ───────────── AI 討論 ─────────────
        def _prepare_council(self, interactive=True):
            """檢查參與的 AI 與主持 AI。回傳 (agents, hub, mode, rounds, notes) 或錯誤訊息字串。"""
            selected = [s for s in self.services if s.get("enabled", True)]
            if not selected:
                return "沒有參與的 AI。請到「設定 → 模型與 API」勾選「參與」。"
            mode = self.mode_var.get()
            uses_hub = mode in (MODE_SYNTH, MODE_REVIEW, MODE_PLAN)
            notes = []
            hub_service = self._service(self.prefs.get("hub_id")) if uses_hub else None
            if uses_hub and hub_service in selected and len(selected) > 2 and self.prefs.get("hub_exclusive", True):
                selected = [s for s in selected if s is not hub_service]
                notes.append(f"主持 AI「{hub_service.get('name')}」只負責主持，不參與回答。")
            agents, errors = [], []
            for s in list(selected):
                if s.get("model") and not likely_chat_model(s["model"]):
                    kind = model_kind_label(s["model"])
                    notes.append(f"略過「{s.get('name')}」：{short_model(s['model'])} 看起來是{kind}模型，不能一般對話（點機器人可換模型）。")
                    selected.remove(s)
            if hub_service is not None and hub_service.get("model") and not likely_chat_model(hub_service["model"]):
                return f"主持 AI「{hub_service.get('name')}」的模型 {hub_service['model']} 看起來不是對話模型，請換一個。"
            for s in selected:
                cfg, err = self._resolve(s)
                if err:
                    errors.append(err)
                else:
                    agents.append(cfg)
            if not agents:
                return "所有 AI 的設定都有問題：\n" + "\n".join(errors)
            groups = {}
            for a in agents:
                groups.setdefault(a["model"], []).append(a)
            spread = [0.3, 0.9, 1.2, 0.6, 1.0, 0.45, 0.75]
            for model, items in groups.items():
                if len(items) > 1:
                    msg = f"{len(items)} 位使用同一個模型（{short_model(model)}），意見容易同質化，建議混用不同模型"
                    if self.prefs.get("spread_temperature", True):
                        for i, a in enumerate(items):
                            if not str(a.get("temperature") or "").strip():
                                a["temperature"] = str(spread[i % len(spread)])
                        msg += "；已自動讓它們使用不同溫度"
                    notes.append(msg + "。")
            hub = None
            if uses_hub and len(agents) > 1:
                hub, err = self._resolve(hub_service) if hub_service else (None, "尚未選擇主持 AI。")
                if err:
                    if not interactive:
                        mode, hub = MODE_PARALLEL, None
                    elif messagebox.askyesno(APP_NAME, f"主持 AI 設定有問題：\n{err}\n\n要改用「平行回答」（不彙整）繼續嗎？"):
                        mode, hub = MODE_PARALLEL, None
                    else:
                        return ""
            rounds = int(self.prefs.get("review_rounds", 1))
            if interactive:
                calls = expected_calls(mode, len(agents), rounds, bool(hub))
                if errors or (self.prefs.get("confirm_big_runs", True) and calls >= 10):
                    text = (f"模式：{mode}｜{len(agents)} 位 AI" + (f"｜互評 {rounds} 輪" if mode == MODE_REVIEW else "")
                            + f"\n預計呼叫約 {calls} 次" + ("（意見穩定時會提前結束）" if mode == MODE_REVIEW else ""))
                    est = self._estimate_secs(agents, hub, mode, rounds)
                    if est:
                        text += "，依過去速度預估" + (f"約 {round(est / 60)} 分鐘" if est >= 90 else "不到 2 分鐘")
                    if hub and mode in (MODE_SYNTH, MODE_REVIEW) and self.prefs.get("auto_route", True):
                        text += "\n（主持 AI 會先判斷：如果是簡單問題，只呼叫 1 次就直接回答）"
                    if errors or notes:
                        text += "\n\n請注意：\n• " + "\n• ".join(errors + notes)
                    if not messagebox.askyesno(APP_NAME, text + "\n\n要開始嗎？"):
                        return ""
            return agents, hub, mode, rounds, notes

        def _estimate_secs(self, agents, hub, mode, rounds):
            """依各模型過去的平均回應時間粗估整場討論要多久（沒有資料就回傳 0）。"""
            lat = self.prefs.get("latency") or {}
            times = [lat.get(a.get("model")) for a in agents]
            known = [t for t in times if t]
            if not known:
                return 0
            fill = sorted(known)[len(known) // 2]
            times = sorted(t or fill for t in times)
            slowest = times[-1]
            factor = float(self.prefs.get("straggler_factor") or 0)
            if factor and len(times) >= 3:
                slowest = min(slowest, max(float(self.prefs.get("straggler_min_sec") or 90), factor * times[len(times) // 2]))
            per_round = slowest
            n_rounds = 1 + (rounds if mode == MODE_REVIEW else 0)
            total = per_round + (n_rounds - 1) * per_round * 1.3
            if hub:
                total += (lat.get(hub.get("model")) or fill) * 1.5
            return total

        def _learn_latency(self, record):
            lat = self.prefs.setdefault("latency", {})
            models = {a["id"]: a.get("model") for a in record.get("agents") or []}
            for rnd in record.get("rounds") or []:
                if rnd.get("round") != 1:
                    continue
                for pid, res in (rnd.get("answers") or {}).items():
                    m = models.get(pid)
                    if m and res.get("status") == "done" and res.get("elapsed"):
                        old = lat.get(m)
                        lat[m] = round(res["elapsed"] if not old else old * 0.6 + res["elapsed"] * 0.4, 1)
            hub = record.get("hub") or {}
            res = record.get("hub_result") or {}
            if hub.get("model") and res.get("status") == "done" and res.get("elapsed"):
                old = lat.get(hub["model"])
                lat[hub["model"]] = round(res["elapsed"] if not old else old * 0.6 + res["elapsed"] * 0.4, 1)
            if len(lat) > 200:
                for k in list(lat)[:len(lat) - 200]:
                    lat.pop(k, None)

        def start_council(self, text, seed=None, review_rounds=None, show_user=True):
            template_only = any(v.strip() and text == v.strip() for v in self.templates.values())
            if seed is None and (template_only or (len(text) <= 80 and text.rstrip().endswith(("：", ":")))):
                if not messagebox.askyesno(APP_NAME, "提示詞看起來只有範本或開頭說明，冒號後面沒有真正的題目。\n\n確定要直接送出嗎？"):
                    return False
            if seed is None and self.prefs.get("quick_small_talk", True) and is_small_talk(text):
                quick = self._quick_responder()
                if quick:
                    if show_user:
                        if not self.conv.get("display"):
                            self.transcript.clear()
                        self.transcript.user_message(text + self._image_note())
                        self.conv["display"].append(["user", text + self._image_note()])
                    self._run_council([quick], None, MODE_PARALLEL, text, 0,
                                      [f"這則訊息很短（打招呼／閒聊），只請「{quick['name']}」直接回答，不啟動多 AI 討論。"
                                       "要完整討論，請在訊息加上「完整討論」。"], None)
                    return True
            if seed:
                prepared = self._prepare_seeded(seed)
            else:
                prepared = self._prepare_council(interactive=True)
            if isinstance(prepared, str):
                if prepared:
                    messagebox.showerror(APP_NAME, prepared)
                return False
            agents, hub, mode, rounds, notes = prepared
            if review_rounds is not None:
                rounds = review_rounds
            if show_user:
                if not self.conv.get("display"):
                    self.transcript.clear()
                self.transcript.user_message(text + self._image_note())
                self.conv["display"].append(["user", text + self._image_note()])
            if self.attach_images and seed is None:
                blind = [a["name"] for a in agents + ([hub] if hub else []) if not supports_vision(a.get("model"))]
                if blind:
                    notes.append(f"你附了 {len(self.attach_images)} 張圖片；{'、'.join(blind[:6])} 不是視覺模型，看不到圖片。")
            self._run_council(agents, hub, mode, text, rounds, notes, seed)
            return True

        def _prompt_with_context(self, kind):
            base = (self.prefs.get("system_prompt") or "").strip()
            return (base + "\n\n" if base else "") + self._capability_text(kind)

        def _capability_text(self, kind):
            """告訴模型「你在什麼程式裡、這個程式實際能做什麼、要做到更多需要什麼」。
            沒有這段時，問「你能做什麼」只會得到一般 LLM 的制式回答（例如「我不能上網、不能執行程式」），和這個程式的實際能力不符。"""
            p = self.prefs
            perms = dict(DEFAULT_PERMISSIONS, **(p.get("agent_perms") or {}))
            perm_label = {PERM_ALLOW: "允許", PERM_ASK: "要先問使用者", PERM_DENY: "禁止"}
            perm_text = "、".join(f"{TOOL_CATEGORIES[k]}＝{perm_label.get(v, v)}" for k, v in perms.items() if k in TOOL_CATEGORIES)
            team = "、".join(f"{x.get('name')}（{short_model(x.get('model'))}" + ("，本機" if is_local_url(x.get("url")) else "") + "）"
                            for x in self.services if x.get("enabled", True))[:600]
            agent = self._service(p.get("agent_model_id"))
            agent_txt = f"{agent.get('name')}（{short_model(agent.get('model'))}）" if agent else "未設定"
            where = "「AI 討論」模式（多位 AI 各自回答 → 匿名互評 → 主持 AI 整合）" if kind == "council" else "「Agent」模式"
            lines = [
                "【關於你所在的程式】只有在使用者問到「你／這個工具能做什麼」「需要什麼才能做更多」，或要求做需要工具的事時才用到；"
                "回答時依照下面的實際情況，不要用一般大型語言模型的制式說法（例如籠統地說「我不能上網、不能執行程式」）。",
                f"你是在使用者電腦上的「AI 協作工作台 {APP_VERSION}」（單一 Python 程式 AI協作.py）裡被呼叫，目前是{where}。",
                "這個程式有兩種對話：",
                "1. AI 討論：每位 AI 用文字回答，看不到使用者的檔案、不能執行程式（使用者用「附加檔案」貼進來的文字與圖片例外）。"
                "主持 AI 會先判斷：簡單問題直接回答；需要最新資訊時，程式會在討論前先上網搜尋並把結果給大家（可在設定關閉）；"
                "需要動手做的事建議改用 Agent。",
                "2. Agent：一位 AI 帶著工具，在使用者指定的「工作資料夾」裡做事：列目錄、讀檔、搜尋檔案內容、新建或修改檔案"
                "（修改前自動備份、可一鍵復原，沒有刪除功能）、在工作資料夾執行命令列指令（Windows cmd，可以跑 Python 等程式）、"
                "上網搜尋與讀網頁（DuckDuckGo，不需金鑰）、把問題交給 AI 討論團、反問使用者、列任務清單、把事情記到 .ai協作/記憶.md；"
                "工作資料夾裡的 AGENTS.md 會當作專案規則自動讀入。"
                "也可以透過使用者設定的 MCP 外部工具操作瀏覽器、桌面程式、雲端服務等（每次使用前請使用者核准）。",
                "其他功能：附加圖片給視覺模型看；語音檔可用 whisper 類模型轉成文字；排程可以在指定時間自動執行 Agent 任務或 AI 討論"
                "（程式關著時可由 Windows 工作排程器啟動）；對話可搜尋、匯出成 Markdown。",
                f"目前設定：Agent 權限 {perm_text}；網路搜尋{'開啟' if p.get('agent_web_search', True) else '關閉'}；"
                f"Agent 模型 {agent_txt}；AI 團隊 {team or '未設定'}；"
                f"討論前上網查證{'開啟' if p.get('web_research', True) else '關閉'}；"
                f"外部工具（MCP）{('已連線：' + '、'.join(sorted({t['server'] for t in self.mcp.agent_tools().values()}))) if self.mcp.agent_tools() else '未連線'}。",
                "要做到更多，使用者可以：切到 Agent 對話並選工作資料夾（要讀寫檔案、執行程式、上網查資料時）；"
                "選支援工具呼叫（function calling）的大模型當 Agent 模型（小模型常常不會用工具）；"
                "在「設定 → Agent」放寬權限或開啟網路搜尋；用環境變數加入更多服務的 API 金鑰（OpenAI、Groq、OpenRouter 等），"
                "或用 Ollama、LM Studio 跑本機模型；在工作資料夾放 AGENTS.md 寫下專案背景與規則；"
                "要看圖片就選視覺模型（模型清單的「視覺」分頁）；要語音轉文字就新增一位 whisper 模型的 AI（OpenAI 或 Groq）；"
                "要操作瀏覽器、桌面或雲端帳號，就在「設定 → 外部工具 MCP」接上對應的 MCP 伺服器（例如 Playwright、Windows-MCP、"
                "GitHub、Google 服務的 MCP 伺服器）；要定時執行就用「設定 → 排程」。",
                "這個程式目前還做不到：即時錄音（只能附語音檔）、把圖片直接貼上（要用附加檔案）、刪除檔案（刻意不做）。"
                "MCP 能做什麼取決於使用者接上的伺服器。被問到時要老實說明。",
            ]
            if kind == "agent":
                lines.append("你就是上面說的 Agent：需要時直接用工具去做，不要說自己不能讀檔、不能上網或不能執行程式。")
            return "\n".join(lines)

        def verify_with_agent(self, final_text):
            """把討論產出的程式專案交給 Agent 實際執行並修正：抽出檔案 → 寫到新資料夾 → 開 Agent 對話並帶入指示。"""
            if self.busy:
                self.status_label.configure(text="執行中，請先等這一輪結束。")
                return
            files = extract_code_project(final_text)
            if not files:
                self.status_label.configure(text="這份成果裡沒有找到可以執行的程式檔。")
                return
            base = filedialog.askdirectory(title="選擇要放驗證專案的資料夾（會在裡面建立新的子資料夾）",
                                           initialdir=self.conv.get("workspace") or self.prefs.get("last_workspace") or APP_DIR)
            if not base:
                return
            folder = os.path.join(base, "驗證專案_" + _dt.datetime.now().strftime("%Y%m%d_%H%M%S"))
            written, skipped = [], []
            try:
                for f in files:
                    dest = os.path.normpath(os.path.join(folder, f["name"]))
                    if not dest.startswith(os.path.normpath(folder) + os.sep):      # 防止 ../ 跳出資料夾
                        skipped.append(f["name"])
                        continue
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with open(dest, "w", encoding="utf-8", newline="") as out:
                        out.write(f["code"])
                    written.append(f["name"])
            except OSError as exc:
                self.status_label.configure(text=f"建立檔案失敗：{exc}")
                return
            if not written:
                self.status_label.configure(text="沒有成功建立任何檔案。")
                return
            self.new_conversation("agent")
            self.conv["workspace"] = folder
            self.conv["mode"] = "build"                 # 要實際執行與修正，用「執行」模式
            self._update_header()
            self._refresh_agent_panel()
            listing = "、".join(written)
            prompt = ("我已經把一場 AI 討論產出的程式專案寫到這個工作資料夾了。請幫我驗證它能不能真的跑：\n"
                      f"1. 先用 read_file 看過這些檔案：{listing}。\n"
                      "2. 實際執行主程式（若有測試檔，也把測試跑起來）。\n"
                      "3. 遇到錯誤、例外或不如預期的行為，就用 edit_file 修正，再重跑，直到能正常執行或測試通過；"
                      "每次最多試幾輪，卡住就把問題和你的判斷回報我。\n"
                      "4. 完成後，條列你改了哪些檔案、為什麼改，以及最後的執行或測試結果。\n"
                      "注意：不要刪除任何檔案（要清理就移到 .ai協作/ 底下）。")
            self.prompt.delete("1.0", "end")
            self.prompt.insert("1.0", prompt)
            self.prompt.focus_set()
            note = f"已把 {len(written)} 個檔案寫到：{folder}"
            if skipped:
                note += f"（略過不安全的路徑：{'、'.join(skipped)}）"
            log_app.info("交給 Agent 驗證：%d 檔 → %s", len(written), folder)
            answer = messagebox.askyesnocancel(
                APP_NAME, note + "\n\n要讓 Agent 在這個新資料夾裡直接修改檔案與執行指令嗎？\n"
                "（只限這次驗證、只限這個資料夾；刪除、覆寫、讀取金鑰這類動作仍會先問你）\n\n"
                "是：授權並馬上開始驗證\n否：馬上開始，但每一步都跳出核准卡\n取消：先不要開始，只帶入指示")
            if answer is None:
                self.transcript.notice("✓ " + note + "。確認右上角的模型後按「送出」，Agent 會實際執行並修正。")
                self.status_label.configure(text=note + "；按「送出」開始驗證。")
                return
            if answer:
                self.conv["verify_allow"] = folder
            self.transcript.notice("✓ " + note + ("。已授權在這個資料夾直接修改與執行。" if answer else "。"))
            self.after(150, self.send)

        def handoff_to_agent(self, prompt):
            """把 AI 討論裡的請求交給 Agent：開新的 Agent 對話並帶入原本的訊息，使用者確認資料夾後按送出。"""
            if self.busy:
                return
            self.new_conversation("agent")
            self.prompt.delete("1.0", "end")
            self.prompt.insert("1.0", prompt)
            self.prompt.focus_set()
            hint = "已帶入你的訊息。" + ("確認右上角的工作資料夾與模型後按「送出」。" if self.conv.get("workspace")
                                         else "請先在右上角選擇工作資料夾，再按「送出」。")
            self.status_label.configure(text=hint)

        def _quick_responder(self):
            hub = self._service(self.prefs.get("hub_id"))
            for s in [hub] + [x for x in self.services if x.get("enabled", True)]:
                if s and likely_chat_model(s.get("model")):
                    cfg, err = self._resolve(s)
                    if not err:
                        return cfg
            return None

        def _prepare_seeded(self, seed):
            agents = []
            for pid in seed["answers"]:
                service = self._service(pid)
                if service:
                    cfg, _err = self._resolve(service)
                    agents.append(cfg or {"id": pid, "name": service.get("name") or pid, "role": service.get("role"),
                                          "model": service.get("model", ""), "url": service.get("url", ""), "key": ""})
            if not agents:
                return "紀錄中的 AI 都已不在設定清單裡，無法重新彙整。"
            hub_service = self._service(self.prefs.get("hub_id"))
            hub, err = self._resolve(hub_service) if hub_service else (None, "尚未選擇主持 AI。")
            if err:
                return f"主持 AI 設定有問題：{err}"
            return agents, hub, MODE_SYNTH, 0, []

        def _run_council(self, agents, hub, mode, prompt, rounds, notes, seed=None):
            self.cancel_event = token = threading.Event()
            self.token = token
            with self.active_lock:
                self.active.clear()
            self.buffers, self.call_started, self.usage = {}, {}, {}
            n = len(agents)
            self.expected = expected_calls(mode, n, rounds, bool(hub)) if not seed else (1 if hub else 0)
            self.done_calls = 0
            self.run_started = time.monotonic()
            self.phase_text = f"{mode}｜{n} 位 AI"
            self.run = {a["id"]: {"rounds": {}, "notes": {}, "errors": {}, "results": {}, "current": 1} for a in agents}
            self.run[HUB_ID] = {"rounds": {}, "notes": {}, "errors": {}, "results": {}, "current": 99}
            if seed:
                for pid, text in seed["answers"].items():
                    if pid in self.run:
                        self.run[pid]["rounds"][seed["round"]] = text
                        self.run[pid]["notes"][seed["round"]] = "沿用"
            agents_view = [{"id": a["id"], "name": a["name"], "role": a.get("role"), "model": a.get("model"), "enabled": True}
                           for a in agents]
            self.graph.agent_view = False
            self.graph.set_participants(agents_view, {"name": hub["name"], "model": hub["model"]} if hub else None, mode)
            self.graph.reset_run()
            self.graph.set_running(True)
            self.rank_label.configure(text="")
            self._build_parts(agents, hub)
            self.council_ui = self._council_block(mode, agents, hub, notes)
            self._set_busy(True)
            if mode != MODE_PARALLEL or seed:
                self.skip_button.pack(side="right", padx=(0, 8))
            history = list(self.conv.get("council_history") or [])
            p = self.prefs
            options = {"filter_think": p.get("filter_think", True), "include_usage": p.get("include_usage", True),
                       "auto_retry": 2 if p.get("auto_retry", True) else 0,
                       "quote_limit": p.get("quote_limit", QUOTE_LIMIT_DEFAULT),
                       "revise_char_limit": p.get("revise_char_limit", 0), "time_limit_min": p.get("time_limit_min", 0),
                       "auto_route": p.get("auto_route", True), "straggler_factor": p.get("straggler_factor", 3),
                       "straggler_min_sec": p.get("straggler_min_sec", 90),
                       "think_limit": p.get("think_limit", THINK_LIMIT_DEFAULT),
                       "web_research": p.get("web_research", True), "quote_total": p.get("quote_total", 24000),
                       "images": [] if seed else list(self.attach_images),
                       "token_limit": p.get("token_limit", 0), "max_concurrent": p.get("max_concurrent", 0),
                       "max_rpm": p.get("max_rpm", 0), "pause_each_round": p.get("pause_each_round", False)}
            prompt = self._mask_outgoing(prompt)
            self._record_base = None
            if p.get("auto_record", True):
                try:
                    base = self._record_base = new_record_base(mode)
                    options["autosave"] = lambda rec, base=base: save_record(rec, base=base)
                except OSError:
                    log_app.exception("無法建立紀錄檔")
            self.session = Session(agents, hub, mode, prompt,
                                   emit=lambda *event: self.ui_queue.put(("council", token) + event),
                                   cancel_event=token,
                                   register=lambda pid, response: self._register_response(token, pid, response),
                                   system_prompt=self._prompt_with_context("council"), review_rounds=rounds, history=history,
                                   options=options, seed=seed)
            log_app.info("討論開始：模式=%s，AI=%s，主持=%s", mode, [f"{a['name']}({a['model']})" for a in agents],
                         hub and hub["name"])
            threading.Thread(target=self.session.run, daemon=True).start()
            self._council_status()

        def _council_block(self, mode, agents, hub, notes):
            tr = self.transcript
            blk = tr.region(prefix="c")
            who = f"◇ AI 討論・{mode}・{len(agents)} 位 AI" + (f"・主持：{hub['name']}" if hub else "")
            tr.write(blk, who + "\n", "who")
            for note in notes:
                tr.write(blk, "ℹ " + note + "\n", "notice")
            progress = tr.region(blk)
            return {"blk": blk, "progress": progress, "sections": {}, "models": {}, "final": None}

        def _council_section(self, ui, number, note):
            tr = self.transcript
            if number in ui["sections"]:
                return ui["sections"][number]
            if number == 99:
                head = tr.region(ui["blk"])
                tr.write(head, "★ 最終成果", "final_head")
                status = tr.region(head)
                tr.write(head, "\n", "final_head")
                body = tr.region(ui["blk"])
                sec = {"head": head, "body": body, "meta": None, "final": True, "status": status}
            else:
                head = tr.region(ui["blk"])
                tag = f"{head}_click"
                title = (f"第 {number} 輪：{note}" if number and "接力" not in note else (note or "主持 AI 規劃"))
                tr.write(head, f"  ▸ {title}", ("sec_head", tag))
                meta = tr.region(head, nl_tags=("sec_head", tag))
                tr.write(head, "\n", ("sec_head", tag))
                body = tr.region(ui["blk"])
                tr.set_collapsible(body, True)
                tr.clickable(tag, lambda h=head, b=body: tr._toggle_tool(h, b))
                sec = {"head": head, "body": body, "meta": meta, "final": False, "count": 0, "done": 0}
            ui["sections"][number] = sec
            return sec

        def _fold_block(self, blk, title, md):
            tr = self.transcript
            head = tr.region(blk)
            tag = f"{head}_click"
            tr.write(head, f"  ▸ {title}", ("sec_head", tag))
            tr.write(head, "\n", ("sec_head", tag))
            body = tr.region(blk)
            tr.set_collapsible(body, True)
            tr.render_markdown(body, md)
            tr.clickable(tag, lambda h=head, b=body: tr._toggle_tool(h, b))

        def _council_model(self, ui, number, pid, note):
            tr = self.transcript
            key = (number, pid)
            if key in ui["models"]:
                return ui["models"][key]
            sec = self._council_section(ui, number, note)
            if sec.get("final"):
                status = sec["status"]
                answer = sec["body"]
            else:
                sec["count"] += 1
                name = self._participant_name(pid)
                service = self._service(pid)
                role = (service or {}).get("role", "")
                model = short_model((service or {}).get("model", ""))
                head = tr.region(sec["body"])
                tr.write(head, f"● {name}", "model_head")
                tr.write(head, f"　{role}・{model}　", ("model_head", "sec_meta"))
                status = tr.region(head)
                tr.write(head, "\n", "model_head")
                answer = tr.region(sec["body"])
                self._update_section_meta(ui, number)
            item = {"status": status, "answer": answer, "number": number, "text": "", "pid": pid,
                    "shown": bool(sec.get("final")), "done": False, "rendered": False}
            ui["models"][key] = item
            if not sec.get("final") and sec["body"] not in tr.on_open:
                tr.on_open[sec["body"]] = lambda u=ui, n=number: self._fill_council_section(u, n)
            return item

        def _section_open(self, ui, number):
            sec = ui["sections"].get(number)
            return bool(sec) and (sec.get("final") or not self.transcript.elided.get(sec["body"], False))

        def _fill_council_section(self, ui, number):
            """收合的回合第一次被展開時，才把各 AI 的回答畫進對話串（串流中的也補上目前的內容）。"""
            tr = self.transcript
            for (n, pid), item in list(ui["models"].items()):
                if n != number:
                    continue
                if item.get("done"):
                    if not item.get("rendered"):
                        tr.finish_markdown(item["answer"], item.get("final_text") or "")
                        if item.get("error"):
                            tr.write(item["answer"], "錯誤：" + item["error"] + "\n", "error")
                        item["rendered"] = True
                elif not item.get("shown"):
                    tr.clear_region(item["answer"])
                    tr.write(item["answer"], self.run.get(pid, {}).get("rounds", {}).get(n, ""), "md_p")
                    item["shown"] = True

        def _update_section_meta(self, ui, number):
            sec = ui["sections"].get(number)
            if not sec or not sec.get("meta"):
                return
            tr = self.transcript
            tr.clear_region(sec["meta"])
            tr.write(sec["meta"], f"　{sec.get('done', 0)}／{sec.get('count', 0)} 完成", ("sec_head", "sec_meta",
                                                                                      f"{sec['head']}_click"))

        def _council_status(self):
            if not self.busy or self.conv["type"] != "council":
                return
            now = time.monotonic()
            for pid, started in list(self.call_started.items()):
                state = self.graph.states.get(pid)
                if state in ("connecting", "thinking", "generating"):
                    self._set_state(pid, state, f"{int(now - started)}s")
            elapsed = time.monotonic() - self.run_started
            parts = [f"● {self.phase_text}", f"{self.done_calls}／{self.expected} 次呼叫", f"已用 {self._fmt_secs(elapsed)}"]
            if self.done_calls and self.expected > self.done_calls:
                parts.append(f"預估剩 {self._fmt_secs(elapsed / self.done_calls * (self.expected - self.done_calls))}")
            tok = self.usage.get("prompt", 0) + self.usage.get("completion", 0) + self.usage.get("estimated", 0)
            if tok:
                parts.append(f"約 {tok:,} tokens")
            self.status_label.configure(text="　".join(parts), foreground=self.theme["accent"])

        def _handle_council(self, kind, payload):
            ui = self.council_ui
            tr = self.transcript
            if kind == "session_done":
                self._finish_council(payload[0])
                return
            if kind == "usage":
                self.usage = payload[0]
                return
            if kind in ("timeline",):
                return
            if self.cancel_event and self.cancel_event.is_set() and kind in ("event", "start", "link", "paused"):
                return
            if kind == "phase":
                text, number = payload
                self.phase_text = text
                self.graph.set_phase(text)
                tr.clear_region(ui["progress"])
                tr.write(ui["progress"], f"⋯ {text}\n", "progress")
            elif kind == "start":
                pid, number, note = payload
                data = self.run.setdefault(pid, {"rounds": {}, "notes": {}, "errors": {}, "results": {}, "current": number})
                data["rounds"][number] = ""
                data["notes"][number] = note
                data["current"] = number
                item = self._council_model(ui, number, pid, note)
                tr.clear_region(item["status"])
                tr.write(item["status"], "　排隊中", ("sec_meta",))
                self._set_state(pid, "queued", "")
            elif kind == "event":
                pid, ev, data = payload
                number = self.run.get(pid, {}).get("current", 1)
                item = ui["models"].get((number, pid))
                if ev == "delta":
                    self.buffers.setdefault(pid, []).append(data)
                    return
                label = {"sending": "連線中", "thinking": "思考中", "generating": "回答中", "queued": "排隊中"}.get(ev)
                detail = ""
                if ev == "thinking" and data:
                    since = self.call_started.get(pid)
                    detail = f"{data / 1000:.1f}k 字" if data >= 1000 else f"{data} 字"
                    if since:
                        detail += f"・{time.monotonic() - since:.0f}s"
                    label = f"思考中 {detail}"
                if ev == "think_cut":
                    label = f"思考超過 {data} 秒，改成不思考直接回答"
                if ev == "continue":
                    label = f"回答被長度上限截斷，自動接續（第 {data} 次）"
                if ev == "sending":
                    self.call_started[pid] = time.monotonic()
                if ev == "rate_wait":
                    label = f"等待配額 {data}s"
                if ev == "retry_wait":
                    label = f"等待重試 {data[0]} 秒"
                if label and item:
                    tr.clear_region(item["status"])
                    tr.write(item["status"], "　" + label, ("sec_meta",))
                state = {"sending": "connecting", "thinking": "thinking", "generating": "generating", "queued": "queued",
                         "rate_wait": "rate", "retry_wait": "retry", "think_cut": "retry", "continue": "generating"}.get(ev)
                if state:
                    self._set_state(pid, state, detail)
            elif kind == "done":
                pid, number, result = payload
                self._flush_council(pid)
                self.call_started.pop(pid, None)
                data = self.run.setdefault(pid, {"rounds": {}, "notes": {}, "errors": {}, "results": {}, "current": number})
                data["results"][number] = result
                data["rounds"][number] = result.get("text") or data["rounds"].get(number, "")
                if result.get("error"):
                    data["errors"][number] = result["error"]
                item = self._council_model(ui, number, pid, data["notes"].get(number, ""))
                status = STATUS_FROM_RESULT.get(result.get("status"), "error")
                label = (f"✓ {result.get('elapsed', 0):.0f}s" if status == "done" else
                         f"✗ {result.get('label') or result.get('status')}")
                if status == "done" and result.get("truncated"):
                    label += "（達到長度上限，可能不完整）"
                elif status == "done" and result.get("continued"):
                    label += f"（自動接續 {result['continued']} 次）"
                if result.get("think_cut"):
                    label += "（思考太久，已改成不思考）"
                tr.clear_region(item["status"])
                tr.write(item["status"], "　" + label, ("sec_meta", "tool_ok" if status == "done" else "tool_bad"))
                item.update(done=True, final_text=result.get("text") or "", error=result.get("error") or "")
                if self._section_open(ui, number):
                    tr.finish_markdown(item["answer"], item["final_text"])
                    if item["error"]:
                        tr.write(item["answer"], "錯誤：" + item["error"] + "\n", "error")
                    item["rendered"] = True
                else:
                    tr.clear_region(item["answer"])
                sec = ui["sections"].get(number)
                if sec and not sec.get("final"):
                    sec["done"] = sec.get("done", 0) + 1
                    self._update_section_meta(ui, number)
                self._set_state(pid, status, f"{result.get('elapsed', 0):.0f}s" if status == "done" else "")
                self.graph.set_preview(pid, (result.get("revised") or result.get("text") or "").strip())
                if pid == HUB_ID and result.get("text"):
                    self.graph.set_final(result["text"])
                self.done_calls += 1
            elif kind == "notice":
                tr.write(ui["blk"], "ⓘ " + payload[0] + "\n", "notice")
            elif kind == "expected":
                self.expected = payload[0]
            elif kind == "research":
                queries, sources, text = payload
                title = f"上網查證：{'、'.join(queries)}（讀了 {len(sources)} 個網頁）"
                self._fold_block(ui["blk"], title, text[:20000])
                self.graph.set_preview(CONTEXT_ID, "上網查證：" + "、".join(queries))
            elif kind == "ranking":
                number, ranks = payload
                self.graph.set_ranks(ranks)
                order = sorted(ranks.items(), key=lambda kv: kv[1])
                text = "互評名次：" + "　".join(f"#{i} {self._participant_name(pid)}（{avg:.1f}）"
                                               for i, (pid, avg) in enumerate(order, start=1))
                self.rank_label.configure(text=text)
                sec = ui["sections"].get(number)
                if sec:
                    tr.write(sec["body"], text + "\n", "notice")
            elif kind == "paused":
                number, label = payload
                self._show_pause_card(label)
            elif kind == "link":
                self.graph.pulse_link(*payload)
            self._council_status()

        def _flush_council(self, only=None):
            ui = self.council_ui
            if not ui:
                return
            for pid in ([only] if only else list(self.buffers)):
                chunks = self.buffers.pop(pid, None)
                if not chunks:
                    continue
                number = self.run.get(pid, {}).get("current", 1)
                item = ui["models"].get((number, pid))
                text = "".join(chunks)
                self.run[pid]["rounds"][number] = self.run[pid]["rounds"].get(number, "") + text
                if item and self._section_open(ui, number):       # 收合中的回合不畫，展開時再補
                    if item.get("shown"):
                        self.transcript.write(item["answer"], text, "md_p")
                    else:
                        self.transcript.write(item["answer"], self.run[pid]["rounds"][number], "md_p")
                        item["shown"] = True

        def _show_pause_card(self, label):
            tr = self.transcript
            rid = tr.region(self.council_ui["blk"])
            tr.write(rid, f"  ⏸ {label}，已暫停。可以補充給下一輪的指示：\n", "card_title")
            var = tk.StringVar()
            frame = tk.Frame(tr.text, bg=self.theme["canvas_chat"])
            entry = ttk.Entry(frame, textvariable=var, width=50)
            entry.pack(side="left", padx=(0, 6))

            def go(skip=False):
                if not self.session:
                    return
                if skip:
                    self.skip_to_synthesis()
                else:
                    self.session.pending_note = var.get().strip()
                    self.session.resume.set()
                try:
                    frame.destroy()
                except tk.TclError:
                    pass
                tr.write(rid, ("  ⏭ 直接彙整\n" if skip else f"  ▶ 繼續{'：' + var.get().strip() if var.get().strip() else ''}\n"),
                         "card_done")

            ttk.Button(frame, text="繼續", style="Primary.TButton", command=go).pack(side="left", padx=(0, 6))
            ttk.Button(frame, text="直接彙整", command=lambda: go(True)).pack(side="left")
            entry.bind("<Return>", lambda _e: go())
            tr.write(rid, "  ", "card_done")
            tr.embed(rid, frame)
            tr.write(rid, "\n", "card_done")
            tr.scroll_end(force=True)
            self.bell()

        def skip_to_synthesis(self):
            if not (self.session and self.busy) or self.session.skip.is_set():
                return
            self.session.skip.set()
            self.session.resume.set()
            with self.active_lock:
                responses = [r for (tok, pid), r in [(k, v) for k, v in self.active.items() if isinstance(k, tuple)]
                             if pid != HUB_ID]
            for response in responses:
                try:
                    response.close()
                except Exception:
                    pass
            self.phase_text = "直接彙整：收尾進行中的回答後開始整合"
            self._council_status()

        def _finish_council(self, record):
            ui = self.council_ui
            tr = self.transcript
            self._flush_council()
            self._set_busy(False)
            self.graph.set_running(False)
            status = STATUS_LABELS.get(record.get("status"), record.get("status"))
            usage = record.get("usage_total") or {}
            tok = usage.get("prompt", 0) + usage.get("completion", 0)
            summary = f"{status}　{self._fmt_secs(time.monotonic() - self.run_started)}　{usage.get('calls', 0)} 次呼叫" + \
                      (f"　{tok:,} tokens" if tok else "") + (f"　{record['failures']} 次失敗" if record.get("failures") else "")
            tr.clear_region(ui["progress"])
            final = record.get("final")
            answers = record.get("latest_answers") or {}
            if not (final and final.get("text")) and len(record.get("agents") or []) == 1 and len(answers) == 1:
                pid, only = next(iter(answers.items()))       # 只有一位回答（例如打招呼的快速回覆）→ 直接當成果
                agent = (record.get("agents") or [{}])[0]
                final = record["final"] = {"text": only, "name": agent.get("name", ""), "source": pid}
                self.after(50, lambda: self.graph.set_phase(f"快速回覆：只請 {agent.get('name', '')} 回答"))
            main_text, contrib = split_final((final or {}).get("text", ""))
            self.graph.set_final(main_text or ("各家回答已完成" if answers else ""))
            self.graph.set_phase(f"{STATUS_LABELS.get(record.get('status'), '')}")
            if final and final.get("text"):
                sec = self._council_section(ui, 99, "")
                tr.finish_markdown(sec["body"], main_text)
                if final.get("disagreement"):
                    tr.write(ui["blk"], "⚠ 各 AI 的結論不一致：" + final["disagreement"][:400]
                                        + "\n　主持 AI 已判斷採用其中一方；這類題目答錯代價高時，請自己再確認或改用 Agent 實際驗證。\n", "error")
                if contrib:
                    self._fold_block(ui["blk"], "各回答的貢獻與分歧（主持 AI 的整合說明）", contrib)
                if final.get("labels"):
                    tr.write(ui["blk"], "代號對照：" + "、".join(f"{k}＝{v}" for k, v in final["labels"].items()) + "\n", "notice")
                if final.get("note"):
                    tr.write(ui["blk"], f"ℹ {final['note']}（來源：{final.get('name')}）\n", "notice")
            elif record.get("status") == "error":
                tr.write(ui["blk"], "✗ " + (record.get("error") or "討論失敗") + "\n", "error")
            elif record.get("mode") == MODE_PARALLEL:
                tr.write(ui["blk"], "ℹ 平行回答不做整合；可以按右側「重新彙整」請主持 AI 整合。\n", "notice")
            if record.get("stragglers"):
                names = {}
                for st in record["stragglers"]:
                    for n in st["names"]:
                        names.setdefault(n, []).append(str(st["round"]))
                for n, rounds in names.items():
                    tr.write(ui["blk"], f"⏱ {n} 太慢，第 {'、'.join(rounds)} 輪沒等它"
                                        + ("（每輪都跟不上，建議換一個較快的模型或取消它的「參與」）" if len(rounds) >= 2 else "")
                                        + "；可在「設定 → AI 討論」調整「不等慢的」。\n", "notice")
            tr.write(ui["blk"], summary + "\n", "progress")
            if record.get("route") == "agent":
                self._card_buttons(ui["blk"], [("改用 Agent 做這件事", "Primary.TButton",
                                                lambda q=record.get("prompt", ""): self.handoff_to_agent(q))])
            final_text = (record.get("final") or {}).get("text", "")
            btns = [("複製最終成果", "Chip.TButton", lambda r=record: self._copy(split_final((r.get("final") or {}).get("text", ""))[0])),
                    ("並排比較", "Chip.TButton", self.open_compare),
                    ("重新彙整", "Chip.TButton", self.resynthesize)]
            if extract_code_project(final_text):
                btns.insert(0, ("✓ 交給 Agent 驗證並修正", "Primary.TButton",
                                lambda t=final_text: self.verify_with_agent(t)))
            self._card_buttons(ui["blk"], btns)
            self.status_label.configure(text=summary, foreground=self.theme["muted"])
            drift = drift_notice(split_final((record.get("final") or {}).get("text", ""))[0])
            if drift:
                tr.write(ui["blk"], "ⓘ " + drift + "\n", "notice")
            self._learn_latency(record)
            self._schedule_finished(STATUS_LABELS.get(record.get("status"), record.get("status") or ""))
            if not self.dirty:
                self.save_settings(quiet=True)
            self.last_record = record
            if record.get("status") in ("done", "partial") and (final or record.get("latest_answers")):
                turn = turn_from_record(record)
                hist = self.conv.setdefault("council_history", [])
                if record.get("seed_round") and hist and hist[-1].get("prompt") == turn["prompt"]:
                    hist[-1] = turn
                else:
                    hist.append(turn)
            self.conv["display"].append(["council", record])
            if self.prefs.get("auto_record", True):
                try:
                    self.last_record_path = save_record(record, base=getattr(self, "_record_base", None))
                except OSError:
                    log_app.exception("存紀錄失敗")
                self._record_base = None
            self._save_conv()
            log_app.info("討論結束：%s", summary)

        def _render_council_record(self, record):
            """把存檔中的討論重新畫出來（靜態）。"""
            tr = self.transcript
            agents = {a["id"]: a for a in record.get("agents", [])}
            hub = record.get("hub")
            blk = tr.region(prefix="c")
            tr.write(blk, f"◇ AI 討論・{record.get('mode')}・{len(agents)} 位 AI" + (f"・主持：{hub['name']}" if hub else "") + "\n", "who")
            for rnd in record.get("rounds", []):
                head = tr.region(blk)
                tag = f"{head}_click"
                label = rnd["label"]
                title = label if "接力" in label else f"第 {rnd['round']} 輪：{label}"
                ok = sum(1 for r in rnd["answers"].values() if r.get("status") == "done")
                tr.write(head, f"  ▸ {title}", ("sec_head", tag))
                tr.write(head, f"　{ok}／{len(rnd['answers'])} 完成\n", ("sec_head", "sec_meta", tag))
                body = tr.region(blk)
                tr.set_collapsible(body, True)
                tr.clickable(tag, lambda h=head, b=body: tr._toggle_tool(h, b))

                def fill(body=body, rnd=rnd):         # 展開時才畫（舊對話重開時不必一次塞進全部內容）
                    tr.on_open.pop(body, None)
                    if rnd.get("ranking"):
                        order = sorted(rnd["ranking"].items(), key=lambda kv: kv[1][0])
                        tr.write(body, "互評名次：" + "　".join(f"#{i} {agents.get(pid, {}).get('name', pid)}（{v[0]:.1f}）"
                                                             for i, (pid, v) in enumerate(order, start=1)) + "\n", "notice")
                    for pid, result in rnd["answers"].items():
                        a = agents.get(pid, {})
                        mh = tr.region(body)
                        mark = "✓" if result.get("status") == "done" else "✗"
                        tr.write(mh, f"● {a.get('name', pid)}", "model_head")
                        tr.write(mh, f"　{a.get('role', '')}・{short_model(a.get('model', ''))}　{mark} {result.get('elapsed', 0):.0f}s\n",
                                 ("model_head", "sec_meta"))
                        ans = tr.region(body)
                        tr.render_markdown(ans, result.get("text") or "")
                        if result.get("error"):
                            tr.write(ans, "錯誤：" + result["error"] + "\n", "error")

                tr.on_open[body] = fill
            final = record.get("final")
            if final and final.get("text"):
                head = tr.region(blk)
                tr.write(head, "★ 最終成果\n", "final_head")
                body = tr.region(blk)
                main_text, contrib = split_final(final["text"])
                tr.render_markdown(body, main_text)
                if final.get("disagreement"):
                    tr.write(blk, "⚠ 各 AI 的結論不一致：" + final["disagreement"][:400] + "\n", "error")
                if contrib:
                    self._fold_block(blk, "各回答的貢獻與分歧（主持 AI 的整合說明）", contrib)
                if final.get("labels"):
                    tr.write(blk, "代號對照：" + "、".join(f"{k}＝{v}" for k, v in final["labels"].items()) + "\n", "notice")
            elif record.get("error"):
                tr.write(blk, "✗ " + record["error"] + "\n", "error")
            usage = record.get("usage_total") or {}
            tr.write(blk, f"{STATUS_LABELS.get(record.get('status'), '')}　{usage.get('calls', 0)} 次呼叫\n", "progress")

        def resynthesize(self):
            if self.busy:
                return
            record = self.last_record
            answers = (record or {}).get("latest_answers") or {}
            if len(answers) < 2:
                messagebox.showinfo(APP_NAME, "需要至少 2 份成功的回答才能彙整，請先在「AI 討論」中執行一次。")
                return
            if self.conv["type"] != "council":
                messagebox.showinfo(APP_NAME, "請在 AI 討論的對話中使用。")
                return
            last_round = max((r["round"] for r in record.get("rounds", [])), default=1)
            self.transcript.notice("↻ 用上一次各家的回答重新彙整（不重跑各家）")
            self.start_council(record.get("prompt", ""), seed={"round": last_round, "answers": answers},
                               review_rounds=0, show_user=False)

        def _participant_name(self, pid):
            if pid == HUB_ID:
                hub = self._service(self.prefs.get("hub_id"))
                return "主持 AI" + (f"：{hub.get('name')}" if hub else "")
            s = self._service(pid)
            return (s.get("name") or s.get("model") or "未命名") if s else "（已移除的 AI）"

        @staticmethod
        def _round_label(data, n):
            note = data["notes"].get(n, "")
            if n == 99 or "接力" in note:
                return note
            return f"第 {n} 輪：{note}"

        def open_compare(self):
            ids = [s["id"] for s in self.services if s["id"] in self.run and self.run[s["id"]]["rounds"]]
            if self.run.get(HUB_ID, {}).get("rounds"):
                ids.append(HUB_ID)
            if not ids:
                messagebox.showinfo(APP_NAME, "還沒有回覆可以比較，請先執行一次。")
                return
            win = tk.Toplevel(self)
            win.title("並排比較")
            win.configure(bg=self.theme["bg"])
            win.geometry(f"{int(1300 * self.scale)}x{int(780 * self.scale)}")
            top = ttk.Frame(win, style="Bar.TFrame", padding=(10, 6))
            top.pack(fill="x", padx=10, pady=(10, 6))
            ttk.Label(top, text="顯示", style="Muted.TLabel").pack(side="left")
            choice = tk.StringVar(value="每位 AI 的最後一輪")
            all_rounds = sorted({n for pid in ids for n in self.run[pid]["rounds"] if n != 99})
            combo = ttk.Combobox(top, textvariable=choice, state="readonly", width=18,
                                 values=["每位 AI 的最後一輪"] + [f"第 {n} 輪" for n in all_rounds])
            combo.pack(side="left", padx=6)
            ttk.Label(top, text="欄數會依視窗寬度自動調整", style="Muted.TLabel").pack(side="left", padx=10)
            scroll = ScrollFrame(self, win)
            scroll.pack(fill="both", expand=True, padx=10, pady=(0, 10))
            columns = []
            for pid in ids:
                card = ttk.Frame(scroll.inner, style="Card.TFrame", padding=8)
                ttk.Label(card, text=self._participant_name(pid), style="Section.TLabel").pack(anchor="w")
                meta = ttk.Label(card, text="", style="Muted.TLabel", wraplength=320)
                meta.pack(anchor="w", pady=(2, 6))
                frame, text = self._text(card, height=18)
                frame.pack(fill="both", expand=True)
                columns.append((pid, meta, text, card))
            state = {"cols": 0}

            def reflow(_e=None):
                width = max(1, scroll.canvas.winfo_width())
                cols = max(1, min(len(columns), width // int(360 * self.scale)))
                if cols == state["cols"]:
                    return
                state["cols"] = cols
                for c in range(len(columns)):
                    scroll.inner.columnconfigure(c, weight=1 if c < cols else 0, uniform="cmp" if c < cols else "")
                for i, (_pid, meta, _t, card) in enumerate(columns):
                    card.grid(row=i // cols, column=i % cols, sticky="nsew", padx=4, pady=4)
                    meta.configure(wraplength=max(200, width // cols - 40))

            def fill(_e=None):
                pick = choice.get()
                for pid, meta, text, _card in columns:
                    data = self.run[pid]
                    if pid == HUB_ID:
                        number = 99
                    elif pick.startswith("第"):
                        number = int(pick.split()[1])
                    else:
                        number = max((n for n in data["rounds"] if n != 99), default=None)
                    if number in data["rounds"]:
                        meta.configure(text=self._round_label(data, number) + "｜" + result_summary(data["results"].get(number)))
                    else:
                        meta.configure(text="這一輪沒有參與")
                    body = data["rounds"].get(number, "")
                    if data["errors"].get(number):
                        body += "\n\n錯誤：" + data["errors"][number]
                    self._set_text(text, body)

            scroll.canvas.bind("<Configure>", reflow, add="+")
            combo.bind("<<ComboboxSelected>>", fill)
            fill()
            win.after(100, reflow)


        # ───────────── 背景事件 → 畫面 ─────────────
        def _process_queue(self):
            more = False
            try:
                deadline = time.perf_counter() + 0.03      # 每次最多處理 30ms，剩下的留到下一輪，畫面才不會卡住
                while True:
                    if time.perf_counter() > deadline:
                        more = True
                        break
                    try:
                        item = self.ui_queue.get_nowait()
                    except queue.Empty:
                        break
                    try:
                        source, token, kind, *payload = item
                        if kind == "call":
                            payload[0]()
                        elif source == "agent" and token is self.token:
                            self._handle_agent(kind, payload)
                        elif source == "council" and token is self.cancel_event:
                            self._handle_council(kind, payload)
                        elif source == "models":
                            pass
                    except Exception:
                        log_app.exception("處理事件失敗：%s", str(item[:3])[:200])
                self._flush_agent()
                self._flush_council()
            finally:
                try:
                    self.after(5 if more else 40, self._process_queue)
                except tk.TclError:
                    pass

        def _tick(self):
            try:
                self._tick_count = getattr(self, "_tick_count", 0) + 1
                deadline = getattr(self, "_sched_deadline", None)
                if deadline and self.busy and self._sched_running is not None and time.monotonic() > deadline:
                    log_app.warning("排程超過時間上限，停止：%s", self._sched_running.get("name"))
                    self._sched_timed_out = True
                    self._sched_deadline = None
                    self.stop()
                rd = getattr(self, "rd", None)
                if rd and self.busy and time.monotonic() > rd["deadline"] + RD_GRACE_SECONDS:
                    log_app.warning("自主研發超過時間上限，停止目前步驟")
                    rd["timed_out"] = True
                    self.stop()
                if self._tick_count % 15 == 0 and not self.busy:
                    self._check_schedules()
                if self.busy:
                    if self.conv["type"] == "agent":
                        self._agent_status()
                    else:
                        self._council_status()
            finally:
                try:
                    self.after(1000, self._tick)
                except tk.TclError:
                    pass

        # ───────────── 設定視窗 ─────────────
        def open_settings(self, page=None):
            if not hasattr(self, "settings_win") or not self.settings_win.winfo_exists():
                self._build_settings_window()
            self.settings_win.deiconify()
            self.settings_win.lift()
            self._settings_page(page or self.settings_current or "模型與 API")

        def _build_settings_window(self):
            win = tk.Toplevel(self)
            self.settings_win = win
            win.title("設定")
            win.configure(bg=self.theme["bg"])
            win.geometry(f"{int(860 * self.scale)}x{int(640 * self.scale)}")
            win.transient(self)
            win.protocol("WM_DELETE_WINDOW", win.withdraw)
            nav = ttk.Frame(win, style="Side.TFrame", padding=(10, 14), width=int(170 * self.scale))
            nav.pack(side="left", fill="y")
            nav.pack_propagate(False)
            host = ttk.Frame(win, style="Surface.TFrame", padding=(18, 14))
            host.pack(side="left", fill="both", expand=True)
            self.settings_pages, self.settings_nav, self.settings_current = {}, {}, None
            for name, builder in (("模型與 API", self._build_endpoint_page), ("Agent", self._build_agent_page),
                                  ("AI 討論", self._build_settings_tab), ("外部工具 MCP", self._build_mcp_page),
                                  ("排程", self._build_schedule_page), ("外觀", self._build_theme_tab),
                                  ("更新與打包", self._build_update_page)):
                frame = ttk.Frame(host, style="Surface.TFrame")
                self.settings_pages[name] = frame
                b = ttk.Button(nav, text=name, style="Side.TButton", command=lambda n=name: self._settings_page(n))
                b.pack(fill="x", pady=1)
                self.settings_nav[name] = b
                builder(frame)
            ttk.Button(nav, text="儲存設定（Ctrl+S）", style="New.TButton", command=self.save_settings).pack(side="bottom", fill="x")
            self._rebuild_editors()

        # ───────────── 外部工具（MCP） ─────────────
        def start_mcp(self, then=None):
            """在背景啟動 MCP伺服器.json 裡啟用的伺服器（npx／uvx 第一次執行可能要下載，會比較久）。"""
            if not self.prefs.get("mcp_enabled", True):
                self.mcp.stop_all()
                self._refresh_mcp_status()
                return
            try:
                config = load_mcp_config()
            except ValueError as exc:
                self.mcp.status = {"（設定檔）": f"✘ {exc}"}
                self._refresh_mcp_status()
                return
            if not any(isinstance(v, dict) and v.get("enabled", True) for v in config["mcpServers"].values()):
                self.mcp.stop_all()
                self._refresh_mcp_status()
                return

            def work():
                self.mcp.start_all(on_status=lambda: self.ui_queue.put(("ui", None, "call", self._refresh_mcp_status)))
                self.ui_queue.put(("ui", None, "call", self._refresh_mcp_status))
                n = len(self.mcp.agent_tools())
                log_app.info("MCP：%s", self.mcp.status)
                if then:
                    self.ui_queue.put(("ui", None, "call", then))
                if n:
                    self.ui_queue.put(("ui", None, "call", lambda: self.status_label.configure(
                        text=f"外部工具（MCP）已連線：{n} 個工具可給 Agent 使用。")))

            threading.Thread(target=work, daemon=True).start()

        def _refresh_mcp_status(self):
            label = getattr(self, "mcp_status_label", None)
            if label is None:
                return
            st = self.mcp.status
            text = "\n".join(f"{k}：{v}" for k, v in st.items()) if st else "目前沒有啟用的 MCP 伺服器。"
            tools = self.mcp.agent_tools()
            if tools:
                text += "\n\n可用工具：" + "、".join(f"{t['server']}・{t['tool']}" for t in tools.values())[:1500]
            try:
                label.configure(text=text)
            except tk.TclError:
                pass

        def _build_mcp_page(self, tab):
            ttk.Label(tab, text="外部工具（MCP）", style="Title.TLabel").pack(anchor="w")
            ttk.Label(tab, text="接上外部工具後，Agent 就能操作瀏覽器、桌面程式、指定資料夾、GitHub 等。全部預設關閉，"
                                "需要哪個就勾哪個、填好欄位，按「儲存並重新連線」。每次使用外部工具前預設會請你核准"
                                "（設定 → Agent →「外部工具（MCP）」權限）。外部工具拿不到你的 AI 金鑰；需要金鑰的（例如 GitHub）"
                                "請在下面選擇存放金鑰的環境變數，程式只記名稱、不存金鑰。",
                      style="Muted.TLabel", wraplength=int(620 * self.scale), justify="left").pack(anchor="w", pady=(4, 8))
            self.mcp_enabled_var = tk.BooleanVar(value=self.prefs.get("mcp_enabled", True))

            def toggle():
                self.prefs["mcp_enabled"] = bool(self.mcp_enabled_var.get())
                self._mark_dirty()
                self.start_mcp()

            ttk.Checkbutton(tab, text="讓 Agent 使用外部工具（總開關）", variable=self.mcp_enabled_var,
                            command=toggle).pack(anchor="w")
            rows_box = ttk.Frame(tab, style="Surface.TFrame")
            rows_box.pack(fill="x", pady=(8, 4))
            form = []                                  # [(row, enabled_var, folder_var, key_var)]

            def build_rows():
                for child in rows_box.winfo_children():
                    child.destroy()
                form.clear()
                try:
                    config = load_mcp_config()
                except ValueError as exc:
                    ttk.Label(rows_box, text=f"⚠ 設定檔格式錯誤：{exc}（請用下方「直接編輯 JSON」修正）",
                              style="Muted.TLabel", foreground=self.theme["danger"]).pack(anchor="w")
                    return
                for r in mcp_form_rows(config):
                    box = ttk.Frame(rows_box, style="Surface.TFrame")
                    box.pack(fill="x", pady=3)
                    en = tk.BooleanVar(value=r["enabled"])
                    desc = str(r["spec"].get("說明") or r["spec"].get("command") or "")
                    ttk.Checkbutton(box, text=f"{r['name']}　{desc}", variable=en).grid(row=0, column=0, columnspan=3, sticky="w")
                    if r["needs"]:
                        ttk.Label(box, text="⚠ " + r["needs"], style="Muted.TLabel",
                                  foreground=self.theme["warning"]).grid(row=1, column=0, columnspan=3, sticky="w", padx=(24, 0))
                    field = MCP_FORM_FIELDS.get(r["name"], {})
                    fv, kv = tk.StringVar(value=r["folder"]), tk.StringVar(value=r["key_env"])
                    if field:
                        ttk.Label(box, text=field["label"], style="Muted.TLabel").grid(row=2, column=0, sticky="w", padx=(24, 8))
                    if field.get("kind") == "folder":
                        ttk.Entry(box, textvariable=fv, width=44).grid(row=2, column=1, sticky="ew")
                        ttk.Button(box, text="選擇…", style="Ghost.TButton",
                                   command=lambda v=fv: v.set(filedialog.askdirectory(parent=self.settings_win) or v.get())
                                   ).grid(row=2, column=2, padx=(6, 0))
                    elif field.get("kind") == "key_env":
                        ttk.Combobox(box, textvariable=kv, width=30,
                                     values=sorted(set(list_key_env_names([kv.get()] if kv.get() else [])) |
                                                   {"GITHUB_TOKEN", "GH_TOKEN"})).grid(row=2, column=1, sticky="w")
                    box.columnconfigure(1, weight=1)
                    form.append((r, en, fv, kv))
                if getattr(self, "mcp_text", None) is not None:
                    try:
                        with open(MCP_CONFIG_PATH, "r", encoding="utf-8") as f:
                            self._set_text(self.mcp_text, f.read())
                    except OSError:
                        self._set_text(self.mcp_text, json.dumps({"mcpServers": {}}, ensure_ascii=False, indent=2))

            def save_form():
                try:
                    config = load_mcp_config()
                except ValueError as exc:
                    messagebox.showerror(APP_NAME, f"MCP 設定檔有誤，請先在「直接編輯 JSON」修正：\n{exc}", parent=self.settings_win)
                    return
                data, problems = mcp_apply_form(config, [{"name": r["name"], "spec": r["spec"], "enabled": en.get(),
                                                          "folder": fv.get(), "key_env": kv.get()} for r, en, fv, kv in form])
                try:
                    save_mcp_config(json.dumps(data, ensure_ascii=False))
                except (ValueError, OSError) as exc:
                    messagebox.showerror(APP_NAME, f"沒有儲存：\n{exc}", parent=self.settings_win)
                    return
                if problems:
                    messagebox.showwarning(APP_NAME, "以下項目缺少必要欄位，先維持關閉：\n" + "\n".join(problems),
                                           parent=self.settings_win)
                build_rows()
                self.mcp_status_label.configure(text="已儲存，正在重新連線…")
                self.start_mcp()

            row = ttk.Frame(tab, style="Surface.TFrame")
            row.pack(fill="x", pady=(4, 0))
            ttk.Button(row, text="儲存並重新連線", style="Primary.TButton", command=save_form).pack(side="left")
            ttk.Button(row, text="重新連線", style="Ghost.TButton", command=self.start_mcp).pack(side="left", padx=6)
            adv_btn = ttk.Button(row, text="進階：直接編輯 JSON ▸", style="Ghost.TButton")
            adv_btn.pack(side="left")
            ttk.Label(tab, text="連線狀態", style="Section.TLabel").pack(anchor="w", pady=(10, 2))
            self.mcp_status_label = ttk.Label(tab, text="", style="Muted.TLabel", wraplength=int(620 * self.scale), justify="left")
            self.mcp_status_label.pack(anchor="w")
            adv = ttk.Frame(tab, style="Surface.TFrame")
            ttk.Label(adv, text="格式與 Claude Desktop 的 claude_desktop_config.json 相同；金鑰請寫成 \"${環境變數名稱}\"，"
                                "不要直接寫進檔案。可以在這裡加入自訂的伺服器，儲存後會出現在上面的清單。",
                      style="Muted.TLabel", wraplength=int(620 * self.scale), justify="left").pack(anchor="w", pady=(8, 4))
            frame, self.mcp_text = self._text(adv, height=10, readonly=False)
            frame.pack(fill="both", expand=True)

            def save_json():
                try:
                    save_mcp_config(self.mcp_text.get("1.0", "end-1c"))
                except (ValueError, OSError) as exc:
                    messagebox.showerror(APP_NAME, f"MCP 設定有誤，沒有儲存：\n{exc}", parent=self.settings_win)
                    return
                build_rows()
                self.mcp_status_label.configure(text="已儲存，正在重新連線…")
                self.start_mcp()

            ttk.Button(adv, text="儲存 JSON 並重新連線", style="Ghost.TButton", command=save_json).pack(anchor="w", pady=(4, 0))

            def toggle_adv():
                if adv.winfo_ismapped():
                    adv.pack_forget()
                    adv_btn.configure(text="進階：直接編輯 JSON ▸")
                else:
                    adv.pack(fill="both", expand=True)
                    adv_btn.configure(text="進階：直接編輯 JSON ▾")

            adv_btn.configure(command=toggle_adv)
            build_rows()
            self._refresh_mcp_status()

        # ───────────── 更新與打包 ─────────────
        def _build_update_page(self, tab):
            ttk.Label(tab, text="更新與打包", style="Title.TLabel").pack(anchor="w")
            ttk.Label(tab, text=f"目前版本：{APP_VERSION}" + ("（打包版 .exe）" if FROZEN else f"（{os.path.join(APP_DIR, 'AI協作.py')}）"),
                      style="Value.TLabel").pack(anchor="w", pady=(6, 10))
            ttk.Label(tab, text="從 GitHub 更新（建議）", style="Section.TLabel").pack(anchor="w")
            clone = self.prefs.get("update_clone") or find_update_clone(self.prefs.get("update_repo") or UPDATE_REPO_DEFAULT)
            ttk.Label(tab, text=("用這台電腦上已經登入的 Git 副本：" + clone) if clone else
                      "找不到這個程式的 Git 副本（例如 桌面\\AI-）；有設定環境變數 GITHUB_TOKEN 時改用 GitHub API。"
                      "下載後會比對 SHA-256、檢查版本與語法，舊版先備份。",
                      style="Muted.TLabel", wraplength=int(620 * self.scale), justify="left").pack(anchor="w")
            gh_row = ttk.Frame(tab, style="Surface.TFrame")
            gh_row.pack(fill="x", pady=(4, 2))
            gh_msg = ttk.Label(tab, text="", style="Muted.TLabel", wraplength=int(620 * self.scale), justify="left")
            ttk.Button(gh_row, text="檢查並更新", style="Primary.TButton",
                       command=lambda: self.check_github_update(status_label=gh_msg)).pack(side="left")
            auto_var = tk.BooleanVar(value=bool(self.prefs.get("auto_update", True)))

            def auto_changed(*_a):
                self.prefs["auto_update"] = bool(auto_var.get())
                self._mark_dirty()
            ttk.Checkbutton(gh_row, text="啟動時自動檢查（每 6 小時最多一次，有新版會先問你）",
                            variable=auto_var, command=auto_changed).pack(side="left", padx=(10, 0))
            gh_msg.pack(anchor="w", pady=(2, 12))
            ttk.Label(tab, text="從網址更新", style="Section.TLabel").pack(anchor="w")
            ttk.Label(tab, text="填入新版 AI協作.py 的網址（例如放在 GitHub 的 raw 檔案網址），程式會檢查版本、語法，"
                                "舊版先備份到「備份/更新前_v版本_時間」再更新，重新啟動後生效。",
                      style="Muted.TLabel", wraplength=int(620 * self.scale), justify="left").pack(anchor="w")
            url_var = tk.StringVar(value=self.prefs.get("update_url", ""))
            row = ttk.Frame(tab, style="Surface.TFrame")
            row.pack(fill="x", pady=(4, 10))
            ttk.Entry(row, textvariable=url_var).pack(side="left", fill="x", expand=True)
            sha_row = ttk.Frame(tab, style="Surface.TFrame")
            ttk.Label(sha_row, text="SHA-256（選填）", style="Muted.TLabel").pack(side="left")
            sha_var = tk.StringVar()
            ttk.Entry(sha_row, textvariable=sha_var).pack(side="left", fill="x", expand=True, padx=(6, 0))
            msg = ttk.Label(tab, text="", style="Muted.TLabel", wraplength=int(620 * self.scale), justify="left")

            def from_url():
                self.prefs["update_url"] = url_var.get().strip()
                self._mark_dirty()
                msg.configure(text="正在下載…", foreground=self.theme["muted"])

                def work():
                    sha = parse_sha256(sha_var.get())
                    try:
                        text = fetch_update(self.prefs["update_url"])
                        err = None
                        if not sha:              # 沒填就試著下載旁邊的 .sha256（build.py 會產生）
                            sha = fetch_update_checksum(self.prefs["update_url"])
                    except Exception as exc:
                        text, err = "", str(exc)
                    self.ui_queue.put(("ui", None, "call", lambda: apply(text, err, sha)))

                threading.Thread(target=work, daemon=True).start()

            def from_file():
                path = filedialog.askopenfilename(title="選擇新版的 AI協作.py", filetypes=[("Python", "*.py")],
                                                  parent=self.settings_win)
                if not path:
                    return
                try:
                    with open(path, "r", encoding="utf-8", newline="") as f:
                        text = f.read()
                    sha = parse_sha256(sha_var.get())
                    if not sha and os.path.isfile(path + ".sha256"):
                        with open(path + ".sha256", "r", encoding="utf-8") as f:
                            sha = parse_sha256(f.read())
                    apply(text, None, sha)
                except OSError as exc:
                    apply("", str(exc))

            def apply(text, err, sha=""):
                if FROZEN:
                    msg.configure(text="打包版（.exe）不能直接替換程式碼：請用新版 AI協作.py 重新執行「打包成exe.bat」。",
                                  foreground=self.theme["warning"])
                    return
                if err:
                    msg.configure(text=f"更新失敗：{err}", foreground=self.theme["danger"])
                    return
                new_v = source_version(text)
                actual = sha256_text(text)
                if sha:
                    try:
                        verify_update_hash(text, sha)
                    except ValueError as exc:
                        msg.configure(text=f"沒有更新：{exc}", foreground=self.theme["danger"])
                        return
                    check = f"SHA-256 相符：{actual[:16]}…"
                else:
                    check = (f"⚠ 沒有可比對的 SHA-256，無法確認檔案沒被竄改。\n實際雜湊：{actual}\n"
                             "建議從可信任的地方取得雜湊值填進「SHA-256」再更新。")
                if not messagebox.askyesno(APP_NAME, f"要從 {APP_VERSION} 更新到 {new_v or '?'} 嗎？\n{check}\n\n"
                                           "（目前的程式會先備份，不會刪除）", parent=self.settings_win,
                                           icon="question" if sha else "warning", default="yes" if sha else "no"):
                    return
                try:
                    version, backup = apply_update(text, expected_sha256=sha or None)
                except (ValueError, SyntaxError, OSError) as exc:
                    msg.configure(text=f"沒有更新：{exc}", foreground=self.theme["danger"])
                    return
                msg.configure(text=f"已更新到 {version}，舊版備份在 {backup}。請關閉程式再重新開啟。",
                              foreground=self.theme["success"])

            ttk.Button(row, text="檢查並更新", style="Primary.TButton", command=from_url).pack(side="left", padx=(6, 0))
            sha_row.pack(fill="x", pady=(0, 8))
            ttk.Button(tab, text="從檔案更新…（選擇新版的 AI協作.py）", style="Ghost.TButton", command=from_file).pack(anchor="w")
            msg.pack(anchor="w", pady=(6, 12))
            ttk.Label(tab, text="打包成 .exe", style="Section.TLabel").pack(anchor="w")
            ttk.Label(tab, text="在程式資料夾執行「打包成exe.bat」：會用 PyInstaller（自動安裝）打包成 dist\\AI協作.exe，"
                                "沒有安裝 Python 的電腦也能執行。設定檔、紀錄、工作階段會放在 .exe 所在的資料夾。",
                      style="Muted.TLabel", wraplength=int(620 * self.scale), justify="left").pack(anchor="w")
            ttk.Button(tab, text="開啟程式資料夾", style="Ghost.TButton", command=lambda: open_path(APP_DIR)).pack(anchor="w", pady=(6, 0))
            ttk.Label(tab, text="資料用量", style="Section.TLabel").pack(anchor="w", pady=(16, 0))
            usage = ttk.Label(tab, text="計算中…", style="Muted.TLabel", wraplength=int(620 * self.scale), justify="left")
            usage.pack(anchor="w")

            def refresh_usage():
                def work():
                    sizes = folder_sizes()
                    text = "　".join(f"{k}：{human_size(v)}" for k, v in sizes.items() if v) or "目前沒有資料"
                    self.ui_queue.put(("ui", None, "call", lambda: usage.configure(text=text)))
                threading.Thread(target=work, daemon=True).start()

            def archive():
                if not messagebox.askyesno(APP_NAME, "把 90 天以上沒動過的對話、討論紀錄、日誌移到各資料夾的「封存」裡？\n"
                                                     "（只是搬移，不會刪除；封存的對話不再出現在左側清單）",
                                           parent=self.settings_win):
                    return
                if self.busy:
                    usage.configure(text="執行中不能封存，請等這一輪結束。")
                    return
                current = {f"{self.conv.get('id')}.json"} if self.conv.get("id") else set()     # 正在開的對話不搬
                n = sum(archive_old_files(os.path.join(APP_DIR, d), skip=current) for d in ("工作階段", "紀錄", "日誌"))
                self.refresh_sessions()
                usage.configure(text=f"已移動 {n} 個檔案到封存。")
                self.after(800, refresh_usage)

            ttk.Button(tab, text="把 90 天前的對話、紀錄、日誌移到封存…", style="Ghost.TButton", command=archive).pack(anchor="w", pady=(6, 0))
            refresh_usage()

        # ───────────── 排程 ─────────────
        def _schedules(self):
            return self.settings.setdefault("schedules", [])

        def _report_interrupted(self):
            """上次的討論沒有正常結束（當機、斷電、強制關閉）：告訴使用者已保存的部分成果在哪裡。"""
            if not getattr(self, "instance_owner", True):
                return
            try:
                found = find_interrupted_records()
            except Exception:
                log_app.exception("檢查中斷的紀錄失敗")
                return
            if found:
                names = "、".join(os.path.basename(p) for p in found[:3])
                msg = f"上次有 {len(found)} 場 AI 討論沒有正常結束，已完成的回答都保存在「紀錄」資料夾：{names}"
                log_app.warning(msg)
                try:
                    self.transcript.notice("ⓘ " + msg)
                    self.status_label.configure(text=msg[:160])
                except tk.TclError:
                    pass

        def _check_schedule_paths(self):
            """已登錄 Windows 工作排程器的排程，指向的程式路徑若失效（搬過資料夾、換過環境）就提醒並提供重新登錄。"""
            if os.name != "nt" or not getattr(self, "instance_owner", True):
                return

            def work():
                try:
                    problems = check_windows_task_paths(self._schedules())
                except Exception:
                    log_app.exception("檢查排程路徑失敗")
                    return
                if problems:
                    self.ui_queue.put(("ui", None, "call", lambda: self._show_schedule_path_problems(problems)))
            threading.Thread(target=work, daemon=True).start()

        def _show_schedule_path_problems(self, problems):
            names = "\n".join(f"• {sch.get('name')}：{msg}" for sch, msg in problems[:8])
            if messagebox.askyesno(APP_NAME, "下列已排程的工作可能無法執行：\n\n" + names
                                   + "\n\n要現在用目前的路徑重新登錄這些排程嗎？"):
                fixed = 0
                for sch, _msg in problems:
                    if sch.get("enabled", True) and self._windows_task(sch, register=True) == "":
                        fixed += 1
                self.status_label.configure(text=f"已重新登錄 {fixed} 個排程到 Windows 工作排程器。")

        def _daily_health_check(self):
            """每天第一次開啟：在背景檢查金鑰與模型（只讀模型清單）。有問題才跳出提醒，不會自動改設定。"""
            p = self.prefs
            today = _dt.date.today().isoformat()
            if not p.get("health_check", True) or p.get("health_last") == today or self.busy:
                return
            services = [dict(s) for s in self.services]
            priority = p.get("key_priority")

            def work():
                try:
                    problems = health_check(services, priority, probe=True, probe_timeout=20)
                except Exception:
                    log_app.exception("健康檢查失敗")
                    return
                self.ui_queue.put(("ui", None, "call", lambda: self._show_health(problems, today)))
            threading.Thread(target=work, daemon=True).start()

        def _show_health(self, problems, today):
            self.prefs["health_last"] = today
            self.save_settings(quiet=True)
            log_app.info("健康檢查：%d 個問題", len(problems))
            if not problems:
                return
            lines = []
            for sv, kind, msg, alt in problems:
                line = f"• {sv.get('name')}（{sv.get('model')}）：{msg}"
                if alt:
                    line += f"\n　建議改用：{alt}"
                lines.append(line)
            messagebox.showwarning(APP_NAME, "每日檢查發現下列 AI 可能無法使用：\n\n" + "\n".join(lines[:12])
                                   + "\n\n可以點拓樸圖上的機器人換模型，或到「設定 → 模型與 API」按「測試全部」。"
                                     "（這項檢查讀模型清單，並對你團隊的模型各送一個字做最小測試，不含任何對話內容；"
                                     "可在「設定 → AI 討論」關閉。）")

        def _take_schedule_requests(self):
            """Windows 排程啟動的另一個程式發現這裡已經開著，就把排程交過來；在這裡執行，只跑一次。"""
            if not getattr(self, "instance_owner", True):
                return False
            for path, sid in take_schedule_requests():
                sch = next((x for x in self._schedules() if x.get("id") == sid), None)
                finish_schedule_request(path)
                if sch is None:
                    log_app.warning("排程請求找不到排程：%s", sid)
                    continue
                log_app.info("接手 Windows 排程：%s", sch.get("name"))
                self.run_schedule(sch)
                return True
            return False

        def _check_schedules(self):
            if self._take_schedule_requests():
                return
            now = _dt.datetime.now()
            for sch in self._schedules():
                if not sch.get("enabled", True) or not sch.get("next"):
                    continue
                if sch.get("windows_task"):          # 由 Windows 工作排程器負責啟動；這裡也跑會變成執行兩次
                    continue
                try:
                    due = _dt.datetime.fromisoformat(sch["next"])
                except ValueError:
                    continue
                if due > now:
                    continue
                if (now - due).total_seconds() > 3600:            # 程式關著時錯過超過 1 小時：不補跑，排下一次
                    sch["last_status"] = f"錯過（{due:%m-%d %H:%M} 程式沒開）"
                    self._reschedule(sch, now)
                    continue
                self.run_schedule(sch)
                return

        def _reschedule(self, sch, after=None):
            try:
                nxt = next_run_time(sch, after)
            except ValueError:
                nxt = None
            sch["next"] = nxt.isoformat(timespec="minutes") if nxt else None
            if not nxt and sch.get("repeat") == "once":
                sch["enabled"] = False
            self.save_settings(quiet=True)
            self._refresh_schedule_list()

        def run_schedule(self, sch, launched=False):
            """執行一個排程：開新對話、帶入內容並送出。需要核准的動作依排程設定自動拒絕或允許（刪除類一律拒絕）。"""
            if self.busy:
                return False
            self._sched_running = sch
            self._launched_schedule = sch if launched else None
            self.new_conversation(sch.get("kind", "agent"))
            if sch.get("kind") == "agent" and sch.get("workspace"):
                if os.path.isdir(sch["workspace"]):
                    self.conv["workspace"] = sch["workspace"]
                    self._update_header()
                    self._refresh_agent_panel()
            self.conv["title"] = ("⏰ " + (sch.get("name") or "排程"))[:40]
            self.prompt.delete("1.0", "end")
            self.prompt.insert("1.0", sch.get("prompt", ""))
            self._unattended = sch
            limit = int(self.prefs.get("schedule_time_limit_min", 30) or 0)
            self._sched_deadline = time.monotonic() + limit * 60 if limit else None
            self._sched_timed_out = False
            sch["last_run"] = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
            sch["last_status"] = "執行中"
            log_app.info("排程開始：%s", sch.get("name"))
            self.send()
            if not self.busy:                   # 沒有開始（例如資料夾不存在、模型設定有誤）
                self._unattended = None
                self._sched_running = None
                sch["last_status"] = "沒有開始（請檢查設定）"
                self._reschedule(sch)
                return False
            return True

        def _schedule_finished(self, label):
            sch = self._sched_running
            if sch is None:
                return
            if getattr(self, "_sched_timed_out", False):
                label = f"超過時間上限（{self.prefs.get('schedule_time_limit_min', 30)} 分鐘），已停止並存檔"
                self._sched_timed_out = False
            self._sched_deadline = None
            self._sched_running = None
            self._unattended = None
            sch["last_status"] = label
            self._save_conv()
            self.refresh_sessions()
            self._reschedule(sch)
            log_app.info("排程結束：%s（%s）", sch.get("name"), label)
            try:
                self.bell()
            except tk.TclError:
                pass
            if self._launched_schedule is sch and sch.get("close_after", True):
                self.after(5000, self._close_after_schedule)

        def _close_after_schedule(self):
            if self.busy:
                return
            self.dirty = False
            self._on_close()

        def run_schedule_by_id(self, sid):
            sch = next((x for x in self._schedules() if x.get("id") == sid), None)
            if sch is None:
                self.status_label.configure(text=f"找不到排程 {sid}（可能已被移除）")
                return
            self.run_schedule(sch, launched=True)

        def _build_schedule_page(self, tab):
            top = ttk.Frame(tab, style="Surface.TFrame")
            top.pack(fill="x")
            ttk.Label(top, text="排程", style="Title.TLabel").pack(side="left")
            ttk.Button(top, text="＋ 新增排程", command=lambda: self.edit_schedule(None)).pack(side="right")
            ttk.Label(tab, text="在指定時間自動執行一段 Agent 任務或 AI 討論，結果存成一個新對話（標題前有 ⏰）。"
                                "程式開著時會自動執行；勾選「登錄到 Windows 工作排程器」後，程式沒開時 Windows 也會啟動它來執行，完成後自動關閉。"
                                "排程執行時沒有人可以核准，需要核准的動作預設會被拒絕。",
                      style="Muted.TLabel", wraplength=int(620 * self.scale), justify="left").pack(anchor="w", pady=(4, 8))
            self.schedule_box = ttk.Frame(tab, style="Surface.TFrame")
            self.schedule_box.pack(fill="both", expand=True)
            self._refresh_schedule_list()

        def _refresh_schedule_list(self):
            box = getattr(self, "schedule_box", None)
            if box is None:
                return
            try:
                for child in box.winfo_children():
                    child.destroy()
            except tk.TclError:
                return
            items = self._schedules()
            if not items:
                ttk.Label(box, text="還沒有排程。", style="Muted.TLabel").pack(anchor="w")
            for sch in items:
                row = ttk.Frame(box, style="Card.TFrame", padding=(10, 8))
                row.pack(fill="x", pady=3)
                nxt = sch.get("next") or "—"
                state = "" if sch.get("enabled", True) else "（已停用）"
                ttk.Label(row, text=f"{sch.get('name')}{state}", style="Value.TLabel").grid(row=0, column=0, sticky="w")
                ttk.Label(row, text=f"{describe_schedule(sch)}　下次：{nxt.replace('T', ' ')}　上次：{sch.get('last_run') or '—'} "
                                    f"{sch.get('last_status') or ''}" + ("　｜Windows 工作排程器" if sch.get("windows_task") else ""),
                          style="Muted.TLabel").grid(row=1, column=0, sticky="w")
                btns = ttk.Frame(row, style="Card.TFrame")
                btns.grid(row=0, column=1, rowspan=2, sticky="e")
                row.columnconfigure(0, weight=1)
                ttk.Button(btns, text="立即執行", style="Ghost.TButton", command=lambda x=sch: self.run_schedule(x)).pack(side="left")
                ttk.Button(btns, text="編輯", style="Ghost.TButton", command=lambda x=sch: self.edit_schedule(x)).pack(side="left", padx=4)
                ttk.Button(btns, text="移除", style="Danger.TButton", command=lambda x=sch: self.remove_schedule(x)).pack(side="left")

        def remove_schedule(self, sch):
            if not messagebox.askyesno(APP_NAME, f"要移除排程「{sch.get('name')}」嗎？\n（設定會移到「已移除的排程」保存，不會刪除；"
                                                 "如果有登錄到 Windows 工作排程器，也會一併取消）", parent=self.settings_win):
                return
            if sch.get("windows_task"):
                self._windows_task(sch, register=False)
            self._schedules().remove(sch)
            self.settings.setdefault("removed_schedules", []).append(dict(sch, removed_at=time.strftime("%Y-%m-%d %H:%M")))
            self.save_settings(quiet=True)
            self._refresh_schedule_list()

        def _windows_task(self, sch, register=True):
            if sys.platform != "win32":
                return "只有 Windows 支援工作排程器"
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            try:
                name, args = windows_task_command(sch, os.path.abspath(__file__))
                if not register:
                    args = ["schtasks", "/Delete", "/F", "/TN", name]
                r = subprocess.run(args, capture_output=True, text=True, timeout=30, creationflags=flags)
                if r.returncode != 0:
                    return (r.stderr or r.stdout or "schtasks 失敗").strip()
                if register:
                    b = subprocess.run(windows_battery_command(name, sch.get("on_battery", True)), capture_output=True,
                                       text=True, timeout=30, creationflags=flags)
                    if b.returncode != 0:          # 工作已建立；只是電源條件沒改成功，不算失敗
                        log_app.warning("設定排程電源條件失敗：%s", (b.stderr or b.stdout or "")[:300])
                return ""
            except Exception as exc:
                return str(exc)

        def edit_schedule(self, sch):
            new = sch is None
            data = dict(new_schedule() if new else sch)
            win = tk.Toplevel(self.settings_win if hasattr(self, "settings_win") else self)
            win.title("新增排程" if new else f"編輯排程：{data.get('name')}")
            win.configure(bg=self.theme["surface"])
            win.transient(self)
            body = ttk.Frame(win, style="Surface.TFrame", padding=14)
            body.pack(fill="both", expand=True)
            v = {k: tk.StringVar(value=str(data.get(k, ""))) for k in ("name", "time", "date", "workspace")}
            kind = tk.StringVar(value=data.get("kind", "agent"))
            repeat = tk.StringVar(value=REPEATS.get(data.get("repeat", "daily"), "每天"))
            approval = tk.StringVar(value=data.get("approval", "deny"))
            enabled = tk.BooleanVar(value=data.get("enabled", True))
            wintask = tk.BooleanVar(value=data.get("windows_task", False))
            close_after = tk.BooleanVar(value=data.get("close_after", True))
            on_battery = tk.BooleanVar(value=data.get("on_battery", True))
            days = [tk.BooleanVar(value=i in (data.get("weekdays") or [])) for i in range(7)]
            grid = ttk.Frame(body, style="Surface.TFrame")
            grid.pack(fill="x")

            def lab(r, text):
                ttk.Label(grid, text=text, style="Muted.TLabel").grid(row=r, column=0, sticky="nw", padx=(0, 8), pady=3)

            lab(0, "名稱")
            ttk.Entry(grid, textvariable=v["name"], width=30).grid(row=0, column=1, sticky="ew", pady=3)
            lab(1, "類型")
            kr = ttk.Frame(grid, style="Surface.TFrame")
            kr.grid(row=1, column=1, sticky="w")
            ttk.Radiobutton(kr, text="Agent（動手做事）", variable=kind, value="agent").pack(side="left")
            ttk.Radiobutton(kr, text="AI 討論", variable=kind, value="council").pack(side="left", padx=8)
            lab(2, "工作資料夾")
            wr = ttk.Frame(grid, style="Surface.TFrame")
            wr.grid(row=2, column=1, sticky="ew")
            ttk.Entry(wr, textvariable=v["workspace"]).pack(side="left", fill="x", expand=True)
            ttk.Button(wr, text="選擇…", style="Ghost.TButton", command=lambda: v["workspace"].set(
                filedialog.askdirectory(parent=win) or v["workspace"].get())).pack(side="left", padx=4)
            lab(3, "重複")
            rr = ttk.Frame(grid, style="Surface.TFrame")
            rr.grid(row=3, column=1, sticky="w")
            ttk.Combobox(rr, textvariable=repeat, values=list(REPEATS.values()), state="readonly", width=10).pack(side="left")
            ttk.Label(rr, text="  時間", style="Muted.TLabel").pack(side="left")
            ttk.Entry(rr, textvariable=v["time"], width=6).pack(side="left", padx=4)
            ttk.Label(rr, text="日期（只執行一次時）", style="Muted.TLabel").pack(side="left")
            ttk.Entry(rr, textvariable=v["date"], width=11).pack(side="left", padx=4)
            lab(4, "星期（每週時）")
            dr = ttk.Frame(grid, style="Surface.TFrame")
            dr.grid(row=4, column=1, sticky="w")
            for i, name in enumerate(WEEKDAY_NAMES):
                ttk.Checkbutton(dr, text=name, variable=days[i]).pack(side="left")
            lab(5, "要做的事")
            frame, prompt = self._text(grid, height=6, readonly=False)
            frame.grid(row=5, column=1, sticky="nsew", pady=3)
            self._set_text(prompt, data.get("prompt", ""))
            lab(6, "需要核准時")
            ar = ttk.Frame(grid, style="Surface.TFrame")
            ar.grid(row=6, column=1, sticky="w")
            ttk.Radiobutton(ar, text="自動拒絕（建議）", variable=approval, value="deny").pack(side="left")
            ttk.Radiobutton(ar, text="自動允許（刪除類指令與外部工具仍會拒絕）", variable=approval, value="allow").pack(side="left", padx=8)
            grid.columnconfigure(1, weight=1)
            ttk.Checkbutton(body, text="啟用", variable=enabled).pack(anchor="w", pady=(8, 0))
            ttk.Checkbutton(body, text="登錄到 Windows 工作排程器（程式沒開時也會由 Windows 啟動來執行）", variable=wintask).pack(anchor="w")
            ttk.Checkbutton(body, text="由 Windows 啟動時，執行完自動關閉程式", variable=close_after).pack(anchor="w")
            ttk.Checkbutton(body, text="筆電用電池時也執行（Windows 預設沒插電就不執行）", variable=on_battery).pack(anchor="w")
            msg = ttk.Label(body, text="", style="Muted.TLabel", wraplength=int(560 * self.scale))
            msg.pack(anchor="w", pady=(6, 0))

            def save():
                rev = {label: key for key, label in REPEATS.items()}
                out = dict(data, name=v["name"].get().strip() or "排程", kind=kind.get(), workspace=v["workspace"].get().strip(),
                           repeat=rev.get(repeat.get(), "daily"), time=v["time"].get().strip(), date=v["date"].get().strip(),
                           weekdays=[i for i in range(7) if days[i].get()], approval=approval.get(), enabled=enabled.get(),
                           windows_task=wintask.get(), close_after=close_after.get(), on_battery=on_battery.get(),
                           prompt=prompt.get("1.0", "end-1c").strip())
                if not out["prompt"]:
                    msg.configure(text="請填「要做的事」。", foreground=self.theme["danger"])
                    return
                if out["kind"] == "agent" and not os.path.isdir(out["workspace"]):
                    msg.configure(text="Agent 排程需要一個存在的工作資料夾。", foreground=self.theme["danger"])
                    return
                try:
                    nxt = next_run_time(out)
                except ValueError as exc:
                    msg.configure(text=str(exc), foreground=self.theme["danger"])
                    return
                if not nxt and out["enabled"]:
                    msg.configure(text="這個時間已經過了，請改成未來的時間。", foreground=self.theme["danger"])
                    return
                out["next"] = nxt.isoformat(timespec="minutes") if nxt else None
                had_task = (sch or {}).get("windows_task")
                if had_task and (not out["windows_task"] or not out["enabled"]):
                    self._windows_task(sch, register=False)
                if out["windows_task"] and out["enabled"]:
                    err = self._windows_task(out, register=True)
                    if err:
                        msg.configure(text=f"登錄到 Windows 工作排程器失敗：{err}\n（排程仍會在程式開著時執行）",
                                      foreground=self.theme["warning"])
                        out["windows_task"] = False
                if new:
                    self._schedules().append(out)
                else:
                    sch.clear()
                    sch.update(out)
                self.save_settings(quiet=True)
                self._refresh_schedule_list()
                if not str(msg.cget("text")).startswith("登錄"):
                    win.destroy()

            ttk.Button(body, text="儲存", style="Primary.TButton", command=save).pack(anchor="e", pady=(10, 0))

        def _settings_page(self, name):
            if name not in self.settings_pages:
                return
            for n, f in self.settings_pages.items():
                f.pack_forget()
                self.settings_nav[n].configure(style="SegOn.TButton" if n == name else "Side.TButton")
            self.settings_pages[name].pack(fill="both", expand=True)
            self.settings_current = name

        def _build_endpoint_page(self, tab):
            top = ttk.Frame(tab, style="Surface.TFrame")
            top.pack(fill="x", pady=(0, 6))
            ttk.Label(top, text="模型與 API", style="Title.TLabel").pack(side="left")
            ttk.Button(top, text="＋ 新增", command=self.add_service).pack(side="right")
            ttk.Button(top, text="＋ 訂閱 CLI（Claude Code／Codex）", style="Ghost.TButton",
                       command=self.open_cli_dialog).pack(side="right", padx=(6, 0))
            ttk.Button(top, text="測試全部", style="Ghost.TButton", command=self.test_all).pack(side="right", padx=6)
            row = ttk.Frame(tab, style="Surface.TFrame")
            row.pack(fill="x", pady=(0, 6))
            ttk.Label(row, text="已移除", style="Muted.TLabel").pack(side="left")
            self.removed_var = tk.StringVar()
            self.removed_combo = ttk.Combobox(row, textvariable=self.removed_var, state="readonly", width=28)
            self.removed_combo.pack(side="left", padx=6)
            ttk.Button(row, text="還原", style="Ghost.TButton", command=self.restore_service).pack(side="left")
            ttk.Label(tab, text="Agent 使用右上角選的那一個模型；「AI 討論」使用所有勾選「參與」的模型。"
                                "金鑰可填環境變數名稱（會保存名稱）或直接貼上（不會保存）。",
                      style="Muted.TLabel", wraplength=int(600 * self.scale)).pack(fill="x", pady=(0, 8))
            self.endpoint_scroll = ScrollFrame(self, tab)
            self.endpoint_scroll.pack(fill="both", expand=True)

        def _build_agent_page(self, tab):
            scroll = ScrollFrame(self, tab)
            scroll.pack(fill="both", expand=True)
            self.agent_scroll = scroll
            body = scroll.inner
            ttk.Label(body, text="Agent", style="Title.TLabel").pack(anchor="w")
            ttk.Label(body, text="工具權限：允許＝直接做；詢問＝每次跳出核准卡；拒絕＝不能用。刪除類指令一律會詢問。",
                      style="Muted.TLabel", wraplength=int(600 * self.scale)).pack(anchor="w", pady=(4, 8))
            perms = dict(DEFAULT_PERMISSIONS, **(self.prefs.get("agent_perms") or {}))
            self.perm_vars = {}
            grid = ttk.Frame(body, style="Surface.TFrame")
            grid.pack(fill="x")
            for r, (cat, label) in enumerate(TOOL_CATEGORIES.items()):
                ttk.Label(grid, text=label, style="Value.TLabel", width=14).grid(row=r, column=0, sticky="w", pady=3)
                var = tk.StringVar(value=perms.get(cat, PERM_ASK))
                self.perm_vars[cat] = var
                for c, (val, text) in enumerate(PERM_LABELS.items(), start=1):
                    ttk.Radiobutton(grid, text=text, value=val, variable=var, command=self._on_agent_prefs).grid(
                        row=r, column=c, sticky="w", padx=(0, 14))
            self.agent_num = {}
            row = ttk.Frame(body, style="Surface.TFrame")
            row.pack(fill="x", pady=(14, 2))
            ttk.Label(row, text="每次最多步數", style="Value.TLabel").pack(side="left")
            var = tk.StringVar(value=str(self.prefs.get("agent_max_steps", AGENT_MAX_STEPS)))
            self.agent_num["agent_max_steps"] = var
            ttk.Spinbox(row, from_=5, to=200, increment=5, width=6, textvariable=var, command=self._on_agent_prefs).pack(side="left", padx=6)
            for key, text, lo, hi, step, unit, default in (
                    ("schedule_max_steps", "排程執行時最多步數", 5, 200, 5, "步（沒有人看著，限制得比平常少）", 30),
                    ("schedule_time_limit_min", "排程整體時間上限", 0, 600, 5, "分鐘（超過就停止並存檔；0＝不限）", 30)):
                row = ttk.Frame(body, style="Surface.TFrame")
                row.pack(fill="x", pady=2)
                ttk.Label(row, text=text, style="Value.TLabel").pack(side="left")
                var = tk.StringVar(value=str(self.prefs.get(key, default)))
                self.agent_num[key] = var
                ttk.Spinbox(row, from_=lo, to=hi, increment=step, width=6, textvariable=var,
                            command=self._on_agent_prefs).pack(side="left", padx=6)
                ttk.Label(row, text=unit, style="Muted.TLabel").pack(side="left")
            ttk.Label(body, text="工具呼叫方式", style="Section.TLabel").pack(anchor="w", pady=(14, 2))
            self.tool_mode_var = tk.StringVar(value=self.prefs.get("agent_tool_mode", "auto"))
            for val, text in (("auto", "自動（先用原生工具呼叫，不支援時自動改用文字格式）"),
                              ("native", "原生工具呼叫（OpenAI function calling）"),
                              ("text", "文字格式（相容所有模型，但較不穩定）")):
                ttk.Radiobutton(body, text=text, value=val, variable=self.tool_mode_var, command=self._on_agent_prefs).pack(anchor="w", pady=1)
            self.web_search_var = tk.BooleanVar(value=self.prefs.get("agent_web_search", True))
            ttk.Checkbutton(body, text="允許網路搜尋工具（使用 DuckDuckGo，不需金鑰；不穩定時可關閉）",
                            variable=self.web_search_var, command=self._on_agent_prefs).pack(anchor="w", pady=(10, 2))
            ttk.Label(body, text="安全設計", style="Section.TLabel").pack(anchor="w", pady=(14, 2))
            for line in ("• 只能存取所選工作資料夾內的檔案。",
                         f"• 沒有刪除工具；修改前自動備份到「{AGENT_DIR_NAME}/備份/」，右側可一鍵復原。",
                         "• 「規劃」模式只讀不改；「執行」模式才能修改與執行指令。",
                         "• 工作資料夾內的 AGENTS.md 會自動當作專案規則讀入；Agent 記住的事存在「記憶.md」。"):
                ttk.Label(body, text=line, style="Muted.TLabel", wraplength=int(600 * self.scale)).pack(anchor="w")
            self._build_sandbox_budget_section(body)
            self._build_advanced_section(body)

        def _apply_advanced_prefs(self):
            """把「進階功能」的手動開關套用到程式（啟動時與變更時）。"""
            p = self.prefs
            set_env_pass_through(p.get("env_pass_enabled", False), p.get("env_pass_names", ""))
            ALLOW_INSECURE_HTTP[0] = bool(p.get("allow_insecure_http", False))
            try:
                USAGE.configure(p.get("budget_tokens", 0), p.get("budget_usd", 0), p.get("model_prices", ""))
            except (TypeError, ValueError):
                USAGE.configure(0, 0, "")

        def _build_advanced_section(self, body):
            """需要特別設定、平常用不到的功能：全部預設關閉，使用者在這裡手動開啟。"""
            t = self.theme
            ttk.Label(body, text="進階功能（需要時再手動開啟，預設全部關閉）", style="Section.TLabel").pack(anchor="w", pady=(16, 2))
            ttk.Label(body, text="這些功能會放寬安全保護，只在你確定需要時開啟；開啟的項目會記在設定檔，隨時可以關掉。",
                      style="Muted.TLabel", wraplength=int(600 * self.scale)).pack(anchor="w")
            # 1. 交給子程式的環境變數
            env_on = tk.BooleanVar(value=bool(self.prefs.get("env_pass_enabled", False)))
            env_names = tk.StringVar(value=self.prefs.get("env_pass_names", ""))
            box = ttk.Frame(body, style="Surface.TFrame")
            box.pack(fill="x", pady=(8, 0))
            ttk.Checkbutton(box, text="把指定的環境變數交給 Agent 執行的指令與外部工具（MCP）", variable=env_on).pack(anchor="w")
            sub = ttk.Frame(box, style="Surface.TFrame")
            sub.pack(fill="x", padx=(24, 0))
            ttk.Label(sub, text="名稱（用逗號分隔）", style="Muted.TLabel").pack(side="left")
            entry = ttk.Combobox(sub, textvariable=env_names, width=40,
                                 values=sorted({"GITHUB_TOKEN", "GH_TOKEN", "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"}))
            entry.pack(side="left", padx=(8, 0), fill="x", expand=True)
            ttk.Label(box, text="平常程式會拿掉名稱像金鑰的環境變數（…KEY、…TOKEN、…SECRET），避免 Agent 的指令或外部工具"
                                "把金鑰外洩。只有在專案的指令真的需要時（例如 gh、huggingface-cli）才填，越少越好；"
                                "不要填你的 AI 服務金鑰（例如 NVIDIA_API_KEY）。",
                      style="Muted.TLabel", wraplength=int(580 * self.scale)).pack(anchor="w", padx=(24, 0))
            # 2. 雲端 API 用 http://
            http_on = tk.BooleanVar(value=bool(self.prefs.get("allow_insecure_http", False)))
            box2 = ttk.Frame(body, style="Surface.TFrame")
            box2.pack(fill="x", pady=(10, 0))
            ttk.Checkbutton(box2, text="允許雲端 API 使用未加密的 http://（不建議）", variable=http_on).pack(anchor="w")
            ttk.Label(box2, text="預設只有本機與區網的服務可以用 http://。開啟後，金鑰和對話可能以明文經過網路，"
                                 "只適合你自己架設、走在可信任網路上的服務。",
                      style="Muted.TLabel", wraplength=int(580 * self.scale)).pack(anchor="w", padx=(24, 0))

            def changed(*_a):
                names = env_names.get().strip()
                if env_on.get() and re.search(r"(?i)nvidia|openai|anthropic|groq|gemini|deepseek|openrouter|mistral", names) \
                        and not getattr(self, "_warned_ai_env", False):
                    self._warned_ai_env = True
                    messagebox.showwarning(APP_NAME, "名單裡有 AI 服務的金鑰。交給 Agent 的指令後，模型可能讀到或傳出它；"
                                                     "除非確定需要，建議拿掉。", parent=self.settings_win)
                if http_on.get() and not self.prefs.get("allow_insecure_http") and not messagebox.askyesno(
                        APP_NAME, "確定允許雲端 API 用 http:// 嗎？金鑰和對話會以明文經過網路。", parent=self.settings_win):
                    http_on.set(False)
                sub_state = "normal" if env_on.get() else "disabled"
                entry.configure(state=sub_state)
                self.prefs.update(env_pass_enabled=bool(env_on.get()), env_pass_names=names,
                                  allow_insecure_http=bool(http_on.get()))
                self._apply_advanced_prefs()
                self._mark_dirty()

            entry.configure(state="normal" if env_on.get() else "disabled")
            env_on.trace_add("write", changed)
            http_on.trace_add("write", changed)
            entry.bind("<FocusOut>", changed)
            entry.bind("<<ComboboxSelected>>", changed)

        def _on_agent_prefs(self):
            self.prefs["agent_perms"] = {k: v.get() for k, v in self.perm_vars.items()}
            try:
                self.prefs["agent_max_steps"] = max(5, min(200, int(self.agent_num["agent_max_steps"].get())))
            except ValueError:
                pass
            for key, lo, hi in (("schedule_max_steps", 5, 200), ("schedule_time_limit_min", 0, 600)):
                try:
                    self.prefs[key] = max(lo, min(hi, int(self.agent_num[key].get())))
                except (ValueError, KeyError):
                    pass
            self.prefs["agent_tool_mode"] = self.tool_mode_var.get()
            self.prefs["agent_web_search"] = bool(self.web_search_var.get())
            self._mark_dirty()
            if self.runner:
                self.runner.permissions = dict(DEFAULT_PERMISSIONS, **self.prefs["agent_perms"])
                self.runner.options = self._agent_options()

        def _build_settings_tab(self, tab):
            scroll = ScrollFrame(self, tab)
            scroll.pack(fill="both", expand=True)
            self.settings_scroll = scroll
            body = scroll.inner
            ttk.Label(body, text="全域系統提示詞（每位 AI 都會收到）", style="Section.TLabel").pack(anchor="w")
            frame, self.system_text = self._text(body, height=4, readonly=False)
            frame.pack(fill="x", pady=(4, 12))
            self._set_text(self.system_text, self.prefs.get("system_prompt", ""))
            self.system_text.bind("<KeyRelease>", lambda _e: self._on_prefs_changed())

            self.bool_vars = {}

            def check(key, text):
                var = tk.BooleanVar(value=bool(self.prefs.get(key, DEFAULT_PREFERENCES.get(key))))
                self.bool_vars[key] = var
                ttk.Checkbutton(body, text=text, variable=var, command=self._on_prefs_changed).pack(anchor="w", pady=2)

            self.num_vars = {}

            def number(key, text, lo, hi, step, unit=""):
                row = ttk.Frame(body, style="Surface.TFrame")
                row.pack(fill="x", pady=2)
                ttk.Label(row, text=text, style="Value.TLabel").pack(side="left")
                var = tk.StringVar(value=str(self.prefs.get(key, DEFAULT_PREFERENCES.get(key))))
                self.num_vars[key] = (var, lo, hi)
                spin = ttk.Spinbox(row, from_=lo, to=hi, increment=step, width=8, textvariable=var,
                                   command=self._on_prefs_changed)
                spin.pack(side="left", padx=6)
                spin.bind("<FocusOut>", lambda _e: self._on_prefs_changed())
                if unit:
                    ttk.Label(row, text=unit, style="Muted.TLabel").pack(side="left")

            ttk.Label(body, text="協作品質", style="Section.TLabel").pack(anchor="w", pady=(4, 2))
            check("hub_exclusive", "主持 AI 不同時參與回答（避免主持 AI 偏好自己的答案）")
            check("spread_temperature", "相同模型自動使用不同溫度（避免意見同質化）")
            number("revise_char_limit", "互評「修正後回答」字數上限", 0, 10000, 250, "字（0＝不限，避免越寫越長）")
            number("quote_limit", "互評／彙整時每份回答最多引用", 1000, 50000, 1000, "字")
            number("quote_total", "互評／彙整時引用的總字數上限", 0, 200000, 2000, "字（人越多每份越短，避免用量暴增；0＝不限）")
            ttk.Label(body, text="停止條件與用量", style="Section.TLabel").pack(anchor="w", pady=(12, 2))
            number("time_limit_min", "時間上限", 0, 240, 5, "分鐘（0＝不限；超過就停止互評、直接整合）")
            number("token_limit", "token 上限", 0, 5000000, 10000, "（0＝不限）")
            number("max_concurrent", "同時呼叫數上限", 0, 24, 1, "（0＝不限）")
            number("max_rpm", "每分鐘請求上限", 0, 600, 5, "（0＝不限；常遇到 429 時調低）")
            number("straggler_factor", "不等慢的：超過其他人", 0, 10, 1, "倍時間就不等（0＝一律等完）")
            number("straggler_min_sec", "　至少先等", 30, 1800, 30, "秒")
            number("think_limit", "思考時間上限", 0, 3600, 30,
                   "秒還沒開始回答，就改成「不思考」重新回答（0＝不限制；選「深入思考」的 AI 不受限）")
            ttk.Label(body, text="流程", style="Section.TLabel").pack(anchor="w", pady=(12, 2))
            check("pause_each_round", "每輪結束後暫停，讓我查看並補充指示")
            check("confirm_big_runs", "呼叫次數較多（10 次以上）時先確認")
            check("quick_small_talk", "打招呼、道謝等很短的訊息只請一位 AI 直接回答（訊息加「完整討論」可強制討論）")
            check("auto_route", "主持 AI 先判斷：簡單問題直接回答（1 次呼叫），值得討論才啟動整場討論")
            check("health_check", "每天第一次開啟時，檢查金鑰與模型還能不能用（讀模型清單，並對你團隊的模型各送一個字做最小測試；不含任何對話內容）")
            check("web_research", "需要最新或可查證的資訊時，討論前先上網搜尋並讀幾個網頁，給大家當共用資料（DuckDuckGo）")
            check("filter_think", "隱藏回覆中的 <think>…</think> 思考內容")
            check("include_usage", "要求服務回報 token 用量（不支援時自動改為不要求）")
            check("auto_retry", "遇到 429／500／502／503／504 時自動重試（最多 2 次）")
            check("auto_record", "每次執行自動存檔到「紀錄」資料夾")

            ttk.Label(body, text="金鑰來源優先順序（同名環境變數兩處的值不同時）", style="Section.TLabel").pack(anchor="w", pady=(12, 2))
            self.priority_var = tk.StringVar(value=self.prefs.get("key_priority", PRIORITY_SYSTEM))
            for value, text in PRIORITY_LABELS.items():
                ttk.Radiobutton(body, text=text, value=value, variable=self.priority_var,
                                command=self._on_prefs_changed).pack(anchor="w", pady=1)
            row = ttk.Frame(body, style="Surface.TFrame")
            row.pack(fill="x", pady=(16, 0))
            ttk.Button(row, text="儲存設定", command=self.save_settings).pack(side="left")
            ttk.Button(row, text="設定備份", style="Ghost.TButton",
                       command=lambda: self._open_dir(SETTINGS_BACKUP_DIR)).pack(side="left", padx=6)
            ttk.Button(row, text="日誌", style="Ghost.TButton", command=lambda: self._open_dir(LOG_DIR)).pack(side="left")
            ttk.Label(body, text=f"設定檔：{SETTINGS_PATH}", style="Muted.TLabel", wraplength=380).pack(anchor="w", pady=(10, 0))

        def _build_theme_tab(self, tab):
            scroll = ScrollFrame(self, tab)
            scroll.pack(fill="both", expand=True)
            self.theme_scroll = scroll
            body = scroll.inner
            ttk.Label(body, text="主題", style="Section.TLabel").pack(anchor="w")
            row = ttk.Frame(body, style="Surface.TFrame")
            row.pack(fill="x", pady=(4, 12))
            self.theme_var = tk.StringVar(value=self.theme.name)
            for i, name in enumerate(THEMES):
                ttk.Radiobutton(row, text=name, value=name, variable=self.theme_var,
                                command=self._on_theme_changed).grid(row=i // 3, column=i % 3, sticky="w", padx=(0, 16), pady=2)

            ttk.Label(body, text="字體", style="Section.TLabel").pack(anchor="w")
            families = sorted({f for f in tkfont.families(self) if not f.startswith("@")})
            grid = ttk.Frame(body, style="Surface.TFrame")
            grid.pack(fill="x", pady=(4, 12))
            grid.columnconfigure(1, weight=1)
            self.font_var = tk.StringVar(value=self.prefs.get("font_family") or DEFAULT_UI_FONT)
            self.content_font_var = tk.StringVar(value=self.prefs.get("content_family") or DEFAULT_UI_FONT)
            self.font_size_var = tk.StringVar(value=str(self.prefs.get("font_size", 10)))
            self.reply_size_var = tk.StringVar(value=str(self.prefs.get("reply_font_size", 11)))
            for r, (label, var, values) in enumerate((("介面字體", self.font_var, families),
                                                      ("內容字體（回覆、提示詞）", self.content_font_var, families))):
                ttk.Label(grid, text=label, style="Value.TLabel").grid(row=r, column=0, sticky="w", pady=3, padx=(0, 8))
                box = ttk.Combobox(grid, textvariable=var, values=values, width=26)
                box.grid(row=r, column=1, sticky="ew", pady=3)
                box.bind("<<ComboboxSelected>>", lambda _e: self._on_font_changed())
                box.bind("<Return>", lambda _e: self._on_font_changed())
            for r, (label, var, lo, hi) in enumerate((("介面字級", self.font_size_var, 8, 16),
                                                      ("內容字級", self.reply_size_var, 8, 22)), start=2):
                ttk.Label(grid, text=label, style="Value.TLabel").grid(row=r, column=0, sticky="w", pady=3, padx=(0, 8))
                ttk.Spinbox(grid, from_=lo, to=hi, width=5, textvariable=var, state="readonly",
                            command=self._on_font_changed).grid(row=r, column=1, sticky="w", pady=3)

            ttk.Label(body, text="配色（只影響目前主題）", style="Section.TLabel").pack(anchor="w")
            colors = ttk.Frame(body, style="Surface.TFrame")
            colors.pack(fill="x", pady=(4, 4))
            self.swatches = {}
            for i, (key, label) in enumerate(THEME_KEYS.items()):
                cell = ttk.Frame(colors, style="Surface.TFrame")
                cell.grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 18), pady=2)
                sw = tk.Label(cell, width=3, relief="flat", bd=0, cursor="hand2")
                sw.pack(side="left")
                sw.bind("<Button-1>", lambda _e, k=key: self._pick_color(k))
                ttk.Label(cell, text=label, style="Value.TLabel").pack(side="left", padx=(6, 0))
                self.swatches[("c", key)] = sw
            ttk.Button(body, text="重設此主題配色", style="Ghost.TButton", command=self._reset_colors).pack(anchor="w", pady=(4, 12))

            ttk.Label(body, text="角色顏色", style="Section.TLabel").pack(anchor="w")
            roles = ttk.Frame(body, style="Surface.TFrame")
            roles.pack(fill="x", pady=(4, 4))
            for i, role in enumerate(ROLES):
                cell = ttk.Frame(roles, style="Surface.TFrame")
                cell.grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 18), pady=2)
                sw = tk.Label(cell, width=3, relief="flat", bd=0, cursor="hand2")
                sw.pack(side="left")
                sw.bind("<Button-1>", lambda _e, r=role: self._pick_role_color(r))
                ttk.Label(cell, text=role, style="Value.TLabel").pack(side="left", padx=(6, 0))
                self.swatches[("r", role)] = sw
            ttk.Button(body, text="重設角色顏色", style="Ghost.TButton", command=self._reset_role_colors).pack(anchor="w", pady=(4, 12))

            ttk.Label(body, text="拓樸圖", style="Section.TLabel").pack(anchor="w")
            self.grid_var = tk.BooleanVar(value=self.prefs.get("show_grid", True))
            self.anim_var = tk.BooleanVar(value=self.prefs.get("animate", True))
            ttk.Checkbutton(body, text="顯示背景格點", variable=self.grid_var, command=self._on_canvas_prefs).pack(anchor="w", pady=2)
            ttk.Checkbutton(body, text="播放動畫（機器人動作、流動光點、旋轉外圈）", variable=self.anim_var,
                            command=self._on_canvas_prefs).pack(anchor="w", pady=2)
            ttk.Label(body, text="點色塊即可自訂顏色；所有外觀設定會自動套用，按 Ctrl+S 或關閉時儲存。",
                      style="Muted.TLabel", wraplength=420).pack(anchor="w", pady=(10, 0))

        def _refresh_swatches(self):
            for (kind, key), sw in self.swatches.items():
                color = self.theme[key] if kind == "c" else self.theme.role_color(key)
                try:
                    sw.configure(bg=color, activebackground=color, highlightthickness=1,
                                 highlightbackground=self.theme["border"])
                except tk.TclError:
                    pass

        def _on_theme_changed(self):
            self.prefs["theme"] = self.theme_var.get()
            self._mark_dirty()
            self._apply_theme()

        def _on_font_changed(self):
            families = set(tkfont.families(self))
            for key, var in (("font_family", self.font_var), ("content_family", self.content_font_var)):
                value = var.get().strip()
                if value in families:
                    self.prefs[key] = value
                else:
                    var.set(self.prefs.get(key) or DEFAULT_UI_FONT)
            for key, var, lo, hi in (("font_size", self.font_size_var, 8, 16), ("reply_font_size", self.reply_size_var, 8, 22)):
                try:
                    self.prefs[key] = max(lo, min(hi, int(var.get())))
                except ValueError:
                    pass
            self._mark_dirty()
            self._apply_theme()

        def _on_canvas_prefs(self):
            self.prefs["show_grid"] = bool(self.grid_var.get())
            self.prefs["animate"] = bool(self.anim_var.get())
            self._mark_dirty()
            self._apply_theme()

        def _pick_color(self, key):
            result = colorchooser.askcolor(color=self.theme[key], parent=self, title=f"選擇顏色：{THEME_KEYS[key]}")
            if result and result[1]:
                overrides = self.prefs.setdefault("color_overrides", {}).setdefault(self.theme.name, {})
                overrides[key] = result[1].upper()
                self._mark_dirty()
                self._apply_theme()

        def _pick_role_color(self, role):
            result = colorchooser.askcolor(color=self.theme.role_color(role), parent=self, title=f"角色顏色：{role}")
            if result and result[1]:
                self.prefs.setdefault("role_colors", {})[role] = result[1].upper()
                self._mark_dirty()
                self._apply_theme()

        def _reset_colors(self):
            self.prefs.setdefault("color_overrides", {}).pop(self.theme.name, None)
            self._mark_dirty()
            self._apply_theme()

        def _reset_role_colors(self):
            self.prefs["role_colors"] = {}
            self._mark_dirty()
            self._apply_theme()


        # ───────────── 模型與 API（端點）管理 ─────────────
        def _rebuild_editors(self):
            if not hasattr(self, "endpoint_scroll"):
                self.count_var.set(str(len(self.services)))
                return
            for child in self.endpoint_scroll.inner.winfo_children():
                child.destroy()
            self._tk_widgets = [(w, k) for w, k in self._tk_widgets if w.winfo_exists()]
            self.editors = {}
            for i, service in enumerate(self.services):
                self.editors[service["id"]] = EndpointEditor(self, self.endpoint_scroll.inner, service, i)
            removed = self.settings.get("removed_services", [])
            self.removed_combo.configure(values=[f"{s.get('name') or s.get('model')}｜{s.get('removed_at', '')}" for s in removed])
            self.removed_var.set("")
            self.count_var.set(str(len(self.services)))

        def on_service_changed(self, service):
            self._mark_dirty()
            self._refresh_hub_choices()
            if self._graph_job:
                self.after_cancel(self._graph_job)
            self._graph_job = self.after(300, self._after_service_edit)

        def _after_service_edit(self):
            self._graph_job = None
            self._refresh_model_choices()
            self._update_header()
            self.runner_key = None
            self._build_team()
            if not self.busy:
                self._graph_for_conversation()

        def _new_service(self, template=None):
            n = len(self.services) + 1
            roles = list(ROLES)
            base = template or {}
            service = normalize_service({
                "name": short_model(base.get("model")) or f"AI {n}", "role": roles[(n - 1) % len(roles)],
                "url": base.get("url") or f"https://{NVIDIA_HOST}/v1", "model": base.get("model", ""),
                "temperature": base.get("temperature", ""), "max_tokens": base.get("max_tokens", ""),
            })
            service["credential"] = (base.get("credential") if base.get("credential") and
                                     looks_like_env_name(base.get("credential")) else DEFAULT_NVIDIA_ENV)
            # 新成員直接用這個身分實測最適合的模型（NVIDIA 服務、且清單裡有才用；沒有就沿用上一位的模型）
            url = service["url"].strip().rstrip("/")
            pick = role_default_model(service["role"], self.model_cache.get(url), url)
            if pick:
                service["model"], service["reasoning"] = pick
                service["name"] = short_model(pick[0]) or service["name"]
            return service

        def role_default_changes(self):
            """列出「依身分套用推薦模型」會改哪些成員：[(service, 新模型, 新思考設定)]。只看 NVIDIA 服務。"""
            out = []
            for sv in self.services:
                url = (sv.get("url") or "").strip().rstrip("/")
                pick = role_default_model(sv.get("role") or DEFAULT_ROLE, self.model_cache.get(url), url)
                if pick and (sv.get("model"), sv.get("reasoning", "")) != pick:
                    out.append((sv, pick[0], pick[1]))
            return out

        def apply_role_defaults(self):
            """一鍵把每位成員換成該身分實測最適合的模型。先列出變更請使用者確認，絕不默默改團隊。"""
            if self.busy:
                self.status_label.configure(text="執行中不能換模型，請等這一輪結束。")
                return
            changes = self.role_default_changes()
            hub_tip = role_default_model("主持")
            agent_tip = role_default_model("Agent")
            tips = (f"\n\n主持與 Agent 是從成員中挑選；實測建議：主持用 {short_model(hub_tip[0]) if hub_tip else '—'}、"
                    f"Agent 用 {short_model(agent_tip[0]) if agent_tip else '—'}（可在設定裡指定）。")
            if not changes:
                messagebox.showinfo(APP_NAME, "每位成員都已經是該身分的推薦模型（或不是 NVIDIA 服務，不套用）。" + tips)
                return
            lines = [f"・{sv.get('name') or '未命名'}（{sv.get('role') or DEFAULT_ROLE}）：{short_model(sv.get('model')) or '未設定'}"
                     f" → {short_model(m)}" + (f"，思考 {REASONING_LABELS.get(r, r)}" if r else "") for sv, m, r in changes]
            if not messagebox.askyesno(APP_NAME, f"依身分套用推薦模型（{ROLE_DEFAULT_SOURCE}），會變更 {len(changes)} 位：\n\n"
                                                 + "\n".join(lines) + tips + "\n\n舊設定會先備份，之後也可以點機器人換回來。要套用嗎？"):
                return
            self.save_settings(quiet=True)          # 先把目前狀態存一次（存檔時會備份舊設定）
            for sv, model, reasoning in changes:
                old_model, old_name = sv.get("model") or "", (sv.get("name") or "").strip()
                auto_name = (not old_name or re.fullmatch(r"AI\s*\d+", old_name) or old_name == short_model(old_model)
                             or (len(old_name) >= 3 and old_name.lower() in old_model.lower()))
                self._apply_model_pick(sv, None, None, None, model, reasoning=reasoning)
                if auto_name and sv.get("name") != short_model(model):    # 名字是照舊模型取的 → 跟著換，避免名不符實
                    sv["name"] = short_model(model)
                    editor = self.editors.get(sv["id"])
                    if editor is not None:
                        try:
                            editor.vars["name"].set(sv["name"])
                        except (tk.TclError, KeyError):
                            pass
            fix_service_names(self.services)
            self.save_settings(quiet=True)
            self._build_team()
            if not self.busy:
                self._graph_for_conversation()
            log.info("依身分套用推薦模型：%s", [(sv.get("name"), m) for sv, m, _r in changes])
            self.status_label.configure(text=f"已依身分套用推薦模型（{len(changes)} 位）。")


        def _after_services_changed(self):
            self._rebuild_editors()
            self._refresh_hub_choices()
            self._refresh_model_choices()
            self._update_header()
            self._mark_dirty()
            self.count_var.set(str(len(self.services)))
            self._build_team()
            if not self.busy:
                self._graph_for_conversation()

        def _add_robot(self):
            if self.busy:
                return
            if len(self.services) >= MAX_AGENTS:
                messagebox.showinfo(APP_NAME, f"最多 {MAX_AGENTS} 個。")
                return
            service = self._new_service(self.services[-1] if self.services else None)
            self.services.append(service)
            fix_service_names(self.services)
            self._after_services_changed()
            self.open_model_picker(service=service)

        def _build_team(self):
            box = getattr(self, "team_box", None)
            if box is None:
                return
            for child in box.winfo_children():
                child.destroy()
            t = self.theme
            agent_id = self.conv.get("model_id") if getattr(self, "conv", None) else None
            agent_id = agent_id or self.prefs.get("agent_model_id")
            for x in self.services:
                row = tk.Frame(box, bg=t["side"], cursor="hand2")
                row.pack(fill="x", pady=2)
                dot = tk.Canvas(row, width=12, height=12, highlightthickness=0, bg=t["side"])
                dot.create_oval(2, 2, 11, 11, fill=t.role_color(x.get("role") or DEFAULT_ROLE), outline="")
                dot.grid(row=0, column=0, rowspan=2, sticky="n", pady=(4, 0), padx=(0, 8))
                name = (x.get("name") or "未命名") + ("（Agent）" if x["id"] == agent_id else "")
                a = tk.Label(row, text=name, bg=t["side"], fg=t["text"], font=self.fonts["ui_bold"], anchor="w")
                a.grid(row=0, column=1, sticky="w")
                b = tk.Label(row, text=(f"{x.get('role') or DEFAULT_ROLE}・{short_model(x.get('model'))}" if x.get("model")
                                        else "未設定模型 → 點這裡選") + (f"\n工作：{x['task'][:40]}" if x.get("task") else ""),
                             bg=t["side"], justify="left",
                             fg=t["muted"] if x.get("model") else t["danger"], font=self.fonts["small"], anchor="w")
                b.grid(row=1, column=1, sticky="w")
                row.columnconfigure(1, weight=1)
                for w in (row, dot, a, b):
                    w.bind("<Button-1>", lambda _e, sv=x: self.open_model_picker(service=sv))

        def open_cli_dialog(self):
            """v6.10：加入 Claude Code／Codex（用已登入的訂閱額度，不需要 API 金鑰）。"""
            win = tk.Toplevel(self)
            win.title("訂閱 CLI：Claude Code／Codex")
            win.transient(self)
            win.configure(bg=self.theme["surface"])
            body = ttk.Frame(win, style="Surface.TFrame", padding=16)
            body.pack(fill="both", expand=True)
            ttk.Label(body, text="用訂閱額度呼叫 Claude Code／Codex", style="Title.TLabel").pack(anchor="w")
            ttk.Label(body, text="不需要 API 金鑰：程式會在背景執行你電腦上已登入的 claude／codex 命令列工具，"
                                 "花的是 Claude 訂閱（Pro／Max）或 ChatGPT 訂閱（Plus／Pro）的額度。\n"
                                 "當 Agent 主模型時，它會自己在工作資料夾裡讀檔、改檔、跑指令；改過的檔案照樣會備份、可以復原。",
                      style="Muted.TLabel", wraplength=520, justify="left").pack(anchor="w", pady=(4, 10))
            kind_var = tk.StringVar(value="claude")
            found = {k: find_cli(k) for k in CLI_KINDS}
            for k, info in CLI_KINDS.items():
                text = f"{info['label']}（{info['plan']}）　" + ("✔ 已安裝" if found[k] else "✘ 找不到")
                ttk.Radiobutton(body, text=text, value=k, variable=kind_var,
                                command=lambda: kind_changed()).pack(anchor="w", pady=2)
            row = ttk.Frame(body, style="Surface.TFrame")
            row.pack(fill="x", pady=(10, 4))
            ttk.Label(row, text="模型").pack(side="left")
            model_var = tk.StringVar(value=CLI_KINDS["claude"]["default"])
            combo = ttk.Combobox(row, textvariable=model_var, width=24, values=CLI_KINDS["claude"]["models"])
            combo.pack(side="left", padx=6)
            ttk.Label(row, text="（claude-code／codex＝用 CLI 預設的模型）", style="Muted.TLabel").pack(side="left")
            status = ttk.Label(body, text="", style="Muted.TLabel", wraplength=520, justify="left")
            status.pack(anchor="w", pady=(8, 8))

            def kind_changed():
                k = kind_var.get()
                combo.configure(values=CLI_KINDS[k]["models"])
                model_var.set(CLI_KINDS[k]["default"])
                status.configure(text=(f"位置：{found[k]}" if found[k] else
                                       f"找不到 {CLI_KINDS[k]['label']}。請先安裝並登入（{CLI_KINDS[k]['login']}），再重新開啟這個視窗。"),
                                 foreground=self.theme["muted"] if found[k] else self.theme["danger"])

            def test():
                k, m = kind_var.get(), model_var.get().strip()
                status.configure(text=f"測試 {CLI_KINDS[k]['label']} 中…（第一次可能要 10～30 秒）", foreground=self.theme["muted"])

                def work():
                    ok, msg, secs = test_model(f"cli://{k}", "", m)
                    self.ui_queue.put(("ui", None, "call", lambda: win.winfo_exists() and status.configure(
                        text=("✔ " if ok else "✘ ") + f"{msg}（{secs:.0f} 秒）",
                        foreground=self.theme["success"] if ok else self.theme["danger"])))

                threading.Thread(target=work, daemon=True).start()

            def add(as_agent):
                k, m = kind_var.get(), model_var.get().strip() or CLI_KINDS[kind_var.get()]["default"]
                if not found[k]:
                    messagebox.showerror(APP_NAME, f"找不到 {CLI_KINDS[k]['label']}，請先安裝並登入。", parent=win)
                    return
                url = f"cli://{k}"
                service = next((x for x in self.services if x.get("url") == url and x.get("model") == m), None)
                if service is None:
                    if len(self.services) >= MAX_AGENTS:
                        messagebox.showinfo(APP_NAME, f"最多 {MAX_AGENTS} 個。", parent=win)
                        return
                    service = normalize_service({"name": CLI_KINDS[k]["label"] + ("" if m == CLI_KINDS[k]["default"] else f"・{m}"),
                                                 "role": DEFAULT_ROLE, "url": url, "model": m})
                    service["credential"] = NO_KEY
                    self.services.append(service)
                if as_agent:
                    self.conv["model_id"] = service["id"]
                    self.prefs["agent_model_id"] = service["id"]
                    self.runner_key = None
                self._mark_dirty()
                self._after_services_changed()
                if as_agent:
                    self._refresh_model_choices()
                    self._graph_for_conversation()
                win.destroy()
                self.status_label.configure(text=f"已加入 {service['name']}" + ("，並設為 Agent 主模型" if as_agent else ""))

            bar = ttk.Frame(body, style="Surface.TFrame")
            bar.pack(fill="x")
            ttk.Button(bar, text="測試（會用掉一點額度）", style="Ghost.TButton", command=test).pack(side="left")
            ttk.Button(bar, text="關閉", style="Ghost.TButton", command=win.destroy).pack(side="right")
            ttk.Button(bar, text="設為 Agent 主模型", command=lambda: add(True)).pack(side="right", padx=6)
            ttk.Button(bar, text="加入 AI 團隊", command=lambda: add(False)).pack(side="right")
            kind_changed()
            win.grab_set()

        def add_service(self):
            if len(self.services) >= MAX_AGENTS:
                messagebox.showinfo(APP_NAME, f"最多 {MAX_AGENTS} 個。")
                return
            self.services.append(self._new_service(self.services[-1] if self.services else None))
            fix_service_names(self.services)
            self._after_services_changed()
            self.open_settings("模型與 API")
            self.after(150, lambda: self.endpoint_scroll.canvas.yview_moveto(1.0))

        def _on_count_changed(self):
            if self.busy:
                self.count_var.set(str(len(self.services)))
                return
            try:
                target = max(1, min(MAX_AGENTS, int(self.count_var.get())))
            except ValueError:
                self.count_var.set(str(len(self.services)))
                return
            current = len(self.services)
            if target == current:
                return
            if target > current:
                for _ in range(target - current):
                    self.services.append(self._new_service(self.services[-1] if self.services else None))
                fix_service_names(self.services)
                msg = f"已新增 {target - current} 位 AI（沿用最後一位的網址、金鑰與模型），可到「端點」分頁調整。"
            else:
                stamp = time.strftime("%Y-%m-%d %H:%M")
                for service in self.services[target:]:
                    self.settings.setdefault("removed_services", []).append(self._removed_copy(service, stamp))
                del self.services[target:]
                msg = f"已移除 {current - target} 位 AI（移到「已移除」清單，可在「端點」分頁還原）。"
            self._after_services_changed()
            self.status_label.configure(text=msg)

        @staticmethod
        def _removed_copy(service, stamp):
            saved = {k: v for k, v in service.items() if k != "credential" and not k.startswith("_")}
            cred = service.get("credential", "")
            saved["credential_env"] = cred if looks_like_env_name(cred) else service.get("credential_env", "")
            saved["removed_at"] = stamp
            return saved

        def remove_service(self, service):
            if self.busy:
                return
            if not messagebox.askyesno(APP_NAME, f"要移除「{service.get('name') or service.get('model')}」嗎？\n"
                                                 "（不會永久刪除，會移到「已移除」清單，可隨時還原。）"):
                return
            self.services.remove(service)
            self.settings.setdefault("removed_services", []).append(self._removed_copy(service, time.strftime("%Y-%m-%d %H:%M")))
            self._after_services_changed()

        def restore_service(self):
            index = self.removed_combo.current()
            removed = self.settings.get("removed_services", [])
            if index < 0 or index >= len(removed):
                messagebox.showinfo(APP_NAME, "請先選擇要還原的 AI。")
                return
            service = normalize_service(removed.pop(index))
            service["credential"] = service.get("credential_env", "")
            self.services.append(service)
            self._after_services_changed()

        def move_service(self, service, step):
            i = self.services.index(service)
            j = i + step
            if 0 <= j < len(self.services) and not self.busy:
                self.services[i], self.services[j] = self.services[j], self.services[i]
                self._after_services_changed()

        def _service(self, pid):
            return next((s for s in self.services if s["id"] == pid), None)

        def _refresh_hub_choices(self):
            self.hub_combo.configure(values=[self._label(s) for s in self.services])
            hub = self._service(self.prefs.get("hub_id"))
            if not hub and self.services:
                hub = self.services[0]
                self.prefs["hub_id"] = hub["id"]
            self.hub_var.set(self._label(hub) if hub else "")

        @staticmethod
        def _label(service):
            return f"{service.get('name') or '未命名'}｜{service.get('model') or '未設定模型'}"


        def _refresh_graph(self):
            self._graph_job = None

        def _on_web_research(self):
            self.prefs["web_research"] = bool(self.web_research_var.get())
            if hasattr(self, "bool_vars") and "web_research" in self.bool_vars:
                self.bool_vars["web_research"].set(self.prefs["web_research"])
            self._mark_dirty()

        def _on_mode_changed(self):
            self._on_prefs_changed()
            if self.conv["type"] == "council" and not self.busy:
                self._graph_for_conversation()
            self.rounds_spin.configure(state="readonly" if self.mode_var.get() == MODE_REVIEW else "disabled")
            self.hub_combo.configure(state="readonly" if self.mode_var.get() in (MODE_SYNTH, MODE_REVIEW, MODE_PLAN) else "disabled")
            self._update_header()

        def _on_hub_changed(self):
            index = self.hub_combo.current()
            if 0 <= index < len(self.services):
                self.prefs["hub_id"] = self.services[index]["id"]
            self._on_prefs_changed()

        def _on_prefs_changed(self):
            p = self.prefs
            p["mode"] = self.mode_var.get()
            try:
                p["review_rounds"] = max(1, min(5, int(self.rounds_var.get())))
            except ValueError:
                p["review_rounds"] = 1
            if hasattr(self, "num_vars"):
                p["system_prompt"] = self.system_text.get("1.0", "end-1c").strip()
                for key, var in self.bool_vars.items():
                    p[key] = bool(var.get())
                if hasattr(self, "web_research_var"):
                    self.web_research_var.set(bool(p.get("web_research", True)))
                for key, (var, lo, hi) in self.num_vars.items():
                    try:
                        p[key] = max(lo, min(hi, int(float(var.get()))))
                    except ValueError:
                        pass
                p["key_priority"] = self.priority_var.get()
            self._mark_dirty()

        def _fetch_models_async(self, service, callback):
            url = service.get("url", "").strip()
            info = resolve_credential(service.get("credential", ""), self.prefs.get("key_priority"))
            if not url:
                callback([], "請先填 API 網址")
                return
            if info["error"]:
                callback([], info["error"])
                return

            def work():
                models, error = fetch_models(url, info["key"])
                self.ui_queue.put(("ui", None, "call", lambda: self._models_loaded(url, models, error, callback)))

            threading.Thread(target=work, daemon=True).start()

        def _models_loaded(self, url, models, error, callback):
            if models:
                self.model_cache[url.rstrip("/")] = models
                for editor in self.editors.values():
                    if editor.service.get("url", "").strip().rstrip("/") == url.rstrip("/"):
                        editor.model_combo.configure(values=models)
            callback(models, error)

        def open_model_picker(self, editor=None, service=None, title_hint=""):
            """選擇模型視窗。從設定頁開（editor）或點拓樸圖上的機器人開（service）。
            上方可換「金鑰環境變數」，程式會自動猜 API 網址並抓取該服務可用的模型清單（只讀名稱，不顯示金鑰）。"""
            service = editor.service if editor else service
            if service is None:
                return
            if self.busy and not editor:
                self.status_label.configure(text="執行中不能換模型，請等這一輪結束或先按「停止」。")
                return
            old = getattr(self, "_picker_win", None)
            if old is not None:
                try:
                    old.destroy()
                except tk.TclError:
                    pass
            win = tk.Toplevel(self)
            self._picker_win = win
            win.title(f"選擇模型：{title_hint or service.get('name') or '未命名'}")
            win.configure(bg=self.theme["surface"])
            win.transient(self)
            win.geometry(f"{int(680 * self.scale)}x{int(640 * self.scale)}")
            body = ttk.Frame(win, style="Surface.TFrame", padding=12)
            body.pack(fill="both", expand=True)
            cur_cred = (editor.vars["credential"].get() if editor else service.get("credential", "")).strip()
            cur_url = (editor.vars["url"].get() if editor else service.get("url", "")).strip()
            local_mode = tk.BooleanVar(value=cur_cred == NO_KEY or is_local_url(cur_url))
            env_var = tk.StringVar(value=cur_cred if looks_like_env_name(cur_cred) and cur_cred != NO_KEY else "")
            url_var = tk.StringVar(value=cur_url)
            is_hub = title_hint.startswith(("主持", "Agent"))
            # 身分與工作：決定這位 AI 負責什麼；推薦模型會跟著身分改變
            role_var = tk.StringVar(value=(editor.vars["role"].get() if editor else service.get("role")) or DEFAULT_ROLE)
            task_var = tk.StringVar(value=service.get("task", ""))
            who = ttk.Frame(body, style="Surface.TFrame")
            who.pack(fill="x", pady=(0, 8))
            ttk.Label(who, text="身分", style="Muted.TLabel", width=14).grid(row=0, column=0, sticky="w", padx=(0, 8))
            role_combo = ttk.Combobox(who, textvariable=role_var, values=list(ROLES), state="readonly", width=12)
            role_combo.grid(row=0, column=1, sticky="w", pady=2)
            role_desc = ttk.Label(who, text="", style="Muted.TLabel")
            role_desc.grid(row=0, column=2, sticky="w", padx=(10, 0))
            ttk.Label(who, text="工作（選填）", style="Muted.TLabel", width=14).grid(row=1, column=0, sticky="w", padx=(0, 8))
            task_entry = ttk.Entry(who, textvariable=task_var)
            task_entry.grid(row=1, column=1, columnspan=2, sticky="ew", pady=2)
            who.columnconfigure(2, weight=1)
            if is_hub:
                for w in who.winfo_children():
                    w.grid_remove()
                who.pack_forget()
            src_row = ttk.Frame(body, style="Surface.TFrame")
            src_row.pack(fill="x", pady=(0, 6))
            src_cloud = ttk.Button(src_row, text="☁  雲端服務（用金鑰）", style="Seg.TButton", command=lambda: set_source(False))
            src_cloud.pack(side="left", fill="x", expand=True)
            src_local = ttk.Button(src_row, text="⌂  本機模型（Ollama、LM Studio…）", style="Seg.TButton",
                                   command=lambda: set_source(True))
            src_local.pack(side="left", fill="x", expand=True, padx=(2, 0))
            grid = ttk.Frame(body, style="Surface.TFrame")
            grid.pack(fill="x")
            first_label = ttk.Label(grid, text="金鑰（環境變數）", style="Muted.TLabel", width=14)
            first_label.grid(row=0, column=0, sticky="w", padx=(0, 8))
            env_combo = ttk.Combobox(grid, textvariable=env_var, values=list_key_env_names([env_var.get()]), width=28)
            env_combo.grid(row=0, column=1, sticky="ew", pady=2)
            local_var = tk.StringVar()
            local_combo = ttk.Combobox(grid, textvariable=local_var, state="readonly", width=28)
            local_combo.grid(row=0, column=1, sticky="ew", pady=2)
            local_found = {}       # 顯示文字 → 網址
            ttk.Label(grid, text="API 網址", style="Muted.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 8))
            url_entry = ttk.Entry(grid, textvariable=url_var)
            url_entry.grid(row=1, column=1, sticky="ew", pady=2)
            grid.columnconfigure(1, weight=1)
            think_row = ttk.Frame(body, style="Surface.TFrame")
            think_row.pack(fill="x", pady=(4, 0))
            ttk.Label(think_row, text="思考", style="Muted.TLabel", width=14).pack(side="left", padx=(0, 8))
            cur_reason = service.get("reasoning", "")
            if not cur_reason and local_mode.get():
                cur_reason = "none"
            reason_var = tk.StringVar(value=REASONING_LABELS.get(cur_reason, "模型預設"))
            ttk.Combobox(think_row, textvariable=reason_var, values=list(REASONING_LABELS.values()), state="readonly",
                         width=16).pack(side="left")
            ttk.Label(think_row, text="本機思考模型建議關閉（實測 2 分鐘 → 3 秒）",
                      style="Muted.TLabel").pack(side="left", padx=(8, 0))
            env_note = ttk.Label(body, text="", style="Muted.TLabel", wraplength=int(560 * self.scale))
            env_note.pack(fill="x", pady=(2, 6))
            ttk.Label(body, text="搜尋模型（可輸入部分名稱，例如 deepseek、llama、qwen）", style="Muted.TLabel").pack(anchor="w")
            query = tk.StringVar()
            entry = ttk.Entry(body, textvariable=query)
            entry.pack(fill="x", pady=(4, 6))
            # 模型種類分頁：全部／對話／視覺／語音／圖像／嵌入／其他（依名稱判斷）
            kind_var = tk.StringVar(value="對話")
            kind_row = ttk.Frame(body, style="Surface.TFrame")
            kind_row.pack(fill="x")
            kind_buttons = {}
            for k in ("全部",) + MODEL_KINDS:
                b = ttk.Button(kind_row, text=k, style="Seg.TButton", width=-6, command=lambda kk=k: (kind_var.set(kk), refill()))
                b.pack(side="left", padx=(0, 2), fill="x", expand=True)
                kind_buttons[k] = b
            kind_help = ttk.Label(body, text="", style="Muted.TLabel")
            kind_help.pack(anchor="w", pady=(2, 0))
            row = ttk.Frame(body, style="Surface.TFrame")
            row.pack(side="bottom", fill="x", pady=(8, 0))
            status = ttk.Label(body, text="", style="Muted.TLabel", wraplength=int(600 * self.scale))
            status.pack(side="bottom", fill="x")
            tree_wrap = ttk.Frame(body, style="Surface.TFrame")
            tree_wrap.pack(fill="both", expand=True, pady=(6, 6))
            box = ttk.Treeview(tree_wrap, columns=("kind",), show="tree headings", selectmode="browse",
                               style="Picker.Treeview", height=8)
            box.heading("#0", text="模型", anchor="w")
            box.heading("kind", text="種類", anchor="w")
            box.column("#0", width=int(420 * self.scale), stretch=True)
            box.column("kind", width=int(90 * self.scale), stretch=False)
            vsb = ttk.Scrollbar(tree_wrap, orient="vertical", command=box.yview)
            box.configure(yscrollcommand=vsb.set)
            box.pack(side="left", fill="both", expand=True)
            vsb.pack(side="right", fill="y")
            for k in MODEL_KINDS:
                box.tag_configure(k, foreground=self.theme.role_color(
                    {"對話": "研究分析", "視覺": "創意發想", "語音": "對話溝通", "圖像": "審查批判", "嵌入": "資料處理",
                     "其他": "一般助理"}[k]))
            shown = []
            role_switched = [False]

            def cred_now():
                if local_mode.get():
                    return NO_KEY
                return env_var.get().strip() or (service.get("credential", "") if service.get("credential") != NO_KEY else "")

            def candidate():
                return dict(service, url=url_var.get().strip(), credential=cred_now())

            def set_source(local, initial=False):
                local_mode.set(local)
                src_cloud.configure(style="SegOn.TButton" if not local else "Seg.TButton")
                src_local.configure(style="SegOn.TButton" if local else "Seg.TButton")
                if local:
                    if not initial and reason_var.get() == REASONING_LABELS[""]:
                        reason_var.set(REASONING_LABELS["none"])
                    first_label.configure(text="本機服務")
                    env_combo.grid_remove()
                    local_combo.grid()
                    if not initial and not is_local_url(url_var.get()):
                        url_var.set(ollama_url())
                    probe()
                else:
                    first_label.configure(text="金鑰（環境變數）")
                    local_combo.grid_remove()
                    env_combo.grid()
                    if not initial and is_local_url(url_var.get()):
                        url_var.set(guess_provider_url(env_var.get()) or f"https://{NVIDIA_HOST}/v1")
                    env_changed(initial=initial)

            def probe():
                env_note.configure(text="正在偵測本機的模型服務（Ollama 11434、LM Studio 1234、llama.cpp 8080…）…")
                local_combo.configure(values=[n for n, _u in LOCAL_SERVERS])

                def work():
                    found = probe_local_servers()
                    installed = ollama_installed_models()
                    self.ui_queue.put(("ui", None, "call", lambda: probed(found, installed)))

                threading.Thread(target=work, daemon=True).start()

            def probed(found, installed):
                if not win.winfo_exists() or not local_mode.get():
                    return
                local_found.clear()
                running = []
                for name, url, models, err in found:
                    if models and not err:
                        label = f"{name}（執行中，{len(models)} 個模型）"
                        running.append(name)
                        self.model_cache[url.rstrip("/")] = models
                    elif name == "Ollama" and installed:
                        label = f"{name}（沒有執行，已下載 {len(installed)} 個）"
                    else:
                        label = f"{name}（沒有偵測到）"
                    local_found[label] = url
                cur = url_var.get().strip().rstrip("/")
                if cur and is_local_url(cur) and not any(u.rstrip("/") == cur for u in local_found.values()):
                    custom = f"目前設定的網址（{cur}）"           # 自訂埠號或區網伺服器：保留，不要被預設清單蓋掉
                    items = list(local_found.items())
                    local_found.clear()
                    local_found[custom] = cur
                    local_found.update(items)
                local_combo.configure(values=list(local_found))
                pick = next((lb for lb, u in local_found.items() if u.rstrip("/") == cur), None)
                if pick is None or (running and "執行中" not in pick and not pick.startswith("目前設定")):
                    pick = next((lb for lb in local_found if "執行中" in lb), pick or next(iter(local_found), ""))
                local_var.set(pick)
                if pick in local_found:
                    url_var.set(local_found[pick])
                msg = ("偵測到執行中的本機服務：" + "、".join(running) + "。不需要金鑰。") if running else \
                    "沒有偵測到執行中的本機模型服務。請先啟動 Ollama（或在 LM Studio 開啟 Local Server），再按「重新抓取」。"
                if installed and "Ollama" not in running:
                    msg += f"\nOllama 模型資料夾（{ollama_models_dir()}）裡已下載 {len(installed)} 個模型。"
                env_note.configure(text=msg)
                load()

            def local_changed(_e=None):
                url = local_found.get(local_var.get())
                if url:
                    url_var.set(url)
                load()

            def refill(*_a):
                models = self.model_cache.get(url_var.get().strip().rstrip("/"), [])
                q = query.get().strip().lower()
                kind = kind_var.get()
                tags = {m: model_tags(m) for m in models}
                counts = {k: sum(1 for m in models if k in tags[m]) for k in MODEL_KINDS}
                for k, b in kind_buttons.items():
                    n = len(models) if k == "全部" else counts[k]
                    b.configure(text=f"{k} {n}" if models else k,
                                style="SegOn.TButton" if k == kind else "Seg.TButton")
                kind_help.configure(text=MODEL_KIND_HELP.get(kind, "服務提供的全部模型"))
                shown[:] = [m for m in models if (not q or q in m.lower()) and (kind == "全部" or kind in tags[m])]
                box.delete(*box.get_children())
                role = role_var.get() or DEFAULT_ROLE
                rec = [] if is_hub else [m for m in recommend_models(role, models) if m in shown]
                role_desc.configure(text=ROLE_MODEL_NOTE.get(role, "") if not is_hub else "")
                for m in rec:                               # 系統推薦排最前面，其他模型照樣可以選
                    rank = tested_rank(role, m)
                    box.insert("", "end", iid="★" + m, text="★ " + m, tags=("rec",),
                               values=("實測首選" if rank == 0 else "實測備用" if rank is not None else "推薦",))
                for m in shown:
                    if m not in rec:
                        box.insert("", "end", iid=m, text=m, values=("・".join(tags[m]),), tags=(model_kind_label(m),))
                current = service.get("model", "")
                if role_switched[0] and rec:              # 換了身分：先選好新身分的首選（按「使用此模型」才會套用）
                    current = rec[0]
                    pick = role_default_model(role, models, url_var.get().strip())
                    if pick and pick[0] == current:
                        reason_var.set(REASONING_LABELS.get(pick[1], "模型預設"))
                role_switched[0] = False
                cur_iid = ("★" + current) if current in rec else current
                if box.exists(cur_iid):
                    box.selection_set(cur_iid)
                    box.see(cur_iid)
                if rec:
                    box.yview_moveto(0)            # 推薦的模型排在最上面，先讓它們看得到
                if models:
                    status.configure(text=f"共 {len(models)} 個模型，顯示 {len(shown)} 個。點兩下或按「使用此模型」套用；"
                                          "種類依名稱判斷，可先「測試」確認能不能呼叫。", foreground=self.theme["muted"])

            def load(force=False):
                if self.model_cache.get(url_var.get().strip().rstrip("/")) and not force:
                    refill()
                    return
                box.delete(*box.get_children())
                status.configure(text="正在從服務抓取模型清單…", foreground=self.theme["muted"])

                def done(models, error):
                    if not win.winfo_exists():
                        return
                    refill()
                    if error:
                        status.configure(text=("⚠ " if models else "抓取失敗：") + error[:240],
                                         foreground=self.theme["warning"] if models else self.theme["danger"])

                self._fetch_models_async(candidate(), done)

            def env_changed(_e=None, initial=False, fetch=True):
                if local_mode.get():
                    return
                name = env_var.get().strip()
                info = lookup_env(name, self.prefs.get("key_priority")) if looks_like_env_name(name) else {"value": None}
                value = clean_key(info.get("value") or "")
                if name.upper().startswith("OLLAMA") or re.match(r"^[A-Za-z]:[\\/]|^/|^~", value):
                    env_note.configure(text=f"「{name}」的內容是{'資料夾路徑' if value else '設定值'}，不是 API 金鑰。"
                                            "本機模型（Ollama 等）請按上方「⌂ 本機模型」，不需要金鑰。")
                    return
                guess = guess_provider_url(name)
                # 使用者換了金鑰變數才自動換網址；剛打開時保留原本的網址（可能是自架或代理）
                if guess and (not url_var.get().strip() or (not initial and guess.rstrip("/") != url_var.get().strip().rstrip("/"))):
                    url_var.set(guess)
                if not name:
                    env_note.configure(text="選一個環境變數；程式只會讀它的值來連線，不會顯示或存下金鑰本體。")
                elif info.get("value"):
                    env_note.configure(text=f"✔ 找到 {name}（{info.get('source')}，指紋 {fingerprint(clean_key(info['value']))}）"
                                            + ("" if guess else "；這個名稱無法自動判斷服務，請確認 API 網址。"))
                else:
                    env_note.configure(text=f"✘ 找不到環境變數 {name}。設定後（setx {name} 金鑰）按「重新抓取」。")
                if fetch:
                    load()

            def chosen():
                sel = box.selection()
                return sel[0].lstrip("★") if sel else (query.get().strip() if not shown else "")

            def use():
                model = chosen()
                if not model:
                    return
                if not likely_chat_model(model) and not messagebox.askyesno(
                        APP_NAME, f"「{model}」看起來是{model_kind_label(model)}模型（{MODEL_KIND_HELP[model_kind_label(model)]}）。\n"
                                  "機器人需要能對話的模型，仍要使用嗎？", parent=win):
                    return
                bad = validate_api_url(url_var.get())
                if bad:
                    status.configure(text=bad, foreground=self.theme["danger"])
                    return
                self._apply_model_pick(service, editor, cred_now(), url_var.get().strip(), model,
                                       None if is_hub else role_var.get(), None if is_hub else task_var.get().strip(),
                                       reasoning={v: k for k, v in REASONING_LABELS.items()}.get(reason_var.get(), ""))
                win.destroy()

            def keep_model():
                """只改身分與工作，不換模型。"""
                self._apply_model_pick(service, editor, None, None, service.get("model", ""),
                                       role_var.get(), task_var.get().strip(),
                                       reasoning={v: k for k, v in REASONING_LABELS.items()}.get(reason_var.get(), ""))
                win.destroy()

            def test():
                model = chosen()
                if not model:
                    return
                status.configure(text=f"測試 {model} 中…", foreground=self.theme["muted"])

                def done(ok, msg, secs):
                    if win.winfo_exists():
                        status.configure(text=("✔ " if ok else "✘ ") + f"{model}：{msg}（{secs:.1f} 秒）",
                                         foreground=self.theme["success"] if ok else self.theme["danger"])

                self._test_async(dict(candidate(), model=model), done)

            query.trace_add("write", refill)
            env_combo.bind("<<ComboboxSelected>>", env_changed)
            env_combo.bind("<Return>", env_changed)
            env_combo.bind("<KeyRelease>", lambda _e: env_changed(fetch=False))
            local_combo.bind("<<ComboboxSelected>>", local_changed)
            url_entry.bind("<Return>", lambda _e: load(True))
            box.bind("<Double-Button-1>", lambda _e: use())
            ttk.Button(row, text="重新抓取", style="Ghost.TButton", command=lambda: load(True)).pack(side="left")
            ttk.Button(row, text="測試選取的模型", style="Ghost.TButton", command=test).pack(side="left", padx=6)
            ttk.Button(row, text="使用此模型", style="Primary.TButton", command=use).pack(side="right")
            if not is_hub and service.get("model"):
                ttk.Button(row, text="只更新身分與工作", style="Ghost.TButton", command=keep_model).pack(side="right", padx=6)
            role_combo.bind("<<ComboboxSelected>>", lambda _e: (role_switched.__setitem__(0, True), refill()))
            box.tag_configure("rec", foreground=self.theme["accent"])
            entry.focus_set()
            set_source(local_mode.get(), initial=True)

        def _apply_model_pick(self, service, editor, env_name, url, model, role=None, task=None, reasoning=None):
            """把挑好的金鑰變數、網址、模型（以及身分、工作說明）套用到這位 AI（機器人），並立即存檔、重畫拓樸圖。"""
            editor = editor or self.editors.get(service["id"])
            if reasoning is not None:
                service["reasoning"] = reasoning
                if editor is not None:
                    try:
                        editor.reasoning_var.set(REASONING_LABELS.get(reasoning, "模型預設"))
                    except tk.TclError:
                        pass
            if task is not None:
                service["task"] = task
                if editor is not None:
                    try:
                        editor.vars["task"].set(task)
                    except (tk.TclError, KeyError):
                        pass
            if role and role in ROLES:
                service["role"] = role
                if editor is not None:
                    try:
                        editor.vars["role"].set(role)
                    except tk.TclError:
                        pass
            if editor is not None:
                try:
                    if env_name:
                        editor.vars["credential"].set(env_name)
                    if url:
                        editor.vars["url"].set(url)
                    editor.vars["model"].set(model)
                except tk.TclError:
                    editor = None
            if editor is None:
                old_model, old_name = service.get("model", ""), service.get("name", "")
                if env_name:
                    service["credential"] = env_name
                if url:
                    service["url"] = url
                service["model"] = model
                service.pop("_tested", None)
                if not old_name or re.fullmatch(r"AI\s*\d+", old_name) or old_name == short_model(old_model):
                    service["name"] = short_model(model) or old_name
                self.on_service_changed(service)
            if fix_service_names(self.services) and editor is not None:
                try:
                    editor.vars["name"].set(service["name"])
                except (tk.TclError, KeyError):
                    pass
            self.save_settings(quiet=True)
            self._refresh_model_choices()
            self._refresh_hub_choices()
            self._build_team()
            if not self.busy:
                self._graph_for_conversation()
            self.status_label.configure(text=f"已更新「{service.get('name')}」：{service.get('role') or DEFAULT_ROLE}・{short_model(model)}"
                                             + (f"・工作：{service['task'][:30]}" if service.get("task") else "") + "（已儲存）。")

        def _test_async(self, service, callback):
            info = ({"key": "", "error": ""} if cli_kind(service.get("url")) else
                    resolve_credential(service.get("credential", ""), self.prefs.get("key_priority")))
            if info["error"]:
                callback(False, info["error"], 0.0)
                return
            if not service.get("url") or not service.get("model"):
                callback(False, "缺少 API 網址或模型名稱", 0.0)
                return
            bad = validate_api_url(service.get("url"))
            if bad:
                callback(False, bad, 0.0)
                return

            def work():
                ok, msg, secs = test_model(service["url"], info["key"], service["model"])
                self.ui_queue.put(("ui", None, "call", lambda: callback(ok, msg, secs)))

            threading.Thread(target=work, daemon=True).start()

        def test_service(self, service):
            editor = self.editors.get(service["id"])
            if editor:
                editor.set_status("測試中…")
            self.graph.set_state(service["id"], "testing", "")
            model = service.get("model")

            def done(ok, msg, secs):
                if service.get("model") != model:
                    return
                service["_tested"] = ok
                ed = self.editors.get(service["id"])
                if ed:
                    ed.set_status(("✔ " if ok else "✘ ") + f"{msg}（{secs:.1f} 秒）", "ok" if ok else "bad")
                if not self.busy:
                    self.graph.set_state(service["id"], "ok" if ok else "bad", f"{secs:.1f}s" if ok else "")

            self._test_async(service, done)

        def test_all(self):
            if self.busy:
                return
            targets = [s for s in self.services if s.get("enabled", True)]
            hub = self._service(self.prefs.get("hub_id"))
            if hub and hub not in targets and self.mode_var.get() in (MODE_SYNTH, MODE_REVIEW):
                targets.append(hub)
            for s in targets:
                self.test_service(s)
            self.status_label.configure(text=f"正在測試 {len(targets)} 個模型能否呼叫…（結果顯示在拓樸圖與端點卡片）")

        def _mark_dirty(self):
            self.dirty = True

        def save_settings(self, quiet=False):
            services = []
            for s in self.services:
                cred = (s.get("credential") or "").strip()
                item = {k: s.get(k, "") for k in ("id", "name", "role", "url", "model", "temperature", "max_tokens", "task", "reasoning",
                                                  "num_ctx", "keep_alive")}
                item["enabled"] = bool(s.get("enabled", True))
                item["credential_env"] = cred if looks_like_env_name(cred) else ""   # 金鑰本體一律不寫入
                services.append(item)
            self.settings["services"] = services
            self.settings["preferences"] = self.prefs
            notes = []
            disk_digest = settings_file_digest()
            if disk_digest and self._settings_digest and disk_digest != self._settings_digest:
                # 另一個程式（例如 Windows 排程啟動的）在這段時間存過設定：先合併，不要整份蓋掉
                disk, _w = load_settings_file()
                notes = merge_external_settings(self.settings, disk)
                log_app.info("設定檔被另一個程式改過，已合併：%s", "；".join(notes) or "沒有需要合併的排程")
            try:
                save_settings_file(self.settings)
            except OSError as exc:
                log_app.exception("儲存設定失敗")
                messagebox.showerror(APP_NAME, f"無法儲存設定：{exc}")
                return False
            self._settings_digest = settings_file_digest()
            if notes:
                self._refresh_schedule_list()
                try:
                    self.status_label.configure(text="設定檔剛被另一個視窗改過，已合併：" + "；".join(notes)[:200])
                except tk.TclError:
                    pass
                quiet = True
            self.dirty = False
            if not quiet:
                self.status_label.configure(text="設定已儲存（金鑰本體不會保存；舊設定已備份）")
            return True


        # ───────────── 範本與附加檔 ─────────────
        def _refresh_templates(self):
            templates = dict(DEFAULT_TEMPLATES)
            templates.update(self.settings.get("templates", {}))
            self.templates = templates

        def _template_menu(self):
            t = self.theme
            menu = tk.Menu(self, tearoff=0, font=self.fonts["ui"], bg=t["surface"], fg=t["text"],
                           activebackground=t["accent_soft"], activeforeground=t["text"])
            for name, content in self.templates.items():
                if content:
                    menu.add_command(label=name, command=lambda c=content: self._insert_template(c))
            menu.add_separator()
            menu.add_command(label="把目前內容存為範本…", command=self.save_template)
            menu.add_command(label="刪除範本…", command=self.delete_template)
            menu.add_command(label="還原已刪除的範本…", command=self.restore_template)
            menu.add_separator()
            menu.add_command(label="匯出範本與 AI 團隊…", command=self.export_bundle_dialog)
            menu.add_command(label="匯入範本與 AI 團隊…", command=self.import_bundle_dialog)
            x = self.template_button.winfo_rootx()
            y = self.template_button.winfo_rooty() - 8
            try:
                menu.tk_popup(x, y)
            finally:
                menu.grab_release()

        def _insert_template(self, content):
            self.prompt.insert("1.0", content)
            self.prompt.mark_set("insert", "end")
            self.prompt.focus_set()
            self._update_char_count()

        def save_template(self):
            content = self.prompt.get("1.0", "end-1c").strip()
            if not content:
                messagebox.showinfo(APP_NAME, "請先在輸入框輸入要存成範本的內容。")
                return
            name = simpledialog.askstring("存為範本", "範本名稱：", parent=self)
            if not name or not name.strip():
                return
            name = name.strip()
            if name in DEFAULT_TEMPLATES:
                messagebox.showerror(APP_NAME, "這是內建範本的名稱，請換一個。")
                return
            custom = self.settings.setdefault("templates", {})
            if name in custom:
                if not messagebox.askyesno(APP_NAME, f"已有「{name}」，要覆蓋嗎？（舊內容可還原）"):
                    return
                self._trash_template(name, custom[name])
            custom[name] = content
            self._refresh_templates()
            self.save_settings(quiet=True)

        def _trash_template(self, name, content):
            trash = self.settings.setdefault("deleted_templates", {})
            key = name if name not in trash else f"{name}（{time.strftime('%m%d_%H%M%S')}）"
            trash[key] = {"content": content, "deleted_at": time.strftime("%Y-%m-%d %H:%M"), "name": name}


        def delete_template(self):
            custom = self.settings.setdefault("templates", {})
            if not custom:
                messagebox.showinfo(APP_NAME, "目前沒有自訂範本（內建範本不能刪除）。")
                return
            name = self._choose("刪除範本", "選擇要刪除的範本（會移到「已刪除」，可還原）：", list(custom))
            if name:
                self._trash_template(name, custom.pop(name))
                self._refresh_templates()
                self.save_settings(quiet=True)

        def restore_template(self):
            trash = self.settings.setdefault("deleted_templates", {})
            if not trash:
                messagebox.showinfo(APP_NAME, "目前沒有已刪除的範本。")
                return
            key = self._choose("還原範本", "選擇要還原的範本：", list(trash))
            if not key:
                return
            item = trash.pop(key)
            name = item.get("name") or key
            custom = self.settings.setdefault("templates", {})
            if name in custom or name in DEFAULT_TEMPLATES:
                name = f"{name}（還原）"
            custom[name] = item.get("content", "")
            self._refresh_templates()
            self.save_settings(quiet=True)

        def _choose(self, title, prompt, options):
            win = tk.Toplevel(self)
            win.title(title)
            win.configure(bg=self.theme["surface"])
            win.transient(self)
            ttk.Label(win, text=prompt, style="Section.TLabel").pack(anchor="w", padx=14, pady=(12, 6))
            box = tk.Listbox(win, height=min(12, len(options)), width=44, relief="flat", highlightthickness=1)
            self._theme_widget(box, "listbox")
            for o in options:
                box.insert("end", o)
            box.pack(fill="both", expand=True, padx=14)
            result = {"value": None}

            def ok():
                sel = box.curselection()
                if sel:
                    result["value"] = options[sel[0]]
                win.destroy()

            ttk.Button(win, text="確定", style="Primary.TButton", command=ok).pack(pady=10)
            box.bind("<Double-Button-1>", lambda _e: ok())
            win.grab_set()
            self.wait_window(win)
            return result["value"]

        def attach_files(self):
            """附加檔案：文字檔貼進提示詞；圖片給視覺模型看；語音檔先轉成文字。"""
            img_types = " ".join(f"*{e}" for e in IMAGE_TYPES)
            paths = filedialog.askopenfilenames(title="附加檔案（文字、圖片或語音）", filetypes=[
                ("全部支援的檔案", " ".join(f"*{e}" for e in TEXT_FILE_EXTS) + " " + img_types + " " + " ".join(f"*{e}" for e in AUDIO_EXTS)),
                ("文字與程式檔", " ".join(f"*{e}" for e in TEXT_FILE_EXTS)), ("圖片", img_types),
                ("語音", " ".join(f"*{e}" for e in AUDIO_EXTS)), ("所有檔案", "*.*")])
            self.add_attachments(paths)

        def add_attachments(self, paths):
            warnings = []
            for path in paths:
                ext = os.path.splitext(path)[1].lower()
                name = os.path.basename(path)
                try:
                    if ext in IMAGE_TYPES:
                        if len(self.attach_images) >= IMAGE_MAX_COUNT:
                            warnings.append(f"{name}：一次最多附 {IMAGE_MAX_COUNT} 張圖片")
                            continue
                        self.attach_images.append(load_image(path))
                        continue
                    if ext in AUDIO_EXTS:
                        self.transcribe_file(path)
                        continue
                    text, warning = read_attachment(path)
                except (OSError, ValueError) as exc:
                    warnings.append(f"{name}：{exc}")
                    continue
                if warning:
                    warnings.append(f"{name}：{warning}")
                self.prompt.insert("insert", format_attachment(path, text))
            self._render_attach_bar()
            self._update_char_count()
            if warnings:
                messagebox.showwarning(APP_NAME, "\n".join(warnings))

        def _image_note(self):
            return ("\n（附圖：" + "、".join(im["name"] for im in self.attach_images) + "）") if self.attach_images else ""

        def _render_attach_bar(self):
            bar = self.attach_bar
            for child in bar.winfo_children():
                child.destroy()
            if not self.attach_images:
                bar.pack_forget()
                return
            bar.pack(fill="x", pady=(6, 0), before=self._attach_row)
            ttk.Label(bar, text="附圖：", style="Muted.TLabel").pack(side="left")
            for i, im in enumerate(self.attach_images):
                ttk.Button(bar, text=f"▣ {im['name'][:18]}  ✕", style="Chip.TButton",
                           command=lambda k=i: (self.attach_images.pop(k), self._render_attach_bar())).pack(side="left", padx=(0, 4))
            ttk.Label(bar, text="（視覺模型才看得到）", style="Muted.TLabel").pack(side="left", padx=(4, 0))

        def _transcribe_service(self):
            sv = self._service(self.prefs.get("transcribe_id"))
            if sv and sv.get("model"):
                return sv
            for sv in self.services:
                if re.search(r"whisper|transcri|asr|speech-to-text|stt", sv.get("model", ""), re.I):
                    return sv
            return None

        def transcribe_file(self, path):
            """語音檔 → 文字（OpenAI 相容的 /audio/transcriptions，例如 OpenAI、Groq 的 whisper），結果插入輸入框。"""
            sv = self._transcribe_service()
            if not sv:
                messagebox.showinfo(APP_NAME, "要把語音轉成文字，需要一位使用語音辨識模型的 AI：\n\n"
                                    "1. 在 AI 團隊按「＋ 新增」\n2. 金鑰選 OPENAI_API_KEY 或 GROQ_API_KEY\n"
                                    "3. 在「語音」分頁選 whisper-1 或 whisper-large-v3\n\n"
                                    "這位 AI 不會參與文字討論，只負責語音轉文字。（NVIDIA 的語音模型不支援這種介面。）")
                return
            cfg, err = self._resolve(sv)
            if err:
                messagebox.showerror(APP_NAME, err)
                return
            name = os.path.basename(path)
            self.status_label.configure(text=f"正在把「{name}」轉成文字（{short_model(cfg['model'])}）…")

            def work():
                try:
                    text = transcribe_audio(cfg["url"], cfg["key"], cfg["model"], path)
                    msg = None
                except Exception as exc:
                    text, msg = "", str(exc)
                self.ui_queue.put(("ui", None, "call", lambda: done(text, msg)))

            def done(text, msg):
                if msg:
                    self.status_label.configure(text=f"語音轉文字失敗：{msg[:160]}")
                    messagebox.showerror(APP_NAME, f"「{name}」轉文字失敗：\n{msg}")
                    return
                self.prompt.insert("end", f"\n[語音轉文字：{name}]\n{text}\n")
                self._update_char_count()
                self.status_label.configure(text=f"已把「{name}」轉成文字（{len(text)} 字），可以修改後再送出。")

            threading.Thread(target=work, daemon=True).start()

        def _update_char_count(self):
            n = len(self.prompt.get("1.0", "end-1c"))
            self.char_label.configure(text=f"{n:,} 字" if n else "")

        # ───────────── 其他 ─────────────
        def _resolve(self, service):
            name = service.get("name") or service.get("model") or "未命名 AI"
            url, model = service.get("url", "").strip(), service.get("model", "").strip()
            if not url or not model:
                return None, f"「{name}」缺少 API 網址或模型名稱。"
            if cli_kind(url):                    # Claude Code／Codex：用已登入的命令列工具，不需要金鑰
                info = {"key": "", "note": "訂閱 CLI（不用金鑰）", "hint": "不需要金鑰（用訂閱額度）", "error": ""}
            elif not url.lower().startswith(("http://", "https://")):
                return None, f"「{name}」的 API 網址需以 http:// 或 https:// 開頭。"
            else:
                info = resolve_credential(service.get("credential", ""), self.prefs.get("key_priority"))
            if info["error"]:
                return None, f"「{name}」：{info['error']}"
            self.key_hints[service["id"]] = info["hint"]
            return {"id": service["id"], "name": name, "role": service.get("role") or DEFAULT_ROLE, "url": url,
                    "model": model, "key": info["key"], "key_note": info["note"],
                    "temperature": service.get("temperature", ""), "max_tokens": service.get("max_tokens", ""),
                    "task": service.get("task", ""), "reasoning": service.get("reasoning", ""),
                    "num_ctx": service.get("num_ctx", ""), "keep_alive": service.get("keep_alive", "")}, None

        @staticmethod
        def _fmt_secs(secs):
            secs = int(max(0, secs))
            return f"{secs // 60}:{secs % 60:02d}"

        def _register_response(self, token, pid, response):
            with self.active_lock:
                if response is None:
                    self.active.pop((id(token), pid), None)
                else:
                    self.active[(id(token), pid)] = response
            if response is not None and token.is_set():
                try:
                    response.close()
                except Exception:
                    pass

        def _copy(self, value):
            if not value:
                messagebox.showinfo(APP_NAME, "目前沒有可複製的內容。")
                return
            self.clipboard_clear()
            self.clipboard_append(value)
            self.status_label.configure(text="已複製")

        # ───────────── v6.14：訓練工作室（語言模型蒸餾、語音、影片） ─────────────
        # ── 正確率實測（v6.18.0）──
        def open_bench(self):
            win = getattr(self, "bench_win", None)
            if win is not None and win.winfo_exists():
                win.deiconify()
                win.lift()
                return
            t = self.theme
            win = self.bench_win = tk.Toplevel(self)
            win.title("正確率實測")
            win.configure(bg=t["surface"])
            win.geometry(f"{int(1040 * self.scale)}x{int(780 * self.scale)}")
            win.protocol("WM_DELETE_WINDOW", self._bench_close)
            b = self._bench = {"cancel": None, "result": None, "report": "", "cand_vars": {}, "items": []}
            body = ttk.Frame(win, style="Surface.TFrame", padding=12)
            body.pack(fill="both", expand=True)
            ttk.Label(body, text="用一組能自動評分的題目，實際量你的模型、AI 團隊與 Agent 答對多少。評分全部用規則完成"
                                 "（程式跑測試、比對標準答案、檢查埋好的錯與格式），不用 AI 當裁判。",
                      style="Value.TLabel", wraplength=int(1000 * self.scale), justify="left").pack(anchor="w")
            top = ttk.Frame(body, style="Surface.TFrame")
            top.pack(fill="x", pady=(8, 4))
            left = ttk.Frame(top, style="Surface.TFrame")
            left.pack(side="left", fill="both", expand=True)
            ttk.Label(left, text="受測模型（AI 團隊的成員）", style="Section.TLabel").pack(anchor="w")
            cands = ttk.Frame(left, style="Surface.TFrame")
            cands.pack(fill="x")
            usable = [s for s in self.services if s.get("url") and s.get("model") and likely_chat_model(s.get("model"))]
            for i, s in enumerate(usable[:MAX_AGENTS]):
                var = tk.BooleanVar(value=bool(s.get("enabled", True)))
                b["cand_vars"][s["id"]] = var
                ttk.Checkbutton(cands, variable=var, command=self._bench_estimate,
                                text=f"{s.get('name') or '未命名'}（{short_model(s.get('model'))}・{s.get('role') or DEFAULT_ROLE}）"
                                ).grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 16))
            if not usable:
                ttk.Label(cands, text="還沒有設定任何對話模型，請先到「設定 → 模型與 API」新增。", style="Muted.TLabel").pack(anchor="w")
            extra = ttk.Frame(left, style="Surface.TFrame")
            extra.pack(fill="x", pady=(6, 0))
            ttk.Label(extra, text="另外測這些模型：", style="Value.TLabel").pack(side="left")
            b["extra_models"] = tk.StringVar()
            ent = ttk.Entry(extra, textvariable=b["extra_models"], width=38)
            ent.pack(side="left")
            b["extra_models"].trace_add("write", lambda *_a: self._bench_estimate())
            ttk.Label(extra, text="用", style="Value.TLabel").pack(side="left", padx=(6, 2))
            b["extra_src"] = tk.StringVar(value=(usable[0].get("name") or usable[0]["id"]) if usable else "")
            b["extra_map"] = {(s.get("name") or s["id"]): s for s in usable}
            ttk.Combobox(extra, textvariable=b["extra_src"], values=list(b["extra_map"]), state="readonly", width=16).pack(side="left")
            ttk.Label(extra, text="的網址與金鑰", style="Value.TLabel").pack(side="left", padx=(2, 0))
            ttk.Label(left, text="多個模型用逗號隔開，例如 z-ai/glm-5.3-flash, nvidia/nemotron-3-ultra-550b-a55b（模型清單裡要有）。",
                      style="Muted.TLabel").pack(anchor="w")
            right = ttk.Frame(top, style="Surface.TFrame")
            right.pack(side="left", fill="y", padx=(16, 0))
            ttk.Label(right, text="範圍", style="Section.TLabel").pack(anchor="w")
            b["own_role"] = tk.BooleanVar(value=False)
            ttk.Checkbutton(right, text="每位成員只考自己身分的題目（較省）", variable=b["own_role"],
                            command=self._bench_estimate).pack(anchor="w")
            rep = ttk.Frame(right, style="Surface.TFrame")
            rep.pack(anchor="w")
            ttk.Label(rep, text="每題重複", style="Value.TLabel").pack(side="left")
            b["repeats"] = tk.StringVar(value="1")
            ttk.Spinbox(rep, from_=1, to=3, width=3, textvariable=b["repeats"], command=self._bench_estimate).pack(side="left", padx=4)
            ttk.Label(rep, text="次（看穩不穩定）", style="Value.TLabel").pack(side="left")
            b["team"] = tk.BooleanVar(value=len(usable) >= 2)
            ttk.Checkbutton(right, text="測 AI 團隊的討論模式（同樣的難題）", variable=b["team"],
                            command=self._bench_estimate).pack(anchor="w", pady=(4, 0))
            b["mode_vars"] = {}
            modes_row = ttk.Frame(right, style="Surface.TFrame")
            modes_row.pack(anchor="w", padx=(20, 0))
            for mode in (MODE_SYNTH, MODE_REVIEW, MODE_PLAN):
                v = b["mode_vars"][mode] = tk.BooleanVar(value=True)
                ttk.Checkbutton(modes_row, text=mode, variable=v, command=self._bench_estimate).pack(anchor="w")
            agent = self._service(self.prefs.get("agent_model_id"))
            b["agent"] = tk.BooleanVar(value=bool(agent))
            ttk.Checkbutton(right, text=f"測 Agent（{short_model(agent.get('model')) if agent else '未設定'}，修好一個有錯的程式檔）",
                            variable=b["agent"], command=self._bench_estimate,
                            state="normal" if agent else "disabled").pack(anchor="w", pady=(4, 0))
            row = ttk.Frame(body, style="Surface.TFrame")
            row.pack(fill="x", pady=(8, 2))
            b["start"] = ttk.Button(row, text="▶ 開始實測", style="Primary.TButton", command=self._bench_start)
            b["start"].pack(side="left")
            b["stop"] = ttk.Button(row, text="■ 停止", style="Danger.TButton", command=self._bench_stop, state="disabled")
            b["stop"].pack(side="left", padx=6)
            b["estimate"] = ttk.Label(row, text="", style="Muted.TLabel")
            b["estimate"].pack(side="left", padx=8)
            ttk.Button(row, text="開啟報告資料夾", style="Ghost.TButton",
                       command=lambda: (os.makedirs(BENCH_DIR, exist_ok=True), open_path(BENCH_DIR))).pack(side="right")
            b["open_report"] = ttk.Button(row, text="開啟這次的報告", style="Ghost.TButton", state="disabled",
                                          command=lambda: self._bench.get("report") and open_path(self._bench["report"]))
            b["open_report"].pack(side="right", padx=6)
            b["bar"] = ttk.Progressbar(body, mode="determinate", maximum=100)
            b["bar"].pack(fill="x", pady=(4, 2))
            b["status"] = ttk.Label(body, text="還沒開始。", style="Value.TLabel")
            b["status"].pack(anchor="w")
            cols = ("name",) + BENCH_ROLES + ("score", "secs")
            tree = b["tree"] = ttk.Treeview(body, columns=cols, show="headings", height=9)
            for c, label, w in (("name", "受測者", 230), ("score", "總分", 60), ("secs", "平均秒", 60)):
                tree.heading(c, text=label)
                tree.column(c, width=int(w * self.scale), anchor="w" if c == "name" else "center")
            for role in BENCH_ROLES:
                tree.heading(role, text=role)
                tree.column(role, width=int(70 * self.scale), anchor="center")
            tree.pack(fill="both", expand=True, pady=(6, 4))
            tree.bind("<Double-1>", lambda _e: self._bench_show_detail())
            ttk.Label(body, text="雙擊一列看每題的回答與扣分原因。", style="Muted.TLabel").pack(anchor="w")
            rec_row = ttk.Frame(body, style="Surface.TFrame")
            rec_row.pack(fill="x", pady=(6, 0))
            b["apply"] = ttk.Button(rec_row, text="依結果更新團隊…", style="Ghost.TButton", state="disabled", command=self._bench_apply)
            b["apply"].pack(side="right")
            b["advice"] = tk.Text(body, height=11, wrap="word", relief="flat", highlightthickness=1)
            self._theme_widget(b["advice"], "text")
            b["advice"].pack(fill="x")
            b["advice"].insert("end", "跑完後這裡會列出：每個身分最準的模型、團隊討論有沒有比單一模型準、Agent 能不能真的修好程式。")
            b["advice"].configure(state="disabled")
            self._bench_estimate()

        def _bench_close(self):
            b = getattr(self, "_bench", {})
            if b.get("cancel") is not None and not b["cancel"].is_set():
                if not messagebox.askyesno(APP_NAME, "實測還在跑，關閉視窗會停止它（已完成的題目會存成報告）。確定嗎？", parent=self.bench_win):
                    return
                b["cancel"].set()
            self.bench_win.destroy()

        def _bench_candidates(self):
            """勾選的成員＋「另外測」的模型 → (端點清單, 錯誤訊息清單)。"""
            b = self._bench
            out, errors = [], []
            for sid, var in b["cand_vars"].items():
                if var.get():
                    cfg, err = self._resolve(self._service(sid))
                    if err:
                        errors.append(err)
                    else:
                        out.append(cfg)
            src = b["extra_map"].get(b["extra_src"].get())
            models = [m.strip() for m in re.split(r"[,，\s]+", b["extra_models"].get()) if m.strip()]
            if models and src:
                cfg, err = self._resolve(src)
                if err:
                    errors.append(err)
                else:
                    for m in dict.fromkeys(models):
                        if m != cfg["model"] or src["id"] not in {c["id"] for c in out}:
                            out.append(dict(cfg, id=f"{src['id']}::{m}", model=m, name=short_model(m), role=DEFAULT_ROLE,
                                            reasoning="", task=""))
            return out, errors

        def _bench_team(self):
            selected = [s for s in self.services if s.get("enabled", True) and likely_chat_model(s.get("model"))]
            hub_service = self._service(self.prefs.get("hub_id"))
            if hub_service in selected and len(selected) > 2 and self.prefs.get("hub_exclusive", True):
                selected = [s for s in selected if s is not hub_service]
            agents = [c for c, e in (self._resolve(s) for s in selected) if not e]
            hub = self._resolve(hub_service)[0] if hub_service else None
            return {"agents": agents, "hub": hub} if len(agents) >= 2 else None

        def _bench_settings(self):
            b = self._bench
            cands, errors = self._bench_candidates()
            try:
                repeats = max(1, min(3, int(b["repeats"].get())))
            except ValueError:
                repeats = 1
            modes = [m for m, v in b["mode_vars"].items() if v.get()] if b["team"].get() else []
            team = self._bench_team() if modes else None
            agent = None
            if b["agent"].get():
                agent, err = self._resolve(self._service(self.prefs.get("agent_model_id")) or {})
                if err:
                    errors.append("Agent：" + err)
                    agent = None
            return cands, errors, repeats, modes, team, agent

        def _bench_estimate(self):
            """依勾選的數量估算呼叫次數（不檢查金鑰，金鑰有問題開始時才提醒）。"""
            b = getattr(self, "_bench", None)
            if not b or "estimate" not in b:
                return
            n_cands = sum(1 for v in b["cand_vars"].values() if v.get())
            n_cands += len({m.strip() for m in re.split(r"[,，\s]+", b["extra_models"].get()) if m.strip()})
            try:
                repeats = max(1, min(3, int(b["repeats"].get())))
            except ValueError:
                repeats = 1
            calls = n_cands * (2 if b["own_role"].get() else len(BENCH_TASKS)) * repeats
            note = ""
            if b["team"].get():
                members = [s for s in self.services if s.get("enabled", True) and likely_chat_model(s.get("model"))]
                hub = self._service(self.prefs.get("hub_id"))
                if hub in members and len(members) > 2 and self.prefs.get("hub_exclusive", True):
                    members.remove(hub)
                if len(members) >= 2:
                    modes = [m for m, v in b["mode_vars"].items() if v.get()]
                    calls += sum(expected_calls(m, len(members), 1, bool(hub)) for m in modes) * len(BENCH_TEAM_TASKS) * repeats
                else:
                    note = "（參與的成員少於 2 位，這次不測團隊）"
            if b["agent"].get():
                calls += 8 * repeats
            b["estimate"].configure(text=f"約 {calls} 次 API 呼叫" + note)

        def _bench_start(self):
            b = self._bench
            if b.get("cancel") is not None and not b["cancel"].is_set():
                return
            cands, errors, repeats, modes, team, agent = self._bench_settings()
            if errors:
                messagebox.showwarning(APP_NAME, "這些設定有問題，會略過：\n" + "\n".join(errors[:6]), parent=self.bench_win)
            if not cands and not team and not agent:
                messagebox.showinfo(APP_NAME, "沒有可以測的模型。請勾選成員或輸入要另外測的模型。", parent=self.bench_win)
                return
            roles = None
            own = b["own_role"].get()
            cancel = b["cancel"] = threading.Event()
            b["items"] = []
            b["tree"].delete(*b["tree"].get_children())
            b["start"].configure(state="disabled")
            b["stop"].configure(state="normal")
            b["apply"].configure(state="disabled")
            b["status"].configure(text="實測中…")
            # 只送給「這一次」開的視窗：跑到一半關掉又重開時，舊的結果不會混進新視窗
            put = lambda fn: self.ui_queue.put(("bench", None, "call", lambda: fn() if self._bench is b else None))

            def on_event(kind, payload):
                if kind == "progress":
                    put(lambda p=payload: self._bench_progress(*p))
                elif kind == "item":
                    put(lambda it=payload: self._bench_item(it))

            system_prompt = self.prefs.get("system_prompt") or DEFAULT_SYSTEM_PROMPT

            def worker():
                try:
                    if own:          # 每位成員只考自己身分的題目：分成幾批跑，再合併
                        result = None
                        groups = {}
                        for c in cands:
                            groups.setdefault(c.get("role") if c.get("role") in BENCH_ROLES else DEFAULT_ROLE, []).append(c)
                        parts = [run_benchmark(cs, cancel, on_event, repeats=repeats, roles={role}, system_prompt=system_prompt)
                                 for role, cs in groups.items()]
                        parts.append(run_benchmark([], cancel, on_event, team=team, agent=agent, repeats=repeats, modes=modes,
                                                   system_prompt=system_prompt))
                        result = dict(parts[0], items=[it for p in parts for it in p["items"]],
                                      planned=sum(p["planned"] for p in parts), stopped=cancel.is_set(),
                                      finished=time.strftime("%Y-%m-%d %H:%M:%S"))
                    else:
                        result = run_benchmark(cands, cancel, on_event, team=team, agent=agent, repeats=repeats, roles=roles,
                                               modes=modes, system_prompt=system_prompt)
                    report = save_bench_result(result) if result["items"] else ""
                    put(lambda: self._bench_done(result, report, ""))
                except Exception as exc:
                    log_app.exception("正確率實測失敗")
                    put(lambda e=exc: self._bench_done(None, "", f"{type(e).__name__}：{e}"))

            log_app.info("正確率實測開始：%d 個模型、團隊模式 %s、Agent %s", len(cands), modes, bool(agent))
            threading.Thread(target=worker, daemon=True).start()

        def _bench_stop(self):
            c = self._bench.get("cancel")
            if c is not None:
                c.set()
                self._bench["status"].configure(text="停止中（等進行中的題目結束）…")

        def _bench_alive(self):
            return getattr(self, "bench_win", None) is not None and self.bench_win.winfo_exists()

        def _bench_progress(self, done, total, label):
            if not self._bench_alive():
                return
            self._bench["bar"].configure(value=(100 * done / total) if total else 0)
            self._bench["status"].configure(text=f"{done}／{total}　{label}")

        def _bench_item(self, item):
            if not self._bench_alive():
                return
            self._bench["items"].append(item)
            self._bench_fill_table(bench_summary({"items": self._bench["items"]}))

        def _bench_fill_table(self, summary):
            tree = self._bench["tree"]
            tree.delete(*tree.get_children())
            for r in summary["table"]:
                label = r["name"] + (f"（{short_model(r['model'])}）" if r["kind"] == "single" and r["model"] else "")
                if r["kind"] == "agent":
                    label = f"Agent：{label}"
                cells = [f"{r['roles'][k] * 100:.0f}%" if k in r["roles"] else "" for k in BENCH_ROLES]
                tree.insert("", "end", iid=r["cid"], values=[label] + cells + [f"{r['score'] * 100:.0f}%", f"{r['secs']:.1f}"])

        def _bench_done(self, result, report, error):
            b = self._bench
            b["cancel"] = None
            if not self._bench_alive():
                return
            b["start"].configure(state="normal")
            b["stop"].configure(state="disabled")
            if error:
                b["status"].configure(text="實測失敗：" + error)
                return
            b["result"], b["report"] = result, report
            summary = bench_summary(result)
            self._bench_fill_table(summary)
            b["bar"].configure(value=100)
            b["status"].configure(text=("已停止，" if result.get("stopped") else "完成，") +
                                       f"共 {len(result['items'])} 題。" + (f"報告：{report}" if report else ""))
            if report:
                b["open_report"].configure(state="normal")
            lines = []
            for role, r in summary["best"].items():
                lines.append(f"・{role}：{r['name']}（{short_model(r['model'])}）{r['roles'][role] * 100:.0f}%")
            for t in summary["team_vs"]:
                bs = t["best_single"]
                verdict = ("" if not bs else "，比單一模型最佳還準" if t["score"] > bs[1] + 1e-9 else
                           "，跟單一模型最佳一樣" if abs(t["score"] - bs[1]) < 1e-9 else
                           f"，比單一模型最佳（{bs[0]} {bs[1] * 100:.0f}%）差：這個模式對這組團隊沒有幫助")
                lines.append(f"・團隊「{t['mode']}」：{t['score'] * 100:.0f}%，平均 {t['secs']:.0f} 秒{verdict}")
            for r in (x for x in summary["table"] if x["kind"] == "agent"):
                lines.append(f"・Agent {r['name']}：{r['score'] * 100:.0f}%（{r['secs']:.0f} 秒）")
            box = b["advice"]
            box.configure(state="normal")
            box.delete("1.0", "end")
            box.insert("end", "\n".join(lines) or "沒有完成任何題目。")
            box.configure(state="disabled")
            b["apply"].configure(state="normal" if self._bench_changes(summary) else "disabled")
            log_app.info("正確率實測完成：%d 題，報告 %s", len(result["items"]), report)

        def _bench_changes(self, summary):
            """依實測結果，哪些成員可以換成同一個服務裡分數更高的模型 → [(成員, 新模型, 舊分數, 新分數)]。"""
            out = []
            rows = {r["cid"]: r for r in summary["table"] if r["kind"] == "single"}
            for sv in self.services:
                role = sv.get("role") or DEFAULT_ROLE
                best = summary["best"].get(role)
                if not best or not sv.get("enabled", True):
                    continue
                mine = rows.get(sv["id"])
                src_id = best["cid"].split("::")[0]
                src = self._service(src_id)
                if not src or src.get("url") != sv.get("url") or best["model"] == sv.get("model"):
                    continue
                if mine and mine["roles"].get(role, 0) >= best["roles"][role]:
                    continue
                out.append((sv, best["model"], mine["roles"].get(role) if mine else None, best["roles"][role]))
            return out

        def _bench_apply(self):
            b = self._bench
            if not b.get("result") or self.busy:
                return
            changes = self._bench_changes(bench_summary(b["result"]))
            if not changes:
                messagebox.showinfo(APP_NAME, "每位成員都已經是同一個服務裡分數最高的模型。", parent=self.bench_win)
                return
            lines = [f"・{sv.get('name')}（{sv.get('role')}）：{short_model(sv.get('model'))}"
                     + (f" {old * 100:.0f}%" if old is not None else "（沒測）") + f" → {short_model(m)} {new * 100:.0f}%"
                     for sv, m, old, new in changes]
            if not messagebox.askyesno(APP_NAME, "依實測結果換模型（只換同一個服務裡的模型）：\n\n" + "\n".join(lines)
                                                 + "\n\n舊設定會先備份。要套用嗎？", parent=self.bench_win):
                return
            self.save_settings(quiet=True)
            for sv, model, _old, _new in changes:
                self._apply_model_pick(sv, None, None, None, model)
            fix_service_names(self.services)
            self.save_settings(quiet=True)
            self._build_team()
            log_app.info("依實測結果換模型：%s", [(sv.get("name"), m) for sv, m, _o, _n in changes])
            self.status_label.configure(text=f"已依正確率實測更新 {len(changes)} 位成員的模型。")

        def _bench_show_detail(self):
            b = self._bench
            sel = b["tree"].selection()
            if not sel:
                return
            items = [it for it in b["items"] if it["cid"] == sel[0]]
            if not items:
                return
            top = tk.Toplevel(self.bench_win)
            top.title(f"實測明細：{items[0].get('name')}")
            top.geometry(f"{int(820 * self.scale)}x{int(620 * self.scale)}")
            box = tk.Text(top, wrap="word", relief="flat")
            self._theme_widget(box, "text")
            box.pack(fill="both", expand=True)
            for it in sorted(items, key=lambda x: x["task"]):
                box.insert("end", f"■ {it.get('title')}（{it.get('role')}）　{float(it.get('score') or 0) * 100:.0f}%　"
                                  f"{it.get('elapsed', 0)} 秒\n{it.get('detail', '')}\n")
                if it.get("disagreement"):
                    box.insert("end", f"主持 AI 標示分歧：{it['disagreement']}\n")
                box.insert("end", "── 回答 ──\n" + safe_display(str(it.get("answer") or "（沒有）"))[0][:3000] + "\n\n")
            box.configure(state="disabled")

        # ── 作品檢視（v6.18.1）：圖片在程式裡顯示、WAV 在程式裡播放，其他交給系統程式 ──
        def open_media(self, path, parent=None):
            """打開一個生成的作品或工作區裡的媒體檔。回傳檢視視窗（沒有開視窗時回傳 None）。"""
            info = media_info(path)
            if info["note"]:
                messagebox.showerror(APP_NAME, f"{info['note']}：\n{path}", parent=parent or self)
                return None
            t = self.theme
            win = tk.Toplevel(parent or self)
            win.title(f"{MEDIA_LABELS.get(info['kind'], '檔案')}：{os.path.basename(path)}")
            win.configure(bg=t["surface"])
            body = ttk.Frame(win, style="Surface.TFrame", padding=12)
            body.pack(fill="both", expand=True)
            ttk.Label(body, text=os.path.basename(path), style="Section.TLabel").pack(anchor="w")
            ttk.Label(body, text=media_summary(path) + "　" + path, style="Muted.TLabel",
                      wraplength=int(640 * self.scale), justify="left").pack(anchor="w", pady=(0, 8))
            stage = ttk.Frame(body, style="Surface.TFrame")
            stage.pack(fill="both", expand=True)
            bar = ttk.Frame(body, style="Surface.TFrame")
            bar.pack(fill="x", pady=(10, 0))
            win._media = {"path": path, "kind": info["kind"], "shown": ""}
            kind = info["kind"]
            if kind == "image":
                win._media["shown"] = self._media_show_image(stage, path)
            elif kind == "audio" and sys.platform == "win32" and path.lower().endswith(".wav"):
                import winsound

                def play():
                    try:
                        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
                        state.configure(text="播放中…（按「停止」或關閉視窗結束）")
                    except RuntimeError as exc:
                        state.configure(text=f"程式裡播放失敗（{exc}），請改用系統程式開啟。")

                def stop():
                    winsound.PlaySound(None, 0)
                    state.configure(text="已停止。")
                ttk.Button(stage, text="▶ 播放", style="Primary.TButton", command=play).pack(side="left")
                ttk.Button(stage, text="■ 停止", style="Ghost.TButton", command=stop).pack(side="left", padx=6)
                state = ttk.Label(stage, text="", style="Value.TLabel")
                state.pack(side="left", padx=8)
                win.bind("<Destroy>", lambda e: e.widget is win and winsound.PlaySound(None, 0))
                win._media["shown"] = "audio-player"
                win.after(100, play)
            else:
                why = ("影片沒辦法在這個程式裡直接播放（Tk 不支援），按下面的按鈕用系統的播放器開啟。" if kind == "video" else
                       "這種格式不能在程式裡直接播放，按下面的按鈕用系統程式開啟。")
                ttk.Label(stage, text=why, style="Value.TLabel", wraplength=int(600 * self.scale), justify="left").pack(anchor="w")
                ttk.Button(stage, text="▶ 用系統播放器開啟" if kind in ("video", "audio") else "用系統程式開啟",
                           style="Primary.TButton", command=lambda: open_path(path, win)).pack(anchor="w", pady=(8, 0))
                win._media["shown"] = "external"
            ttk.Button(bar, text="關閉", style="Ghost.TButton", command=win.destroy).pack(side="right")
            ttk.Button(bar, text="在資料夾中顯示", style="Ghost.TButton", command=lambda: reveal_in_folder(path)).pack(side="right", padx=6)
            ttk.Button(bar, text="用系統程式開啟", style="Ghost.TButton", command=lambda: open_path(path, win)).pack(side="right")
            ttk.Button(bar, text="複製路徑", style="Ghost.TButton",
                       command=lambda: (win.clipboard_clear(), win.clipboard_append(path))).pack(side="left")
            return win

        def _media_show_image(self, stage, path):
            """PNG／GIF 用 Tk 內建顯示；其他格式有 Pillow 才顯示。太大的圖縮小到放得進視窗。回傳顯示方式。"""
            img = None
            try:
                if path.lower().endswith((".png", ".gif", ".ppm", ".pgm")):
                    img = tk.PhotoImage(file=path)
                else:
                    from PIL import Image, ImageTk          # 不是必要套件：沒有就交給系統程式
                    pil = Image.open(path)
                    pil.thumbnail((int(900 * self.scale), int(640 * self.scale)))
                    img = ImageTk.PhotoImage(pil)
            except Exception as exc:
                ttk.Label(stage, text=f"這張圖片不能在程式裡顯示（{type(exc).__name__}），請用系統程式開啟。",
                          style="Value.TLabel").pack(anchor="w")
                return "external"
            max_w, max_h = int(900 * self.scale), int(640 * self.scale)
            factor = max(1, -(-img.width() // max_w), -(-img.height() // max_h))
            if factor > 1 and isinstance(img, tk.PhotoImage):
                img = img.subsample(factor)
            label = tk.Label(stage, image=img, bg=self.theme["surface"], bd=0)
            label.image = img                    # 留住參考，圖才不會被回收
            label.pack()
            return "image"

        # ── v6.19.1：可以指定「工作與成果資料夾」與「模型下載位置」 ──
        def _train_root(self):
            """這次要放工作的資料夾：使用者指定的（要能寫入）→ 否則程式資料夾底下的 訓練/。回傳 (資料夾, 錯誤說明)。"""
            custom = (self.prefs.get("train_dir") or "").strip()
            if not custom:
                return TRAIN_DIR, ""
            err, _free = check_output_dir(custom)
            return (custom, "") if not err else (None, f"指定的工作與成果資料夾不能用：{custom}\n{err}\n\n"
                                                         "（例如外接硬碟沒有接上。）可以在訓練工作室最上面改回預設。")

        def _media_roots(self):
            """作品清單要掃的資料夾：預設的、目前指定的、以前指定過的（換資料夾之後舊作品也找得到）。"""
            return [TRAIN_DIR] + [p for p in [self.prefs.get("train_dir")] + list(self.prefs.get("train_dirs_seen") or []) if p]

        def _hf_env(self):
            hf = (self.prefs.get("hf_home") or "").strip()
            return {"HF_HOME": hf} if hf else {}

        def _studio_folder_bar(self, parent, before=None):
            bar = ttk.Frame(parent, style="Surface.TFrame")
            bar.pack(fill="x", pady=(0, 6), before=before)
            rows = {}
            for key, label, default in (("train_dir", "工作與成果資料夾", TRAIN_DIR), ("hf_home", "模型下載位置", default_hf_home())):
                row = ttk.Frame(bar, style="Surface.TFrame")
                row.pack(fill="x")
                ttk.Label(row, text=label, style="Value.TLabel", width=16).pack(side="left")
                val = ttk.Label(row, text="", style="Muted.TLabel")
                val.pack(side="left", fill="x", expand=True)
                ttk.Button(row, text="用預設", style="Ghost.TButton",
                           command=lambda k=key: self._studio_set_folder(k, "")).pack(side="right")
                ttk.Button(row, text="開啟", style="Ghost.TButton",
                           command=lambda k=key, d=default: (lambda p: os.makedirs(p, exist_ok=True) or open_path(p, self.studio_win))(
                               (self.prefs.get(k) or "").strip() or d)).pack(side="right", padx=4)
                ttk.Button(row, text="變更…", style="Ghost.TButton",
                           command=lambda k=key: self._studio_pick_folder(k)).pack(side="right")
                rows[key] = (val, default)
            self._studio["folder_rows"] = rows
            self._studio_folder_refresh()

        def _studio_folder_refresh(self):
            for key, (val, default) in (self._studio.get("folder_rows") or {}).items():
                if not val.winfo_exists():
                    continue
                custom = (self.prefs.get(key) or "").strip()
                path = custom or default
                try:
                    free = f"，剩 {shutil.disk_usage(path).free / 2 ** 30:.0f} GB" if os.path.isdir(path) else ""
                except OSError:
                    free = ""
                val.configure(text=f"{path}（{'自訂' if custom else '預設'}{free}）")

        def _studio_pick_folder(self, key):
            label = "工作與成果資料夾（訓練與生成的結果都放這裡）" if key == "train_dir" else "模型下載位置（Hugging Face 模型很大，FLUX 約 30 GB）"
            p = filedialog.askdirectory(parent=self.studio_win, title=f"選擇{label}",
                                        initialdir=self.prefs.get(key) or (TRAIN_DIR if key == "train_dir" else default_hf_home()))
            if p:
                self._studio_set_folder(key, os.path.normpath(p))

        def _studio_set_folder(self, key, path):
            """套用新的資料夾（空字串＝改回預設）。會先確認能寫入；模型位置改了要提醒舊的模型要重新下載或搬過去。"""
            if path:
                err, free = check_output_dir(path)
                if err:
                    messagebox.showerror(APP_NAME, err, parent=self.studio_win)
                    return False
                if free is not None and free < (40 if key == "hf_home" else 10):
                    if not messagebox.askyesno(APP_NAME, f"這個位置只剩 {free:.0f} GB，"
                                                         + ("大模型可能放不下（FLUX 約 30 GB）。" if key == "hf_home" else "訓練與生成的結果可能放不下。")
                                                         + "\n\n仍要使用嗎？", parent=self.studio_win):
                        return False
            old = (self.prefs.get(key) or "").strip()
            if os.path.normcase(old) == os.path.normcase(path):
                return True
            self.prefs[key] = path
            if key == "train_dir" and old:          # 記住以前用過的位置：作品清單還是列得出舊作品
                seen = [p for p in self.prefs.get("train_dirs_seen") or [] if os.path.normcase(p) != os.path.normcase(old)]
                self.prefs["train_dirs_seen"] = ([old] + seen)[:10]
            self._mark_dirty()
            self.save_settings(quiet=True)
            self._studio_folder_refresh()
            if key == "train_dir":
                self._studio_log(f"工作與成果資料夾：{path or TRAIN_DIR}（之後的訓練與生成都放這裡；以前的作品照樣列在「成果」）")
                refresh = self._studio.get("media_refresh")
                if refresh:
                    refresh()
            else:
                self._studio_log(f"模型下載位置：{path or default_hf_home()}。之前下載過的模型不在新位置會重新下載；"
                                 f"不想重新下載，可以把舊位置（{old or default_hf_home()}）裡的 hub 資料夾整個搬過去。")
            log_app.info("訓練工作室資料夾：%s → %s", key, path or "（預設）")
            return True

        def open_training_studio(self):
            win = getattr(self, "studio_win", None)
            if win is not None and win.winfo_exists():
                win.deiconify()
                win.lift()
                return
            t = self.theme
            win = self.studio_win = tk.Toplevel(self)
            win.title("訓練工作室")
            win.configure(bg=t["surface"])
            win.geometry(f"{int(980 * self.scale)}x{int(760 * self.scale)}")
            self._train_job = None
            self._studio = {}
            top = ttk.Frame(win, style="Surface.TFrame")
            top.pack(fill="both", expand=True, padx=12, pady=(10, 4))
            nb = ttk.Notebook(top)
            nb.pack(fill="both", expand=True)
            self._studio_folder_bar(top, before=nb)
            for label, build in (("環境", self._studio_env_tab), ("語言模型蒸餾", self._studio_llm_tab),
                                 ("語音", self._studio_tts_tab), ("圖片生成", self._studio_image_tab), ("圖片 LoRA 訓練", self._studio_ilora_tab),
                                 ("影片生成", self._studio_video_tab),
                                 ("影片 LoRA 訓練", self._studio_vlora_tab), ("成果", self._studio_results_tab)):
                frame = ttk.Frame(nb, style="Surface.TFrame")
                nb.add(frame, text=f"  {label}  ")
                scroll = ScrollFrame(self, frame)               # 內容比視窗長時可以捲動（小螢幕）
                scroll.pack(fill="both", expand=True)
                inner = ttk.Frame(scroll.inner, style="Surface.TFrame", padding=10)
                inner.pack(fill="both", expand=True)
                build(inner)
            bottom = ttk.Frame(win, style="Surface.TFrame")
            bottom.pack(fill="x", padx=12, pady=(4, 10))
            row = ttk.Frame(bottom, style="Surface.TFrame")
            row.pack(fill="x")
            self._studio["status"] = ttk.Label(row, text="還沒有在執行的工作。", style="Value.TLabel")
            self._studio["status"].pack(side="left")
            self._studio["stop"] = ttk.Button(row, text="■ 停止", style="Danger.TButton", command=self._studio_stop)
            self._studio["open"] = ttk.Button(row, text="開啟工作資料夾", style="Ghost.TButton",
                                              command=lambda: self._studio.get("job_dir") and open_path(self._studio["job_dir"]))
            self._studio["open"].pack(side="right")
            self._studio["bar"] = ttk.Progressbar(bottom, mode="determinate", maximum=100)
            self._studio["bar"].pack(fill="x", pady=(4, 4))
            logbox = tk.Text(bottom, height=8, wrap="word", relief="flat", highlightthickness=1)
            self._theme_widget(logbox, "text")
            logbox.pack(fill="x")
            logbox.configure(state="disabled")
            self._studio["log"] = logbox
            win.protocol("WM_DELETE_WINDOW", self._studio_close)
            # v6.16.1：訓練工作室視窗也接受拖放（本機檢測時使用者常常拖到這個視窗；拖到欄位上會填入路徑）
            win.after(300, lambda: setattr(self, "_studio_drop_obj", install_file_drop(win, lambda paths, x, y: self.ui_queue.put(
                ("ui", None, "call", lambda: self._on_studio_drop(paths, x, y))))[1]))

        def _on_studio_drop(self, paths, x, y):
            paths = [p for p in paths if p]
            if not paths:
                return
            waiter = getattr(self, "_selfcheck_drop", None)
            if waiter:
                self._selfcheck_drop = None
                waiter(paths)
                return
            try:
                w = self.studio_win.winfo_containing(x, y)
            except (tk.TclError, KeyError):
                w = None
            var_name = str(w.cget("textvariable")) if w is not None and isinstance(w, (ttk.Entry, ttk.Combobox)) else ""
            if var_name:
                w.setvar(var_name, paths[0])
                self._studio_log(f"已填入：{paths[0]}")
            else:
                self._studio_log("把檔案或資料夾拖到欄位上（例如「錄音資料夾」「參考錄音」）就會填入路徑。")

        def _studio_close(self):
            if (self._train_job is not None or self._studio.get("bg")) and not messagebox.askyesno(APP_NAME, "還有工作在執行，關閉視窗會停止它。確定嗎？",
                                                                       parent=self.studio_win):
                return
            self._studio_stop()
            self.studio_win.destroy()

        def _studio_log(self, text):
            box = self._studio.get("log")
            if not box or not box.winfo_exists():
                return
            box.configure(state="normal")
            box.insert("end", text.rstrip() + "\n")
            if int(box.index("end-1c").split(".")[0]) > 2000:
                box.delete("1.0", "500.0")
            box.see("end")
            box.configure(state="disabled")

        def _studio_log_link(self, text, path):
            """紀錄裡加一行可以點的連結：點了用作品檢視打開（以前只是一行路徑文字，捲走就找不到）。"""
            box = self._studio.get("log")
            if not box or not box.winfo_exists():
                return
            tag = f"media{len(box.tag_names())}"
            box.configure(state="normal")
            box.insert("end", text, (tag,))
            box.insert("end", "\n")
            box.tag_configure(tag, foreground=self.theme["accent"], underline=True)
            box.tag_bind(tag, "<Button-1>", lambda _e: self.open_media(path, self.studio_win))
            box.tag_bind(tag, "<Enter>", lambda _e: box.configure(cursor="hand2"))
            box.tag_bind(tag, "<Leave>", lambda _e: box.configure(cursor=""))
            box.see("end")
            box.configure(state="disabled")

        def _studio_new_media(self, path, show=True):
            """生成完成：紀錄加可以點的連結、更新「成果 → 生成的作品」，並用作品檢視打開。"""
            if not path:
                return
            icon = {"video": "🎬", "audio": "🔊", "image": "🖼"}.get(media_kind(path), "📄")
            self._studio_log_link(f"{icon} {os.path.basename(path)}（{media_summary(path)}）— 點這裡打開", path)
            refresh = self._studio.get("media_refresh")
            if refresh:
                refresh()
            if show:
                self.open_media(path, self.studio_win)

        def _studio_status(self, text, pct=None):
            if self._studio.get("status") and self._studio["status"].winfo_exists():
                self._studio["status"].configure(text=text)
                if pct is not None:
                    self._studio["bar"].configure(value=max(0, min(100, pct)))

        # 共用小工具
        def _sfield(self, parent, label, var=None, width=40, values=None, browse=None, hint=""):
            row = ttk.Frame(parent, style="Surface.TFrame")
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=label, style="Value.TLabel", width=14).pack(side="left")
            var = var if var is not None else tk.StringVar()
            w = ttk.Combobox(row, textvariable=var, values=values, width=width) if values is not None else \
                ttk.Entry(row, textvariable=var, width=width)
            w.pack(side="left", fill="x", expand=True)
            if browse:
                ttk.Button(row, text="選擇…", style="Ghost.TButton", command=lambda: browse(var)).pack(side="left", padx=(4, 0))
            if hint:
                ttk.Label(row, text=hint, style="Muted.TLabel").pack(side="left", padx=(6, 0))
            return var

        def _stext(self, parent, label, height=3, initial=""):
            ttk.Label(parent, text=label, style="Value.TLabel").pack(anchor="w", pady=(4, 0))
            box = tk.Text(parent, height=height, wrap="word", relief="flat", highlightthickness=1)
            self._theme_widget(box, "text")
            box.insert("1.0", initial)
            box.pack(fill="x")
            return box

        def _sbuttons(self, parent, items):
            row = ttk.Frame(parent, style="Surface.TFrame")
            row.pack(fill="x", pady=(8, 2))
            for text, cmd, style in items:
                ttk.Button(row, text=text, style=style, command=cmd).pack(side="left", padx=(0, 6))
            return row

        def _pick_dir(self, var):
            p = filedialog.askdirectory(parent=self.studio_win)
            if p:
                var.set(p)

        def _pick_file(self, var, types):
            p = filedialog.askopenfilename(parent=self.studio_win, filetypes=types)
            if p:
                var.set(p)

        def _train_python(self):
            return find_train_python(self.prefs)

        def _studio_gpu_gb(self):
            if not hasattr(self, "_gpu_gb_cache"):
                self._gpu_gb_cache = gpu_total_gb()
            return self._gpu_gb_cache

        def _studio_estimate(self, task_key, config):
            level, text = vram_verdict(task_key, config, self._studio_gpu_gb())
            self._studio_log(("✔ " if level == "ok" else "⚠ ") + text)
            self._studio_status(text[:120])

        # 執行一個訓練腳本
        def _studio_run(self, task_key, config, smoke=False, job_name="", on_result=None, script=None, on_done=None,
                        vram_checked=False):
            if self._train_job is not None:
                messagebox.showinfo(APP_NAME, "已經有工作在執行，請等它結束或先按「停止」。", parent=self.studio_win)
                return
            python = self._train_python()
            if not python:
                messagebox.showerror(APP_NAME, "找不到訓練用的 Python，請到「環境」分頁指定。", parent=self.studio_win)
                return
            if not smoke and not vram_checked:
                level, text = vram_verdict(task_key, config, self._studio_gpu_gb())
                self._studio_log(("✔ " if level == "ok" else "⚠ ") + text)
                if level == "over" and not messagebox.askyesno(APP_NAME, text + "\n\n仍要開始嗎？", parent=self.studio_win,
                                                               icon="warning", default="no"):
                    return
            root, err = self._train_root()
            if err:
                messagebox.showerror(APP_NAME, err, parent=self.studio_win)
                return
            job = new_job_dir(task_key + ("_測試" if smoke else ""), job_name, root=root)
            cfg = dict(config, out_dir=config.get("out_dir") or os.path.join(job, "out"))
            cfg_path = os.path.join(job, "config.json")
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            script_path = write_train_script(script or TRAIN_TASKS[task_key]["script"], job)
            self._studio["job_dir"] = job
            self._studio_log(f"── 開始：{TRAIN_TASKS.get(task_key, {}).get('label', task_key)}"
                             f"{'（快速測試：極小模型、CPU）' if smoke else ''}　資料夾：{job}")
            self._studio_status("準備中…", 0)
            self._studio["stop"].pack(side="right", padx=(0, 6))

            def on_event(kind, data):
                self.ui_queue.put(("ui", None, "call", lambda: self._studio_event(kind, data, on_result, on_done)))
            self._train_job = TrainJob(python, script_path, cfg_path, smoke=smoke, on_event=on_event, extra_env=self._hf_env())
            keep_awake(True)
            threading.Thread(target=self._train_job.run, daemon=True).start()

        def _studio_event(self, kind, data, on_result, on_done=None):
            if kind == "progress":
                step, total = data.get("step"), data.get("total")
                pct = (step / total * 100) if step and total else None
                parts = [data.get("stage", "")]
                if step and total:
                    parts.append(f"{step}/{total}")
                for key, label in (("loss", "損失"), ("eta_min", "約剩"), ("vram", "顯存")):
                    if data.get(key) not in (None, ""):
                        parts.append(f"{label} {data[key]}" + (" 分鐘" if key == "eta_min" else ""))
                self._studio_status("　".join(str(p) for p in parts if p != ""), pct)
                if data.get("msg"):
                    self._studio_log(f"{data.get('stage', '')}：{data['msg']}")
            elif kind in ("log", "raw"):
                self._studio_log(data.get("msg", ""))
            elif kind == "error":
                self._studio_log("✘ " + data.get("error", "") + (f"\n  → {data['hint']}" if data.get("hint") else ""))
            elif kind == "done":
                job, self._train_job = self._train_job, None
                keep_awake(self.busy)
                try:
                    self._studio["stop"].pack_forget()
                except (tk.TclError, KeyError):
                    pass
                if data.get("result"):
                    self._studio_status("完成", 100)
                    self._studio_log("✔ 完成：" + json.dumps(data["result"], ensure_ascii=False)[:600])
                    if on_result:
                        on_result(data["result"], job)
                else:
                    err = data.get("error") or {}
                    self._studio_status("沒有完成：" + str(err.get("error", ""))[:120])
                    if err.get("hint") and not on_done:
                        messagebox.showwarning(APP_NAME, f"{err.get('error', '')}\n\n{err['hint']}", parent=self.studio_win)
                if on_done:
                    on_done(data.get("result"), data.get("error"))

        def _studio_stop(self):
            if self._train_job is not None:
                self._train_job.stop()
                self._studio_log("正在停止…")
            if self._studio.get("bg"):                   # 產生資料、評測：停止送出新的請求（進行中的那幾個會先結束）
                self._studio["cancel"].set()
                self._studio_log("正在停止（等進行中的請求結束）…")

        def _studio_bg_begin(self, label):
            """開始一個在程式裡跑的長工作（老師出題回答、評測）：可以停止，結束時顯示用了多少。"""
            self._studio["cancel"] = threading.Event()
            self._studio["bg"] = label
            self._studio["usage"] = {"prompt": 0, "completion": 0, "cost": 0.0, "calls": 0, "estimated": 0}
            try:
                self._studio["stop"].pack(side="right", padx=(0, 6))
            except (tk.TclError, KeyError):
                pass

        def _studio_bg_end(self):
            self._studio["bg"] = None
            try:
                self._studio["stop"].pack_forget()
            except (tk.TclError, KeyError):
                pass
            text = UsageMeter.summary(self._studio.get("usage"))
            if text:
                self._studio_log("📊 " + text)

        def _studio_cloud(self, task_key, config, data_paths, name):
            dest = filedialog.asksaveasfilename(parent=self.studio_win, title="儲存雲端訓練包", defaultextension=".zip",
                                                initialfile=f"訓練包_{task_key}_{name or time.strftime('%m%d')}.zip",
                                                filetypes=[("zip", "*.zip")])
            if not dest:
                return
            try:
                make_cloud_package(task_key, config, data_paths, dest)
            except (OSError, ValueError) as exc:
                messagebox.showerror(APP_NAME, f"打包失敗：{exc}", parent=self.studio_win)
                return
            self._studio_log(f"已產生雲端訓練包：{dest}\n  到 Google Colab 上傳裡面的「雲端訓練.ipynb」，或在 RunPod 執行 run.sh；"
                             "訓練完把「結果.zip」用「匯入雲端結果」帶回來。")
            open_path(os.path.dirname(dest))

        def _studio_import(self, task_key, on_done):
            src = filedialog.askopenfilename(parent=self.studio_win, title="選擇雲端訓練的結果.zip", filetypes=[("zip", "*.zip")])
            if not src:
                return
            root, err = self._train_root()
            if err:
                messagebox.showerror(APP_NAME, err, parent=self.studio_win)
                return
            job = new_job_dir(task_key + "_雲端", root=root)
            try:
                skipped = []
                n = import_cloud_result(src, os.path.join(job, "out"), skipped=skipped)
            except (OSError, ValueError, zipfile_error()) as exc:
                messagebox.showerror(APP_NAME, f"匯入失敗：{exc}", parent=self.studio_win)
                return
            if skipped:
                self._studio_log(f"⚠ 略過 {len(skipped)} 個 pickle 格式的檔案（載入時可能執行程式碼）：{'、'.join(skipped[:5])}")
            self._studio["job_dir"] = job
            self._studio_log(f"已匯入雲端結果（{n} 個檔案）到 {job}")
            on_done(os.path.join(job, "out"))

        # ── 環境 ──
        def _studio_env_tab(self, f):
            ttk.Label(f, text="訓練用的 Python 環境", style="Section.TLabel").pack(anchor="w")
            ttk.Label(f, text="預設用目前執行本程式的 Python（例如 conda 環境）。訓練需要 PyTorch 等套件，"
                              "這些只裝在這個環境裡，本程式本身仍然不需要任何套件。",
                      style="Muted.TLabel", wraplength=int(900 * self.scale)).pack(anchor="w")
            pyvar = tk.StringVar(value=self._train_python())

            def set_py(*_a):
                self.prefs["train_python"] = pyvar.get().strip()
                self._mark_dirty()
            self._sfield(f, "Python", pyvar, width=70,
                         browse=lambda v: (self._pick_file(v, [("python", "python*.exe python*"), ("全部", "*")]), set_py()))
            pyvar.trace_add("write", set_py)
            out = tk.Text(f, height=12, wrap="word", relief="flat", highlightthickness=1)
            self._theme_widget(out, "text")
            state = {"probe": None, "driver": None}

            def show(text):
                out.configure(state="normal")
                out.delete("1.0", "end")
                out.insert("1.0", text)
                out.configure(state="disabled")

            def check():
                show("檢查中…（第一次載入 PyTorch 可能要一點時間）")

                def work():
                    driver = nvidia_driver_cuda()
                    probe = probe_train_env(pyvar.get().strip() or self._train_python())
                    state.update(probe=probe, driver=driver)
                    self.ui_queue.put(("ui", None, "call", lambda: show(describe_env(probe, driver))))
                threading.Thread(target=work, daemon=True).start()

            def install():
                if not state["probe"] or state["probe"].get("error"):
                    messagebox.showinfo(APP_NAME, "請先按「檢查環境」。", parent=self.studio_win)
                    return
                plan = full_install_plan(state["probe"], state["driver"])
                if not plan:
                    messagebox.showinfo(APP_NAME, "需要的套件都已經安裝好了。", parent=self.studio_win)
                    return
                py = pyvar.get().strip() or self._train_python()
                lines = "\n".join(f"• {w}\n  {os.path.basename(py)} -m pip {' '.join(a)}" for w, a in plan)
                if not messagebox.askyesno(APP_NAME, f"要在這個 Python 環境安裝以下套件嗎？（會下載數 GB，需要幾分鐘到幾十分鐘）\n\n{lines}",
                                           parent=self.studio_win):
                    return
                if self._train_job is not None:
                    return
                self._studio_log("── 安裝套件：" + py)
                self._studio_status("安裝套件中…", 0)

                def on_line(kind, text, pct):
                    self.ui_queue.put(("ui", None, "call", lambda: (self._studio_log(text),
                                                                    pct is not None and self._studio_status(text, pct))))

                def work():
                    execute_install_plan(py, plan, on_line)
                    self.ui_queue.put(("ui", None, "call", lambda: (self._studio_status("安裝結束，重新檢查環境…", 100), check())))
                os.makedirs(TRAIN_DIR, exist_ok=True)
                threading.Thread(target=work, daemon=True).start()

            def smoke_all():
                self._studio_log("── 依序快速測試四個流程（極小模型、CPU）。每個約 1～3 分鐘，會下載幾 MB 的測試模型。")
                tasks = [("llm", self._llm_config(smoke=True)), ("tts", self._tts_smoke_config()),
                         ("video", {"model": "wan-1.3b", "prompt": "測試"}), ("video_lora", self._vlora_smoke_config())]

                def next_one(_res=None, _job=None):
                    if not tasks:
                        self._studio_log("✔ 四個流程的快速測試都完成了")
                        return
                    key, cfg = tasks.pop(0)
                    self.after(200, lambda: self._studio_run(key, cfg, smoke=True, on_result=next_one))
                next_one()

            self._sbuttons(f, [("檢查環境", check, "Primary.TButton"), ("安裝缺少的套件", install, "Ghost.TButton"),
                               ("快速測試全部流程", smoke_all, "Ghost.TButton"),
                               ("這台電腦完整檢測", self.studio_selfcheck, "Ghost.TButton")])
            ttk.Label(f, text="「這台電腦完整檢測」：用顯示卡真的跑一次小模型的訓練、匯入 Ollama、錄 2 秒麥克風、"
                              "請你拖一個檔案到主視窗，最後產生一份報告（約 5～15 分鐘；第一次會下載約 300 MB 的小模型）。",
                      style="Muted.TLabel", wraplength=int(900 * self.scale)).pack(anchor="w")
            out.pack(fill="both", expand=True, pady=(6, 0))
            show("按「檢查環境」查看這個 Python 有沒有 PyTorch、能不能用顯示卡、各功能缺哪些套件。")


        # ── 這台電腦完整檢測（v6.16）：雲端測不到的部分（顯示卡訓練、Ollama、麥克風、拖放）在使用者的電腦上一鍵跑完 ──
        def studio_selfcheck(self):
            if self._train_job is not None or self._studio.get("bg"):
                messagebox.showinfo(APP_NAME, "已經有工作在執行，請等它結束或先按「停止」。", parent=self.studio_win)
                return
            if not messagebox.askyesno(APP_NAME, "要開始這台電腦的完整檢測嗎？\n\n1. 用顯示卡訓練一個 1.35 億參數的小模型（真的走 QLoRA，跟正式訓練同一條路）\n"
                                                 "2. 把它匯入 Ollama 並問一句話，檢查完刪掉這個測試模型\n3. 影片 LoRA 與語音訓練各用顯示卡跑一次快速測試\n"
                                                 "4. 錄 2 秒麥克風\n5. 請你在 30 秒內拖一個檔案到主視窗\n\n約 5～15 分鐘；第一次會下載約 300 MB。",
                                       parent=self.studio_win):
                return
            report = [f"AI 協作 {APP_VERSION} 本機檢測　{time.strftime('%Y-%m-%d %H:%M')}"]
            probe = probe_train_env(self._train_python())
            pk = probe.get("packages") or {}
            report.append("  套件：" + "、".join(f"{m} {pk.get(m) or '沒有'}" for m in
                                                ("torch", "transformers", "peft", "bitsandbytes", "diffusers", "f5_tts")))
            stale = outdated_modules(probe)
            if stale:
                report.append("  ⚠ 版本太舊：" + "、".join(f"{m} {h}（需要 {n} 以上）" for m, (h, n) in stale.items())
                              + "，請先按「安裝缺少的套件」")
            self._selfcheck_report = report

            def add(ok, name, msg=""):
                line = f"{'✔' if ok else ('—' if ok is None else '✘')} {name}" + (f"：{msg}" if msg else "")
                report.append(line)
                self._studio_log(line)

            def finish():
                path = os.path.join(TRAIN_DIR, f"本機檢測結果_{time.strftime('%Y%m%d_%H%M%S')}.txt")
                os.makedirs(TRAIN_DIR, exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write("\n".join(report) + "\n")
                text = "\n".join(report)
                try:
                    self.clipboard_clear()
                    self.clipboard_append(text)
                except tk.TclError:
                    pass
                self._studio_log(f"── 檢測完成，報告存在 {path}（已複製到剪貼簿，可以直接貼給 Claude）")
                messagebox.showinfo(APP_NAME, text[:1800] + "\n\n（報告已複製到剪貼簿）", parent=self.studio_win)

            steps = []

            def run_next(*_a):
                if steps:
                    self.after(300, steps.pop(0))
                else:
                    finish()

            # 1. 顯示卡上真的跑 QLoRA（小模型）＋合併
            state = {}

            def gpu_llm():
                probe_gb = self._studio_gpu_gb()
                add(bool(probe_gb), "顯示卡", f"{probe_gb:.1f} GB" if probe_gb else "沒有偵測到 NVIDIA 顯示卡（後面的訓練會用 CPU）")
                data = self._llm_config(smoke=True)["data_path"]
                cfg = {"base_model": "HuggingFaceTB/SmolLM2-135M-Instruct", "data_path": data, "epochs": 2, "max_len": 128,
                       "grad_accum": 1, "batch_size": 2, "lr": 5e-4, "lora_r": 8, "merge": True, "qlora": True}

                where = "顯示卡、4-bit QLoRA、合併" if probe_gb else "CPU（沒有顯示卡）、LoRA、合併"

                def done(res, err):
                    if res:
                        state["merged"] = res.get("merged")
                        add(True, f"語言模型訓練（{where}）", f"{res.get('steps')} 步、損失 {res.get('train_loss')}、{res.get('minutes')} 分鐘")
                    else:
                        add(False, f"語言模型訓練（{where}）", (err or {}).get("error", "沒有結果")[:300])
                    run_next()
                self._studio_run("llm", cfg, job_name="本機檢測", on_done=done)

            def ollama_step():
                merged = state.get("merged")
                if not merged:
                    add(None, "匯入 Ollama", "略過（上一步沒有產生模型）")
                    return run_next()
                if not find_ollama():
                    add(False, "匯入 Ollama", "找不到 Ollama（ollama.exe），請先安裝並開啟 Ollama")
                    return run_next()
                self._studio_status("匯入 Ollama 測試模型中…")

                def work():
                    ok, msg = ollama_import(merged, "ai-collab-selftest", python=self._train_python())
                    answer = ""
                    if ok:
                        try:
                            ep = {"url": "http://localhost:11434/v1", "model": "ai-collab-selftest", "key": ""}
                            r = _stream_chat_raw(ep, [{"role": "user", "content": "hi"}], threading.Event(),
                                                 options={"auto_retry": 0})
                            answer = "回答了一句話" if r.get("status") == "done" else f"沒有回答：{r.get('error') or r.get('status')}"
                        except Exception as exc:              # 只是檢測，失敗就照實記下
                            answer = f"沒有回答：{exc}"
                        try:                                  # 刪掉檢測用的模型（是這一步自己建立的）
                            subprocess.run([find_ollama(), "rm", "ai-collab-selftest"], capture_output=True, timeout=60,
                                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                        except (OSError, subprocess.SubprocessError):
                            pass

                    def done():
                        add(ok and answer == "回答了一句話", "匯入 Ollama 並回答", msg if not ok else answer)
                        run_next()
                    self.ui_queue.put(("ui", None, "call", done))
                threading.Thread(target=work, daemon=True).start()

            def gpu_smoke(task, cfg, label):
                def step():
                    def done(res, err):
                        add(bool(res), label if self._studio_gpu_gb() else label.replace("顯示卡", "CPU "),
                            "完成" if res else (err or {}).get("error", "沒有結果")[:300])
                        run_next()
                    self._studio_run(task, dict(cfg, smoke_gpu=True), smoke=True, on_done=done)
                return step

            def mic():
                rec = AudioRecorder()
                if not rec.backend:
                    add(False, "麥克風", "找不到錄音程式")
                    return run_next()
                devices = AudioRecorder.input_devices()
                if devices is not None:
                    report.append(f"  錄音裝置：{'、'.join(devices) if devices else '沒有'}")
                path = os.path.join(TRAIN_DIR, "_檢測錄音.wav")
                try:
                    rec.start(path)
                except (RuntimeError, OSError) as exc:
                    add(False, "麥克風", str(exc)[:200])
                    return run_next()
                self._studio_status("🎤 錄音 2 秒，請說句話…")

                def stop():
                    try:
                        out = rec.stop()
                        size = os.path.getsize(out) if out else 0
                        add(size > 1000, "麥克風", (f"錄到 {size:,} 位元組（{getattr(rec, 'format', '')}）") if size else "沒有錄到聲音")
                    except (RuntimeError, OSError) as exc:
                        add(False, "麥克風", str(exc)[:200])
                    run_next()
                self.after(2200, stop)

            def drag():
                self._studio_status("請在 30 秒內，從檔案總管把任何一個檔案拖到這個視窗或主視窗")
                self._studio_log("👉 請在 30 秒內，從檔案總管把任何一個檔案拖到這個視窗或主視窗（任何位置都可以）")
                done = {"v": False}

                def got(paths):
                    done["v"] = True
                    add(True, "從檔案總管拖放", f"收到 {len(paths)} 個：{os.path.basename(paths[0])}")
                    run_next()
                self._selfcheck_drop = got

                def timeout():
                    if not done["v"]:
                        self._selfcheck_drop = None
                        add(None if getattr(self, "_file_drop", None) else False, "從檔案總管拖放",
                            "30 秒內沒有收到（可能是沒有拖，或拖放沒有接上：" + getattr(self, "file_drop_status", "?") + "）")
                        run_next()
                self.after(30000, timeout)

            steps += [gpu_llm, ollama_step,
                      gpu_smoke("video_lora", self._vlora_smoke_config(), "影片 LoRA 訓練（顯示卡快速測試）"),
                      gpu_smoke("tts", self._tts_smoke_config(), "語音訓練（顯示卡快速測試）"),
                      gpu_smoke("image", {"model": "sdxl-turbo", "prompt": "test", "count": 1}, "圖片生成（顯示卡快速測試）"),
                      gpu_smoke("image_lora", dict(self._vlora_smoke_config(), base="sd15"), "圖片 LoRA 訓練（顯示卡快速測試）"),
                      mic, drag]
            self._studio_log("── 開始這台電腦的完整檢測")
            run_next()

        # ── 語言模型蒸餾 ──
        def _studio_llm_tab(self, f):
            labels = [self._label(s) for s in self.services]
            v = self._studio_llm = {}
            ttk.Label(f, text="1. 用老師模型產生訓練資料", style="Section.TLabel").pack(anchor="w")
            hub = self._service(self.prefs.get("hub_id")) or (self.services[0] if self.services else None)
            v["teacher"] = self._sfield(f, "老師模型", tk.StringVar(value=self._label(hub) if hub else ""), values=labels,
                                        hint="大模型當老師（例如 nemotron-ultra）")
            v["topic"] = self._sfield(f, "主題", hint="例如：台灣勞基法問答、Python 除錯、客服回覆")
            v["count"] = self._sfield(f, "題數", tk.StringVar(value="300"), width=8, hint="建議 300～2000；會花老師模型的額度")
            v["seeds"] = self._stext(f, "自己的問題（選填，一行一題；會優先使用，不夠再請老師出題）", height=3)
            v["system"] = self._stext(f, "系統提示詞（老師回答與學生學習時都會用）", height=2, initial=DISTILL_SYSTEM)
            self._sbuttons(f, [("產生訓練資料", self._llm_generate, "Primary.TButton"),
                               ("使用現有的資料檔…", self._llm_pick_data, "Ghost.TButton"),
                               ("檢查資料", lambda: v.get("data") and open_path(v["data"]), "Ghost.TButton")])
            v["data_label"] = ttk.Label(f, text="還沒有訓練資料。", style="Muted.TLabel")
            v["data_label"].pack(anchor="w")
            ttk.Label(f, text="2. 訓練學生模型", style="Section.TLabel").pack(anchor="w", pady=(8, 0))
            v["base"] = self._sfield(f, "底模（學生）", tk.StringVar(value=LLM_BASE_MODELS[0][0]),
                                     values=[m for m, _ in LLM_BASE_MODELS], hint="1.5B 最穩；7B 建議雲端")
            row = ttk.Frame(f, style="Surface.TFrame")
            row.pack(fill="x")
            for key, label, default in (("epochs", "訓練輪數", "2"), ("max_len", "最長長度", "1024"), ("lora_r", "LoRA r", "16"),
                                        ("lr", "學習率", "2e-4")):
                ttk.Label(row, text=label, style="Value.TLabel").pack(side="left", padx=(0, 4))
                v[key] = tk.StringVar(value=default)
                ttk.Entry(row, textvariable=v[key], width=8).pack(side="left", padx=(0, 12))
            v["name"] = self._sfield(f, "模型名稱", tk.StringVar(value="my-distilled"), hint="匯入 Ollama 用的名稱（英數字）")
            self._sbuttons(f, [("在這台電腦訓練", lambda: self._llm_train(False), "Primary.TButton"),
                               ("預估顯存", lambda: self._studio_estimate("llm", self._llm_config()), "Ghost.TButton"),
                               ("快速測試", lambda: self._llm_train(True), "Ghost.TButton"),
                               ("產生雲端訓練包", self._llm_cloud, "Ghost.TButton"),
                               ("匯入雲端結果…", lambda: self._studio_import("llm", self._llm_after_train_dir), "Ghost.TButton")])
            ttk.Label(f, text="3. 使用與評測", style="Section.TLabel").pack(anchor="w", pady=(8, 0))
            self._sbuttons(f, [("匯入 Ollama 並加入 AI 團隊", self._llm_to_ollama, "Ghost.TButton"),
                               ("評測：學生 vs 老師", self._llm_evaluate, "Ghost.TButton")])

        def _llm_pick_data(self):
            p = filedialog.askopenfilename(parent=self.studio_win, filetypes=[("JSONL", "*.jsonl"), ("全部", "*")])
            if p:
                self._studio_llm["data"] = p
                self._studio_llm["data_label"].configure(text=f"訓練資料：{p}（{len(read_jsonl(p))} 筆）")

        def _studio_chat_fn(self, label):
            sv = next((s for s in self.services if self._label(s) == label), None)
            if not sv:
                raise ValueError("請先選擇老師模型")
            ep, err = self._resolve(sv)
            if err:
                raise ValueError(err)
            lock = threading.Lock()

            def chat(messages):
                cancel = self._studio.setdefault("cancel", threading.Event())     # 每次都讀最新的，「停止」才傳得到
                if cancel.is_set():
                    raise RuntimeError("已停止")
                r = stream_chat(ep, messages, cancel, options={"auto_retry": 2, "filter_think": True})
                usage = r.get("usage") if isinstance(r.get("usage"), dict) else None
                p = int((usage or {}).get("prompt_tokens") or 0) or estimate_tokens(_messages_text(messages))
                c = int((usage or {}).get("completion_tokens") or 0) or estimate_tokens(r.get("text", ""))
                pin, pout = USAGE.price_for(ep.get("model"))
                with lock:
                    u = self._studio.setdefault("usage", {"prompt": 0, "completion": 0, "cost": 0.0, "calls": 0, "estimated": 0})
                    u["prompt"] += p
                    u["completion"] += c
                    u["cost"] += (p * pin + c * pout) / 1_000_000
                    u["calls"] += 1
                    u["estimated"] += 0 if usage else 1
                if r.get("status") != "done":
                    raise RuntimeError(r.get("error") or r.get("label") or r.get("status"))
                return r.get("text", "")
            return chat

        def _llm_generate(self):
            v = self._studio_llm
            topic = v["topic"].get().strip()
            seeds = [q.strip() for q in v["seeds"].get("1.0", "end").splitlines() if q.strip()]
            try:
                count = max(5, min(20000, int(v["count"].get())))
                chat = self._studio_chat_fn(v["teacher"].get())
            except ValueError as exc:
                messagebox.showerror(APP_NAME, str(exc), parent=self.studio_win)
                return
            if not topic and not seeds:
                messagebox.showinfo(APP_NAME, "請填主題，或貼上自己的問題。", parent=self.studio_win)
                return
            system = v["system"].get("1.0", "end").strip()
            if self._studio.get("bg") or self._train_job is not None:
                messagebox.showinfo(APP_NAME, "已經有工作在執行，請等它結束或先按「停止」。", parent=self.studio_win)
                return
            job = new_job_dir("llm資料", topic or "自訂", root=self._train_root()[0] or TRAIN_DIR)
            self._studio["job_dir"] = job
            self._studio_bg_begin("產生訓練資料")
            cancel = self._studio["cancel"]
            self._studio_log(f"── 產生訓練資料：主題「{topic}」，目標 {count} 題（老師：{v['teacher'].get()}）")

            def prog(stage):
                return lambda a, b: self.ui_queue.put(("ui", None, "call", lambda: self._studio_status(f"{stage} {a}/{b}", a / max(b, 1) * 100)))

            def work():
                try:
                    qs = seeds[:count]
                    if len(qs) < count:
                        qs += generate_questions(chat, topic or "使用者提供的問題", count - len(qs), existing=qs, cancel=cancel,
                                                 on_progress=prog("出題"))
                    st = build_distill_dataset(chat, qs, os.path.join(job, "訓練資料.jsonl"), system=system, cancel=cancel,
                                               on_progress=prog("老師回答"))
                    err = None
                except Exception as exc:              # 網路、額度等問題：告訴使用者
                    st, err = None, str(exc)

                def done():
                    self._studio_bg_end()
                    if err:
                        self._studio_log("✘ " + err)
                        return
                    if cancel.is_set():
                        self._studio_log(f"已停止：保留已完成的 {st['train'] + st['eval']} 筆")
                    v["data"] = os.path.join(job, "訓練資料.jsonl")
                    v["eval"] = st["eval_path"]
                    v["data_label"].configure(text=f"訓練資料：{st['train']} 筆、評測保留 {st['eval']} 筆、剔除 {len(st['rejected'])} 筆　{v['data']}")
                    self._studio_status("訓練資料完成", 100)
                    for q, why in st["rejected"][:10]:
                        self._studio_log(f"  剔除：{q[:40]}（{why}）")
                self.ui_queue.put(("ui", None, "call", done))
            threading.Thread(target=work, daemon=True).start()

        def _llm_config(self, smoke=False):
            v = getattr(self, "_studio_llm", {})
            data = v.get("data") or ""
            if smoke and not data:
                data = os.path.join(TRAIN_DIR, "_測試資料.jsonl")
                os.makedirs(TRAIN_DIR, exist_ok=True)
                with open(data, "w", encoding="utf-8") as f:
                    for i in range(12):
                        f.write(json.dumps({"messages": [{"role": "user", "content": f"1+{i}=?"},
                                                         {"role": "assistant", "content": f"答案是 {1 + i}。"}]}, ensure_ascii=False) + "\n")

            def num(key, default, cast):
                try:
                    return cast(v[key].get())
                except (KeyError, ValueError, tk.TclError):
                    return default
            return {"base_model": v["base"].get().strip() if v.get("base") else LLM_BASE_MODELS[0][0], "data_path": data,
                    "epochs": num("epochs", 2, float), "max_len": num("max_len", 1024, int), "lora_r": num("lora_r", 16, int),
                    "lr": num("lr", 2e-4, float), "merge": True, "qlora": True}

        def _llm_train(self, smoke):
            cfg = self._llm_config(smoke)
            if not cfg["data_path"]:
                messagebox.showinfo(APP_NAME, "請先產生或選擇訓練資料。", parent=self.studio_win)
                return
            self._studio_run("llm", cfg, smoke=smoke, job_name=self._studio_llm["name"].get(),
                             on_result=lambda res, job: self._llm_after_train_dir(os.path.dirname(res.get("merged") or res.get("adapter", ""))))

        def _llm_cloud(self):
            cfg = self._llm_config()
            if not cfg["data_path"]:
                messagebox.showinfo(APP_NAME, "請先產生或選擇訓練資料。", parent=self.studio_win)
                return
            self._studio_cloud("llm", cfg, {"data_path": cfg["data_path"]}, self._studio_llm["name"].get())

        def _llm_after_train_dir(self, out_dir):
            merged = os.path.join(out_dir, "merged")
            self._studio_llm["merged"] = merged if os.path.isdir(merged) else ""
            if self._studio_llm["merged"]:
                self._studio_log(f"完整模型：{merged}。可以按「匯入 Ollama 並加入 AI 團隊」。")

        def _llm_to_ollama(self):
            v = self._studio_llm
            merged = v.get("merged") or ""
            if not merged:
                p = filedialog.askdirectory(parent=self.studio_win, title="選擇合併後的模型資料夾（merged）")
                if not p:
                    return
                merged = v["merged"] = p
            name = ollama_model_name(v["name"].get())
            system = v["system"].get("1.0", "end").strip()
            self._studio_log(f"── 匯入 Ollama：{name}（量化成 q4_K_M，需要幾分鐘）")
            self._studio_status("匯入 Ollama 中…", 0)

            def work():
                ok, msg = ollama_import(merged, name, system, python=self._train_python())

                def done():
                    self._studio_log(("✔ " if ok else "✘ ") + msg)
                    self._studio_status(msg[:120], 100 if ok else 0)
                    if not ok:
                        return
                    register_artifact("llm", name, merged, ollama=name)
                    if any(s.get("model") == name and "11434" in s.get("url", "") for s in self.services):
                        return
                    sv = normalize_service({"name": name, "role": DEFAULT_ROLE, "url": "http://localhost:11434/v1",
                                            "model": name, "credential_env": NO_KEY})
                    sv["credential"] = NO_KEY
                    self.services.append(sv)
                    self._after_services_changed()
                    self.save_settings(quiet=True)
                    self._studio_log(f"已把「{name}」加入 AI 團隊（本機 Ollama）。")
                self.ui_queue.put(("ui", None, "call", done))
            threading.Thread(target=work, daemon=True).start()

        def _llm_evaluate(self):
            v = self._studio_llm
            eval_path = v.get("eval") or ""
            if not eval_path or not os.path.isfile(eval_path):
                p = filedialog.askopenfilename(parent=self.studio_win, title="選擇評測資料（評測.jsonl）",
                                               filetypes=[("JSONL", "*.jsonl")])
                if not p:
                    return
                eval_path = v["eval"] = p
            name = ollama_model_name(v["name"].get())
            student_sv = next((s for s in self.services if s.get("model") == name and "11434" in s.get("url", "")), None)
            if not student_sv:
                messagebox.showinfo(APP_NAME, f"AI 團隊裡沒有「{name}」，請先匯入 Ollama。", parent=self.studio_win)
                return
            try:
                judge = self._studio_chat_fn(v["teacher"].get())
                student = self._studio_chat_fn(self._label(student_sv))
            except ValueError as exc:
                messagebox.showerror(APP_NAME, str(exc), parent=self.studio_win)
                return
            rows = read_jsonl(eval_path, limit=50)
            if self._studio.get("bg") or self._train_job is not None:
                messagebox.showinfo(APP_NAME, "已經有工作在執行，請等它結束或先按「停止」。", parent=self.studio_win)
                return
            self._studio_log(f"── 評測 {len(rows)} 題：學生「{name}」回答，老師評分")
            self._studio_bg_begin("評測")
            cancel = self._studio["cancel"]

            def work():
                res = evaluate_student(student, judge, rows, cancel=cancel, on_progress=lambda a, b: self.ui_queue.put(
                    ("ui", None, "call", lambda: self._studio_status(f"評測 {a}/{b}", a / max(b, 1) * 100))))
                path = os.path.join(os.path.dirname(eval_path), f"評測結果_{name}.json")
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(res, f, ensure_ascii=False, indent=2)

                def done():
                    self._studio_bg_end()
                    low = sorted([x for x in res["items"] if x["score"] is not None], key=lambda x: x["score"])[:3]
                    self._studio_log(f"✔ 學生平均 {res['avg']}／10（10＝跟老師一樣好）。詳細結果：{path}")
                    for x in low:
                        self._studio_log(f"  最低分 {x['score']}：{x['question'][:40]}（{x['reason']}）")
                    self._studio_status(f"評測完成：平均 {res['avg']}／10", 100)
                    register_artifact("llm", name, v.get("merged", ""), ollama=name, eval_avg=res["avg"])
                self.ui_queue.put(("ui", None, "call", done))
            threading.Thread(target=work, daemon=True).start()

        # ── 語音 ──
        def _studio_tts_tab(self, f):
            v = self._studio_tts = {}
            v["consent"] = tk.BooleanVar(value=False)
            ttk.Checkbutton(f, text="我確認：參考錄音或訓練用的聲音是我本人，或已經取得聲音主人的同意（不能用來冒充他人）",
                            variable=v["consent"]).pack(anchor="w")
            ttk.Label(f, text="語音生成（F5-TTS：中文、英文；用一段 3～15 秒的參考錄音模仿聲音）", style="Section.TLabel").pack(anchor="w", pady=(8, 0))
            v["ref"] = self._sfield(f, "參考錄音", browse=lambda var: self._pick_file(var, [("音檔", "*.wav *.mp3 *.flac *.ogg *.m4a")]))
            rec_row = ttk.Frame(f, style="Surface.TFrame")
            rec_row.pack(fill="x")
            v["rec_btn"] = ttk.Button(rec_row, text="🎤 錄一段參考錄音", style="Ghost.TButton", command=self._tts_record)
            v["rec_btn"].pack(side="left", padx=(110, 0))
            v["ref_text"] = self._sfield(f, "參考逐字稿", hint="參考錄音說了什麼（一字不差，品質最好）")
            v["text"] = self._stext(f, "要念的文字", height=3)
            voices = ["F5-TTS 預訓練（不用訓練）"] + [f"{x['name']}｜{x['path']}" for x in load_registry() if x.get("kind") == "voice"]
            v["voice"] = self._sfield(f, "聲音模型", tk.StringVar(value=voices[0]), values=voices)
            v["speed"] = self._sfield(f, "語速", tk.StringVar(value="1.0"), width=6)
            self._sbuttons(f, [("生成語音", lambda: self._tts_generate(False), "Primary.TButton"),
                               ("快速測試", lambda: self._tts_generate(True), "Ghost.TButton")])
            ttk.Label(f, text="聲音訓練（用多段錄音微調，效果比只用一段參考錄音更像；建議 10 分鐘以上、每段 3～15 秒）",
                      style="Section.TLabel").pack(anchor="w", pady=(10, 0))
            v["data"] = self._sfield(f, "錄音資料夾", browse=self._pick_dir, hint="每段錄音旁邊放同名 .txt 逐字稿")
            row = ttk.Frame(f, style="Surface.TFrame")
            row.pack(fill="x")
            for key, label, default in (("steps", "訓練步數", "2000"), ("lr", "學習率", "1e-5")):
                ttk.Label(row, text=label, style="Value.TLabel").pack(side="left", padx=(0, 4))
                v[key] = tk.StringVar(value=default)
                ttk.Entry(row, textvariable=v[key], width=8).pack(side="left", padx=(0, 12))
            v["name"] = self._sfield(f, "聲音名稱", tk.StringVar(value="我的聲音"))
            self._sbuttons(f, [("在這台電腦訓練", lambda: self._tts_train(False), "Primary.TButton"),
                               ("產生雲端訓練包", self._tts_cloud, "Ghost.TButton"),
                               ("匯入雲端結果…", lambda: self._studio_import("tts", self._tts_register_dir), "Ghost.TButton")])

        def _tts_record(self):
            v = self._studio_tts
            rec = getattr(self, "_tts_recorder", None)
            if rec is None:
                rec = AudioRecorder()
                if not rec.backend:
                    messagebox.showinfo(APP_NAME, "找不到錄音程式（Windows 內建可以錄）。", parent=self.studio_win)
                    return
                path = os.path.join(TRAIN_DIR, "參考錄音", f"參考_{time.strftime('%Y%m%d_%H%M%S')}.wav")
                try:
                    rec.start(path)
                except (RuntimeError, OSError) as exc:
                    messagebox.showerror(APP_NAME, str(exc), parent=self.studio_win)
                    return
                self._tts_recorder = rec
                v["rec_btn"].configure(text="■ 停止錄音")
                return
            self._tts_recorder = None
            v["rec_btn"].configure(text="🎤 錄一段參考錄音")
            path = rec.stop()
            if path:
                v["ref"].set(path)
                self._studio_log(f"已錄好參考錄音：{path}（請在「參考逐字稿」填入你說的內容）")

        def _tts_need_consent(self):
            if not self._studio_tts["consent"].get():
                messagebox.showinfo(APP_NAME, "請先勾選上方的確認：聲音是你本人，或已經取得聲音主人的同意。", parent=self.studio_win)
                return False
            return True

        def _tts_smoke_config(self):
            import wave, struct
            folder = os.path.join(TRAIN_DIR, "_測試錄音")
            os.makedirs(folder, exist_ok=True)
            for i, text in enumerate(("你好，今天天氣很好。", "這是測試錄音。")):
                p = os.path.join(folder, f"c{i}.wav")
                if not os.path.isfile(p):
                    with wave.open(p, "wb") as w:
                        w.setnchannels(1)
                        w.setsampwidth(2)
                        w.setframerate(24000)
                        w.writeframes(b"".join(struct.pack("<h", int(6000 * math.sin(2 * math.pi * (200 + 40 * i) * n / 24000)))
                                               for n in range(24000 * 2)))
                    with open(os.path.join(folder, f"c{i}.txt"), "w", encoding="utf-8") as f:
                        f.write(text)
            return {"mode": "finetune", "consent": True, "data_dir": folder}

        def _tts_generate(self, smoke):
            v = self._studio_tts
            if smoke:
                cfg = self._tts_smoke_config()
                self._studio_run("tts", cfg, smoke=True)
                return
            if not self._tts_need_consent():
                return
            ref, text = v["ref"].get().strip(), v["text"].get("1.0", "end").strip()
            if not ref or not os.path.isfile(ref) or not text:
                messagebox.showinfo(APP_NAME, "請選擇參考錄音，並填入要念的文字。", parent=self.studio_win)
                return
            voice = v["voice"].get()
            model_path = voice.split("｜", 1)[1] if "｜" in voice else ""
            try:
                speed = float(v["speed"].get())
            except ValueError:
                speed = 1.0
            cfg = {"mode": "generate", "consent": True, "ref_audio": ref, "ref_text": v["ref_text"].get().strip(),
                   "gen_text": text, "model_path": model_path, "speed": speed}
            self._studio_run("tts", cfg, job_name="生成", on_result=lambda res, job: self._studio_new_media(res.get("audio", "")))

        def _tts_train_config(self):
            v = self._studio_tts
            try:
                steps, lr = int(v["steps"].get()), float(v["lr"].get())
            except ValueError:
                steps, lr = 2000, 1e-5
            return {"mode": "finetune", "consent": True, "data_dir": v["data"].get().strip(), "steps": steps, "lr": lr}

        def _tts_train(self, smoke):
            if not self._tts_need_consent():
                return
            cfg = self._tts_train_config()
            if not cfg["data_dir"] or not os.path.isdir(cfg["data_dir"]):
                messagebox.showinfo(APP_NAME, "請選擇錄音資料夾。", parent=self.studio_win)
                return
            self._studio_run("tts", cfg, smoke=smoke, job_name=self._studio_tts["name"].get(),
                             on_result=lambda res, job: self._tts_register_dir(os.path.dirname(res.get("model", ""))))

        def _tts_cloud(self):
            if not self._tts_need_consent():
                return
            cfg = self._tts_train_config()
            if not cfg["data_dir"]:
                messagebox.showinfo(APP_NAME, "請選擇錄音資料夾。", parent=self.studio_win)
                return
            self._studio_cloud("tts", cfg, {"data_dir": cfg["data_dir"]}, self._studio_tts["name"].get())

        def _tts_register_dir(self, out_dir):
            path = os.path.join(out_dir, "model.safetensors")
            if not os.path.isfile(path):
                self._studio_log(f"✘ {out_dir} 裡沒有 model.safetensors")
                return
            name = self._studio_tts["name"].get().strip() or "我的聲音"
            register_artifact("voice", name, path)
            self._studio_log(f"✔ 已加入聲音模型「{name}」，在上方「聲音模型」選它就能用。")

        # ── 影片生成 ──
        # ── 圖片生成（v6.19.0）──
        IMAGE_MEMORY = (("auto", "自動（建議）"), ("normal", "一般（最快，需要大顯存）"), ("lowest", "極省（逐層卸載，很慢但放得下）"))

        def _studio_image_tab(self, f):
            v = self._studio_image = {}
            ttk.Label(f, text="文字轉圖片（本機開源模型，用你的顯示卡；第一次使用會下載模型，數 GB～30 GB）",
                      style="Section.TLabel").pack(anchor="w")
            v["model"] = self._sfield(f, "模型", tk.StringVar(value=IMAGE_MODELS[0][0]), values=[m for m, _d, _l in IMAGE_MODELS])
            for m, desc, lic in IMAGE_MODELS:
                ttk.Label(f, text=f"　{m}：{desc}（{lic}）", style="Muted.TLabel").pack(anchor="w")
            ttk.Label(f, text="　需要同意授權的模型：先到 Hugging Face 網站登入並按同意，再設定環境變數 HF_TOKEN（存取權杖）。",
                      style="Muted.TLabel").pack(anchor="w")
            v["prompt"] = self._stext(f, "圖片描述（英文描述通常效果較好；FLUX 與 SD 3.5 看得懂較長的句子）", height=3)
            v["neg"] = self._sfield(f, "不要出現", tk.StringVar(value="blurry, low quality, watermark, deformed"),
                                    hint="FLUX 與引導強度 ≤ 1 時不使用")
            row = ttk.Frame(f, style="Surface.TFrame")
            row.pack(fill="x", pady=(4, 0))
            w, h, steps, guide = IMAGE_DEFAULTS[IMAGE_MODELS[0][0]]
            for key, label, default in (("width", "寬", str(w)), ("height", "高", str(h)), ("steps", "步數", str(steps)),
                                        ("guidance", "引導強度", str(guide)), ("seed", "種子", "42"), ("count", "張數", "1")):
                ttk.Label(row, text=label, style="Value.TLabel").pack(side="left", padx=(0, 4))
                v[key] = tk.StringVar(value=default)
                ttk.Entry(row, textvariable=v[key], width=6).pack(side="left", padx=(0, 10))
            ttk.Button(row, text="🎲", width=3, style="Ghost.TButton",
                       command=lambda: v["seed"].set(str(random.randint(0, 2 ** 31 - 1)))).pack(side="left")

            def model_changed(*_a):                 # 換模型就換成它的建議尺寸、步數與引導強度
                d = IMAGE_DEFAULTS.get(v["model"].get())
                if d:
                    for key, val in zip(("width", "height", "steps", "guidance"), d):
                        v[key].set(str(val))
            v["model"].trace_add("write", model_changed)
            labels = [lab for _k, lab in self.IMAGE_MEMORY]
            v["memory"] = self._sfield(f, "記憶體模式", tk.StringVar(value=labels[0]), values=labels, width=30)
            lrow = ttk.Frame(f, style="Surface.TFrame")          # v6.20.0：下拉清單＝自己訓練的圖片 LoRA，也可以選檔案
            lrow.pack(fill="x", pady=2)
            ttk.Label(lrow, text="LoRA（選用）", style="Value.TLabel", width=14).pack(side="left")
            v["lora"] = tk.StringVar()
            v["lora_combo"] = ttk.Combobox(lrow, textvariable=v["lora"], width=40)
            v["lora_combo"].pack(side="left", fill="x", expand=True)
            ttk.Button(lrow, text="選擇…", style="Ghost.TButton",
                       command=lambda: self._pick_file(v["lora"], [("LoRA", "*.safetensors")])).pack(side="left", padx=(4, 0))
            ttk.Button(lrow, text="清空", style="Ghost.TButton", command=lambda: v["lora"].set("")).pack(side="left", padx=(4, 0))
            ttk.Label(lrow, text="清單裡是你訓練的圖片 LoRA", style="Muted.TLabel").pack(side="left", padx=(6, 0))
            self._image_lora_choices()
            v["lora_note"] = ttk.Label(f, text="", style="Muted.TLabel", wraplength=int(880 * self.scale), justify="left")
            v["lora_note"].pack(anchor="w")

            def lora_changed(*_a):                  # 選了 LoRA 或換模型：馬上顯示相不相容
                p = v["lora"].get().strip()
                if not p:
                    v["lora_note"].configure(text="", foreground=self.theme["muted"])
                    return
                if not os.path.exists(p):
                    v["lora_note"].configure(text="⚠ 找不到這個檔案", foreground=self.theme["danger"])
                    return
                ok, why = lora_compat(v["model"].get(), p)
                v["lora_note"].configure(text=("✔ " if ok else "✘ " if ok is False else "⚠ ") + why,
                                         foreground=self.theme["danger"] if ok is False else self.theme["muted"])
            v["lora"].trace_add("write", lora_changed)
            v["model"].trace_add("write", lora_changed)
            v["lora_scale"] = self._sfield(f, "LoRA 強度", tk.StringVar(value="1.0"), width=6)
            self._sbuttons(f, [("生成圖片", lambda: self._image_generate(False), "Primary.TButton"),
                               ("預估顯存", lambda: self._studio_estimate("image", self._image_config()), "Ghost.TButton"),
                               ("快速測試", lambda: self._image_generate(True), "Ghost.TButton"),
                               ("產生雲端生成包", self._image_cloud, "Ghost.TButton"),
                               ("匯入雲端結果…", lambda: self._studio_import("image", self._studio_imported_media), "Ghost.TButton")])

        def _image_config(self):
            v = self._studio_image

            def num(key, cast, default):
                try:
                    return cast(v[key].get())
                except ValueError:
                    return default
            model = v["model"].get()
            w, h, steps, guide = IMAGE_DEFAULTS.get(model, (1024, 1024, 30, 5.0))
            memory = next((k for k, lab in self.IMAGE_MEMORY if lab == v["memory"].get()), "auto")
            return {"model": model, "prompt": v["prompt"].get("1.0", "end").strip(), "negative_prompt": v["neg"].get().strip(),
                    "width": num("width", int, w), "height": num("height", int, h), "steps": num("steps", int, steps),
                    "guidance": num("guidance", float, guide), "seed": num("seed", int, 42),
                    "count": max(1, min(8, num("count", int, 1))), "memory": memory,
                    "lora_path": v["lora"].get().strip(), "lora_scale": num("lora_scale", float, 1.0)}

        def _image_generate(self, smoke):
            cfg = self._image_config()
            if smoke:
                cfg.update(prompt=cfg["prompt"] or "test", lora_path="", count=2)
            elif not cfg["prompt"]:
                messagebox.showinfo(APP_NAME, "請填圖片描述。", parent=self.studio_win)
                return
            if cfg["model"] not in IMAGE_DEFAULTS:
                messagebox.showinfo(APP_NAME, "請從清單選一個模型。", parent=self.studio_win)
                return
            if cfg["lora_path"] and not os.path.exists(cfg["lora_path"]):
                messagebox.showinfo(APP_NAME, f"找不到 LoRA 檔案：{cfg['lora_path']}", parent=self.studio_win)
                return
            if cfg["lora_path"]:                    # v6.19.2：開始前先確認 LoRA 跟模型相容（不用等下載完才失敗）
                ok, why = lora_compat(cfg["model"], cfg["lora_path"])
                if ok is False:
                    messagebox.showerror(APP_NAME, why + "\n\n要不用 LoRA 生成，請把「LoRA」欄位清空。", parent=self.studio_win)
                    self._studio_log("✘ " + why)
                    return
                self._studio_log(("✔ " if ok else "⚠ ") + why)

            checked = False
            gpu = self._studio_gpu_gb()
            if not smoke and gpu and cfg["memory"] != "auto":       # v6.19.2：選了「一般」卻放不下，但「自動」放得下 → 直接問要不要換
                level, text = vram_verdict("image", cfg, gpu)
                auto_level, auto_text = vram_verdict("image", dict(cfg, memory="auto"), gpu)
                if level == "over" and auto_level != "over":
                    ans = messagebox.askyesnocancel(APP_NAME, text + f"\n\n改用「自動」記憶體模式的話：{auto_text}\n\n"
                                                                     "是：改用「自動」再開始\n否：照目前的設定開始\n取消：先不要開始",
                                                    parent=self.studio_win)
                    if ans is None:
                        return
                    if ans:
                        cfg["memory"] = "auto"
                        self._studio_image["memory"].set(self.IMAGE_MEMORY[0][1])
                        self._studio_log("記憶體模式已改成「自動」。")
                    checked = True

            def on_result(res, _job):
                images = res.get("images") or ([res["image"]] if res.get("image") else [])
                for i, p in enumerate(images):
                    self._studio_new_media(p, show=(i == 0 and not smoke))
                if len(images) > 1 and not smoke:
                    self._studio_log(f"共 {len(images)} 張；其他張在「成果 → 生成的作品」，或點上面的連結。")
            self._studio_run("image", cfg, smoke=smoke, job_name="圖片", on_result=on_result, vram_checked=checked)

        def _studio_imported_media(self, out_dir):
            """雲端生成的結果匯入後：每個作品加連結、更新作品清單，並打開第一個。"""
            found = [m["path"] for m in list_generated_media(self._media_roots()) if os.path.realpath(m["path"]).startswith(os.path.realpath(out_dir))]
            if not found:
                self._studio_log("結果檔裡沒有找到圖片、影片或語音。")
                return
            for i, p in enumerate(sorted(found)):
                self._studio_new_media(p, show=(i == 0))

        def _image_cloud(self):
            cfg = self._image_config()
            if not cfg["prompt"]:
                messagebox.showinfo(APP_NAME, "請填圖片描述。", parent=self.studio_win)
                return
            data = {"lora_path": cfg["lora_path"]} if cfg["lora_path"] else {}
            self._studio_cloud("image", cfg, data, "圖片")

        # ── 圖片 LoRA 訓練（v6.20.0）──
        def _studio_ilora_tab(self, f):
            v = self._studio_ilora = {}
            ttk.Label(f, text="用自己的圖片訓練圖片模型的 LoRA（學一個人物、角色、物品或畫風），訓練完到「圖片生成」套用",
                      style="Section.TLabel").pack(anchor="w")
            ttk.Label(f, text="資料：一個資料夾放 10～30 張圖片（png、jpg、webp）。可以在每張旁邊放同名的 .txt 寫描述"
                              "（例如「a woman in a red dress, smiling」）；沒有描述的圖片只用觸發詞。圖片會從中間裁成正方形。"
                              "學人物時，角度、表情、背景越多樣越好。",
                      style="Muted.TLabel", wraplength=int(900 * self.scale), justify="left").pack(anchor="w")
            v["base"] = self._sfield(f, "底模", tk.StringVar(value=IMAGE_LORA_BASES[0][0]), values=[b for b, *_r in IMAGE_LORA_BASES])
            for b, desc, _res, _st in IMAGE_LORA_BASES:
                ttk.Label(f, text=f"　{b}：{desc}", style="Muted.TLabel").pack(anchor="w")
            v["data"] = self._sfield(f, "圖片資料夾", browse=self._pick_dir)
            v["data_note"] = ttk.Label(f, text="", style="Muted.TLabel")
            v["data_note"].pack(anchor="w")
            v["trigger"] = self._sfield(f, "觸發詞", tk.StringVar(value="zhstyle"),
                                        hint="生成時寫進描述就會套用；用一個不常見的字（例如 zhgirl）")
            row = ttk.Frame(f, style="Surface.TFrame")
            row.pack(fill="x", pady=(4, 0))
            res, steps = IMAGE_LORA_BASES[0][2], IMAGE_LORA_BASES[0][3]
            for key, label, default in (("resolution", "解析度", str(res)), ("steps", "步數", str(steps)), ("lr", "學習率", "1e-4"),
                                        ("rank", "LoRA r", "16")):
                ttk.Label(row, text=label, style="Value.TLabel").pack(side="left", padx=(0, 4))
                v[key] = tk.StringVar(value=default)
                ttk.Entry(row, textvariable=v[key], width=7).pack(side="left", padx=(0, 10))
            v["flip"] = tk.BooleanVar(value=True)
            ttk.Checkbutton(row, text="左右翻轉（資料加倍；圖裡有文字或不對稱的特徵時取消）", variable=v["flip"]).pack(side="left")
            v["preview"] = self._sfield(f, "預覽描述", tk.StringVar(value=""), hint="空白＝用第一張圖的描述")
            v["name"] = self._sfield(f, "LoRA 名稱", tk.StringVar(value="我的圖片風格"))

            def base_changed(*_a):
                b = next((x for x in IMAGE_LORA_BASES if x[0] == v["base"].get()), None)
                if b:
                    v["resolution"].set(str(b[2]))
                    v["steps"].set(str(b[3]))
            v["base"].trace_add("write", base_changed)

            def data_changed(*_a):
                d = v["data"].get().strip()
                if not d or not os.path.isdir(d):
                    v["data_note"].configure(text="")
                    return
                try:
                    names = os.listdir(d)
                except OSError:
                    names = []
                imgs = [n for n in names if os.path.splitext(n)[1].lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp")]
                caps = sum(1 for n in imgs if os.path.isfile(os.path.join(d, os.path.splitext(n)[0] + ".txt")))
                tip = "（建議至少 10 張）" if len(imgs) < 10 else ""
                v["data_note"].configure(text=f"　找到 {len(imgs)} 張圖片，其中 {caps} 張有描述{tip}")
            v["data"].trace_add("write", data_changed)
            self._sbuttons(f, [("在這台電腦訓練", lambda: self._ilora_train(False), "Primary.TButton"),
                               ("預估顯存", lambda: self._studio_estimate("image_lora", self._ilora_config()), "Ghost.TButton"),
                               ("快速測試", lambda: self._ilora_train(True), "Ghost.TButton"),
                               ("產生雲端訓練包", self._ilora_cloud, "Ghost.TButton"),
                               ("匯入雲端結果…", lambda: self._studio_import("image_lora", self._ilora_register_dir), "Ghost.TButton")])

        def _ilora_config(self):
            v = self._studio_ilora

            def num(key, cast, default):
                try:
                    return cast(v[key].get())
                except ValueError:
                    return default
            base = v["base"].get()
            b = next((x for x in IMAGE_LORA_BASES if x[0] == base), IMAGE_LORA_BASES[0])
            return {"base": base, "data_dir": v["data"].get().strip(), "trigger": v["trigger"].get().strip(),
                    "resolution": num("resolution", int, b[2]), "steps": num("steps", int, b[3]), "lr": num("lr", float, 1e-4),
                    "lora_r": num("rank", int, 16), "flip": bool(v["flip"].get()), "preview_prompt": v["preview"].get().strip()}

        def _ilora_train(self, smoke):
            if smoke:
                cfg = dict(self._vlora_smoke_config(), base="sd15")       # 同一份 16×16 測試圖
            else:
                cfg = self._ilora_config()
                if cfg["base"] not in {b for b, *_r in IMAGE_LORA_BASES}:
                    messagebox.showinfo(APP_NAME, "請從清單選一個底模。", parent=self.studio_win)
                    return
                if not cfg["data_dir"] or not os.path.isdir(cfg["data_dir"]):
                    messagebox.showinfo(APP_NAME, "請選擇圖片資料夾。", parent=self.studio_win)
                    return
                if not cfg["trigger"]:
                    if not messagebox.askyesno(APP_NAME, "沒有設定觸發詞：這樣生成時沒辦法用一個字叫出這個 LoRA，"
                                                         "而且沒有描述的圖片會被略過。\n\n仍要開始嗎？", parent=self.studio_win):
                        return

            def on_result(res, _job):
                if res.get("preview"):
                    self._studio_new_media(res["preview"], show=not smoke)
                if not smoke:
                    self._ilora_register_dir(os.path.dirname(res.get("lora", "")))
            self._studio_run("image_lora", cfg, smoke=smoke, job_name=self._studio_ilora["name"].get(), on_result=on_result)

        def _ilora_cloud(self):
            cfg = self._ilora_config()
            if not cfg["data_dir"]:
                messagebox.showinfo(APP_NAME, "請選擇圖片資料夾。", parent=self.studio_win)
                return
            self._studio_cloud("image_lora", cfg, {"data_dir": cfg["data_dir"]}, self._studio_ilora["name"].get())

        def _ilora_register_dir(self, out_dir):
            """把訓練好的圖片 LoRA 加進清單，並且在「圖片生成」直接選好它（底模也換成一樣的）。"""
            path = os.path.join(out_dir, "lora")
            if not os.path.isfile(os.path.join(path, "pytorch_lora_weights.safetensors")):
                self._studio_log(f"✘ {out_dir} 裡沒有 lora/pytorch_lora_weights.safetensors")
                return
            info = {}
            try:
                with open(os.path.join(path, "模型資訊.json"), encoding="utf-8") as f:
                    info = json.load(f)
            except (OSError, ValueError):
                pass
            arch = info.get("arch") or lora_arch(path)
            name = self._studio_ilora["name"].get().strip() or "我的圖片風格"
            trigger = info.get("trigger") or self._studio_ilora["trigger"].get().strip()
            register_artifact("image_lora", name, path, trigger=trigger, arch=arch, base=info.get("base", ""))
            self._image_use_lora(path, arch, trigger)
            self._studio_log(f"✔ 已加入圖片 LoRA「{name}」。「圖片生成」分頁已經選好它"
                             + (f"；描述裡寫「{trigger}」就會套用" if trigger else "") + "。")

        def _image_use_lora(self, path, arch="", trigger=""):
            """在「圖片生成」選好這個 LoRA；底模不同就換成對應的模型。"""
            v = getattr(self, "_studio_image", None)
            if not v:
                return
            self._image_lora_choices()
            v["lora"].set(path)
            want = {"sdxl": "sdxl", "sd15": "sd15"}.get(arch)
            if want and v["model"].get() not in {m for m, s in IMAGE_MODEL_ARCH.items() if arch in s}:
                v["model"].set(want)
            if trigger:
                box = v["prompt"]
                text = box.get("1.0", "end").strip()
                if trigger not in text:
                    box.delete("1.0", "end")
                    box.insert("1.0", (trigger + ", " + text).strip(", "))

        def _image_lora_choices(self):
            """「圖片生成」的 LoRA 下拉清單：自己訓練的圖片 LoRA。"""
            combo = (getattr(self, "_studio_image", None) or {}).get("lora_combo")
            if combo is not None and combo.winfo_exists():
                combo.configure(values=[x["path"] for x in reversed(load_registry()) if x.get("kind") == "image_lora"])

        def _studio_video_tab(self, f):
            v = self._studio_video = {}
            ttk.Label(f, text="文字轉影片（本機開源模型；第一次使用會下載模型，數 GB）", style="Section.TLabel").pack(anchor="w")
            v["model"] = self._sfield(f, "模型", tk.StringVar(value=VIDEO_MODELS[0][0]), values=[m for m, _ in VIDEO_MODELS])
            for m, desc in VIDEO_MODELS:
                ttk.Label(f, text=f"　{m}：{desc}", style="Muted.TLabel").pack(anchor="w")
            v["prompt"] = self._stext(f, "影片描述（英文描述通常效果較好）", height=3)
            v["neg"] = self._sfield(f, "不要出現", tk.StringVar(value="blurry, low quality, distorted"))
            row = ttk.Frame(f, style="Surface.TFrame")
            row.pack(fill="x", pady=(4, 0))
            for key, label, default in (("width", "寬", "480"), ("height", "高", "272"), ("frames", "格數", "33"),
                                        ("steps", "步數", "30"), ("guidance", "引導強度", "5.0"), ("seed", "種子", "42")):
                ttk.Label(row, text=label, style="Value.TLabel").pack(side="left", padx=(0, 4))
                v[key] = tk.StringVar(value=default)
                ttk.Entry(row, textvariable=v[key], width=6).pack(side="left", padx=(0, 10))
            loras = ["（不使用）"] + [f"{x['name']}｜{x['path']}" for x in load_registry() if x.get("kind") == "video_lora"]
            v["lora"] = self._sfield(f, "LoRA", tk.StringVar(value=loras[0]), values=loras, hint="影片 LoRA 訓練的成果")
            v["lora_scale"] = self._sfield(f, "LoRA 強度", tk.StringVar(value="1.0"), width=6)
            self._sbuttons(f, [("生成影片", lambda: self._video_generate(False), "Primary.TButton"),
                               ("預估顯存", lambda: self._studio_estimate("video", self._video_config()), "Ghost.TButton"),
                               ("快速測試", lambda: self._video_generate(True), "Ghost.TButton"),
                               ("產生雲端生成包", self._video_cloud, "Ghost.TButton"),
                               ("匯入雲端結果…", lambda: self._studio_import("video", self._studio_imported_media), "Ghost.TButton")])

        def _video_config(self):
            v = self._studio_video

            def num(key, cast, default):
                try:
                    return cast(v[key].get())
                except ValueError:
                    return default
            lora = v["lora"].get()
            return {"model": v["model"].get(), "prompt": v["prompt"].get("1.0", "end").strip(), "negative_prompt": v["neg"].get(),
                    "width": num("width", int, 480), "height": num("height", int, 272), "num_frames": num("frames", int, 33),
                    "steps": num("steps", int, 30), "guidance": num("guidance", float, 5.0), "seed": num("seed", int, 42),
                    "lora_path": lora.split("｜", 1)[1] if "｜" in lora else "", "lora_scale": num("lora_scale", float, 1.0)}

        def _video_generate(self, smoke):
            cfg = self._video_config()
            if not cfg["prompt"] and not smoke:
                messagebox.showinfo(APP_NAME, "請填影片描述。", parent=self.studio_win)
                return
            cfg["prompt"] = cfg["prompt"] or "test"
            if smoke:
                cfg["lora_path"] = ""
            self._studio_run("video", cfg, smoke=smoke, job_name="影片", on_result=lambda res, job: self._studio_new_media(
                res.get("video", ""), show=not smoke))

        def _video_cloud(self):
            cfg = self._video_config()
            data = {"lora_path": cfg["lora_path"]} if cfg["lora_path"] else {}
            self._studio_cloud("video", cfg, data, "影片")

        # ── 影片 LoRA 訓練 ──
        def _studio_vlora_tab(self, f):
            v = self._studio_vlora = {}
            ttk.Label(f, text="訓練影片模型的 LoRA（Wan2.1 1.3B；學一種風格、角色或動作）", style="Section.TLabel").pack(anchor="w")
            ttk.Label(f, text="資料：一個資料夾，放 10～50 段短影片（或圖片），每個檔案旁邊放同名的 .txt 描述內容。"
                              "8 GB 顯示卡：解析度 416×240、17 格、1000 步約數小時；記憶體不夠時請改用雲端 GPU。",
                      style="Muted.TLabel", wraplength=int(900 * self.scale)).pack(anchor="w")
            v["data"] = self._sfield(f, "資料夾", browse=self._pick_dir)
            v["trigger"] = self._sfield(f, "觸發詞", tk.StringVar(value="zhstyle"), hint="生成時寫進描述就會套用這個風格")
            row = ttk.Frame(f, style="Surface.TFrame")
            row.pack(fill="x", pady=(4, 0))
            for key, label, default in (("width", "寬", "416"), ("height", "高", "240"), ("frames", "格數", "17"),
                                        ("steps", "步數", "1000"), ("lr", "學習率", "1e-4"), ("rank", "LoRA r", "32")):
                ttk.Label(row, text=label, style="Value.TLabel").pack(side="left", padx=(0, 4))
                v[key] = tk.StringVar(value=default)
                ttk.Entry(row, textvariable=v[key], width=7).pack(side="left", padx=(0, 10))
            v["name"] = self._sfield(f, "LoRA 名稱", tk.StringVar(value="我的風格"))
            self._sbuttons(f, [("在這台電腦訓練", lambda: self._vlora_train(False), "Primary.TButton"),
                               ("預估顯存", lambda: self._studio_estimate("video_lora", self._vlora_config()), "Ghost.TButton"),
                               ("快速測試", lambda: self._vlora_train(True), "Ghost.TButton"),
                               ("產生雲端訓練包（建議）", self._vlora_cloud, "Ghost.TButton"),
                               ("匯入雲端結果…", lambda: self._studio_import("video_lora", self._vlora_register_dir), "Ghost.TButton")])

        def _vlora_config(self):
            v = self._studio_vlora

            def num(key, cast, default):
                try:
                    return cast(v[key].get())
                except ValueError:
                    return default
            return {"data_dir": v["data"].get().strip(), "trigger": v["trigger"].get().strip(), "width": num("width", int, 416),
                    "height": num("height", int, 240), "num_frames": num("frames", int, 17), "steps": num("steps", int, 1000),
                    "lr": num("lr", float, 1e-4), "lora_r": num("rank", int, 32)}

        def _vlora_smoke_config(self):
            import zlib, struct
            folder = os.path.join(TRAIN_DIR, "_測試影片資料")
            os.makedirs(folder, exist_ok=True)
            p = os.path.join(folder, "a.png")
            if not os.path.isfile(p):                  # 用標準函式庫寫一張 16×16 的 PNG
                rows = b"".join(b"\x00" + b"".join(bytes([(x * 16) % 256, (y * 16) % 256, 128]) for x in range(16)) for y in range(16))

                def chunk(tag, data):
                    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
                with open(p, "wb") as f:
                    f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 16, 16, 8, 2, 0, 0, 0))
                            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))
                with open(os.path.join(folder, "a.txt"), "w", encoding="utf-8") as f:
                    f.write("測試圖片")
            return {"data_dir": folder, "trigger": "test"}

        def _vlora_train(self, smoke):
            cfg = self._vlora_smoke_config() if smoke else self._vlora_config()
            if not smoke and (not cfg["data_dir"] or not os.path.isdir(cfg["data_dir"])):
                messagebox.showinfo(APP_NAME, "請選擇資料夾。", parent=self.studio_win)
                return
            self._studio_run("video_lora", cfg, smoke=smoke, job_name=self._studio_vlora["name"].get(),
                             on_result=lambda res, job: None if smoke else self._vlora_register_dir(os.path.dirname(res.get("lora", ""))))

        def _vlora_cloud(self):
            cfg = self._vlora_config()
            if not cfg["data_dir"]:
                messagebox.showinfo(APP_NAME, "請選擇資料夾。", parent=self.studio_win)
                return
            self._studio_cloud("video_lora", cfg, {"data_dir": cfg["data_dir"]}, self._studio_vlora["name"].get())

        # ── 成果 ──
        def _studio_media_list(self, f):
            """成果分頁上半部：生成的影片、語音、圖片（雙擊打開）。"""
            ttk.Label(f, text="生成的作品（影片、語音、圖片）", style="Section.TLabel").pack(anchor="w")
            ttk.Label(f, text="雙擊打開。檔案放在「工作與成果資料夾」（最上面可以變更）各工作的 out/ 底下。",
                      style="Muted.TLabel").pack(anchor="w")
            tree = ttk.Treeview(f, columns=("kind", "name", "time", "info"), show="headings", height=7)
            for col, label, w in (("kind", "種類", 70), ("name", "檔名", 250), ("time", "時間", 130), ("info", "長度／大小", 300)):
                tree.heading(col, text=label)
                tree.column(col, width=int(w * self.scale), anchor="w")
            tree.pack(fill="both", expand=True, pady=(6, 0))
            paths = {}

            def refresh():
                if not tree.winfo_exists():
                    return
                tree.delete(*tree.get_children())
                paths.clear()
                for i, m in enumerate(list_generated_media(self._media_roots())):
                    iid = str(i)
                    paths[iid] = m["path"]
                    tree.insert("", "end", iid=iid, values=(MEDIA_LABELS.get(m["kind"], m["kind"]) + ("（測試）" if m["smoke"] else ""),
                                                            m["name"], time.strftime("%Y-%m-%d %H:%M", time.localtime(m["mtime"])),
                                                            media_summary(m["path"])))
                if not paths:
                    tree.insert("", "end", iid="none", values=("", "還沒有生成任何作品", "", ""))
            self._studio["media_refresh"] = refresh
            self._studio["media_tree"] = tree

            def chosen():
                sel = tree.selection()
                if not sel or sel[0] not in paths:
                    messagebox.showinfo(APP_NAME, "請先在清單裡選一個作品。", parent=self.studio_win)
                    return None
                return paths[sel[0]]
            tree.bind("<Double-1>", lambda _e: (lambda p: p and self.open_media(p, self.studio_win))(
                paths.get(tree.focus())))
            row = ttk.Frame(f, style="Surface.TFrame")
            row.pack(fill="x", pady=(4, 0))
            ttk.Button(row, text="打開", style="Primary.TButton",
                       command=lambda: (lambda p: p and self.open_media(p, self.studio_win))(chosen())).pack(side="left")
            ttk.Button(row, text="用系統程式開啟", style="Ghost.TButton",
                       command=lambda: (lambda p: p and open_path(p, self.studio_win))(chosen())).pack(side="left", padx=6)
            ttk.Button(row, text="在資料夾中顯示", style="Ghost.TButton",
                       command=lambda: (lambda p: p and reveal_in_folder(p))(chosen())).pack(side="left")
            ttk.Button(row, text="重新整理", style="Ghost.TButton", command=refresh).pack(side="right")
            refresh()

        def _studio_results_tab(self, f):
            self._studio_media_list(f)
            ttk.Label(f, text="做出來的模型（訓練好的語言模型、聲音、影片 LoRA）", style="Section.TLabel").pack(anchor="w", pady=(14, 0))
            ttk.Label(f, text="「從清單移除」只是不再列出，檔案不會被刪除。", style="Muted.TLabel").pack(anchor="w")
            tree = ttk.Treeview(f, columns=("kind", "name", "created", "info"), show="headings", height=12)
            for col, label, w in (("kind", "種類", 90), ("name", "名稱", 160), ("created", "建立時間", 130), ("info", "位置／評分", 460)):
                tree.heading(col, text=label)
                tree.column(col, width=int(w * self.scale), anchor="w")
            tree.pack(fill="both", expand=True, pady=(6, 0))
            self._studio_results = tree
            labels = {"llm": "語言模型", "voice": "聲音", "video_lora": "影片 LoRA", "image_lora": "圖片 LoRA"}

            def refresh():
                tree.delete(*tree.get_children())
                for i, x in enumerate(reversed(load_registry())):
                    info = (f"Ollama：{x.get('ollama')}" if x.get("ollama") else "") + \
                           (f"　評測 {x['eval_avg']}／10" if x.get("eval_avg") is not None else "")
                    tree.insert("", "end", iid=str(i), values=(labels.get(x["kind"], x["kind"]), x["name"], x.get("created", ""),
                                                               (info + "　" if info else "") + x["path"]), tags=(x["kind"], x["path"]))

            def selected():
                sel = tree.selection()
                if not sel:
                    messagebox.showinfo(APP_NAME, "請先在清單裡選一個。", parent=self.studio_win)
                    return None
                kind, path = tree.item(sel[0], "tags")[:2]
                return kind, path

            def open_dir():
                s = selected()
                if s:
                    p = s[1]
                    open_path(p if os.path.isdir(p) else os.path.dirname(p))

            def use():
                s = selected()
                if not s:
                    return
                kind, path = s
                item = next((x for x in load_registry() if x["kind"] == kind and x["path"] == path), {})
                if kind == "voice" and hasattr(self, "_studio_tts"):
                    self._studio_tts["voice"].set(f"{item.get('name')}｜{path}")
                    self._studio_log(f"語音分頁的「聲音模型」已改成：{item.get('name')}")
                elif kind == "image_lora" and hasattr(self, "_studio_image"):
                    self._image_use_lora(path, item.get("arch", ""), item.get("trigger", ""))
                    self._studio_log(f"圖片生成的 LoRA 已改成：{item.get('name')}"
                                     + (f"；描述裡寫「{item['trigger']}」就會套用" if item.get("trigger") else ""))
                elif kind == "video_lora" and hasattr(self, "_studio_video"):
                    self._studio_video["lora"].set(f"{item.get('name')}｜{path}")
                    if item.get("trigger"):
                        self._studio_log(f"影片生成的 LoRA 已改成：{item.get('name')}；描述裡寫「{item['trigger']}」就會套用")
                elif kind == "llm":
                    self._studio_log(f"「{item.get('ollama') or item.get('name')}」已經在 AI 團隊（本機 Ollama），"
                                     "在拓樸圖或右上角選它就能用。")

            def remove():
                s = selected()
                if s and messagebox.askyesno(APP_NAME, "從清單移除這一項嗎？（檔案不會被刪除）", parent=self.studio_win):
                    unregister_artifact(*s)
                    refresh()
            self._sbuttons(f, [("重新整理", refresh, "Ghost.TButton"), ("開啟資料夾", open_dir, "Ghost.TButton"),
                               ("用這個", use, "Primary.TButton"), ("從清單移除", remove, "Ghost.TButton")])
            refresh()

        def _vlora_register_dir(self, out_dir):
            path = os.path.join(out_dir, "lora")
            if not os.path.isdir(path):
                self._studio_log(f"✘ {out_dir} 裡沒有 lora 資料夾")
                return
            name = self._studio_vlora["name"].get().strip() or "我的風格"
            register_artifact("video_lora", name, path, trigger=self._studio_vlora["trigger"].get().strip())
            self._studio_log(f"✔ 已加入影片 LoRA「{name}」，到「影片生成」分頁的 LoRA 選它；描述裡寫觸發詞就會套用。")

        # ───────────── v6.13：從 GitHub 自動更新、當機紀錄 ─────────────
        def _report_previous_crash(self):
            crashes = previous_crash_logs(current=_CRASH_FILE[1])
            if not crashes:
                return
            path, text = crashes[0]
            for p, _t in crashes:                      # 只提醒一次：改名成「已回報」
                try:
                    os.replace(p, os.path.join(os.path.dirname(p), "已回報" + os.path.basename(p)))
                except OSError:
                    pass
            reported = os.path.join(os.path.dirname(path), "已回報" + os.path.basename(path))
            first = next((l for l in text.splitlines() if "Fatal" in l or "fatal" in l or "exception" in l.lower()), "")
            messagebox.showwarning(APP_NAME, "上次程式不正常結束（當掉）了，詳細紀錄在：\n"
                                             f"{reported}\n\n{first[:200]}\n\n"
                                             "把這個檔案的內容貼給 Claude 就能找出原因。")

        def _auto_update_check(self):
            if FROZEN or not self.prefs.get("auto_update", True):
                return
            last = float(self.prefs.get("last_update_check") or 0)
            if time.time() - last < 6 * 3600:
                return
            self.check_github_update(quiet=True)

        def check_github_update(self, quiet=False, status_label=None):
            """quiet：自動檢查時，沒有新版或檢查失敗都不跳視窗（只寫日誌）。"""
            if FROZEN:
                if not quiet:
                    messagebox.showinfo(APP_NAME, "打包版（.exe）不能直接替換程式碼：請用新版 AI協作.py 重新執行「打包成exe.bat」。")
                return
            if getattr(self, "_update_checking", False):
                return
            self._update_checking = True
            repo = self.prefs.get("update_repo") or UPDATE_REPO_DEFAULT
            clone = self.prefs.get("update_clone") or None
            token = None
            for name in ("GITHUB_TOKEN", "GH_TOKEN"):
                token = lookup_env(name).get("value")
                if token:
                    break
            show = (lambda text, color="muted": status_label.configure(text=text, foreground=self.theme[color])) \
                if status_label is not None else (lambda text, color="muted": self.status_label.configure(text=text))
            if not quiet:
                show("正在檢查 GitHub 上的新版…")

            def work():
                try:
                    info, err = check_github_update(repo, clone, token), None
                except Exception as exc:                # 網路、git、驗證失敗：都只是「這次沒更新」
                    info, err = None, str(exc)
                self.ui_queue.put(("ui", None, "call", lambda: done(info, err)))

            def done(info, err):
                self._update_checking = False
                self.prefs["last_update_check"] = time.time()
                self._mark_dirty()
                if err:
                    log_app.warning("檢查更新失敗：%s", err)
                    if not quiet:
                        show(f"沒有更新：{err}", "danger")
                    return
                if not info:
                    if not quiet:
                        show(f"已經是最新版（{APP_VERSION}）。", "success")
                    return
                self._offer_update(info, show)

            threading.Thread(target=work, daemon=True).start()

        def _offer_update(self, info, show):
            if self.busy:                               # 執行中不打斷：結束後再問
                self.after(30000, lambda: self._offer_update(info, show))
                return
            if not messagebox.askyesno(APP_NAME, f"GitHub 上有新版 {info['version']}（目前 {APP_VERSION}）。\n"
                                                 f"來源：{info['source']}\nSHA-256 相符：{info['sha'][:16]}…\n\n"
                                                 "要現在更新並重新啟動嗎？目前的程式會先備份，設定與對話都不會動。"):
                show(f"有新版 {info['version']}，可以到「設定 → 更新與打包」更新。")
                return
            try:
                version, backup = apply_update(info["text"], expected_sha256=info["sha"])
            except (ValueError, SyntaxError, OSError) as exc:
                messagebox.showerror(APP_NAME, f"沒有更新：{exc}")
                return
            log_app.info("已更新到 %s（%s），舊版備份在 %s", version, info["source"], backup)
            if self.dirty:
                self.save_settings(quiet=True)
            try:
                restart_program()
            except OSError as exc:
                messagebox.showinfo(APP_NAME, f"已更新到 {version}，但沒辦法自動重新啟動（{exc}）。請關閉程式再重新開啟。")
                return
            self.dirty = False
            self._on_close()

        # ───────────── v6.12：拖放檔案 ─────────────
        def _install_file_drop(self):
            # 拖放的通知在 Windows 視窗訊息處理程序裡收到，那裡不能呼叫 Tk：只放進佇列，由事件迴圈取出再處理
            how, obj = install_file_drop(self, lambda paths, x, y: self.ui_queue.put(
                ("ui", None, "call", lambda: self._on_files_dropped(paths, x, y))))
            self._file_drop = obj                      # 留著參照（Windows 的視窗程序被回收會讓程式當掉）
            self.file_drop_status = how
            log_app.info("拖放：%s", how)

        def _is_inside(self, widget, container):
            while widget is not None:
                if widget is container:
                    return True
                widget = getattr(widget, "master", None)
            return False

        def _on_files_dropped(self, paths, x, y):
            paths = [p for p in paths if p]
            if not paths:
                return
            waiter = getattr(self, "_selfcheck_drop", None)
            if waiter:                                    # 本機檢測正在等你拖檔案
                self._selfcheck_drop = None
                waiter(paths)
                return
            try:
                w = self.winfo_containing(x, y)
            except (tk.TclError, KeyError):
                w = None
            in_ws = (self.conv.get("type") == "agent" and getattr(self, "ws_tab_frame", None) is not None
                     and self._is_inside(w, self.ws_tab_frame))
            if in_ws:
                target = ""
                if w is self.file_tree:
                    node = self.file_tree.identify_row(y - self.file_tree.winfo_rooty())
                    if node.startswith("d:"):
                        target = node[2:]
                    elif node.startswith("f:") and "/" in node[2:]:
                        target = node[2:].rsplit("/", 1)[0]
                self.drop_into_workspace(paths, target)
                return
            files = [p for p in paths if os.path.isfile(p)]
            folders = [p for p in paths if os.path.isdir(p)]
            if files:
                self.add_attachments(files)
                self.status_label.configure(text=f"已附加 {len(files)} 個檔案。要放進工作資料夾，請拖到右側「工作區」。")
            if folders:
                ws = self._ws_root()
                inside = [f for f in folders if ws and _inside(os.path.realpath(f), os.path.realpath(ws))]
                for f in inside:
                    self.mention_file(os.path.relpath(f, ws).replace("\\", "/"))
                if len(inside) < len(folders):
                    messagebox.showinfo(APP_NAME, "資料夾不能當附件。要讓 Agent 使用，請把資料夾拖到右側「工作區」"
                                                  "（會複製進工作資料夾），或用「換資料夾」直接改用那個資料夾。")

        def add_files_to_workspace(self):
            if not self._ws_root():
                messagebox.showinfo(APP_NAME, "請先選擇工作資料夾。")
                return
            paths = filedialog.askopenfilenames(title="選擇要複製到工作資料夾的檔案")
            if paths:
                self.drop_into_workspace(list(paths), "")

        def drop_into_workspace(self, paths, target_rel=""):
            ws = self._ws_root()
            if not ws:
                messagebox.showinfo(APP_NAME, "請先選擇工作資料夾，再把檔案拖進「工作區」。")
                return
            why = drop_target_reason(ws, target_rel)
            if why:
                messagebox.showerror(APP_NAME, f"不能放在這裡：{why}")
                return
            real_ws = os.path.realpath(ws)
            loops = [p for p in paths if os.path.isdir(p) and _inside(real_ws, os.path.realpath(p))]
            if loops:
                messagebox.showerror(APP_NAME, f"「{os.path.basename(os.path.normpath(loops[0]))}」就是工作資料夾（或包含它），"
                                               "不能複製到它自己裡面。")
                return
            n_files, size = measure_paths(paths)
            where = f"「{target_rel}」" if target_rel else "工作資料夾"
            size_text = f"{size / 1_000_000:,.1f} MB" if size >= 1_000_000 else f"{max(1, round(size / 1000)):,} KB"
            names = "、".join(os.path.basename(os.path.normpath(p)) for p in paths[:6]) + ("…" if len(paths) > 6 else "")
            big = n_files >= DROP_WARN_FILES or size >= DROP_WARN_BYTES
            if not messagebox.askyesno(APP_NAME, f"要把 {names}（共 {n_files:,} 個檔案、{size_text}）"
                                                 f"複製到{where}嗎？\n\n原本的檔案不會被移動或刪除。"
                                                 + ("\n\n⚠ 檔案很多或很大，複製要一些時間，Agent 讀取時也會比較慢。" if big else ""),
                                       icon="warning" if big else "question"):
                return
            conflict = "rename"
            dup = drop_conflicts(ws, paths, target_rel)
            if dup:
                ans = messagebox.askyesnocancel(APP_NAME, f"{where}已經有同名的：{'、'.join(dup[:8])}{'…' if len(dup) > 8 else ''}\n\n"
                                                          "是＝取代（被蓋掉的檔案先備份到 .ai協作/備份）\n"
                                                          "否＝另存成新名稱（例如 a (2).txt）\n取消＝不複製")
                if ans is None:
                    return
                conflict = "replace" if ans else "rename"
            self.status_label.configure(text=f"正在複製 {n_files:,} 個檔案到{where}…")

            def work():
                try:
                    done, skipped = copy_into_workspace(ws, paths, target_rel, conflict, self.conv.get("id") or "拖放")
                    err = None
                except (ToolError, OSError) as exc:
                    done, skipped, err = [], [], str(exc)

                def finish():
                    if err:
                        messagebox.showerror(APP_NAME, f"複製失敗：{err}")
                        return
                    self._refresh_ws_tab(force=True)
                    if done:
                        msg = f"📥 已複製到工作區：{'、'.join(done[:10])}{'…' if len(done) > 10 else ''}"
                        try:
                            self.transcript.notice(msg)
                            self.conv.setdefault("display", []).append(["notice", msg])
                        except (tk.TclError, AttributeError):
                            pass
                        self.status_label.configure(text=f"已複製 {len(done)} 個項目到{where}。")
                    if skipped:
                        messagebox.showwarning(APP_NAME, "以下項目沒有複製：\n" + "\n".join(skipped[:15]))
                self.ui_queue.put(("ui", None, "call", finish))
            threading.Thread(target=work, daemon=True).start()

        # ───────────── v6.11：貼上圖片、錄音 ─────────────
        def _on_paste(self, _event=None):
            try:
                self.clipboard_get()
                return None                          # 剪貼簿是文字：照一般方式貼上
            except tk.TclError:
                self.paste_image()
                return "break"

        def paste_image(self):
            dest = os.path.join(APP_DIR, "附件", "貼上")
            self.status_label.configure(text="正在讀取剪貼簿的圖片…")

            def work():
                path = grab_clipboard_image(dest)

                def done():
                    if not path:
                        self.status_label.configure(text="剪貼簿裡沒有圖片（先用截圖工具或「複製圖片」再按一次）。")
                        return
                    self.add_attachments([path])
                    self.status_label.configure(text=f"已貼上圖片：{os.path.basename(path)}")
                self.ui_queue.put(("ui", None, "call", done))
            threading.Thread(target=work, daemon=True).start()

        def toggle_recording(self):
            rec = getattr(self, "_recorder", None)
            if rec is None:
                rec = AudioRecorder()
                if not rec.backend:
                    messagebox.showinfo(APP_NAME, "這台電腦找不到錄音程式。Windows 內建可以錄；Linux 需要 arecord，"
                                                  "macOS 需要 sox（brew install sox）。")
                    return
                path = os.path.join(APP_DIR, "附件", "錄音", f"錄音_{time.strftime('%Y%m%d_%H%M%S')}.wav")
                try:
                    rec.start(path)
                except (RuntimeError, OSError) as exc:
                    messagebox.showerror(APP_NAME, str(exc))
                    return
                self._recorder = rec
                self.record_button.configure(text="■ 停止錄音")
                self.status_label.configure(text="🎤 錄音中…再按一次「停止錄音」就會轉成文字。")
                return
            self._recorder = None
            self.record_button.configure(text="🎤 錄音")
            try:
                path = rec.stop()
            except (RuntimeError, OSError) as exc:
                messagebox.showerror(APP_NAME, str(exc))
                return
            if path:
                self.transcribe_file(path)
            else:
                self.status_label.configure(text="沒有錄到聲音。")

        # ───────────── v6.11：用量 ─────────────
        def _report_usage(self, run):
            text = UsageMeter.summary(run)
            if not text or not getattr(self, "conv", None):
                return
            total = self.conv.setdefault("usage", {"prompt": 0, "completion": 0, "cost": 0.0, "calls": 0})
            for k in ("prompt", "completion", "cost", "calls"):
                total[k] = total.get(k, 0) + run.get(k, 0)
            whole = f"本對話累計 {total['prompt'] + total['completion']:,} token" + (
                f"、約 US${total['cost']:.4f}" if total.get("cost") else "")
            msg = f"📊 這次{text}。{whole}。"
            try:
                self.transcript.notice(msg)
                self.conv.setdefault("display", []).append(["notice", msg])
            except (tk.TclError, AttributeError):
                pass

        def _build_sandbox_budget_section(self, body):
            ttk.Label(body, text="沙盒執行", style="Section.TLabel").pack(anchor="w", pady=(14, 2))
            sb = tk.BooleanVar(value=bool(self.prefs.get("agent_sandbox", False)))
            ttk.Checkbutton(body, text="Agent 的指令在工作資料夾的暫存複本裡執行，跑完列出改了哪些檔案，你核准後才套回",
                            variable=sb).pack(anchor="w")
            ttk.Label(body, text="指令刪檔、改壞檔案都只影響複本；套回前先備份、可以復原，刪除不會套回。"
                                 "不含 .git 與捷徑；資料夾超過 6 萬個檔案或 1.5 GB 時不能用。"
                                 "注意：沙盒只保護工作資料夾，指令仍然可以連網或動到工作資料夾以外的地方。",
                      style="Muted.TLabel", wraplength=int(580 * self.scale)).pack(anchor="w", padx=(24, 0))
            ttk.Label(body, text="用量與預算", style="Section.TLabel").pack(anchor="w", pady=(14, 2))
            ttk.Label(body, text="每次執行（一輪 Agent 或一次 AI 討論）結束後，對話裡會顯示用了多少 token、約多少錢。"
                                 "超過上限就不再送出新的請求（0＝不限）。",
                      style="Muted.TLabel", wraplength=int(600 * self.scale)).pack(anchor="w")
            row = ttk.Frame(body, style="Surface.TFrame")
            row.pack(fill="x", pady=(4, 2))
            tok = tk.StringVar(value=str(self.prefs.get("budget_tokens", 0)))
            usd = tk.StringVar(value=str(self.prefs.get("budget_usd", 0)))
            ttk.Label(row, text="每次最多", style="Value.TLabel").pack(side="left")
            ttk.Entry(row, textvariable=tok, width=10).pack(side="left", padx=4)
            ttk.Label(row, text="token　或　US$", style="Value.TLabel").pack(side="left")
            ttk.Entry(row, textvariable=usd, width=8).pack(side="left", padx=4)
            ttk.Label(body, text="模型價格（美元／每百萬 token），每行「模型名稱的一部分 = 輸入價, 輸出價」，例如 gpt-5 = 1.25, 10；"
                                 "沒列的模型只算 token、不算錢（本機與訂閱 CLI 不用填）。",
                      style="Muted.TLabel", wraplength=int(600 * self.scale)).pack(anchor="w", pady=(6, 2))
            prices = tk.Text(body, height=4, width=60, relief="flat", highlightthickness=1)
            self._theme_widget(prices, "text")
            prices.insert("1.0", self.prefs.get("model_prices", ""))
            prices.pack(fill="x")

            def changed(*_a):
                try:
                    t = max(0, int(float(tok.get() or 0)))
                    u = max(0.0, float(usd.get() or 0))
                except ValueError:
                    return
                self.prefs.update(agent_sandbox=bool(sb.get()), budget_tokens=t, budget_usd=u,
                                  model_prices=prices.get("1.0", "end-1c"))
                self._apply_advanced_prefs()
                self._mark_dirty()
                if self.runner:
                    self.runner.options = self._agent_options()
            sb.trace_add("write", changed)
            tok.trace_add("write", changed)
            usd.trace_add("write", changed)
            prices.bind("<KeyRelease>", changed)

        # ───────────── v6.11：匯出 HTML／PDF／GitHub Issue ─────────────
        def export_conversation_as(self, sid, kind):
            sid = sid or self.conv.get("id")
            try:
                data = self.conv if self.conv.get("id") == sid else load_session(sid)
            except (OSError, ValueError) as exc:
                messagebox.showerror(APP_NAME, f"讀不到這個對話：{exc}")
                return
            title = mask_secrets(data.get("title") or "對話")[0]
            md = mask_secrets(session_to_markdown(data))[0]
            safe = re.sub(r'[\\/:*?"<>|]', "_", title)[:40]
            if kind == "html":
                path = filedialog.asksaveasfilename(title="匯出成 HTML", defaultextension=".html", initialfile=f"{safe}.html",
                                                    filetypes=[("HTML", "*.html")])
                if path:
                    self._write_file(path, markdown_to_html(md, title))
                return
            if kind == "pdf":
                path = filedialog.asksaveasfilename(title="匯出成 PDF", defaultextension=".pdf", initialfile=f"{safe}.pdf",
                                                    filetypes=[("PDF", "*.pdf")])
                if not path:
                    return
                self.status_label.configure(text="正在轉成 PDF（用 Edge／Chrome，最多約 1 分鐘）…")

                def work():
                    try:
                        html_to_pdf(markdown_to_html(md, title), path, timeout=60)
                        done = lambda: self.status_label.configure(text=f"已匯出：{os.path.basename(path)}")
                    except (RuntimeError, OSError) as exc:
                        done = lambda e=exc: messagebox.showerror(APP_NAME, f"轉成 PDF 失敗：{e}")
                    self.ui_queue.put(("ui", None, "call", done))
                threading.Thread(target=work, daemon=True).start()
                return
            repo = simpledialog.askstring("發到 GitHub Issue", "倉庫（擁有者/名稱）：", parent=self,
                                          initialvalue=self.prefs.get("github_repo", ""))
            if not repo:
                return
            repo = repo.strip()
            token = None
            for name in ("GITHUB_TOKEN", "GH_TOKEN"):
                token = lookup_env(name).get("value")
                if token:
                    break
            if not token:
                messagebox.showinfo(APP_NAME, "需要 GitHub 權杖：請把權杖設成環境變數 GITHUB_TOKEN（或 GH_TOKEN），"
                                              "權限只要能建立 Issue 即可，然後重新開啟程式。")
                return
            if not messagebox.askyesno(APP_NAME, f"要在 {repo} 開一個 Issue「{title[:60]}」嗎？\n\n"
                                                 f"對話內容（{len(md):,} 字）會上傳到 GitHub，能看到這個倉庫的人都看得到。"
                                                 "像金鑰的字串已先遮蔽。", icon="warning"):
                return
            self.prefs["github_repo"] = repo
            self._mark_dirty()
            self.status_label.configure(text="正在建立 GitHub Issue…")

            def work_issue():
                try:
                    url = github_create_issue(repo, title, md, token)
                    done = lambda: (self.status_label.configure(text=f"已建立 Issue：{url}"),
                                    messagebox.showinfo(APP_NAME, f"已建立 Issue：\n{url}"))
                except (ValueError, RuntimeError, OSError) as exc:
                    done = lambda e=exc: messagebox.showerror(APP_NAME, f"建立 Issue 失敗：{mask_secrets(str(e))[0]}")
                self.ui_queue.put(("ui", None, "call", done))
            threading.Thread(target=work_issue, daemon=True).start()

        # ───────────── v6.11：範本與 AI 團隊匯入匯出 ─────────────
        def export_bundle_dialog(self):
            path = filedialog.asksaveasfilename(title="匯出範本與 AI 團隊", defaultextension=".json",
                                                initialfile="AI協作_範本與團隊.json", filetypes=[("JSON", "*.json")])
            if path:
                self._write_file(path, json.dumps(export_bundle(self.settings), ensure_ascii=False, indent=2))

        def import_bundle_dialog(self):
            if self.busy:
                messagebox.showinfo(APP_NAME, "執行中不能匯入，請等這一輪結束。")
                return
            path = filedialog.askopenfilename(title="匯入範本與 AI 團隊", filetypes=[("JSON", "*.json")])
            if not path:
                return
            try:
                if os.path.getsize(path) > 5_000_000:
                    raise ValueError("檔案太大（超過 5 MB）")
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                preview = {"services": [], "templates": dict(self.settings.get("templates", {}))}
                n_sv, n_tp, warns = import_bundle(preview, data)
            except (OSError, ValueError) as exc:
                messagebox.showerror(APP_NAME, f"匯入失敗：{exc}")
                return
            names = "、".join(s["name"] or s["model"] for s in preview["services"][:10])
            if not messagebox.askyesno(APP_NAME, f"要加入 {n_sv} 位 AI（{names or '無'}）與 {n_tp} 個範本嗎？\n"
                                                 "只會新增，不會覆蓋你現有的設定。" + ("\n\n⚠ " + "\n⚠ ".join(warns[:8]) if warns else "")):
                return
            for sv in preview["services"]:
                sv.setdefault("credential", sv.get("credential_env", ""))
                self.services.append(sv)
            self.settings["templates"] = preview["templates"]
            self._refresh_templates()
            fix_service_names(self.services)
            self.save_settings(quiet=True)
            try:
                self._refresh_model_choices()
                self._graph_for_conversation()
            except (tk.TclError, AttributeError):
                pass
            self.status_label.configure(text=f"已匯入 {n_sv} 位 AI、{n_tp} 個範本（舊設定已備份）。")

        # ───────────── v6.11：Git 分支隔離 ─────────────
        def _fill_branch_menu(self):
            m = self.branch_menu
            m.delete(0, "end")
            info = self.conv.get("branch") if getattr(self, "conv", None) else None
            if info:
                m.add_command(label=f"目前在分支 {info['branch']}", state="disabled")
                m.add_command(label="合併回原本的分支…", command=self.merge_branch)
                m.add_command(label="回到原資料夾（分支保留，不合併）", command=self.leave_branch)
            else:
                m.add_command(label="在新分支工作（Agent 的修改先放在獨立資料夾）…", command=self.start_branch)

        def start_branch(self):
            ws = self._ws_root()
            if self.busy or not ws:
                messagebox.showinfo(APP_NAME, "請先選擇工作資料夾，並等目前的工作結束。")
                return
            try:
                info = git_worktree_start(ws)
            except GitError as exc:
                messagebox.showerror(APP_NAME, f"無法開分支：{exc}")
                return
            extra = f"\n\n⚠ 原資料夾有 {info['dirty']} 個還沒提交的修改，這些不會出現在新分支裡。" if info["dirty"] else ""
            messagebox.showinfo(APP_NAME, f"已建立分支 {info['branch']}，工作資料夾換到：\n{info['path']}\n\n"
                                          "Agent 接下來的修改都在這裡，原本的資料夾不會變。確認沒問題後按「⑂ 分支 → 合併回原本的分支」。"
                                          + extra)
            self.set_workspace(info["path"])
            self.conv["branch"] = info
            self._save_conv()

        def merge_branch(self):
            info = self.conv.get("branch")
            if self.busy or not info:
                return
            try:
                summary = git_worktree_summary(info)
            except GitError as exc:
                messagebox.showerror(APP_NAME, str(exc))
                return
            files = summary["uncommitted"]
            if not files and not summary["commits"]:
                messagebox.showinfo(APP_NAME, "分支裡沒有任何修改。")
                return
            listing = "\n".join(files[:25]) + ("\n…" if len(files) > 25 else "")
            if not messagebox.askyesno(APP_NAME, f"要把分支 {info['branch']} 合併回「{info.get('base')}」嗎？\n\n"
                                                 f"未提交的修改 {len(files)} 個（會先提交）：\n{listing}\n"
                                                 f"已提交 {len(summary['commits'])} 次。"):
                return
            try:
                text = git_worktree_merge(info)
            except GitError as exc:
                messagebox.showerror(APP_NAME, str(exc))
                return
            self.conv.pop("branch", None)
            self.set_workspace(info["origin"])
            self._save_conv()
            messagebox.showinfo(APP_NAME, text)

        def leave_branch(self):
            info = self.conv.get("branch")
            if self.busy or not info:
                return
            self.conv.pop("branch", None)
            self.set_workspace(info["origin"])
            self._save_conv()
            self.status_label.configure(text=f"已回到 {info['origin']}；分支 {info['branch']} 與資料夾都保留著。")

        def _write_file(self, path, content):
            try:
                with open(path, "w", encoding="utf-8") as output:
                    output.write(content)
                self.status_label.configure(text=f"已匯出：{os.path.basename(path)}")
            except OSError as exc:
                messagebox.showerror(APP_NAME, f"匯出失敗：{exc}")

        def _open_dir(self, path):
            os.makedirs(path, exist_ok=True)
            open_path(path)

        def _on_mousewheel(self, event):
            if event.num == 4:
                steps = -1
            elif event.num == 5:
                steps = 1
            else:
                steps = int(-event.delta / 120) or (-1 if event.delta > 0 else 1)
            try:
                widget = self.winfo_containing(event.x_root, event.y_root)
            except (KeyError, tk.TclError):
                return None
            while widget is not None:
                if isinstance(widget, (tk.Text, tk.Listbox, ttk.Combobox, ttk.Spinbox)):
                    first, last = widget.yview() if hasattr(widget, "yview") and not isinstance(widget, (ttk.Combobox, ttk.Spinbox)) else (0, 1)
                    if isinstance(widget, (ttk.Combobox, ttk.Spinbox)) or (steps < 0 and first > 0) or (steps > 0 and last < 1):
                        return None          # 元件自己還能捲 → 交給它
                sf = getattr(widget, "_scroll_frame", None)
                if sf is not None:
                    sf.canvas.yview_scroll(steps, "units")
                    return "break"
                widget = getattr(widget, "master", None)
            return None

        def _report_exception(self, exc, value, tb):
            log_app.error("介面錯誤", exc_info=(exc, value, tb))
            try:
                self.status_label.configure(text=f"發生錯誤：{value}（詳見日誌）")
            except Exception:
                pass


        def _on_close(self):
            if self.busy and not messagebox.askyesno(APP_NAME, "仍在執行中，確定要中止並關閉嗎？"):
                return
            if self.dirty:
                answer = messagebox.askyesnocancel(APP_NAME, "設定有尚未儲存的變更，要先儲存嗎？\n（直接貼上的金鑰本體不會保存）")
                if answer is None:
                    return
                if answer and not self.save_settings(quiet=True):
                    return
            try:
                zoomed = self.state() == "zoomed"
                state = {"zoomed": zoomed}
                if self.graph_visible and self.center.winfo_height() > 0:
                    state["graph_ratio"] = round(self.center.sashpos(0) / self.center.winfo_height(), 3)
                else:
                    state["graph_ratio"] = self.ui_state.get("graph_ratio", 0.46)
                if not zoomed:
                    state["geometry"] = self.geometry()
                save_ui_state(state)
            except (tk.TclError, OSError):
                pass
            self.stop()
            try:
                self.mcp.stop_all()
            except Exception:
                pass
            log_app.info("關閉程式")
            self.destroy()

    return AIWorkbench
