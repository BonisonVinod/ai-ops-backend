from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "AI Operations Intelligence Platform"
    app_env: str = "development"

    database_url: str
    redis_url: str
    qdrant_url: str

    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()
