# ═════════════════════════ 1. 常數、路徑、角色、主題 ═════════════════════════
APP_NAME = "AI 協作工作台"
APP_VERSION = "6.20.1"

FROZEN = bool(getattr(sys, "frozen", False))          # 用 PyInstaller 打包成 .exe 時
for _stream in ("stdout", "stderr"):          # 打包成視窗程式（--windowed）時沒有主控台，print 會出錯
    if getattr(sys, _stream) is None:
        setattr(sys, _stream, open(os.devnull, "w", encoding="utf-8"))
APP_DIR = os.path.dirname(os.path.abspath(sys.executable if FROZEN else __file__))
SETTINGS_PATH = os.path.join(APP_DIR, "多AI工作台設定.json")      # 沿用舊檔名，舊設定直接可用
SETTINGS_BACKUP_DIR = os.path.join(APP_DIR, "備份", "設定")
RECORDS_DIR = os.path.join(APP_DIR, "紀錄")
LOG_DIR = os.path.join(APP_DIR, "日誌")

REQUEST_TIMEOUT = 180          # 聊天請求：每次等待資料的秒數上限（推理型模型可能很慢）
MODELS_TIMEOUT = 30
TEST_TIMEOUT = 60              # 「測試模型」等待第一筆資料的秒數
MAX_PLAIN_CHARS = 2_000_000
MAX_ATTACH_BYTES = 300_000
QUOTE_LIMIT_DEFAULT = 8000
HISTORY_TURNS = 6
AUTO_RETRY_CODES = (429, 500, 502, 503, 504)      # 500：NVIDIA 的「Failed to generate completions」通常是暫時的
THINK_LIMIT_DEFAULT = 240      # 思考超過這麼多秒還沒開始回答，就改成「不思考」重新回答（0＝不限制）
LONG_MAX_TOKENS = 8192         # 回答被服務預設的長度上限截斷時，接續時改用的上限
AUTO_RETRY_MAX_WAIT = 30
MAX_AGENTS = 24

NVIDIA_HOST = "integrate.api.nvidia.com"
DEFAULT_NVIDIA_ENV = "NVIDIA_API_KEY"
DEFAULT_SYSTEM_PROMPT = "請一律使用台灣繁體中文回答，避免簡體字與中國大陸用語；專有名詞可保留原文。"

HUB_ID = "__hub__"
FINAL_ID = "__final__"
CONTEXT_ID = "__context__"

# 角色：預設顏色、圖示、角色提示詞（顏色可在「外觀」分頁自訂）
ROLES = {
    "一般助理": {"color": "#5B7FC4", "icon": "spark",
              "prompt": "你是一位全方位助理，回答要完整、正確、條理清楚。"},
    "程式專家": {"color": "#4C82EE", "icon": "code",
              "prompt": "你是資深軟體工程師，著重程式正確性、安全性、效能與可維護性，必要時提供可執行的程式碼。"},
    "研究分析": {"color": "#26A67A", "icon": "search",
              "prompt": "你是研究分析師，著重事實查核、數據與推理，清楚區分已知事實與推測。"},
    "對話溝通": {"color": "#8572F0", "icon": "chat",
              "prompt": "你擅長溝通與說明，用淺顯易懂的方式解釋，並顧及讀者感受。"},
    "文件撰寫": {"color": "#EC7D5C", "icon": "doc",
              "prompt": "你是專業撰稿與編輯，著重結構、用詞精準與可讀性，產出可直接使用的文件。"},
    "資料處理": {"color": "#1FAAA5", "icon": "db",
              "prompt": "你是資料工程與資料分析專家，著重資料結構、計算正確與可重現的步驟。"},
    "審查批判": {"color": "#D8922A", "icon": "check",
              "prompt": "你是嚴格的審查者，專門找出錯誤、漏洞、風險與遺漏，並提出具體修正。"},
}
DEFAULT_ROLE = "一般助理"
ROBOT_LOOKS = tuple(ROLES) + ("主持", "Agent")      # 拓樸圖裡每種身分各有一款 Q 版機器人造型

