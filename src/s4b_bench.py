

# ───────────────────────── 正確率實測（v6.18.0） ─────────────────────────
# 用一組「可以自動評分」的題目，實際量你的模型與團隊答對多少：
#   1. 單一模型：每個身分 2 題（程式跑測試、計算有標準答案、審查有埋好的錯、資料處理比對 JSON、
#      改寫檢查用語與格式、說明檢查句數與用語、格式題比對 JSON）。
#   2. 團隊模式：同樣的難題交給目前的 AI 團隊，用各種討論模式各跑一次，看討論有沒有比單一模型準。
#   3. Agent：在暫存資料夾修一個有錯的程式檔，用測試評分（不給執行指令的權限）。
# 評分全部在本機用規則完成，不用另一個 AI 當裁判（AI 當裁判本身也會錯）。
BENCH_VERSION = 1
BENCH_DIR = os.path.join(RECORDS_DIR, "正確率實測")
BENCH_CODE_TIMEOUT = 10
BENCH_ANSWER_RULE = "最後一行只寫「答案：」加上答案本身（只寫數字，不加單位）。"

_REVIEW_SEARCH_CODE = '''def find(items, target, seen=[]):
    lo, hi = 0, len(items) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if items[mid] < target:
            lo = mid
        else:
            hi = mid
    seen.append(target)
    return lo if items[lo] == target else -1'''

_REVIEW_LOGIN_CODE = '''def login(db, username, password):
    row = db.execute(f"SELECT * FROM users WHERE name = '{username}' AND pw = '{password}'").fetchone()
    log.info("login: %s / %s", username, password)
    return row is not None'''

_AGENT_CALC = '''def average(nums):
    """平均值；空串列回傳 0。"""
    return sum(nums) / len(nums)


def median(nums):
    """中位數；空串列回傳 0。偶數個時取中間兩個的平均。"""
    nums.sort()
    return nums[len(nums) // 2]
'''

