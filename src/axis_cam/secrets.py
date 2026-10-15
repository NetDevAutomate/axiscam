"""Which device parameters hold credentials.

Axis devices keep some secrets in ordinary parameters -- SNMP community
strings, proxy and 802.1X passwords, wireless PSKs -- and
``param.cgi?action=list`` returns them like any other value. Everything that
handles the parameter tree uses this one rule to recognise them: backup
manifests declare them, restore leaves them alone unless asked, the CLI does
not echo them and the MCP server redacts them.

The rule is by *name* and deliberately broad: a false positive costs one
parameter that needs an explicit opt-in; a false negative leaks a credential.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

#: Matched case-insensitively against the full dotted name.
SECRET_NAME = re.compile(
    r"(?i)pass(word|wd|phrase)?|secret|community|psk|token|credential|privatekey"
)


def is_secret_name(name: str) -> bool:
    """Whether a parameter name looks like it holds a credential."""
    return bool(SECRET_NAME.search(name))


def credential_names(params: Mapping[str, str]) -> list[str]:
    """Sorted names of credential parameters that have a value.

    An empty value is "not set" and is not a credential worth declaring.
    """
    return sorted(name for name, value in params.items() if value and is_secret_name(name))


__all__ = ["SECRET_NAME", "credential_names", "is_secret_name"]
