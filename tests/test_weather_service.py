from datetime import datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.config.settings import Settings
from app.models.events import EventStatus
from app.models.weather import WeatherData
from app.services.weather_service import WeatherService
from app.utils.exceptions import InvalidCityError


class TestWeatherService:
    """Test suite for WeatherService"""

    @pytest.fixture
    async def mock_settings(self):
        """Create mock settings for testing"""
        return Settings(
            weather_api_key="test-api-key",
            cache_ttl_minutes=5,
            provider_mode="local",
            local_storage_path="./test_data/weather_files",
            local_db_path="./test_data/weather_events.db",
        )

    @pytest.fixture
    async def weather_service(self, mock_settings):
        """Create WeatherService instance for testing"""
        service = WeatherService(mock_settings)
        return service

    @pytest.fixture
    async def sample_weather_data(self):
        """Create sample weather data for testing"""
        return WeatherData(
            city="London",
            temperature=15.5,
            description="Clear sky",
            humidity=65,
            pressure=1013.25,
            wind_speed=3.2,
            wind_direction=180,
            visibility=10.0,
            timestamp=datetime.now(),
            source="openweathermap",
        )

    async def test_service_initialization(self, mock_settings):
        """Test service initialization process"""
        # Test successful initialization
        with (
            patch("app.services.weather_service.WeatherClient") as mock_weather_client,
            patch("app.services.weather_service.CacheService") as mock_cache_service,
            patch(
                "app.services.weather_service.create_storage_provider"
            ) as mock_storage_provider,
            patch(
                "app.services.weather_service.get_database_provider"
            ) as mock_database_provider,
        ):
            service = WeatherService(mock_settings)

            # Service should not be initialized yet
            assert not service._initialized

            # Initialize the service
            await service.initialize()

            # Service should now be initialized
            assert service._initialized

            mock_weather_client.assert_called_once_with(mock_settings)
            mock_cache_service.assert_called_once()
            mock_storage_provider.assert_called_once_with(mock_settings)
            mock_database_provider.assert_called_once()

    async def test_get_weather_cache_hit(self, weather_service, sample_weather_data):
        """Test get_weather with cache hit scenario"""
        city = "London"
        cache_age_seconds = 120
        event_id = str(uuid4())

        mock_cache_service = AsyncMock()
        mock_database_provider = AsyncMock()

        mock_cache_service.get_cached_weather.return_value = (
            sample_weather_data,
            cache_age_seconds,
        )
        mock_database_provider.log_event.return_value = event_id

        weather_service._cache_service = mock_cache_service
        weather_service._database_provider = mock_database_provider
        weather_service._initialized = True

        result_data, metadata = await weather_service.get_weather(city)

        assert result_data == sample_weather_data
        assert metadata["cache_hit"] is True
        assert metadata["cache_age_seconds"] == cache_age_seconds
        assert metadata["storage_path"] is None
        assert metadata["event_id"] == event_id

        mock_cache_service.get_cached_weather.assert_called_once_with(city)

        mock_database_provider.log_event.assert_called_once()
        logged_event = mock_database_provider.log_event.call_args[0][0]
        assert logged_event.city == city
        assert logged_event.status == EventStatus.SUCCESS
        assert logged_event.metadata["cache_hit"] is True
        assert logged_event.metadata["cached"] is True
        assert logged_event.metadata["external_api_called"] is False

    async def test_get_weather_cache_miss(self, weather_service, sample_weather_data):
        """Test get_weather with cache miss scenario"""
        city = "London"
        storage_path = "/path/to/stored/file.json"
        event_id = str(uuid4())

        mock_cache_service = AsyncMock()
        mock_weather_client = AsyncMock()
        mock_database_provider = AsyncMock()

        mock_cache_service.get_cached_weather.return_value = None
        mock_cache_service.store_weather_data.return_value = storage_path
        mock_database_provider.log_event.return_value = event_id

        # Mock weather client context manager
        mock_weather_client.__aenter__.return_value = mock_weather_client
        mock_weather_client.__aexit__.return_value = None
        mock_weather_client.fetch_weather_data.return_value = sample_weather_data

        weather_service._cache_service = mock_cache_service
        weather_service._weather_client = mock_weather_client
        weather_service._database_provider = mock_database_provider
        weather_service._initialized = True

        result_data, metadata = await weather_service.get_weather(city)

        assert result_data == sample_weather_data
        assert metadata["cache_hit"] is False
        assert metadata["cache_age_seconds"] == 0
        assert metadata["storage_path"] == storage_path
        assert metadata["event_id"] == event_id

        mock_cache_service.get_cached_weather.assert_called_once_with(city)
        mock_cache_service.store_weather_data.assert_called_once_with(
            city, sample_weather_data
        )

        mock_database_provider.log_event.assert_called_once()
        logged_event = mock_database_provider.log_event.call_args[0][0]
        assert logged_event.city == city
        assert logged_event.status == EventStatus.SUCCESS
        assert logged_event.metadata["cache_hit"] is False
        assert logged_event.metadata["cached"] is False
        assert logged_event.metadata["external_api_called"] is True

    async def test_get_weather_invalid_city(self, weather_service):
        """Test get_weather with invalid city input"""
        weather_service._initialized = True

        with pytest.raises(InvalidCityError, match="City name cannot be empty"):
            await weather_service.get_weather("")

        with pytest.raises(InvalidCityError, match="City name cannot be empty"):
            await weather_service.get_weather("   ")

        with pytest.raises(InvalidCityError, match="City name cannot be empty"):
            await weather_service.get_weather(None)

    async def test_health_check_exception_handling(self, weather_service):
        """Test health check exception handling"""
        mock_weather_client = AsyncMock()
        mock_weather_client.__aenter__.return_value = mock_weather_client
        mock_weather_client.__aexit__.return_value = None
        mock_weather_client.health_check.side_effect = Exception("Health check failed")

        weather_service._weather_client = mock_weather_client
        weather_service._cache_service = None
        weather_service._storage_provider = AsyncMock()
        weather_service._database_provider = AsyncMock()
        weather_service._initialized = True

        health_status = await weather_service.health_check()

        assert health_status["service"] == "unhealthy"
        assert "error" in health_status