BENCH_TASKS = [
    # ── 程式專家：寫函式，用測試評分 ──
    {"id": "code_roman", "role": "程式專家", "kind": "code", "title": "羅馬數字轉整數",
     "prompt": "用 Python 寫一個函式 roman_to_int(s)，把羅馬數字字串（例如 \"MCMXCIV\"）轉成整數，空字串回傳 0。"
               "只用標準函式庫，把完整程式放在一個 ```python 程式碼區塊裡。",
     "func": "roman_to_int",
     "tests": [[["III"], 3], [["IV"], 4], [["IX"], 9], [["LVIII"], 58], [["MCMXCIV"], 1994], [["MMXXIV"], 2024], [[""], 0]]},
    {"id": "code_merge", "role": "程式專家", "kind": "code", "title": "合併重疊區間",
     "prompt": "用 Python 寫一個函式 merge_intervals(intervals)：輸入 [[起, 迄], …]（可能沒排序），"
               "把重疊或相接的區間合併，回傳依起點排序的串列，例如 [[1,3],[2,6],[8,10]] → [[1,6],[8,10]]；[[1,4],[4,5]] → [[1,5]]。"
               "不要修改傳入的串列。只用標準函式庫，把完整程式放在一個 ```python 程式碼區塊裡。",
     "func": "merge_intervals", "check_mutation": "merge_intervals",
     "tests": [[[[[1, 3], [2, 6], [8, 10], [15, 18]]], [[1, 6], [8, 10], [15, 18]]], [[[[1, 4], [4, 5]]], [[1, 5]]],
               [[[]], []], [[[[5, 7], [1, 2]]], [[1, 2], [5, 7]]], [[[[1, 10], [2, 3], [4, 12]]], [[1, 12]]],
               [[[[3, 3]]], [[3, 3]]]]},
    # ── 研究分析：有標準答案的推理與計數（單一模型最容易錯的類型）──
    {"id": "math_seven", "role": "研究分析", "kind": "number", "title": "1～1000 含 7 的數",
     "prompt": "1 到 1000（含）的整數中，至少有一個位數是 7 的有幾個？請一步一步推算。" + BENCH_ANSWER_RULE, "answer": 271},
    {"id": "math_ones", "role": "研究分析", "kind": "number", "title": "1～100 寫幾個 1",
     "prompt": "把 1 到 100 的整數全部寫出來，數字「1」一共會寫幾次？（例如 11 算兩次）請一步一步推算。" + BENCH_ANSWER_RULE,
     "answer": 21},
    # ── 審查批判：找出埋好的錯 ──
    {"id": "review_search", "role": "審查批判", "kind": "review", "title": "二分搜尋的錯",
     "prompt": "審查下面的 Python 函式，條列所有錯誤（每點說明會在什麼情況出錯）：\n```python\n" + _REVIEW_SEARCH_CODE + "\n```",
     "bugs": [["無窮迴圈", r"無窮迴圈|無限迴圈|死循環|卡住|不會結束|infinite|lo\s*=\s*mid\s*\+\s*1|mid\s*\+\s*1"],
              ["可變預設參數", r"seen\s*=\s*\[\]|可變.{0,8}預設|預設.{0,8}(可變|串列|清單|list)|mutable|共用.{0,12}(串列|清單|list)|累積"],
              ["空串列", r"空(的)?\s*(串列|清單|列表|陣列|list)|len\(items\)\s*==\s*0|IndexError|索引.{0,6}(超出|錯誤|越界)|empty"]]},
    {"id": "review_login", "role": "審查批判", "kind": "review", "title": "登入函式的漏洞",
     "prompt": "審查下面的 Python 登入函式，條列所有安全問題（每點說明怎麼被利用、該怎麼改）：\n```python\n" + _REVIEW_LOGIN_CODE + "\n```",
     "bugs": [["SQL 注入", r"SQL\s*(注入|隱碼|injection)|參數化|parameteri[sz]|佔位符|placeholder"],
              ["明文密碼", r"明文|雜湊|hash|bcrypt|argon|pbkdf|加鹽|salt"],
              ["日誌記錄密碼", r"(日誌|紀錄|記錄|log)[^\n]{0,30}(密碼|password)|(密碼|password)[^\n]{0,30}(日誌|紀錄|記錄|log)"]]},
    # ── 資料處理：輸出 JSON，跟標準答案比 ──
    {"id": "data_sales", "role": "資料處理", "kind": "json", "title": "訂單去重加總",
     "prompt": "下面是訂單資料（CSV）。同一個訂單編號重複出現只算一次；金額空白當 0。請算出每個城市的金額總和，"
               "只輸出一個 JSON 物件（鍵是城市、值是數字），不要其他文字。\n\n訂單編號,城市,金額\nA001,台北,120\nA002,台中,80\n"
               "A001,台北,120\nA003,台北,\nA004,高雄,200\nA005,台中,45.5\nA004,高雄,200",
     "answer": {"台北": 120, "台中": 125.5, "高雄": 200}},
    {"id": "data_salary", "role": "資料處理", "kind": "json", "title": "條件篩選平均",
     "prompt": "下面是員工資料。只算 2024-01-01（含）之後到職的人，算出每個部門的平均薪資（四捨五入到整數）。"
               "只輸出一個 JSON 物件（鍵是部門、值是整數），不要其他文字；沒有人符合的部門不要列。\n\n"
               '[{"name":"甲","dept":"研發","salary":62000,"joined":"2023-05-01"},'
               '{"name":"乙","dept":"研發","salary":58000,"joined":"2024-02-01"},'
               '{"name":"己","dept":"研發","salary":61001,"joined":"2024-07-15"},'
               '{"name":"丙","dept":"業務","salary":45000,"joined":"2024-01-01"},'
               '{"name":"丁","dept":"業務","salary":51000,"joined":"2022-11-30"},'
               '{"name":"戊","dept":"人資","salary":47000,"joined":"2024-03-03"},'
               '{"name":"庚","dept":"法務","salary":70000,"joined":"2021-08-08"}]',
     "answer": {"研發": 59501, "業務": 45000, "人資": 47000}},
    # ── 文件撰寫：用語與格式 ──
    {"id": "write_notice", "role": "文件撰寫", "kind": "rewrite", "title": "公告改寫成台灣用語",
     "prompt": "把下面的公告改寫成台灣用語，條列剛好 3 點，總長 120 字以內，只輸出改寫結果：\n"
               "「各位用戶：為了優化服務質量，我們將於本周六凌晨 2 點至 6 點對服務器進行升級，屆時軟件將無法登錄，"
               "數據不會丟失。給您帶來不便，敬請諒解。」",
     "bullets": 3, "max_chars": 120, "must": [["週六", r"週六|星期六|禮拜六"], ["伺服器", r"伺服器"], ["時間", r"2\s*(點|時|:)|凌晨\s*2|02:00"]],
     "banned": ["用戶", "優化", "質量", "服務器", "軟件", "登錄", "數據"]},
    {"id": "write_table", "role": "文件撰寫", "kind": "table", "title": "會議紀錄整理成表格",
     "prompt": "把下面的會議紀錄整理成 Markdown 表格，欄位依序是「事項、負責人、期限」，只輸出表格：\n"
               "今天討論了三件事。官網改版由小美負責，11 月 20 日前要上線；年終尾牙場地交給阿凱，12 月 1 日前訂好；"
               "另外新進同仁的教育訓練教材，請志明在 11 月 15 日前完成初稿。",
     "columns": ["事項", "負責人", "期限"],
     "rows": [["官網", "小美", r"11\s*[月/／-]\s*20"], ["尾牙", "阿凱", r"12\s*[月/／-]\s*0?1"], ["教育訓練|教材", "志明", r"11\s*[月/／-]\s*15"]]},
    # ── 對話溝通：句數、不夾英文、台灣用語 ──
    {"id": "talk_seasons", "role": "對話溝通", "kind": "explain", "title": "向小學生解釋四季",
     "prompt": "用三句話以內、不要夾英文，向國小學生解釋為什麼會有四季。", "max_sentences": 3,
     "must": [["地軸傾斜", r"傾斜|斜斜|歪"], ["太陽", r"太陽|陽光"]]},
    {"id": "talk_angry", "role": "對話溝通", "kind": "explain", "title": "回覆生氣的使用者",
     "prompt": "使用者很生氣地說：「你們的 App 又當機了，我的資料全沒了！」請你以客服身分，用兩句話以內回覆：先道歉，再說明下一步怎麼幫他。"
               "不要夾英文（App 可以照寫）。", "max_sentences": 2, "allow_latin": ["App", "APP", "app"],
     "must": [["道歉", r"抱歉|對不起|很遺憾|不好意思"], ["下一步", r"協助|幫您|幫你|請(您|你)?提供|聯繫|聯絡|復原|還原|找回|備份|處理"]]},
    # ── 一般助理：嚴格照格式 ──
    {"id": "json_mountain", "role": "一般助理", "kind": "json", "title": "只輸出 JSON（常識）",
     "prompt": "只輸出 JSON，不要任何其他文字或程式碼區塊：{\"mountain\": 台灣最高的山的名字, \"height_m\": 它的高度（整數公尺）}",
     "answer": {"mountain": "玉山", "height_m": 3952}, "tolerance": {"height_m": 1}, "strict": True},
    {"id": "json_fruit", "role": "一般助理", "kind": "json", "title": "只輸出 JSON（計算＋排序）",
     "prompt": "只輸出 JSON 陣列，不要任何其他文字或程式碼區塊：把「蘋果 3 個、每個 30 元；香蕉 12 根、每根 5 元；芒果 2 顆、每顆 40 元」"
               "轉成 [{\"item\": 名稱, \"qty\": 數量, \"unit_price\": 單價, \"subtotal\": 小計}]，依 subtotal 由大到小排列。",
     "answer": [{"item": "蘋果", "qty": 3, "unit_price": 30, "subtotal": 90}, {"item": "芒果", "qty": 2, "unit_price": 40, "subtotal": 80},
                {"item": "香蕉", "qty": 12, "unit_price": 5, "subtotal": 60}], "strict": True},
]
BENCH_ROLES = tuple(dict.fromkeys(t["role"] for t in BENCH_TASKS))
# 團隊模式用的題目：單一模型最常錯、討論最有機會幫上忙的幾類
BENCH_TEAM_TASKS = ("math_seven", "math_ones", "code_merge", "review_search", "data_salary")
BENCH_AGENT_TASK = {
    "id": "agent_fix", "role": "Agent", "kind": "agent", "title": "修好有錯的程式檔",
    "prompt": "工作資料夾裡的 calc.py 有錯：average 和 median 遇到空串列會出錯（應該回傳 0），median 在偶數個時算錯"
              "（應該取中間兩個的平均），而且 median 會改到呼叫者傳進來的串列。請直接修改 calc.py 修好這些問題，函式名稱不要改。",
    "file": "calc.py", "source": _AGENT_CALC,
    "tests": {"average": [[[[1, 2, 3, 4]], 2.5], [[[]], 0], [[[5]], 5]],
              "median": [[[[3, 1, 2]], 2], [[[4, 1, 3, 2]], 2.5], [[[]], 0], [[[7]], 7]]},
    "check_mutation": "median"}


