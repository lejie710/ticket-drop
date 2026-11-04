"""Runtime settings, read once from environment variables."""

import os
import time
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    db_path: str = ".local/ticket-drop.db"
    hold_seconds: int = 300
    max_seats: int = 4
    # Epoch milliseconds. None means the sale is already open.
    sale_opens_at_ms: int | None = None
    # Seconds the mock payment gateway waits before reporting a timeout.
    payment_timeout_seconds: float = 2.0
    # Per-account token bucket for seat changes.
    hold_rate_per_second: float = 5.0
    hold_burst: int = 10
    # Failed logins allowed per client address per minute.
    failed_logins_per_minute: int = 10
    # Seeded faults to switch on. Empty in normal use. See app/faults.py.
    faults: frozenset[str] = field(default_factory=frozenset)
    # Exposes /api/_test routes for controlling time. Never on by default.
    test_hooks: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ
        opens_at = None
        if env.get("TICKET_DROP_SALE_OPENS_IN"):
            opens_at = int(time.time() * 1000) + int(float(env["TICKET_DROP_SALE_OPENS_IN"]) * 1000)
        faults = frozenset(f.strip() for f in env.get("TICKET_DROP_FAULTS", "").split(",") if f.strip())
        return cls(
            db_path=env.get("TICKET_DROP_DB", cls.db_path),
            hold_seconds=int(env.get("TICKET_DROP_HOLD_SECONDS", cls.hold_seconds)),
            sale_opens_at_ms=opens_at,
            payment_timeout_seconds=float(env.get("TICKET_DROP_PAYMENT_TIMEOUT", cls.payment_timeout_seconds)),
            faults=faults,
            test_hooks=env.get("TICKET_DROP_TEST_HOOKS") == "1",
        )
