

# ═════════════════════════ 3e. v6.11：安全強化與新功能的核心（不含畫面） ═════════════════════════
# 程序樹、沙盒執行、連線鎖定 IP（防 DNS rebinding）、更新檔雜湊、用量與預算、Git 分支隔離、
# 匯出 HTML／PDF／GitHub Issue、範本與角色匯入匯出、搜尋過去的對話、剪貼簿圖片與錄音。

import functools
import hmac
import http.client
import socket
import tempfile

# ───────────────────────── 1. 程序樹：逾時、停止、結束時把所有子程序一起結束 ─────────────────────────
# v6.10.2 壓測：「sleep 30 &」這類背景程序在逾時、按停止後還繼續跑（原本只結束了 shell 本身）。


def _win_job_create():
    """Windows：建立 Job Object（之後把程序放進去，TerminateJobObject 會連子程序一起結束）。失敗回傳 None。"""
    if os.name != "nt":
        return None
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.CreateJobObjectW.restype = ctypes.c_void_p
        job = k32.CreateJobObjectW(None, None)
        return job or None
    except Exception:
        return None


def _win_job_active(job):
    """Job 裡還在執行的程序數；查不到回傳 -1。"""
    try:
        import ctypes

        class _Acct(ctypes.Structure):
            _fields_ = [("TotalUserTime", ctypes.c_int64), ("TotalKernelTime", ctypes.c_int64),
                        ("ThisPeriodTotalUserTime", ctypes.c_int64), ("ThisPeriodTotalKernelTime", ctypes.c_int64),
                        ("TotalPageFaultCount", ctypes.c_uint32), ("TotalProcesses", ctypes.c_uint32),
                        ("ActiveProcesses", ctypes.c_uint32), ("TotalTerminatedProcesses", ctypes.c_uint32)]
        info = _Acct()
        ok = ctypes.windll.kernel32.QueryInformationJobObject(ctypes.c_void_p(job), 1, ctypes.byref(info),
                                                               ctypes.sizeof(info), None)
        return int(info.ActiveProcesses) if ok else -1
    except Exception:
        return -1


class ProcessTree:
    """啟動一個指令，並把它和之後產生的所有子程序綁在一起（Windows：Job Object；其他：獨立的程序群組）。"""

    def __init__(self, command, cwd, env, shell=True, capture=True):
        # Windows：先用「暫停」狀態建立程序，放進 Job 之後才讓它開始跑。
        # v6.11 自動測試（Windows）：沒暫停時，cmd 在放進 Job 之前就把 start /b 的子程序開好了，子程序不在 Job 裡、結束不了。
        self.job = _win_job_create()
        suspended = 0x00000004 if self.job else 0                  # CREATE_SUSPENDED
        kw = ({"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0) | suspended} if os.name == "nt"
              else {"start_new_session": True})
        out = subprocess.PIPE if capture else subprocess.DEVNULL     # 不讀輸出時一定要丟掉，不然管線塞滿程序會卡住
        self.proc = subprocess.Popen(command, shell=shell, cwd=cwd, stdout=out, stderr=subprocess.STDOUT if capture else out,
                                     stdin=subprocess.DEVNULL, env=env, **kw)
        if self.job:
            try:
                import ctypes
                handle = ctypes.c_void_p(int(self.proc._handle))
                if not ctypes.windll.kernel32.AssignProcessToJobObject(ctypes.c_void_p(self.job), handle):
                    self.close()
            except Exception:
                self.close()
            finally:
                try:
                    import ctypes
                    ctypes.windll.ntdll.NtResumeProcess(ctypes.c_void_p(int(self.proc._handle)))   # 不論成敗都要讓它跑
                except Exception:
                    pass

    def leftovers(self):
        """主程序結束後，樹裡還活著的子程序數（0＝沒有；-1＝不知道）。"""
        if os.name == "nt":
            if not self.job:
                return -1
            n = _win_job_active(self.job)
            return n
        try:
            os.killpg(self.proc.pid, 0)
            return 1
        except (ProcessLookupError, PermissionError):
            return 0
        except OSError:
            return -1

    def kill(self):
        """結束整個程序樹（含背景子程序）。"""
        if os.name == "nt":
            done = False
            if self.job:
                try:
                    import ctypes
                    done = bool(ctypes.windll.kernel32.TerminateJobObject(ctypes.c_void_p(self.job), 1))
                except Exception:
                    done = False
            if not done:
                try:
                    subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.proc.pid)], capture_output=True, timeout=15,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                except (OSError, subprocess.SubprocessError):
                    pass
        else:
            import signal
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
        try:
            self.proc.kill()
        except OSError:
            pass

    def close(self):
        if self.job:
            try:
                import ctypes
                ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(self.job))
            except Exception:
                pass
            self.job = None


def kill_process_tree(proc):
    """結束 Popen 建立的程序與它的子程序（MCP、CLI 停止時用）。"""
    if proc is None:
        return
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        import signal
        try:
            if os.getpgid(proc.pid) == proc.pid:          # 自己是群組長（start_new_session）才整組結束
                os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    try:
        proc.kill()
    except OSError:
        pass


def run_process_tree(command, cwd, env, timeout=120, cancel=None, cap=4_000_000, shell=True):
    """執行指令並收集輸出（只保留前 cap 位元組）。逾時、取消或指令結束後還留著背景程序時，整個程序樹都結束。
    回傳 (輸出文字, 狀態文字或 None, 結束代碼, 耗時, 備註)。"""
    tree = ProcessTree(command, cwd, env, shell=shell)
    proc = tree.proc
    out_chunks, total = [], [0]

    def reader():
        try:
            for chunk in iter(lambda: proc.stdout.read(65536), b""):
                total[0] += len(chunk)
                if total[0] - len(chunk) < cap:
                    out_chunks.append(chunk)
        except (OSError, ValueError):
            pass

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    started = time.monotonic()
    status, note = None, ""
    while proc.poll() is None:
        if cancel is not None and cancel.is_set():
            status = "已停止"
            break
        if time.monotonic() - started > timeout:
            status = f"逾時（{timeout} 秒）"
            break
        time.sleep(0.1)
    if status is None:
        t.join(0.5)
        # 主程序結束了，輸出管線卻還被佔著＝有子程序在背景繼續跑（Job 不能用時的第二層判斷）
        if tree.leftovers() > 0 or t.is_alive():
            note = "指令結束時還有背景程序在執行（例如用 & 或 start 啟動的），已一併結束，避免在你不知道的情況下繼續跑。"
    if status is not None or note:
        tree.kill()
    t.join(3)
    tree.close()
    output = _decode(b"".join(out_chunks)[:cap])
    if total[0] > cap:
        output += f"\n…（輸出共 {total[0]:,} 位元組，只保留前 {cap:,}）"
    return output, status, proc.returncode, time.monotonic() - started, note


# ───────────────────────── 2. 沙盒：指令在工作資料夾的暫存複本裡執行，看過再套回 ─────────────────────────
SANDBOX_SKIP = {".git", AGENT_DIR_NAME, "__pycache__"}
SANDBOX_MAX_FILES = 60000
SANDBOX_MAX_BYTES = 1_500_000_000
SANDBOX_MAX_APPLY = 3000


class SandboxError(Exception):
    pass


def _same_file_content(a, b, chunk=1 << 20):
    """分段比對兩個檔案（v6.11 紅隊：整個檔讀進記憶體比對，300 MB 的檔案就多吃 300 MB）。"""
    try:
        with open(a, "rb") as fa, open(b, "rb") as fb:
            while True:
                x, y = fa.read(chunk), fb.read(chunk)
                if x != y:
                    return False
                if not x:
                    return True
    except OSError:
        return False


