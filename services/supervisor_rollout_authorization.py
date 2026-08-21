"""Fail-closed authorization for the controlled Supervisor reviewer rollout."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


SUPERVISOR_REVIEWER_ALLOWLIST_ENV = "SUPERVISOR_ORCHESTRATION_ALLOWED_USER_IDS"


@dataclass(frozen=True)
class SupervisorReviewerAllowlist:
    user_ids: frozenset[int]
    invalid_values: tuple[str, ...] = ()

    @property
    def configured(self) -> bool:
        return bool(self.user_ids or self.invalid_values)

    @property
    def valid(self) -> bool:
        return not self.invalid_values


@dataclass(frozen=True)
class SupervisorRolloutAuthorization:
    authorized: bool
    source: str
    internal_reviewer: bool
    allowlist_configured: bool
    allowlist_user_count: int
    configuration_valid: bool


def parse_supervisor_reviewer_allowlist(
    raw_value: Any,
) -> SupervisorReviewerAllowlist:
    """Parse positive integer user IDs without silently accepting bad entries."""

    if raw_value is None:
        values: Iterable[Any] = ()
    elif isinstance(raw_value, str):
        values = raw_value.split(",")
    elif isinstance(raw_value, Iterable):
        values = raw_value
    else:
        values = (raw_value,)

    user_ids: set[int] = set()
    invalid_values: list[str] = []
    for raw_entry in values:
        entry = str(raw_entry).strip()
        if not entry:
            continue
        try:
            user_id = int(entry)
        except (TypeError, ValueError):
            invalid_values.append(entry)
            continue
        if isinstance(raw_entry, bool) or user_id <= 0 or str(user_id) != entry:
            invalid_values.append(entry)
            continue
        user_ids.add(user_id)

    return SupervisorReviewerAllowlist(
        user_ids=frozenset(user_ids),
        invalid_values=tuple(sorted(set(invalid_values))),
    )


def authorize_supervisor_rollout_user(
    *,
    user_id: int | None,
    is_admin: bool,
    allowed_user_ids: Any,
) -> SupervisorRolloutAuthorization:
    """Authorize only admins or explicitly allowlisted internal reviewers."""

    allowlist = parse_supervisor_reviewer_allowlist(allowed_user_ids)
    common = {
        "allowlist_configured": allowlist.configured,
        "allowlist_user_count": len(allowlist.user_ids),
        "configuration_valid": allowlist.valid,
    }
    if not allowlist.valid:
        return SupervisorRolloutAuthorization(
            authorized=False,
            source="invalid_allowlist",
            internal_reviewer=False,
            **common,
        )
    if is_admin:
        return SupervisorRolloutAuthorization(
            authorized=True,
            source="admin",
            internal_reviewer=False,
            **common,
        )
    if user_id is not None and int(user_id) in allowlist.user_ids:
        return SupervisorRolloutAuthorization(
            authorized=True,
            source="internal_reviewer_allowlist",
            internal_reviewer=True,
            **common,
        )
    return SupervisorRolloutAuthorization(
        authorized=False,
        source="not_authorized",
        internal_reviewer=False,
        **common,
    )


def supervisor_rollout_denial_reason(
    authorization: SupervisorRolloutAuthorization,
) -> str:
    if not authorization.configuration_valid:
        return (
            f"{SUPERVISOR_REVIEWER_ALLOWLIST_ENV} contains an invalid user ID; "
            "Supervisor rollout access is disabled."
        )
    return "Explicit internal reviewer authorization is required."
