from datetime import datetime, timezone
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.services.weather_service import WeatherService
from app.utils.exceptions import (
    APIRateLimitError,
    APITimeoutError,
    CacheError,
    DatabaseError,
    ExternalAPIError,
    InvalidCityError,
    StorageError,
    WeatherServiceError,
)

logger = structlog.get_logger(__name__)
router = APIRouter()


def get_weather_service(request: Request) -> WeatherService:
    """
    Dependency injection for weather service.

    Retrieves the weather service instance from the application state.
    This service is initialized during application startup.
    """
    if not hasattr(request.app.state, "weather_service"):
        raise HTTPException(status_code=503, detail="Weather service not available")

    return request.app.state.weather_service


@router.get(
    "/weather",
    response_model=dict[str, Any],
    summary="Get current weather data",
    description="""
    Retrieve current weather information for a specified city.

    The service implements intelligent caching:
    - Returns cached data if available and less than 5 minutes old
    - Fetches fresh data from external API if cache is expired or missing
    - Stores all weather data for future retrieval and analysis

    **Query Parameters:**
    - `city`: Name of the city (required, 1-100 characters)

    **Response includes:**
    - Complete weather data (temperature, humidity, description, etc.)
    - Cache metadata (hit/miss, age)
    - Storage information
    - Event tracking ID
    """,
    responses={
        200: {
            "description": "Weather data retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "weather_data": {
                            "city": "London",
                            "country": "GB",
                            "temperature": 18.5,
                            "feels_like": 17.8,
                            "description": "Partly cloudy",
                            "humidity": 65,
                            "pressure": 1013.2,
                            "visibility": 10.0,
                            "wind_speed": 5.2,
                            "wind_direction": 230,
                            "timestamp": "2023-11-20T15:30:00Z",
                            "sunrise": "2023-11-20T07:45:00Z",
                            "sunset": "2023-11-20T16:30:00Z",
                        },
                        "metadata": {
                            "cache_hit": True,
                            "cache_age_seconds": 120,
                            "storage_path": "weather-data/london_20231120_153000.json",
                            "event_id": "evt_abc123",
                        },
                    }
                }
            },
        },
        400: {"description": "Invalid city name or missing parameter"},
        404: {"description": "City not found"},
        429: {"description": "API rate limit exceeded"},
        503: {"description": "External weather service unavailable"},
        500: {"description": "Internal server error"},
    },
    tags=["Weather"],
)
async def get_weather(
    city: Annotated[
        str,
        Query(
            description="City name to get weather data for",
            min_length=1,
            max_length=100,
            example="London",
        ),
    ],
    weather_service: WeatherService = Depends(get_weather_service),
) -> dict[str, Any]:
    """
    Get current weather data for a specified city.

    This endpoint orchestrates the complete weather data flow:
    1. Validates the city parameter
    2. Checks for cached data (5-minute TTL)
    3. Fetches from external API if needed
    4. Stores data for future use
    5. Logs the event for analytics
    6. Returns weather data with metadata
    """
    logger.info("Weather request received", city=city)

    try:
        weather_data, metadata = await weather_service.get_weather(city)

        response_data = {
            "weather_data": weather_data.model_dump(),
            "metadata": metadata,
        }

        logger.info(
            "Weather request completed successfully",
            city=city,
            cache_hit=metadata["cache_hit"],
            event_id=metadata["event_id"],
        )

        return response_data

    except InvalidCityError as e:
        logger.warning("Invalid city requested", city=city, error=str(e))
        raise HTTPException(status_code=400, detail=f"Invalid city: {str(e)}") from e

    except APIRateLimitError as e:
        logger.warning("API rate limit exceeded", city=city, error=str(e))
        raise HTTPException(
            status_code=429,
            detail="Weather API rate limit exceeded. Please try again later.",
        ) from e

    except APITimeoutError as e:
        logger.warning("API timeout", city=city, error=str(e))
        raise HTTPException(
            status_code=503, detail="Weather service timeout. Please try again later."
        ) from e

    except ExternalAPIError as e:
        logger.error("External API error", city=city, error=str(e))
        if "not found" in str(e).lower():
            raise HTTPException(
                status_code=404, detail=f"City '{city}' not found"
            ) from e
        raise HTTPException(
            status_code=503, detail="Weather service temporarily unavailable"
        ) from e

    except (CacheError, StorageError, DatabaseError) as e:
        logger.error(
            "Storage/database error",
            city=city,
            error=str(e),
            error_type=type(e).__name__,
        )
        raise HTTPException(
            status_code=500, detail="Internal service error occurred"
        ) from e

    except WeatherServiceError as e:
        logger.error("Weather service error", city=city, error=str(e))
        raise HTTPException(
            status_code=500, detail="Weather service error occurred"
        ) from e

    except Exception as e:
        logger.error(
            "Unexpected error in weather endpoint",
            city=city,
            error=str(e),
            error_type=type(e).__name__,
        )
        raise HTTPException(
            status_code=500, detail="An unexpected error occurred"
        ) from e


