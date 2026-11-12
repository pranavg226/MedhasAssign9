"""OpenRouter (OpenAI-compatible) chat client. Needs OPENROUTER_API_KEY. Retries on 429 (free tier is rate limited)."""
import os, time, httpx

if os.path.exists(".env"):  # minimal .env loader (no extra dependency)
    for _l in open(".env"):
        if "=" in _l and not _l.lstrip().startswith("#"):
            _k, _v = _l.strip().split("=", 1); os.environ.setdefault(_k, _v.strip().strip("\"'"))

def _anthropic(model, messages, tools, max_tokens):
    import json
    system = "".join(m["content"] for m in messages if m["role"] == "system")
    out = []
    for m in messages:
        if m["role"] == "system": continue
        if m["role"] == "tool":
            blk = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list): out[-1]["content"].append(blk)
            else: out.append({"role": "user", "content": [blk]})
        elif m["role"] == "assistant" and m.get("tool_calls"):
            c = ([{"type": "text", "text": m["content"]}] if m.get("content") else []) + [
                {"type": "tool_use", "id": t["id"], "name": t["function"]["name"], "input": json.loads(t["function"]["arguments"] or "{}")} for t in m["tool_calls"]]
            out.append({"role": "assistant", "content": c})
        else: out.append({"role": m["role"], "content": m["content"]})
    body = {"model": model, "max_tokens": max_tokens, "messages": out}
    if system: body["system"] = system
    if tools: body["tools"] = [{"name": t["function"]["name"], "description": t["function"]["description"], "input_schema": t["function"]["parameters"]} for t in tools]
    for i in range(6):
        r = httpx.post("https://api.anthropic.com/v1/messages", json=body, timeout=120,
                       headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"})
        if r.status_code in (429, 500, 529): time.sleep(5 * (i + 1)); continue
        r.raise_for_status()
        c = r.json()["content"]
        return {"content": "".join(b["text"] for b in c if b["type"] == "text"),
                "tool_calls": [{"id": b["id"], "type": "function", "function": {"name": b["name"], "arguments": json.dumps(b["input"])}} for b in c if b["type"] == "tool_use"] or None}
    raise RuntimeError("Anthropic: retries exhausted")


def chat(model, messages, tools=None, max_tokens=800):
    if os.environ.get("ANTHROPIC_API_KEY", "").startswith("sk-ant"):  # preferred provider when a key is present
        return _anthropic(model, messages, tools, max_tokens)
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0}
    if tools: body["tools"] = tools
    for i in range(10):
        r = httpx.post("https://openrouter.ai/api/v1/chat/completions", json=body, timeout=120,
                       headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"})
        if r.status_code in (429, 502, 503): time.sleep(min(60, 8 * (i + 1))); continue
        r.raise_for_status()
        d = r.json()
        if "error" in d: time.sleep(min(60, 8 * (i + 1))); continue
        time.sleep(float(os.getenv("CALL_DELAY", "2")))  # pace calls for free-tier limits
        return d["choices"][0]["message"]
    raise RuntimeError("OpenRouter: retries exhausted")