# 拓樸圖的動態角色（「機器人動畫」資料夾，2026-10 原創）：每個身分、每種尺寸一張橫向長條 PNG，
# 前 30 格是 2.4 秒的循環動畫（每格 80 毫秒），第 31 格是停用時的淡灰定格。
# 找不到資料夾或這台電腦的 Tk 讀不了 PNG 時，改用程式畫的造型，功能不受影響。
ROBOT_SPRITE_DIRNAME = "機器人動畫"
ROBOT_SPRITE_KEYS = {"一般助理": "assist", "程式專家": "coder", "研究分析": "research", "對話溝通": "comm",
                     "文件撰寫": "writer", "資料處理": "data", "審查批判": "review", "主持": "hub", "Agent": "agent"}
ROBOT_SPRITE_SIZES = (32, 44, 56, 72, 88, 108, 132, 160, 196)
ROBOT_SPRITE_FRAMES = 30
ROBOT_SPRITE_STILL = 24          # 關閉動畫時顯示的那一格（眼睛張開、動作完整）


def robot_sprite_dirs():
    """動態角色素材的位置：程式（或 exe）旁的資料夾優先，其次是打包進 exe 的那一份。"""
    dirs = [os.path.join(APP_DIR, ROBOT_SPRITE_DIRNAME)]
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        dirs.append(os.path.join(bundle, ROBOT_SPRITE_DIRNAME))
    return [d for d in dirs if os.path.isdir(d)]


def robot_sprite_size(want):
    """挑最接近的預先算好的尺寸（用比例比較，小尺寸時差幾個像素也看得出來）。"""
    want = max(1.0, float(want))
    return min(ROBOT_SPRITE_SIZES, key=lambda size: abs(math.log(want / size)))


def robot_sprite_file(look, want, dirs=None):
    """回傳（長條圖路徑或 None, 尺寸）。"""
    key = ROBOT_SPRITE_KEYS.get(look, ROBOT_SPRITE_KEYS[DEFAULT_ROLE])
    size = robot_sprite_size(want)
    for d in robot_sprite_dirs() if dirs is None else dirs:
        path = os.path.join(d, f"s{size:03d}", f"{key}.png")
        if os.path.isfile(path):
            return path, size
    return None, size

