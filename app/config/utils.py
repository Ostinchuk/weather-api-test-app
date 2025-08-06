import os

from .settings import settings


def validate_configuration() -> dict[str, list[str] | bool]:
    """Validate configuration and return validation results."""
    errors = []
    warnings = []

    if not settings.weather_api_key:
        errors.append("WEATHER_API_KEY must be set to a valid OpenWeatherMap API key")

    if settings.use_aws_services:
        if not settings.aws_region:
            errors.append("AWS_REGION must be set when using AWS services")

        if not any(
            [
                settings.aws_access_key_id,
                os.getenv("AWS_PROFILE"),
                os.getenv("AWS_ROLE_ARN"),
                # AWS credentials could be provided via IAM role; don't make this a hard error
            ]
        ):
            warnings.append(
                "No AWS credentials found. Ensure AWS credentials are available via "
                "environment variables, AWS profile, or IAM role"
            )

    if settings.cache_ttl_minutes <= 0:
        errors.append("CACHE_TTL_MINUTES must be a positive integer")

    if settings.weather_api_timeout <= 0:
        errors.append("WEATHER_API_TIMEOUT must be a positive integer")

    if settings.health_check_timeout <= 0:
        errors.append("HEALTH_CHECK_TIMEOUT must be a positive integer")

    if not (1 <= settings.port <= 65535):
        errors.append("PORT must be between 1 and 65535")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }


def get_config_summary() -> dict[str, str | int | bool]:
    """Get a summary of current configuration for logging/debugging."""
    return {
        "app_name": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "provider_mode": settings.provider_mode,
        "cache_ttl_minutes": settings.cache_ttl_minutes,
        "debug": settings.debug,
        "log_level": settings.log_level,
        "api_endpoint": f"{settings.host}:{settings.port}",
        "weather_api_configured": bool(
            settings.weather_api_key and len(settings.weather_api_key.strip()) >= 10
        ),
    }
