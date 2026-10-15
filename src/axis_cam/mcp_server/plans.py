"""Server-minted plans: the only thing ``apply_plan`` will accept.

A plan records *what* would change on *which* device (by serial number) and
when it stops being valid. ``apply_plan`` applies one only after a confirmation
the server renders from the stored plan -- a handle proves sequencing, not
consent (see the design decision) -- and consumes it on approval.

Plans live in memory: a restart forgets them, which is the safe direction.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

#: How long a plan stays valid (seconds).
PLAN_TTL = 600


@dataclass(frozen=True)
class StoredPlan:
    """One plan as the server holds it."""

    plan_id: str
    kind: str  # "param_restore" | "account_change"
    device: str
    serial: str
    payload: dict[str, Any]
    digest: str
    created: float
    expires: float
    #: What apply needs that must never be returned to the client (unredacted
    #: values, the backup path). Excluded from repr.
    private: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass
class PlanStore:
    """In-memory plans keyed by an unguessable id.

    Args:
        ttl: Seconds a plan stays valid.
        clock: Monotonic time source (injectable for tests).
    """

    ttl: int = PLAN_TTL
    clock: Callable[[], float] = time.monotonic
    _plans: dict[str, StoredPlan] = field(default_factory=dict)

    def mint(
        self,
        kind: str,
        device: str,
        serial: str,
        payload: dict[str, Any],
        *,
        private: dict[str, Any] | None = None,
    ) -> StoredPlan:
        """Store a new plan and return it.

        ``payload`` is what the client sees; ``private`` is what apply needs and
        the client must not see (it still counts towards the digest).
        """
        self._expire()
        now = self.clock()
        digest = hashlib.sha256(
            json.dumps(
                {
                    "kind": kind,
                    "device": device,
                    "serial": serial,
                    "payload": payload,
                    "private": private or {},
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        plan = StoredPlan(
            plan_id=secrets.token_urlsafe(16),
            kind=kind,
            device=device,
            serial=serial,
            payload=payload,
            digest=digest,
            created=now,
            expires=now + self.ttl,
            private=dict(private or {}),
        )
        self._plans[plan.plan_id] = plan
        return plan

    def get(self, plan_id: str) -> StoredPlan | None:
        """The plan, or ``None`` if unknown or expired."""
        self._expire()
        return self._plans.get(plan_id)

    def take(self, plan_id: str) -> StoredPlan | None:
        """Remove and return the plan (single use), or ``None``."""
        self._expire()
        return self._plans.pop(plan_id, None)

    def __len__(self) -> int:
        self._expire()
        return len(self._plans)

    def _expire(self) -> None:
        now = self.clock()
        for plan_id in [p for p, plan in self._plans.items() if plan.expires <= now]:
            del self._plans[plan_id]


__all__ = ["PLAN_TTL", "PlanStore", "StoredPlan"]
