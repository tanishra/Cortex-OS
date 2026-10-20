"""Human-wall detection: signatures for CAPTCHA / 2FA / verification pages.

Two tiers:
- STRONG signatures are widget/script markers (cf-challenge, g-recaptcha …)
  that never appear inside ordinary prose — they always fire.
- WEAK signatures are plain phrases ("verification code", "captcha", "two
  factor") that articles, help pages and login screens also contain. They
  fire only when the page looks like a bare challenge: short DOM text and
  no password field (a login you can type into is a task, not a wall;
  2FA/OTP codes are never password-type inputs).
"""

import re

_STRONG: list[tuple[re.Pattern, str]] = [
    (re.compile(p, re.I), reason)
    for p, reason in [
        (r"cf-challenge|challenges\.cloudflare\.com", "cloudflare_challenge"),
        (r"recaptcha|g-recaptcha", "recaptcha"),
        (r"hcaptcha", "hcaptcha"),
        (r"turnstile", "cloudflare_turnstile"),
    ]
]

_WEAK: list[tuple[re.Pattern, str]] = [
    (re.compile(p, re.I), reason)
    for p, reason in [
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
# Wall pages are thin challenges — a long page with a weak keyword is
# prose, not a wall.
_WEAK_MAX_TEXT = 1500
_PASSWORD_RE = re.compile(r'type\s*=\s*["\']?password["\']?', re.I)


def detect_human_wall(url: str, title: str, dom_text: str) -> str | None:
    """Return a reason string if the page looks like a human-only wall, else None."""
    haystack = f"{url}\n{title}\n{dom_text[:_DOM_SCAN_LIMIT]}"
    for pattern, reason in _STRONG:
        if pattern.search(haystack):
            return reason
    if len(haystack) >= _WEAK_MAX_TEXT or _PASSWORD_RE.search(haystack):
        return None
    for pattern, reason in _WEAK:
        if pattern.search(haystack):
            return reason
    return None
