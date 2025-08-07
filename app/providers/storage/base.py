from abc import ABC, abstractmethod
from datetime import datetime


class StorageProvider(ABC):
    """Abstract base class for storage providers (S3, local file, etc.)"""

    @abstractmethod
    async def store_weather_data(
        self, city: str, data: dict, timestamp: datetime
    ) -> str:
        """
        Store weather data and return the storage path/URL

        Args:
            city: Name of the city
            data: Weather data dictionary
            timestamp: When the data was fetched

        Returns:
            Storage path or URL where the data was stored
        """
        pass

    @abstractmethod
    async def get_weather_data(
        self, city: str, max_age_minutes: int = 5
    ) -> dict | None:
        """
        Retrieve cached weather data if it exists and is not expired

        Args:
            city: Name of the city
            max_age_minutes: Maximum age of data in minutes

        Returns:
            Weather data dictionary if found and valid, None otherwise
        """
        pass

    @abstractmethod
    async def delete_expired_data(self, max_age_minutes: int = 5) -> int:
        """
        Delete expired weather data

        Args:
            max_age_minutes: Maximum age of data in minutes

        Returns:
            Number of files deleted
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """
        Check if the storage provider is healthy and accessible

        Returns:
            True if healthy, False otherwise
        """
        pass
