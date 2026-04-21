from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AI Operations Intelligence Platform"
    app_env: str = "development"

    database_url: str
    redis_url: str
    qdrant_url: str

    # License signing
    license_secret_key: str = "dev-license-secret-change-in-prod"

    # Stripe billing
    stripe_secret_key:       str = ""
    stripe_webhook_secret:   str = ""
    stripe_price_starter:    str = ""   # Stripe Price ID for Starter plan
    stripe_price_pro:        str = ""   # Stripe Price ID for Pro plan
    stripe_price_enterprise: str = ""   # Stripe Price ID for Enterprise plan
    frontend_url:            str = "http://localhost:5173"

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
