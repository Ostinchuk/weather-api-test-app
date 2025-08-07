import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from pydantic import ValidationError

from app.config.settings import Settings
from app.models.weather import WeatherData
from app.utils.exceptions import (
    APIRateLimitError,
    APITimeoutError,
    ConfigurationError,
    ExternalAPIError,
    InvalidCityError,
)

logger = logging.getLogger(__name__)


class WeatherClient:
    """
    Async weather client for fetching data from external weather API (OpenWeatherMap)
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._validate_config()
        self.client: httpx.AsyncClient | None = None
        self._circuit_breaker_failures = 0
        self._circuit_breaker_last_failure: datetime | None = None
        self._circuit_breaker_threshold = 5
        self._circuit_breaker_reset_timeout = 60

    def _validate_config(self) -> None:
        """Validate client configuration"""
        if not self.settings.weather_api_key:
            raise ConfigurationError("Weather API key is required but not provided")

        if not self.settings.weather_api_url:
            raise ConfigurationError("Weather API URL is required but not provided")

    async def __aenter__(self) -> "WeatherClient":
        """Async context manager entry"""
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.settings.weather_api_timeout),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
        )
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit"""
        if self.client:
            await self.client.aclose()

    def _is_circuit_breaker_open(self) -> bool:
        """Check if circuit breaker is open (preventing requests)"""
        if self._circuit_breaker_failures < self._circuit_breaker_threshold:
            return False

        if self._circuit_breaker_last_failure is None:
            return False

        elapsed = (datetime.now() - self._circuit_breaker_last_failure).total_seconds()
        if elapsed > self._circuit_breaker_reset_timeout:
            # Reset circuit breaker
            self._circuit_breaker_failures = 0
            self._circuit_breaker_last_failure = None
            logger.info("Circuit breaker reset after timeout")
            return False

        return True

    def _record_failure(self) -> None:
        """Record a failure for circuit breaker tracking"""
        self._circuit_breaker_failures += 1
        self._circuit_breaker_last_failure = datetime.now()
        logger.warning(
            f"Circuit breaker failure count: {self._circuit_breaker_failures}"
        )

    def _record_success(self) -> None:
        """Record a success, potentially resetting circuit breaker"""
        if self._circuit_breaker_failures > 0:
            self._circuit_breaker_failures = 0
            self._circuit_breaker_last_failure = None
            logger.info("Circuit breaker reset after successful request")

    async def fetch_weather_data(self, city: str) -> WeatherData:
        """Fetch weather data for a given city from external API"""
        if not self.client:
            raise ConfigurationError(
                "Weather client not initialized. Use async context manager."
            )

        # Circuit breaker check
        if self._is_circuit_breaker_open():
            logger.error("Circuit breaker is open, rejecting request")
            raise ExternalAPIError(
                "Service temporarily unavailable due to circuit breaker"
            )

        city = city.strip()
        if not city:
            raise InvalidCityError(city, "City name cannot be empty")

        logger.info(f"Fetching weather data for city: {city}")

        try:
            response = await self._make_api_request(city)
            weather_data = self._parse_response(response, city)
            self._record_success()

            logger.info(f"Successfully fetched weather data for {city}")
            return weather_data

        except (ExternalAPIError, InvalidCityError, APITimeoutError, APIRateLimitError):
            self._record_failure()
            raise
        except Exception as e:
            self._record_failure()
            logger.error(f"Unexpected error fetching weather data for {city}: {e}")
            raise ExternalAPIError(f"Unexpected error: {str(e)}") from e

    async def _make_api_request(self, city: str) -> httpx.Response:
        """Make HTTP request to weather API"""
        params = {
            "q": city,
            "appid": self.settings.weather_api_key,
            "units": "metric",  # Celsius
        }

        try:
            response = await self.client.get(
                str(self.settings.weather_api_url), params=params
            )

            if response.status_code == 200:
                return response
            elif response.status_code == 401:
                raise ExternalAPIError(
                    "Invalid API key", response.status_code, response.text
                )
            elif response.status_code == 404:
                raise InvalidCityError(city, f"City '{city}' not found")
            elif response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                retry_seconds = int(retry_after) if retry_after else None
                raise APIRateLimitError(retry_seconds)
            else:
                raise ExternalAPIError(
                    f"API returned status {response.status_code}",
                    response.status_code,
                    response.text,
                )

        except httpx.TimeoutException as e:
            logger.error(f"API request timed out for city: {city}")
            raise APITimeoutError(self.settings.weather_api_timeout) from e
        except httpx.RequestError as e:
            logger.error(f"Request error for city {city}: {e}")
            raise ExternalAPIError(f"Request failed: {str(e)}") from e

    def _parse_response(self, response: httpx.Response, city: str) -> WeatherData:
        """Parse API response into WeatherData model"""
        try:
            data = response.json()
        except Exception as e:
            logger.error(f"Failed to parse JSON response for {city}: {e}")
            raise ExternalAPIError(f"Invalid JSON response: {str(e)}") from e

        try:
            main = data.get("main", {})
            weather = data.get("weather", [{}])[0]
            wind = data.get("wind", {})

            return WeatherData(
                city=city,
                temperature=main.get("temp", 0.0),
                description=weather.get("description", ""),
                humidity=main.get("humidity", 0),
                pressure=main.get("pressure", 0.0),
                wind_speed=wind.get("speed", 0.0),
                wind_direction=wind.get("deg"),
                visibility=data.get("visibility", 0.0) / 1000
                if data.get("visibility")
                else None,  # Convert to km
                timestamp=datetime.now(timezone.utc),
                source="openweathermap",
            )

        except (KeyError, TypeError, ValidationError) as e:
            logger.error(f"Failed to parse weather data for {city}: {e}")
            raise ExternalAPIError(f"Failed to parse weather data: {str(e)}") from e

    async def health_check(self) -> bool:
        """Perform health check by making a test request"""
        try:
            test_city = self.settings.health_check_city
            await self.fetch_weather_data(test_city)
            return True
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False


async def create_weather_client(settings: Settings) -> WeatherClient:
    """Factory function to create and initialize weather client"""
    return WeatherClient(settings)
