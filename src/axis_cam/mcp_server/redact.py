"""Keeping credentials out of everything the server returns.

Two mechanisms, because there are two ways a secret could leak:

* :func:`is_secret_name` / :func:`redact_params` — parameter *values* whose
  *names* say they are credentials (SNMP community strings, proxy and 802.1X
  passwords, PSKs). The device stores these in plain parameters and
  ``param.cgi?action=list`` returns them; the server replaces the value.
* :class:`Scrubber` — the device password itself, and its HTTP Basic form,
  removed from any string on the way out (error texts above all: an
  exception message is the easiest place for a credential to ride along).
"""

from __future__ import annotations

import base64
import re
from typing import Any

REDACTED = "[redacted]"

#: Parameter names that hold credentials. Matched case-insensitively against
#: the whole dotted name, so ``root.SNMP.ReadCommunity`` and
#: ``root.Network.Interface.I0.dot1x.EAPOL.KeyPassword`` are both caught.
SECRET_NAME = re.compile(
    r"(?i)pass(word|wd|phrase)?|secret|community|psk|token|credential|privatekey"
)


def is_secret_name(name: str) -> bool:
    """Whether a parameter name looks like it holds a credential."""
    return bool(SECRET_NAME.search(name))


def redact_params(params: dict[str, str]) -> dict[str, str]:
    """A copy with every credential-looking value replaced by ``[redacted]``.

    An empty value stays empty: "not set" is useful to know and leaks nothing.
    """
    return {k: (REDACTED if v and is_secret_name(k) else v) for k, v in params.items()}


class Scrubber:
    """Removes known secrets from strings and nested JSON-ready data.

    Args:
        username: Account the server authenticates as (used to build the
            HTTP Basic form of the password).
        secrets: Values that must never appear in output.
    """

    def __init__(self, username: str, *secrets: str) -> None:
        needles: set[str] = set()
        for secret in secrets:
            if not secret:
                continue
            needles.add(secret)
            needles.add(base64.b64encode(f"{username}:{secret}".encode()).decode())
        # longest first, so a value containing another is replaced whole
        self._needles = sorted(needles, key=len, reverse=True)

    def text(self, value: str) -> str:
        """``value`` with every secret replaced."""
        for needle in self._needles:
            value = value.replace(needle, REDACTED)
        return value

    def data(self, value: Any) -> Any:
        """Recursively scrub strings inside dicts, lists and tuples."""
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {self.text(str(k)): self.data(v) for k, v in value.items()}
        if isinstance(value, list | tuple):
            return [self.data(v) for v in value]
        return value


__all__ = ["REDACTED", "SECRET_NAME", "Scrubber", "is_secret_name", "redact_params"]
