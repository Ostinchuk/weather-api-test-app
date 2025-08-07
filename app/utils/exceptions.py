from typing import Any


class WeatherAPIError(Exception):
    """Base exception for weather API related errors"""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.status_code = 500
        self.error_code = "WEATHER_API_ERROR"


class ExternalAPIError(WeatherAPIError):
    """Exception raised when external weather API fails"""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        response_body: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class InvalidCityError(WeatherAPIError):
    """Exception raised when city name is invalid or not found"""

    def __init__(self, city: str, message: str | None = None):
        super().__init__(message or f"Invalid or unknown city: {city}")
        self.city = city


class APITimeoutError(WeatherAPIError):
    """Exception raised when API request times out"""

    def __init__(self, timeout_seconds: int):
        super().__init__(f"API request timed out after {timeout_seconds} seconds")
        self.timeout_seconds = timeout_seconds


class APIRateLimitError(WeatherAPIError):
    """Exception raised when API rate limit is exceeded"""

    def __init__(self, retry_after: int | None = None):
        message = "API rate limit exceeded"
        if retry_after:
            message += f". Retry after {retry_after} seconds"
        super().__init__(message)
        self.retry_after = retry_after


class ConfigurationError(WeatherAPIError):
    """Exception raised when configuration is invalid"""

    pass


class CacheError(WeatherAPIError):
    """Exception raised when cache operations fail"""

    def __init__(self, message: str, operation: str | None = None):
        super().__init__(message)
        self.operation = operation


class StorageError(WeatherAPIError):
    """Exception raised when storage operations fail"""

    def __init__(self, message: str, provider: str | None = None):
        super().__init__(message)
        self.provider = provider


class DatabaseError(WeatherAPIError):
    """Exception raised when database operations fail"""

    def __init__(self, message: str, operation: str | None = None):
        super().__init__(message)
        self.operation = operation


class WeatherServiceError(WeatherAPIError):
    """Exception raised when the weather service encounters errors"""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message, details)
        self.error_code = "WEATHER_SERVICE_ERROR"
