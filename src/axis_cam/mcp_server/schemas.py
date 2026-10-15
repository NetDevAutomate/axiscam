"""Result models every tool returns (the structured content of a call)."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from axis_cam.mcp_server.devices import DeviceSummary


class DeviceList(BaseModel):
    """Configured devices; names are what every `device` argument accepts."""

    devices: list[DeviceSummary]


class ModuleList(BaseModel):
    """Readable modules on one device, by what its API discovery advertises."""

    device: str
    advertised: list[str] = Field(description="Discoverable REST modules this device advertises.")
    not_advertised: list[str] = Field(description="Modules this device does not advertise.")
    never_gated: list[str] = Field(description="CGI modules, always attempted.")


class ModuleRead(BaseModel):
    """One module read. `status` says whether `value` is real; `unreadable` is never 'disabled'."""

    device: str
    module: str
    status: Literal["ok", "not_advertised", "unreadable", "error"]
    model: str | None = None
    value: dict[str, Any] | None = None
    reason: str | None = None


class Payload(BaseModel):
    """A library result passed through as JSON."""

    device: str
    result: dict[str, Any]


class ParamItem(BaseModel):
    """One parameter; `redacted` is true when the value was withheld as a credential."""

    name: str
    value: str
    redacted: bool = False


class ParamPage(BaseModel):
    """A page of parameters under a prefix; follow `next_cursor` for more."""

    device: str
    prefix: str
    total: int
    items: list[ParamItem]
    next_cursor: int | None = None


class BackupInfo(BaseModel):
    """One backup in the server's backup directory."""

    backup_id: str
    device: dict[str, str] = Field(default_factory=dict)
    created_at: str = ""
    files: int = 0
    errors: dict[str, str] = Field(default_factory=dict)


class BackupBackups(BaseModel):
    """Backups in the server's backup directory, newest first."""

    backups: list[BackupInfo]


class BackupCheck(BaseModel):
    """Result of re-hashing a backup's files against its manifest."""

    backup_id: str
    ok: bool
    problems: list[str]


class PlanResult(BaseModel):
    """A stored plan: nothing has been written. Apply it with `apply_plan`."""

    plan_id: str
    kind: str
    device: str
    serial: str
    expires_in_seconds: int
    plan: dict[str, Any]
    note: str = (
        "Plan only: nothing was written to the device. To apply it, call apply_plan; "
        "the server asks the human to confirm and refuses on hosts that cannot ask."
    )


class Confirmation(BaseModel):
    """What the human is asked. Rendered by the host as a form."""

    approve: bool = Field(description="Apply exactly this change to the device now.")


class AppliedChange(BaseModel):
    """One change attempted by `apply_plan`, verified by reading it back."""

    name: str
    ok: bool
    detail: str


class ApplyResult(BaseModel):
    """Outcome of `apply_plan`: applied, partial, failed, declined or refused."""

    plan_id: str
    device: str
    status: Literal["applied", "partial", "failed", "declined", "refused"]
    reason: str | None = None
    results: list[AppliedChange] = Field(default_factory=list)
