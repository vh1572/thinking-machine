# thinking-machine

A Python "thinking machine" that continuously reasons about **low-risk, stable-income stock investing** using a local Ollama model.

## Features
- Endless autonomous thinking loop (time-based cycles).
- Interactive user console for live prompts.
- Separate internal console to monitor logs and tool usage.
- Tool use support:
  - Web search (DuckDuckGo HTML endpoint).
  - Python execution in a Docker container (`python:3.11-slim`) with local fallback.

## Requirements
- Python 3.10+
- Local Ollama running (default endpoint: `http://127.0.0.1:11434`)
- Optional: Docker (for isolated code execution)

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

## Run
Open **Terminal 1** (internal console):

```bash
python internal_console.py
```

Open **Terminal 2** (thinking machine + user interaction):

```bash
python thinking_machine.py
```

## Commands in user console
- `/help` — show commands
- `/status` — show runtime status
- `/quit` — stop the machine

## Environment variables
- `OLLAMA_URL` (default: `http://127.0.0.1:11434/api/chat`)
- `OLLAMA_MODEL` (default: `llama3.1`)
- `THINK_INTERVAL_SECONDS` (default: `30`)
- `INTERNAL_LOG_FILE` (default: `internal.log`)
- `SEARCH_MAX_RESULTS` (default: `5`)

## Notes
- This tool is educational and not financial advice.
- If Docker is unavailable, Python tool execution falls back to local execution and logs a warning.