# 程式圖示（原創 Q 版主持 AI 頭像，2026-10 繪製）：視窗左上角與打包 exe 用。內容是 PNG 的 base64。
APP_ICON_PNG = {
    16: (
        "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAADOklEQVR42lWSX0idZQCHn/f93u+ves5RN+u4lkF/FlLUqJsVU5gr"
        "Q/Nig3YVeZVRLnYRQRSbBFtdRQxs1Ai6cN3MZCRFaSBbBetiUCbMSQtNxelEd/75fd/5znfet4sxqOf+Bw8/HgHQPWJUbjs8bln0"
        "QOpqbYQAiqECIBukGEBKYcCuptrM3B/Pj54//2xNdA8uepnG3EWvITcQhnWSmsRRNVJtsf+RCgC/32xEyTpJauPYmiCwiHeK33tO"
        "6RXV1JR70w9yA6VSubbvgZL1+EMRYZrHceDQvj8A2JM/QJLUCNQyN5Z8FlYz9Uwm2x9XzHEloFenia6mSj7ZsSWPdN/iyl8Pk8Qx"
        "11afA2B3LsXxArof/ZtLJs+fSy1Gp4k2UvSKgeHCT8oJDqdJRSNsGVUtsg0RrTmB5wBAnMBWwVDc8fFdDSbRym6UaRpevvsSIISg"
        "mtR4/qmIl7pyNDXa1FMDgKUE5UqNqV8K/DarcBxxb4YCUJZgpwJHDxveOLabG/PzLC+s4gXBXYMw5MGOPYy81cmX32wzPi3IuoI0"
        "BSWlplxJafRDho61M3ruAic/+pymtt0U/lkBoLljL8WNTT5873VOvD3I1K9rlCouvq2R62uL2GadvoMW1Tjm7OgYQx+/z+mr4+x9"
        "upPH9ncyenWc/jMfcO6zC4RRSF+XwmGD9bUlZKWc8MLBNvp77qNYjpDCsJnNEboKZVmk0mLNVTitObQwFMsRfYfaeLGrjUoYoxoC"
        "xfTP67jK57UjzeSzzSx/8gXXL15iZ/02AF+9+i5NK5vksy3ksgFfT95i6kpE4DtIx5ZsbEaMTSyjjc3IqWHirQJzk1P4+Tx+eztz"
        "k1NEW3cYOTmMkA5jE8us3w5xbYnShnrgW7pUUubM6E1Ov9PFtwc6KW6X0LUEAGk7ZFoy7Mru4tSnC5R3LDIZpWtJta4QTCPc3sAL"
        "az9cLomVtVle7mmjtbkZY+41AtvzVb6bmWVuISHwrDrCtSGcFt2Di15S2ZpwvJY+oyOi2FBN6ggM/8UgcB0L3xMI6VOLt3/UMjkq"
        "AJ4ZumZ7d9wTCNMjROpKYYTR/B8JxghjjKoaIWYKWpy9Pv5E8i9/u2n789j9DQAAAABJRU5ErkJggg=="
    ),
    32: (
        "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"
        "CwEAYAAAAABJRU5ErkJggg=="
    ),
    48: (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAMAAABg3Am1AAABIFBMVEVmWnRfiJyOT3Ymdu5xdohNZuSfrdgfH39jOl9ne9G8Yo3F"
        "Yo/2yVL/6ZDL+f0/dIs5U81QcPdNbPGIxdX///9Ma/A6VM37/PwAAAAdJUIUGDfM1fBMbe4iKUUyTcs5VMpUcvgsNVAaIT7BzPOM"
        "+P7o6vBuh/KXqfCF6vuEmOk7VcxNbvCntvNGXs2AhZVVVapQaNI8Xe5BW9dVVf9tgds6VM5ObPL47Mo6U81cc9VifvV8kurGx87c"
        "4u1Ca4SsuNv/1VgHCipptcq1wvKw9/04Qlw3VW84U8pNau5Zlql41OSJmtX+4nD/8pn69c4vSmU6VdBObfBObfNHdIt/f/9mr8Jw"
        "xtl76fyQk6G8wdDa2NsAAP8/P78/f79HTWVISNqzurIUAAAAYHRSTlP///8D/wv/A///////////n0an/wH9/f8A////Hf/+J/7/"
        "//////////8dK////wP+/ycD/9TO/0r//////////////////3Nq/////////6dJm/8C////////AQQE/wfAtPw/AAADOElEQVR4"
        "2qWWiXKiQBCGR3NustlbYIZAuAQ0bHQ3Kt5H1MQjMfe9m7z/W2zPIEgCmlTtbxWOM/9nd09DMUiguqKXle35+gHrOWZF9LIvCF8v"
        "SqkFKl2cM5sH7Au7JUVRFgGwXNplBAB/hUFqoXvKpAZgBWBfGMTYq9UYZABmBPnE/J3lulYMAVmhq6tSNEDVbbfdaAyltLSEhPPA"
        "b1qmknF0Mc3zk3Z7wvNpUXcyCkwHxDnUcOED5mTL5UHphiiKrguXRpr+drcmPqF8E1AuyEg//nisw/cvKkVhX6FpL6cVtB1k6Jy0"
        "T/iuY2Vq5lS1jOV0eZh2AtN2CEh1HxyHJRFW2nEeujPPbhjwolbNjGU5IMvKmNXXOxgF3tD/AwpUGlLNVBYCVUtvvCg7nRZnbYsC"
        "GZGPkWjNA6J76u9sPGDN8YOsOKDG/PXlvhpSH9VZjFoM0KUrCUI0jLWpYETIMp3XlQhg0gCJjiQRQrCEQRKGoSR1lsMhZoBF84F1"
        "cpq4xBoFNPw5cQowuYclJwCyHJUst2AWEYk0ez3jhkXA3z8ZRhOmECzdczIz/vaASqGgw6yqYdXmP90aCRoqwfO2YauaptJmFAqV"
        "AJDz8HTRnqmYNI2eYRs3tN6bXs+2IQSWoDzqyMs+YIm6PgUujVtwjWhGIza8nALgsPwINIAPHBo2uA4IxuSADQ99AD55v4YggiZR"
        "m0FdlDU8NBJhVgMA6rU9grxBpDmyr1UiYfV1DcEuPUF4jagSYW3DRFKJBu3r01aHd4m2gfXhjqDNpES7Bv2mvdCk5CYie7DUAksI"
        "AGRMbwB1fSPJenY9HB6wQXJjnZbAj72+hYA8LaKuQVIg3B8OT70RYXdGozIFdnyAk1fpXfmAiKdOp+MNntj9vTp1hQAu7z2f9bu9"
        "kO7q3lOal6OA/EGc98A1Cr6fy6Jc8U1CnPmLz0j4wgVEfrUR8/etIB+OO4P3Q5kLqTJu6WJIemtc4WZ+riygx1lOrIPczxfi5JCd"
        "Ky49wktxh3u3yvBShBPB0Xv9R2CGF/uf9xJHYGVHh5xQLr5tL5bZ8YQdTnLCWvlsIVM8K695xxkGsOFKdmeuss/B8ecfzz0GygOH"
        "0rkAAAAASUVORK5CYII="
    ),
    64: (
        "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAMAAACdt4HsAAABIFBMVEUtX91kjqNPVWtKbeCer+udVX45Z4Bxdohqtsh/7f+JjZwk"
        "SLZISLapWIJMa+86VM78/f0AAAAdJUJTcvoUGTfN1u8iKEWE7PxNbO85VM3n6u+puPVwiO3CzfoxTMsZIT6M9/45U8y0ucwrNlIA"
        "AP9Na/CbqdZWXHJOZtGXqOy3xPpTVf3EytfP1d3d4u392GwwSmVCaoJObPK4w93HY5D/9a86VM9NbPBkeNKFmfAA//85VM1ON1lh"
        "p7pvwtS2+f75zVX90Vv/7JP/9tkzU8uFltU/P784V3E5Wu0/f/9LautHe5RuQmdpbYF/f/9ge/Bwg9J/lfd00uXS+/3976sAf387"
        "VdBVVapEXc5PbvRNbO9bcNBiZnuTlqQAAH8/Vb/S89E4AAAAYHRSTlMT//8H/////////wcH//7+/wD//v////+4xv////////+1"
        "//8Byf//////A////////3P///+Klf//AXD//////////xP/BP//BBT///8C////////AkgD/zlU////AgzzVi4LAAAENElEQVR4"
        "2r2XaVfbOhCGHUpvl9uL7Fiyg/fEBmzjLCQkBAh7oEBLoQs7tP//X1xJtmPZsUPCh76HAxpZ82hmtHDECZG2zoQZdLYVt7jo7ypu"
        "3rc3KlNoo33/hjowAGdVOG8viVNrqX0ufHMSgOMIDwviwgwSF9o46xjgbN1uzOROEZU3lMCR+FcrM/tTAsmCI+Uonv9yfv6ymEBL"
        "j389iEWJany3y2tF5RHb2Jnbcs4LozzVD/f3D/XTwgHnzjfuTGjnTCBqm56q+nwTi/dV1dvU8kZtCGecwy0xn0QV6d89XeEjdQ8O"
        "unFb0b3vOlJTIJyCcM/2oG7zkA5uIKT7voqOjpDq+zpCDQo9bHYRG8IDBrAZaEcHzf1fvph0aVoyWvR/7TcPjrRUDlxqDccBp6cT"
        "ARUMqExKgWpCCktZQLaIrHKKOA7ILKOvY/mFyzgBMO15mAQg5z7b+nsRiJfamC7FqQGa1wnQmIKOp00F0GoodxXxOqKa9jLAqxe4"
        "U0TdExde2kj8RDVqkzdSrcHzMxDGAF48vxLUMgrizBpeMUCrh2OCJwmOSZoLwq91rRBQC2cpQViWxlSG8F0YXa0IEAVwAfFo4sFI"
        "ol1wjg5AWgHAowE8Q+JKgk78I0uCH2kIXgGgQ7/SmeE/OztrI0JimbTKnZELAVRBJJcW6SMJAO7sWZZVMiP/kSXBEs3BjX0WGYDx"
        "SOkruALwy0/+pyxbXwiMtaIqoL6RBbjk7qMA28Tl+rHH89jlR1hAxjJtUidERrsswNikB46UAANgS5b3LBmrhRNnLcymAKJNIwEY"
        "LtJ1pMcRwJYlfyAeVghIrBigk/GukUTg4a4EYNpyJNskUbNWDMA/KpOCygLwpLs0ZGuXLl3KygekU8Auny3sY1mfQwBrFaSQFJEC"
        "JLiGHeR4J8WWNAIQeUb+Ms7hcWYZ2mtrdrITQ8vEZJvPXUa6kVwKeIdP4mBQNiE0k7NArcEAn8gnCng0cnYiuKNnIYDS2/X1r2Z4"
        "Gs3oTEmS+XV9/T8J1uiY3K0MwLwS7uUQQEIv7bZauyVaPAJ4C1foea6BXIBx1QiPIxxIYfim/V6W39uRIQ1gmd4YjWMjPwK3E15Z"
        "9uhCMqFtQ3N0JdnhpZZkkAEYx+GdrFyUYY7KT+GNxwSQAYC76FLk688XKxldPEc3rtK5A0UA4zFQXvq/oNT7RhrQAwyhX1de8r9i"
        "/EEVA7ZBitCZSFACdn4AehjAgRTBXUaFCAXNuyl/cCNwzieQUX85QIqSoeAOFCz3Qdof4PlP0jmQIAz36nh5TMdXbtYdZ3DCOc4Q"
        "jMkwjCm6ABg61+TBsQ1eqW3hNnzyVF/nXw2fPIJzO3wVYTF+dAmO8O8rCNU/wu/Rw1OYvQ7bAvWPn76cMOzN4t7jhGsn+/j+c9Or"
        "Lk6hau9mmH18kyBOZnn+n1zHrf8BvwBYvnz4/QcAAAAASUVORK5CYII="
    ),
    256: (
        "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"
    ),
}


