"""
Billing & License API routes.

Endpoints
---------
POST /billing/checkout          Create a Stripe Checkout Session (plan upgrade)
GET  /billing/portal            Create a Stripe Customer Portal session
POST /billing/webhook           Stripe webhook — keeps DB in sync
GET  /billing/status            Current subscription status + graceful degradation
POST /billing/tier-gate         Check if N MCP servers are allowed (paywall gate)

POST /license/handshake         Sovereign bridge startup — issues a signed token
POST /license/heartbeat         Bridge calls every 23 h to refresh token
POST /license/verify            Validate a token (used by composer / engine)
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config.settings import settings
from app.database.models.license import License
from app.database.models.subscription import Subscription
from app.database.session.db import get_db
from app.engine.auth.license_manager import (
    TIER_ENTERPRISE,
    TIER_LIMITS,
    TIER_PRO,
    TIER_STARTER,
    LicenseError,
    LicenseManager,
    TierLimitError,
    get_license_manager,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["billing"])

stripe.api_key = settings.stripe_secret_key

# ---------------------------------------------------------------------------
# Stripe Price ID → tier mapping (populated from settings)
# ---------------------------------------------------------------------------

def _price_to_tier() -> dict[str, str]:
    return {
        settings.stripe_price_starter:    TIER_STARTER,
        settings.stripe_price_pro:        TIER_PRO,
        settings.stripe_price_enterprise: TIER_ENTERPRISE,
    }


def _tier_to_price(tier: str) -> str:
    mapping = {
        TIER_STARTER:    settings.stripe_price_starter,
        TIER_PRO:        settings.stripe_price_pro,
        TIER_ENTERPRISE: settings.stripe_price_enterprise,
    }
    return mapping.get(tier, settings.stripe_price_pro)


def _tier_limits(tier: str) -> tuple[int, bool]:
    meta = TIER_LIMITS.get(tier, TIER_LIMITS[TIER_STARTER])
    return meta["max_mcp_servers"], meta["allow_high_risk"]


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _get_or_create_subscription(tenant_id: str, db: Session) -> Subscription:
    sub = db.query(Subscription).filter(Subscription.tenant_id == tenant_id).first()
    if not sub:
        sub = Subscription(
            tenant_id=tenant_id,
            tier=TIER_STARTER,
            status="active",
            mcp_server_limit=1,
            allow_high_risk=False,
        )
        db.add(sub)
        db.commit()
        db.refresh(sub)
    return sub


def _apply_tier(sub: Subscription, tier: str) -> None:
    sub.tier = tier
    limit, high_risk = _tier_limits(tier)
    sub.mcp_server_limit = limit
    sub.allow_high_risk  = high_risk


def _record_license(tenant_id: str, token: str, tier: str, mode: str,
                    expires_at: datetime, db: Session) -> None:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    lic = License(
        tenant_id  = tenant_id,
        token_hash = token_hash,
        tier       = tier,
        mode       = mode,
        expires_at = expires_at,
    )
    db.add(lic)
    db.commit()


def _update_heartbeat(token: str, db: Session) -> None:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    lic = db.query(License).filter(License.token_hash == token_hash).first()
    if lic:
        lic.last_heartbeat = datetime.utcnow()
        db.commit()


# ---------------------------------------------------------------------------
# ── STRIPE CHECKOUT ─────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

class CheckoutRequest(BaseModel):
    tenant_id: str
    tier: str = TIER_PRO


@router.post("/billing/checkout")
def create_checkout(req: CheckoutRequest, db: Session = Depends(get_db)):
    """
    Create a Stripe Checkout Session for the requested tier.
    Returns a checkout_url the frontend redirects to.
    """
    if not settings.stripe_secret_key:
        raise HTTPException(503, "Stripe is not configured on this server.")

    sub = _get_or_create_subscription(req.tenant_id, db)

    price_id = _tier_to_price(req.tier)
    if not price_id:
        raise HTTPException(400, f"No Stripe price configured for tier '{req.tier}'.")

    tier_meta = TIER_LIMITS.get(req.tier, {})

    # Reuse existing Stripe customer if available
    customer_id = sub.stripe_customer_id or None

    try:
        session = stripe.checkout.Session.create(
            customer       = customer_id,
            mode           = "subscription",
            line_items     = [{"price": price_id, "quantity": 1}],
            metadata       = {"tenant_id": req.tenant_id, "tier": req.tier},
            success_url    = f"{settings.frontend_url}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url     = f"{settings.frontend_url}/billing/cancel",
            allow_promotion_codes = True,
        )
    except stripe.StripeError as exc:
        logger.error("Stripe checkout error: %s", exc)
        raise HTTPException(502, f"Stripe error: {exc.user_message or str(exc)}")

    return {
        "status":       "success",
        "checkout_url": session.url,
        "session_id":   session.id,
        "tier":         req.tier,
        "tier_label":   tier_meta.get("label", req.tier),
    }


# ---------------------------------------------------------------------------
# ── STRIPE CUSTOMER PORTAL ──────────────────────────────────────────────────
# ---------------------------------------------------------------------------

class PortalRequest(BaseModel):
    tenant_id: str


@router.get("/billing/portal")
def customer_portal(tenant_id: str, db: Session = Depends(get_db)):
    """
    Create a Stripe Billing Portal session so the customer can manage their
    subscription, update payment method, or cancel.
    """
    if not settings.stripe_secret_key:
        raise HTTPException(503, "Stripe is not configured on this server.")

    sub = _get_or_create_subscription(tenant_id, db)
    if not sub.stripe_customer_id:
        raise HTTPException(400, "No Stripe customer found for this tenant. Complete checkout first.")

    try:
        portal = stripe.billing_portal.Session.create(
            customer   = sub.stripe_customer_id,
            return_url = f"{settings.frontend_url}/dashboard",
        )
    except stripe.StripeError as exc:
        logger.error("Stripe portal error: %s", exc)
        raise HTTPException(502, f"Stripe error: {exc.user_message or str(exc)}")

    return {"status": "success", "portal_url": portal.url}


# ---------------------------------------------------------------------------
# ── STRIPE WEBHOOK ───────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

@router.post("/billing/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db),
                         stripe_signature: Optional[str] = Header(None)):
    """
    Receives Stripe events and keeps the subscriptions table in sync.
    Configure this URL in your Stripe Dashboard → Webhooks.
    """
    body = await request.body()

    if settings.stripe_webhook_secret and stripe_signature:
        try:
            event = stripe.Webhook.construct_event(
                body, stripe_signature, settings.stripe_webhook_secret
            )
        except stripe.SignatureVerificationError:
            raise HTTPException(400, "Invalid Stripe signature.")
    else:
        # Dev mode — accept unsigned events
        try:
            event = json.loads(body)
        except Exception:
            raise HTTPException(400, "Invalid payload.")

    event_type = event.get("type", "")
    data_obj   = event.get("data", {}).get("object", {})

    if event_type == "checkout.session.completed":
        _handle_checkout_completed(data_obj, db)

    elif event_type in ("customer.subscription.updated", "customer.subscription.created"):
        _handle_subscription_updated(data_obj, db)

    elif event_type in ("customer.subscription.deleted", "customer.subscription.paused"):
        _handle_subscription_cancelled(data_obj, db)

    elif event_type == "invoice.payment_failed":
        _handle_payment_failed(data_obj, db)

    return {"status": "ok", "event": event_type}


def _handle_checkout_completed(obj: dict, db: Session) -> None:
    tenant_id   = obj.get("metadata", {}).get("tenant_id")
    tier        = obj.get("metadata", {}).get("tier", TIER_PRO)
    customer_id = obj.get("customer")
    sub_id      = obj.get("subscription")
    if not tenant_id:
        return
    sub = _get_or_create_subscription(tenant_id, db)
    sub.stripe_customer_id     = customer_id
    sub.stripe_subscription_id = sub_id
    sub.status = "active"
    _apply_tier(sub, tier)
    db.commit()
    logger.info("Checkout completed: tenant=%s tier=%s", tenant_id, tier)


def _handle_subscription_updated(obj: dict, db: Session) -> None:
    sub_id    = obj.get("id")
    status    = obj.get("status", "active")
    period_end = obj.get("current_period_end")
    items     = obj.get("items", {}).get("data", [])
    price_id  = items[0]["price"]["id"] if items else None

    sub = db.query(Subscription).filter(
        Subscription.stripe_subscription_id == sub_id
    ).first()
    if not sub:
        return

    sub.status = status
    if period_end:
        sub.current_period_end = datetime.fromtimestamp(period_end, tz=timezone.utc)
    if price_id:
        tier = _price_to_tier().get(price_id, sub.tier)
        _apply_tier(sub, tier)
    db.commit()
    logger.info("Subscription updated: sub_id=%s status=%s", sub_id, status)


def _handle_subscription_cancelled(obj: dict, db: Session) -> None:
    sub_id = obj.get("id")
    sub = db.query(Subscription).filter(
        Subscription.stripe_subscription_id == sub_id
    ).first()
    if sub:
        sub.status = "cancelled"
        db.commit()
        logger.info("Subscription cancelled: sub_id=%s", sub_id)


def _handle_payment_failed(obj: dict, db: Session) -> None:
    sub_id = obj.get("subscription")
    sub = db.query(Subscription).filter(
        Subscription.stripe_subscription_id == sub_id
    ).first()
    if sub:
        sub.status = "past_due"
        db.commit()
        logger.warning("Payment failed: sub_id=%s tenant=%s", sub_id, sub.tenant_id)


# ---------------------------------------------------------------------------
# ── SUBSCRIPTION STATUS ──────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

@router.get("/billing/status")
def billing_status(tenant_id: str, db: Session = Depends(get_db)):
    """
    Returns the tenant's current subscription state including graceful
    degradation messaging when the subscription has lapsed.
    """
    sub = _get_or_create_subscription(tenant_id, db)
    payload = sub.to_dict()

    if not sub.is_active:
        payload["degradation"] = LicenseManager.sleep_mode_message()
        payload["degradation"]["action_url"] = f"/billing/portal?tenant_id={tenant_id}"
    else:
        payload["degradation"] = None

    return {"status": "success", "subscription": payload}


# ---------------------------------------------------------------------------
# ── TIER GATE (paywall check) ─────────────────────────────────────────────────
# ---------------------------------------------------------------------------

class TierGateRequest(BaseModel):
    tenant_id: str
    requested_mcp_count: int
    high_risk_requested: bool = False


@router.post("/billing/tier-gate")
def tier_gate(req: TierGateRequest, db: Session = Depends(get_db)):
    """
    Call before adding MCP servers in the Assemble phase.
    Returns { allowed: true } or { allowed: false, upgrade_card: {...} }.
    """
    sub = _get_or_create_subscription(req.tenant_id, db)

    if not sub.is_active:
        return {
            "allowed":    False,
            "reason":     "sleep_mode",
            "sleep_mode": LicenseManager.sleep_mode_message(),
        }

    # MCP server count check
    if req.requested_mcp_count > sub.mcp_server_limit:
        required = TIER_PRO if sub.tier == TIER_STARTER else TIER_ENTERPRISE
        card = LicenseManager.upgrade_card(
            sub.tier, required,
            f"You're adding {req.requested_mcp_count} connectors, "
            f"but {TIER_LIMITS[sub.tier]['label']} allows {sub.mcp_server_limit}.",
        )
        return {"allowed": False, "reason": "mcp_limit", "upgrade_card": card}

    # High-risk tool check
    if req.high_risk_requested and not sub.allow_high_risk:
        card = LicenseManager.upgrade_card(
            sub.tier, TIER_PRO,
            "High-Risk tool execution (code runner, Python) requires the Pro plan.",
        )
        return {"allowed": False, "reason": "high_risk", "upgrade_card": card}

    return {
        "allowed":           True,
        "tier":              sub.tier,
        "mcp_server_limit":  sub.mcp_server_limit,
        "allow_high_risk":   sub.allow_high_risk,
    }


# ---------------------------------------------------------------------------
# ── LICENSE HANDSHAKE ────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

class HandshakeRequest(BaseModel):
    tenant_id: str
    bridge_version: str = "1.0.0"


@router.post("/license/handshake")
def license_handshake(req: HandshakeRequest, db: Session = Depends(get_db)):
    """
    Called by the Sovereign Bridge on every startup.
    Issues a 24-hour signed token encoding the tenant's tier and permissions.
    """
    sub = _get_or_create_subscription(req.tenant_id, db)
    lm  = get_license_manager()
    lt  = lm.handshake(req.tenant_id, sub.tier, sub.is_active)

    _record_license(req.tenant_id, lt.token, lt.tier, lt.mode, lt.expires_at, db)

    response = {
        "status":      "success" if lt.mode == "active" else "sleep_mode",
        "license":     lt.to_dict(),
    }

    if lt.mode == "sleep":
        response["degradation"] = LicenseManager.sleep_mode_message()
        response["degradation"]["action_url"] = f"/billing/portal?tenant_id={req.tenant_id}"

    return response


# ---------------------------------------------------------------------------
# ── LICENSE HEARTBEAT ────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

class HeartbeatRequest(BaseModel):
    tenant_id: str
    token: str


@router.post("/license/heartbeat")
def license_heartbeat(req: HeartbeatRequest, db: Session = Depends(get_db)):
    """
    Bridge calls this every 23 hours (or when token has ≤ 1 hour remaining).
    Re-issues a fresh 24-hour token.
    """
    lm  = get_license_manager()
    sub = _get_or_create_subscription(req.tenant_id, db)

    try:
        lt = lm.heartbeat(req.token, sub.is_active)
    except LicenseError as exc:
        raise HTTPException(401, str(exc))

    _update_heartbeat(req.token, db)
    _record_license(req.tenant_id, lt.token, lt.tier, lt.mode, lt.expires_at, db)

    response = {
        "status":  "refreshed" if lt.mode == "active" else "sleep_mode",
        "license": lt.to_dict(),
    }

    if lt.mode == "sleep":
        response["degradation"] = LicenseManager.sleep_mode_message()

    return response


# ---------------------------------------------------------------------------
# ── LICENSE VERIFY ───────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

class VerifyRequest(BaseModel):
    token: str


@router.post("/license/verify")
def license_verify(req: VerifyRequest, db: Session = Depends(get_db)):
    """
    Lightweight token validation.  Used by the engine before executing
    high-risk tools or registering new MCP servers.
    """
    lm = get_license_manager()
    try:
        lt = lm.verify(req.token)
    except LicenseError as exc:
        raise HTTPException(401, str(exc))

    # Check DB for revocation
    token_hash = hashlib.sha256(req.token.encode()).hexdigest()
    lic = db.query(License).filter(License.token_hash == token_hash).first()
    if lic and lic.revoked:
        raise HTTPException(401, f"Token has been revoked: {lic.revoke_reason or 'no reason given'}")

    response = {"status": "valid", "license": lt.to_dict()}

    if lt.mode == "sleep":
        response["degradation"] = LicenseManager.sleep_mode_message()

    return response