# ── 評分 ──
def _bench_num(text):
    try:
        v = float(str(text).replace(",", "").replace("，", ""))
    except ValueError:
        return None
    return int(v) if v.is_integer() else v


def extract_final_number(text):
    """「答案：271」優先（取最後一個）；沒有就取全文最後一個數字。回傳 (數字或 None, 是否照格式)。"""
    t = (text or "").replace("，", ",")
    marks = re.findall(r"答案\s*[:：]\s*\**\s*(-?\d[\d,]*(?:\.\d+)?)", t)
    if marks:
        return _bench_num(marks[-1]), True
    nums = re.findall(r"-?\d[\d,]*(?:\.\d+)?", t)
    return (_bench_num(nums[-1]) if nums else None), False


def extract_code_block(text):
    """取出最長的 Python 程式碼區塊（沒有區塊就當整段是程式）。"""
    blocks = re.findall(r"```(?:python|py)?[ \t]*\n(.*?)```", text or "", re.S | re.I)
    if blocks:
        return max(blocks, key=len)
    return text or ""


# operator、dataclasses 不開放：operator.attrgetter 可以用執行時組出來的字串取屬性，dataclasses 會用 exec 產生程式
BENCH_ALLOWED_IMPORTS = {"math", "re", "itertools", "collections", "functools", "string", "heapq", "bisect",
                         "statistics", "copy", "fractions", "decimal"}
# typing 裡有會把字串當程式執行的函式（get_type_hints、3.14 的 evaluate_forward_ref…）→ 只准 from typing 匯入型別名稱
BENCH_TYPING_NAMES = {"List", "Dict", "Tuple", "Set", "FrozenSet", "Optional", "Union", "Any", "Iterable", "Iterator",
                      "Sequence", "Mapping", "Callable", "Deque", "DefaultDict", "Counter", "Generator", "TypeVar"}
_BENCH_BANNED_NAMES = {"open", "exec", "eval", "compile", "__import__", "globals", "locals", "vars", "getattr", "setattr",
                       "delattr", "input", "breakpoint", "exit", "quit", "help", "memoryview", "__builtins__", "classmethod",
                       "Formatter", "get_type_hints", "ForwardRef", "attrgetter", "methodcaller"}
# 這些方法會把「字串」當屬性名稱去取物件（v6.18.0 自己攻擊時用 string.Formatter().get_field 摸到 object.__subclasses__）
_BENCH_BANNED_ATTRS = {"get_field", "get_value", "vformat", "Formatter", "get_type_hints", "ForwardRef", "attrgetter",
                       "methodcaller", "format_map", "mro", "gi_frame", "gi_code", "f_globals", "f_locals", "f_back", "tb_frame",
                       "cr_frame", "ag_frame", "func_globals", "evaluate_forward_ref", "get_annotations", "load_module"}


def code_safety_reason(source):
    """評分前先檢查模型寫的程式：只准用少數標準模組，不准讀寫檔、動態執行、碰底線開頭的屬性（常見的沙盒逃脫手法）。
    不安全回傳原因，安全回傳 ""。這是第一層；第二層是在獨立程序、暫存資料夾、時間上限內執行。"""
    import ast as _ast
    if len(source or "") > 100_000:
        return "程式太長（超過 10 萬字）"
    try:
        tree = _ast.parse(source)
    except SyntaxError as exc:
        return f"程式有語法錯誤：{exc.msg}（第 {exc.lineno} 行）"
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Import):
            bad = [a.name for a in node.names if a.name.split(".")[0] not in BENCH_ALLOWED_IMPORTS]
            if bad:
                return f"用了不允許的模組：{'、'.join(bad)}"
        elif isinstance(node, _ast.ImportFrom):
            if node.module == "typing" and not node.level:
                bad = [a.name for a in node.names if a.name not in BENCH_TYPING_NAMES]
                if bad:
                    return f"typing 只能匯入型別名稱，不能用：{'、'.join(bad)}"
            elif (node.module or "").split(".")[0] not in BENCH_ALLOWED_IMPORTS or node.level:
                return f"用了不允許的模組：{node.module}"
        elif isinstance(node, _ast.Name) and (node.id in _BENCH_BANNED_NAMES or node.id.startswith("__")):
            return f"用了不允許的名稱：{node.id}"
        elif isinstance(node, _ast.Attribute) and (node.attr.startswith("_") or node.attr in _BENCH_BANNED_ATTRS):
            return f"用了不允許的屬性：{node.attr}"
        elif isinstance(node, _ast.alias) and node.name in _BENCH_BANNED_NAMES:
            return f"用了不允許的名稱：{node.name}"
        elif isinstance(node, _ast.Constant) and isinstance(node.value, str) and "__" in node.value:
            return "字串裡有雙底線（可能是繞過檢查的手法）"
    return ""


