from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv(override=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    app_name: str = "StudyBuddy"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    cors_origins: list[str] = ["*"]

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres"
    sync_database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/postgres"
    checkpoint_database_url: str = "postgresql://postgres:postgres@localhost:5432/postgres"
    redis_url: str = "redis://localhost:6379/0"
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"

    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    google_api_key: str = "Azia............"
    chat_model_name: str = "gemini-3.1-flash-lite"
    summarizer_model_name: str = "gemini-3.1-flash-lite"
    query_model_name: str = "gemini-3.1-flash-lite"

    # Local Supabase Kong (docker compose); use service_role key for storage
    supabase_url: str = "http://localhost:54321"
    supabase_key: str = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImV4cCI6MTk4MzgxMjk5Nn0.EGIM96RAZx35lJzdJsyH-qQwv8Hdp7fsn3W0YpN81IU"

    elasticsearch_url: str = "http://localhost:9200"

    # Self-hosted Unstructured API (docker compose service `unstructured`)
    unstructured_api_url: str = "http://localhost:8001"
    unstructured_api_key: str = ""

    # Document ingest: delayed retries via TTL queues (not broker requeue)
    rabbitmq_max_retries: int = 3
    rabbitmq_retry_base_ms: int = 5_000
    rabbitmq_retry_max_ms: int = 300_000