def icon_ico_bytes():
    """把內嵌的 PNG 組成 Windows 的 .ico（Windows Vista 以後支援 PNG 格式的圖示），打包 exe 時用。"""
    import struct
    entries = [(n, base64.b64decode(APP_ICON_PNG[n])) for n in sorted(APP_ICON_PNG)]
    head = struct.pack("<HHH", 0, 1, len(entries))
    offset, dirs, blobs = 6 + 16 * len(entries), b"", b""
    for n, data in entries:
        dirs += struct.pack("<BBBBHHII", n % 256, n % 256, 0, 0, 1, 32, len(data), offset + len(blobs))
        blobs += data
    return head + dirs + blobs

MODE_PARALLEL = "平行回答"
MODE_SYNTH = "平行＋彙整"
MODE_REVIEW = "互評修正＋彙整"
MODE_RELAY = "接力精修"
MODE_PLAN = "分工合作"
MODES = [MODE_PARALLEL, MODE_SYNTH, MODE_REVIEW, MODE_RELAY, MODE_PLAN]
MODE_HELP = {
    MODE_PARALLEL: "每位 AI 各自回答同一題，方便比較。",
    MODE_SYNTH: "各自回答後，由主持 AI 整合成一份最終成果。",
    MODE_REVIEW: "各自回答 → 匿名互評、排名並修正（可多輪，意見穩定會提前結束）→ 主持 AI 整合。",
    MODE_RELAY: "依端點順序接力，每位 AI 以專長改進前一位的成果。",
    MODE_PLAN: "主持 AI 先拆解題目、依角色分派子任務 → 各自完成 → 主持 AI 整合。",
}

