import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aioboto3
from botocore.exceptions import BotoCoreError, ClientError

from app.config.settings import Settings
from app.providers.storage.base import StorageProvider
from app.utils.exceptions import StorageError

logger = logging.getLogger(__name__)


class S3StorageProvider(StorageProvider):
    """S3-based storage provider for weather data"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.bucket_name = settings.s3_bucket_name
        self.prefix = settings.s3_prefix
        self.session = aioboto3.Session(
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            aws_session_token=settings.aws_session_token,
            region_name=settings.aws_region,
        )

    def _get_file_key(self, city: str, timestamp: datetime) -> str:
        """Generate S3 key for weather data file"""
        timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S")
        return f"{self.prefix}{city.lower()}_{timestamp_str}.json"

    async def store_weather_data(
        self, city: str, data: dict[str, Any], timestamp: datetime
    ) -> str:
        """Store weather data in S3 bucket"""
        try:
            async with self.session.client("s3") as s3_client:
                key = self._get_file_key(city, timestamp)

                weather_data = {
                    "city": city,
                    "timestamp": timestamp.isoformat(),
                    "data": data,
                }

                await s3_client.put_object(
                    Bucket=self.bucket_name,
                    Key=key,
                    Body=json.dumps(weather_data, indent=2),
                    ContentType="application/json",
                    Metadata={
                        "city": city.lower(),
                        "timestamp": timestamp.isoformat(),
                    },
                )

                s3_url = f"s3://{self.bucket_name}/{key}"
                logger.info(f"Successfully stored weather data for {city} at {s3_url}")
                return s3_url

        except (ClientError, BotoCoreError) as e:
            logger.error(f"Failed to store weather data for {city} in S3: {e}")
            raise StorageError(f"Failed to store weather data in S3: {e}") from e
        except Exception as e:
            logger.error(f"Unexpected error storing weather data for {city}: {e}")
            raise StorageError(f"Unexpected storage error: {e}") from e

    async def get_weather_data(
        self, city: str, max_age_minutes: int = 5
    ) -> dict[str, Any] | None:
        """Retrieve cached weather data from S3 if not expired"""
        try:
            async with self.session.client("s3") as s3_client:
                prefix = f"{self.prefix}{city.lower()}_"

                response = await s3_client.list_objects_v2(
                    Bucket=self.bucket_name,
                    Prefix=prefix,
                    MaxKeys=50,
                )

                if "Contents" not in response:
                    logger.debug(f"No cached data found for {city}")
                    return None

                cutoff_time = datetime.now(timezone.utc) - timedelta(
                    minutes=max_age_minutes
                )
                recent_files = []

                for obj in response["Contents"]:
                    if obj["LastModified"] >= cutoff_time:
                        recent_files.append((obj["Key"], obj["LastModified"]))

                if not recent_files:
                    logger.debug(f"No recent cached data found for {city}")
                    return None

                most_recent_key = max(recent_files, key=lambda x: x[1])[0]

                obj_response = await s3_client.get_object(
                    Bucket=self.bucket_name, Key=most_recent_key
                )

                content = await obj_response["Body"].read()
                weather_data = json.loads(content.decode("utf-8"))

                logger.info(
                    f"Retrieved cached weather data for {city} from {most_recent_key}"
                )
                return dict(weather_data["data"])

        except (ClientError, BotoCoreError) as e:
            logger.error(f"Failed to retrieve weather data for {city} from S3: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error retrieving weather data for {city}: {e}")
            return None

    async def delete_expired_data(self, max_age_minutes: int = 5) -> int:
        """Delete expired weather data from S3"""
        try:
            async with self.session.client("s3") as s3_client:
                cutoff_time = datetime.now(timezone.utc) - timedelta(
                    minutes=max_age_minutes
                )

                response = await s3_client.list_objects_v2(
                    Bucket=self.bucket_name,
                    Prefix=self.prefix,
                )

                if "Contents" not in response:
                    logger.debug("No objects found for cleanup")
                    return 0

                expired_keys = []
                for obj in response["Contents"]:
                    if obj["LastModified"] < cutoff_time:
                        expired_keys.append({"Key": obj["Key"]})

                if not expired_keys:
                    logger.debug("No expired files found")
                    return 0

                deleted_count = 0
                for i in range(0, len(expired_keys), 1000):
                    batch = expired_keys[i : i + 1000]  # noqa: E203

                    await s3_client.delete_objects(
                        Bucket=self.bucket_name,
                        Delete={"Objects": batch},
                    )

                    deleted_count += len(batch)

                logger.info(
                    f"Deleted {deleted_count} expired weather data files from S3"
                )
                return deleted_count

        except (ClientError, BotoCoreError) as e:
            logger.error(f"Failed to delete expired data from S3: {e}")
            raise StorageError(f"Failed to delete expired data from S3: {e}") from e
        except Exception as e:
            logger.error(f"Unexpected error during S3 cleanup: {e}")
            raise StorageError(f"Unexpected cleanup error: {e}") from e

    async def health_check(self) -> bool:
        """Check S3 connectivity and bucket access"""
        try:
            async with self.session.client("s3") as s3_client:
                await s3_client.head_bucket(Bucket=self.bucket_name)

                await s3_client.list_objects_v2(
                    Bucket=self.bucket_name,
                    Prefix=self.prefix,
                    MaxKeys=1,
                )

                logger.debug(f"S3 health check passed for bucket {self.bucket_name}")
                return True

        except (ClientError, BotoCoreError) as e:
            logger.error(f"S3 health check failed: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during S3 health check: {e}")
            return False