_BENCH_HARNESS = r'''
import json, sys
try:                                   # Linux／macOS：記憶體上限 1 GB（Windows 靠時間上限與系統配置失敗）
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (1 << 30, 1 << 30))
except Exception:
    pass
def norm(v):
    if isinstance(v, tuple):
        v = list(v)
    if isinstance(v, list):
        return [norm(x) for x in v]
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v
def same(a, b):
    if type(a) is not type(b):
        return False
    if isinstance(a, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict):
        return set(a) == set(b) and all(same(a[k], b[k]) for k in a)
    return a == b
spec = json.load(open("spec.json", encoding="utf-8"))
import builtins as _b
ALLOWED = set(spec["allowed"])
def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level or name.split(".")[0] not in ALLOWED:
        raise ImportError("實測不允許匯入 %s" % name)
    return _b.__import__(name, globals, locals, fromlist, level)
SAFE = ("abs all any ascii bin bool bytearray bytes callable chr complex dict divmod enumerate filter float format frozenset "
        "hash hex id int isinstance issubclass iter len list map max min next object oct ord pow print property range repr "
        "reversed round set slice sorted staticmethod str sum super tuple type zip __build_class__ "
        "BaseException Exception ArithmeticError AssertionError AttributeError IndexError KeyError LookupError "
        "NotImplementedError OverflowError RecursionError RuntimeError StopIteration TypeError ValueError ZeroDivisionError "
        "True False None NotImplemented Ellipsis").split()
safe_builtins = {k: getattr(_b, k) for k in SAFE if hasattr(_b, k)}
safe_builtins["__import__"] = guarded_import
safe_builtins["print"] = lambda *a, **k: None        # 模型的程式印再多也不會塞爆輸出；結果寫到檔案
ALLOWED.add("typing")                  # 語法檢查已限制 typing 只能匯入型別名稱
g = {"__name__": "solution", "__builtins__": safe_builtins}     # 第二層：執行時也只給白名單的內建函式與模組
try:
    exec(compile(open("solution.py", encoding="utf-8").read(), "solution.py", "exec"), g)
except BaseException as exc:
    open("result.json", "w", encoding="utf-8").write(json.dumps({"error": "載入失敗：%s: %s" % (type(exc).__name__, exc)}, ensure_ascii=False)); sys.exit(0)
out = {}
for fname, tests in spec["tests"].items():
    fn = g.get(fname)
    res = []
    for args, want in tests:
        if not callable(fn):
            res.append([False, "沒有 %s 這個函式" % fname]); continue
        before = json.dumps(args)
        try:
            got = fn(*args)
            ng, nw = norm(got), norm(want)
            num = (int, float)
            if isinstance(nw, num) and not isinstance(nw, bool):
                ok = type(ng) in num and abs(ng - nw) < 1e-9
            else:                       # 型別要一樣：避免回傳一個「跟什麼比都相等」的物件騙過測試
                ok = type(ng) is type(nw) and same(ng, nw)
            msg = "" if ok else "%r → %r（應為 %r）" % (args, got, want)
            if ok and fname == spec.get("check_mutation") and json.dumps(args) != before:
                ok, msg = False, "%r 被函式改掉了" % (args,)
            res.append([ok, msg])
        except BaseException as exc:
            res.append([False, "%r → %s: %s" % (args, type(exc).__name__, exc)])
    out[fname] = res
open("result.json", "w", encoding="utf-8").write(json.dumps({"results": out}, ensure_ascii=False))
'''


def bench_python():
    """評分程式用的 Python：一般情況就是自己；打包成 exe 時找系統上的 python。"""
    if not getattr(sys, "frozen", False):
        return sys.executable
    return shutil.which("python") or shutil.which("py") or ""