DEFAULT_TEMPLATES = {
    "空白提示詞": "",
    "摘要整理": "請整理以下內容，列出重點、結論與待辦事項：\n\n",
    "回覆要用繁體中文": "請以自然、通順的台灣繁體中文回覆，並保留專有名詞：\n\n",
    "程式碼審查": "請審查下方貼上（或用「附加檔案」插入）的程式碼，優先指出錯誤、安全問題與可維護性問題，並提供具體修正建議：\n\n",
    "方案比較": "針對以下問題，請提出至少兩種可行方案，比較優缺點、成本與風險，最後給出建議：\n\n",
}

TEXT_FILE_EXTS = (".txt", ".md", ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".csv", ".html", ".css",
                  ".xml", ".yaml", ".yml", ".ini", ".toml", ".cs", ".java", ".c", ".cpp", ".h", ".go",
                  ".rs", ".sql", ".ps1", ".bat", ".sh", ".log", ".vue", ".kt", ".swift", ".rb", ".php")

# ── 主題（可在「外觀」分頁切換，並可再自訂顏色與字體） ──
THEME_KEYS = {          # 可自訂的顏色與中文名稱
    "accent": "主色", "bg": "視窗背景", "surface": "卡片背景", "surface2": "輸入框背景", "border": "邊框",
    "text": "文字", "muted": "次要文字", "canvas": "拓樸圖背景", "grid": "拓樸圖格點", "line": "連線",
    "success": "成功", "danger": "錯誤", "warning": "警告",
}
THEMES = {
    "晨光白": dict(dark=False, bg="#F2F4F8", surface="#FFFFFF", surface2="#F7F8FB", border="#E2E6EE",
                text="#1C2433", muted="#6E7889", accent="#4E6CF0", success="#16A06A", danger="#DB4F4A",
                warning="#D9962B", canvas="#F7F8FC", grid="#E5E9F0", line="#C9D1DE", shadow="#E4E8EF",
                visor="#1E2542", eye="#86EEFF", robot="#FFFFFF", robot_line="#D4DAE5"),
    "暖杏": dict(dark=False, bg="#F5EFE8", surface="#FFFCF8", surface2="#FAF5EF", border="#E8DDD0",
               text="#2E2620", muted="#8A7B6E", accent="#D0683E", success="#3D9A63", danger="#C94A3F",
               warning="#C98A1F", canvas="#FBF7F2", grid="#EEE4D8", line="#D6C8B7", shadow="#EBE0D3",
               visor="#2C2420", eye="#FFD9A0", robot="#FFFFFF", robot_line="#E1D4C5"),
    "薄荷綠": dict(dark=False, bg="#EEF5F2", surface="#FFFFFF", surface2="#F5FAF8", border="#DAE7E2",
                text="#17302A", muted="#6A8079", accent="#1E9A82", success="#1F9D60", danger="#D2554C",
                warning="#CF9A2E", canvas="#F4FAF8", grid="#DFEBE7", line="#C0D5CE", shadow="#DFEAE6",
                visor="#15302A", eye="#9CFFE3", robot="#FFFFFF", robot_line="#D0E0DA"),
    "櫻花粉": dict(dark=False, bg="#F8F0F3", surface="#FFFFFF", surface2="#FCF6F9", border="#EEDCE4",
                text="#2F1F27", muted="#8C7380", accent="#D6538B", success="#3A9E6E", danger="#D04848",
                warning="#D29A33", canvas="#FCF7FA", grid="#F0E2E9", line="#DCC4CF", shadow="#EFE1E8",
                visor="#2E1E28", eye="#FFC7E1", robot="#FFFFFF", robot_line="#E8D5DE"),
    "深夜藍": dict(dark=True, bg="#0E1420", surface="#161E2E", surface2="#1B2436", border="#273249",
                text="#E4EAF4", muted="#8E9BB2", accent="#6E8BFF", success="#3CCB8A", danger="#FF6B6B",
                warning="#F2B44C", canvas="#101827", grid="#1A2438", line="#34425E", shadow="#0A0F19",
                visor="#070B14", eye="#7DF4FF", robot="#E9EEF7", robot_line="#9AA8C0"),
    "石墨灰": dict(dark=True, bg="#141414", surface="#1E1E1F", surface2="#252527", border="#343437",
                text="#ECECEC", muted="#9C9CA2", accent="#E3A341", success="#4CC38A", danger="#F06A63",
                warning="#E3A341", canvas="#171718", grid="#232325", line="#3E3E42", shadow="#0D0D0D",
                visor="#0B0B0C", eye="#FFE3A3", robot="#EFEFEF", robot_line="#A5A5AA"),
}
DEFAULT_THEME = "晨光白"
DEFAULT_UI_FONT = "Microsoft JhengHei UI" if sys.platform == "win32" else "Noto Sans CJK TC"
DEFAULT_MONO_FONT = "Consolas" if sys.platform == "win32" else "DejaVu Sans Mono"


