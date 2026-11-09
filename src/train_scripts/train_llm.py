"""AI 協作：語言模型蒸餾／微調（LoRA；有 NVIDIA 顯示卡時用 4-bit QLoRA）。
資料：JSONL，每行 {"messages": [{"role": "system"|"user"|"assistant", "content": "..."}...]}，最後一則是 assistant（要學的回答）。
用法：python train_llm.py --config config.json [--smoke]
不依賴 trl（版本變動太快），自己寫訓練迴圈；transformers 4.x 與 5.x 都能用。"""
import math
import os
import random
import time

# @@COMMON@@

SMOKE_TOKENIZER = "HuggingFaceTB/SmolLM2-135M-Instruct"     # 快速測試：用真的分詞器（只下載幾 MB）配極小的隨機權重


def tiny_smoke_base(folder):
    """在本機組一個極小的 Llama（隨機權重）＋ SmolLM2 的分詞器，給快速測試用；轉 GGUF 也能測到。"""
    from transformers import AutoTokenizer, LlamaConfig, LlamaForCausalLM
    if os.path.isfile(os.path.join(folder, "config.json")):
        return folder
    tok = AutoTokenizer.from_pretrained(SMOKE_TOKENIZER)
    cfg = LlamaConfig(vocab_size=len(tok), hidden_size=64, intermediate_size=128, num_hidden_layers=2, num_attention_heads=4,
                      num_key_value_heads=2, max_position_embeddings=512, tie_word_embeddings=True,
                      bos_token_id=tok.bos_token_id, eos_token_id=tok.eos_token_id)
    LlamaForCausalLM(cfg).save_pretrained(folder)
    tok.save_pretrained(folder)
    return folder
FALLBACK_TEMPLATE = ("{% for m in messages %}<|{{ m['role'] }}|>\n{{ m['content'] }}\n{% endfor %}"
                     "{% if add_generation_prompt %}<|assistant|>\n{% endif %}")


def dtype_kw(dtype):
    import transformers
    major, minor = (int(x) for x in transformers.__version__.split(".")[:2])
    return {"dtype": dtype} if (major, minor) >= (4, 56) else {"torch_dtype": dtype}


def read_rows(path, limit=None):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            obj = _json.loads(line)
            msgs = obj.get("messages") if isinstance(obj, dict) else None
            if not msgs or msgs[-1].get("role") != "assistant" or not str(msgs[-1].get("content", "")).strip():
                log(f"第 {n} 行格式不對（最後一則要是 assistant 的回答），略過")
                continue
            rows.append(msgs)
            if limit and len(rows) >= limit:
                break
    if not rows:
        raise ValueError("資料集是空的，或格式都不對")
    return rows


def encode(tok, msgs, max_len):
    """只學最後一則 assistant 回答：前面的部分 label 設成 -100。"""
    full = tok.apply_chat_template(msgs, tokenize=False)
    prompt = tok.apply_chat_template(msgs[:-1], tokenize=False, add_generation_prompt=True)
    ids = tok(full, add_special_tokens=False)["input_ids"]
    p = len(tok(prompt, add_special_tokens=False)["input_ids"])
    if tok.eos_token_id is not None and (not ids or ids[-1] != tok.eos_token_id):
        ids = ids + [tok.eos_token_id]
    ids = ids[:max_len]
    labels = [-100] * min(p, len(ids)) + ids[p:]
    if all(x == -100 for x in labels):
        return None                                   # 問題本身就超過最長長度：沒有東西可學
    return ids, labels


def batches(items, size, pad_id, shuffle=True):
    import torch
    order = list(range(len(items)))
    if shuffle:
        random.shuffle(order)
    for i in range(0, len(order), size):
        group = [items[j] for j in order[i:i + size]]
        n = max(len(g[0]) for g in group)
        ids = torch.full((len(group), n), pad_id, dtype=torch.long)
        lab = torch.full((len(group), n), -100, dtype=torch.long)
        att = torch.zeros((len(group), n), dtype=torch.long)
        for k, (a, b) in enumerate(group):
            ids[k, :len(a)] = torch.tensor(a)
            lab[k, :len(b)] = torch.tensor(b)
            att[k, :len(a)] = 1
        yield ids, lab, att


