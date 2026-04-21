from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from app.database.base import Base


class License(Base):
    """
    Audit trail for every issued sovereign license token.
    We store only the SHA-256 hash of the raw token — never the token itself.
    """

    __tablename__ = "licenses"

    id              = Column(Integer, primary_key=True, index=True)
    tenant_id       = Column(String, nullable=False, index=True)
    token_hash      = Column(String, nullable=False, unique=True, index=True)

    tier            = Column(String, nullable=False, default="starter")
    mode            = Column(String, nullable=False, default="active")  # active | sleep

    issued_at       = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at      = Column(DateTime, nullable=False)
    last_heartbeat  = Column(DateTime, nullable=True)

    revoked         = Column(Boolean, nullable=False, default=False)
    revoke_reason   = Column(String, nullable=True)

    # Back-ref to subscription (joined on tenant_id — not a FK to avoid migration pain)
    subscription    = None  # resolved in Subscription.licenses relationship

    def to_dict(self) -> dict:
        return {
            "tenant_id":      self.tenant_id,
            "tier":           self.tier,
            "mode":           self.mode,
            "issued_at":      self.issued_at.isoformat() if self.issued_at else None,
            "expires_at":     self.expires_at.isoformat() if self.expires_at else None,
            "last_heartbeat": self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            "revoked":        self.revoked,
        }
