import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiofiles

from app.config.settings import Settings
from app.providers.storage.base import StorageProvider
from app.utils.exceptions import StorageError

logger = logging.getLogger(__name__)


class LocalFileStorageProvider(StorageProvider):
    """Local file system-based storage provider for weather data"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.storage_path = Path(settings.local_storage_path)
        # Ensure storage directory exists
        self.storage_path.mkdir(parents=True, exist_ok=True)

    def _get_file_path(self, city: str, timestamp: datetime) -> Path:
        """Generate file path for weather data file"""
        timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S")
        filename = f"{city.lower()}_{timestamp_str}.json"
        return self.storage_path / filename

    def _parse_timestamp_from_filename(self, filename: str) -> datetime | None:
        """Parse timestamp from filename"""
        try:
            # Extract timestamp part from filename (city_YYYYMMDD_HHMMSS.json)
            parts = filename.replace(".json", "").split("_")
            if len(parts) >= 3:
                date_part = parts[-2]  # YYYYMMDD
                time_part = parts[-1]  # HHMMSS
                timestamp_str = f"{date_part}_{time_part}"
                return datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
        except (ValueError, IndexError) as e:
            logger.warning(f"Failed to parse timestamp from filename {filename}: {e}")
        return None

    async def store_weather_data(
        self, city: str, data: dict[str, Any], timestamp: datetime
    ) -> str:
        """Store weather data in local file system"""
        try:
            file_path = self._get_file_path(city, timestamp)

            weather_data = {
                "city": city,
                "timestamp": timestamp.isoformat(),
                "data": data,
            }

            async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
                await f.write(json.dumps(weather_data, indent=2))

            logger.info(f"Successfully stored weather data for {city} at {file_path}")
            return str(file_path)

        except OSError as e:
            logger.error(f"Failed to store weather data for {city} in local file: {e}")
            raise StorageError(
                f"Failed to store weather data in local file: {e}"
            ) from e
        except Exception as e:
            logger.error(f"Unexpected error storing weather data for {city}: {e}")
            raise StorageError(f"Unexpected storage error: {e}") from e

    async def get_weather_data(
        self, city: str, max_age_minutes: int = 5
    ) -> dict[str, Any] | None:
        """Retrieve cached weather data from local file system if not expired"""
        try:
            pattern = f"{city.lower()}_*.json"
            matching_files = []

            for file_path in self.storage_path.glob(pattern):
                if file_path.is_file():
                    stat = file_path.stat()
                    modified_time = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
                    matching_files.append((file_path, modified_time))

            if not matching_files:
                logger.debug(f"No cached data found for {city}")
                return None

            cutoff_time = datetime.now(timezone.utc) - timedelta(
                minutes=max_age_minutes
            )
            recent_files = [
                (path, mtime) for path, mtime in matching_files if mtime >= cutoff_time
            ]

            if not recent_files:
                logger.debug(f"No recent cached data found for {city}")
                return None

            most_recent_path = max(recent_files, key=lambda x: x[1])[0]

            async with aiofiles.open(most_recent_path, "r", encoding="utf-8") as f:
                content = await f.read()
                weather_data = json.loads(content)

            logger.info(
                f"Retrieved cached weather data for {city} from {most_recent_path}"
            )
            return dict(weather_data["data"])

        except OSError as e:
            logger.error(
                f"Failed to retrieve weather data for {city} from local file: {e}"
            )
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON data for {city}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error retrieving weather data for {city}: {e}")
            return None

    async def delete_expired_data(self, max_age_minutes: int = 5) -> int:
        """Delete expired weather data from local file system"""
        try:
            cutoff_time = datetime.now(timezone.utc) - timedelta(
                minutes=max_age_minutes
            )
            deleted_count = 0

            for file_path in self.storage_path.glob("*.json"):
                if not file_path.is_file():
                    continue

                try:
                    stat = file_path.stat()
                    modified_time = datetime.fromtimestamp(stat.st_mtime, timezone.utc)

                    if modified_time < cutoff_time:
                        file_path.unlink()
                        deleted_count += 1
                        logger.debug(f"Deleted expired file: {file_path}")

                except OSError as e:
                    logger.warning(f"Failed to delete file {file_path}: {e}")
                    continue

            if deleted_count > 0:
                logger.info(f"Deleted {deleted_count} expired weather data files")
            else:
                logger.debug("No expired files found")

            return deleted_count

        except Exception as e:
            logger.error(f"Unexpected error during local file cleanup: {e}")
            raise StorageError(f"Unexpected cleanup error: {e}") from e

    async def health_check(self) -> bool:
        """Check local file system accessibility"""
        try:
            if not self.storage_path.exists():
                logger.error(f"Storage directory does not exist: {self.storage_path}")
                return False

            if not self.storage_path.is_dir():
                logger.error(f"Storage path is not a directory: {self.storage_path}")
                return False

            test_file = self.storage_path / ".health_check_test"
            try:
                async with aiofiles.open(test_file, "w") as f:
                    await f.write("health_check")

                if test_file.exists():
                    test_file.unlink()

                logger.debug(
                    f"Local file storage health check passed for {self.storage_path}"
                )
                return True

            except OSError as e:
                logger.error(f"Storage directory is not writable: {e}")
                return False

        except Exception as e:
            logger.error(f"Unexpected error during local file health check: {e}")
            return False