def run_code_tests(source, tests, check_mutation=None, cancel=None, timeout=BENCH_CODE_TIMEOUT):
    """tests：{函式名: [[參數串列, 期望值], …]}。回傳 (通過數, 總數, 說明)。"""
    total = sum(len(v) for v in tests.values())
    reason = code_safety_reason(source)
    if reason:
        return 0, total, "沒有執行：" + reason
    py = bench_python()
    if not py:
        return 0, total, "沒有執行：找不到 Python（打包版需要另外安裝 Python 才能評分程式題）"
    import tempfile as _tf
    with _tf.TemporaryDirectory(prefix="ai協作實測_") as d:
        with open(os.path.join(d, "solution.py"), "w", encoding="utf-8") as f:
            f.write(source)
        with open(os.path.join(d, "spec.json"), "w", encoding="utf-8") as f:
            json.dump({"tests": tests, "check_mutation": check_mutation, "allowed": sorted(BENCH_ALLOWED_IMPORTS)}, f,
                      ensure_ascii=False)
        with open(os.path.join(d, "harness.py"), "w", encoding="utf-8") as f:
            f.write(_BENCH_HARNESS)
        env = {k: v for k, v in os.environ.items() if k.upper() in ("SYSTEMROOT", "PATH", "TEMP", "TMP", "LANG")}
        env["PYTHONIOENCODING"] = "utf-8"
        out, status, _code, _secs, _note = run_process_tree([py, "-I", "-S", "harness.py"], d, env, timeout=timeout,
                                                            cancel=cancel, cap=200_000, shell=False)
        result_path = os.path.join(d, "result.json")
        data = None
        if not status and os.path.isfile(result_path):
            try:
                with open(result_path, encoding="utf-8") as f:
                    data = json.load(f)
            except ValueError:
                data = None
    if status:
        return 0, total, f"執行{status}"
    if not isinstance(data, dict):
        return 0, total, "執行失敗：" + (out or "").strip()[-300:]
    if data.get("error"):
        return 0, total, data["error"]
    passed = sum(1 for res in data["results"].values() for ok, _m in res if ok)
    fails = [msg for res in data["results"].values() for ok, msg in res if not ok and msg][:3]
    return passed, total, "；".join(fails)


def _json_payload(text):
    """回傳 (資料, 是否乾淨)：乾淨＝整段就是 JSON；有程式碼區塊或前後多了文字也盡量解析，但算沒照格式。"""
    t = (text or "").strip()
    try:
        return json.loads(t), True
    except ValueError:
        pass
    m = re.search(r"```(?:json)?\s*\n?(.*?)```", t, re.S)
    if m:
        try:
            return json.loads(m.group(1).strip()), False
        except ValueError:
            pass
    for opener, closer in (("{", "}"), ("[", "]")):
        a, b = t.find(opener), t.rfind(closer)
        if 0 <= a < b:
            try:
                return json.loads(t[a:b + 1]), False
            except ValueError:
                pass
    return None, False


def _json_equal(got, want, tol=None, key=None):
    if isinstance(want, dict):
        return isinstance(got, dict) and set(got) == set(want) and all(_json_equal(got[k], want[k], tol, k) for k in want)
    if isinstance(want, list):
        return isinstance(got, list) and len(got) == len(want) and all(_json_equal(g, w, tol) for g, w in zip(got, want))
    if isinstance(want, (int, float)) and not isinstance(want, bool):
        if isinstance(got, str):
            got = _bench_num(got)
        return isinstance(got, (int, float)) and abs(got - want) <= (tol or {}).get(key, 1e-6)
    return str(got).strip() == str(want)


def _sentences(text):
    plain = re.sub(r"\s+", "", text or "")
    return [s for s in re.split(r"[。！？!?；;]+", plain) if len(s) >= 2]


def _bullet_lines(text):
    return [ln for ln in (text or "").splitlines() if re.match(r"\s*(?:[-*•‧・]|\d+[.、)）]|[（(]\d+[）)])\s*\S", ln)]


def grade_answer(task, text, cancel=None):
    """回傳 {"score": 0～1, "detail": 說明}。"""
    kind, text = task["kind"], text or ""
    if not text.strip():
        return {"score": 0.0, "detail": "沒有回答"}
    if kind == "number":
        got, formatted = extract_final_number(text)
        ok = got is not None and abs(got - task["answer"]) < 1e-9
        detail = f"回答 {got}，正確答案 {task['answer']}" + ("" if formatted else "（沒有照「答案：」格式，取最後一個數字）")
        return {"score": 1.0 if ok else 0.0, "detail": detail}
    if kind == "code":
        passed, total, note = run_code_tests(extract_code_block(text), {task["func"]: task["tests"]}, task.get("check_mutation"),
                                             cancel=cancel)
        return {"score": passed / total if total else 0.0, "detail": f"測試通過 {passed}／{total}" + (f"：{note}" if note else "")}
    if kind == "review":
        found = [name for name, pat in task["bugs"] if re.search(pat, text, re.I)]
        missed = [name for name, _p in task["bugs"] if name not in found]
        return {"score": len(found) / len(task["bugs"]),
                "detail": f"找到 {len(found)}／{len(task['bugs'])} 個埋好的錯" + (f"，漏了：{'、'.join(missed)}" if missed else "")}
    if kind == "json":
        data, clean = _json_payload(text)
        if data is None:
            return {"score": 0.0, "detail": "不是有效的 JSON"}
        ok = _json_equal(data, task["answer"], task.get("tolerance"))
        if not ok:
            return {"score": 0.0, "detail": "內容不對：" + json.dumps(data, ensure_ascii=False)[:200]}
        if task.get("strict") and not clean:
            return {"score": 0.5, "detail": "內容正確，但前後多了文字或程式碼區塊（題目要求只輸出 JSON）"}
        return {"score": 1.0, "detail": "完全正確"}
    checks = []                      # 文字題：逐項檢查，分數＝通過的比例
    if kind == "rewrite":
        body = text.strip()
        bullets = _bullet_lines(body)
        checks.append((len(bullets) == task["bullets"], f"條列 {len(bullets)} 點（要 {task['bullets']} 點）"))
        size = len(re.sub(r"\s", "", body))
        checks.append((size <= task["max_chars"], f"{size} 字（上限 {task['max_chars']}）"))
        left = [w for w in task["banned"] if w in body]
        checks.append((not left, "沒有大陸用語" if not left else "還有大陸用語：" + "、".join(left)))
        for name, pat in task["must"]:
            checks.append((bool(re.search(pat, body)), f"{'有' if re.search(pat, body) else '缺'}「{name}」", True))
    elif kind == "table":
        rows = [ln for ln in text.splitlines() if ln.strip().startswith("|")]
        header = rows[0] if rows else ""
        cols_ok = bool(header) and [c.strip(" *") for c in header.strip().strip("|").split("|")] == task["columns"]
        checks.append((cols_ok, "欄位正確" if cols_ok else "欄位不是「" + "、".join(task["columns"]) + "」"))
        data_rows = [r for r in rows[1:] if not re.fullmatch(r"[\s|:\-]+", r)]
        checks.append((len(data_rows) == len(task["rows"]), f"{len(data_rows)} 列資料（要 {len(task['rows'])} 列）"))
        for item, person, due in task["rows"]:
            hit = any(re.search(item, r) and person in r and re.search(due, r) for r in data_rows)
            checks.append((hit, f"{'有' if hit else '缺'}「{person}」那一列（事項、期限要對）", True))
    elif kind == "explain":
        n = len(_sentences(text))
        checks.append((n <= task["max_sentences"], f"{n} 句（上限 {task['max_sentences']}）"))
        latin = re.sub("|".join(map(re.escape, task.get("allow_latin") or [])) or r"(?!)", "", text)
        has_latin = bool(re.search(r"[A-Za-z]{2,}", latin))
        checks.append((not has_latin, "沒有夾英文" if not has_latin else "夾了英文"))
        for name, pat in task["must"]:
            checks.append((bool(re.search(pat, text)), f"{'有' if re.search(pat, text) else '缺'}「{name}」", True))
    simp, examples, terms = language_drift(text)
    if kind in ("rewrite", "explain", "table"):
        drift_ok = simp < 2 and not terms
        checks.append((drift_ok, "台灣用語" if drift_ok else f"有簡體字或大陸用語（{examples or '、'.join(t for t, _tw in terms)}）"))
    checks = [c if len(c) == 3 else (c[0], c[1], False) for c in checks]
    passed = sum(1 for ok, _d, _c in checks if ok)
    score = passed / len(checks) if checks else 0.0
    if not any(ok for ok, _d, content in checks if content):     # 內容一項都不對：格式再好也是 0 分
        score = 0.0
    return {"score": score, "detail": "；".join(d for ok, d, _c in checks if not ok) or "全部符合"}


