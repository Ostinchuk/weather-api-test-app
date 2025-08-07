from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.main import create_app
from app.models.weather import WeatherData
from app.services.weather_service import WeatherService
from app.utils.exceptions import ExternalAPIError, InvalidCityError


class TestAPIEndpoints:
    """Test suite for API endpoints"""

    @pytest.fixture
    async def mock_settings(self):
        """Create mock settings for testing"""
        return Settings(
            weather_api_key="test-api-key",
            cache_ttl_minutes=5,
            provider_mode="local",
            local_storage_path="./test_data/weather_files",
            local_db_path="./test_data/weather_events.db",
            is_development=True,
        )

    @pytest.fixture
    async def sample_weather_data(self):
        """Create sample weather data for testing"""
        from datetime import datetime, timezone
        
        return WeatherData(
            city="London",
            temperature=18.5,
            description="Partly cloudy",
            humidity=65,
            pressure=1013.2,
            visibility=10.0,
            wind_speed=5.2,
            wind_direction=230,
            timestamp=datetime(2023, 11, 20, 15, 30, tzinfo=timezone.utc),
            source="openweathermap",
        )

    @pytest.fixture
    async def app(self, mock_settings):
        """Create FastAPI app for testing"""
        with patch("app.config.settings.settings", mock_settings):
            app = create_app()
            return app

    @pytest.fixture
    async def mock_weather_service(self, sample_weather_data):
        """Create mock weather service"""
        service = AsyncMock(spec=WeatherService)
        service._initialized = True

        metadata = {
            "cache_hit": True,
            "cache_age_seconds": 120,
            "storage_path": "weather-data/london_20231120_153000.json",
            "event_id": str(uuid4()),
            "external_api_called": False,
            "cached": True,
        }
        service.get_weather.return_value = (sample_weather_data, metadata)

        return service

    @pytest.fixture
    async def client(self, app, mock_weather_service):
        """Create test client with mocked weather service"""
        app.state.weather_service = mock_weather_service
        return TestClient(app)

    async def test_weather_endpoint_success(self, client):
        """Test successful weather endpoint response"""
        response = client.get("/api/v1/weather?city=London")

        assert response.status_code == 200
        data = response.json()

        assert "weather_data" in data
        assert "metadata" in data

        weather_data = data["weather_data"]
        assert weather_data["city"] == "London"
        assert weather_data["temperature"] == 18.5
        assert weather_data["description"] == "Partly cloudy"
        assert weather_data["humidity"] == 65
        assert weather_data["pressure"] == 1013.2
        assert weather_data["wind_speed"] == 5.2
        assert weather_data["source"] == "openweathermap"

        metadata = data["metadata"]
        assert "cache_hit" in metadata
        assert "cache_age_seconds" in metadata
        assert "storage_path" in metadata
        assert "event_id" in metadata

    async def test_weather_endpoint_invalid_city(self, client, mock_weather_service):
        """Test weather endpoint with invalid city"""
        mock_weather_service.get_weather.side_effect = InvalidCityError(
            "Invalid city name provided"
        )

        response = client.get("/api/v1/weather?city=InvalidCity123")

        assert response.status_code == 400
        data = response.json()
        assert "detail" in data
        assert "Invalid city" in data["detail"]

    async def test_weather_endpoint_missing_city_parameter(self, client):
        """Test weather endpoint without city parameter"""
        response = client.get("/api/v1/weather")

        assert response.status_code == 422
        data = response.json()
        assert "detail" in data

    async def test_weather_endpoint_empty_city_parameter(self, client):
        """Test weather endpoint with empty city parameter"""
        response = client.get("/api/v1/weather?city=")

        assert response.status_code == 422
        data = response.json()
        assert "detail" in data

    async def test_weather_endpoint_city_not_found(self, client, mock_weather_service):
        """Test weather endpoint when city is not found"""
        mock_weather_service.get_weather.side_effect = ExternalAPIError(
            "City not found"
        )

        response = client.get("/api/v1/weather?city=NonExistentCity")

        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
        assert "not found" in data["detail"]

    async def test_weather_endpoint_service_unavailable(
        self, client, mock_weather_service
    ):
        """Test weather endpoint when external service is unavailable"""
        mock_weather_service.get_weather.side_effect = ExternalAPIError(
            "External weather service unavailable"
        )

        response = client.get("/api/v1/weather?city=London")

        assert response.status_code == 503
        data = response.json()
        assert "detail" in data
        assert "unavailable" in data["detail"]
