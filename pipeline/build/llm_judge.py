"""Language-model judges for the provisional outfall step (docs/llm-judges.md; owner 2026-11-03 16:20).

Jev (TypeSafe, OpenRouter decisions API) classifies: a choice among named options with probabilities and a
confidence, or a 0-1 "noul" probability. Luna (openai/gpt-6-luna, chat/completions) writes text only where text
must be written (a geocoder query, a reason), at temperature 0 with a JSON schema for the answer.

Rules come first; a model sees only what rules left. Every answer is cached by the hash of (model, question
version, input) in data/build/provisional-outfalls-llm.json with the model id, the question version, the time and the
raw answer, so a re-run costs nothing; every call is logged (tokens, cost) in
data/build/provisional-outfalls-llm-log.jsonl; a run stops asking once its spend reaches the cap (default $2).
The key is read from the environment or the project's .env and never printed or written anywhere.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path

from common import BUILD_DIR, ROOT, now_iso, read_json

CACHE_PATH = BUILD_DIR / "provisional-outfalls-llm.json"
LOG_PATH = BUILD_DIR / "provisional-outfalls-llm-log.jsonl"
DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
JEV_DEFAULT = "typesafe/jev-1.14-20261014"
LUNA_DEFAULT = "openai/gpt-6-luna"
LUNA_PRICE = (0.10 / 1e6, 0.50 / 1e6)         # $ per input token, per output token (docs/llm-judges.md)


def env_value(name: str) -> str | None:
    v = os.environ.get(name)
    if v:
        return v
    p = ROOT / ".env"
    try:
        for line in p.read_text().splitlines():
            if line.strip().startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'") or None
    except OSError:
        return None
    return None


class SpendCap(Exception):
    pass


class Judge:
    def __init__(self, cap_usd: float = 2.0, offline: bool = False, cache_path: Path = CACHE_PATH,
                 log_path: Path = LOG_PATH, budget_s: float | None = None):
        self.cap, self.offline = cap_usd, offline
        self.budget_s = budget_s              # seconds spent waiting on the models this run (not wall-clock)
        self.model_seconds = 0.0
        self.cache_path, self.log_path = cache_path, log_path
        try:
            self.cache = read_json(cache_path) or {}
        except Exception:
            self.cache = {}
        self.jev = env_value("OPENROUTER_DECISIONS_MODEL") or JEV_DEFAULT
        self.luna = env_value("OPENROUTER_MODEL") or LUNA_DEFAULT
        self.spent = 0.0
        self.calls = {"jev": 0, "luna": 0, "cached": 0, "failed": 0}
        self.tokens = {"input": 0, "output": 0}
        self.lock = threading.Lock()
        self.stopped = None
        self._session = None

    # ------------------------------------------------ plumbing
    def _key(self, model: str, version: str, payload) -> str:
        return hashlib.sha256(json.dumps([model, version, payload], sort_keys=True).encode()).hexdigest()[:32]

    def _post(self, url: str, body: dict, timeout: float = 60):
        import requests
        key = env_value("OPENROUTER_API_KEY")
        if not key:
            raise RuntimeError("no OPENROUTER_API_KEY")
        if self._session is None:
            self._session = requests.Session()
        for attempt in range(3):
            try:
                r = self._session.post(url, json=body, timeout=timeout,
                                       headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                                "HTTP-Referer": "https://dirtywaterwatch.org", "X-Title": "DirtyWaterWatch"})
            except requests.RequestException:
                time.sleep(2 * 2 ** attempt)
                continue
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(3 * 2 ** attempt)
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
            return r.json()
        raise RuntimeError("no answer after 3 tries")

    def _log(self, row: dict):
        try:
            with self.log_path.open("a") as f:
                f.write(json.dumps(row) + "\n")
        except OSError:
            pass

    def save(self):
        if self.offline or not (self.calls["jev"] or self.calls["luna"]):
            return                                    # nothing new: leave the file to the runs that asked
        with self.lock:
            mine = dict(self.cache)
        try:
            disk = json.loads(self.cache_path.read_text())       # another run's answers since this one read it
        except (OSError, ValueError):
            disk = {}
        out = {**(disk if isinstance(disk, dict) else {}), **mine}
        tmp = self.cache_path.with_suffix(f".json.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(out, separators=(",", ":")))
        tmp.replace(self.cache_path)

    def _cached_or_call(self, kind: str, model: str, version: str, payload, call):
        k = self._key(model, version, payload)
        hit = self.cache.get(k)
        if hit is not None:
            with self.lock:
                self.calls["cached"] += 1
            return hit
        if self.offline:
            return None
        with self.lock:
            if self.spent >= self.cap:
                self.stopped = f"spend cap ${self.cap:.2f} reached"
                raise SpendCap(self.stopped)
            if self.budget_s is not None and self.model_seconds >= self.budget_s:
                self.stopped = "time budget of this run reached (cached answers still used)"
                raise SpendCap(self.stopped)
        t0 = time.monotonic()
        try:
            answer, usage, cost = call()
        except SpendCap:
            raise
        except Exception as ex:
            with self.lock:
                self.calls["failed"] += 1
                self.model_seconds += time.monotonic() - t0
            self._log({"at": now_iso(), "kind": kind, "model": model, "version": version, "error": str(ex)[:200]})
            return None
        entry = {"model": model, "version": version, "at": now_iso(), "answer": answer, "usage": usage, "cost": cost,
                 "input": payload}
        with self.lock:
            self.model_seconds += time.monotonic() - t0
            self.cache[k] = entry
            self.spent += cost or 0.0
            self.calls[kind] += 1
            self.tokens["input"] += int((usage or {}).get("input_tokens") or (usage or {}).get("prompt_tokens") or 0)
            self.tokens["output"] += int((usage or {}).get("output_tokens") or (usage or {}).get("completion_tokens") or 0)
        self._log({"at": entry["at"], "kind": kind, "model": model, "version": version, "usage": usage, "cost": cost,
                   "seconds": round(time.monotonic() - t0, 2)})
        return entry

    # ------------------------------------------------ Jev: classification
    def decide(self, version: str, state, questions: dict) -> dict | None:
        """{"answers": {...}} from the decisions API (cached), or None (offline, failure). Raises SpendCap."""
        model = self.jev
        payload = {"state": state, "questions": questions}

        def call():
            d = self._post(DECISIONS_URL, {"model": model, **payload})
            if not isinstance(d, dict) or d.get("error") or not isinstance(d.get("answers"), dict):
                raise RuntimeError(f"no answers: {str(d)[:160]}")         # never cached
            u = d.get("usage") or {}
            return {"answers": d.get("answers"), "model": d.get("model"), "id": d.get("id")}, u, float(u.get("cost") or 0)

        e = self._cached_or_call("jev", model, version, payload, call)
        return e["answer"] if e else None

    # ------------------------------------------------ Luna: writing
    def write(self, version: str, system: str, user: str, schema: dict, name: str = "answer") -> dict | None:
        """The parsed JSON answer of luna at temperature 0 with a JSON schema (cached), or None. Raises SpendCap."""
        model = self.luna
        payload = {"system": system, "user": user, "schema": schema}

        def call():
            d = self._post(CHAT_URL, {
                "model": model, "temperature": 0,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "response_format": {"type": "json_schema",
                                    "json_schema": {"name": name, "strict": True, "schema": schema}}})
            u = d.get("usage") or {}
            cost = u.get("cost")
            if cost is None:
                cost = (u.get("prompt_tokens") or 0) * LUNA_PRICE[0] + (u.get("completion_tokens") or 0) * LUNA_PRICE[1]
            text = ((d.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            try:
                parsed = json.loads(text)
            except ValueError:
                parsed = None
            if not isinstance(parsed, dict):
                raise RuntimeError(f"no JSON answer: {text[:160]}")      # never cached
            return {"parsed": parsed, "raw": text[:2000], "model": d.get("model")}, u, float(cost or 0)

        e = self._cached_or_call("luna", model, version, payload, call)
        return (e["answer"] or {}).get("parsed") if e else None

    def stats(self) -> dict:
        return {"models": {"jev": self.jev, "luna": self.luna}, "calls": dict(self.calls),
                "tokens": dict(self.tokens), "spent_usd": round(self.spent, 5), "cap_usd": self.cap,
                "model_seconds": round(self.model_seconds, 1), "budget_s": self.budget_s,
                "stopped": self.stopped}
