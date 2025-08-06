from typing import Literal

from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Weather API Service"
    app_version: str = "1.0.0"
    debug: bool = False
    environment: Literal["development", "production"] = "development"

    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1

    weather_api_key: str = Field(..., description="OpenWeatherMap API key")
    weather_api_url: HttpUrl = Field(
        default="https://api.openweathermap.org/data/2.5/weather",
        description="Weather API base URL",
    )
    weather_api_timeout: int = Field(
        default=30, description="Weather API request timeout in seconds"
    )

    cache_ttl_minutes: int = Field(default=5, description="Cache TTL in minutes")

    provider_mode: Literal["aws", "local"] = Field(
        default="local",
        description="Provider mode: aws for AWS services, local for local alternatives",
    )

    aws_region: str = "us-east-1"
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_session_token: str | None = None

    s3_bucket_name: str = Field(
        default="weather-api-bucket",
        description="S3 bucket name for storing weather data",
    )
    s3_prefix: str = Field(
        default="weather-data/", description="S3 key prefix for organizing files"
    )

    dynamodb_table_name: str = Field(
        default="weather-events", description="DynamoDB table name for logging events"
    )

    local_storage_path: str = Field(
        default="./data/weather_files",
        description="Local directory path for storing weather files",
    )
    local_db_path: str = Field(
        default="./data/weather_events.db",
        description="Local SQLite database path for event logging",
    )

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["json", "console"] = "console"
    log_file: str | None = None

    health_check_timeout: int = Field(
        default=10, description="Health check timeout in seconds"
    )

    @property
    def is_development(self) -> bool:
        return self.environment == "development"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def use_aws_services(self) -> bool:
        return self.provider_mode == "aws"

    @property
    def use_local_services(self) -> bool:
        return self.provider_mode == "local"


settings = Settings()