def mix(color_a, color_b, t):
    """兩個 #RRGGBB 顏色依比例混合（t=0 → a，t=1 → b）。"""
    try:
        a = [int(color_a[i:i + 2], 16) for i in (1, 3, 5)]
        b = [int(color_b[i:i + 2], 16) for i in (1, 3, 5)]
    except (ValueError, TypeError, IndexError):
        return color_a
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(a, b))


def safe_replace(tmp, path, tries=4):
    """用暫存檔取代正式檔。Windows 上防毒或索引程式偶爾會暫時鎖住檔案（WinError 5／32），稍等重試，不要直接存檔失敗。"""
    for i in range(tries):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.25 * (i + 1))


def valid_color(value):
    return isinstance(value, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", value) is not None


class Theme:
    """目前使用的配色：主題預設值＋使用者自訂覆寫。"""

    def __init__(self, prefs=None):
        self.update(prefs or {})

    def update(self, prefs):
        name = prefs.get("theme") if prefs.get("theme") in THEMES else DEFAULT_THEME
        self.name = name
        self.c = dict(THEMES[name])
        for key, value in (prefs.get("color_overrides") or {}).get(name, {}).items():
            if key in THEME_KEYS and valid_color(value):
                self.c[key] = value
        dark = self.c["dark"]
        self.c["accent_hover"] = mix(self.c["accent"], "#000000" if not dark else "#FFFFFF", 0.14)
        self.c["accent_soft"] = mix(self.c["accent"], self.c["surface"], 0.86 if not dark else 0.78)
        self.c["hover"] = mix(self.c["accent"], self.c["surface"], 0.93 if not dark else 0.86)
        self.c["hub"] = self.c["accent"]
        self.c["hub_light"] = mix(self.c["accent"], self.c["canvas"], 0.82 if not dark else 0.72)
        self.c["side"] = self.c["bg"]                     # 左右側欄
        self.c["canvas_chat"] = self.c["surface"]         # 對話串背景
        self.roles = {}
        custom_roles = prefs.get("role_colors") or {}
        for role, info in ROLES.items():
            color = custom_roles.get(role) if valid_color(custom_roles.get(role)) else info["color"]
            self.roles[role] = color
        self.show_grid = prefs.get("show_grid", True)
        self.animate = prefs.get("animate", True)

    def __getitem__(self, key):
        return self.c[key]

    @property
    def dark(self):
        return self.c["dark"]

    def role_color(self, role):
        return self.roles.get(role, self.roles[DEFAULT_ROLE])

    def role_light(self, role):
        return mix(self.role_color(role), self.c["canvas"], 0.80 if not self.dark else 0.70)

    def status(self, key):
        """狀態 → (文字, 顏色)。"""
        c = self.c
        table = {
            "idle": ("待命", c["muted"]), "disabled": ("停用", mix(c["muted"], c["surface"], 0.35)),
            "queued": ("排隊中", c["muted"]), "connecting": ("連線中", c["accent"]),
            "thinking": ("思考中", "#8A6CF0"), "generating": ("生成中", c["accent"]),
            "retry": ("等待重試", c["warning"]), "done": ("完成", c["success"]), "error": ("失敗", c["danger"]),
            "timeout": ("逾時", c["danger"]), "stopped": ("已停止", c["muted"]), "empty": ("沒有內容", c["warning"]),
            "testing": ("測試中", c["accent"]), "ok": ("可用", c["success"]), "bad": ("不可用", c["danger"]),
            "rate": ("等待配額", c["warning"]), "paused": ("暫停中", c["warning"]),
        }
        return table.get(key, table["idle"])


ACTIVE_STATES = {"connecting", "thinking", "generating", "retry", "testing", "rate"}
