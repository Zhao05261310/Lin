# ═════════════════════════ 5. 設定檔、紀錄、附加檔、日誌（不永久刪除任何資料） ═════════════════════════

log = logging.getLogger("ai_collab")

SETTINGS_VERSION = 2

DEFAULT_PREFERENCES = {
    "mode": MODE_SYNTH,
    "review_rounds": 1,
    "hub_id": "",
    "system_prompt": DEFAULT_SYSTEM_PROMPT,
    "filter_think": True,
    "include_usage": True,
    "key_priority": "system",
    "quote_limit": QUOTE_LIMIT_DEFAULT,
    "continue_chat": False,
    "auto_record": True,
    "auto_retry": True,
    # 協作品質與可控性（v4）
    "hub_exclusive": True,          # 主持 AI 不同時參與回答（避免偏好自己的答案）
    "spread_temperature": True,     # 相同模型自動使用不同溫度（避免意見同質化）
    "revise_char_limit": 1500,      # 互評「修正後回答」字數上限（0＝不限）
    "time_limit_min": 0,            # 整次執行時間上限（分鐘，0＝不限）；超過就停止互評直接彙整
    "token_limit": 0,               # token 上限（0＝不限）
    "max_concurrent": 4,            # 同時呼叫數上限（0＝不限）
    "max_rpm": 0,                   # 每分鐘請求上限（0＝不限）
    "pause_each_round": False,      # 每輪結束後暫停，讓使用者查看並補充指示
    "confirm_big_runs": True,       # 呼叫次數多時先確認
    "quick_small_talk": True,       # 打招呼、道謝等很短的訊息只請一位 AI 回答
    "auto_route": True,
    "web_research": True,           # AI 討論前先上網查證（主持 AI 判斷需要時）
    "quote_total": 24000,           # 互評／整合時引用其他回答的總字數上限（人越多每份越短；0＝不限）
    "transcribe_id": "",
    "mcp_enabled": True,
    "update_url": "",               # 新版 AI協作.py 的網址（例如 GitHub raw），可一鍵更新            # Agent 可以使用 MCP伺服器.json 裡啟用的外部工具            # 語音轉文字用的 AI（模型要是 whisper 之類）             # 主持 AI 先判斷：簡單問題直接回答，值得討論才啟動整場討論
    "straggler_factor": 3,          # 多數 AI 已完成、剩下的超過中位數幾倍時間就不等（0＝一律等）
    "straggler_min_sec": 90,        # 至少等這麼久才考慮不等
    "think_limit": THINK_LIMIT_DEFAULT,   # 思考超過這麼多秒還沒開始回答，就改成不思考重新回答（0＝不限制）
    "health_check": True,           # 每天第一次開啟時，只讀模型清單檢查金鑰與模型是否可用
    "health_last": "",              # 上次健康檢查的日期
    "schedule_max_steps": 30,       # 排程執行（無人看管）時的 Agent 步數上限
    "schedule_time_limit_min": 30,  # 排程整體時間上限（分鐘，0＝不限）
    "trusted_agents_md": {},        # 已確認信任的 AGENTS.md（路徑 → 內容雜湊）
    "latency": {},                  # 各模型過去的平均回應秒數（用來預估時間）
    # Agent（v5）
    "agent_model_id": "",
    "agent_mode": "build",
    "agent_perms": {},
    "agent_max_steps": 40,
    "agent_tool_mode": "auto",
    "agent_web_search": True,
    "last_workspace": "",
    "recent_workspaces": [],
    "new_chat_type": "agent",
    # 外觀
    "theme": DEFAULT_THEME,
    "font_family": DEFAULT_UI_FONT,
    "font_size": 10,
    "content_family": DEFAULT_UI_FONT,
    "reply_font_size": 11,
    "color_overrides": {},
    "role_colors": {},
    "show_grid": True,
    "animate": True,
}


def new_id():
    return uuid.uuid4().hex[:10]


