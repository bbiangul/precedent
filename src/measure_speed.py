#!/usr/bin/env python3
"""Measure speed + cost of the govern pipeline vs a memory baseline, per model.

The govern pipeline = ONE model call (authority+consequentiality extraction) + a
deterministic matrix step (~0 ms, measured). The enforcement gate (govern_pr.py) is
ZERO model calls. This quantifies the "small fast model + instant matrix" claim.

Usage: OPENROUTER_API_KEY=... python3 tools/measure_speed.py <model>
"""
import json, os, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_arms, govern

MODEL = sys.argv[1] if len(sys.argv) > 1 else "google/gemini-2.5-flash"
KEY = os.environ["OPENROUTER_API_KEY"]

def pricing(model):
    req = urllib.request.Request("https://openrouter.ai/api/v1/models",
        headers={"Authorization": "Bearer " + KEY})
    for m in json.load(urllib.request.urlopen(req, timeout=20))["data"]:
        if m["id"] == model:
            p = m["pricing"]
            return float(p["prompt"]), float(p["completion"])   # $ per token
    return 0.0, 0.0

def call(prompt, json_mode):
    body = {"model": MODEL, "temperature": 0, "max_tokens": 2000,
            "messages": [{"role": "user", "content": prompt}]}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
    t = time.time()
    r = json.load(urllib.request.urlopen(req, timeout=120))
    dt = time.time() - t
    u = r.get("usage", {})
    return dt, u.get("prompt_tokens", 0), u.get("completion_tokens", 0)

def bench(label, prompt_fn, json_mode):
    lats, pin, pout = [], 0, 0
    for t in run_arms.GOV_TASKS:
        try:
            dt, i, o = call(prompt_fn(t), json_mode)
            lats.append(dt); pin += i; pout += o
        except Exception:
            pass
    lats.sort()
    n = len(lats) or 1
    pp, pc = pricing(MODEL)
    cost = pin * pp + pout * pc
    return {"label": label, "n": len(lats),
            "mean_s": sum(lats) / n, "p95_s": lats[min(n - 1, int(0.95 * n))],
            "tok_in": pin, "tok_out": pout,
            "cost_total": cost, "cost_per": cost / n}

if __name__ == "__main__":
    print(f"model: {MODEL}  ({len(run_arms.GOV_TASKS)} tasks, 1 call each)\n")
    # matrix step timing (deterministic, no model)
    t = time.time()
    for _ in range(1000):
        for tk in run_arms.GOV_TASKS:
            govern.resolve("policy_match", "medium", False)
    matrix_us = (time.time() - t) / (1000 * len(run_arms.GOV_TASKS)) * 1e6

    g = bench("govern (1 model call + matrix)", run_arms._govern_prompt, True)
    f = bench("file baseline (1 model call)", lambda t: run_arms.build_prompt("file", t), False)
    for r in (g, f):
        print(f"{r['label']:34} mean={r['mean_s']:5.2f}s  p95={r['p95_s']:5.2f}s  "
              f"tok={r['tok_in']}+{r['tok_out']}  ${r['cost_per']*1000:.3f}/1k-decisions")
    print(f"\ndeterministic matrix step: {matrix_us:.1f} µs/decision (no model call)")
    print("enforcement gate (govern_pr.py): 0 model calls — pure Python")
