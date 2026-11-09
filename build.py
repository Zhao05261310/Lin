"""把 src/ 的各段組合成單一檔案 AI協作.py（程式本身仍是單檔，只用 Python 內建模組）。
用法：python build.py           → 組合
      python build.py --test    → 組合後跑自我測試"""
import os, subprocess, sys
ROOT = os.path.dirname(os.path.abspath(__file__))
PARTS = ["s0.py", "s1.py", "s2.py", "s3.py", "s3b_agent.py", "s3c_mcp.py", "s3d_cli.py", "s3e_extras.py", "@train_scripts", "s3f_train.py", "s4.py", "s4b_bench.py", "s5.py",
         "s5b_sessions.py", "s6.py", "s7.py", "s8.py"]


def train_scripts_part():
    """把 src/train_scripts/*.py 嵌成 TRAIN_SCRIPTS 字典（程式執行時再寫成檔案交給訓練用的 Python）。"""
    folder = os.path.join(ROOT, "src", "train_scripts")
    items = []
    for name in sorted(os.listdir(folder)):
        if name.endswith(".py"):
            with open(os.path.join(folder, name), encoding="utf-8") as f:
                items.append(f"    {name[:-3]!r}: {f.read()!r},\n")
    return "\n\n# 訓練腳本（由 build.py 從 src/train_scripts/ 嵌入；請改那裡的檔案）\nTRAIN_SCRIPTS = {\n" + "".join(items) + "}\n"


out = "".join(train_scripts_part() if p == "@train_scripts" else open(os.path.join(ROOT, "src", p), encoding="utf-8").read()
              for p in PARTS)
compile(out, "AI協作.py", "exec")
# 各段接成一個檔案時，後面定義的同名函式會默默蓋掉前面的（v6.15 就這樣把 model_size_b 蓋掉、弄壞了模型推薦）→ 直接擋下
import ast, collections
_names = collections.Counter(n.name for n in ast.parse(out).body
                             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
_dups = {k: v for k, v in _names.items() if v > 1 and k not in ("stream_chat", "stream_agent_turn")}   # 這兩個是刻意包一層（用量統計）
for _cls in ast.walk(ast.parse(out)):                    # 類別裡的方法也一樣（例如主視窗的幾千行）
    if isinstance(_cls, ast.ClassDef):
        _m = collections.Counter(n.name for n in _cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
        _dups.update({f"{_cls.name}.{k}": v for k, v in _m.items() if v > 1})
if _dups:
    sys.exit("有重複定義的函式或類別（後面的會蓋掉前面的）：" + "、".join(f"{k}（{v} 次）" for k, v in _dups.items()))
with open(os.path.join(ROOT, "AI協作.py"), "w", encoding="utf-8", newline="\n") as f:
    f.write(out)
import hashlib
with open(os.path.join(ROOT, "AI協作.py.sha256"), "w", encoding="utf-8", newline="\n") as f:   # 更新時比對用
    f.write(f"{hashlib.sha256(out.encode('utf-8')).hexdigest()}  AI協作.py\n")
print(f"已組合 AI協作.py（{out.count(chr(10)):,} 行）")
if "--test" in sys.argv:
    sys.exit(subprocess.call([sys.executable, os.path.join(ROOT, "AI協作.py"), "--selftest"]))