def normalize_service(raw):
    """把舊版或手改過的服務設定整理成完整欄位。"""
    if not isinstance(raw, dict):
        return None
    role = str(raw.get("role") or DEFAULT_ROLE)
    return {
        "id": str(raw.get("id") or new_id()),
        "name": str(raw.get("name") or ""),
        "role": role if role in ROLES else DEFAULT_ROLE,
        "url": str(raw.get("url") or ""),
        "model": str(raw.get("model") or ""),
        "credential_env": str(raw.get("credential_env") or ""),
        "enabled": bool(raw.get("enabled", True)),
        "temperature": str(raw.get("temperature") or ""),
        "max_tokens": str(raw.get("max_tokens") or ""),
        "task": str(raw.get("task") or ""),
        "num_ctx": str(raw.get("num_ctx") or "") if str(raw.get("num_ctx") or "").isdigit() else "",   # 本機（Ollama）上下文長度
        "keep_alive": str(raw.get("keep_alive") or ""),                                                 # 本機模型用完保持載入多久
        "reasoning": str(raw.get("reasoning") or "") if str(raw.get("reasoning") or "") in REASONING_LEVELS else "",          # 自訂工作說明（給這位 AI 的具體分工）
    }


MODEL_LIKE_NAME = re.compile(r"^(?=[a-z0-9._:\-]+$)(?=.*-)(?=.*(\d+(\.\d+)?b\b|-v\d|\d+\.\d+|:)).*$")   # 像模型名稱：有連字號與版本／大小


def fix_service_names(services):
    """名稱跟著模型：空白、「AI 3」或看起來是別的模型名稱（例如換了模型卻還叫舊模型名）時，改成目前模型的簡稱；
    同名的加上（2）（3）區分。使用者自己取的名字（例如「DeepSeek」「研究員」）不會動。回傳是否有改動。"""
    changed = False
    seen = {}
    for sv in services:
        model_short = (sv.get("model") or "").rstrip("/").split("/")[-1]
        name = (sv.get("name") or "").strip()
        base = re.sub(r"（\d+）$", "", name)
        if model_short and (not name or re.fullmatch(r"AI\s*\d+", name)
                            or (MODEL_LIKE_NAME.match(base) and base != model_short)):
            base = model_short
        count = seen.get(base, 0) + 1
        seen[base] = count
        new = base if count == 1 else f"{base}（{count}）"
        if new != name:
            sv["name"] = new
            changed = True
    return changed


def default_settings():
    url = f"https://{NVIDIA_HOST}/v1"
    services = [
        normalize_service({"name": "GLM", "role": "程式專家", "url": url, "model": "z-ai/glm-5.3-flash",
                           "credential_env": DEFAULT_NVIDIA_ENV}),
        normalize_service({"name": "DeepSeek", "role": "研究分析", "url": url, "model": "deepseek-ai/deepseek-v4.1-flash",
                           "credential_env": DEFAULT_NVIDIA_ENV}),
    ]
    prefs = dict(DEFAULT_PREFERENCES, hub_id=services[0]["id"])
    return {"version": SETTINGS_VERSION, "services": services, "removed_services": [],
            "templates": {}, "deleted_templates": {}, "preferences": prefs, "schedules": [], "removed_schedules": []}


def find_importable_settings():
    """打包的 exe 放在 dist/ 執行時，設定會存在 dist/ 自己這裡（與 AI協作.py 旁邊的不同）。
    第一次啟動、這裡還沒有設定檔時，找上一層（通常是程式資料夾）有沒有可以沿用的設定，回傳路徑或空字串。"""
    if os.path.exists(SETTINGS_PATH):
        return ""
    for up in (os.path.dirname(APP_DIR), os.path.dirname(os.path.dirname(APP_DIR))):
        cand = os.path.join(up, os.path.basename(SETTINGS_PATH))
        if os.path.normcase(cand) != os.path.normcase(SETTINGS_PATH) and os.path.isfile(cand):
            return cand
    return ""


def import_settings_from(src):
    """把別處的設定複製到這個資料夾（不覆蓋已存在的）。回傳是否成功。"""
    if os.path.exists(SETTINGS_PATH) or not os.path.isfile(src):
        return False
    try:
        with open(src, "r", encoding="utf-8") as f:
            data = json.load(f)
        save_settings_file(data)
        return True
    except (OSError, ValueError):
        return False


