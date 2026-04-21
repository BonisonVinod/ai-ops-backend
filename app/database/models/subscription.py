from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.orm import relationship

from app.database.base import Base


class Subscription(Base):
    """
    One row per tenant.  Tracks Stripe billing state and resolved tier.
    Tier is denormalised here so API calls never need to hit Stripe.
    """

    __tablename__ = "subscriptions"

    id                      = Column(Integer, primary_key=True, index=True)
    tenant_id               = Column(String, unique=True, nullable=False, index=True)

    # Tier: starter | pro | enterprise
    tier                    = Column(String, nullable=False, default="starter")

    # Stripe IDs
    stripe_customer_id      = Column(String, nullable=True)
    stripe_subscription_id  = Column(String, nullable=True)
    stripe_price_id         = Column(String, nullable=True)

    # Billing cycle
    status                  = Column(String, nullable=False, default="active")
    # status values: active | trialing | past_due | cancelled | expired
    current_period_end      = Column(DateTime, nullable=True)

    # Denormalised limits (updated when tier changes)
    mcp_server_limit        = Column(Integer, nullable=False, default=1)
    allow_high_risk         = Column(Boolean, nullable=False, default=False)

    created_at              = Column(DateTime, default=datetime.utcnow)
    updated_at              = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    licenses                = relationship("License", back_populates="subscription",
                                           foreign_keys="License.tenant_id",
                                           primaryjoin="Subscription.tenant_id == License.tenant_id")

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        if self.status not in ("active", "trialing"):
            return False
        if self.current_period_end and datetime.utcnow() > self.current_period_end:
            return False
        return True

    def to_dict(self) -> dict:
        from app.engine.auth.license_manager import TIER_LIMITS
        tier_meta = TIER_LIMITS.get(self.tier, {})
        return {
            "tenant_id":            self.tenant_id,
            "tier":                 self.tier,
            "tier_label":           tier_meta.get("label", self.tier),
            "tier_description":     tier_meta.get("description", ""),
            "status":               self.status,
            "is_active":            self.is_active,
            "mcp_server_limit":     self.mcp_server_limit,
            "allow_high_risk":      self.allow_high_risk,
            "current_period_end":   self.current_period_end.isoformat() if self.current_period_end else None,
            "stripe_customer_id":   self.stripe_customer_id,
        }
