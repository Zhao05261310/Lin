"""AI 協作：把合併後的語言模型（Hugging Face safetensors）轉成 GGUF，給 Ollama 用。
為什麼自己轉：新版 Ollama（0.40 起）直接匯入 safetensors 需要 MLX 元件，Windows 版實測沒有附；GGUF 則是每一版 Ollama 都能讀的格式。
支援 Llama（含 SmolLM2）與 Qwen2（Qwen2.5）架構；權重存成 Q8_0（正規化層用 F32），只需要 numpy 與 safetensors。
用法：python export_gguf.py --config config.json   （config：model_dir、out_path）"""
import glob
import os
import struct

# @@COMMON@@

ALIGN = 32
T_UINT32, T_INT32, T_FLOAT32, T_BOOL, T_STRING, T_ARRAY, T_UINT64 = 4, 5, 6, 7, 8, 9, 10
GGML_F32, GGML_F16, GGML_Q8_0 = 0, 1, 8
FILE_TYPE_Q8_0 = 7
TOKEN_NORMAL, TOKEN_CONTROL, TOKEN_USER_DEFINED, TOKEN_UNUSED = 1, 3, 4, 5


def _s(text):
    b = text.encode("utf-8")
    return struct.pack("<Q", len(b)) + b


def kv(key, value):
    """一個 GGUF 的 key／value（依 Python 型別決定 GGUF 型別）。"""
    out = _s(key)
    if isinstance(value, bool):
        return out + struct.pack("<IB", T_BOOL, int(value))
    if isinstance(value, int):
        return out + struct.pack("<II", T_UINT32, value)
    if isinstance(value, float):
        return out + struct.pack("<If", T_FLOAT32, value)
    if isinstance(value, str):
        return out + struct.pack("<I", T_STRING) + _s(value)
    if isinstance(value, tuple) and value[0] == "i32[]":
        items = value[1]
        return out + struct.pack("<IIQ", T_ARRAY, T_INT32, len(items)) + struct.pack(f"<{len(items)}i", *items)
    if isinstance(value, tuple) and value[0] == "f32[]":
        items = value[1]
        return out + struct.pack("<IIQ", T_ARRAY, T_FLOAT32, len(items)) + struct.pack(f"<{len(items)}f", *items)
    if isinstance(value, list):
        return out + struct.pack("<IIQ", T_ARRAY, T_STRING, len(value)) + b"".join(_s(v) for v in value)
    raise TypeError(f"不支援的 GGUF 值：{key}")


def quantize_q8_0(arr):
    """Q8_0：每 32 個數一組，存一個 fp16 比例與 32 個 int8。"""
    import numpy as np
    x = arr.astype(np.float32).reshape(-1, 32)
    d = np.abs(x).max(axis=1) / 127.0
    with np.errstate(divide="ignore", invalid="ignore"):
        q = np.where(d[:, None] > 0, np.round(x / d[:, None]), 0).clip(-127, 127).astype(np.int8)
    blocks = np.empty(x.shape[0], dtype=[("d", "<f2"), ("qs", "i1", 32)])
    blocks["d"] = d.astype(np.float16)
    blocks["qs"] = q
    return blocks.tobytes()


