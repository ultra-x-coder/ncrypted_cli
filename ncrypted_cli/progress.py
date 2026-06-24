"""Small stderr progress bar and spinner used by uploads/downloads."""

import io
import sys
import threading
import time

from .ui import human_bytes, human_eta


class SimpleProgress:
    def __init__(self):
        self.description = ""
        self.total = None
        self.current = 0
        self.started_at = 0.0
        self._last_render = 0.0
        self._rendered = False

    def __enter__(self):
        self.started_at = time.monotonic()
        return self

    def __exit__(self, *exc):
        if exc and exc[0] is not None:
            if self._rendered:
                sys.stderr.write("\n")
                sys.stderr.flush()
            return False
        self._render(force=True)
        if self._rendered:
            sys.stderr.write("\n")
            sys.stderr.flush()
        return False

    def add_task(self, description: str, total: int | None = None):
        self.description = description
        self.total = total
        self.current = 0
        self.started_at = time.monotonic()
        self._render(force=True)
        return 0

    def update(self, task_id, advance: int = 0):
        del task_id
        self.current += advance
        self._render()

    def _render(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_render < 0.08:
            return
        self._last_render = now
        elapsed = max(now - self.started_at, 0.001)
        speed = self.current / elapsed

        if self.total:
            pct = min(self.current / self.total, 1.0)
            width = 28
            filled = int(width * pct)
            bar = "#" * filled + "-" * (width - filled)
            remaining = (self.total - self.current) / speed if speed > 0 else None
            line = (
                f"{self.description} [{bar}] {pct * 100:5.1f}% "
                f"{human_bytes(self.current)}/{human_bytes(self.total)} "
                f"{human_bytes(speed)}/s eta {human_eta(remaining)}"
            )
        else:
            line = (
                f"{self.description} {human_bytes(self.current)} "
                f"{human_bytes(speed)}/s"
            )

        sys.stderr.write("\r" + line[:120].ljust(120))
        sys.stderr.flush()
        self._rendered = True


def make_progress() -> SimpleProgress:
    return SimpleProgress()


class spinner:
    def __init__(self, description: str):
        self._description = description
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._rendered = False

    def __enter__(self):
        if sys.stderr.isatty():
            self._thread = threading.Thread(target=self._spin, daemon=True)
            self._thread.start()
        else:
            sys.stderr.write(f"{self._description}...\n")
            sys.stderr.flush()
        return self

    def done(self, description: str):
        with self._lock:
            self._description = description

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
        if exc and exc[0] is not None:
            if self._rendered:
                sys.stderr.write("\n")
                sys.stderr.flush()
            return False
        with self._lock:
            description = self._description
        if sys.stderr.isatty():
            sys.stderr.write(f"\r{description} done\n")
        else:
            sys.stderr.write(f"{description} done\n")
        sys.stderr.flush()
        return False

    def _spin(self):
        frames = "|/-\\"
        index = 0
        while not self._stop.is_set():
            with self._lock:
                description = self._description
            sys.stderr.write(f"\r{frames[index % len(frames)]} {description}")
            sys.stderr.flush()
            self._rendered = True
            index += 1
            time.sleep(0.1)


class ProgressReader:
    def __init__(self, data: bytes, progress: SimpleProgress, task_id, chunk: int = 64 * 1024, limiter=None):
        self._buf = io.BytesIO(data)
        self._progress = progress
        self._task = task_id
        self._chunk = chunk
        self._limiter = limiter
        self.len = len(data)

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = self._chunk
        else:
            size = min(size, self._chunk)
        data = self._buf.read(size)
        if data:
            if self._limiter is not None:
                self._limiter.throttle(len(data))
            self._progress.update(self._task, advance=len(data))
        return data

    def seek(self, *args, **kwargs):
        return self._buf.seek(*args, **kwargs)

    def tell(self):
        return self._buf.tell()

    def close(self):
        return self._buf.close()
