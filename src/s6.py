# ═════════════════════════ 6. 協作拓樸圖 ═════════════════════════
# 中央（或上方）是主持 AI，周圍是各角色 AI；虛線是訊息通道，小光點代表訊息往來。
# 版面依 AI 數量自動切換：
#   1～8 位：「環繞」版面——左右兩側環繞主持 AI，每位旁邊有一張資訊卡。
#   9 位以上：「陣列」版面——主持 AI 在上方，所有 AI 以格狀排列並以匯流線相連。
# 畫布不夠大時整張圖等比縮小，保證元件不重疊。


def rounded_points(x1, y1, x2, y2, r):
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    return [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
            x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]


def short_model(model):
    """「deepseek-ai/deepseek-v4.1-flash」→「deepseek-v4.1-flash」（廠商前綴佔空間，完整名稱放在提示框）。"""
    return (model or "").rstrip("/").split("/")[-1]


def _bezier(a, c, b, steps=24):
    pts = []
    for i in range(steps + 1):
        t = i / steps
        pts.append(((1 - t) ** 2 * a[0] + 2 * (1 - t) * t * c[0] + t * t * b[0],
                    (1 - t) ** 2 * a[1] + 2 * (1 - t) * t * c[1] + t * t * b[1]))
    return pts


def _make_topology_class():
    """tkinter 載入後才建立類別（讓 --selftest 不需要 tkinter）。"""

    class TopologyView(tk.Canvas):
        CARD_MAX = 8          # 超過這個數量改用陣列版面

        def __init__(self, master, theme, family, scale=1.0, callbacks=None):
            super().__init__(master, bg=theme["canvas"], highlightthickness=0, bd=0)
            self.t = theme
            self.base = scale
            self.s = scale
            self.cb = callbacks or {}
            self.agents, self.hub, self.mode = [], None, MODE_SYNTH
            self.states, self.details, self.previews = {}, {}, {}
            self.selected = None
            self.ranks = {}          # pid → 互評平均名次
            self.agent_view = False  # True：Agent 模式（中央是 Agent，周圍是工具類別）
            self.tip_pid = None
            self.phase, self.round_text, self.final_preview = "待命", "共享脈絡", ""
            self.running = False
            self.pos, self.anchor, self.paths, self.eyes, self.card_geom = {}, {}, {}, {}, {}
            self.sprites = {}            # pid → (圖片項目, 各格圖片, 起始格)：會動的角色
            self._sprite_cache, self._sprite_used = {}, set()
            self.packets, self.flow_timer = [], {}
            self.hub_arc, self.arc_angle, self.frame = None, 0, 0
            self.layout_kind = "cards"
            self.final_geom = None
            self._redraw_job = None
            self.f = {k: tkfont.Font(family=family, size=v[0], weight=v[1]) for k, v in
                      {"title": (10, "bold"), "small": (8, "normal"), "body": (9, "normal"),
                       "hub": (11, "bold"), "icon": (7, "bold")}.items()}
            self.f["icon"].configure(family=DEFAULT_MONO_FONT)
            self.bind("<Configure>", lambda _e: self._schedule_redraw())
            self.after(40, self._animate)

        # ───────────── 對外介面 ─────────────
        def set_theme(self, theme, family):
            self.t = theme
            for key in ("title", "small", "body", "hub"):
                self.f[key].configure(family=family)
            self.configure(bg=theme["canvas"])
            self._schedule_redraw()

        def set_participants(self, agents, hub, mode):
            self.agents, self.hub, self.mode = list(agents), hub, mode
            for a in self.agents:
                if not a.get("enabled", True):
                    self.states[a["id"]] = "disabled"
                elif self.states.get(a["id"]) in (None, "disabled"):
                    self.states[a["id"]] = "idle"
            self._schedule_redraw()

        def reset_run(self):
            for a in self.agents:
                self.states[a["id"]] = "idle" if a.get("enabled", True) else "disabled"
                self.details[a["id"]] = self.previews[a["id"]] = ""
            self.states[HUB_ID] = "idle"
            self.details[HUB_ID] = self.previews[HUB_ID] = ""
            self.ranks = {}
            self.final_preview = ""
            self.packets.clear()
            self.redraw()

        def set_state(self, pid, status, detail=None):
            self.states[pid] = status
            if detail is not None:
                self.details[pid] = detail
            self._update_node(pid)

        def set_preview(self, pid, text):
            self.previews[pid] = text
            self._update_node(pid)

        def set_final(self, text):
            self.final_preview = text or ""
            if self.final_geom:
                self.itemconfigure("final_text", text=self._fit(self.final_preview or "完成後點這裡查看",
                                                                self.f["small"], self.final_geom))

        def set_phase(self, phase, round_text=None):
            self.phase = phase
            if round_text is not None:
                self.round_text = round_text
            self.itemconfigure("phase_text", text=phase)
            self.itemconfigure("context_text", text=self.round_text)

        def set_running(self, running):
            self.running = running
            self.flow_timer.clear()
            self.itemconfigure("phase_dot", fill=self.t["accent"] if running else self.t["line"])

        def select(self, pid):
            self.selected = pid
            self.redraw()

        def pulse_link(self, src, dst, kind="review"):
            path = self._link_path(src, dst, kind)
            if path:
                self._spawn(path, self._color(src), size=5, speed=0.03)

        # ───────────── 顏色與文字 ─────────────
        def _schedule_redraw(self):
            if self._redraw_job:
                self.after_cancel(self._redraw_job)
            self._redraw_job = self.after(60, self.redraw)

        def _agent(self, pid):
            return next((a for a in self.agents if a["id"] == pid), None)

        def _color(self, pid):
            if pid == HUB_ID:
                return self.t["hub"]
            a = self._agent(pid)
            if a and not a.get("enabled", True):
                return mix(self.t["muted"], self.t["canvas"], 0.3)
            return self.t.role_color(a.get("role") if a else DEFAULT_ROLE)

        def _light(self, pid):
            if pid == HUB_ID:
                return self.t["hub_light"]
            a = self._agent(pid)
            if a and not a.get("enabled", True):
                return mix(self.t["muted"], self.t["canvas"], 0.82)
            return self.t.role_light(a.get("role") if a else DEFAULT_ROLE)

        def _fit(self, text, font, width, lines=1):
            text = " ".join((text or "").split())
            if not text or width <= 10:
                return ""
            budget = width * lines * 0.94
            if font.measure(text) <= budget:
                return text
            lo, hi = 0, len(text)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if font.measure(text[:mid] + "…") <= budget:
                    lo = mid
                else:
                    hi = mid - 1
            return text[:lo] + "…"

        # ───────────── 繪圖基本元件 ─────────────
        def _rrect(self, x1, y1, x2, y2, r, **kw):
            return self.create_polygon(rounded_points(x1, y1, x2, y2, r), smooth=True, **kw)

        def _card(self, x1, y1, x2, y2, tags, outline=None, width=1, r=12):
            s = self.s
            self._rrect(x1, y1 + 3 * s, x2, y2 + 4 * s, r * s, fill=self.t["shadow"], outline="", tags=tags)
            return self._rrect(x1, y1, x2, y2, r * s, fill=self.t["surface"], outline=outline or self.t["border"],
                               width=width, tags=tags)

        # ───────────── 動態角色（「機器人動畫」資料夾的逐格圖） ─────────────
        # 有素材時拓樸圖用會動的角色；找不到素材或讀取失敗時，_robot 改用下面程式畫的造型。
        def _sprite_frames(self, look, want):
            path, size = robot_sprite_file(look, want)
            if not path:
                return None
            key = (path, size)
            frames = self._sprite_cache.get(key)
            if frames is None:
                frames = []
                try:
                    sheet = tk.PhotoImage(master=self, file=path)
                    count = sheet.width() // size
                    if count >= ROBOT_SPRITE_FRAMES + 1 and sheet.height() >= size:
                        for i in range(ROBOT_SPRITE_FRAMES + 1):
                            img = tk.PhotoImage(master=self, width=size, height=size)
                            img.tk.call(img, "copy", sheet, "-from", i * size, 0, (i + 1) * size, size,
                                        "-to", 0, 0, "-compositingrule", "set")
                            frames.append(img)
                    del sheet
                except tk.TclError as e:          # 例如 Tk 太舊讀不了 PNG：記住失敗，之後用程式畫的造型
                    logging.getLogger("ai_collab.ui").warning("讀取動態角色失敗 %s：%s", path, e)
                    frames = []
                self._sprite_cache[key] = frames
            self._sprite_used.add(key)
            return (frames, size) if frames else None

        def _sprite_dim(self, pid):
            """停用的 AI、此模式用不到的主持 AI：顯示淡灰定格。"""
            if pid == HUB_ID:
                return not (self.agent_view or self.mode in (MODE_SYNTH, MODE_REVIEW, MODE_PLAN))
            a = self._agent(pid)
            return bool(a and not a.get("enabled", True))

        def _sprite_robot(self, pid, cx, cy, k, color, light, tags, look):
            s = self.s * k
            got = self._sprite_frames(look, 112 * s)
            if not got:
                return False
            frames, _size = got
            t = self.t

            def oval(x1, y1, x2, y2, **kw):
                self.create_oval(cx + x1 * s, cy + y1 * s, cx + x2 * s, cy + y2 * s, tags=tags, **kw)

            # 底座和程式畫的造型一樣，顏色跟著身分與狀態
            oval(-46, 30, 46, 54, fill=mix(light, t["shadow"], 0.45), outline="")
            oval(-44, 22, 44, 48, fill=light, outline=color, width=max(1, 2 * self.s))
            oval(-30, 27, 30, 41, fill=mix(light, t["surface"], 0.5), outline="")
            if self._sprite_dim(pid):
                self.create_image(cx, cy - 8 * s, image=frames[ROBOT_SPRITE_FRAMES], tags=tags)
                return True
            # 每位的起始格錯開，不會整齊劃一地動
            phase = int(hashlib.md5(str(pid).encode("utf-8")).hexdigest(), 16) % ROBOT_SPRITE_FRAMES
            index = (self.frame // 2 + phase) % ROBOT_SPRITE_FRAMES if self.t.animate else ROBOT_SPRITE_STILL
            item = self.create_image(cx, cy - 8 * s, image=frames[index], tags=tags)
            self.sprites[pid] = (item, frames, phase)
            return True

        # ───────────── Q 版機器人：原創造型「協作小隊」（沒有動態素材時使用） ─────────────
        # 全家共同特徵：麻糬形大頭、深色螢幕臉＋發光大眼與腮紅、兩側六角耳螺絲、圓圓小身體與短腳、圓形底座。
        # 每個身分各有自己的道具，一眼就能分辨工作：
        #   一般助理＝星星天線＋小領巾、揮手　　程式專家＝耳罩耳機＋筆電　　研究分析＝探險帽＋放大鏡
        #   對話溝通＝對話框天線＋耳麥　　　　　文件撰寫＝貝雷帽＋大鉛筆　　資料處理＝資料庫帽＋長條圖平板
        #   審查批判＝方帽＋認真眉毛＋打勾夾板　主持 AI＝節點光環＋領結＋指揮棒　Agent＝工程帽＋扳手＋工具腰帶
        ROBOT_PROP_INK = {"pencil": "#F3BE45", "pencil_tip": "#F4DDBB", "eraser": "#F29BB0", "lead": "#4A4A55",
                          "blush": "#FF7FA0", "spark": "#FFFFFF"}

        def _robot(self, pid, cx, cy, k, color, light, tags, look=None):
            s = self.s * k
            t = self.t
            look = look if look in ROBOT_LOOKS else DEFAULT_ROLE
            if self._sprite_robot(pid, cx, cy, k, color, light, tags, look):
                return
            ink, shell = t["robot_line"], t["robot"]
            lw = max(1, 1.3 * s)
            prop = self.ROBOT_PROP_INK

            def P(*xy):
                return [v * s + (cx if i % 2 == 0 else cy) for i, v in enumerate(xy)]

            def oval(x1, y1, x2, y2, **kw):
                return self.create_oval(*P(x1, y1, x2, y2), tags=tags, **kw)

            def rr(x1, y1, x2, y2, r, **kw):
                return self._rrect(*P(x1, y1, x2, y2), r * s, tags=tags, **kw)

            def poly(pts, **kw):
                return self.create_polygon(*P(*pts), tags=tags, **kw)

            def line(pts, w=1.6, **kw):
                return self.create_line(*P(*pts), width=max(1, w * s), capstyle="round", joinstyle="round",
                                        tags=tags, **kw)

            def arc(x1, y1, x2, y2, start, extent, w=1.6, **kw):
                return self.create_arc(*P(x1, y1, x2, y2), start=start, extent=extent, style="arc",
                                       width=max(1, w * s), tags=tags, **kw)

            def star(x, y, r, points=4, inner=0.42, **kw):
                pts = []
                for i in range(points * 2):
                    rad = r if i % 2 == 0 else r * inner
                    a = math.radians(180 / points * i - 90)
                    pts += [x + rad * math.cos(a), y + rad * math.sin(a)]
                return poly(pts, **kw)

            def hexagon(x, y, r, **kw):
                return poly([v for i in range(6) for v in (x + r * math.cos(math.radians(60 * i)),
                                                           y + r * math.sin(math.radians(60 * i)))], **kw)

            def arm(side, raised=False):
                d = 1 if side == "right" else -1
                if raised:
                    pts, hand = [13 * d, 6, 22 * d, -3, 27 * d, 0, 19 * d, 12], (25 * d, -3)
                else:
                    pts, hand = [13 * d, 8, 22 * d, 13, 21 * d, 20, 13 * d, 17], (22 * d, 19)
                poly(pts, smooth=True, fill=shell, outline=ink, width=lw)
                oval(hand[0] - 4, hand[1] - 4, hand[0] + 4, hand[1] + 4, fill=color, outline="")

            # 底座與影子
            oval(-46, 30, 46, 54, fill=mix(light, t["shadow"], 0.45), outline="")
            oval(-44, 22, 44, 48, fill=light, outline=color, width=max(1, 2 * self.s))
            oval(-30, 27, 30, 41, fill=mix(light, t["surface"], 0.5), outline="")
            # 腳、身體、肚子
            oval(-13, 25, -3, 34, fill=color, outline="")
            oval(3, 25, 13, 34, fill=color, outline="")
            rr(-15, 2, 15, 31, 11, fill=shell, outline=ink, width=lw)
            oval(-9, 11, 9, 27, fill=light, outline="")
            oval(-3, 16, 3, 22, fill=color, outline="")

            # 手（拿道具的那隻手在後面畫）
            raised_left = look in ("對話溝通",)
            raised_right = look in ("一般助理",)
            if look not in ("程式專家", "審查批判"):
                arm("left", raised_left)
            if look not in ("程式專家", "研究分析", "文件撰寫", "資料處理", "主持", "Agent"):
                arm("right", raised_right)

            # 身體上的配件
            if look == "一般助理":
                poly([-11, 3, 11, 3, 0, 12], fill=color, outline="")
            elif look == "主持":
                poly([-9, 2, -1, 6, -9, 10], fill=color, outline="")
                poly([9, 2, 1, 6, 9, 10], fill=color, outline="")
                oval(-2.5, 3.5, 2.5, 8.5, fill=mix(color, "#000000", 0.2), outline="")
            elif look == "Agent":
                rr(-15, 19, 15, 24, 2, fill=color, outline="")
                rr(-4, 18, 4, 25, 1.5, fill=mix(color, "#FFFFFF", 0.45), outline="")

            # 頭
            rr(-31, -38, 31, 8, 20, fill=shell, outline=ink, width=lw)
            if look not in ("程式專家",):
                for x in (-32, 32):
                    hexagon(x, -15, 5, fill=color, outline="")
                    oval(x - 1.6, -16.6, x + 1.6, -13.4, fill=mix(color, "#FFFFFF", 0.5), outline="")
            rr(-23, -30, 23, 0, 13, fill=t["visor"], outline="")
            line([-17, -26.5, -11, -27.5], w=1.4, fill=mix(t["visor"], "#FFFFFF", 0.3))
            # 臉：大眼睛（含亮點，眨眼時一起闔上）、嘴巴、腮紅
            eyes = []
            for ex in (-10, 10):
                c1 = P(ex - 5.5, -23, ex + 5.5, -10)
                if look == "程式專家":          # 方形像素眼
                    c1 = P(ex - 5, -22, ex + 5, -11)
                    item = self.create_rectangle(*c1, fill=t["eye"], outline="", tags=tags)
                else:
                    item = self.create_oval(*c1, fill=t["eye"], outline="", tags=tags)
                eyes.append((item, c1))
                c2 = P(ex - 3.2, -21, ex - 0.2, -17.6)
                eyes.append((self.create_oval(*c2, fill=prop["spark"], outline="", tags=tags), c2))
            self.eyes[pid] = eyes
            if look == "對話溝通":              # 張嘴說話
                self.create_arc(*P(-4.5, -11, 4.5, -2), start=180, extent=180, style="chord", fill=t["eye"],
                                outline="", tags=tags)
            else:
                arc(-4, -10.5, 4, -3.5, 205, 130, w=1.4, outline=t["eye"])
            for bx in (-18, 14):
                oval(bx, -8.5, bx + 5, -5, fill=mix(t["visor"], prop["blush"], 0.6), outline="")
            if look == "審查批判":
                line([-16, -27, -6, -24.5], w=1.6, fill=t["eye"])
                line([16, -27, 6, -24.5], w=1.6, fill=t["eye"])

            # 頭上的配件與手上的道具
            if look == "一般助理":
                line([0, -38, 0, -46], w=1.8, fill=ink)
                star(0, -50, 6.5, fill=color, outline="")
                star(0, -50, 2.4, fill=mix(color, "#FFFFFF", 0.6), outline="")
            elif look == "程式專家":
                arc(-35, -47, 35, 12, 18, 144, w=3.2, outline=color)
                for x1 in (-38, 29):
                    rr(x1, -23, x1 + 9, -5, 4, fill=color, outline="")
                arm("left")
                arm("right")
                poly([-17, 22, 17, 22, 20, 28, -20, 28], fill=ink, outline="")
                rr(-13, 8, 13, 23, 2.5, fill=t["visor"], outline=ink, width=lw)
                for y, x2 in ((12.5, -1), (15.5, 6), (18.5, 2)):
                    line([-8, y, x2, y], w=1.3, fill=color)
            elif look == "研究分析":
                oval(-30, -38, 30, -30, fill=color, outline="")
                rr(-18, -51, 18, -33, 9, fill=color, outline="")
                line([-17, -38, 17, -38], w=2, fill=mix(color, "#FFFFFF", 0.45))
                line([25, -2, 30, -8], w=3, fill=ink)
                oval(25, -24, 43, -6, fill=mix(light, t["surface"], 0.35), outline=color, width=max(1, 3 * s))
                arc(28, -21, 40, -9, 100, 70, w=1.4, outline=prop["spark"])
                arm("right", True)
            elif look == "對話溝通":
                arc(-35, -47, 35, 12, 30, 120, w=2, outline=ink)
                rr(-38, -21, -30, -7, 3.5, fill=color, outline="")
                line([-34, -8, -27, 2, -15, 3], w=1.6, fill=ink)
                oval(-17, 0.5, -12, 5.5, fill=color, outline="")
                line([8, -38, 12, -46], w=1.8, fill=ink)
                rr(6, -62, 32, -46, 6, fill=color, outline="")
                poly([12, -47, 9, -41, 17, -47], fill=color, outline="")
                for dx in (12, 19, 26):
                    oval(dx - 1.6, -55.6, dx + 1.6, -52.4, fill=prop["spark"], outline="")
            elif look == "文件撰寫":
                poly([-29, -33, -22, -44, -2, -48, 20, -43, 24, -35], smooth=True, fill=color, outline="")
                line([-1, -47, 1, -52], w=2, fill=color)
                poly([20, 16, 36, -8, 41, -5, 25, 19], fill=prop["pencil"], outline=ink, width=lw)
                poly([36, -8, 41, -5, 41.5, -14], fill=prop["pencil_tip"], outline=ink, width=lw)
                poly([39.6, -11.5, 41.2, -10.4, 41.5, -14], fill=prop["lead"], outline="")
                poly([20, 16, 25, 19, 23, 22, 18, 19], fill=prop["eraser"], outline="")
                arm("right", True)
            elif look == "資料處理":
                rr(-13, -49, 13, -36, 3, fill=color, outline="")
                oval(-13, -52, 13, -46, fill=mix(color, "#FFFFFF", 0.35), outline="")
                arc(-13, -46, 13, -40, 180, 180, w=1.4, outline=mix(color, "#FFFFFF", 0.5))
                arm("right")
                rr(14, 4, 36, 24, 3, fill=t["visor"], outline=ink, width=lw)
                for x, top in ((19, 15), (25, 9), (31, 12)):
                    line([x, 20, x, top], w=3, fill=color)
            elif look == "審查批判":
                rr(-13, -44, 13, -35, 3, fill=mix(color, "#000000", 0.18), outline="")
                poly([-26, -43, 0, -51, 26, -43, 0, -36], fill=color, outline="")
                line([18, -42, 22, -33], w=1.4, fill=mix(color, "#000000", 0.25))
                oval(20, -34, 24, -30, fill=mix(color, "#000000", 0.25), outline="")
                arm("right")
                rr(-38, 3, -18, 27, 2.5, fill=t["surface"], outline=ink, width=lw)
                rr(-32, 1, -24, 6, 1.5, fill=color, outline="")
                line([-33, 15, -29, 20, -22, 10], w=2.4, fill=color)
                arm("left")
            elif look == "主持":
                oval(-23, -55, 23, -46, outline=color, width=max(1, 2 * s))
                for nx, ny in ((-21, -50.5), (21, -50.5), (0, -55)):
                    oval(nx - 3, ny - 3, nx + 3, ny + 3, fill=color, outline=t["surface"], width=max(1, s))
                line([24, -3, 36, -16], w=2, fill=ink)
                star(37, -17, 5.5, points=5, inner=0.45, fill=color, outline="")
                arm("right", True)
            elif look == "Agent":
                rr(-24, -51, 24, -34, 13, fill=color, outline="")
                rr(-31, -38, 31, -32, 3, fill=color, outline="")
                line([0, -50, 0, -37], w=2.4, fill=mix(color, "#FFFFFF", 0.4))
                star(32, -12, 9, points=8, inner=0.72, fill=mix(color, "#1A1A22", 0.35), outline="")
                oval(29, -15, 35, -9, fill=light, outline="")
                arm("right", True)

        def _badge(self, cx, cy, icon, color, tags, k=1.0):
            s = self.s * k
            r = 11 * s
            w = "#FFFFFF"
            self.create_oval(cx - r, cy - r, cx + r, cy + r, fill=color, outline=self.t["surface"],
                             width=max(1, 2 * self.s), tags=tags)
            lw = max(1, 1.6 * s)
            if icon == "code":
                self.create_text(cx, cy, text="</>", fill=w, font=self.f["icon"], tags=tags)
            elif icon == "search":
                self.create_oval(cx - 5 * s, cy - 5 * s, cx + 2 * s, cy + 2 * s, outline=w, width=lw, tags=tags)
                self.create_line(cx + 1 * s, cy + 1 * s, cx + 5 * s, cy + 5 * s, fill=w, width=lw, tags=tags)
            elif icon == "chat":
                self._rrect(cx - 6 * s, cy - 5 * s, cx + 6 * s, cy + 3 * s, 3 * s, fill=w, outline="", tags=tags)
                self.create_polygon(cx - 3 * s, cy + 2 * s, cx - 5 * s, cy + 7 * s, cx + 1 * s, cy + 2 * s, fill=w,
                                    outline="", tags=tags)
            elif icon == "doc":
                self.create_rectangle(cx - 4.5 * s, cy - 6 * s, cx + 4.5 * s, cy + 6 * s, outline=w, width=lw,
                                      tags=tags)
                for dy in (-2, 1, 4):
                    self.create_line(cx - 2.5 * s, cy + dy * s, cx + 2.5 * s, cy + dy * s, fill=w, tags=tags)
            elif icon == "db":
                self.create_oval(cx - 5 * s, cy - 6 * s, cx + 5 * s, cy - 2 * s, outline=w, width=lw, tags=tags)
                self.create_line(cx - 5 * s, cy - 4 * s, cx - 5 * s, cy + 4 * s, fill=w, width=lw, tags=tags)
                self.create_line(cx + 5 * s, cy - 4 * s, cx + 5 * s, cy + 4 * s, fill=w, width=lw, tags=tags)
                self.create_arc(cx - 5 * s, cy + 2 * s, cx + 5 * s, cy + 6 * s, start=180, extent=180, style="arc",
                                outline=w, width=lw, tags=tags)
            elif icon == "check":
                self.create_line(cx - 5 * s, cy, cx - 1.5 * s, cy + 4 * s, cx + 5 * s, cy - 4 * s, fill=w,
                                 width=max(1, 2 * s), tags=tags)
            elif icon == "hub":
                for i in range(6):
                    a = math.radians(60 * i)
                    self.create_line(cx, cy, cx + 6 * s * math.cos(a), cy + 6 * s * math.sin(a), fill=w, tags=tags)
                self.create_oval(cx - 3 * s, cy - 3 * s, cx + 3 * s, cy + 3 * s, fill=w, outline="", tags=tags)
            else:
                pts = []
                for i in range(8):
                    rr = (6 if i % 2 == 0 else 2.2) * s
                    a = math.radians(45 * i - 90)
                    pts += [cx + rr * math.cos(a), cy + rr * math.sin(a)]
                self.create_polygon(pts, fill=w, outline="", tags=tags)

        def _chip(self, pid, x_right, y_mid, max_w, tags):
            """狀態膠囊（右對齊），回傳膠囊寬度。"""
            s = self.s
            text, color = self.t.status(self.states.get(pid, "idle"))
            detail = self.details.get(pid) or ""
            label = self._fit(text + (f" {detail}" if detail else ""), self.f["small"], max_w)
            w = self.f["small"].measure(label) + 20 * s
            self._rrect(x_right - w, y_mid - 9 * s, x_right, y_mid + 9 * s, 9 * s,
                        fill=mix(color, self.t["surface"], 0.85), outline="", tags=tags + (f"chipbg:{pid}",))
            self.create_oval(x_right - w + 7 * s, y_mid - 3 * s, x_right - w + 13 * s, y_mid + 3 * s, fill=color,
                             outline="", tags=tags + (f"chipdot:{pid}",))
            self.create_text(x_right - w + 16 * s, y_mid, text=label, anchor="w", fill=color, font=self.f["small"],
                             tags=tags + (f"chip:{pid}",))
            return w

        # ───────────── 主要繪製 ─────────────
        def redraw(self):
            self._redraw_job = None
            self.delete("all")
            for d in (self.pos, self.anchor, self.paths, self.eyes, self.card_geom, self.sprites):
                d.clear()
            self.packets.clear()
            self._sprite_used = set()
            w, h = max(self.winfo_width(), 300), max(self.winfo_height(), 140)   # 高度不能假裝成 300，否則矮的區域會被裁掉
            # 版面：畫布又寬又矮（例如放在對話串上方）→ 橫帶版面；否則 1～8 位環繞、9 位以上陣列
            band_fit, band_rows = self._band_fit(w, h)
            cards_fit = min(1.0, w / (1000 * self.base), h / (640 * self.base))
            if self.agents and w / max(1, h) >= 1.7 and band_fit > cards_fit * 1.15:
                self.layout_kind, fit, self.band_rows = "band", band_fit, band_rows
            elif len(self.agents) <= self.CARD_MAX:
                self.layout_kind, fit = "cards", cards_fit
            else:
                self.layout_kind, fit = "grid", self._grid_fit(w, h)
            self.s = self.base * max(0.34 if self.layout_kind == "band" else 0.42, fit)
            ratio = self.s / self.base
            for key, size, low in (("title", 10, 7), ("small", 8, 6), ("body", 9, 7), ("hub", 11, 8), ("icon", 7, 5)):
                self.f[key].configure(size=max(low, round(size * ratio)))
            if self.t.show_grid:
                self._draw_backdrop(w, h)
            if self.layout_kind == "cards":
                self._draw_cards_layout(w, h)
            elif self.layout_kind == "band":
                self._draw_band_layout(w, h)
            else:
                self._draw_grid_layout(w, h)
            self._draw_header()
            if not self.agents:
                self.create_text(w / 2, h - 40 * self.s, text="還沒有任何 AI，請用工具列的「AI 數量」或「端點」分頁新增。",
                                 fill=self.t["muted"], font=self.f["body"])
            # 動態角色的快取只留這次畫面用到的尺寸（視窗縮放後舊尺寸就用不到了）
            if len(self._sprite_cache) > 2 * len(ROBOT_SPRITE_KEYS):
                for key in [k for k in self._sprite_cache if k not in self._sprite_used]:
                    del self._sprite_cache[key]

        def _draw_backdrop(self, w, h):
            step = int(max(18, 28 * self.s))
            color = self.t["grid"]
            # 背景點陣畫成一張圖片並快取：原本每次重畫都建立數百個小圓點，會讓畫面變慢
            key = (int(w), int(h), step, color)
            if getattr(self, "_bg_key", None) != key:
                img = tk.PhotoImage(width=int(w), height=int(h))
                xs = range(step // 2, int(w), step)
                for y in range(step // 2, int(h) - 1, step):
                    for x in xs:
                        if x + 2 <= int(w):
                            img.put(color, to=(x - 1, y - 1, x + 1, y + 1))
                self._bg_img, self._bg_key = img, key
            self.create_image(0, 0, image=self._bg_img, anchor="nw")

        def _draw_header(self):
            s = self.s
            x, y = 14 * s, 12 * s
            label = {"cards": "環繞版面", "band": "橫帶版面"}.get(self.layout_kind, "陣列版面")
            if self.agent_view:
                text = f"Agent｜{self.mode}｜AI 團隊 {len(self.agents)} 位"
            else:
                n_ans = len([a for a in self.agents if a.get('enabled', True)])
                hub_txt = "＋主持" if self.hub and self.mode in (MODE_SYNTH, MODE_REVIEW, MODE_PLAN) else ""
                text = f"{self.mode}｜{n_ans} 位回答{hub_txt}｜{label}"
            tw = self.f["title"].measure(text)
            self._rrect(x, y, x + tw + 26 * s, y + 28 * s, 14 * s, fill=self.t["surface"], outline=self.t["border"])
            self.create_text(x + 13 * s, y + 14 * s, text=text, anchor="w", fill=self.t["text"], font=self.f["title"])
            y2 = y + 34 * s
            self.create_oval(x + 4 * s, y2 + 6 * s, x + 12 * s, y2 + 14 * s,
                             fill=self.t["accent"] if self.running else self.t["line"], outline="", tags=("phase_dot",))
            self.create_text(x + 18 * s, y2 + 10 * s, text=self.phase, anchor="w", fill=self.t["muted"],
                             font=self.f["body"], tags=("phase_text",))

        def _line(self, points, pid, base_width=1.4):
            active = self.states.get(pid) in ACTIVE_STATES
            flat = [v for p in points for v in p]
            self.create_line(*flat, fill=self._color(pid) if active else self.t["line"],
                             width=max(1, (2 if active else base_width) * self.s), dash=(6, 5),
                             tags=("line", f"line:{pid}"))

        # ── 1～8 位：環繞版面 ──
        def _draw_cards_layout(self, w, h):
            s = self.s
            cx, cy = w / 2, h / 2 + 6 * s
            card_w = 196 * s
            rx = max(150 * s, w / 2 - card_w - 70 * s)
            ry = max(105 * s, h / 2 - 100 * s)
            n = len(self.agents)
            right = (n + 1) // 2

            def angles(k):
                if k <= 0:
                    return []
                if k == 1:
                    return [0.0]
                span = min(100.0, 34.0 * (k - 1))
                return [-span / 2 + span * i / (k - 1) for i in range(k)]

            places = [(cx + rx * math.cos(math.radians(a)), cy + ry * math.sin(math.radians(a)), "right")
                      for a in angles(right)]
            places += [(cx - rx * math.cos(math.radians(a)), cy + ry * math.sin(math.radians(a)), "left")
                       for a in angles(n - right)]
            hub_pt = (cx, cy + 10 * s)
            self.pos[HUB_ID] = hub_pt
            for agent, (x, y, _side) in zip(self.agents, places):
                pid = agent["id"]
                self.pos[pid] = (x, y + 10 * s)
                self.paths[pid] = [hub_pt, (x, y + 10 * s)]
                self._line(self.paths[pid], pid)
            top_y = max(52 * s, cy - ry - 20 * s)
            bottom_y = min(h - 48 * s, cy + ry + 34 * s)
            if self.mode != MODE_PARALLEL:
                self.create_line(cx, cy - 70 * s, cx, top_y + 28 * s, fill=self.t["line"], dash=(4, 4))
                self.create_line(cx, cy + 60 * s, cx, bottom_y - 30 * s, fill=self.t["line"], dash=(4, 4))
            self._draw_context(cx, top_y)
            self._draw_hub(cx, cy, 1.25)
            for agent, (x, y, side) in zip(self.agents, places):
                self._draw_agent_card(agent, x, y, side, card_w, w)
            self._draw_final(cx, bottom_y, 120 * s)

        def _draw_agent_card(self, agent, x, y, side, card_w, canvas_w):
            s = self.s
            pid = agent["id"]
            tags = ("node", f"node:{pid}")
            color, light = self._color(pid), self._light(pid)
            state = self.states.get(pid, "idle")
            if state in ACTIVE_STATES:
                self.create_oval(x - 58 * s, y + 10 * s, x + 58 * s, y + 56 * s, outline=color, width=max(1, 2 * s),
                                 tags=tags + (f"glow:{pid}",))
            self._robot(pid, x, y - 6 * s, 0.9, color, light, tags, agent.get("role"))
            self._badge(x, y + 34 * s, ROLES.get(agent.get("role"), ROLES[DEFAULT_ROLE])["icon"], color, tags, 0.95)
            self._rank_badge(pid, x - 34 * s, y - 40 * s, tags)
            card_h = 84 * s
            x1 = min(x + 54 * s, canvas_w - card_w - 8 * s) if side == "right" else max(x - 54 * s - card_w, 8 * s)
            x2 = x1 + card_w
            y1 = y - card_h / 2 - 6 * s
            selected = self.selected == pid
            self._card(x1, y1, x2, y1 + card_h, tags, outline=color if selected else None,
                       width=max(1, (2 if selected else 1) * s))
            self.create_rectangle(x1 + 10 * s, y1 + 12 * s, x1 + 13 * s, y1 + 26 * s, fill=color, outline="", tags=tags)
            chip_w = self._chip(pid, x2 - 8 * s, y1 + 19 * s, card_w * 0.5, tags)
            title = self._fit(agent.get("name") or "未命名", self.f["title"], card_w - chip_w - 34 * s)
            self.create_text(x1 + 19 * s, y1 + 19 * s, text=title, anchor="w", fill=self.t["text"],
                             font=self.f["title"], tags=tags)
            meta = agent.get("meta") or f"{agent.get('role') or DEFAULT_ROLE}｜{short_model(agent.get('model')) or '未設定模型'}"
            self.create_text(x1 + 12 * s, y1 + 38 * s, text=self._fit(meta, self.f["small"], card_w - 24 * s),
                             anchor="w", fill=self.t["muted"], font=self.f["small"], tags=tags)
            preview = self.previews.get(pid) or ("（停用中，右鍵可啟用）" if state == "disabled" else "點一下查看回覆")
            self.create_text(x1 + 12 * s, y1 + 50 * s, text=self._fit(preview, self.f["small"], card_w - 24 * s, 2),
                             anchor="nw", width=card_w - 24 * s,
                             fill=self.t["text"] if self.previews.get(pid) else self.t["muted"],
                             font=self.f["small"], tags=tags + (f"preview:{pid}",))
            self.card_geom[pid] = (card_w - 24 * s, 2, card_w * 0.5)
            self._bind_node(pid)

        # ── 橫帶版面：主持 AI／Agent 在中央，兩側以機器人小卡排成 1～3 列 ──
        HUB_BAND_W = 250

        def _band_dims(self, rows):
            n = len(self.agents)
            left = n // 2
            right = n - left
            cols = max(1, math.ceil(max(left, right) / rows))
            need_w = self.HUB_BAND_W + 2 * cols * self.TILE_W + 30
            need_h = max(rows * self.TILE_H, 290) + 66        # 中央欄要放共享脈絡、主持 AI、最終成果
            return cols, need_w, need_h

        def _band_fit(self, w, h):
            best, best_rows = 0.0, 1
            if not self.agents:
                return 0.0, 1
            for rows in (1, 2, 3):
                if rows > 1 and math.ceil(len(self.agents) / 2) < rows:
                    break
                _cols, need_w, need_h = self._band_dims(rows)
                fit = min(1.0, w / (need_w * self.base), h / (need_h * self.base))
                if fit > best + 0.02:
                    best, best_rows = fit, rows
            return best, best_rows

        def _draw_band_layout(self, w, h):
            s = self.s
            rows = self.band_rows
            cols, need_w, need_h = self._band_dims(rows)
            cx = w / 2
            cy = 36 * s + (h - 36 * s) / 2 - 8 * s
            hub_pt = (cx, cy + 10 * s)
            self.pos[HUB_ID] = hub_pt
            n = len(self.agents)
            left_n = n // 2
            right = self.agents[:n - left_n]
            left = self.agents[n - left_n:]
            places = []
            for side, group in ((1, right), (-1, left)):
                for i, agent in enumerate(group):
                    col, row = divmod(i, rows)
                    in_col = min(rows, len(group) - col * rows)
                    x = cx + side * (self.HUB_BAND_W / 2 + (col + 0.5) * self.TILE_W) * s
                    top = cy - in_col * self.TILE_H * s / 2 + row * self.TILE_H * s
                    places.append((agent, x, top, side))
            for agent, x, top, side in places:
                pid = agent["id"]
                anchor = (x - side * (self.TILE_W - 12) * s / 2, top + 6 * s + (self.TILE_H - 12) * s / 2)
                self.paths[pid] = [hub_pt, anchor]
                self.pos[pid] = anchor
                self._line(self.paths[pid], pid)
            self._draw_hub(cx, cy - 6 * s, 0.85)
            if h > 260 * s:
                self._draw_context(cx - 26 * s, max(36 * s, cy - 118 * s))
            self._draw_final(cx, min(h - 36 * s, cy + 108 * s), 86 * s)
            for agent, x, top, _side in places:
                self._draw_agent_tile(agent, x, top)

        # ── 9 位以上：陣列版面 ──
        TILE_W, TILE_H, TOP_BAND = 168, 150, 200

        def _grid_dims(self, w, s):
            cols = max(1, int((w - 24 * s) // (self.TILE_W * s)))
            cols = min(cols, max(1, len(self.agents)))
            rows = math.ceil(len(self.agents) / cols) if self.agents else 0
            return cols, rows

        def _grid_fit(self, w, h):
            fit = min(1.0, w / (1000 * self.base))
            while fit > 0.42:
                s = self.base * fit
                cols, rows = self._grid_dims(w, s)
                if (self.TOP_BAND + rows * self.TILE_H + 16) * s <= h:
                    break
                fit *= 0.95
            return fit

        def _draw_grid_layout(self, w, h):
            s = self.s
            cx = w / 2
            hub_y = 92 * s
            cols, rows = self._grid_dims(w, s)
            grid_w = cols * self.TILE_W * s
            gx = (w - grid_w) / 2
            gy = self.TOP_BAND * s
            bus_y = gy - 18 * s
            hub_pt = (cx, hub_y + 52 * s)
            self.pos[HUB_ID] = (cx, hub_y)
            places = []
            for i, agent in enumerate(self.agents):
                r, c = divmod(i, cols)
                in_row = min(cols, len(self.agents) - r * cols)
                offset = (cols - in_row) * self.TILE_W * s / 2      # 最後一列置中
                x = gx + offset + (c + 0.5) * self.TILE_W * s
                y = gy + r * self.TILE_H * s
                places.append((x, y))
            # 匯流線：主持 AI → 水平匯流排 → 各列
            if places:
                xs = [p[0] for p in places]
                self.create_line(cx, hub_pt[1], cx, bus_y, fill=self.t["line"], width=max(1, 1.4 * s), dash=(6, 5))
                self.create_line(min(xs + [cx]), bus_y, max(xs + [cx]), bus_y, fill=self.t["line"],
                                 width=max(1, 1.4 * s), dash=(6, 5))
            for agent, (x, y) in zip(self.agents, places):
                pid = agent["id"]
                top = (x, y + 4 * s)
                self.paths[pid] = [hub_pt, (cx, bus_y), (x, bus_y), top]
                self.pos[pid] = (x, y + 50 * s)
                self.anchor[pid] = top
                self._line([(x, bus_y), top], pid)
            self._draw_hub(cx, hub_y, 0.95)
            self._draw_context(max(70 * s, cx - 250 * s), 60 * s)
            self._draw_final(min(w - 130 * s, cx + 270 * s), 96 * s, 112 * s)
            for agent, (x, y) in zip(self.agents, places):
                self._draw_agent_tile(agent, x, y)

        def _draw_agent_tile(self, agent, x, y):
            s = self.s
            pid = agent["id"]
            tags = ("node", f"node:{pid}")
            color, light = self._color(pid), self._light(pid)
            tw, th = (self.TILE_W - 12) * s, (self.TILE_H - 12) * s
            x1, y1 = x - tw / 2, y + 6 * s
            selected = self.selected == pid
            self._card(x1, y1, x1 + tw, y1 + th, tags, outline=color if selected else None,
                       width=max(1, (2 if selected else 1) * s), r=14)
            state = self.states.get(pid, "idle")
            if state in ACTIVE_STATES:
                self._rrect(x1 - 3 * s, y1 - 3 * s, x1 + tw + 3 * s, y1 + th + 3 * s, 16 * s, fill="", outline=color,
                            width=max(1, 2 * s), tags=tags + (f"glow:{pid}",))
            self._robot(pid, x, y1 + 46 * s, 0.62, color, light, tags, agent.get("role"))
            self._badge(x + 31 * s, y1 + 73 * s, ROLES.get(agent.get("role"), ROLES[DEFAULT_ROLE])["icon"], color,
                        tags, 0.75)
            self._rank_badge(pid, x1 + 18 * s, y1 + 18 * s, tags)
            self.create_text(x, y1 + 92 * s, text=self._fit(agent.get("name") or "未命名", self.f["title"], tw - 16 * s),
                             fill=self.t["text"], font=self.f["title"], tags=tags)
            self.create_text(x, y1 + 108 * s, text=self._fit(agent.get("meta") or f"{agent.get('role') or DEFAULT_ROLE}・{short_model(agent.get('model')) or '未設定模型'}", self.f["small"],
                                                             tw - 16 * s),
                             fill=self.t["muted"], font=self.f["small"], tags=tags)
            text, scolor = self.t.status(state)
            detail = self.details.get(pid) or ""
            label = self._fit(text + (f" {detail}" if detail else ""), self.f["small"], tw - 34 * s)
            cw = self.f["small"].measure(label) + 20 * s
            self._chip(pid, x + cw / 2, y1 + th - 14 * s, tw - 34 * s, tags)
            self.card_geom[pid] = (None, 0, tw - 34 * s)
            self._bind_node(pid)

        # ── 共用節點 ──
        def _draw_hub(self, cx, cy, k):
            s = self.s * k
            tags = ("node", f"node:{HUB_ID}")
            uses_hub = self.agent_view or self.mode in (MODE_SYNTH, MODE_REVIEW, MODE_PLAN)
            color = self.t["hub"] if uses_hub else mix(self.t["hub"], self.t["canvas"], 0.45)
            light = self.t["hub_light"]
            self.create_oval(cx - 90 * s, cy - 16 * s, cx + 90 * s, cy + 53 * s,
                             fill=mix(light, self.t["canvas"], 0.5), outline="", tags=tags)
            self.create_oval(cx - 77 * s, cy - 6 * s, cx + 77 * s, cy + 45 * s, fill=light,
                             outline=mix(color, self.t["canvas"], 0.35), width=max(1, 2 * self.s), tags=tags)
            self.hub_arc = self.create_arc(cx - 77 * s, cy - 6 * s, cx + 77 * s, cy + 45 * s, start=self.arc_angle,
                                           extent=70, style="arc", outline=color, width=max(2, 3 * self.s), tags=tags)
            self.create_oval(cx - 56 * s, cy + 3 * s, cx + 56 * s, cy + 35 * s,
                             fill=mix(light, self.t["surface"], 0.55), outline="", tags=tags)
            if self.selected == HUB_ID:
                self.create_oval(cx - 82 * s, cy - 10 * s, cx + 82 * s, cy + 49 * s, outline=self.t["accent"],
                                 width=max(2, 2.5 * self.s), tags=tags)
            self._robot(HUB_ID, cx, cy - 16 * s, k, color, light, tags, "Agent" if self.agent_view else "主持")
            name = "主持 AI" + (f"：{self.hub.get('name')}" if self.hub and uses_hub else "（此模式不需要）")
            if self.agent_view:
                name = f"Agent：{self.hub.get('name')}" if self.hub else "Agent（尚未選擇模型）"
            self.create_text(cx, cy + 58 * s, text=self._fit(name, self.f["hub"], 260 * self.s), fill=self.t["text"],
                             font=self.f["hub"], tags=tags)
            self.create_text(cx, cy + 75 * s, text=self._hub_status_text(), fill=self.t.status(self.states.get(HUB_ID, "idle"))[1],
                             font=self.f["small"], tags=tags + ("hub_status",))
            self._bind_node(HUB_ID)

        def _hub_status_text(self):
            uses_hub = self.agent_view or self.mode in (MODE_SYNTH, MODE_REVIEW, MODE_PLAN)
            status = self.t.status(self.states.get(HUB_ID, "idle"))[0]
            detail = self.details.get(HUB_ID) or ""
            model = self.hub.get("model", "") if self.hub and uses_hub else ""
            return "｜".join(x for x in (self._fit(model, self.f["small"], 150 * self.s),
                                         status + (f" {detail}" if detail else "")) if x)

        def _draw_context(self, cx, y):
            s = self.s
            tags = ("node", f"node:{CONTEXT_ID}")
            color = mix(self.t["accent"], self.t["canvas"], 0.35 if self.mode != MODE_PARALLEL else 0.65)
            fill = mix(self.t["accent"], self.t["surface"], 0.9)
            for i in range(3):
                top = y + i * 9 * s
                self.create_rectangle(cx - 22 * s, top + 4 * s, cx + 22 * s, top + 12 * s, fill=fill, outline="",
                                      tags=tags)
                self.create_line(cx - 22 * s, top + 4 * s, cx - 22 * s, top + 12 * s, fill=color, tags=tags)
                self.create_line(cx + 22 * s, top + 4 * s, cx + 22 * s, top + 12 * s, fill=color, tags=tags)
                self.create_arc(cx - 22 * s, top + 6 * s, cx + 22 * s, top + 18 * s, start=180, extent=180,
                                style="arc", outline=color, tags=tags)
            self.create_oval(cx - 22 * s, y - 2 * s, cx + 22 * s, y + 10 * s, fill=self.t["surface"], outline=color,
                             tags=tags)
            self.create_text(cx + 32 * s, y + 14 * s, text=self.round_text, anchor="w", fill=self.t["muted"],
                             font=self.f["small"], tags=tags + ("context_text",))
            self._bind_node(CONTEXT_ID)

        def _draw_final(self, cx, y, half_w):
            s = self.s
            tags = ("node", f"node:{FINAL_ID}")
            h2 = 30 * s
            selected = self.selected == FINAL_ID
            self._card(cx - half_w, y - h2, cx + half_w, y + h2, tags,
                       outline=self.t["accent"] if selected else None, width=max(1, (2 if selected else 1) * s), r=14)
            self._badge(cx - half_w + 24 * s, y, "doc", self.t["accent"], tags, 1.0)
            label = {MODE_PARALLEL: "各家回答（未彙整）", MODE_RELAY: "最終成果（最後一棒）"}.get(self.mode, "最終成果")
            self.create_text(cx - half_w + 44 * s, y - 10 * s, text=label, anchor="w", fill=self.t["text"],
                             font=self.f["title"], tags=tags)
            self.final_geom = 2 * half_w - 56 * s
            self.create_text(cx - half_w + 44 * s, y + 10 * s, anchor="w", fill=self.t["muted"], font=self.f["small"],
                             text=self._fit(self.final_preview or "完成後點這裡查看", self.f["small"], self.final_geom),
                             tags=tags + ("final_text",))
            self._bind_node(FINAL_ID)

        def _rank_badge(self, pid, x, y, tags):
            """互評綜合名次徽章（第 1 名金色、第 2 名銀色、第 3 名銅色）。"""
            if pid not in self.ranks:
                return
            order = sorted(self.ranks, key=lambda p: self.ranks[p])
            place = order.index(pid) + 1
            color = {1: "#E5A823", 2: "#9AA5B4", 3: "#C27A45"}.get(place, self.t["muted"])
            r = 11 * self.s
            self.create_oval(x - r, y - r, x + r, y + r, fill=color, outline=self.t["surface"], width=max(1, 2 * self.s),
                             tags=tags)
            self.create_text(x, y, text=f"#{place}", fill="#FFFFFF", font=self.f["small"], tags=tags)

        def set_ranks(self, ranks):
            self.ranks = dict(ranks or {})
            self._schedule_redraw()

        def _bind_node(self, pid):
            tag = f"node:{pid}"
            self.tag_bind(tag, "<Button-1>", lambda _e, p=pid: self.cb.get("select", lambda _p: None)(p))
            self.tag_bind(tag, "<Double-Button-1>", lambda _e, p=pid: self.cb.get("open", lambda _p: None)(p))
            self.tag_bind(tag, "<Button-3>", lambda e, p=pid: self.cb.get("menu", lambda _p, _e: None)(p, e))
            self.tag_bind(tag, "<Enter>", lambda e, p=pid: (self.configure(cursor="hand2"), self._show_tip(p, e)))
            self.tag_bind(tag, "<Motion>", lambda e, p=pid: self._move_tip(e))
            self.tag_bind(tag, "<Leave>", lambda _e: (self.configure(cursor=""), self._hide_tip()))

        # ───────────── 提示框（滑鼠移上去顯示完整資訊） ─────────────
        def _tip_lines(self, pid):
            if pid in (FINAL_ID, CONTEXT_ID):
                return ["點一下查看" + ("最終成果" if pid == FINAL_ID else "共享脈絡")]
            if pid == HUB_ID:
                if not self.hub:
                    return ["主持 AI：未設定"]
                return [f"主持 AI：{self.hub.get('name')}", f"模型：{self.hub.get('model')}",
                        "狀態：" + self.t.status(self.states.get(HUB_ID, "idle"))[0],
                        "雙擊編輯設定、右鍵更多操作"]
            a = self._agent(pid)
            if not a:
                return []
            lines = [a.get("name") or "未命名", f"角色：{a.get('role') or DEFAULT_ROLE}",
                     f"模型：{a.get('model') or '未設定'}"]
            status = self.t.status(self.states.get(pid, "idle"))[0]
            detail = self.details.get(pid)
            lines.append(f"狀態：{status}" + (f" {detail}" if detail else ""))
            if pid in self.ranks:
                lines.append(f"互評平均名次：{self.ranks[pid]:.1f}")
            lines.append("點一下看回覆・雙擊編輯・右鍵更多")
            return lines

        def _show_tip(self, pid, event):
            self._hide_tip()
            lines = self._tip_lines(pid)
            if not lines:
                return
            self.tip_pid = pid
            s = self.base
            text = "\n".join(lines)
            item = self.create_text(0, 0, text=text, anchor="nw", fill=self.t["text"], font=self.f["body"],
                                    tags=("tip", "tip_text"))
            x1, y1, x2, y2 = self.bbox(item)
            pad = 8 * s
            self._rrect(0, 0, x2 - x1 + 2 * pad, y2 - y1 + 2 * pad, 8 * s, fill=self.t["surface"],
                        outline=self.t["accent"], tags=("tip", "tip_bg"))
            self.tag_raise("tip_text")
            self.tip_size = (x2 - x1 + 2 * pad, y2 - y1 + 2 * pad, pad)
            self._move_tip(event)

        def _move_tip(self, event):
            if not self.tip_pid or not self.find_withtag("tip"):
                return
            w, h, pad = self.tip_size
            x = event.x + 16
            y = event.y + 16
            if x + w > self.winfo_width() - 4:
                x = event.x - w - 12
            if y + h > self.winfo_height() - 4:
                y = event.y - h - 12
            bg = self.find_withtag("tip_bg")
            if bg:
                bx1, by1, _bx2, _by2 = self.bbox(bg[0])
                self.move("tip_bg", x - bx1, y - by1)
            self.coords("tip_text", x + pad, y + pad)
            self.tag_raise("tip")

        def _hide_tip(self):
            self.tip_pid = None
            self.delete("tip")

        # ───────────── 局部更新 ─────────────
        def _update_node(self, pid):
            if pid == HUB_ID:
                self.itemconfigure("hub_status", text=self._hub_status_text(),
                                   fill=self.t.status(self.states.get(HUB_ID, "idle"))[1])
                return
            if pid not in self.pos:
                return
            state = self.states.get(pid, "idle")
            if (state in ACTIVE_STATES) != bool(self.find_withtag(f"glow:{pid}")):
                self._schedule_redraw()
                return
            color = self._color(pid)
            active = state in ACTIVE_STATES
            self.itemconfigure(f"line:{pid}", fill=color if active else self.t["line"],
                               width=max(1, (2 if active else 1.4) * self.s))
            text, scolor = self.t.status(state)
            detail = self.details.get(pid) or ""
            geom = self.card_geom.get(pid)
            label = text + (f" {detail}" if detail else "")
            old = self.itemcget(f"chip:{pid}", "text") if self.find_withtag(f"chip:{pid}") else ""
            if geom and self.f["small"].measure(self._fit(label, self.f["small"], geom[2])) > self.f["small"].measure(old) + 2:
                self._schedule_redraw()      # 膠囊變寬時重畫，讓標題讓出空間
            if geom:
                label = self._fit(label, self.f["small"], geom[2])
            self.itemconfigure(f"chip:{pid}", text=label, fill=scolor)
            self.itemconfigure(f"chipdot:{pid}", fill=scolor)
            self.itemconfigure(f"chipbg:{pid}", fill=mix(scolor, self.t["surface"], 0.85))
            if geom and geom[0] and self.previews.get(pid):
                self.itemconfigure(f"preview:{pid}", text=self._fit(self.previews[pid], self.f["small"], geom[0], geom[1]),
                                   fill=self.t["text"])

        # ───────────── 動畫 ─────────────
        def _link_path(self, src, dst, kind):
            if src == HUB_ID:
                return self.paths.get(dst)
            if kind == "synth" or dst == HUB_ID:
                p = self.paths.get(src)
                return list(reversed(p)) if p else None
            a, b = self.paths.get(src), self.paths.get(dst)
            if not a or not b:
                return None
            if self.layout_kind == "grid":
                return list(reversed(a))[:-1] + b[1:]
            hub = self.pos[HUB_ID]
            pa, pb = a[-1], b[-1]
            mid = ((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2)
            ctrl = (mid[0] + (hub[0] - mid[0]) * 0.55, mid[1] + (hub[1] - mid[1]) * 0.55)
            return _bezier(pa, ctrl, pb)

        def _spawn(self, points, color, size=4, speed=0.035):
            if len(points) < 2:
                return
            lengths = [math.dist(points[i], points[i + 1]) for i in range(len(points) - 1)]
            total = sum(lengths) or 1
            r = size * self.s
            x, y = points[0]
            item = self.create_oval(x - r, y - r, x + r, y + r, fill=color, outline=self.t["surface"], width=1)
            self.packets.append({"item": item, "pts": points, "len": lengths, "total": total, "t": 0.0,
                                 "speed": speed * min(2.0, max(0.6, 500 * self.s / total)), "r": r})

        def _at(self, p):
            d = p["t"] * p["total"]
            for i, seg in enumerate(p["len"]):
                if d <= seg or i == len(p["len"]) - 1:
                    f = 0 if seg == 0 else min(1.0, d / seg)
                    (x1, y1), (x2, y2) = p["pts"][i], p["pts"][i + 1]
                    return x1 + (x2 - x1) * f, y1 + (y2 - y1) * f
                d -= seg
            return p["pts"][-1]

        def _animate(self):
            try:
                self.frame += 1
                if self.t.animate and self.running:
                    if self.hub_arc:
                        self.arc_angle = (self.arc_angle - 6) % 360
                        self.itemconfigure(self.hub_arc, start=self.arc_angle)
                    for a in self.agents:
                        pid = a["id"]
                        state = self.states.get(pid)
                        path = self.paths.get(pid)
                        if state not in ACTIVE_STATES or not path:
                            continue
                        if self.frame >= self.flow_timer.get(pid, 0):
                            self.flow_timer[pid] = self.frame + (10 if state == "generating" else 16)
                            self._spawn(list(reversed(path)) if state == "generating" else path, self._color(pid))
                    if self.states.get(HUB_ID) in ACTIVE_STATES and self.frame % 14 == 0:
                        for a in self.agents:
                            if a.get("enabled", True) and self.paths.get(a["id"]):
                                self._spawn(list(reversed(self.paths[a["id"]])), self.t["hub"], size=3)
                    width = max(1, (1.5 + abs(math.sin(self.frame / 6))) * self.s)
                    for a in self.agents:
                        self.itemconfigure(f"glow:{a['id']}", width=width)
                alive = []
                for p in self.packets:
                    p["t"] += p["speed"]
                    if p["t"] >= 1:
                        self.delete(p["item"])
                        continue
                    x, y = self._at(p)
                    r = p["r"]
                    self.coords(p["item"], x - r, y - r, x + r, y + r)
                    alive.append(p)
                self.packets = alive
                if self.t.animate and self.sprites and self.frame % 2 == 0:      # 動態角色：每 80 毫秒換一格
                    step = self.frame // 2
                    for item, frames, phase in self.sprites.values():
                        self.itemconfigure(item, image=frames[(step + phase) % ROBOT_SPRITE_FRAMES])
                if self.t.animate and self.frame % 25 == 0 and self.eyes:
                    pid = random.choice(list(self.eyes))
                    for item, (x1, y1, x2, y2) in self.eyes[pid]:
                        mid = (y1 + y2) / 2
                        self.coords(item, x1, mid - 1, x2, mid + 1)
                    self.after(130, lambda p=pid: self._open_eyes(p))
            except tk.TclError:
                return
            self.after(40, self._animate)

        def _open_eyes(self, pid):
            try:
                for item, coords in self.eyes.get(pid, []):
                    self.coords(item, *coords)
            except tk.TclError:
                pass

    return TopologyView

