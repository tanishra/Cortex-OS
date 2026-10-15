"""Human-wall detection: signatures for CAPTCHA / 2FA / verification pages.

Deterministic keyword matching on url + title + DOM text. When a signature
matches, the runner pauses the agent and marks the task waiting_human.
"""

import re

_SIGNATURES: list[tuple[re.Pattern, str]] = [
    (re.compile(p, re.I), reason)
    for p, reason in [
        (r"cf-challenge|challenges\.cloudflare\.com", "cloudflare_challenge"),
        (r"recaptcha|g-recaptcha", "recaptcha"),
        (r"hcaptcha", "hcaptcha"),
        (r"turnstile", "cloudflare_turnstile"),
        (r"verify you are human|verify that you are human", "human_verify"),
        (r"are you a robot|i'm not a robot|im not a robot", "robot_check"),
        (r"unusual traffic|automated queries", "bot_detection"),
        (r"two-?factor|2fa\b", "two_factor"),
        (r"verification code|enter the code|one-?time (?:code|pass)", "otp"),
        (r"authenticator app", "totp"),
        (r"security check(?:point)?\b", "security_checkpoint"),
        (r"captcha", "captcha_generic"),
    ]
]

_DOM_SCAN_LIMIT = 50_000


def detect_human_wall(url: str, title: str, dom_text: str) -> str | None:
    """Return a reason string if the page looks like a human-only wall, else None."""
    haystack = f"{url}\n{title}\n{dom_text[:_DOM_SCAN_LIMIT]}"
    for pattern, reason in _SIGNATURES:
        if pattern.search(haystack):
            return reason
    return None
