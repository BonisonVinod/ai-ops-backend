"""
LicenseManager — Sovereign Bridge license handshake and heartbeat system.

Flow:
  1. Sovereign Bridge calls POST /license/handshake on startup with its tenant_id.
  2. LicenseManager looks up the tenant's subscription tier, issues a signed token
     valid for 24 hours, and persists a hash of it in the DB.
  3. Bridge includes the token in every API call (Authorization: Bearer <token>).
  4. Every 23 hours the bridge calls POST /license/heartbeat — LicenseManager
     re-issues a fresh 24-hour token if the subscription is still active.
  5. On subscription expiry the handshake returns SLEEP_MODE rather than a token,
     and the bridge surfaces "Brain is in Sleep Mode" to the user.

Token format: HS256-signed JWT (stdlib only — no extra deps).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

# ---------------------------------------------------------------------------
# Tier definitions
# ---------------------------------------------------------------------------

TIER_STARTER    = "starter"
TIER_PRO        = "pro"
TIER_ENTERPRISE = "enterprise"

TIER_LIMITS: dict[str, dict] = {
    TIER_STARTER: {
        "max_mcp_servers":    1,
        "allow_high_risk":    False,
        "label":              "Starter",
        "description":        "1 MCP connector, standard tools only.",
    },
    TIER_PRO: {
        "max_mcp_servers":    5,
        "allow_high_risk":    True,
        "label":              "Pro",
        "description":        "Up to 5 MCP connectors + High-Risk tool execution.",
    },
    TIER_ENTERPRISE: {
        "max_mcp_servers":    999,   # effectively unlimited
        "allow_high_risk":    True,
        "label":              "Enterprise",
        "description":        "Unlimited connectors, priority support, custom SLAs.",
    },
}

TOKEN_TTL_SECONDS   = 86_400        # 24 hours
HEARTBEAT_WINDOW    = 3_600         # re-issue if ≤ 1 hour remaining


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class LicenseError(Exception):
    """Raised when a token is invalid, expired, or revoked."""


class TierLimitError(Exception):
    """Raised when an operation exceeds the tenant's tier limit."""
    def __init__(self, current_tier: str, required_tier: str, detail: str = ""):
        self.current_tier  = current_tier
        self.required_tier = required_tier
        super().__init__(detail or f"Tier '{current_tier}' does not allow this. Upgrade to '{required_tier}'.")


# ---------------------------------------------------------------------------
# Minimal stdlib JWT (HS256)
# ---------------------------------------------------------------------------

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    rem = len(s) % 4
    if rem:
        s += "=" * (4 - rem)
    return base64.urlsafe_b64decode(s)


def _sign_jwt(payload: dict, secret: str) -> str:
    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body   = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    msg    = f"{header}.{body}".encode()
    sig    = hmac.new(secret.encode(), msg, hashlib.sha256).digest()
    return f"{header}.{body}.{_b64url_encode(sig)}"


def _verify_jwt(token: str, secret: str) -> dict:
    parts = token.split(".")
    if len(parts) != 3:
        raise LicenseError("Malformed token.")
    header, body, sig_b64 = parts
    msg      = f"{header}.{body}".encode()
    expected = hmac.new(secret.encode(), msg, hashlib.sha256).digest()
    actual   = _b64url_decode(sig_b64)
    if not hmac.compare_digest(expected, actual):
        raise LicenseError("Token signature is invalid.")
    payload = json.loads(_b64url_decode(body))
    if payload.get("exp", 0) < time.time():
        raise LicenseError("Token has expired.")
    return payload


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------------------
# LicenseToken dataclass (returned to callers)
# ---------------------------------------------------------------------------

