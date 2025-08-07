import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config.settings import settings
from app.models.weather import WeatherData
from app.providers.storage.base import StorageProvider
from app.utils.exceptions import CacheError


class CacheService:
    """
    Caching service with 5-minute expiration logic.

    This service provides a high-level interface for caching weather data
    with automatic expiration handling and cache key management.
    """

    def __init__(self, storage_provider: StorageProvider):
        self.storage_provider = storage_provider
        self.ttl_minutes = settings.cache_ttl_minutes

    def _generate_cache_key(self, city: str) -> str:
        """Generate a consistent cache key for a city"""
        normalized_city = city.lower().strip()
        return hashlib.md5(normalized_city.encode("utf-8")).hexdigest()[:12]

    def _is_data_expired(self, timestamp: datetime) -> bool:
        """Check if cached data is expired based on TTL"""
        if not timestamp.tzinfo:
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        expiry_time = timestamp + timedelta(minutes=self.ttl_minutes)
        current_time = datetime.now(timezone.utc)

        return current_time > expiry_time

    def _calculate_cache_age_seconds(self, timestamp: datetime) -> int:
        """Calculate age of cached data in seconds"""
        if not timestamp.tzinfo:
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        current_time = datetime.now(timezone.utc)
        age = current_time - timestamp
        return int(age.total_seconds())

    async def get_cached_weather(self, city: str) -> tuple[WeatherData, int] | None:
        """Retrieve cached weather data if it exists and is not expired"""

        try:
            cached_data = await self.storage_provider.get_weather_data(
                city=city, max_age_minutes=self.ttl_minutes
            )

            if not cached_data:
                return None

            if isinstance(cached_data, dict):
                timestamp_str = cached_data.get("timestamp")
                if not timestamp_str:
                    return None

                timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))

                if self._is_data_expired(timestamp):
                    return None

                weather_data = WeatherData(**cached_data)
                cache_age_seconds = self._calculate_cache_age_seconds(timestamp)

                return weather_data, cache_age_seconds

            return None

        except Exception as e:
            raise CacheError(
                f"Failed to retrieve cached weather data for {city}: {str(e)}"
            ) from e

    async def store_weather_data(self, city: str, weather_data: WeatherData) -> str:
        """Store weather data in cache with proper formatting"""

        try:
            data_dict = weather_data.model_dump()

            if isinstance(data_dict.get("timestamp"), datetime):
                data_dict["timestamp"] = data_dict["timestamp"].isoformat()

            storage_path = await self.storage_provider.store_weather_data(
                city=city, data=data_dict, timestamp=weather_data.timestamp
            )

            return storage_path

        except Exception as e:
            raise CacheError(
                f"Failed to store weather data for {city}: {str(e)}"
            ) from e

    async def invalidate_expired_cache(self) -> int:
        """Remove expired cache entries"""

        try:
            return await self.storage_provider.delete_expired_data(
                max_age_minutes=self.ttl_minutes
            )
        except Exception as e:
            raise CacheError(f"Failed to invalidate expired cache: {str(e)}") from e

    async def is_cache_healthy(self) -> bool:
        """Check if the cache storage is healthy"""

        try:
            return await self.storage_provider.health_check()
        except Exception:
            return False

    def get_ttl_minutes(self) -> int:
        """Get the configured TTL in minutes."""
        return self.ttl_minutes

    def get_cache_info(self, city: str) -> dict[str, Any]:
        """Get cache configuration information for debugging"""

        return {
            "city": city,
            "cache_key": self._generate_cache_key(city),
            "ttl_minutes": self.ttl_minutes,
            "storage_provider": type(self.storage_provider).__name__,
        }