# ── 執行 ──
def _bench_messages(task, system_prompt):
    """系統提示詞＝使用者的全域提示詞＋題目所屬身分的角色提示詞（跟 AI 討論時一樣），讓分數反映實際使用的情況。"""
    sys_text = "\n\n".join(p for p in ((system_prompt or "").strip(), ROLES.get(task["role"], ROLES[DEFAULT_ROLE])["prompt"]) if p)
    return [{"role": "system", "content": sys_text}, {"role": "user", "content": task["prompt"]}]


def bench_single(endpoint, task, cancel, system_prompt="", options=None):
    """一個模型回答一題並評分。"""
    t0 = time.monotonic()
    res = stream_chat(endpoint, _bench_messages(task, system_prompt), cancel,
                      options=dict({"filter_think": True, "include_usage": True, "auto_retry": 1}, **(options or {})))
    item = {"task": task["id"], "role": task["role"], "title": task["title"], "model": endpoint.get("model", ""),
            "name": endpoint.get("name") or endpoint.get("model", ""), "cid": endpoint.get("id") or endpoint.get("model", ""),
            "elapsed": round(time.monotonic() - t0, 1), "status": res.get("status"), "answer": (res.get("text") or "")[:6000],
            "tokens": int(((res.get("usage") or {}).get("completion_tokens")) or 0)}
    if res.get("status") != "done":
        item.update(score=0.0, detail="呼叫失敗：" + (res.get("error") or res.get("label") or res.get("status") or ""))
        return item
    item.update(grade_answer(task, res.get("text", ""), cancel))
    return item


def bench_team(agents, hub, mode, task, cancel, system_prompt="", options=None):
    """把一題交給 AI 團隊用某種模式討論，評分最後的成果。"""
    t0 = time.monotonic()
    s = Session(agents, hub, mode, task["prompt"], lambda *e: None,
                cancel, lambda *_a: None, system_prompt=system_prompt, review_rounds=1,
                options=dict({"auto_route": False, "web_research": False, "filter_think": True, "auto_retry": 1}, **(options or {})))
    s.run()
    record = s.record
    final = ((record.get("final") or {}).get("text") or "")
    if not final and record.get("latest_answers"):           # 平行回答沒有整合：取第一份
        final = next(iter(record["latest_answers"].values()))
    main_text, _contrib = split_final(final)
    usage = record.get("usage_total") or {}
    item = {"task": task["id"], "role": task["role"], "title": task["title"], "mode": mode, "cid": "team:" + mode,
            "name": f"團隊・{mode}", "model": "", "elapsed": round(time.monotonic() - t0, 1), "status": record.get("status"),
            "answer": main_text[:6000], "tokens": int(usage.get("completion") or usage.get("completion_tokens") or 0),
            "disagreement": (record.get("final") or {}).get("disagreement", "")}
    if not main_text.strip():
        item.update(score=0.0, detail="團隊沒有產出成果：" + (record.get("error") or record.get("status") or ""))
        return item
    item.update(grade_answer(task, main_text, cancel))
    return item