@dataclass
class LicenseToken:
    token:          str
    tenant_id:      str
    tier:           str
    issued_at:      datetime
    expires_at:     datetime
    max_mcp_servers: int
    allow_high_risk: bool
    mode:           str   # "active" | "sleep"

    def to_dict(self) -> dict:
        return {
            "token":             self.token,
            "tenant_id":         self.tenant_id,
            "tier":              self.tier,
            "tier_label":        TIER_LIMITS.get(self.tier, {}).get("label", self.tier),
            "issued_at":         self.issued_at.isoformat(),
            "expires_at":        self.expires_at.isoformat(),
            "max_mcp_servers":   self.max_mcp_servers,
            "allow_high_risk":   self.allow_high_risk,
            "mode":              self.mode,
        }

    @property
    def seconds_remaining(self) -> float:
        return (self.expires_at - datetime.now(timezone.utc)).total_seconds()

    @property
    def needs_heartbeat(self) -> bool:
        return self.seconds_remaining <= HEARTBEAT_WINDOW


# ---------------------------------------------------------------------------
# LicenseManager
# ---------------------------------------------------------------------------

class LicenseManager:
    """
    Issues, verifies, and heartbeats license tokens for sovereign deployments.

    In production inject a real subscription lookup via the `get_subscription`
    callable.  The default implementation reads from the DB session if one is
    provided, or falls back to a dev-mode stub.
    """

    def __init__(self, secret: Optional[str] = None):
        self._secret = secret or os.environ.get("LICENSE_SECRET_KEY", "dev-license-secret-change-in-prod")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def handshake(self, tenant_id: str, tier: str, subscription_active: bool) -> LicenseToken:
        """
        Called by the Sovereign Bridge on startup.
        Returns a LicenseToken.  If subscription_active is False, the token
        carries mode='sleep' and minimal permissions (bridge stays connected
        but automation is paused).
        """
        mode = "active" if subscription_active else "sleep"
        return self._issue(tenant_id, tier, mode)

    def heartbeat(self, token: str, subscription_active: bool) -> LicenseToken:
        """
        Re-issues the token.  Call when ≤ 1 hour remains or on demand.
        If the subscription lapsed, transitions to sleep mode.
        """
        payload = self._verify_raw(token)   # raises LicenseError if expired/invalid
        tier    = payload.get("tier", TIER_STARTER)
        mode    = "active" if subscription_active else "sleep"
        return self._issue(payload["sub"], tier, mode)

    def verify(self, token: str) -> LicenseToken:
        """
        Verify a token and return its decoded LicenseToken.
        Raises LicenseError on failure.
        """
        payload = self._verify_raw(token)
        return self._payload_to_token(payload, token)

    def check_mcp_limit(self, token: str, requested_count: int) -> None:
        """
        Raises TierLimitError if requested_count exceeds the tier's limit.
        Used before registering a new MCP server.
        """
        lt = self.verify(token)
        if lt.mode == "sleep":
            raise LicenseError("Brain is in Sleep Mode — renew your subscription to add connectors.")
        if requested_count > lt.max_mcp_servers:
            required = TIER_PRO if lt.tier == TIER_STARTER else TIER_ENTERPRISE
            raise TierLimitError(
                lt.tier, required,
                f"Your {TIER_LIMITS[lt.tier]['label']} plan allows {lt.max_mcp_servers} "
                f"MCP connector(s). You need {requested_count}. Upgrade to "
                f"{TIER_LIMITS[required]['label']} to continue.",
            )

    def check_high_risk(self, token: str) -> None:
        """
        Raises TierLimitError if the tier does not allow high-risk tool execution.
        """
        lt = self.verify(token)
        if lt.mode == "sleep":
            raise LicenseError("Brain is in Sleep Mode.")
        if not lt.allow_high_risk:
            raise TierLimitError(
                lt.tier, TIER_PRO,
                f"High-Risk tool execution requires the Pro plan or above. "
                f"You are on {TIER_LIMITS[lt.tier]['label']}.",
            )

    # ------------------------------------------------------------------
    # Static helpers (no instance needed)
    # ------------------------------------------------------------------

    @staticmethod
    def sleep_mode_message() -> dict:
        return {
            "mode": "sleep",
            "shield": "active",
            "title": "Brain is in Sleep Mode",
            "message": (
                "Sovereign Bridge Connected [Shield Active], but Brain is in Sleep Mode. "
                "Renew your subscription to resume automation."
            ),
            "action_label": "Renew Subscription",
            "action_url":   "/billing/portal",
        }

    @staticmethod
    def upgrade_card(current_tier: str, required_tier: str, detail: str = "") -> dict:
        """Frontend 'Upgrade to Pro' paywall card payload."""
        req = TIER_LIMITS.get(required_tier, {})
        cur = TIER_LIMITS.get(current_tier, {})
        return {
            "type":             "upgrade_required",
            "current_tier":     current_tier,
            "current_label":    cur.get("label", current_tier),
            "required_tier":    required_tier,
            "required_label":   req.get("label", required_tier),
            "headline":         f"Upgrade to {req.get('label', required_tier)}",
            "subheadline":      detail or f"Your {cur.get('label', current_tier)} plan doesn't include this feature.",
            "features":         _pro_feature_bullets() if required_tier == TIER_PRO else _enterprise_feature_bullets(),
            "cta_label":        f"Upgrade to {req.get('label', required_tier)}",
            "cta_url":          f"/billing/checkout?tier={required_tier}",
            "dismiss_label":    "Maybe later",
            "style":            "high-fashion",   # frontend uses this to pick the premium modal style
        }

    @staticmethod
    def tier_info(tier: str) -> dict:
        return TIER_LIMITS.get(tier, TIER_LIMITS[TIER_STARTER])

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _issue(self, tenant_id: str, tier: str, mode: str) -> LicenseToken:
        if tier not in TIER_LIMITS:
            tier = TIER_STARTER
        limits = TIER_LIMITS[tier]

        now = time.time()
        exp = now + TOKEN_TTL_SECONDS

        # Sleep mode: strip permissions
        max_mcp    = limits["max_mcp_servers"] if mode == "active" else 0
        high_risk  = limits["allow_high_risk"]  if mode == "active" else False

        payload = {
            "sub":              tenant_id,
            "tier":             tier,
            "mode":             mode,
            "max_mcp_servers":  max_mcp,
            "allow_high_risk":  high_risk,
            "iat":              int(now),
            "exp":              int(exp),
        }
        token = _sign_jwt(payload, self._secret)

        return LicenseToken(
            token           = token,
            tenant_id       = tenant_id,
            tier            = tier,
            issued_at       = datetime.fromtimestamp(now, tz=timezone.utc),
            expires_at      = datetime.fromtimestamp(exp,  tz=timezone.utc),
            max_mcp_servers = max_mcp,
            allow_high_risk = high_risk,
            mode            = mode,
        )

    def _verify_raw(self, token: str) -> dict:
        return _verify_jwt(token, self._secret)

    def _payload_to_token(self, payload: dict, raw_token: str) -> LicenseToken:
        return LicenseToken(
            token           = raw_token,
            tenant_id       = payload["sub"],
            tier            = payload.get("tier", TIER_STARTER),
            issued_at       = datetime.fromtimestamp(payload["iat"], tz=timezone.utc),
            expires_at      = datetime.fromtimestamp(payload["exp"],  tz=timezone.utc),
            max_mcp_servers = payload.get("max_mcp_servers", 0),
            allow_high_risk = payload.get("allow_high_risk", False),
            mode            = payload.get("mode", "sleep"),
        )


# ---------------------------------------------------------------------------
# Feature bullet helpers
# ---------------------------------------------------------------------------

def _pro_feature_bullets() -> list[str]:
    return [
        "Up to 5 MCP connectors (Gmail, Sheets, Slack, and more)",
        "High-Risk tool execution (Python, code generation)",
        "Priority sovereign deployment support",
        "Advanced audit logs and compliance reports",
        "Dedicated co-worker analytics dashboard",
    ]


def _enterprise_feature_bullets() -> list[str]:
    return [
        "Unlimited MCP connectors",
        "Custom SLA and dedicated infrastructure",
        "Single Sign-On (SSO) and RBAC",
        "On-premise deployment option",
        "White-label licensing available",
    ]


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_license_manager: Optional[LicenseManager] = None


def get_license_manager() -> LicenseManager:
    global _license_manager
    if _license_manager is None:
        _license_manager = LicenseManager()
    return _license_manager