def load_settings_file(path=SETTINGS_PATH):
    """回傳 (設定 dict, 警告訊息或空字串)。讀不到時回傳預設值；壞掉的檔案會先備份再用預設值。"""
    if not os.path.exists(path):
        return default_settings(), ""
    try:
        with open(path, "r", encoding="utf-8") as source:
            data = json.load(source)
        if not isinstance(data, dict):
            raise TypeError("設定檔格式不是物件")
    except (OSError, ValueError, TypeError) as exc:
        saved = backup_file(path, reason="無法讀取")
        log.exception("讀取設定失敗")
        return default_settings(), f"讀取服務設定失敗，已改用預設值。\n原檔已備份到：{saved}\n{exc}"

    settings = default_settings()
    services = [s for s in (normalize_service(x) for x in data.get("services", []) or []) if s]
    if services or "services" in data:
        settings["services"] = services
    settings["removed_services"] = [s for s in (normalize_service(x) for x in data.get("removed_services", []) or []) if s]
    for item, raw in zip(settings["removed_services"], data.get("removed_services", []) or []):
        if isinstance(raw, dict):
            item["removed_at"] = str(raw.get("removed_at", ""))
    templates = data.get("templates", {})
    if isinstance(templates, dict):
        settings["templates"] = {str(k): str(v) for k, v in templates.items()}
    deleted = data.get("deleted_templates", {})
    if isinstance(deleted, dict):
        settings["deleted_templates"] = {str(k): v for k, v in deleted.items() if isinstance(v, dict)}
    for key in ("schedules", "removed_schedules"):
        settings[key] = [dict(x) for x in (data.get(key) or []) if isinstance(x, dict) and x.get("id")]
    prefs = dict(DEFAULT_PREFERENCES)
    if isinstance(data.get("preferences"), dict):
        prefs.update({k: v for k, v in data["preferences"].items() if k in DEFAULT_PREFERENCES})
    if prefs["mode"] not in MODES:
        prefs["mode"] = DEFAULT_PREFERENCES["mode"]
    if not any(s["id"] == prefs.get("hub_id") for s in settings["services"]):
        prefs["hub_id"] = settings["services"][0]["id"] if settings["services"] else ""
    if prefs.get("agent_model_id") and not any(s["id"] == prefs["agent_model_id"] for s in settings["services"]):
        prefs["agent_model_id"] = settings["services"][0]["id"] if settings["services"] else ""      # 指到已移除的 AI 時改用第一位
    settings["preferences"] = prefs
    return settings, ""


def backup_file(path, reason=""):
    """把檔案複製到「備份/設定/」，檔名加上時間。回傳備份路徑（失敗回傳空字串）。"""
    if not os.path.exists(path):
        return ""
    os.makedirs(SETTINGS_BACKUP_DIR, exist_ok=True)
    base, ext = os.path.splitext(os.path.basename(path))
    stamp = time.strftime("%Y%m%d_%H%M%S")
    suffix = f"_{reason}" if reason else ""
    target = os.path.join(SETTINGS_BACKUP_DIR, f"{base}_{stamp}{suffix}{ext}")
    counter = 1
    while os.path.exists(target):
        target = os.path.join(SETTINGS_BACKUP_DIR, f"{base}_{stamp}{suffix}_{counter}{ext}")
        counter += 1
    try:
        shutil.copy2(path, target)
        return target
    except OSError:
        log.exception("備份設定檔失敗")
        return ""


def settings_file_digest(path=SETTINGS_PATH):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return ""


SCHEDULE_RUN_FIELDS = ("last_run", "last_status", "next")


def merge_external_settings(ours, disk):
    """另一個程式（例如 Windows 排程啟動的那個）在這段時間改過設定檔時合併，避免互相覆蓋：
    模型與偏好以目前這個視窗為準；排程的執行狀態取較新的那一份；對方新增的排程保留。
    直接修改 ours 裡的排程（畫面與執行中的排程拿的是同一份），回傳說明清單。"""
    notes = []
    disk_sch = {s.get("id"): s for s in disk.get("schedules") or [] if isinstance(s, dict) and s.get("id")}
    for s in ours.setdefault("schedules", []):
        d = disk_sch.pop(s.get("id"), None)
        if d and (d.get("last_run") or "") > (s.get("last_run") or ""):
            for k in SCHEDULE_RUN_FIELDS:
                s[k] = d.get(k)
            if s.get("repeat") == "once" and d.get("enabled") is False:
                s["enabled"] = False
            notes.append(f"排程「{s.get('name')}」的執行紀錄用另一個視窗較新的版本")
    removed = ours.setdefault("removed_schedules", [])
    removed_ids = {r.get("id") for r in removed if isinstance(r, dict)}
    for d in disk_sch.values():
        if d.get("id") not in removed_ids:
            ours["schedules"].append(d)
            notes.append(f"保留另一個視窗新增的排程「{d.get('name')}」")
    for r in disk.get("removed_schedules") or []:
        if isinstance(r, dict) and r.get("id") not in removed_ids:
            removed.append(r)
            removed_ids.add(r.get("id"))
            ours["schedules"] = [s for s in ours["schedules"] if s.get("id") != r.get("id")]
    return notes