class Sandbox:
    """把工作資料夾複製到暫存資料夾（不含 .git、.ai協作、符號連結），指令在複本裡跑。
    跑完比對複本與原資料夾：新增、修改的檔案由使用者核准後才套回（會先備份、可以復原）；刪除不會套回。"""

    def __init__(self, ws):
        self.ws = ws
        self.dir = None
        self.snapshot = {}
        self.original = {}             # 原資料夾每個檔案的 (大小, 修改時間)：跑完檢查指令有沒有繞過沙盒直接改原檔

    def prepare(self):
        files, size = [], 0
        for current, dirs, names in os.walk(self.ws.root):
            dirs[:] = [d for d in dirs if d not in SANDBOX_SKIP and not os.path.islink(os.path.join(current, d))]
            for n in names:
                full = os.path.join(current, n)
                if os.path.islink(full):
                    continue                     # 連結會指回原資料夾或外面，不複製（否則在沙盒裡也改得到原檔）
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                files.append((full, st))
                size += st.st_size
                if len(files) > SANDBOX_MAX_FILES or size > SANDBOX_MAX_BYTES:
                    raise SandboxError(f"工作資料夾太大（超過 {SANDBOX_MAX_FILES:,} 個檔案或 {SANDBOX_MAX_BYTES // 1_000_000:,} MB），"
                                       "不適合複製一份到沙盒。可以在設定關掉沙盒，或改選較小的資料夾。")
        self.dir = tempfile.mkdtemp(prefix="ai協作沙盒_")
        for full, st in files:
            rel = os.path.relpath(full, self.ws.root)
            dest = os.path.join(self.dir, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            try:
                shutil.copy2(full, dest)
            except OSError:
                continue
            self.snapshot[rel.replace("\\", "/")] = (st.st_size, os.stat(dest).st_mtime_ns)
            self.original[rel.replace("\\", "/")] = (st.st_size, st.st_mtime_ns)
        return self.dir

    def rewrite_command(self, command):
        """指令裡寫了工作資料夾的完整路徑時，改成沙盒的路徑（不然會直接改到原檔）。"""
        root = self.ws.root
        flags = re.I if os.name == "nt" else 0
        variants = {root, root.replace("\\", "/"), root.replace("/", "\\")}
        for v in sorted(variants, key=len, reverse=True):
            command = re.sub(re.escape(v), lambda _m: self.dir, command, flags=flags)
        return command

    def changes(self):
        """回傳 (新增, 修改, 刪除) 的相對路徑清單。"""
        added, modified, seen = [], [], set()
        for current, dirs, names in os.walk(self.dir):
            dirs[:] = [d for d in dirs if d not in SANDBOX_SKIP and not os.path.islink(os.path.join(current, d))]
            for n in names:
                full = os.path.join(current, n)
                if os.path.islink(full):
                    continue
                rel = os.path.relpath(full, self.dir).replace("\\", "/")
                seen.add(rel)
                before = self.snapshot.get(rel)
                if before is None:
                    added.append(rel)
                    continue
                st = os.stat(full)
                if (st.st_size, st.st_mtime_ns) == before:
                    continue
                if st.st_size != before[0] or not _same_file_content(full, os.path.join(self.ws.root, rel)):
                    modified.append(rel)
        deleted = [r for r in self.snapshot if r not in seen]
        return sorted(added), sorted(modified), sorted(deleted)

    def touched_original(self):
        """指令繞過沙盒（例如用別種寫法的完整路徑）直接改到原資料夾的檔案。回傳相對路徑清單。"""
        hits = []
        for current, dirs, names in os.walk(self.ws.root):
            dirs[:] = [d for d in dirs if d not in SANDBOX_SKIP and not os.path.islink(os.path.join(current, d))]
            for n in names:
                full = os.path.join(current, n)
                if os.path.islink(full):
                    continue
                rel = os.path.relpath(full, self.ws.root).replace("\\", "/")
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                if self.original.get(rel) != (st.st_size, st.st_mtime_ns):
                    hits.append(rel)
                if len(hits) >= 50:
                    return hits
        hits += [r for r in self.original if not os.path.exists(os.path.join(self.ws.root, r))][:50]
        return hits

    def restore_original(self, rels, untouched):
        """被繞過沙盒直接改到的原檔：沙盒裡那份沒被動過時，它就是執行前的原檔，拿來還原（目前的版本先備份）。
        回傳 (還原的項目, 沒辦法還原的路徑)。"""
        items, failed = [], []
        for rel in rels:
            src = os.path.join(self.dir, rel)
            if rel not in untouched or not os.path.isfile(src):
                failed.append(rel)
                continue
            try:
                full = self.ws.resolve(rel)
                backup = self.ws.backup(full)
                os.makedirs(os.path.dirname(full), exist_ok=True)
                shutil.copy2(src, full)
                items.append(self.ws.record_change(full, backup, "還原（繞過沙盒）"))
            except (ToolError, OSError):
                failed.append(rel)
        return items, failed

    def preview(self, added, modified, limit=6000):
        import difflib
        parts = []
        for rel in modified[:20]:
            try:
                with open(os.path.join(self.ws.root, rel), "rb") as f:
                    old = _decode(f.read(400_000)).splitlines(True)
                with open(os.path.join(self.dir, rel), "rb") as f:
                    new = _decode(f.read(400_000)).splitlines(True)
                parts.append("".join(difflib.unified_diff(old, new, f"{rel}（原本）", f"{rel}（沙盒）", n=1)))
            except OSError:
                continue
        for rel in added[:10]:
            try:
                with open(os.path.join(self.dir, rel), "rb") as f:
                    parts.append(f"+++ 新檔 {rel}\n" + _decode(f.read(1500)))
            except OSError:
                continue
        text = "\n".join(parts)
        return text[:limit] + ("\n…（只顯示前段）" if len(text) > limit else "")

    def apply(self, rels):
        """把沙盒裡的檔案套回工作資料夾：受保護的檔案（.git、腳本、AGENTS.md…）不套用。回傳 (套用的項目, 略過的說明)。"""
        items, skipped = [], []
        for rel in rels:
            why = protected_write_reason(rel) or (is_sensitive_path(rel) and "可能存放金鑰的檔案")
            if why:
                skipped.append(f"{rel}：{why}")
                continue
            try:
                full = self.ws.resolve(rel)
            except ToolError as exc:
                skipped.append(f"{rel}：{exc}")
                continue
            src = os.path.join(self.dir, rel)
            existed = os.path.exists(full)
            backup = self.ws.backup(full)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            shutil.copy2(src, full)
            items.append(self.ws.record_change(full, backup, "沙盒修改" if existed else "沙盒新建"))
        return items, skipped

    def cleanup(self):
        if self.dir and os.path.isdir(self.dir) and os.path.basename(self.dir).startswith("ai協作沙盒_"):
            shutil.rmtree(self.dir, ignore_errors=True)        # 只刪自己建的暫存複本
        self.dir = None


# ───────────────────────── 3. 連線時才檢查實際的 IP（防 DNS rebinding） ─────────────────────────
# v6.10.2 紅隊：原本先解析主機名稱檢查是不是內部位址，真正連線時又重新解析一次；
# 惡意網域可以第一次回公開 IP、第二次回 127.0.0.1，繞過檢查去連你的路由器或本機服務。


class BlockedAddress(OSError):
    pass


def _proxy_hosts():
    hosts = set()
    try:
        for v in urllib.request.getproxies().values():
            h = urllib.parse.urlsplit(v if "://" in v else "http://" + v).hostname
            if h:
                hosts.add(h.lower())
    except Exception:
        pass
    return hosts


def guarded_create_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None, allow_host=None):
    """跟 socket.create_connection 一樣，但只解析一次，任何一個位址是內部網路就拒絕，然後連到「檢查過的那個 IP」。"""
    host, port = address
    infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    allowed = allow_host and (host or "").lower().rstrip(".") == allow_host.lower().rstrip(".")
    if not allowed:
        for info in infos:
            ip = info[4][0].split("%")[0]
            if _private_host(ip):
                raise BlockedAddress(f"「{host}」解析成內部網路位址 {ip}，已阻擋（可能是 DNS rebinding 攻擊）")
    err = None
    for family, socktype, proto, _canon, sockaddr in infos:
        sock = None
        try:
            sock = socket.socket(family, socktype, proto)
            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(sockaddr)
            return sock
        except OSError as exc:
            err = exc
            if sock is not None:
                sock.close()
    raise err or OSError(f"無法連線到 {host}")


def _guard_conn(conn, allow_host):
    proxy = (conn.host or "").lower() in _proxy_hosts()

    def create(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None):
        tunnel = getattr(conn, "_tunnel_host", None)
        if proxy:                                      # 經過使用者設定的代理：代理本身可能在本機，只檢查目標名稱
            if tunnel and not (allow_host and tunnel.lower() == allow_host.lower()) and _private_host(tunnel):
                raise BlockedAddress(f"「{tunnel}」是內部網路位址，已阻擋")
            return socket.create_connection(address, timeout, source_address)
        return guarded_create_connection(address, timeout, source_address, allow_host)
    conn._create_connection = create
    return conn


class _GuardedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *a, allow_host=None, **kw):
        super().__init__(*a, **kw)
        _guard_conn(self, allow_host)


class _GuardedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *a, allow_host=None, **kw):
        super().__init__(*a, **kw)
        _guard_conn(self, allow_host)


class _GuardedHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, allow_host=None):
        super().__init__()
        self.allow_host = allow_host

    def http_open(self, req):
        return self.do_open(functools.partial(_GuardedHTTPConnection, allow_host=self.allow_host), req)


class _GuardedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, allow_host=None):
        super().__init__()
        self.allow_host = allow_host

    def https_open(self, req):
        return self.do_open(functools.partial(_GuardedHTTPSConnection, allow_host=self.allow_host), req,
                            context=getattr(self, "_context", None))


