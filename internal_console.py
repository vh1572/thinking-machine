#!/usr/bin/env python3
"""Simple internal console viewer (tail -f style) for Thinking Machine logs."""

from __future__ import annotations

import os
import time

LOG_FILE = os.getenv("INTERNAL_LOG_FILE", "internal.log")


def follow(path: str) -> None:
    print(f"Internal console attached to: {path}")
    print("Press Ctrl+C to exit.")

    while not os.path.exists(path):
        print("Waiting for log file to be created...")
        time.sleep(1)

    with open(path, "r", encoding="utf-8") as f:
        f.seek(0, os.SEEK_END)
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.2)
                continue
            print(line, end="")


if __name__ == "__main__":
    try:
        follow(LOG_FILE)
    except KeyboardInterrupt:
        print("\nInternal console closed.")