@router.get(
    "/health",
    response_model=dict[str, Any],
    summary="Service health check",
    description="""
    Comprehensive health check endpoint that verifies the status of all service components:
    - Weather service initialization
    - External weather API connectivity
    - Cache service functionality
    - Storage provider availability
    - Database provider connectivity

    Returns detailed status information for monitoring and debugging purposes.
    """,
    responses={
        200: {
            "description": "Health check completed",
            "content": {
                "application/json": {
                    "example": {
                        "service": "healthy",
                        "components": {
                            "weather_client": {"status": "healthy"},
                            "cache_service": {"status": "healthy"},
                            "storage_provider": {"status": "healthy"},
                            "database_provider": {"status": "healthy"},
                        },
                        "timestamp": "2023-11-20T15:30:00Z",
                    }
                }
            },
        }
    },
    tags=["Health"],
)
async def health_check(
    weather_service: WeatherService = Depends(get_weather_service),
) -> dict[str, Any]:
    """
    Perform comprehensive health check of all service components.

    This endpoint tests:
    - Service initialization status
    - External API connectivity using health check city
    - Cache service operations
    - Storage provider availability
    - Database provider connectivity

    Returns detailed component status for monitoring systems.
    """
    logger.info("Health check requested")

    try:
        health_status = await weather_service.health_check()

        if health_status["service"] == "healthy":
            status_code = 200
        elif health_status["service"] == "degraded":
            status_code = 200  # Still return 200 for degraded but functional service
        else:
            status_code = 503  # Service unavailable

        logger.info(
            "Health check completed",
            status=health_status["service"],
            status_code=status_code,
        )

        return JSONResponse(status_code=status_code, content=health_status)

    except Exception as e:
        logger.error("Health check failed", error=str(e), error_type=type(e).__name__)

        error_response = {
            "service": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        return JSONResponse(status_code=503, content=error_response)


@router.get(
    "/health/ready",
    response_model=dict[str, Any],
    summary="Readiness probe",
    description="""
    Simple readiness probe for container orchestration systems.

    This endpoint provides a quick check to determine if the service
    is ready to accept traffic. Unlike the full health check, this
    endpoint focuses on basic service availability.
    """,
    tags=["Health"],
)
async def readiness_check(
    weather_service: WeatherService = Depends(get_weather_service),
) -> dict[str, Any]:
    """
    Simple readiness check for container orchestration.

    Returns basic service status without detailed component checking.
    Designed for Kubernetes readiness probes and similar systems.
    """
    try:
        if not weather_service._initialized:
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", "message": "Service not initialized"},
            )

        return {"status": "ready"}

    except Exception as e:
        logger.error("Readiness check failed", error=str(e))
        return JSONResponse(
            status_code=503, content={"status": "not_ready", "error": str(e)}
        )


@router.get(
    "/cache/stats",
    response_model=dict[str, Any],
    summary="Cache statistics",
    description="""
    Retrieve current cache configuration and statistics.

    Provides information about:
    - Cache TTL configuration
    - Storage provider type
    - Service initialization status
    """,
    tags=["Cache Management"],
)
async def get_cache_stats(
    weather_service: WeatherService = Depends(get_weather_service),
) -> dict[str, Any]:
    """Get cache configuration and statistics."""
    logger.info("Cache stats requested")

    try:
        stats = await weather_service.get_cache_stats()
        logger.info("Cache stats retrieved successfully")
        return stats

    except Exception as e:
        logger.error("Failed to retrieve cache stats", error=str(e))
        raise HTTPException(
            status_code=500, detail="Failed to retrieve cache statistics"
        ) from e


@router.post(
    "/cache/invalidate",
    response_model=dict[str, Any],
    summary="Invalidate expired cache entries",
    description="""
    Manually trigger cleanup of expired cache entries.

    This endpoint allows administrators to force cleanup of expired
    cache entries without waiting for automatic cleanup processes.

    Returns the number of entries that were removed.
    """,
    tags=["Cache Management"],
)
async def invalidate_expired_cache(
    weather_service: WeatherService = Depends(get_weather_service),
) -> dict[str, Any]:
    """Manually trigger expired cache cleanup."""
    logger.info("Cache invalidation requested")

    try:
        result = await weather_service.invalidate_expired_cache()
        logger.info(
            "Cache invalidation completed",
            deleted_entries=result.get("deleted_entries", 0),
        )
        return result

    except Exception as e:
        logger.error("Cache invalidation failed", error=str(e))
        raise HTTPException(
            status_code=500, detail="Failed to invalidate expired cache entries"
        ) from e