def permute_qk(w, n_head):
    """Llama 架構：Hugging Face 的 q／k 權重排列跟 GGML 的 RoPE 不同，要換成 GGML 的排法（同 llama.cpp 的轉換程式）。"""
    return w.reshape(n_head, 2, w.shape[0] // n_head // 2, *w.shape[1:]).swapaxes(1, 2).reshape(w.shape)


def load_tokenizer(model_dir, vocab_size):
    with open(os.path.join(model_dir, "tokenizer.json"), "r", encoding="utf-8") as f:
        tj = _json.load(f)
    model = tj.get("model") or {}
    byte_level = "ByteLevel" in _json.dumps(tj.get("pre_tokenizer")) or "ByteLevel" in _json.dumps(tj.get("decoder"))
    if model.get("type") != "BPE" or not byte_level:
        # Llama 2 那種 sentencepiece 式的 BPE 要另一種寫法（有分數表），轉錯會變成亂碼，所以直接說明
        raise ValueError("只支援位元組 BPE 分詞器（Qwen2.5、SmolLM2、Llama 3 系列），這個模型的分詞器不一樣，"
                         "請改選 Qwen2.5 當底模")
    vocab = dict(model["vocab"])
    special, user = set(), set()
    for t in tj.get("added_tokens", []):
        vocab[t["content"]] = t["id"]
        (special if t.get("special") else user).add(t["id"])
    size = max(vocab_size, max(vocab.values()) + 1)
    tokens, types = [f"[PAD{i}]" for i in range(size)], [TOKEN_UNUSED] * size
    for tok, i in vocab.items():
        tokens[i] = tok
        types[i] = TOKEN_CONTROL if i in special else TOKEN_USER_DEFINED if i in user else TOKEN_NORMAL
    merges = [m if isinstance(m, str) else " ".join(m) for m in model.get("merges", [])]
    cfg = {}
    p = os.path.join(model_dir, "tokenizer_config.json")
    if os.path.isfile(p):
        with open(p, "r", encoding="utf-8") as f:
            cfg = _json.load(f)
    template = cfg.get("chat_template") or ""
    jp = os.path.join(model_dir, "chat_template.jinja")
    if not template and os.path.isfile(jp):
        with open(jp, "r", encoding="utf-8") as f:
            template = f.read()
    return tokens, types, merges, cfg, template, vocab


def token_id(name_or_id, cfg, vocab, key):
    v = cfg.get(key)
    if isinstance(v, dict):
        v = v.get("content")
    if isinstance(v, str) and v in vocab:
        return vocab[v]
    return name_or_id if isinstance(name_or_id, int) else None


def main():
    cfg = load_config()
    import numpy as np
    from safetensors import safe_open
    model_dir, out_path = cfg["model_dir"], cfg["out_path"]
    with open(os.path.join(model_dir, "config.json"), "r", encoding="utf-8") as f:
        hp = _json.load(f)
    mtype = hp.get("model_type")
    if mtype not in ("llama", "qwen2"):
        raise ValueError(f"目前只支援 Llama 與 Qwen2 架構（Qwen2.5、SmolLM2…），這個模型是 {mtype}")
    arch = mtype
    n_head, n_kv = hp["num_attention_heads"], hp.get("num_key_value_heads", hp["num_attention_heads"])
    hidden = hp["hidden_size"]
    head_dim = hp.get("head_dim") or hidden // n_head
    rope = hp.get("rope_theta") or (hp.get("rope_parameters") or {}).get("rope_theta") or 10000.0
    tokens, types, merges, tcfg, template, vocab = load_tokenizer(model_dir, hp.get("vocab_size", 0))
    name = os.path.basename(os.path.normpath(os.path.dirname(model_dir))) or "model"
    pre = "qwen2" if arch == "qwen2" else ("smollm" if "smollm" in (hp.get("_name_or_path", "") + name).lower()
                                           or len(tokens) == 49152 else "llama-bpe")
    meta = [("general.architecture", arch), ("general.name", name), ("general.file_type", FILE_TYPE_Q8_0),
            ("general.quantization_version", 2), ("general.alignment", ALIGN),
            (f"{arch}.context_length", int(hp.get("max_position_embeddings", 4096))),
            (f"{arch}.embedding_length", hidden), (f"{arch}.block_count", hp["num_hidden_layers"]),
            (f"{arch}.feed_forward_length", hp["intermediate_size"]), (f"{arch}.attention.head_count", n_head),
            (f"{arch}.attention.head_count_kv", n_kv), (f"{arch}.rope.freq_base", float(rope)),
            (f"{arch}.attention.layer_norm_rms_epsilon", float(hp.get("rms_norm_eps", 1e-6))),
            (f"{arch}.rope.dimension_count", head_dim), (f"{arch}.vocab_size", len(tokens)),
            ("tokenizer.ggml.model", "gpt2"), ("tokenizer.ggml.pre", pre), ("tokenizer.ggml.tokens", tokens),
            ("tokenizer.ggml.token_type", ("i32[]", types)), ("tokenizer.ggml.merges", merges),
            ("tokenizer.ggml.add_bos_token", bool(tcfg.get("add_bos_token", False)))]
    for key, hf_key, fallback in (("bos", "bos_token", hp.get("bos_token_id")), ("eos", "eos_token", hp.get("eos_token_id")),
                                  ("padding", "pad_token", hp.get("pad_token_id"))):
        tid = token_id(fallback if not isinstance(fallback, list) else fallback[0], tcfg, vocab, hf_key)
        if tid is not None:
            meta.append((f"tokenizer.ggml.{key}_token_id", int(tid)))
    if template:
        meta.append(("tokenizer.chat_template", template))

    files = sorted(glob.glob(os.path.join(model_dir, "*.safetensors")))
    if not files:
        raise ValueError(f"{model_dir} 裡沒有 .safetensors 權重檔")
    handles = [safe_open(f, framework="pt") for f in files]          # 用 PyTorch 讀（numpy 不支援 bf16）
    where = {k: h for h in handles for k in h.keys()}

    def hf(name_):
        return where[name_].get_tensor(name_).float().numpy()
    plan = []                                       # (GGUF 名稱, HF 名稱, 轉換)
    plan.append(("token_embd.weight", "model.embed_tokens.weight", None))
    for i in range(hp["num_hidden_layers"]):
        p, b = f"model.layers.{i}.", f"blk.{i}."
        plan += [(b + "attn_norm.weight", p + "input_layernorm.weight", None),
                 (b + "attn_q.weight", p + "self_attn.q_proj.weight", "q"),
                 (b + "attn_k.weight", p + "self_attn.k_proj.weight", "k"),
                 (b + "attn_v.weight", p + "self_attn.v_proj.weight", None),
                 (b + "attn_output.weight", p + "self_attn.o_proj.weight", None),
                 (b + "ffn_norm.weight", p + "post_attention_layernorm.weight", None),
                 (b + "ffn_gate.weight", p + "mlp.gate_proj.weight", None),
                 (b + "ffn_up.weight", p + "mlp.up_proj.weight", None),
                 (b + "ffn_down.weight", p + "mlp.down_proj.weight", None)]
        for proj, short in (("q_proj", "q"), ("k_proj", "k"), ("v_proj", "v")):
            if p + f"self_attn.{proj}.bias" in where:
                plan.append((b + f"attn_{short}.bias", p + f"self_attn.{proj}.bias", None))
    plan.append(("output_norm.weight", "model.norm.weight", None))
    if "lm_head.weight" in where and not hp.get("tie_word_embeddings", False):
        plan.append(("output.weight", "lm_head.weight", None))
    missing = [h for _g, h, _t in plan if h not in where]
    if missing:
        raise ValueError("模型裡找不到這些權重（架構可能不一樣）：" + "、".join(missing[:5]))

    def prepared(gname, hname, how):
        w = hf(hname).astype(np.float32)
        if arch == "llama" and how == "q":
            w = permute_qk(w, n_head)
        elif arch == "llama" and how == "k":
            w = permute_qk(w, n_kv)
        if w.ndim == 2 and w.shape[-1] % 32 == 0:
            return w, GGML_Q8_0
        return w, GGML_F32

    infos, offset = [], 0
    for gname, hname, how in plan:            # 第一輪：算出每個張量的型別、大小與位置（還不讀權重本體）
        shape = where[hname].get_slice(hname).get_shape()
        dtype = GGML_Q8_0 if len(shape) == 2 and shape[-1] % 32 == 0 else GGML_F32
        nbytes = (int(np.prod(shape)) // 32 * 34) if dtype == GGML_Q8_0 else int(np.prod(shape)) * 4
        infos.append((gname, hname, how, list(shape), dtype, offset, nbytes))
        offset += (nbytes + ALIGN - 1) // ALIGN * ALIGN
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    tmp = out_path + ".partial"
    with open(tmp, "wb") as f:
        f.write(b"GGUF" + struct.pack("<IQQ", 3, len(infos), len(meta)))
        for k, v in meta:
            f.write(kv(k, v))
        for gname, _h, _how, shape, dtype, off, _n in infos:
            f.write(_s(gname) + struct.pack("<I", len(shape)) + struct.pack(f"<{len(shape)}Q", *reversed(shape))
                    + struct.pack("<IQ", dtype, off))
        f.write(b"\0" * ((-f.tell()) % ALIGN))
        base = f.tell()
        for n, (gname, hname, how, shape, dtype, off, nbytes) in enumerate(infos, 1):
            w, _t = prepared(gname, hname, how)
            data = quantize_q8_0(w) if dtype == GGML_Q8_0 else w.astype("<f4").tobytes()
            assert len(data) == nbytes, gname
            f.seek(base + off)
            f.write(data)
            if n % 20 == 0 or n == len(infos):
                emit("PROGRESS", stage="轉成 GGUF", step=n, total=len(infos))
        f.write(b"\0" * ((-f.tell()) % ALIGN))
    os.replace(tmp, out_path)
    emit("RESULT", gguf=out_path, tensors=len(infos), mb=round(os.path.getsize(out_path) / 1e6, 1), arch=arch, pre=pre)


if __name__ == "__main__":
    run_main(main)
