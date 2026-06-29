"""Render a server-issued human-verification (captcha) challenge in the terminal.

The server throttles brute-force logins/registrations by demanding a Cloudflare
Turnstile solve (see the server's bruteforce/captcha modules). It returns only a
challenge URL; the user opens it on any device, solves it, and the solve grants
the bound context a short quota the next attempt consumes. So all the client does
is make the challenge easy to reach — offer to open it in a local browser, print a
clickable link, and show a scannable QR for a phone — then wait before retrying.

Degrades cleanly on a headless box: if no browser opens, the link and QR remain.
"""

import webbrowser

from . import ui


def render_challenge(challenge_url: str, message: str = "") -> None:
    """Show the challenge, offer to open it locally, and print a scannable QR."""
    ui.warn(message or "Confirm you are human to continue.")
    ui.write()
    ui.write("Complete this verification to continue:")
    ui.write(f"  {challenge_url}")
    if ui.confirm("Open this link in your browser now?", default=True):
        _open_browser(challenge_url)
    _print_qr(challenge_url)
    ui.write("You can also open the link on another device.")
    ui.write()


def _open_browser(url: str) -> None:
    """Best-effort local-browser open. On a headless box (no GUI) this no-ops or
    raises; we swallow it and leave the link + QR for a phone / another device."""
    try:
        if not webbrowser.open(url):
            ui.info("No browser available — use the link or QR above.")
    except Exception:
        ui.info("Could not open a browser — use the link or QR above.")


def _print_qr(data: str) -> None:
    """Best-effort terminal QR of the challenge URL. Silently skips if segno is
    unavailable (the link above is always enough on its own)."""
    if not data:
        return
    try:
        import segno
    except Exception:
        return
    try:
        qr = segno.make(data, error="m")
    except Exception:
        return
    ui.write()
    ui.write("Or scan this QR code with your phone:")
    try:
        qr.terminal(compact=True)
    except TypeError:
        # Older segno without the compact kwarg.
        qr.terminal()
    except Exception:
        pass
