#!/usr/bin/env python3
"""Download a URL 10 times in a row and print the download speed in Mbit/s."""

from __future__ import annotations

import argparse
import http.client
import sys
import time
from urllib.parse import urlsplit
from urllib.request import urlopen

REQUESTS = 10
MAX_FAILS_IN_ROW = 3  # the address is down, more attempts would only make the user wait
TIMEOUT_S = 10
CHUNK = 64 * 1024


def http_url(value: str) -> str:
    """argparse type: accept only a well-formed http(s) URL."""
    try:
        parts = urlsplit(value)
        parts.port  # noqa: B018 -- raises ValueError on a non-numeric or out-of-range port
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"not an http(s) address: {value!r} ({e})") from None
    if (parts.scheme not in ("http", "https") or not parts.hostname
            or any(c.isspace() or not c.isprintable() for c in value)):
        raise argparse.ArgumentTypeError(f"not an http(s) address: {value!r}")
    return value


def download(url: str) -> tuple[int, float]:
    """Read the whole response without keeping it. Returns (bytes, seconds)."""
    start = time.perf_counter()
    size = 0
    with urlopen(url, timeout=TIMEOUT_S) as resp:
        while chunk := resp.read(CHUNK):
            size += len(chunk)
        if resp.length:  # server promised more (Content-Length) than it sent
            raise ConnectionError(f"connection closed with {resp.length} bytes missing")
    return size, time.perf_counter() - start


def speed_mbps(done: list[tuple[int, float]]) -> float:
    """Total volume over total time of the successful requests, in megabits per second."""
    total_bytes = sum(size for size, _ in done)
    avg_time = sum(seconds for _, seconds in done) / len(done)
    return total_bytes * 8 / (avg_time * len(done)) / 1e6


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", type=http_url, help="http(s) address, e.g. a large image")
    url = parser.parse_args(argv).url

    done: list[tuple[int, float]] = []
    fails_in_row = 0
    for i in range(1, REQUESTS + 1):
        try:
            done.append(download(url))
            fails_in_row = 0
        except (OSError, http.client.HTTPException) as e:  # HTTP 4xx/5xx, DNS, timeout, drop
            print(f"request {i} failed: {e}", file=sys.stderr)
            fails_in_row += 1
            if fails_in_row == MAX_FAILS_IN_ROW:
                print(f"stopped after {MAX_FAILS_IN_ROW} failures in a row", file=sys.stderr)
                break

    if not done:
        print("all requests failed", file=sys.stderr)
        return 1

    print(f"{speed_mbps(done):.2f} Mbit/s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