class InstanceLock:
    """同一個程式資料夾只讓一個程式「負責」排程與設定。用作業系統的檔案鎖：程式結束（含當機）時自動釋放。"""

    def __init__(self, path=None):
        self.path = path or os.path.join(LOG_DIR, "執行中.lock")
        self.f = None

    def acquire(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            f = open(self.path, "a+b")
        except OSError:
            return True                      # 建不了鎖檔就不要擋住使用者
        try:
            f.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            return False
        self.f = f
        return True

    def release(self):
        if not self.f:
            return
        try:
            self.f.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.f.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            self.f.close()
        except OSError:
            pass
        self.f = None


def save_settings_file(settings, path=SETTINGS_PATH):
    """寫入設定（先寫暫存檔再取代）。內容有變時先備份舊檔。失敗時丟出 OSError。"""
    data = dict(settings, version=SETTINGS_VERSION)
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as source:
                old = source.read()
        except OSError:
            old = None
        if old == text:
            return ""
        backup_file(path)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as output:
        output.write(text)
    safe_replace(tmp_path, path)
    return path


# ───────────────────────── 執行紀錄 ─────────────────────────
STATUS_LABELS = {"interrupted": "中斷（程式沒有正常結束，以下是已完成的部分）", "done": "完成", "partial": "完成（部分失敗）", "stopped": "已停止", "error": "失敗", "timeout": "逾時", "empty": "沒有內容",
                 "running": "執行中"}


def result_summary(result):
    if not result:
        return "未執行"
    label = STATUS_LABELS.get(result.get("status"), result.get("status", ""))
    if result.get("label") and result.get("status") not in ("done",):
        label += f"（{result['label']}）"
    parts = [label, f"耗時 {result.get('elapsed', 0):.1f} 秒"]
    if result.get("ttft") is not None:
        parts.append(f"首字 {result['ttft']:.1f} 秒")
    usage = result.get("usage") or {}
    if usage.get("completion_tokens"):
        parts.append(f"輸出 {usage['completion_tokens']} tokens")
    return "｜".join(parts)


def record_to_markdown(record):
    names = {a["id"]: f"{a['name']}（{a.get('role') or ''}｜{a.get('model') or ''}）" for a in record.get("agents", [])}
    hub = record.get("hub")
    if hub:
        names["__hub__"] = f"主持 AI：{hub.get('name')}（{hub.get('model')}）"
    lines = [f"# 多 AI 協作紀錄 — {record.get('started_at', '')}", "",
             f"- 模式：{record.get('mode')}",
             f"- 狀態：{STATUS_LABELS.get(record.get('status'), record.get('status'))}",
             f"- 結束時間：{record.get('finished_at', '')}",
             "- 參與 AI：" + "、".join(names.get(a["id"], a["name"]) for a in record.get("agents", [])), ""]
    if hub and record.get("mode") not in (MODE_PARALLEL, MODE_RELAY):
        lines.insert(-1, f"- 主持 AI：{hub.get('name')}（{hub.get('model')}）")
    header_end = len(lines) - 1
    if record.get("system_prompt"):
        lines += ["## 系統提示詞", "", record["system_prompt"], ""]
    lines += ["## 提示詞", "", record.get("prompt", ""), ""]
    usage = record.get("usage_total") or {}
    if usage:
        tok = usage.get("prompt", 0) + usage.get("completion", 0)
        line = f"- 用量：{usage.get('calls', 0)} 次呼叫、{tok:,} tokens"
        if usage.get("estimated"):
            line += f"（另有約 {usage['estimated']:,} 估算值，服務未回報用量）"
        lines.insert(header_end, line + (f"、總耗時 {record.get('elapsed', 0):.0f} 秒" if record.get("elapsed") else ""))
        header_end += 1
    if record.get("seed_round"):
        lines.insert(header_end, f"- 從第 {record['seed_round']} 輪的結果接續")
    if record.get("notes"):
        lines += ["## 使用者補充指示", ""] + [f"- {n}" for n in record["notes"]] + [""]
    final = record.get("final")
    if final and final.get("text"):
        lines += [f"## 最終成果（{final.get('name', '')}）", ""]
        if final.get("note"):
            lines += [f"> {final['note']}", ""]
        if final.get("disagreement"):
            lines += [f"> ⚠ 各 AI 的結論不一致：{final['disagreement']}", ""]
        if final.get("labels"):
            lines += ["> 代號對照：" + "、".join(f"回答 {k}＝{v}" for k, v in final["labels"].items()), ""]
        lines += [final["text"], ""]
    plan = record.get("plan")
    if plan:
        lines += ["## 主持 AI 的分工規劃", "", plan.get("text", ""), ""]
    for rnd in record.get("rounds", []):
        lines += [f"## 第 {rnd['round']} 輪：{rnd['label']}" if "接力" not in rnd["label"] else f"## {rnd['label']}", ""]
        if rnd.get("ranking"):
            ordered = sorted(rnd["ranking"].items(), key=lambda kv: kv[1][0])
            lines += ["**互評綜合名次**：" + " > ".join(f"{names.get(pid, pid)}（平均 {v[0]:.1f}）" for pid, v in ordered), ""]
        for pid, result in rnd.get("answers", {}).items():
            lines += [f"### {names.get(pid, pid)}", "", f"_{result_summary(result)}_", ""]
            if (rnd.get("tasks") or {}).get(pid):
                lines += [f"> 子任務：{rnd['tasks'][pid]}", ""]
            if (rnd.get("anon") or {}).get(pid):
                lines += ["> 本輪看到的匿名代號：" + "、".join(f"{k}＝{names.get(v, v)}" for k, v in rnd["anon"][pid].items()), ""]
            if result.get("text"):
                lines += [result["text"], ""]
            if result.get("error"):
                lines += [f"> 錯誤：{result['error']}", ""]
    hub_result = record.get("hub_result")
    if hub_result:
        lines += ["## 主持 AI 彙整", "", f"_{result_summary(hub_result)}_", ""]
        if hub_result.get("error"):
            lines += [f"> 錯誤：{hub_result['error']}", ""]
    if record.get("error"):
        lines += [f"> 結果：{record['error']}", ""]
    if record.get("timeline"):
        lines += ["## 時間軸", ""]
        for secs, who, text in record["timeline"]:
            lines.append(f"- {secs:>6.1f} 秒｜{names.get(who, who)}｜{text}")
        lines.append("")
    partial = record.get("partial_answers") or {}
    if partial and record.get("status") in ("running", "interrupted"):
        lines += ["", "## 中斷前已完成的回答", ""]
        for item in partial.values():
            lines += [f"### {item.get('name')}（{item.get('note') or ''}）", "", item.get("text") or "（沒有內容）", ""]
    return "\n".join(lines)


UI_STATE_PATH = os.path.join(APP_DIR, "AI協作介面狀態.json")


def load_ui_state():
    """視窗大小、位置、分隔線位置等（獨立小檔，不影響設定檔與其備份）。"""
    try:
        with open(UI_STATE_PATH, "r", encoding="utf-8") as source:
            data = json.load(source)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_ui_state(state):
    tmp = UI_STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as output:
        json.dump(state, output, ensure_ascii=False, indent=2)
    safe_replace(tmp, UI_STATE_PATH)


def safe_filename(text):
    return re.sub(r'[<>:"/\\|?*\s]+', "_", text or "").strip("_") or "紀錄"


def new_record_base(mode, folder=RECORDS_DIR):
    """一次討論的紀錄檔名（不含副檔名）。開始時就決定好，中途存檔與最後存檔寫同一個檔，不留多餘檔案。"""
    os.makedirs(folder, exist_ok=True)
    base = os.path.join(folder, f"{time.strftime('%Y%m%d_%H%M%S')}_{safe_filename(mode)}")
    path, counter = base, 1
    while os.path.exists(path + ".md") or os.path.exists(path + ".json"):
        path = f"{base}_{counter}"
        counter += 1
    return path


def _write_text_atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as output:
        output.write(text)
    safe_replace(tmp, path)


def save_record(record, folder=RECORDS_DIR, base=None):
    """把一次執行存成 .md 與 .json（先寫暫存檔再取代）。給 base 時寫到那個固定檔名（中途存檔用）。回傳 .md 路徑。"""
    path = base or new_record_base(record.get("mode"), folder)
    _write_text_atomic(path + ".md", record_to_markdown(record))
    _write_text_atomic(path + ".json", json.dumps(record, ensure_ascii=False, indent=2, default=str))
    return path + ".md"


def pid_alive(pid):
    """這個行程還在不在（用來判斷「執行中」的紀錄是不是當機留下的）。"""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            k32 = ctypes.windll.kernel32
            handle = k32.OpenProcess(0x1000, False, pid)            # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return False
            code = ctypes.c_ulong()
            ok = k32.GetExitCodeProcess(handle, ctypes.byref(code))
            k32.CloseHandle(handle)
            return bool(ok) and code.value == 259                    # STILL_ACTIVE
        except Exception:
            return True                                              # 判斷不了就當作還在，不要誤標
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    try:                                     # 已經結束、只是還沒被回收的殭屍程序（Linux）不算還在
        with open(f"/proc/{pid}/stat", "r") as f:
            return f.read().rsplit(")", 1)[-1].split()[0] != "Z"
    except (OSError, IndexError):
        return True


def find_interrupted_records(folder=RECORDS_DIR, days=14):
    """找出上次沒有正常結束的討論（中途存檔的狀態還是「執行中」、而且那個程式已經不在了），
    把狀態改成「中斷」並更新 .md，回傳 .md 路徑清單。不刪除任何東西。"""
    out = []
    try:
        names = [n for n in os.listdir(folder) if n.endswith(".json")]
    except OSError:
        return out
    limit = time.time() - days * 86400
    for n in names:
        path = os.path.join(folder, n)
        try:
            if os.path.getmtime(path) < limit:
                continue
            with open(path, encoding="utf-8") as f:
                rec = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(rec, dict) or rec.get("status") != "running" or pid_alive(rec.get("pid")):
            continue
        rec["status"] = "interrupted"
        try:
            save_record(rec, base=path[:-5])
            out.append(path[:-5] + ".md")
        except OSError:
            pass
    return out


def keep_awake(on):
    """執行中請 Windows 不要進入睡眠（螢幕仍會照設定關閉）；結束時恢復。必須在同一個執行緒呼叫。"""
    if os.name != "nt":
        return
    try:
        import ctypes
        flags = 0x80000000 | (0x00000001 if on else 0)                 # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
        ctypes.windll.kernel32.SetThreadExecutionState(flags)
    except Exception:
        pass


def list_records(folder=RECORDS_DIR):
    if not os.path.isdir(folder):
        return []
    files = [f for f in os.listdir(folder) if f.lower().endswith(".md")]
    return sorted(files, reverse=True)


# ───────────────────────── 附加檔案 ─────────────────────────
def read_attachment(path, limit=MAX_ATTACH_BYTES):
    """讀取文字檔，回傳 (文字, 警告)。自動嘗試 UTF-8 與 Big5（cp950）。"""
    size = os.path.getsize(path)
    with open(path, "rb") as source:
        raw = source.read(limit)
    warning = f"檔案 {size:,} 位元組，超過上限，只附加前 {limit:,} 位元組。" if size > limit else ""
    if b"\x00" in raw[:4096]:
        raise ValueError("這看起來是二進位檔（例如圖片、Office 檔），只能附加文字檔。")
    for encoding in ("utf-8-sig", "cp950"):
        try:
            return raw.decode(encoding), warning
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), (warning + " 部分字元無法辨識。").strip()


def format_attachment(path, text):
    ext = os.path.splitext(path)[1].lstrip(".").lower()
    lang = {"py": "python", "js": "javascript", "ts": "typescript", "md": "markdown", "ps1": "powershell",
            "cs": "csharp", "sh": "bash", "yml": "yaml"}.get(ext, ext)
    return f"\n【附加檔案：{os.path.basename(path)}】\n```{lang}\n{text.rstrip()}\n```\n"


# ───────────────────────── 日誌 ─────────────────────────
def setup_logging():
    """日誌寫到「日誌/多AI工作台_年月.log」，每月一個檔，不自動刪除。"""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        path = os.path.join(LOG_DIR, f"AI協作_{time.strftime('%Y%m')}.log")
        handler = logging.FileHandler(path, encoding="utf-8")
    except OSError:
        handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s：%(message)s"))
    root = logging.getLogger("ai_collab")
    if not root.handlers:
        root.addHandler(handler)
    root.setLevel(logging.INFO)
    return root

