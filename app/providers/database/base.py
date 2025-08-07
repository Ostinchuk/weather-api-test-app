from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.events import EventData


class DatabaseProvider(ABC):
    """Abstract base class for database providers (DynamoDB, local DB, etc.)"""

    @abstractmethod
    async def log_weather_request(
        self,
        city: str,
        timestamp: datetime,
        storage_path: str,
        success: bool = True,
        error_message: str | None = None,
    ) -> str:
        """
        Log a weather API request event

        Args:
            city: Name of the city
            timestamp: When the request was made
            storage_path: Path where the weather data is stored
            success: Whether the request was successful
            error_message: Error message if request failed

        Returns:
            Event ID or identifier
        """
        pass

    @abstractmethod
    async def get_recent_requests(
        self, city: str | None = None, hours: int = 24, limit: int = 100
    ) -> list[dict]:
        """
        Get recent weather requests

        Args:
            city: Filter by city name (None for all cities)
            hours: Number of hours to look back
            limit: Maximum number of records to return

        Returns:
            List of request records
        """
        pass

    @abstractmethod
    async def get_request_stats(self, hours: int = 24) -> dict:
        """
        Get request statistics

        Args:
            hours: Number of hours to look back

        Returns:
            Dictionary with statistics (total requests, success rate, etc.)
        """
        pass

    @abstractmethod
    async def cleanup_old_records(self, days: int = 30) -> int:
        """
        Remove old records to prevent database growth

        Args:
            days: Number of days to keep records

        Returns:
            Number of records deleted
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """
        Check if the database provider is healthy and accessible

        Returns:
            True if healthy, False otherwise
        """
        pass

    @abstractmethod
    async def log_event(self, event_data: "EventData") -> str:
        """
        Log an event using EventData model

        Args:
            event_data: EventData instance containing event information

        Returns:
            Event ID or identifier
        """
        pass