def bench_agent(endpoint, cancel, system_prompt="", task=BENCH_AGENT_TASK, options=None):
    """Agent 實測：在暫存資料夾修好 calc.py。只給讀檔與改檔權限（不能執行指令、不能上網），改完用測試評分。"""
    import tempfile as _tf
    t0 = time.monotonic()
    item = {"task": task["id"], "role": "Agent", "title": task["title"], "model": endpoint.get("model", ""),
            "name": endpoint.get("name") or endpoint.get("model", ""), "cid": "agent:" + (endpoint.get("id") or endpoint.get("model", ""))}
    notices = []
    with _tf.TemporaryDirectory(prefix="ai協作實測agent_") as d:
        path = os.path.join(d, task["file"])
        with open(path, "w", encoding="utf-8") as f:
            f.write(task["source"])
        runner = AgentRunner(endpoint, Workspace(d, "bench"), emit=lambda k, *p: notices.append(p[0]) if k == "notice" and p else None,
                             approve=lambda *_a: ("deny", "實測時不允許這個動作"), ask=lambda _q: "請依你的判斷直接完成，不要再問。",
                             mode="build", permissions={"read": PERM_ALLOW, "edit": PERM_ALLOW, "shell": PERM_DENY, "web": PERM_DENY,
                                                        "council": PERM_DENY},
                             options=dict({"auto_retry": 1, "web_search": False, "max_steps": 20}, **(options or {})),
                             global_prompt=system_prompt)
        stop_link = threading.Event()
        if cancel is not None:             # AgentRunner.run() 開始時會清掉自己的停止旗標，所以用另一條執行緒轉送「停止」

            def relay():
                while not stop_link.wait(0.3):
                    if cancel.is_set():
                        runner.cancel.set()
                        return
            threading.Thread(target=relay, daemon=True).start()
        try:
            status = runner.run(task["prompt"])
        finally:
            stop_link.set()
        with open(path, encoding="utf-8") as f:
            fixed = f.read()
        changed = fixed != task["source"]
        passed, total, note = run_code_tests(fixed, task["tests"], task.get("check_mutation"), cancel=cancel)
    last = next((m for m in reversed(runner.messages) if m.get("role") == "assistant"), {})
    item.update(elapsed=round(time.monotonic() - t0, 1), status=status, answer=content_text(last.get("content"))[:3000],
                tokens=int(runner.usage.get("completion") or 0), steps=runner.usage.get("calls", 0),
                score=passed / total if total else 0.0,
                detail=f"測試通過 {passed}／{total}" + ("" if changed else "（檔案沒有被修改）") + (f"：{note}" if note else ""),
                notices=[n for n in notices if "⚠" in str(n)][:3])
    return item


def bench_plan(candidates, team=None, agent=None, repeats=1, roles=None, modes=()):
    """列出要跑的工作：[(種類, 參數)]。roles＝只測這些身分的題目（None＝全部）。"""
    tasks = [t for t in BENCH_TASKS if roles is None or t["role"] in roles]
    jobs = []
    for _r in range(max(1, int(repeats))):
        for ep in candidates:
            jobs += [("single", ep, t) for t in tasks]
        if team and team.get("agents"):
            for mode in modes:
                jobs += [("team", mode, t) for t in BENCH_TASKS if t["id"] in BENCH_TEAM_TASKS]
        if agent:
            jobs.append(("agent", agent, BENCH_AGENT_TASK))
    return jobs


def run_benchmark(candidates, cancel, on_event=None, team=None, agent=None, repeats=1, roles=None, modes=(),
                  system_prompt="", options=None, workers=4):
    """跑整套實測。candidates：要測的端點（每個是 _resolve 的結果）；team＝{"agents": […], "hub": …}；agent＝Agent 用的端點。
    on_event(kind, payload)：progress（(完成數, 總數, 說明)）、item（一題的結果）。回傳結果 dict（可交給 bench_summary）。"""
    import concurrent.futures as _cf
    jobs = bench_plan(candidates, team, agent, repeats, roles, modes)
    emit = on_event or (lambda *_a: None)
    items, done, lock = [], [0], threading.Lock()
    started = time.strftime("%Y-%m-%d %H:%M:%S")

    def work(job):
        kind, target, task = job
        if cancel.is_set():
            return None
        try:
            if kind == "single":
                return bench_single(target, task, cancel, system_prompt, options)
            if kind == "team":
                return bench_team(team["agents"], team.get("hub"), target, task, cancel, system_prompt, options)
            return bench_agent(target, cancel, system_prompt, task, options)
        except Exception as exc:                   # 一題出錯不影響其他題
            return {"task": task["id"], "role": task["role"], "title": task["title"], "cid": f"{kind}:{target}",
                    "name": str(target)[:60] if kind == "team" else (target.get("name") or target.get("model")),
                    "model": "" if kind == "team" else target.get("model", ""), "mode": target if kind == "team" else "",
                    "score": 0.0, "detail": f"{type(exc).__name__}：{exc}", "status": "error", "elapsed": 0, "tokens": 0}

    emit("progress", (0, len(jobs), "開始"))
    # 同一個模型的題目依序跑（避免同一個服務同時收到太多請求被限速），不同模型、團隊、Agent 平行
    lanes = {}
    for job in jobs:
        key = job[1].get("id", job[1].get("model")) if isinstance(job[1], dict) else "team"
        lanes.setdefault((job[0], key), []).append(job)

    def lane(lane_jobs):
        for job in lane_jobs:
            item = work(job)
            if item is None:
                return
            with lock:
                items.append(item)
                done[0] += 1
                n = done[0]
            emit("item", item)
            emit("progress", (n, len(jobs), f"{item.get('name')}・{item.get('title')}"))

    with _cf.ThreadPoolExecutor(max_workers=max(1, min(workers, len(lanes) or 1))) as pool:
        list(pool.map(lane, lanes.values()))
    return {"version": BENCH_VERSION, "app": APP_VERSION, "started": started, "finished": time.strftime("%Y-%m-%d %H:%M:%S"),
            "stopped": cancel.is_set(), "repeats": repeats, "items": items, "planned": len(jobs)}


