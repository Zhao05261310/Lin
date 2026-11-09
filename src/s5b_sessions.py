
# ───────────────────────── 對話（工作階段）存檔 ─────────────────────────
SESSIONS_DIR = os.path.join(APP_DIR, "工作階段")


def new_session(kind, workspace="", model_id=""):
    return {"id": time.strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:4], "type": kind, "title": "新對話",
            "created": time.strftime("%Y-%m-%d %H:%M:%S"), "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "workspace": workspace, "model_id": model_id, "mode": "build", "messages": [], "display": [],
            "changes": [], "todos": [], "council_history": [], "turn": 0, "usage": {}}


def save_session(session):
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    session["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    path = os.path.join(SESSIONS_DIR, session["id"] + ".json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(session, f, ensure_ascii=False, indent=1, default=str)
    safe_replace(tmp, path)
    return path


def load_session(session_id):
    with open(os.path.join(SESSIONS_DIR, session_id + ".json"), "r", encoding="utf-8") as f:
        return json.load(f)


def list_sessions():
    """回傳 [(id, 標題, 類型, 更新時間)]，新的在前。封存的不列出。"""
    if not os.path.isdir(SESSIONS_DIR):
        return []
    out = []
    for name in os.listdir(SESSIONS_DIR):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(SESSIONS_DIR, name), "r", encoding="utf-8") as f:
                data = json.load(f)
            out.append((data["id"], data.get("title") or "未命名", data.get("type", "agent"), data.get("updated", "")))
        except (OSError, ValueError, KeyError):
            continue
    return sorted(out, key=lambda x: x[3], reverse=True)


def archive_session(session_id):
    """封存（移到 工作階段/封存/，不刪除）。"""
    src = os.path.join(SESSIONS_DIR, session_id + ".json")
    dst_dir = os.path.join(SESSIONS_DIR, "封存")
    os.makedirs(dst_dir, exist_ok=True)
    if os.path.exists(src):
        shutil.move(src, os.path.join(dst_dir, session_id + ".json"))


