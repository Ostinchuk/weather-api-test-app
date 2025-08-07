from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from app.config.settings import Settings
from app.models.weather import WeatherData
from app.services.weather_client import WeatherClient
from app.utils.exceptions import (
    APITimeoutError,
    ConfigurationError,
    ExternalAPIError,
    InvalidCityError,
)


class TestWeatherClient:
    """Test suite for WeatherClient"""

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings for testing"""
        return Settings(
            weather_api_key="test-api-key",
            weather_api_url="https://api.openweathermap.org/data/2.5/weather",
            weather_api_timeout=10,
            health_check_city="London",
        )

    @pytest.fixture
    def weather_client(self, mock_settings):
        """Create WeatherClient instance for testing"""
        return WeatherClient(mock_settings)

    @pytest.fixture
    def sample_api_response(self):
        """Sample API response from OpenWeatherMap"""
        return {
            "main": {
                "temp": 15.5,
                "humidity": 65,
                "pressure": 1013.25,
            },
            "weather": [{"description": "clear sky"}],
            "wind": {"speed": 3.2, "deg": 180},
            "visibility": 10000,
        }

    @pytest.fixture
    def expected_weather_data(self):
        """Expected WeatherData object from parsed response"""
        return WeatherData(
            city="London",
            temperature=15.5,
            description="clear sky",
            humidity=65,
            pressure=1013.25,
            wind_speed=3.2,
            wind_direction=180,
            visibility=10.0,
            timestamp=datetime.now(timezone.utc),
            source="openweathermap",
        )

    async def test_fetch_weather_success(
        self, weather_client, sample_api_response, expected_weather_data
    ):
        """Test successful weather data fetching"""
        city = "London"

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_api_response

        mock_httpx_client = AsyncMock()
        mock_httpx_client.get.return_value = mock_response

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.return_value = mock_httpx_client

            async with weather_client as client:
                result = await client.fetch_weather_data(city)

                assert result.city == expected_weather_data.city
                assert result.temperature == expected_weather_data.temperature
                assert result.description == expected_weather_data.description
                assert result.humidity == expected_weather_data.humidity
                assert result.pressure == expected_weather_data.pressure
                assert result.wind_speed == expected_weather_data.wind_speed
                assert result.wind_direction == expected_weather_data.wind_direction
                assert result.visibility == expected_weather_data.visibility
                assert result.source == expected_weather_data.source

                mock_httpx_client.get.assert_called_once_with(
                    "https://api.openweathermap.org/data/2.5/weather",
                    params={
                        "q": city,
                        "appid": "test-api-key",
                        "units": "metric",
                    },
                )

    async def test_fetch_weather_404_city_not_found(self, weather_client):
        """Test handling of 404 error for city not found"""
        city = "NonexistentCity"

        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.text = "city not found"

        mock_httpx_client = AsyncMock()
        mock_httpx_client.get.return_value = mock_response

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.return_value = mock_httpx_client

            async with weather_client as client:
                with pytest.raises(InvalidCityError) as exc_info:
                    await client.fetch_weather_data(city)

                assert f"City '{city}' not found" in str(exc_info.value)

                assert client._circuit_breaker_failures == 1
                assert client._circuit_breaker_last_failure is not None

    async def test_fetch_weather_401_invalid_api_key(self, weather_client):
        """Test handling of 401 error for invalid API key"""
        city = "London"

        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.text = "Invalid API key"

        mock_httpx_client = AsyncMock()
        mock_httpx_client.get.return_value = mock_response

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.return_value = mock_httpx_client

            async with weather_client as client:
                with pytest.raises(ExternalAPIError) as exc_info:
                    await client.fetch_weather_data(city)

                assert "Invalid API key" in str(exc_info.value)

                assert client._circuit_breaker_failures == 1
                assert client._circuit_breaker_last_failure is not None

    async def test_circuit_breaker_functionality(self, weather_client):
        """Test circuit breaker prevents requests after threshold failures"""
        city = "London"

        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal server error"

        mock_httpx_client = AsyncMock()
        mock_httpx_client.get.return_value = mock_response

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.return_value = mock_httpx_client

            async with weather_client as client:
                for i in range(5):
                    with pytest.raises(ExternalAPIError):
                        await client.fetch_weather_data(city)
                    assert client._circuit_breaker_failures == i + 1

                assert client._is_circuit_breaker_open()

                with pytest.raises(ExternalAPIError) as exc_info:
                    await client.fetch_weather_data(city)

                assert "Service temporarily unavailable" in str(exc_info.value)

                assert mock_httpx_client.get.call_count == 5

    async def test_api_timeout_handling(self, weather_client):
        """Test handling of API timeout"""
        city = "London"

        mock_httpx_client = AsyncMock()
        mock_httpx_client.get.side_effect = httpx.TimeoutException("Request timed out")

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.return_value = mock_httpx_client

            async with weather_client as client:
                with pytest.raises(APITimeoutError) as exc_info:
                    await client.fetch_weather_data(city)

                assert str(weather_client.settings.weather_api_timeout) in str(
                    exc_info.value
                )

                assert client._circuit_breaker_failures == 1
                assert client._circuit_breaker_last_failure is not None

    async def test_client_not_initialized_error(self, weather_client):
        """Test error when client is used without async context manager"""
        with pytest.raises(ConfigurationError) as exc_info:
            await weather_client.fetch_weather_data("London")

        assert "Weather client not initialized" in str(exc_info.value)

    async def test_empty_city_validation(self, weather_client):
        """Test validation of empty city names"""
        mock_httpx_client = AsyncMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.return_value = mock_httpx_client

            async with weather_client as client:
                with pytest.raises(InvalidCityError) as exc_info:
                    await client.fetch_weather_data("")
                assert "City name cannot be empty" in str(exc_info.value)

                with pytest.raises(InvalidCityError) as exc_info:
                    await client.fetch_weather_data("   ")
                assert "City name cannot be empty" in str(exc_info.value)

    async def test_circuit_breaker_reset_after_timeout(self, weather_client):
        """Test circuit breaker resets after timeout period"""
        weather_client._circuit_breaker_failures = 5
        weather_client._circuit_breaker_last_failure = datetime.now()

        assert weather_client._is_circuit_breaker_open()

        from datetime import timedelta

        with patch("app.services.weather_client.datetime") as mock_datetime:
            mock_datetime.now.return_value = (
                weather_client._circuit_breaker_last_failure + timedelta(seconds=61)
            )

            assert not weather_client._is_circuit_breaker_open()
            assert weather_client._circuit_breaker_failures == 0
            assert weather_client._circuit_breaker_last_failure is None