class _NoPrivateRedirectAllow(urllib.request.HTTPRedirectHandler):
    def __init__(self, allow_host=None):
        super().__init__()
        self.allow_host = allow_host

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host = urllib.parse.urlsplit(newurl).hostname
        if not (self.allow_host and (host or "").lower() == self.allow_host.lower()) and _private_host(host):
            raise urllib.error.HTTPError(newurl, code, "轉址到本機或內部網路，已阻擋", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def make_web_opener(allow_host=None):
    """Agent 上網用的連線器：轉址與實際連線都不能到內部網路（allow_host：使用者核准過的那一個內部主機）。"""
    return urllib.request.build_opener(_NoPrivateRedirectAllow(allow_host), _GuardedHTTPHandler(allow_host),
                                       _GuardedHTTPSHandler(allow_host))


_WEB_OPENER = make_web_opener()


# ───────────────────────── 4. 更新檔雜湊驗證 ─────────────────────────
def sha256_text(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def parse_sha256(text):
    """從「雜湊值」或 sha256sum 格式（雜湊值  檔名）取出 64 位十六進位；沒有回傳空字串。"""
    m = re.search(r"\b([0-9a-fA-F]{64})\b", text or "")
    return m.group(1).lower() if m else ""


def verify_update_hash(text, expected):
    """比對更新檔的 SHA-256；不符時丟出 ValueError。"""
    want = parse_sha256(expected)
    if not want:
        raise ValueError("SHA-256 格式不對（要 64 個十六進位字元）")
    got = sha256_text(text)
    if not hmac.compare_digest(got, want):
        raise ValueError(f"檔案的 SHA-256 不符：預期 {want[:16]}…，實際 {got[:16]}…。檔案可能被竄改或下載不完整，沒有更新。")
    return got


def fetch_update_checksum(url, timeout=15):
    """試著下載「網址.sha256」（build.py 會產生）。拿不到回傳空字串。"""
    try:
        req = urllib.request.Request(url + ".sha256", headers={"User-Agent": "AI-Workbench/" + APP_VERSION})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if not resp.geturl().lower().startswith("https://") and not _is_local_or_private_url(resp.geturl()):
                return ""
            return parse_sha256(resp.read(4096).decode("utf-8", "replace"))
    except Exception:
        return ""


# ───────────────────────── 5. 用量統計與預算上限 ─────────────────────────
def parse_price_table(text):
    """每行「模型名稱的一部分 = 輸入價, 輸出價」（美元／每百萬 token）。回傳 [(片段, 輸入, 輸出)]。"""
    out = []
    for line in (text or "").splitlines():
        line = line.split("#", 1)[0].strip()
        m = re.match(r"^(.+?)\s*[=:：]\s*([\d.]+)\s*[,，/\s]\s*([\d.]+)\s*$", line)
        if m:
            try:
                out.append((m.group(1).strip().lower(), float(m.group(2)), float(m.group(3))))
            except ValueError:
                continue
    return out


def estimate_tokens(text):
    """沒有回報用量的服務：中日韓文字約 1 字 1 token，其他約 4 字元 1 token。"""
    text = text or ""
    cjk = len(re.findall(r"[　-鿿가-힯＀-￯]", text))
    return cjk + max(0, len(text) - cjk) // 4


def _messages_text(messages):
    parts = []
    for m in messages or []:
        c = m.get("content") if isinstance(m, dict) else None
        if isinstance(c, str):
            parts.append(c)
        elif isinstance(c, list):
            parts += [p.get("text", "") for p in c if isinstance(p, dict) and isinstance(p.get("text"), str)]
    return "\n".join(parts)


class UsageMeter:
    """統計每一次執行（一輪 Agent 或一次 AI 討論）用了多少 token、約多少錢；超過預算就不再送出新的請求。"""

    def __init__(self):
        self.lock = threading.Lock()
        self.prices = []
        self.token_limit, self.cost_limit = 0, 0.0
        self.run = self._blank()
        self.active = False
        self.inflight = 0              # 已送出、還沒回來的請求預估的輸入 token（同時好幾個請求時不會一起衝過上限）

    @staticmethod
    def _blank():
        return {"prompt": 0, "completion": 0, "cost": 0.0, "calls": 0, "estimated": 0, "by_model": {}}

    def configure(self, token_limit=0, cost_limit=0.0, price_text=""):
        with self.lock:
            self.token_limit = max(0, int(token_limit or 0))
            self.cost_limit = max(0.0, float(cost_limit or 0))
            self.prices = parse_price_table(price_text)

    def begin(self):
        with self.lock:
            self.run, self.active, self.inflight = self._blank(), True, 0

    def reserve(self, messages):
        """送出前預留這次請求的輸入 token；會超過上限就回傳原因、不預留。回傳 (原因, 預留量)。"""
        est = estimate_tokens(_messages_text(messages))
        with self.lock:
            if self.active and self.token_limit:
                total = self.run["prompt"] + self.run["completion"] + self.inflight
                if total + est > self.token_limit and total > 0:
                    return (f"這次執行已用（含進行中）{total:,} token，再送這個約 {est:,} token 的請求會超過上限 "
                            f"{self.token_limit:,}"), 0
            self.inflight += est
        return "", est

    def release(self, amount):
        with self.lock:
            self.inflight = max(0, self.inflight - amount)

    def end(self):
        with self.lock:
            self.active = False
            return dict(self.run)

    def price_for(self, model):
        model = (model or "").lower()
        best = None
        for frag, pin, pout in self.prices:
            if frag and frag in model and (best is None or len(frag) > len(best[0])):
                best = (frag, pin, pout)
        return (best[1], best[2]) if best else (0.0, 0.0)

    def add(self, endpoint, messages, result):
        if not isinstance(result, dict) or result.get("label") == "已達預算上限":
            return
        usage = result.get("usage") if isinstance(result.get("usage"), dict) else None
        if usage and (usage.get("prompt_tokens") or usage.get("completion_tokens")):
            p, c, est = int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0), 0
        else:
            text = result.get("text") or ""
            text += json.dumps(result.get("tool_calls") or [], ensure_ascii=False) if result.get("tool_calls") else ""
            p, c, est = estimate_tokens(_messages_text(messages)), estimate_tokens(text), 1
        pin, pout = self.price_for((endpoint or {}).get("model"))
        cost = (p * pin + c * pout) / 1_000_000
        with self.lock:
            r = self.run
            r["prompt"] += p
            r["completion"] += c
            r["cost"] += cost
            r["calls"] += 1
            r["estimated"] += est
            m = r["by_model"].setdefault((endpoint or {}).get("model") or "?", [0, 0, 0.0])
            m[0] += p
            m[1] += c
            m[2] += cost

    def over_budget(self):
        with self.lock:
            if not self.active:
                return ""
            total = self.run["prompt"] + self.run["completion"]
            if self.token_limit and total >= self.token_limit:
                return f"這次執行已用 {total:,} token，達到設定的上限 {self.token_limit:,}"
            if self.cost_limit and self.run["cost"] >= self.cost_limit:
                return f"這次執行已花約 US${self.run['cost']:.4f}，達到設定的上限 US${self.cost_limit:.4f}"
            return ""

    @staticmethod
    def summary(r):
        if not r or not r.get("calls"):
            return ""
        total = r["prompt"] + r["completion"]
        text = f"用量：{r['calls']} 次呼叫、{total:,} token（輸入 {r['prompt']:,}／輸出 {r['completion']:,}）"
        if r.get("cost"):
            text += f"，約 US${r['cost']:.4f}"
        if r.get("estimated"):
            text += f"（{r['estimated']} 次服務沒有回報用量，是估計值）"
        return text


USAGE = UsageMeter()


def _budget_blocked(reason, agent=False):
    r = {"status": "error", "text": "", "error": f"{reason}。到「設定 → Agent → 用量與預算」可以調高或取消上限。",
         "label": "已達預算上限", "usage": None, "finish": "", "ttft": None, "elapsed": 0.0}
    if agent:
        r["tool_calls"] = []
    return r


_stream_chat_raw = stream_chat
_stream_agent_turn_raw = stream_agent_turn


def stream_chat(endpoint, messages, cancel_event, on_event=None, register=None, options=None):
    reason = USAGE.over_budget()
    held = 0
    if not reason:
        reason, held = USAGE.reserve(messages)
    if reason:
        return _budget_blocked(reason)
    try:
        result = _stream_chat_raw(endpoint, messages, cancel_event, on_event, register, options)
    finally:
        USAGE.release(held)
    USAGE.add(endpoint, messages, result)
    return result


def stream_agent_turn(endpoint, messages, tools, cancel, on_event, register, options):
    reason = USAGE.over_budget()
    held = 0
    if not reason:
        reason, held = USAGE.reserve(messages)
    if reason:
        return _budget_blocked(reason, agent=True)
    try:
        result = _stream_agent_turn_raw(endpoint, messages, tools, cancel, on_event, register, options)
    finally:
        USAGE.release(held)
    USAGE.add(endpoint, messages, result)
    return result


# ───────────────────────── 6. Git 分支隔離（worktree） ─────────────────────────
class GitError(Exception):
    pass


def _git(cwd, *args, timeout=60):
    try:
        r = subprocess.run(["git", *SAFE_GIT_ARGS, *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, stdin=subprocess.DEVNULL, env=scrubbed_env(),
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except FileNotFoundError:
        raise GitError("這台電腦沒有安裝 Git。")
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitError(f"git 執行失敗：{exc}")
    return r


def _git_ok(cwd, *args, **kw):
    r = _git(cwd, *args, **kw)
    if r.returncode != 0:
        raise GitError((r.stderr or r.stdout or "git 回報錯誤").strip()[:600])
    return r.stdout.strip()


def git_worktree_start(root):
    """在新分支的獨立資料夾（worktree）工作：Agent 改的東西不會動到原本的資料夾，確認後再合併。
    回傳 {"origin","path","branch","base","dirty"}。"""
    risk = git_config_risk(root)
    if risk:
        raise GitError("這個儲存庫的 Git 設定會執行外部程式，為了安全不自動執行 git：" + risk)
    top = _git_ok(root, "rev-parse", "--show-toplevel")
    top = os.path.normpath(top)
    base = _git_ok(top, "rev-parse", "--abbrev-ref", "HEAD")
    if _git(top, "rev-parse", "--verify", "HEAD").returncode != 0:
        raise GitError("這個儲存庫還沒有任何提交，先提交一次才能開分支。")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    branch = f"ai/{stamp}"
    path = os.path.join(top, AGENT_DIR_NAME, "分支", stamp)
    common = _git_ok(top, "rev-parse", "--git-common-dir")
    common = common if os.path.isabs(common) else os.path.join(top, common)
    exclude = os.path.join(common, "info", "exclude")
    os.makedirs(os.path.dirname(exclude), exist_ok=True)
    try:
        with open(exclude, "r", encoding="utf-8", errors="replace") as f:
            have = f.read()
    except OSError:
        have = ""
    if f"/{AGENT_DIR_NAME}/" not in have:
        with open(exclude, "a", encoding="utf-8") as f:
            f.write(f"\n# AI 協作的備份、記憶與分支資料夾（不要提交）\n/{AGENT_DIR_NAME}/\n{AGENT_DIR_NAME}/\n")
    _git_ok(top, "worktree", "add", "-b", branch, path, "HEAD")
    dirty = len([l for l in _git_ok(top, "status", "--porcelain").splitlines() if l.strip()])
    return {"origin": top, "path": path, "branch": branch, "base": base, "dirty": dirty}


def git_worktree_summary(info):
    """分支裡改了什麼（含還沒提交的）。"""
    path = info["path"]
    lines = _git_ok(path, "status", "--porcelain").splitlines()
    committed = _git_ok(path, "log", "--oneline", f"{info['base']}..HEAD") if info.get("base") not in ("", "HEAD") else ""
    return {"uncommitted": [l[3:] for l in lines if l.strip()], "commits": [c for c in committed.splitlines() if c]}


def git_worktree_merge(info, message="AI 協作：合併 Agent 的修改"):
    """把分支的修改提交並合併回原本的分支。衝突時取消合併、原資料夾不變，回傳說明。"""
    path, origin, branch = info["path"], info["origin"], info["branch"]
    for d in (path, origin):
        risk = git_config_risk(d)
        if risk:
            raise GitError("Git 設定會執行外部程式，不自動執行 git：" + risk)
    ident = []
    if not _git(path, "config", "user.email").stdout.strip():
        ident = ["-c", "user.name=AI協作", "-c", "user.email=ai-collab@localhost"]
    if _git_ok(path, "status", "--porcelain"):
        _git_ok(path, "add", "-A")
        _git_ok(path, *ident, "commit", "-m", message)
    current = _git_ok(origin, "rev-parse", "--abbrev-ref", "HEAD")
    if info.get("base") and current != info["base"]:
        raise GitError(f"原本的資料夾目前在「{current}」分支，不是開分支時的「{info['base']}」。請先切回去再合併。")
    r = _git(origin, *ident, "merge", "--no-ff", "--no-edit", branch)
    if r.returncode != 0:
        _git(origin, "merge", "--abort")
        raise GitError("合併時發生衝突（原本的資料夾沒有改變）。可以在 Git 工具裡手動合併分支 "
                       f"{branch}：\n" + (r.stdout + r.stderr).strip()[:800])
    return f"已把 {branch} 合併回 {current}。分支資料夾保留在 {path}（不會刪除）。"


# ───────────────────────── 7. 匯出：HTML、PDF、GitHub Issue ─────────────────────────
def _md_inline(s):
    s = _html.escape(s, quote=True)                 # 連引號一起跳脫：一般文字裡的 " ' 也不會被誤會成屬性
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])", r"<em>\1</em>", s)

    def link(m):
        url = _html.unescape(m.group(2))
        if not re.match(r"(?i)^(https?://|mailto:|#)", url):
            return m.group(1)                         # javascript: 之類的連結不輸出
        return f'<a href="{_html.escape(url, quote=True)}">{m.group(1)}</a>'
    # v6.14.3 壓力測試：原本 [^)\s]+ 可以吃進「(」，一行 5 萬個 "[a](" 要 68 秒（平方時間）→ 網址不含括號、限制長度
    return re.sub(r"\[([^\]\[\n]{1,500})\]\(([^()\s]{1,2000})\)", link, s)


def markdown_to_html(md, title="對話"):
    """把對話的 Markdown 轉成獨立的 HTML 檔（所有文字都先跳脫，不會執行裡面的程式碼）。"""
    out, lines, i = [], (md or "").splitlines(), 0
    in_list = None
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            if in_list:
                out.append(f"</{in_list}>")
                in_list = None
            lang = re.sub(r"[^\w+-]", "", line.strip()[3:])[:20]
            buf, i = [], i + 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            out.append(f'<pre><code class="lang-{lang}">' + _html.escape("\n".join(buf), quote=False) + "</code></pre>")
            i += 1
            continue
        if re.match(r"^\s*\|.*\|\s*$", line) and i + 1 < len(lines) and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            head = [c.strip() for c in line.strip().strip("|").split("|")]
            rows, i = [], i + 2
            while i < len(lines) and re.match(r"^\s*\|.*\|\s*$", lines[i]):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            out.append("<table><thead><tr>" + "".join(f"<th>{_md_inline(c)}</th>" for c in head) + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{_md_inline(c)}</td>" for c in r) + "</tr>" for r in rows)
                       + "</tbody></table>")
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        lm = re.match(r"^\s*([-*+]|\d+[.)])\s+(.*)$", line)
        if lm:
            kind = "ol" if lm.group(1)[0].isdigit() else "ul"
            if in_list != kind:
                if in_list:
                    out.append(f"</{in_list}>")
                out.append(f"<{kind}>")
                in_list = kind
            out.append(f"<li>{_md_inline(lm.group(2))}</li>")
            i += 1
            continue
        if in_list:
            out.append(f"</{in_list}>")
            in_list = None
        if m:
            n = len(m.group(1))
            out.append(f"<h{n}>{_md_inline(m.group(2))}</h{n}>")
        elif line.startswith(">"):
            out.append(f"<blockquote>{_md_inline(line.lstrip('> '))}</blockquote>")
        elif re.match(r"^\s*(-{3,}|\*{3,})\s*$", line):
            out.append("<hr>")
        elif line.strip():
            out.append(f"<p>{_md_inline(line)}</p>")
        i += 1
    if in_list:
        out.append(f"</{in_list}>")
    css = ("body{font-family:'Microsoft JhengHei','Noto Sans TC',sans-serif;max-width:860px;margin:32px auto;padding:0 16px;"
           "line-height:1.7;color:#1f2328}pre{background:#f6f8fa;padding:12px;overflow:auto;border-radius:6px}"
           "code{font-family:Consolas,monospace;background:#f6f8fa;padding:0 3px}table{border-collapse:collapse}"
           "td,th{border:1px solid #d0d7de;padding:4px 8px}blockquote{color:#57606a;border-left:4px solid #d0d7de;"
           "margin:0;padding-left:12px}@media print{pre{white-space:pre-wrap}}")
    return (f'<!doctype html><html lang="zh-Hant-TW"><head><meta charset="utf-8">'
            f'<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'">'
            f"<title>{_html.escape(mask_secrets(title)[0])}</title><style>{css}</style></head><body>\n" + "\n".join(out) + "\n</body></html>")


def find_browsers():
    """能把 HTML 印成 PDF 的瀏覽器（Edge、Chrome、Chromium），依序排好、不重複。"""
    env = os.environ.get("AI_COLLAB_BROWSER")
    cands = [env] if env else []
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
            if base:
                cands += [os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
                          os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")]
    elif sys.platform == "darwin":
        cands += ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
    for name in ("msedge", "google-chrome", "chromium", "chromium-browser", "chrome"):
        p = shutil.which(name)
        if p:
            cands.append(p)
    import glob as _glob
    cands += sorted(_glob.glob("/opt/pw-browsers/chromium_headless_shell-*/*/chrome-headless-shell"))
    out, seen = [], set()
    for c in cands:
        if c and os.path.isfile(c) and os.path.normcase(os.path.realpath(c)) not in seen:
            seen.add(os.path.normcase(os.path.realpath(c)))
            out.append(c)
    return out


def find_browser():
    found = find_browsers()
    return found[0] if found else ""


def _remove_temp_dir(d, tries=6, delay=0.5):
    """清掉自己建的暫存資料夾。Windows 上瀏覽器的背景程序結束後還會鎖住設定檔一下子（v6.20.0 在 GitHub 的
    Windows 測試抓到：PDF 已經做好，清暫存檔時 WinError 32），所以重試幾次；真的清不掉就留給系統，不影響結果。"""
    for i in range(tries):
        try:
            shutil.rmtree(d)
            return True
        except FileNotFoundError:
            return True
        except OSError:
            time.sleep(delay * (i + 1))
    shutil.rmtree(d, ignore_errors=True)
    if os.path.isdir(d):
        log_app.warning("暫存資料夾清不掉（被其他程式佔用），留給系統清理：%s", d)
        return False
    return True


def _print_pdf_with(browser, html_text, pdf_path, timeout):
    d = tempfile.mkdtemp(prefix="ai協作匯出_")
    try:
        return _print_pdf_in(browser, html_text, pdf_path, timeout, d)
    finally:
        _remove_temp_dir(d)


def _print_pdf_in(browser, html_text, pdf_path, timeout, d):
    src = os.path.join(d, "export.html")
    with open(src, "w", encoding="utf-8") as f:
        f.write(html_text)
    out = os.path.join(d, "export.pdf")
    import pathlib
    cmd = [browser, "--headless", "--disable-gpu", "--no-sandbox", "--disable-extensions", "--no-first-run",
           f"--user-data-dir={os.path.join(d, 'profile')}", "--no-pdf-header-footer", f"--print-to-pdf={out}",
           pathlib.Path(src).as_uri()]
    tree = ProcessTree(cmd, d, scrubbed_env(), shell=False, capture=False)
    try:
        # 有些版本寫完 PDF 不會自己結束：看到檔案大小穩定就收工
        end, last = time.monotonic() + timeout, -1
        while time.monotonic() < end and tree.proc.poll() is None:
            size = os.path.getsize(out) if os.path.isfile(out) else -1
            if size > 100 and size == last:
                break
            last = size
            time.sleep(0.7)
    finally:
        tree.kill()
        tree.close()
    if not os.path.isfile(out) or os.path.getsize(out) < 100:
        return False
    shutil.copyfile(out, pdf_path)
    return True


def html_to_pdf(html_text, pdf_path, timeout=120):
    """用無畫面的 Edge／Chrome 把 HTML 印成 PDF；一個失敗就換下一個。回傳 PDF 路徑；都不行時丟出 RuntimeError。"""
    browsers = find_browsers()
    if not browsers:
        raise RuntimeError("找不到 Edge 或 Chrome，無法轉成 PDF。可以改匯出 HTML，再用瀏覽器「列印 → 另存為 PDF」。")
    each = max(20, timeout // len(browsers))
    for b in browsers:
        if _print_pdf_with(b, html_text, pdf_path, each):
            return pdf_path
        log_app.warning("用 %s 轉 PDF 失敗，換下一個", b)
    raise RuntimeError("瀏覽器沒有產生 PDF。可以改匯出 HTML，再用瀏覽器「列印 → 另存為 PDF」。")


GITHUB_API = "https://api.github.com"


def github_create_issue(repo, title, body, token, api=None, timeout=30):
    """在 GitHub 倉庫開一個 Issue，回傳網址。內容會先遮蔽金鑰。"""
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}", repo or "") or ".." in repo:
        raise ValueError("倉庫要寫成「擁有者/名稱」，例如 Zhao05261310/Lin")
    if not token:
        raise ValueError("找不到 GitHub 權杖（環境變數 GITHUB_TOKEN 或 GH_TOKEN）")
    api = (api or GITHUB_API).rstrip("/")
    if not api.startswith("https://") and not _is_local_or_private_url(api):
        raise ValueError("GitHub API 網址要用 https://")
    title = mask_secrets((title or "AI 協作匯出").strip())[0][:250]
    body = mask_secrets(body or "")[0]
    if len(body) > 60000:
        body = body[:60000] + "\n\n…（內容太長，已截斷）"
    req = urllib.request.Request(f"{api}/repos/{repo}/issues", method="POST",
                                 data=json.dumps({"title": title, "body": body}).encode("utf-8"),
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                          "User-Agent": "AI-Workbench/" + APP_VERSION, "Content-Type": "application/json"})
    try:
        with urllib.request.build_opener(_SameSiteRedirect()).open(req, timeout=timeout) as resp:
            data = json.loads(resp.read(1_000_000).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read(2000).decode("utf-8", "replace")
        raise RuntimeError(f"GitHub 回報 HTTP {exc.code}：{mask_secrets(detail)[0][:300]}")
    return data.get("html_url") or ""


class _SameSiteRedirect(urllib.request.HTTPRedirectHandler):
    """帶權杖的請求不能被轉到別的網站（權杖會被帶過去）。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).netloc.lower() != urllib.parse.urlsplit(req.full_url).netloc.lower():
            raise urllib.error.HTTPError(newurl, code, "轉址到其他網站，已阻擋（避免權杖外洩）", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# ───────────────────────── 8. 範本與角色（AI 團隊）匯入匯出 ─────────────────────────
BUNDLE_FORMAT = "ai-collab-bundle"
_BUNDLE_SERVICE_KEYS = ("name", "role", "url", "model", "credential_env", "temperature", "max_tokens", "task", "num_ctx",
                        "keep_alive", "reasoning", "enabled")


def export_bundle(settings, team=True, templates=True):
    """匯出 AI 團隊（身分、工作、模型、網址、金鑰的環境變數名稱）與自訂範本。不含任何金鑰本體。"""
    data = {"format": BUNDLE_FORMAT, "version": 1, "app_version": APP_VERSION,
            "exported": time.strftime("%Y-%m-%d %H:%M")}
    if team:
        data["team"] = []
        for sv in settings.get("services", []):
            item = {k: sv.get(k) for k in _BUNDLE_SERVICE_KEYS if k in sv}
            if item.get("credential_env") and not looks_like_env_name(item["credential_env"]):
                item["credential_env"] = ""                 # 欄位裡是金鑰本體：絕不匯出
            data["team"].append(item)
    if templates:
        data["templates"] = dict(settings.get("templates", {}))
    return data


def _bundle_url_ok(url):
    if not url:
        return True
    if cli_kind(url):
        return True
    if not re.match(r"(?i)^https?://[^\s/]+", url) or len(url) > 300:
        return False
    if url.lower().startswith("http://") and not _is_local_or_private_url(url):
        return False
    return True


def _key_matches_url(env_name, url):
    """金鑰的環境變數名稱認得出是哪家服務時，網址必須是那家的主機（本機與訂閱 CLI 不需要金鑰，一律不配）。"""
    known = guess_provider_url(env_name)
    if not known:
        return False                        # 認不出的金鑰名稱：不自動配，請使用者自己選
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    want = (urllib.parse.urlsplit(known).hostname or "").lower()
    return bool(host) and (host == want or host.endswith("." + want))


def import_bundle(settings, data):
    """把匯出檔合併進設定（只新增、不覆蓋）。回傳 (加入的成員數, 加入的範本數, 警告清單)。
    匯入檔可能來自別人：只收已知欄位、限制長度；金鑰欄只能是環境變數名稱；網址要是 https（本機除外）。"""
    if not isinstance(data, dict) or data.get("format") != BUNDLE_FORMAT:
        raise ValueError("這不是 AI 協作的範本與角色匯出檔")
    warnings, added_sv, added_tp = [], 0, 0
    team = data.get("team") or []
    if not isinstance(team, list):
        raise ValueError("team 欄位格式不對")
    services = settings.setdefault("services", [])
    for raw in team[:50]:
        if not isinstance(raw, dict):
            continue
        item = {k: str(raw.get(k) if raw.get(k) is not None else "")[:2000 if k == "task" else 200]
                for k in _BUNDLE_SERVICE_KEYS if k != "enabled"}
        item["enabled"] = bool(raw.get("enabled", True))
        name = item.get("name") or item.get("model") or "匯入的 AI"
        if item["credential_env"] and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,80}|NO_KEY", item["credential_env"]):
            warnings.append(f"{name}：金鑰欄不是環境變數名稱，已清空（匯入檔不能帶金鑰本體）")
            item["credential_env"] = ""
        if item["credential_env"] and item["credential_env"] != "NO_KEY" and not _key_matches_url(item["credential_env"], item["url"]):
            # v6.11 紅隊：匯入檔把 NVIDIA_API_KEY 配給攻擊者的網址，你的金鑰就會被送過去
            warnings.append(f"{name}：金鑰 {item['credential_env']} 不是這個網址（{item['url'][:50]}）的服務，已清空，請自己選金鑰")
            item["credential_env"] = ""
        if item["task"] and looks_like_injection(item["task"]):
            warnings.append(f"{name}：工作說明裡有像在對 AI 下指令的句子（提示注入），請先看過：{item['task'][:80]}")
        if not _bundle_url_ok(item["url"]):
            warnings.append(f"{name}：網址「{item['url'][:60]}」不安全（雲端要用 https://），已略過這位")
            continue
        if item["model"] and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/\-\[\]@+]{0,150}", item["model"]):
            warnings.append(f"{name}：模型名稱格式怪異，已略過這位")
            continue
        sv = normalize_service(dict(item, id=new_id()))
        if sv:
            services.append(sv)
            added_sv += 1
    tps = data.get("templates") or {}
    if not isinstance(tps, dict):
        raise ValueError("templates 欄位格式不對")
    custom = settings.setdefault("templates", {})
    for name, content in list(tps.items())[:200]:
        if not isinstance(name, str) or not isinstance(content, str):
            continue
        name = re.sub(r"[\x00-\x1f]", "", name).strip()[:60] or "匯入的範本"
        if name in custom or name in DEFAULT_TEMPLATES:
            name = f"{name}（匯入）"
        if looks_like_injection(content):
            warnings.append(f"範本「{name}」裡有像在對 AI 下指令的句子（提示注入），使用前請先看過")
        custom[name] = content[:20000]
        added_tp += 1
    return added_sv, added_tp, warnings


# ───────────────────────── 9. 搜尋過去的對話（長期記憶） ─────────────────────────
def _terms(text):
    text = (text or "").lower()
    words = re.findall(r"[a-z0-9_]{2,}", text)
    cjk = re.findall(r"[一-鿿]+", text)
    grams = [run[i:i + 2] for run in cjk for i in range(max(1, len(run) - 1))]
    return words + grams


def _session_texts(data):
    out = []

    def walk(v):
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, dict):
            for k, x in v.items():
                if k not in ("images", "image", "data", "b64"):
                    walk(x)
    walk(data.get("display") or data.get("messages") or [])
    return "\n".join(out)


def search_past_conversations(query, workspace=None, exclude_id=None, folder=None, limit=5):
    """在過去的 Agent 對話裡找相關內容（關鍵字＋中文雙字詞的 TF-IDF 分數）。
    只搜尋同一個工作資料夾的對話（不同專案的內容不會互相流到對方）。回傳 [(分數, 標題, 更新時間, 片段)]。"""
    import math
    folder = folder or SESSIONS_DIR
    q = list(dict.fromkeys(_terms(query)))
    if not q or not os.path.isdir(folder):
        return []
    norm = lambda p: os.path.normcase(os.path.realpath(p)) if p else ""
    want = norm(workspace)
    docs = []
    for name in os.listdir(folder)[:5000]:
        if not name.endswith(".json"):
            continue
        try:
            path = os.path.join(folder, name)
            if os.path.getsize(path) > 30_000_000:
                continue
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or data.get("id") == exclude_id:
            continue
        if want and norm(data.get("workspace")) != want:
            continue
        text = _session_texts(data)
        if text:
            docs.append((data.get("title") or "未命名", data.get("updated", ""), text))
    if not docs:
        return []
    df = {t: sum(1 for _ti, _u, tx in docs if t in tx.lower()) for t in q}
    scored = []
    for title, updated, text in docs:
        low = text.lower()
        score = 0.0
        for t in q:
            tf = low.count(t)
            if tf:
                score += (1 + math.log(tf)) * math.log(1 + len(docs) / (1 + df[t]))
        if score <= 0:
            continue
        pos = min((low.find(t) for t in q if t in low), default=0)
        snippet = text[max(0, pos - 160): pos + 340].replace("\n", " ")
        scored.append((round(score, 3), title, updated, mask_secrets(snippet)[0]))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:limit]


TOOLS["search_history"] = ("read", _schema(
    "search_history", "搜尋這個工作資料夾過去的 Agent 對話（之前做過什麼、討論過的決定、遇過的錯誤）。只會找到同一個資料夾的對話。", {
        "query": {"type": "string", "description": "要找的關鍵字或問題"}}, ["query"]))


# ───────────────────────── 10. 剪貼簿圖片與錄音 ─────────────────────────
def grab_clipboard_image(dest_dir):
    """把剪貼簿裡的圖片存成 PNG，回傳路徑；剪貼簿沒有圖片時回傳空字串。"""
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, f"貼上_{time.strftime('%Y%m%d_%H%M%S')}.png")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        if os.name == "nt":
            ps = ("Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
                  "$i=[System.Windows.Forms.Clipboard]::GetImage();"
                  "if($i){$i.Save($env:AI_CLIP_OUT,[System.Drawing.Imaging.ImageFormat]::Png);'ok'}")
            subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", ps], capture_output=True, timeout=20,
                           env=dict(scrubbed_env(), AI_CLIP_OUT=path), creationflags=flags)
        elif sys.platform == "darwin":
            script = (f'set f to (open for access POSIX file "{path}" with write permission)\n'
                      'write (the clipboard as «class PNGf») to f\nclose access f')
            subprocess.run(["osascript", "-e", script], capture_output=True, timeout=20)
        else:
            for cmd in (["wl-paste", "--type", "image/png"], ["xclip", "-selection", "clipboard", "-t", "image/png", "-o"]):
                if shutil.which(cmd[0]):
                    r = subprocess.run(cmd, capture_output=True, timeout=20)
                    if r.returncode == 0 and r.stdout[:8] == b"\x89PNG\r\n\x1a\n":
                        with open(path, "wb") as f:
                            f.write(r.stdout)
                        break
    except (OSError, subprocess.SubprocessError):
        return ""
    if os.path.isfile(path) and os.path.getsize(path) > 0:
        return path
    try:
        if os.path.exists(path):
            os.remove(path)                    # 自己剛建立的空檔
    except OSError:
        pass
    return ""


class AudioRecorder:
    """錄音成 WAV：Windows 用內建的 winmm（不用裝任何東西）；Linux 用 arecord；其他用 sox 的 rec。"""

    ALIAS = "aicollabrec"

    def __init__(self):
        self.path = ""
        self.proc = None
        self.backend = self.available()

    @staticmethod
    def available():
        if os.name == "nt":
            return "winmm"
        if shutil.which("arecord"):
            return "arecord"
        if shutil.which("rec"):
            return "sox"
        return ""

    @staticmethod
    def input_devices():
        """Windows：這台電腦的錄音裝置名稱（沒有麥克風時是空清單）；其他系統回傳 None（不知道）。"""
        if os.name != "nt":
            return None
        try:
            import ctypes
            from ctypes import wintypes

            class WAVEINCAPSW(ctypes.Structure):
                _fields_ = [("wMid", wintypes.WORD), ("wPid", wintypes.WORD), ("vDriverVersion", wintypes.UINT),
                            ("szPname", wintypes.WCHAR * 32), ("dwFormats", wintypes.DWORD), ("wChannels", wintypes.WORD),
                            ("wReserved1", wintypes.WORD)]
            w = ctypes.windll.winmm
            names = []
            for i in range(w.waveInGetNumDevs()):
                caps = WAVEINCAPSW()
                if w.waveInGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps)) == 0:
                    names.append(caps.szPname)
            return names
        except Exception:
            return None

    def _mci(self, cmd):
        import ctypes
        buf = ctypes.create_unicode_buffer(256)
        err = ctypes.windll.winmm.mciSendStringW(cmd, buf, 255, 0)
        if err:
            msg = ctypes.create_unicode_buffer(256)
            ctypes.windll.winmm.mciGetErrorStringW(err, msg, 255)
            raise RuntimeError(f"錄音失敗：{msg.value or err}")
        return buf.value

    def start(self, path):
        if not self.backend:
            raise RuntimeError("這台電腦找不到錄音程式（Linux 需要 arecord，macOS 需要 sox）。")
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if self.backend == "winmm":
            devices = self.input_devices()
            if devices == []:
                raise RuntimeError("這台電腦沒有錄音裝置（麥克風）。接上麥克風或耳麥後再試；"
                                   "也可以到 Windows「設定 → 系統 → 音效 → 輸入」確認有沒有被停用。")
            # v6.16.1：有些電腦回「未安裝可以記錄目前檔案格式的音訊裝置」→ 依序試幾種常見格式
            last = None
            for rate, ch in ((16000, 1), (44100, 1), (48000, 1), (44100, 2), (48000, 2), (None, None)):
                try:
                    self._mci(f"open new type waveaudio alias {self.ALIAS}")
                except RuntimeError as exc:
                    last = exc
                    break
                try:
                    if rate:
                        self._mci(f"set {self.ALIAS} time format ms bitspersample 16 channels {ch} samplespersec {rate} "
                                  f"bytespersec {rate * 2 * ch} alignment {2 * ch}")
                    self._mci(f"record {self.ALIAS}")
                    self.format = f"{rate or '預設'} Hz、{ch or '預設'} 聲道"
                    return
                except RuntimeError as exc:
                    last = exc
                    try:
                        self._mci(f"close {self.ALIAS}")
                    except RuntimeError:
                        pass
            names = "、".join(devices or []) or "（不知道）"
            raise RuntimeError(f"沒辦法開始錄音（錄音裝置：{names}；可能被其他程式佔用，或在 Windows 的隱私權設定裡"
                               f"不允許桌面應用程式使用麥克風）：{last}")
        elif self.backend == "arecord":
            self.proc = subprocess.Popen(["arecord", "-q", "-f", "S16_LE", "-r", "16000", "-c", "1", path],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            self.proc = subprocess.Popen(["rec", "-q", "-r", "16000", "-c", "1", path],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def stop(self):
        if self.backend == "winmm":
            if '"' in self.path:
                raise RuntimeError("錄音檔路徑不能有雙引號")
            try:
                self._mci(f"stop {self.ALIAS}")
                self._mci(f'save {self.ALIAS} "{self.path}"')
            finally:
                self._mci(f"close {self.ALIAS}")
        elif self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None
        return self.path if os.path.isfile(self.path) else ""


# ───────────────────────── 11. 拖放檔案（v6.12） ─────────────────────────
# tkinter 本身沒有拖放。Windows 用系統內建的 WM_DROPFILES（ctypes，不用安裝套件）；其他系統有 tkdnd 才能用。
DROP_WARN_FILES = 5000
DROP_WARN_BYTES = 300_000_000


def measure_paths(paths, cap=200_000):
    """拖進來的項目共有幾個檔案、多大（不跟著捷徑走）。回傳 (檔案數, 位元組)。"""
    files = size = 0
    for p in paths:
        if os.path.islink(p):
            continue
        if os.path.isfile(p):
            files += 1
            size += os.path.getsize(p)
            continue
        for cur, dirs, names in os.walk(p):
            dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(cur, d))]
            for n in names:
                full = os.path.join(cur, n)
                if os.path.islink(full):
                    continue
                files += 1
                try:
                    size += os.path.getsize(full)
                except OSError:
                    pass
                if files >= cap:
                    return files, size
    return files, size


def _free_name(folder, name):
    """資料夾裡沒人用的名稱：a.txt → a (2).txt → a (3).txt…"""
    base, ext = os.path.splitext(name)
    if os.path.isdir(os.path.join(folder, name)):
        base, ext = name, ""
    n = 2
    while os.path.exists(os.path.join(folder, f"{base} ({n}){ext}")):
        n += 1
    return f"{base} ({n}){ext}"


def drop_target_reason(root, target_rel):
    """拖放的目的地能不能用；不能時回傳原因。"""
    ws = Workspace(root)
    try:
        dest = ws.resolve(target_rel or ".")
    except ToolError as exc:
        return str(exc)
    if not os.path.isdir(dest):
        return "目的地不是資料夾"
    rel = ws.rel(dest)
    if rel != "." and (".git" in [p.lower() for p in rel.split("/")] or rel.split("/")[0] == AGENT_DIR_NAME):
        return "不能放進 .git 或 .ai協作 資料夾"
    return ""


def drop_conflicts(root, paths, target_rel=""):
    dest = os.path.join(root, target_rel) if target_rel else root
    return [os.path.basename(os.path.normpath(p)) for p in paths
            if os.path.exists(os.path.join(dest, os.path.basename(os.path.normpath(p))))]


def copy_into_workspace(root, paths, target_rel="", conflict="rename", session_id="拖放"):
    """把拖進來的檔案、資料夾「複製」進工作資料夾（原檔不動）。
    conflict：rename＝另存新名稱、replace＝取代（被蓋掉的檔案先備份到 .ai協作/備份）、skip＝略過。
    回傳 (複製進來的相對路徑, 略過的說明)。"""
    ws = Workspace(root, session_id)
    why = drop_target_reason(root, target_rel)
    if why:
        raise ToolError(why)
    dest_dir = ws.resolve(target_rel or ".")
    real_dest = os.path.realpath(dest_dir)
    done, skipped = [], []
    for src in paths:
        src = os.path.normpath(src)
        name = os.path.basename(src)
        if not name or not os.path.exists(src):
            skipped.append(f"{src}：找不到")
            continue
        if os.path.islink(src):
            skipped.append(f"{name}：是捷徑／連結，不複製（可能指向工作資料夾以外）")
            continue
        real_src = os.path.realpath(src)
        if os.path.isdir(src) and _inside(real_dest, real_src):
            skipped.append(f"{name}：不能把資料夾複製到它自己裡面")
            continue
        if _WIN_DEVICE.match(name) or name.lower() in (".git", AGENT_DIR_NAME.lower()):
            skipped.append(f"{name}：這個名稱不能用")
            continue
        target = os.path.join(dest_dir, name)
        if os.path.normcase(os.path.realpath(target)) == os.path.normcase(real_src):
            skipped.append(f"{name}：已經在這個位置")
            continue
        if os.path.exists(target):
            if conflict == "skip":
                skipped.append(f"{name}：已有同名的，略過")
                continue
            if conflict == "rename":
                target = os.path.join(dest_dir, _free_name(dest_dir, name))
        if os.path.isdir(src):
            for cur, dirs, names in os.walk(src):
                dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(cur, d)) and d != ".git"]
                out_dir = os.path.join(target, os.path.relpath(cur, src))
                os.makedirs(out_dir, exist_ok=True)
                for n in names:
                    s = os.path.join(cur, n)
                    if os.path.islink(s):
                        continue
                    t = os.path.join(out_dir, n)
                    if os.path.isfile(t):
                        ws.backup(t)
                    shutil.copy2(s, t)
        else:
            if os.path.isfile(target):
                ws.backup(target)
            shutil.copy2(src, target)
        done.append(ws.rel(target))
    return done, skipped


class WindowsFileDrop:
    """Windows：讓 Tk 視窗接受從檔案總管拖進來的檔案（WM_DROPFILES）。

    callback(路徑清單, 螢幕 x, 螢幕 y) 是在「視窗訊息處理程序」裡直接呼叫的，這時正在 Tk 的事件迴圈裡面：
    callback 只能做純 Python 的事（例如放進 queue），絕對不能呼叫任何 Tk 指令（包括 after、update）。
    v6.12.1：v6.12.0 在這裡呼叫 widget.after()，tkinter 執行完 Tk 指令會把它記錄的執行緒狀態清成空的，
    事件迴圈接著再呼叫 Python 時程式就當掉（Fatal Python error: PyEval_RestoreThread … thread state is NULL）。"""
    WM_DROPFILES = 0x0233

    def __init__(self, widget, callback):
        import ctypes
        from ctypes import wintypes
        self.widget, self.callback, self.old = widget, callback, {}
        u32, sh32 = ctypes.windll.user32, ctypes.windll.shell32
        lresult = ctypes.c_ssize_t
        self.WNDPROC = ctypes.WINFUNCTYPE(lresult, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        u32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        u32.CallWindowProcW.restype = lresult
        self.setter = getattr(u32, "SetWindowLongPtrW", None) or u32.SetWindowLongW
        self.setter.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        self.setter.restype = ctypes.c_void_p
        sh32.DragQueryFileW.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.c_wchar_p, wintypes.UINT]
        sh32.DragQueryFileW.restype = wintypes.UINT
        sh32.DragQueryPoint.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.POINT)]
        sh32.DragFinish.argtypes = [ctypes.c_void_p]
        sh32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
        u32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        u32.GetParent.argtypes = [wintypes.HWND]
        u32.GetParent.restype = wintypes.HWND
        self.ct, self.wt, self.u32, self.sh32 = ctypes, wintypes, u32, sh32
        self._proc = self.WNDPROC(self._wndproc)        # 一定要留著參照，不然會被回收、程式當掉
        self.hwnds = []
        inner = widget.winfo_id()
        for hwnd in (u32.GetParent(inner), inner):     # 視窗外框與內層都接受（拖到哪個子元件上都收得到）
            if hwnd and hwnd not in self.hwnds:
                self._hook(hwnd)

    def _hook(self, hwnd):
        old = self.setter(hwnd, -4, self.ct.cast(self._proc, self.ct.c_void_p))   # GWLP_WNDPROC
        if not old:
            return
        self.old[hwnd] = old
        self.hwnds.append(hwnd)
        self.sh32.DragAcceptFiles(hwnd, True)
        try:       # 程式以系統管理員身分執行時，一般權限的檔案總管拖進來的訊息會被擋：明確放行
            for msg in (self.WM_DROPFILES, 0x004A, 0x0049):
                self.u32.ChangeWindowMessageFilterEx(self.wt.HWND(hwnd), msg, 1, None)
        except Exception:
            pass

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == self.WM_DROPFILES:
            paths, x, y = [], 0, 0
            try:
                n = self.sh32.DragQueryFileW(wparam, 0xFFFFFFFF, None, 0)
                for i in range(min(n, 2000)):
                    size = self.sh32.DragQueryFileW(wparam, i, None, 0) + 1
                    buf = self.ct.create_unicode_buffer(size)
                    self.sh32.DragQueryFileW(wparam, i, buf, size)
                    paths.append(buf.value)
                pt = self.wt.POINT()
                self.sh32.DragQueryPoint(wparam, self.ct.byref(pt))
                self.u32.ClientToScreen(hwnd, self.ct.byref(pt))
                x, y = pt.x, pt.y
            except Exception:
                log_app.exception("讀取拖放的檔案失敗")
            finally:
                self.sh32.DragFinish(wparam)
            if paths:
                try:
                    self.callback(paths, x, y)              # 純 Python（放進佇列），不能碰 Tk
                except Exception:
                    log_app.exception("處理拖放的檔案失敗")
            return 0
        return self.u32.CallWindowProcW(self.old.get(hwnd), hwnd, msg, wparam, lparam)


def install_file_drop(widget, callback):
    """讓視窗接受拖進來的檔案。回傳說明文字（成功時是使用的方式，失敗時是原因）與物件。"""
    if os.name == "nt":
        try:
            obj = WindowsFileDrop(widget, callback)
            return ("Windows 拖放", obj) if obj.hwnds else ("無法接上 Windows 的拖放", None)
        except Exception as exc:
            log_app.exception("接上 Windows 拖放失敗")
            return (f"無法接上 Windows 的拖放：{exc}", None)
    try:                                  # macOS／Linux：有安裝 tkdnd 才能用
        widget.tk.call("package", "require", "tkdnd")
        cmd = widget.register(lambda data, x, y: callback(list(widget.tk.splitlist(data)), int(x), int(y)) or "copy")
        widget.tk.call("tkdnd::drop_target", "register", widget._w, ("DND_Files",))
        widget.tk.call("bind", widget._w, "<<Drop:DND_Files>>", f"{cmd} %D %X %Y")
        return "tkdnd 拖放", cmd
    except Exception:
        return "這個系統沒有 tkdnd，不能拖放（可以改用「＋ 附加檔案」或「工作區 → 加入檔案…」）", None


# ───────────────────────── 12. 從 GitHub 自動更新（v6.13） ─────────────────────────
# 以前每次修正都要使用者自己開命令列 git pull、再手動「從檔案更新」。現在程式自己去 GitHub 抓最新版：
#   1. 電腦上已經 clone 過的 Git 副本（例如 桌面\Lin）：git fetch 後直接讀 origin/main 的檔案（不改動副本的工作區）
#   2. 沒有副本時，用環境變數 GITHUB_TOKEN／GH_TOKEN 呼叫 GitHub API
# 下載後一定比對同一個提交裡的 AI協作.py.sha256、檢查版本與語法，再交給 apply_update（先備份舊版）。
UPDATE_REPO_DEFAULT = "Zhao05261310/Lin"
UPDATE_REPO_OLD_NAMES = {}     # 倉庫改名時把舊名稱加在這裡（小寫）：改名前 clone 的副本也認得
UPDATE_FILE = "AI協作.py"


class UpdateError(Exception):
    pass


def _clone_matches(folder, repo):
    """這個資料夾是不是 repo 的 Git 副本（直接讀 .git/config，不執行 git）。"""
    cfg = os.path.join(folder, ".git", "config")
    try:
        with open(cfg, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return False
    names = [repo.lower().rstrip("/")]
    names += UPDATE_REPO_OLD_NAMES.get(names[0], [])
    # v6.14.2 紅隊：原本只看網址結尾，https://evil.example/擁有者/倉庫 也會被當成更新來源 → 主機一定要是 github.com
    allowed = []
    for n in names:
        allowed += [f"https://github.com/{n}", f"git@github.com:{n}", f"ssh://git@github.com/{n}"]
    for url in re.findall(r"(?im)^\s*url\s*=\s*(\S+)", text):
        u = url.strip().lower().rstrip("/")
        if u.endswith(".git"):
            u = u[:-4]
        if u in allowed:
            return True
    return False


def find_update_clone(repo=UPDATE_REPO_DEFAULT, app_dir=None):
    """找電腦上這個倉庫的 Git 副本：程式資料夾本身、旁邊的資料夾、桌面、使用者資料夾底下第一層。"""
    app_dir = app_dir or APP_DIR
    seen, cands = set(), [app_dir]
    roots = [os.path.dirname(os.path.abspath(app_dir)), os.path.join(os.path.expanduser("~"), "Desktop"),
             os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop"), os.path.expanduser("~")]
    for r in roots:
        try:
            cands += [os.path.join(r, n) for n in sorted(os.listdir(r))[:400]]
        except OSError:
            continue
    for c in cands:
        key = os.path.normcase(os.path.abspath(c))
        if key in seen or not os.path.isdir(c):
            continue
        seen.add(key)
        if _clone_matches(c, repo):
            return c
    return ""


def _git_bytes(cwd, *args, timeout=90):
    env = dict(scrubbed_env(), GIT_TERMINAL_PROMPT="0")
    try:
        r = subprocess.run(["git", *SAFE_GIT_ARGS, *args], cwd=cwd, capture_output=True, timeout=timeout,
                           stdin=subprocess.DEVNULL, env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except FileNotFoundError:
        raise UpdateError("這台電腦沒有安裝 Git")
    except subprocess.TimeoutExpired:
        raise UpdateError("連 GitHub 逾時（網路不通或需要重新登入 Git）")
    except OSError as exc:
        raise UpdateError(f"git 執行失敗：{exc}")
    if r.returncode != 0:
        raise UpdateError(mask_secrets(r.stderr.decode("utf-8", "replace").strip())[0][:400] or "git 回報錯誤")
    return r.stdout


def fetch_update_from_clone(clone, branch="main"):
    """在 Git 副本裡 fetch，讀 origin/branch 上的 AI協作.py 與 .sha256。不會改動副本的檔案。"""
    risk = git_config_risk(clone)
    if risk:
        raise UpdateError("這個 Git 副本的設定會執行外部程式，為了安全不自動執行 git：" + risk)
    _git_bytes(clone, "fetch", "--quiet", "origin", branch)
    raw = _git_bytes(clone, "show", f"origin/{branch}:{UPDATE_FILE}")
    try:
        sha = parse_sha256(_git_bytes(clone, "show", f"origin/{branch}:{UPDATE_FILE}.sha256").decode("utf-8", "replace"))
    except UpdateError:
        sha = ""
    return raw.decode("utf-8"), sha


def fetch_update_from_api(repo, token, branch="main", api=None, timeout=30):
    """用 GitHub API 讀私有倉庫的檔案（需要權杖）。"""
    api = (api or GITHUB_API).rstrip("/")
    if not api.startswith("https://") and not _is_local_or_private_url(api):
        raise UpdateError("GitHub API 網址要用 https://")
    opener = urllib.request.build_opener(_SameSiteRedirect())

    def get(name):
        url = f"{api}/repos/{repo}/contents/{urllib.parse.quote(name)}?ref={urllib.parse.quote(branch)}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "User-Agent": "AI-Workbench/" + APP_VERSION,
                                                   "Accept": "application/vnd.github.raw"})
        try:
            with opener.open(req, timeout=timeout) as resp:
                return resp.read(8_000_000)
        except urllib.error.HTTPError as exc:
            raise UpdateError(f"GitHub 回報 HTTP {exc.code}（權杖沒有這個倉庫的讀取權限，或倉庫名稱不對）")
        except OSError as exc:
            raise UpdateError(f"連不到 GitHub：{exc}")
    text = get(UPDATE_FILE).decode("utf-8")
    try:
        sha = parse_sha256(get(UPDATE_FILE + ".sha256").decode("utf-8", "replace"))
    except UpdateError:
        sha = ""
    return text, sha


def check_github_update(repo=UPDATE_REPO_DEFAULT, clone=None, token=None, branch="main", api=None):
    """回傳 {"version","text","sha","source"}；已經是最新版時回傳 None。找不到來源或驗證失敗時丟出 UpdateError。"""
    errors, got = [], None
    clone = clone if clone is not None else find_update_clone(repo)
    if clone:
        try:
            got = fetch_update_from_clone(clone, branch) + (f"Git 副本 {clone}",)
        except UpdateError as exc:
            errors.append(f"Git 副本（{clone}）：{exc}")
    if got is None and token:
        try:
            got = fetch_update_from_api(repo, token, branch, api) + ("GitHub API",)
        except UpdateError as exc:
            errors.append(f"GitHub API：{exc}")
    if got is None:
        if not clone and not token:
            raise UpdateError("找不到這個程式的 Git 副本（例如 桌面\\AI-），也沒有設定 GITHUB_TOKEN，沒辦法自動檢查更新")
        raise UpdateError("；".join(errors))
    text, sha, source = got
    if not sha:
        raise UpdateError(f"{source} 上沒有 {UPDATE_FILE}.sha256，無法確認檔案完整，沒有更新")
    verify_update_hash(text, sha)
    version = source_version(text)
    if not version:
        raise UpdateError("下載的檔案不是 AI協作.py（找不到 APP_VERSION）")
    if version_tuple(version) <= version_tuple(APP_VERSION):
        return None
    compile(text, UPDATE_FILE, "exec")
    return {"version": version, "text": text, "sha": sha, "source": source}


def restart_command(script=None, pid=None, extra=()):
    """更新後重新啟動用的指令：新的程式會先等目前這個（或 pid）結束、放開單一執行鎖之後再開。"""
    script = script or os.path.join(APP_DIR, UPDATE_FILE)
    exe = sys.executable
    if os.name == "nt" and exe.lower().endswith("python.exe"):
        w = exe[:-len("python.exe")] + "pythonw.exe"         # 沒有命令列視窗的版本
        if os.path.isfile(w):
            exe = w
    return [exe, script, "--wait-pid", str(pid or os.getpid()), *extra]


def restart_program(script=None, pid=None, extra=()):
    flags = 0x00000008 | 0x00000200 if os.name == "nt" else 0           # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    kw = {"creationflags": flags} if os.name == "nt" else {"start_new_session": True}
    subprocess.Popen(restart_command(script, pid, extra), cwd=os.path.dirname(os.path.abspath(script)) if script else APP_DIR, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, close_fds=True, **kw)


# ───────────────────────── 13. 當機紀錄（v6.13） ─────────────────────────
# Python 層級的當機（例如 Fatal Python error）不會經過 logging；用 faulthandler 寫進 日誌\當機_時間.txt。
# 正常結束時，沒有內容的紀錄檔會自己清掉；下次啟動時如果發現上次的當機紀錄，就告訴使用者在哪裡。
_CRASH_FILE = [None, ""]


def start_crash_log(folder=None):
    import faulthandler, atexit
    folder = folder or LOG_DIR
    try:
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"當機_{time.strftime('%Y%m%d_%H%M%S')}_{os.getpid()}.txt")
        f = open(path, "w", encoding="utf-8")
        f.write(f"AI 協作 {APP_VERSION}（Python {sys.version.split()[0]}）啟動於 {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.flush()
        faulthandler.enable(file=f, all_threads=True)
        _CRASH_FILE[:] = [f, path]
        atexit.register(_finish_crash_log)
        return path
    except OSError:
        return ""


def _finish_crash_log():
    f, path = _CRASH_FILE
    if not f:
        return
    try:
        import faulthandler
        faulthandler.disable()
        f.close()
        with open(path, "r", encoding="utf-8", errors="replace") as r:
            lines = r.read().splitlines()
        if len(lines) <= 1:                 # 只有啟動那一行＝沒有當機，這是自己剛建的檔案，清掉
            os.remove(path)
    except OSError:
        pass
    _CRASH_FILE[:] = [None, ""]


def previous_crash_logs(folder=None, current=""):
    """上次（以前）留下、真的有當機內容的紀錄檔。"""
    folder = folder or LOG_DIR
    out = []
    try:
        names = sorted(os.listdir(folder), reverse=True)
    except OSError:
        return out
    for n in names:
        p = os.path.join(folder, n)
        if not n.startswith("當機_") or not n.endswith(".txt") or os.path.normcase(p) == os.path.normcase(current or ""):
            continue
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as r:
                text = r.read(200_000)
        except OSError:
            continue
        m = re.search(r"_(\d+)\.txt$", n)
        if m and pid_alive(m.group(1)):
            continue                          # 另一個還開著的視窗正在用
        if len(text.splitlines()) > 1:
            out.append((p, text))
        else:
            try:
                os.remove(p)                  # 只有啟動那一行（被強制結束、沒有當機內容）：程式自己建的空紀錄，清掉
            except OSError:
                pass
    return out
