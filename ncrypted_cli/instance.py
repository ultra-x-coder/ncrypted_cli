"""Machine-wide single-instance lock.

Only one ncrypted process may run at a time. This is NOT a rate limiter (those
are trivially bypassed by editing local state or hitting the API directly); it
is a hard mutual exclusion so the official client cannot be turned into a
parallel request generator / DDoS amplifier against the server.

It uses an advisory whole-file lock (flock) on ~/.ncrypted/ncrypted.lock held
for the process lifetime. The OS releases the lock automatically when the
process exits or is killed, so there is no stale-lock problem and nothing to
clean up. A second concurrent process fails fast instead of waiting.
"""

from . import auth

try:  # Unix (macOS / Linux)
    import fcntl
    _HAVE_FCNTL = True
except ImportError:  # pragma: no cover - Windows / unsupported
    _HAVE_FCNTL = False


class AlreadyRunning(Exception):
    """Another ncrypted process already holds the single-instance lock."""


# Kept at module scope so the file descriptor is not garbage-collected for the
# lifetime of the process (closing the fd would release the lock).
_handle = None


def acquire() -> None:
    """Acquire the single-instance lock. Raises AlreadyRunning if another
    ncrypted process holds it. No-op on platforms without flock."""
    global _handle
    if not _HAVE_FCNTL:
        return
    auth.TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    fh = open(auth.TOKEN_DIR / "ncrypted.lock", "w")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        raise AlreadyRunning(
            "Another ncrypted process is already running on this machine. "
            "Only one can run at a time — wait for it to finish, then retry."
        )
    _handle = fh
