from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from app.models.weather import WeatherData
from app.services.cache_service import CacheService
from app.utils.exceptions import CacheError


class TestCacheService:
    """Test suite for CacheService"""

    @pytest.fixture
    def mock_storage_provider(self):
        """Create a mock storage provider"""
        return AsyncMock()

    @pytest.fixture
    def cache_service(self, mock_storage_provider):
        """Create a CacheService instance with mocked storage provider"""
        service = CacheService(mock_storage_provider)
        service.ttl_minutes = 5  # Set a known TTL for testing
        return service

    @pytest.fixture
    def sample_weather_data(self):
        """Create sample weather data for testing"""
        return WeatherData(
            city="London",
            temperature=20.5,
            description="Clear sky",
            humidity=65,
            pressure=1013.25,
            wind_speed=3.5,
            wind_direction=180,
            visibility=10.0,
            timestamp=datetime.now(timezone.utc),
            source="openweathermap",
        )

    async def test_get_cached_weather_hit(
        self, cache_service, mock_storage_provider, sample_weather_data
    ):
        """Test successful cache hit with valid, non-expired data"""
        cached_data = sample_weather_data.model_dump()
        cached_data["timestamp"] = sample_weather_data.timestamp.isoformat()

        mock_storage_provider.get_weather_data.return_value = cached_data

        result = await cache_service.get_cached_weather("London")

        assert result is not None
        weather_data, cache_age = result
        assert isinstance(weather_data, WeatherData)
        assert weather_data.city == "London"
        assert weather_data.temperature == 20.5
        assert isinstance(cache_age, int)
        assert cache_age >= 0

        mock_storage_provider.get_weather_data.assert_called_once_with(
            city="London", max_age_minutes=5
        )

    async def test_get_cached_weather_miss(self, cache_service, mock_storage_provider):
        """Test cache miss when no data is found"""
        mock_storage_provider.get_weather_data.return_value = None

        result = await cache_service.get_cached_weather("NonExistentCity")

        assert result is None
        mock_storage_provider.get_weather_data.assert_called_once_with(
            city="NonExistentCity", max_age_minutes=5
        )

    async def test_get_cached_weather_expired(
        self, cache_service, mock_storage_provider
    ):
        """Test cache miss when data is expired"""
        expired_timestamp = datetime.now(timezone.utc) - timedelta(minutes=10)
        cached_data = {
            "city": "London",
            "temperature": 20.5,
            "description": "Clear sky",
            "humidity": 65,
            "pressure": 1013.25,
            "wind_speed": 3.5,
            "wind_direction": 180,
            "visibility": 10.0,
            "timestamp": expired_timestamp.isoformat(),
            "source": "openweathermap",
        }

        mock_storage_provider.get_weather_data.return_value = cached_data

        result = await cache_service.get_cached_weather("London")

        assert result is None

    async def test_store_weather_data(
        self, cache_service, mock_storage_provider, sample_weather_data
    ):
        """Test storing weather data in cache"""
        expected_path = "/cache/london_12345.json"
        mock_storage_provider.store_weather_data.return_value = expected_path

        result = await cache_service.store_weather_data("London", sample_weather_data)

        assert result == expected_path
        mock_storage_provider.store_weather_data.assert_called_once()

        call_args = mock_storage_provider.store_weather_data.call_args
        assert call_args[1]["city"] == "London"
        assert call_args[1]["timestamp"] == sample_weather_data.timestamp
        assert isinstance(call_args[1]["data"], dict)

    async def test_cache_age_calculation(self, cache_service):
        """Test cache age calculation functionality"""
        timestamp = datetime.now(timezone.utc) - timedelta(seconds=30)

        age_seconds = cache_service._calculate_cache_age_seconds(timestamp)

        assert 29 <= age_seconds <= 35

    async def test_cache_age_calculation_timezone_naive(self, cache_service):
        """Test cache age calculation with timezone-naive datetime"""
        # Create a timezone-naive timestamp 30 seconds ago in UTC
        utc_now = datetime.now(timezone.utc)
        timestamp = utc_now.replace(tzinfo=None) - timedelta(seconds=30)

        age_seconds = cache_service._calculate_cache_age_seconds(timestamp)

        assert 29 <= age_seconds <= 35

    async def test_get_cached_weather_storage_error(
        self, cache_service, mock_storage_provider
    ):
        """Test handling of storage provider errors during cache retrieval"""
        mock_storage_provider.get_weather_data.side_effect = Exception("Storage error")

        with pytest.raises(CacheError) as exc_info:
            await cache_service.get_cached_weather("London")

        assert "Failed to retrieve cached weather data for London" in str(
            exc_info.value
        )

    async def test_store_weather_data_storage_error(
        self, cache_service, mock_storage_provider, sample_weather_data
    ):
        """Test handling of storage provider errors during data storage"""
        mock_storage_provider.store_weather_data.side_effect = Exception(
            "Storage error"
        )

        with pytest.raises(CacheError) as exc_info:
            await cache_service.store_weather_data("London", sample_weather_data)

        assert "Failed to store weather data for London" in str(exc_info.value)

    async def test_is_data_expired_true(self, cache_service):
        """Test data expiration check for expired data"""
        old_timestamp = datetime.now(timezone.utc) - timedelta(minutes=10)

        is_expired = cache_service._is_data_expired(old_timestamp)

        assert is_expired is True

    async def test_is_data_expired_false(self, cache_service):
        """Test data expiration check for fresh data"""
        recent_timestamp = datetime.now(timezone.utc) - timedelta(minutes=2)

        is_expired = cache_service._is_data_expired(recent_timestamp)

        assert is_expired is False

    async def test_get_cached_weather_missing_timestamp(
        self, cache_service, mock_storage_provider
    ):
        """Test handling of cached data without timestamp"""
        cached_data = {
            "city": "London",
            "temperature": 20.5,
            "description": "Clear sky",
            "humidity": 65,
            "pressure": 1013.25,
            "wind_speed": 3.5,
            "source": "openweathermap",
            # Missing timestamp field
        }
        mock_storage_provider.get_weather_data.return_value = cached_data

        result = await cache_service.get_cached_weather("London")

        assert result is None

    async def test_invalidate_expired_cache(self, cache_service, mock_storage_provider):
        """Test cache invalidation functionality"""
        mock_storage_provider.delete_expired_data.return_value = 3

        deleted_count = await cache_service.invalidate_expired_cache()

        assert deleted_count == 3
        mock_storage_provider.delete_expired_data.assert_called_once_with(
            max_age_minutes=5
        )

    async def test_is_cache_healthy(self, cache_service, mock_storage_provider):
        """Test cache health check"""
        mock_storage_provider.health_check.return_value = True

        is_healthy = await cache_service.is_cache_healthy()

        assert is_healthy is True
        mock_storage_provider.health_check.assert_called_once()

    def test_get_ttl_minutes(self, cache_service):
        """Test TTL getter method"""
        ttl = cache_service.get_ttl_minutes()

        assert ttl == 5

    def test_get_cache_info(self, cache_service):
        """Test cache info getter method"""
        info = cache_service.get_cache_info("London")

        assert info["city"] == "London"
        assert "cache_key" in info
        assert info["ttl_minutes"] == 5
        assert "storage_provider" in info