def main():
    cfg = load_config()
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import LoraConfig, PeftModel, get_peft_model

    smoke = cfg["smoke"]
    random.seed(cfg.get("seed", 42))
    torch.manual_seed(cfg.get("seed", 42))
    out_dir = cfg["out_dir"]
    os.makedirs(out_dir, exist_ok=True)
    base = tiny_smoke_base(os.path.join(out_dir, "_極小測試底模")) if smoke else cfg["base_model"]
    cuda = torch.cuda.is_available() and (not smoke or bool(cfg.get("smoke_gpu")))   # 本機檢測：快速測試也用顯示卡
    emit("PROGRESS", stage="載入模型", msg=f"{base}（{'GPU' if cuda else 'CPU'}）")
    tok = AutoTokenizer.from_pretrained(base)
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token or tok.unk_token
    if not getattr(tok, "chat_template", None):
        tok.chat_template = FALLBACK_TEMPLATE
    rows = read_rows(cfg["data_path"], limit=12 if smoke else None)
    max_len = 256 if smoke else int(cfg.get("max_len", 1024))
    data = [e for e in (encode(tok, m, max_len) for m in rows) if e]
    if not data:
        raise ValueError("每一筆的問題都超過「最長長度」，沒有可以學的內容：請調大最長長度")
    random.shuffle(data)
    n_val = 0 if len(data) < 10 else max(1, int(len(data) * float(cfg.get("val_ratio", 0.05))))
    val, train = data[:n_val], data[n_val:]
    log(f"訓練 {len(train)} 筆、驗證 {len(val)} 筆（原始 {len(rows)} 筆）")

    quant = None
    bf16 = cuda and torch.cuda.is_bf16_supported()
    compute = torch.bfloat16 if bf16 else (torch.float16 if cuda else torch.float32)
    if cuda and cfg.get("qlora", True):
        from transformers import BitsAndBytesConfig
        quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                                   bnb_4bit_compute_dtype=compute)
    model = AutoModelForCausalLM.from_pretrained(base, quantization_config=quant, device_map={"": 0} if cuda else None,
                                                 low_cpu_mem_usage=True, **dtype_kw(compute))
    model.config.use_cache = False
    if quant is not None:
        from peft import prepare_model_for_kbit_training
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    elif cuda and hasattr(model, "gradient_checkpointing_enable"):
        model.gradient_checkpointing_enable()
        model.enable_input_require_grads()
    r = int(cfg.get("lora_r", 16))
    model = get_peft_model(model, LoraConfig(r=r, lora_alpha=int(cfg.get("lora_alpha", r * 2)), lora_dropout=0.05,
                                             task_type="CAUSAL_LM", target_modules="all-linear"))
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    log(f"可訓練參數 {trainable / 1e6:.2f} M")

    epochs = 1 if smoke else float(cfg.get("epochs", 2))
    bsz, accum = int(cfg.get("batch_size", 1)), int(cfg.get("grad_accum", 8))
    steps_per_epoch = max(1, math.ceil(len(train) / bsz / accum))
    total = max(1, int(steps_per_epoch * epochs))
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=float(cfg.get("lr", 2e-4)),
                            weight_decay=0.0)
    from transformers import get_cosine_schedule_with_warmup
    sched = get_cosine_schedule_with_warmup(opt, max(1, int(total * 0.05)), total)
    device = next(model.parameters()).device
    model.train()
    step, micro, started, losses = 0, 0, time.time(), []
    while step < total:
        for ids, lab, att in batches(train, bsz, tok.pad_token_id):
            with torch.autocast("cuda", dtype=compute, enabled=cuda):
                loss = model(input_ids=ids.to(device), attention_mask=att.to(device), labels=lab.to(device)).loss / accum
            loss.backward()
            losses.append(loss.item() * accum)
            micro += 1
            if micro % accum:
                continue
            torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], 1.0)
            opt.step()
            sched.step()
            opt.zero_grad(set_to_none=True)
            step += 1
            avg = sum(losses[-accum * 5:]) / len(losses[-accum * 5:])
            spent = time.time() - started
            emit("PROGRESS", stage="訓練", step=step, total=total, loss=round(avg, 4), lr=sched.get_last_lr()[0],
                 eta_min=round(spent / step * (total - step) / 60, 1), vram=vram_text())
            if step >= total:
                break
    val_loss = None
    if val:
        model.eval()
        tot = cnt = 0.0
        with torch.no_grad():
            for ids, lab, att in batches(val, bsz, tok.pad_token_id, shuffle=False):
                with torch.autocast("cuda", dtype=compute, enabled=cuda):
                    tot += model(input_ids=ids.to(device), attention_mask=att.to(device), labels=lab.to(device)).loss.item()
                cnt += 1
        val_loss = round(tot / max(cnt, 1), 4)
        log(f"驗證損失 {val_loss}")
    adapter = os.path.join(out_dir, "adapter")
    model.save_pretrained(adapter)
    tok.save_pretrained(adapter)
    emit("PROGRESS", stage="儲存", msg=f"LoRA 已存到 {adapter}")
    merged = ""
    if cfg.get("merge", True):
        emit("PROGRESS", stage="合併", msg="把 LoRA 合併回完整模型（給 Ollama 用；在 CPU 上做，需要一些記憶體）")
        del model, opt
        if cuda:
            torch.cuda.empty_cache()
        full = AutoModelForCausalLM.from_pretrained(base, low_cpu_mem_usage=True,
                                                    **dtype_kw(torch.float32 if smoke else torch.float16))
        full = PeftModel.from_pretrained(full, adapter).merge_and_unload()
        merged = os.path.join(out_dir, "merged")
        full.save_pretrained(merged, safe_serialization=True, max_shard_size="2GB")
        tok.save_pretrained(merged)
    emit("RESULT", adapter=adapter, merged=merged, train_loss=round(sum(losses[-20:]) / len(losses[-20:]), 4),
         val_loss=val_loss, steps=total, minutes=round((time.time() - started) / 60, 1), base_model=base)


if __name__ == "__main__":
    run_main(main)
