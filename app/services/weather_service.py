"""
Main weather service orchestrating all components for the weather API.

This service coordinates between the weather client, cache service, storage providers,
and database providers to handle the complete flow of weather data requests.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from app.config.settings import Settings
from app.models.events import EventData, EventStatus, EventType
from app.models.weather import WeatherData
from app.providers.database.factory import get_database_provider
from app.providers.storage.factory import create_storage_provider
from app.services.cache_service import CacheService
from app.services.weather_client import WeatherClient
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

logger = logging.getLogger(__name__)


class WeatherService:
    """
    Main weather service orchestrating all components.

    This service handles the complete flow:
    1. Check cache for recent data
    2. Fetch from external API if cache miss/expired
    3. Store data in storage provider
    4. Log event to database
    5. Return weather data to client
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._weather_client: WeatherClient | None = None
        self._cache_service: CacheService | None = None
        self._storage_provider = create_storage_provider(settings)
        self._database_provider = get_database_provider()
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize all service components"""
        if self._initialized:
            return

        try:
            # Initialize weather client
            self._weather_client = WeatherClient(self.settings)

            # Initialize cache service
            self._cache_service = CacheService(self._storage_provider)

            logger.info("Weather service initialized successfully")
            self._initialized = True

        except Exception as e:
            logger.error(f"Failed to initialize weather service: {e}")
            raise WeatherServiceError(f"Service initialization failed: {str(e)}") from e

    async def cleanup(self) -> None:
        """Cleanup resources"""
        if self._weather_client:
            # Weather client cleanup is handled by context manager
            pass
        self._initialized = False
        logger.info("Weather service cleanup completed")

    async def get_weather(self, city: str) -> tuple[WeatherData, dict[str, Any]]:
        """
        Get weather data for a city with complete orchestration.

        Returns:
            Tuple of (weather_data, metadata) where metadata contains:
            - cache_hit: bool
            - cache_age_seconds: int (if cache hit)
            - storage_path: str
            - event_id: str
        """
        if not self._initialized:
            raise WeatherServiceError("Weather service not initialized")

        if not city or not city.strip():
            raise InvalidCityError(city, "City name cannot be empty")

        city = city.strip()
        start_time = datetime.now()
        event_data = EventData(
            event_type=EventType.WEATHER_REQUEST,
            city=city,
            timestamp=start_time,
            status=EventStatus.PENDING,
            metadata={"request_start": start_time.isoformat()},
        )

        logger.info(f"Processing weather request for city: {city}")

        try:
            # Step 1: Check cache
            cached_result = await self._check_cache(city)
            if cached_result:
                weather_data, cache_age_seconds = cached_result

                # Log successful cache hit
                event_data.status = EventStatus.SUCCESS
                event_data.metadata.update(
                    {
                        "cache_hit": True,
                        "cached": True,
                        "external_api_called": False,
                        "cache_age_seconds": cache_age_seconds,
                        "processing_time_ms": (
                            datetime.now() - start_time
                        ).total_seconds()
                        * 1000,
                    }
                )

                event_id = await self._log_event(event_data)

                logger.info(f"Cache hit for {city}, age: {cache_age_seconds}s")

                return weather_data, {
                    "cache_hit": True,
                    "cache_age_seconds": cache_age_seconds,
                    "storage_path": None,
                    "event_id": event_id,
                }

            # Step 2: Fetch from external API
            weather_data = await self._fetch_from_api(city)

            # Step 3: Store in cache/storage
            storage_path = await self._store_weather_data(city, weather_data)

            # Step 4: Log successful event
            event_data.status = EventStatus.SUCCESS
            event_data.storage_path = storage_path
            event_data.metadata.update(
                {
                    "cache_hit": False,
                    "cached": False,
                    "external_api_called": True,
                    "storage_path": storage_path,
                    "processing_time_ms": (datetime.now() - start_time).total_seconds()
                    * 1000,
                }
            )

            event_id = await self._log_event(event_data)

            logger.info(f"Successfully processed weather request for {city}")

            return weather_data, {
                "cache_hit": False,
                "cache_age_seconds": 0,
                "storage_path": storage_path,
                "event_id": event_id,
            }

        except Exception as e:
            # Log failed event
            event_data.status = EventStatus.FAILED
            event_data.error_message = str(e)
            event_data.metadata.update(
                {
                    "error_type": type(e).__name__,
                    "processing_time_ms": (datetime.now() - start_time).total_seconds()
                    * 1000,
                }
            )

            try:
                await self._log_event(event_data)
            except Exception as log_error:
                logger.error(f"Failed to log error event: {log_error}")

            logger.error(f"Failed to process weather request for {city}: {e}")
            raise

    async def _check_cache(self, city: str) -> tuple[WeatherData, int] | None:
        """Check cache for recent weather data"""
        try:
            return await self._cache_service.get_cached_weather(city)
        except CacheError as e:
            logger.warning(f"Cache check failed for {city}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error checking cache for {city}: {e}")
            return None

    async def _fetch_from_api(self, city: str) -> WeatherData:
        """Fetch weather data from external API"""
        if not self._weather_client:
            raise WeatherServiceError("Weather client not initialized")

        try:
            async with self._weather_client as client:
                return await client.fetch_weather_data(city)
        except (ExternalAPIError, InvalidCityError, APITimeoutError, APIRateLimitError):
            raise
        except Exception as e:
            logger.error(f"Unexpected error fetching weather data for {city}: {e}")
            raise WeatherServiceError(f"Failed to fetch weather data: {str(e)}") from e

    async def _store_weather_data(self, city: str, weather_data: WeatherData) -> str:
        """Store weather data in storage provider"""
        try:
            return await self._cache_service.store_weather_data(city, weather_data)
        except (CacheError, StorageError):
            raise
        except Exception as e:
            logger.error(f"Unexpected error storing weather data for {city}: {e}")
            raise StorageError(f"Failed to store weather data: {str(e)}") from e

    async def _log_event(self, event_data: EventData) -> str:
        """Log event to database"""
        try:
            return await self._database_provider.log_event(event_data)
        except DatabaseError:
            raise
        except Exception as e:
            logger.error(f"Unexpected error logging event: {e}")
            raise DatabaseError(f"Failed to log event: {str(e)}") from e

    async def health_check(self) -> dict[str, Any]:
        """Perform comprehensive health check of all components"""
        health_status = {
            "service": "healthy",
            "components": {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        try:
            # Check weather client
            if self._weather_client:
                async with self._weather_client as client:
                    weather_client_healthy = await client.health_check()
            else:
                weather_client_healthy = False

            health_status["components"]["weather_client"] = {
                "status": "healthy" if weather_client_healthy else "unhealthy"
            }

            # Check cache service
            cache_healthy = (
                await self._cache_service.is_cache_healthy()
                if self._cache_service
                else False
            )
            health_status["components"]["cache_service"] = {
                "status": "healthy" if cache_healthy else "unhealthy"
            }

            # Check storage provider
            storage_healthy = await self._storage_provider.health_check()
            health_status["components"]["storage_provider"] = {
                "status": "healthy" if storage_healthy else "unhealthy"
            }

            # Check database provider
            database_healthy = await self._database_provider.health_check()
            health_status["components"]["database_provider"] = {
                "status": "healthy" if database_healthy else "unhealthy"
            }

            # Overall health
            all_healthy = all(
                component["status"] == "healthy"
                for component in health_status["components"].values()
            )

            health_status["service"] = "healthy" if all_healthy else "degraded"

        except Exception as e:
            logger.error(f"Health check failed: {e}")
            health_status["service"] = "unhealthy"
            health_status["error"] = str(e)

        return health_status

    async def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics and configuration"""
        if not self._cache_service:
            return {"error": "Cache service not initialized"}

        try:
            return {
                "ttl_minutes": self._cache_service.get_ttl_minutes(),
                "storage_provider": type(self._storage_provider).__name__,
                "service_initialized": self._initialized,
            }
        except Exception as e:
            logger.error(f"Failed to get cache stats: {e}")
            return {"error": str(e)}

    async def invalidate_expired_cache(self) -> dict[str, Any]:
        """Manually trigger expired cache cleanup"""
        if not self._cache_service:
            return {"error": "Cache service not initialized"}

        try:
            deleted_count = await self._cache_service.invalidate_expired_cache()
            return {
                "deleted_entries": deleted_count,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            logger.error(f"Failed to invalidate expired cache: {e}")
            return {"error": str(e)}


async def create_weather_service(settings: Settings) -> WeatherService:
    """
    Factory function to create and initialize a weather service.

    Usage:
        service = await create_weather_service(settings)
        try:
            weather_data, metadata = await service.get_weather("London")
        finally:
            await service.cleanup()
    """
    service = WeatherService(settings)
    await service.initialize()
    return service
