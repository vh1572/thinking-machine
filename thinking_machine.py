#!/usr/bin/env python3
"""Thinking Machine: endless autonomous investing thinker with user console."""

from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import sys
import tempfile
import textwrap
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")
THINK_INTERVAL_SECONDS = int(os.getenv("THINK_INTERVAL_SECONDS", "30"))
INTERNAL_LOG_FILE = os.getenv("INTERNAL_LOG_FILE", "internal.log")
SEARCH_MAX_RESULTS = int(os.getenv("SEARCH_MAX_RESULTS", "5"))

SYSTEM_PROMPT = textwrap.dedent(
    """
    You are a long-running autonomous thinking machine.
    Primary mission: reason continuously about low-risk, stable-income stock investing.

    Principles:
    - Emphasize capital preservation, quality companies, dividend sustainability, and risk management.
    - Prefer diversified, evidence-based, realistic ideas over hype or market timing.
    - Be explicit about uncertainty and include practical next steps.

    Tools available to you (request by returning strict JSON only):
    1) web_search: gather recent external information.
    2) run_python: run python code in a container for simple calculations/backtests.

    Response protocol:
    - If you need a tool, respond ONLY with JSON: {"tool":"web_search|run_python","input":{...}}
    - For web_search input: {"query":"..."}
    - For run_python input: {"code":"..."}
    - Otherwise respond with plain text insights.
    """
).strip()


@dataclass
class InternalState:
    thoughts_count: int = 0
    last_user_message: str = ""
    memory: list[str] = field(default_factory=list)


