"""Hard caps for the public Ask endpoint.

Two scopes: per-IP sliding windows, and a global daily budget accumulated
from real token usage. Slots are RESERVED at check time (so concurrent
bursts and failed calls still count) and cost is settled after the call.
In-process state by design.
# ponytail: state resets on container restart; move to a SQLite counter
# table if abuse ever shows up in practice.
"""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

# claude-haiku-4-5 list prices, USD per million tokens
PRICE_IN = 1.00
PRICE_OUT = 5.00


class AskLimiter:
    def __init__(self):
        self.per_hour = int(os.environ.get("ASK_PER_IP_HOUR", 5))
        self.per_day = int(os.environ.get("ASK_PER_IP_DAY", 20))
        self.daily_requests = int(os.environ.get("ASK_DAILY_REQUESTS", 100))
        self.daily_budget = float(os.environ.get("ASK_DAILY_BUDGET_USD", 1.0))
        self.hits: dict[str, deque] = defaultdict(deque)
        self.day = self._today()
        self.day_requests = 0
        self.day_cost = 0.0
        self._lock = threading.Lock()

    def _today(self) -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def _roll_day(self) -> None:
        today = self._today()
        if today != self.day:
            self.day, self.day_requests, self.day_cost = today, 0, 0.0

    def check(self, ip: str) -> tuple[bool, str | None, int]:
        """Returns (allowed, blocked_scope, retry_after_seconds).

        Allowing RESERVES the slot immediately — the request counts whether
        or not the downstream call succeeds.
        """
        with self._lock:
            self._roll_day()
            if self.day_requests >= self.daily_requests or self.day_cost >= self.daily_budget:
                mid = datetime.now(timezone.utc).replace(hour=23, minute=59, second=59)
                return False, "global", int((mid - datetime.now(timezone.utc)).total_seconds()) + 1
            now = time.time()
            q = self.hits[ip]
            while q and q[0] < now - 86400:
                q.popleft()
            recent = [t for t in q if t > now - 3600]
            if len(recent) >= self.per_hour:
                return False, "ip", int(3600 - (now - min(recent))) + 1 if recent else 3600
            if len(q) >= self.per_day:
                return False, "ip", int(86400 - (now - q[0])) + 1
            q.append(now)
            self.day_requests += 1
            if len(self.hits) > 5000:  # prune idle IPs
                cutoff = now - 86400
                for k in [k for k, dq in self.hits.items() if not dq or dq[-1] < cutoff]:
                    del self.hits[k]
            return True, None, 0

    def settle(self, input_tokens: int, output_tokens: int) -> None:
        """Add the real cost of a completed call to the daily budget."""
        with self._lock:
            self._roll_day()
            self.day_cost += input_tokens * PRICE_IN / 1e6 + output_tokens * PRICE_OUT / 1e6


def client_ip(request) -> str:
    """The real client IP, per deployment topology.

    TRUST_CF_CONNECTING_IP=1 is set ONLY where Cloudflare's edge is the sole
    route in (the AppliedIQ box: zero inbound ports, cloudflared tunnel only).
    There the edge sets CF-Connecting-IP and OVERWRITES any client-supplied
    value, so it cannot be forged. NEVER set the flag on a directly-reachable
    host: a visitor could simply send the header and mint a fresh bucket per
    request, evading the per-IP cap on an endpoint that spends real money.

    Fallback is the LAST X-Forwarded-For hop — what a trusted proxy appends;
    the earlier hops are client-supplied and trivially spoofable.
    """
    if os.environ.get("TRUST_CF_CONNECTING_IP") == "1":
        cf = request.headers.get("cf-connecting-ip")
        if cf:
            return cf.strip()
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"
