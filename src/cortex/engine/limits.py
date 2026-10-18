"""Per-domain start throttling, shared across workers via Redis."""

import asyncio
import logging
import time
from urllib.parse import urlparse

logger = logging.getLogger("cortex.limits")


async def domain_wait(redis, host: str, interval_s: float) -> float:
    """Sleep until `interval_s` has passed since the last task started on
    `host`. Returns seconds waited. Redis failure → no throttle (log + go)."""
    if not host or interval_s <= 0:
        return 0.0
    key = f"cortex:rate:{host}"
    waited = 0.0
    try:
        raw = await redis.get(key)
        if raw is not None:
            remaining = interval_s - (time.time() - float(raw))
            if remaining > 0:
                logger.info("Rate limit: waiting %.1fs for %s", remaining, host)
                await asyncio.sleep(remaining)
                waited = remaining
        await redis.set(key, str(time.time()), ex=max(1, int(interval_s * 2)))
        return waited
    except Exception:
        logger.warning("Rate-limit check failed for %s; proceeding", host, exc_info=True)
        return 0.0


def host_of(url: str | None) -> str:
    if not url:
        return ""
    return (urlparse(url).hostname or "").lower()