def bench_summary(result):
    """整理成：每個受測者每個身分的平均分數、總分、平均秒數；每個身分的建議人選。"""
    rows = {}
    for it in result.get("items") or []:
        r = rows.setdefault(it["cid"], {"cid": it["cid"], "name": it.get("name"), "model": it.get("model", ""),
                                        "mode": it.get("mode", ""), "kind": ("team" if it["cid"].startswith("team:") else
                                                                             "agent" if it["cid"].startswith("agent:") else "single"),
                                        "roles": {}, "scores": [], "secs": []})
        r["roles"].setdefault(it["role"], []).append(float(it.get("score") or 0))
        r["scores"].append(float(it.get("score") or 0))
        r["secs"].append(float(it.get("elapsed") or 0))
    table = []
    for r in rows.values():
        table.append({"cid": r["cid"], "name": r["name"], "model": r["model"], "mode": r["mode"], "kind": r["kind"],
                      "roles": {k: sum(v) / len(v) for k, v in r["roles"].items()},
                      "score": sum(r["scores"]) / len(r["scores"]), "secs": sum(r["secs"]) / len(r["secs"]), "n": len(r["scores"])})
    table.sort(key=lambda x: (x["kind"] != "single", -x["score"], x["secs"]))
    best = {}
    for role in BENCH_ROLES:
        ranked = sorted((r for r in table if r["kind"] == "single" and role in r["roles"]),
                        key=lambda r: (-r["roles"][role], r["secs"]))
        if ranked:
            best[role] = ranked[0]
    # 團隊模式 vs 同一批題目的單一模型最佳成績：討論到底有沒有幫上忙
    team_vs = []
    singles = [r for r in table if r["kind"] == "single"]
    for r in (x for x in table if x["kind"] == "team"):
        same = [it for it in result["items"] if it["cid"] == r["cid"]]
        ids = {it["task"] for it in same}
        best_single = None
        for s in singles:
            sub = [float(it.get("score") or 0) for it in result["items"] if it["cid"] == s["cid"] and it["task"] in ids]
            if sub:
                avg = sum(sub) / len(sub)
                if best_single is None or avg > best_single[1]:
                    best_single = (s["name"], avg)
        team_vs.append({"mode": r["mode"], "score": r["score"], "secs": r["secs"], "best_single": best_single})
    return {"table": table, "best": best, "team_vs": team_vs}


def _pct(v):
    return f"{v * 100:.0f}%"


def bench_report_md(result):
    """實測報告（Markdown）。"""
    s = bench_summary(result)
    roles = list(BENCH_ROLES)
    lines = [f"# 正確率實測報告", "", f"- 時間：{result.get('started')} ～ {result.get('finished')}",
             f"- 程式版本：{result.get('app')}；題庫版本：{result.get('version')}；每題重複 {result.get('repeats')} 次",
             f"- 完成 {len(result.get('items') or [])}／{result.get('planned')} 題" + ("（中途停止）" if result.get("stopped") else ""),
             "- 評分全部用規則自動完成（程式跑測試、比對標準答案、檢查埋好的錯與格式），沒有用 AI 當裁判。", ""]
    singles = [r for r in s["table"] if r["kind"] == "single"]
    if singles:
        lines += ["## 單一模型", "", "| 模型 | " + " | ".join(roles) + " | 總分 | 平均秒數 |",
                  "|---|" + "---|" * (len(roles) + 2)]
        for r in singles:
            cells = [_pct(r["roles"][k]) if k in r["roles"] else "—" for k in roles]
            lines.append(f"| {r['name']}（{short_model(r['model'])}） | " + " | ".join(cells) + f" | **{_pct(r['score'])}** | {r['secs']:.1f} |")
        lines += ["", "### 各身分建議人選（分數相同取較快的）", ""]
        for role, r in s["best"].items():
            lines.append(f"- {role}：{r['name']}（{short_model(r['model'])}），{_pct(r['roles'][role])}")
        lines.append("")
    if s["team_vs"]:
        lines += ["## 團隊討論模式", "", "| 模式 | 分數 | 平均秒數 | 同樣題目單一模型最佳 |", "|---|---|---|---|"]
        for t in s["team_vs"]:
            bs = f"{t['best_single'][0]} {_pct(t['best_single'][1])}" if t["best_single"] else "—"
            lines.append(f"| {t['mode']} | **{_pct(t['score'])}** | {t['secs']:.1f} | {bs} |")
        lines += ["", "團隊分數比單一模型最佳還低時，代表討論沒有幫上忙（常見原因：主持 AI 比成員弱、成員都用同一家模型、互評時被多數帶偏）。", ""]
    agents = [r for r in s["table"] if r["kind"] == "agent"]
    if agents:
        lines += ["## Agent", ""]
        for r in agents:
            lines.append(f"- {r['name']}（{short_model(r['model'])}）：{_pct(r['score'])}，平均 {r['secs']:.1f} 秒")
        lines.append("")
    lines += ["## 每題明細", "", "| 受測者 | 題目 | 分數 | 秒數 | 說明 |", "|---|---|---|---|---|"]
    for it in sorted(result.get("items") or [], key=lambda x: (x["cid"], x["task"])):
        detail = str(it.get("detail", "")).replace("|", "｜").replace("\n", " ")[:200]
        lines.append(f"| {it.get('name')} | {it.get('title')} | {_pct(float(it.get('score') or 0))} | {it.get('elapsed', 0)} | {detail} |")
    return "\n".join(lines) + "\n"


def save_bench_result(result, folder=BENCH_DIR):
    """存成 JSON（完整紀錄，含每題的回答）與 Markdown 報告，回傳 Markdown 路徑。"""
    os.makedirs(folder, exist_ok=True)
    base = os.path.join(folder, "實測_" + time.strftime("%Y%m%d_%H%M%S"))
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    with open(base + ".md", "w", encoding="utf-8") as f:
        f.write(bench_report_md(result))
    return base + ".md"