def search_sessions(query, limit=200):
    """在標題與對話內容中搜尋（不分大小寫）。回傳格式同 list_sessions。"""
    q = (query or "").strip().lower()
    if not q:
        return list_sessions()[:limit]
    if not os.path.isdir(SESSIONS_DIR):
        return []
    out = []
    for name in os.listdir(SESSIONS_DIR):
        if not name.endswith(".json"):
            continue
        path = os.path.join(SESSIONS_DIR, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read()
            data = json.loads(raw)
        except (OSError, ValueError):
            continue
        title = data.get("title") or "未命名"
        if q in title.lower() or q in json.dumps(data.get("display", []), ensure_ascii=False).lower():
            out.append((data.get("id", name[:-5]), title, data.get("type", "agent"), data.get("updated", "")))
    return sorted(out, key=lambda x: x[3], reverse=True)[:limit]


def session_to_markdown(session):
    """把一個對話（Agent 或 AI 討論）轉成 Markdown 文字。"""
    kind = "Agent" if session.get("type") == "agent" else "AI 討論"
    lines = [f"# {session.get('title') or '對話'}", "",
             f"- 類型：{kind}", f"- 建立：{session.get('created', '')}　更新：{session.get('updated', '')}"]
    if session.get("workspace"):
        lines.append(f"- 工作資料夾：`{session['workspace']}`")
    lines.append("")
    for item in session.get("display") or []:
        kind_ = item[0] if item else ""
        if kind_ == "user":
            lines += ["## 你", "", str(item[1]), ""]
        elif kind_ == "assistant":
            who = item[2] if len(item) > 2 else "Agent"
            lines += [f"## {who}", "", str(item[1]), ""]
        elif kind_ == "tool":
            _k, name, title, ok, output = (list(item) + [""] * 5)[:5]
            lines += [f"<details><summary>{'✓' if ok else '✗'} 工具：{title}</summary>", "", "```",
                      str(output).rstrip()[:6000], "```", "", "</details>", ""]
        elif kind_ in ("notice", "error"):
            lines += [f"> {item[1]}", ""]
        elif kind_ == "council":
            rec = item[1] if len(item) > 1 and isinstance(item[1], dict) else {}
            names = {a.get("id"): a.get("name") for a in rec.get("agents") or []}
            lines += [f"## AI 討論（{rec.get('mode', '')}，{len(names)} 位 AI）", ""]
            research = rec.get("research") or {}
            if research.get("sources"):
                lines += ["**上網查到的來源：** " + "、".join(research["sources"]), ""]
            final = (rec.get("final") or {}).get("text")
            if final:
                main, contrib = split_final(final)
                lines += ["### 最終成果", "", main, ""]
                if (rec.get("final") or {}).get("disagreement"):
                    lines += [f"> ⚠ 各 AI 的結論不一致：{rec['final']['disagreement']}", ""]
                if contrib:
                    lines += ["<details><summary>各回答的貢獻與分歧</summary>", "", contrib, "", "</details>", ""]
            for rnd in rec.get("rounds") or []:
                lines += [f"<details><summary>第 {rnd.get('round')} 輪：{rnd.get('label', '')}</summary>", ""]
                for pid, res in (rnd.get("answers") or {}).items():
                    lines += [f"#### {names.get(pid, pid)}", "", str(res.get("text") or res.get("error") or ""), ""]
                lines += ["</details>", ""]
    return "\n".join(lines).rstrip() + "\n"


# ───────────────────────── 排程 ─────────────────────────
REPEATS = {"once": "只執行一次", "hourly": "每小時", "daily": "每天", "weekly": "每週"}
WEEKDAY_NAMES = ["一", "二", "三", "四", "五", "六", "日"]
SCHTASK_DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


LANG_DEFAULT = {"python": "main.py", "py": "main.py", "javascript": "index.js", "js": "index.js",
                "typescript": "index.ts", "html": "index.html", "css": "style.css", "json": "data.json",
                "bash": "run.sh", "sh": "run.sh", "java": "Main.java", "c": "main.c", "cpp": "main.cpp",
                "go": "main.go", "rust": "main.rs", "rs": "main.rs", "sql": "schema.sql", "yaml": "config.yaml",
                "yml": "config.yaml", "markdown": "README.md", "md": "README.md", "text": "README.md"}
_PATH = re.compile(r"([A-Za-z0-9_.\-/\\]+\.[A-Za-z0-9]{1,6})")
_COMMENT_FIRST = re.compile(r"^\s*(?:#|//|--|<!--|/\*|;)?\s*(?:file|filename|檔名|檔案)?\s*[:：]?\s*([A-Za-z0-9_.\-/\\]+\.[A-Za-z0-9]{1,6})")


def _name_from_context(before_lines):
    for line in reversed(before_lines):
        line = line.strip().strip("*`#").strip()
        if not line or len(line) > 120:
            continue
        m = _PATH.search(line)
        if m and "." in m.group(1) and not m.group(1).startswith("."):
            cand = m.group(1).replace("\\", "/")
            if not re.match(r"^\d", cand) and " " not in cand:
                return cand.lstrip("/")
        if line and not m:
            break
    return ""


def _name_from_code(code, lang):
    first = code.splitlines()[:3]
    for line in first:
        m = _COMMENT_FIRST.match(line)
        if m:
            return m.group(1).replace("\\", "/").lstrip("/")
    return ""


CODE_LANGS = {"python","py","javascript","js","typescript","ts","html","css","json","java","c","cpp","c++","go",
              "rust","rs","sql","yaml","yml","php","ruby","rb","sh","bash","shell","kotlin","swift","scala","r",
              "xml","toml","ini","dockerfile","makefile","vue","jsx","tsx"}
_LOOKS_CODE = re.compile(r"(^#!|^\s*(import|from|def |class |function |const |let |var |package |public |private |"
                         r"#include|using |namespace|export |module|require\(|async |await |print\(|console\.|"
                         r"<\?php|<!DOCTYPE|<html|<\?xml|SELECT |CREATE |INSERT )|[{};]\s*$|=>|\)\s*:\s*$)",
                         re.I | re.M)


def _looks_like_code(code):
    return bool(_LOOKS_CODE.search(code))


KEEP_EXTS = {".txt", ".md", ".cfg", ".toml", ".ini", ".env", ".yaml", ".yml", ".csv", ".gitignore", ".bat"}
KEEP_NAMES = {"requirements.txt", "package.json", "dockerfile", "makefile", ".gitignore", ".env", ".env.example"}


def extract_code_project(text, max_files=20):
    """從 Markdown 文字抽出程式專案：回傳 [{"name","code","lang"}]。檔名取自程式碼區塊前的標題/路徑，或區塊內首行註解；
    都沒有時依語言給預設名。同名後出現的覆蓋前面的（模型常附「修正版」）。"""
    if not text:
        return []
    files = {}
    order = []
    pos = 0
    pattern = re.compile(r"```([^\n`]*)\n(.*?)```", re.DOTALL)
    used_default = set()
    lines = text.split("\n")
    # 以行為單位找出每個 code fence 的前文
    for m in pattern.finditer(text):
        info = (m.group(1) or "").strip().lower()
        code = m.group(2)
        if not code.strip():
            continue
        lang = re.split(r"[\s:]", info)[0] if info else ""
        before = text[:m.start()].split("\n")[-4:]
        name = _name_from_context(before) or _name_from_code(code, lang)
        if not name:
            # 標在 fence info 上，例如 ```python title=app.py
            m2 = _PATH.search(info)
            if m2:
                name = m2.group(1)
        if not name:
            if lang in ("", "text", "txt", "console", "shell", "output", "bash") and "python" not in info:
                continue  # 疑似終端輸出或純文字，不是檔案
            base = LANG_DEFAULT.get(lang, (lang or "file") + ".txt")
            if base in used_default:
                root, ext = os.path.splitext(base)
                base = f"{root}_{len(used_default)}{ext}"
            used_default.add(base)
            name = base
        name = name.strip().lstrip("/")
        if len(name) > 100 or ".." in name:
            continue
        base = name.rsplit("/", 1)[-1].lower()
        ext = os.path.splitext(base)[1]
        keep_doc = base in KEEP_NAMES or ext in KEEP_EXTS
        if lang not in CODE_LANGS and not _looks_like_code(code) and not keep_doc:
            continue                                  # 沒有程式語言標記、內容也不像程式碼、也不是已知設定/說明檔：跳過
        if name not in files:
            order.append(name)
        files[name] = {"name": name, "code": code.rstrip() + "\n", "lang": lang}
    return [files[n] for n in order]


def new_schedule():
    now = _dt.datetime.now() + _dt.timedelta(minutes=5)
    return {"id": "s" + uuid.uuid4().hex[:8], "name": "新排程", "enabled": True, "kind": "agent", "prompt": "",
            "workspace": "", "repeat": "daily", "time": now.strftime("%H:%M"), "date": now.strftime("%Y-%m-%d"),
            "weekdays": [now.weekday()], "approval": "deny", "close_after": True, "next": None,
            "last_run": "", "last_status": "", "windows_task": False, "on_battery": True}


def _parse_hhmm(text):
    m = re.match(r"^\s*(\d{1,2})[:：](\d{2})\s*$", text or "")
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ValueError("時間格式要像 08:30")
    return int(m.group(1)), int(m.group(2))


def next_run_time(sch, after=None):
    """回傳下一次執行的時間（datetime），沒有下一次就回傳 None。"""
    after = after or _dt.datetime.now()
    hh, mm = _parse_hhmm(sch.get("time", ""))
    repeat = sch.get("repeat", "daily")
    if repeat == "once":
        try:
            day = _dt.datetime.strptime(sch.get("date", ""), "%Y-%m-%d")
        except ValueError:
            raise ValueError("日期格式要像 2026-10-25")
        when = day.replace(hour=hh, minute=mm)
        return when if when > after else None
    if repeat == "hourly":
        when = after.replace(minute=mm, second=0, microsecond=0)
        return when if when > after else when + _dt.timedelta(hours=1)
    base = after.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if repeat == "daily":
        return base if base > after else base + _dt.timedelta(days=1)
    days = sorted({int(d) % 7 for d in (sch.get("weekdays") or [])}) or [after.weekday()]
    for offset in range(0, 8):
        when = base + _dt.timedelta(days=offset)
        if when.weekday() in days and when > after:
            return when
    return None


def describe_schedule(sch):
    rep = sch.get("repeat", "daily")
    if rep == "once":
        when = f"{sch.get('date')} {sch.get('time')}"
    elif rep == "hourly":
        when = f"每小時的第 {sch.get('time', '00:00').split(':')[-1]} 分"
    elif rep == "weekly":
        when = "每週" + "、".join(WEEKDAY_NAMES[int(d) % 7] for d in sorted(sch.get("weekdays") or [])) + f" {sch.get('time')}"
    else:
        when = f"每天 {sch.get('time')}"
    return f"{when}・{'Agent' if sch.get('kind') == 'agent' else 'AI 討論'}"


def schtasks_date(date_text, pattern=None):
    """schtasks /SD 要用系統的短日期格式（例如 zh-TW 是 yyyy/M/d）。"""
    day = _dt.datetime.strptime(date_text, "%Y-%m-%d")
    if pattern is None and sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\International") as k:
                pattern = winreg.QueryValueEx(k, "sShortDate")[0]
        except OSError:
            pattern = None
    pattern = pattern or "yyyy/MM/dd"
    if re.search(r"ddd|MMM|[^yMd/\-. ]", pattern):
        pattern = "yyyy/MM/dd"
    out = pattern
    for token, value in (("yyyy", f"{day.year:04d}"), ("yy", f"{day.year % 100:02d}"), ("MM", f"{day.month:02d}"),
                         ("M", str(day.month)), ("dd", f"{day.day:02d}"), ("d", str(day.day))):
        out = out.replace(token, "\0" + value + "\0")       # 用標記避免已替換的數字再被處理
    return out.replace("\0", "")


SCHEDULE_INBOX = os.path.join(LOG_DIR, "排程請求")


def check_windows_task_paths(schedules):
    """檢查已登錄到 Windows 工作排程器的排程，指向的程式／Python 路徑是否還存在（搬過資料夾或換環境後常失效）。
    回傳 [(排程, 問題說明)]；只在 Windows 上有意義。"""
    if os.name != "nt":
        return []
    problems = []
    for sch in schedules:
        if not sch.get("windows_task") or not sch.get("enabled", True):
            continue
        try:
            name, args = windows_task_command(sch, os.path.abspath(APP_DIR + os.sep + "AI協作.py"))
            q = subprocess.run(["schtasks", "/Query", "/TN", name, "/FO", "LIST", "/V"], capture_output=True,
                               text=True, encoding="cp950", errors="replace", timeout=15,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            continue
        if q.returncode != 0:
            problems.append((sch, "Windows 工作排程器裡找不到這個排程（可能被移除）"))
            continue
        for line in q.stdout.splitlines():
            m = re.search(r'"([A-Za-z]:\\[^"]+\.exe)"', line)
            if m and not os.path.exists(m.group(1)):
                problems.append((sch, f"排程指向的程式不存在：{m.group(1)}（可能搬過資料夾或換過 Python 環境）"))
                break
    return problems


def post_schedule_request(sid, inbox=None):
    """Windows 排程啟動時，如果程式已經開著，就把「請執行排程 sid」交給開著的那一個（避免執行兩次、互相覆蓋設定）。"""
    inbox = inbox or SCHEDULE_INBOX
    os.makedirs(inbox, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(inbox, f"{re.sub(r'[^0-9A-Za-z_-]', '_', sid)}_{stamp}_{uuid.uuid4().hex[:4]}.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"id": sid, "time": _dt.datetime.now().isoformat(timespec="seconds")}, f, ensure_ascii=False)
    safe_replace(tmp, path)
    return path


def take_schedule_requests(inbox=None):
    """取出待執行的排程請求，回傳 [(檔案路徑, 排程 id)]（舊的在前）。"""
    inbox = inbox or SCHEDULE_INBOX
    try:
        names = sorted(n for n in os.listdir(inbox) if n.endswith(".json"))
    except OSError:
        return []
    out = []
    for n in names:
        path = os.path.join(inbox, n)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            out.append((path, str(data.get("id") or "")))
        except (OSError, ValueError):
            continue
    return out


def finish_schedule_request(path, inbox=None):
    """處理完的請求移到「已處理」（不刪除）。"""
    done = os.path.join(inbox or SCHEDULE_INBOX, "已處理")
    try:
        os.makedirs(done, exist_ok=True)
        os.replace(path, os.path.join(done, os.path.basename(path)))
    except OSError:
        pass


def windows_battery_command(task_name, allow=True):
    """Windows 預設「用電池時不啟動、改用電池就停止」，筆電沒插電時排程會悄悄不執行。
    用 PowerShell 改這個工作的電源條件（schtasks 指令本身沒有這個選項）。回傳指令參數清單。"""
    folder, _sep, leaf = task_name.rpartition("\\")
    q = lambda s: "'" + s.replace("'", "''") + "'"
    flag = "$false" if allow else "$true"
    script = (f"$t = Get-ScheduledTask -TaskPath {q(chr(92) + folder + chr(92))} -TaskName {q(leaf)}; "
              f"$t.Settings.DisallowStartIfOnBatteries = {flag}; $t.Settings.StopIfGoingOnBatteries = {flag}; "
              "Set-ScheduledTask -InputObject $t | Out-Null")
    return ["powershell", "-NoProfile", "-NonInteractive", "-Command", script]


DATA_FOLDERS = ("工作階段", "紀錄", "日誌", "備份", "dist", "build")


def folder_sizes(base=None):
    """各資料夾佔用的空間（位元組），讓使用者知道哪裡在長大。"""
    base = base or APP_DIR
    out = {}
    for name in DATA_FOLDERS:
        total = 0
        for root, _dirs, files in os.walk(os.path.join(base, name)):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        out[name] = total
    return out


def archive_old_files(folder, days=90, now=None, skip=()):
    """把資料夾第一層、超過 days 天沒改過的檔案移到「封存/年月」（不刪除）。回傳移動的檔案數。
    紀錄的 .md 與 .json 是同名一組，會一起移。"""
    now = now or time.time()
    try:
        names = os.listdir(folder)
    except OSError:
        return 0
    moved = 0
    for n in names:
        src = os.path.join(folder, n)
        if not os.path.isfile(src) or n.endswith((".tmp", ".lock")) or n in skip:
            continue
        try:
            mtime = os.path.getmtime(src)
        except OSError:
            continue
        if now - mtime < days * 86400:
            continue
        dest_dir = os.path.join(folder, "封存", time.strftime("%Y%m", time.localtime(mtime)))
        try:
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, n)
            if os.path.exists(dest):
                root, ext = os.path.splitext(n)
                dest = os.path.join(dest_dir, f"{root}_{int(mtime)}{ext}")
            os.replace(src, dest)
            moved += 1
        except OSError:
            continue
    return moved


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def windows_task_command(sch, script_path, python_exe=None):
    """組出 schtasks 建立工作的參數（程式沒開時也會由 Windows 啟動並執行這個排程）。"""
    exe = python_exe or sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(pyw) and not FROZEN:
        exe = pyw
    name = "AI協作\\" + re.sub(r'[\\/:*?"<>|]', "_", sch.get("name") or sch["id"])[:60] + "_" + sch["id"]
    hh, mm = _parse_hhmm(sch.get("time", ""))
    args = ["schtasks", "/Create", "/F", "/TN", name,
            "/TR", (f'"{exe}" --run-schedule {sch["id"]}' if FROZEN else
                    f'"{exe}" "{os.path.abspath(script_path)}" --run-schedule {sch["id"]}'), "/ST", f"{hh:02d}:{mm:02d}"]
    rep = sch.get("repeat", "daily")
    if rep == "once":
        args += ["/SC", "ONCE", "/SD", schtasks_date(sch.get("date", ""))]
    elif rep == "hourly":
        args += ["/SC", "HOURLY"]
    elif rep == "weekly":
        args += ["/SC", "WEEKLY", "/D", ",".join(SCHTASK_DAYS[int(d) % 7] for d in sorted(sch.get("weekdays") or [0]))]
    else:
        args += ["/SC", "DAILY"]
    return name, args


# ───────────────────────── 更新 ─────────────────────────
def source_version(text):
    m = re.search(r'^APP_VERSION\s*=\s*"([\d.]+)"', text or "", re.M)
    return m.group(1) if m else ""


def version_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "0"))


def apply_update(new_text, target=None, expected_sha256=None):
    """用新版的 AI協作.py 取代目前的程式：先檢查 SHA-256（有給的話）、語法與版本號，舊檔備份到 備份/更新前_v版本_時間/，再寫入。"""
    target = target or os.path.join(APP_DIR, "AI協作.py")
    if expected_sha256:
        verify_update_hash(new_text, expected_sha256)
    version = source_version(new_text)
    if not version:
        raise ValueError("這不是 AI協作.py（找不到 APP_VERSION）")
    compile(new_text, "AI協作.py", "exec")            # 語法有錯就不更新
    if version_tuple(version) <= version_tuple(APP_VERSION):
        raise ValueError(f"新檔的版本 {version} 沒有比目前的 {APP_VERSION} 新")
    # 備份放在被更新的檔案旁邊（原本固定放程式資料夾，自我測試會在使用者的資料夾留下測試用的備份）
    backup_dir = os.path.join(os.path.dirname(os.path.abspath(target)), "備份",
                              f"更新前_v{APP_VERSION}_{time.strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(backup_dir, exist_ok=True)
    if os.path.exists(target):
        shutil.copy2(target, os.path.join(backup_dir, os.path.basename(target)))
    tmp = target + ".new"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(new_text)
    safe_replace(tmp, target)
    return version, backup_dir


def fetch_update(url, timeout=30):
    if not re.match(r"^https?://", url or ""):
        raise ValueError("更新網址要用 http:// 或 https:// 開頭（例如 GitHub 的 raw 檔案網址）")
    if url.lower().startswith("http://") and not _is_local_or_private_url(url):
        raise ValueError("更新檔要用 https:// 下載（http:// 沒有加密，途中可能被換成惡意程式）")
    req = urllib.request.Request(url, headers={"User-Agent": "AI-Workbench/" + APP_VERSION})   # 標頭只能用 ASCII
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        final = resp.geturl() or url
        if final.lower().startswith("http://") and not _is_local_or_private_url(final):
            raise ValueError("更新網址被轉到未加密的 http://，可能被換成惡意程式，已停止")    # v6.11
        return resp.read(5_000_000).decode("utf-8")
