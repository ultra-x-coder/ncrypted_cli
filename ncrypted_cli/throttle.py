"""Bandwidth throttling — parse human-readable rate strings and a token-bucket
RateLimiter used by upload (ProgressReader) and download (the iter_bytes loop).

Rates are BYTES PER SECOND (to match the byte-based progress bars). Suffixes:
    k / kb  = 1000          ki / kib = 1024
    m / mb  = 1000^2        mi / mib = 1024^2
    g / gb  = 1000^3        gi / gib = 1024^3
A bare number is bytes/sec. None / "" / "0" / "unlimited" / "none" / "off" = no
limit (parse_rate returns None and RateLimiter.throttle becomes a no-op).
"""

import re
import time

_SUFFIXES = {
    "": 1,
    "b": 1,
    "k": 1000, "kb": 1000, "ki": 1024, "kib": 1024,
    "m": 1000 ** 2, "mb": 1000 ** 2, "mi": 1024 ** 2, "mib": 1024 ** 2,
    "g": 1000 ** 3, "gb": 1000 ** 3, "gi": 1024 ** 3, "gib": 1024 ** 3,
}

_RATE_RE = re.compile(r"^([0-9]*\.?[0-9]+)\s*([a-z]*)$", re.IGNORECASE)


def parse_rate(value) -> int | None:
    """Parse a human-readable bytes/sec rate string.

    Returns an int (bytes/sec) or None for "no limit". Raises ValueError on a
    malformed string so the CLI can surface a clear message.
    """
    if value is None:
        return None
    s = str(value).strip().lower()
    if s in ("", "0", "none", "unlimited", "inf", "off"):
        return None
    m = _RATE_RE.match(s)
    if not m:
        raise ValueError(f"Invalid rate: {value!r} (try e.g. 500k, 1m, 2mib)")
    num, suffix = m.group(1), m.group(2)
    if suffix not in _SUFFIXES:
        raise ValueError(
            f"Unknown rate unit {suffix!r} in {value!r} "
            "(use k/m/g for 1000-based or ki/mi/gi for 1024-based, bytes/sec)"
        )
    rate = int(float(num) * _SUFFIXES[suffix])
    return rate or None


class RateLimiter:
    """Token-bucket limiter. Call ``throttle(nbytes)`` once per transferred
    chunk; it sleeps as needed to keep the average throughput at or below
    ``rate`` bytes/sec. ``rate=None`` disables limiting (throttle is a no-op).

    A small burst capacity (``max_burst_seconds`` worth of tokens) smooths out
    chunk-sized jitter without exceeding the average rate.
    """

    def __init__(self, rate: int | None, max_burst_seconds: float = 1.0):
        self.rate = rate
        self._capacity = rate * max_burst_seconds if rate else 0.0
        self._tokens = self._capacity
        self._last = time.monotonic()

    def throttle(self, nbytes: int) -> None:
        if not self.rate or nbytes <= 0:
            return
        now = time.monotonic()
        self._tokens = min(self._capacity, self._tokens + (now - self._last) * self.rate)
        self._last = now
        self._tokens -= nbytes
        if self._tokens < 0:
            # Not enough tokens: sleep just long enough to refill the deficit.
            time.sleep(-self._tokens / self.rate)
            self._tokens = 0.0
            # Re-stamp AFTER sleeping so the slept time is not re-credited as
            # refill on the next call (that double-count would inflate the rate).
            self._last = time.monotonic()
