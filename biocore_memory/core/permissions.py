# -*- coding: utf-8 -*-
"""Scope-based read/write permissions (default OFF; pure, no astrbot)."""
from __future__ import annotations

enabled = False
ENABLED = False
ADMIN_ROLES = ("admin", "owner", "system", "superuser", "root")
READONLY_ROLES = ("guest", "readonly", "viewer")
PUBLIC_SCOPES = ("*", "public", "all", "shared")


def _principal(principal):
    value = principal if isinstance(principal, dict) else {}
    role = str(value.get("role") or "user").strip().lower()
    identifier = str(value.get("id") or value.get("user_id") or "").strip()
    scopes = value.get("scopes")
    if not isinstance(scopes, list):
        scopes = [value.get("scope")] if value.get("scope") is not None else []
    return role, identifier, {str(s).strip() for s in scopes if str(s).strip()}


def _scopes(entry):
    if not isinstance(entry, dict):
        return set()
    raw = entry.get("scope")
    if raw is None:
        raw = entry.get("scopes")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple, set)):
        return set()
    return {str(value).strip() for value in raw if str(value).strip()}


def _can_access(entry, principal):
    if not enabled:
        return True
    role, identifier, principal_scopes = _principal(principal)
    if role in ADMIN_ROLES:
        return True
    scopes = _scopes(entry)
    if not scopes:
        return True
    if scopes & set(PUBLIC_SCOPES):
        return True
    if identifier and (identifier in scopes or ("user:" + identifier) in scopes):
        return True
    return bool(principal_scopes & scopes)


def can_read(entry, principal=None):
    """True when principal may read entry (disabled -> always True)."""
    try:
        return _can_access(entry, principal)
    except Exception:
        return not enabled


def can_write(entry, principal=None):
    """True when principal may write entry; readonly roles are denied when on."""
    try:
        if not enabled:
            return True
        role, _identifier, _scopes_set = _principal(principal)
        if role in READONLY_ROLES:
            return False
        return _can_access(entry, principal)
    except Exception:
        return not enabled