class ThinkingMachine:
    def __init__(self) -> None:
        self.state = InternalState()
        self.user_queue: queue.Queue[str] = queue.Queue()
        self.stop_event = threading.Event()
        self._configure_logging()

    def _configure_logging(self) -> None:
        self.logger = logging.getLogger("thinking_machine")
        self.logger.setLevel(logging.INFO)
        self.logger.handlers.clear()
        fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
        file_handler = logging.FileHandler(INTERNAL_LOG_FILE, encoding="utf-8")
        file_handler.setFormatter(fmt)
        self.logger.addHandler(file_handler)
        self.logger.info("Thinking machine initialized.")
        self.logger.info("Ollama endpoint: %s", OLLAMA_URL)
        self.logger.info("Ollama model: %s", OLLAMA_MODEL)

    def _http_json_post(self, url: str, payload: dict[str, Any], timeout: int = 120) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        req = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(req, timeout=timeout) as resp:
            data = resp.read().decode("utf-8")
            return json.loads(data)

    def _http_get_text(self, url: str, timeout: int = 20) -> str:
        req = Request(url, headers={"User-Agent": "thinking-machine/1.0"}, method="GET")
        with urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")

    def _ollama_chat(self, messages: list[dict[str, str]]) -> str:
        payload: dict[str, Any] = {"model": OLLAMA_MODEL, "messages": messages, "stream": False}
        self.logger.info("Calling Ollama with %d message(s).", len(messages))
        data = self._http_json_post(OLLAMA_URL, payload)
        content = data.get("message", {}).get("content", "")
        self.logger.info("Received response from Ollama (%d chars).", len(content))
        return content

    def web_search(self, query: str) -> str:
        self.logger.info("Running web search for query=%r", query)
        html = self._http_get_text(f"https://duckduckgo.com/html/?q={quote_plus(query)}")
        results: list[str] = []
        marker = 'class="result__a"'
        pos = 0
        while len(results) < SEARCH_MAX_RESULTS:
            idx = html.find(marker, pos)
            if idx == -1:
                break
            start = html.rfind("<a", 0, idx)
            end = html.find("</a>", idx)
            if start == -1 or end == -1:
                break
            text = _strip_html(html[start : end + 4])
            if text:
                results.append(text)
            pos = end + 4
        return "\n".join(f"- {r}" for r in results) if results else "No results parsed from search page."

    def run_python(self, code: str) -> str:
        self.logger.info("Executing python code (%d chars).", len(code))
        script = textwrap.dedent(code).strip() + "\n"
        with tempfile.TemporaryDirectory(prefix="thinking_machine_") as tmpdir:
            script_path = os.path.join(tmpdir, "script.py")
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(script)
            docker_cmd = ["docker", "run", "--rm", "-v", f"{script_path}:/app/script.py:ro", "python:3.11-slim", "python", "/app/script.py"]
            try:
                completed = subprocess.run(docker_cmd, capture_output=True, text=True, timeout=60, check=False)
                out = (completed.stdout or "") + (completed.stderr or "")
                return out.strip() or f"(python exited with code {completed.returncode}, no output)"
            except FileNotFoundError:
                self.logger.warning("Docker not available; falling back to local python execution.")
                completed = subprocess.run([sys.executable, script_path], capture_output=True, text=True, timeout=60, check=False)
                out = (completed.stdout or "") + (completed.stderr or "")
                return "[Fallback local execution]\n" + (out.strip() or "(no output)")

    def _maybe_handle_tool_request(self, llm_output: str) -> str | None:
        raw = llm_output.strip()
        if not (raw.startswith("{") and raw.endswith("}")):
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        tool = payload.get("tool")
        tool_input = payload.get("input", {})
        if tool == "web_search":
            query = str(tool_input.get("query", "")).strip()
            return self.web_search(query) if query else "Tool error: web_search missing non-empty query"
        if tool == "run_python":
            code = str(tool_input.get("code", "")).strip()
            return self.run_python(code) if code else "Tool error: run_python missing non-empty code"
        return f"Tool error: unsupported tool {tool!r}"

    def _build_messages(self, prompt: str) -> list[dict[str, str]]:
        mem_block = "\n".join(self.state.memory[-6:])
        now = datetime.now(timezone.utc).isoformat()
        user_payload = textwrap.dedent(
            f"""
            Timestamp (UTC): {now}
            Thoughts so far: {self.state.thoughts_count}
            Last user message: {self.state.last_user_message or '[none]'}

            Recent memory:
            {mem_block or '[empty]'}

            New prompt:
            {prompt}
            """
        ).strip()
        return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_payload}]

    def think_once(self, prompt: str) -> str:
        first = self._ollama_chat(self._build_messages(prompt))
        tool_result = self._maybe_handle_tool_request(first)
        if tool_result is None:
            return first
        self.logger.info("Tool invoked; returning result to Ollama.")
        messages = self._build_messages(prompt)
        messages.append({"role": "assistant", "content": first})
        messages.append({"role": "user", "content": f"Tool result:\n{tool_result}\n\nNow provide the best next insight."})
        return self._ollama_chat(messages)

    def _thinking_loop(self) -> None:
        self.logger.info("Thinking loop started.")
        while not self.stop_event.is_set():
            try:
                prompt = "Continue autonomous analysis on low-risk, stable-income stock investing. Focus on portfolio construction, downside protection, and practical actions."
                if not self.user_queue.empty():
                    user_msg = self.user_queue.get_nowait()
                    self.state.last_user_message = user_msg
                    prompt = f"User asks: {user_msg}"
                answer = self.think_once(prompt)
                self.state.thoughts_count += 1
                self.state.memory.append(f"T{self.state.thoughts_count}: {answer[:500]}")
                self.state.memory = self.state.memory[-30:]
                print(f"\n[THOUGHT #{self.state.thoughts_count}]\n{answer}\n")
                self.logger.info("Thought #%d generated.", self.state.thoughts_count)
            except Exception as exc:  # noqa: BLE001
                self.logger.exception("Thinking step failed: %s", exc)
            self.stop_event.wait(THINK_INTERVAL_SECONDS)
        self.logger.info("Thinking loop stopped.")

    def _user_loop(self) -> None:
        print("Thinking Machine user console ready.")
        print("Type your message and press Enter. Type '/quit' to stop. Type '/help' for commands.")
        while not self.stop_event.is_set():
            try:
                raw = input("you> ").strip()
            except EOFError:
                raw = "/quit"
            if not raw:
                continue
            if raw == "/quit":
                self.stop_event.set()
                break
            if raw == "/help":
                print("Commands: /quit, /help, /status")
                continue
            if raw == "/status":
                print(f"Thoughts: {self.state.thoughts_count}, queued messages: {self.user_queue.qsize()}, last user msg: {self.state.last_user_message or '[none]'}")
                continue
            self.user_queue.put(raw)
            self.logger.info("User message queued (%d chars).", len(raw))
            print("Message received. It will be considered in the next thought cycle.")

    def run(self) -> None:
        t = threading.Thread(target=self._thinking_loop, daemon=True)
        t.start()
        self._user_loop()
        self.stop_event.set()
        t.join(timeout=5)


def _strip_html(s: str) -> str:
    out: list[str] = []
    in_tag = False
    for ch in s:
        if ch == "<":
            in_tag = True
            continue
        if ch == ">":
            in_tag = False
            continue
        if not in_tag:
            out.append(ch)
    return " ".join("".join(out).split())


def main() -> None:
    ThinkingMachine().run()


if __name__ == "__main__":
    main()
