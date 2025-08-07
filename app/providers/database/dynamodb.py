import asyncio
import re
import uuid
from datetime import datetime, timedelta

import aioboto3
import structlog
from botocore.exceptions import ClientError

from app.config.settings import settings
from app.models.events import EventStatus, EventType
from app.utils.exceptions import DatabaseError

from .base import DatabaseProvider


class DynamoDBProvider(DatabaseProvider):
    """DynamoDB implementation of the database provider"""

    def __init__(self):
        self.table_name = settings.dynamodb_table_name
        self.region = settings.aws_region
        self.logger = structlog.get_logger(__name__).bind(
            provider="dynamodb", table=self.table_name
        )

    async def _get_client(self):
        """Get async DynamoDB client"""
        session = aioboto3.Session(
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            aws_session_token=settings.aws_session_token,
            region_name=self.region,
        )
        return session.client("dynamodb")

    async def _get_resource(self):
        """Get async DynamoDB resource"""
        session = aioboto3.Session(
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            aws_session_token=settings.aws_session_token,
            region_name=self.region,
        )
        return session.resource("dynamodb")

    async def log_weather_request(
        self,
        city: str,
        timestamp: datetime,
        storage_path: str,
        success: bool = True,
        error_message: str | None = None,
    ) -> str:
        """Log a weather API request event to DynamoDB"""
        # Input validation
        self._validate_city_name(city)
        self._validate_timestamp(timestamp)

        event_id = str(uuid.uuid4())

        self.logger.info(
            "logging_weather_request",
            event_id=event_id,
            city=city,
            success=success,
            has_error=error_message is not None,
        )

        try:
            async with await self._get_resource() as dynamodb:
                table = dynamodb.Table(self.table_name)

                item = {
                    "event_id": event_id,
                    "event_type": EventType.WEATHER_REQUEST,
                    "city": city.lower(),
                    "city_display": city,  # Keep original case for display
                    "timestamp": timestamp.isoformat(),
                    "timestamp_epoch": int(timestamp.timestamp()),  # For range queries
                    "status": EventStatus.SUCCESS if success else EventStatus.FAILED,
                    "storage_path": storage_path,
                    "ttl": int(
                        (timestamp + timedelta(days=30)).timestamp()
                    ),  # Auto-expire after 30 days
                }

                if error_message:
                    item["error_message"] = error_message

                await table.put_item(Item=item)

                self.logger.info(
                    "weather_request_logged",
                    event_id=event_id,
                    city=city,
                    success=success,
                )
                return event_id

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            self.logger.error(
                "dynamodb_put_item_failed",
                event_id=event_id,
                city=city,
                error_code=error_code,
                error=str(e),
            )
            raise DatabaseError(
                f"Failed to log weather request to DynamoDB: {error_code} - {str(e)}"
            ) from e
        except Exception as e:
            self.logger.error(
                "unexpected_dynamodb_error", event_id=event_id, city=city, error=str(e)
            )
            raise DatabaseError(
                f"Unexpected error logging to DynamoDB: {str(e)}"
            ) from e

    async def get_recent_requests(
        self, city: str | None = None, hours: int = 24, limit: int = 100
    ) -> list[dict]:
        """Get recent weather requests from DynamoDB"""
        if city:
            self._validate_city_name(city)

        self.logger.info("getting_recent_requests", city=city, hours=hours, limit=limit)

        try:
            async with await self._get_resource() as dynamodb:
                table = dynamodb.Table(self.table_name)

                cutoff_time = datetime.now() - timedelta(hours=hours)
                cutoff_epoch = int(cutoff_time.timestamp())

                if city:
                    response = await table.query(
                        IndexName="city-timestamp-index",
                        KeyConditionExpression=(
                            "city = :city AND timestamp_epoch >= :cutoff"
                        ),
                        ExpressionAttributeValues={
                            ":city": city.lower(),
                            ":cutoff": cutoff_epoch,
                        },
                        ScanIndexForward=False,  # Most recent first
                        Limit=limit,
                    )
                else:
                    response = await table.scan(
                        FilterExpression="timestamp_epoch >= :cutoff",
                        ExpressionAttributeValues={":cutoff": cutoff_epoch},
                        Limit=limit,
                    )

                items = response.get("Items", [])

                results = []
                for item in items:
                    result = {
                        "event_id": item["event_id"],
                        "event_type": item["event_type"],
                        "city": item["city_display"],
                        "timestamp": item["timestamp"],
                        "status": item["status"],
                        "storage_path": item["storage_path"],
                    }
                    if "error_message" in item:
                        result["error_message"] = item["error_message"]
                    results.append(result)

                self.logger.info(
                    "recent_requests_retrieved", city=city, count=len(results)
                )
                return results

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            self.logger.error(
                "get_recent_requests_failed",
                city=city,
                error_code=error_code,
                error=str(e),
            )
            raise DatabaseError(
                f"Failed to get recent requests from DynamoDB: {error_code} - {str(e)}"
            ) from e
        except Exception as e:
            self.logger.error(
                "unexpected_get_recent_requests_error", city=city, error=str(e)
            )
            raise DatabaseError(
                f"Unexpected error getting recent requests from DynamoDB: {str(e)}"
            ) from e

    async def get_request_stats(self, hours: int = 24) -> dict:
        """Get request statistics from DynamoDB"""
        self.logger.info("getting_request_stats", hours=hours)

        try:
            async with await self._get_resource() as dynamodb:
                table = dynamodb.Table(self.table_name)

                cutoff_time = datetime.now() - timedelta(hours=hours)
                cutoff_epoch = int(cutoff_time.timestamp())

                response = await table.scan(
                    FilterExpression="timestamp_epoch >= :cutoff",
                    ExpressionAttributeValues={":cutoff": cutoff_epoch},
                )

                items = response.get("Items", [])

                total_requests = len(items)
                successful_requests = sum(
                    1 for item in items if item["status"] == EventStatus.SUCCESS
                )
                failed_requests = total_requests - successful_requests

                city_counts = {}
                for item in items:
                    city = item["city_display"]
                    city_counts[city] = city_counts.get(city, 0) + 1

                most_requested_cities = sorted(
                    city_counts.keys(), key=lambda x: city_counts[x], reverse=True
                )[:10]

                stats = {
                    "total_requests": total_requests,
                    "successful_requests": successful_requests,
                    "failed_requests": failed_requests,
                    "cache_hits": 0,  # Not tracked in this implementation
                    "cache_misses": 0,  # Not tracked in this implementation
                    "average_response_time_ms": None,  # Not tracked
                    "period_hours": hours,
                    "most_requested_cities": most_requested_cities,
                }

                self.logger.info(
                    "request_stats_retrieved",
                    stats={
                        "total_requests": total_requests,
                        "successful_requests": successful_requests,
                        "failed_requests": failed_requests,
                    },
                )
                return stats

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            self.logger.error(
                "get_request_stats_failed", error_code=error_code, error=str(e)
            )
            raise DatabaseError(
                f"Failed to get request stats from DynamoDB: {error_code} - {str(e)}"
            ) from e
        except Exception as e:
            self.logger.error("unexpected_get_request_stats_error", error=str(e))
            raise DatabaseError(
                f"Unexpected error getting request stats from DynamoDB: {str(e)}"
            ) from e

    async def cleanup_old_records(self, days: int = 30) -> int:
        """Remove old records from DynamoDB"""
        self.logger.info("starting_cleanup", days=days)

        try:
            async with await self._get_resource() as dynamodb:
                table = dynamodb.Table(self.table_name)

                cutoff_time = datetime.now() - timedelta(days=days)
                cutoff_epoch = int(cutoff_time.timestamp())

                response = await table.scan(
                    FilterExpression="timestamp_epoch < :cutoff",
                    ExpressionAttributeValues={":cutoff": cutoff_epoch},
                    ProjectionExpression="event_id",
                )

                items = response.get("Items", [])
                deleted_count = 0

                # Process items in batches of 25 (DynamoDB limit)
                for i in range(0, len(items), 25):
                    batch = items[i : i + 25]  # noqa: E203

                    # Use async batch operations properly
                    delete_requests = []
                    for item in batch:
                        delete_requests.append(
                            {"DeleteRequest": {"Key": {"event_id": item["event_id"]}}}
                        )

                    # Use async batch_write_item instead of sync batch_writer
                    async with await self._get_client() as client:
                        await client.batch_write_item(
                            RequestItems={self.table_name: delete_requests}
                        )

                    deleted_count += len(batch)

                    # Add small delay between batches to avoid throttling
                    if i + 25 < len(items):
                        await asyncio.sleep(0.1)

                self.logger.info("cleanup_completed", deleted_count=deleted_count)
                return deleted_count

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            self.logger.error("cleanup_failed", error_code=error_code, error=str(e))
            raise DatabaseError(
                f"Failed to cleanup old records in DynamoDB: {error_code} - {str(e)}"
            ) from e
        except Exception as e:
            self.logger.error("unexpected_cleanup_error", error=str(e))
            raise DatabaseError(
                f"Unexpected error cleaning up DynamoDB records: {str(e)}"
            ) from e

    async def health_check(self) -> bool:
        """Check if DynamoDB table is accessible"""
        try:
            async with await self._get_client() as dynamodb:
                response = await dynamodb.describe_table(TableName=self.table_name)
                table_status = response["Table"]["TableStatus"]
                is_healthy = table_status == "ACTIVE"

                self.logger.info(
                    "health_check_completed",
                    table_status=table_status,
                    is_healthy=is_healthy,
                )
                return is_healthy

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code")
            self.logger.warning(
                "health_check_failed",
                error_code=error_code,
                table_exists=(error_code != "ResourceNotFoundException"),
            )
            return False
        except Exception as e:
            self.logger.error("health_check_error", error=str(e))
            return False

    async def create_table_if_not_exists(self) -> bool:
        """Create DynamoDB table if it doesn't exist (utility method)"""
        try:
            async with await self._get_client() as dynamodb:
                try:
                    await dynamodb.describe_table(TableName=self.table_name)
                    return True
                except ClientError as e:
                    if (
                        e.response.get("Error", {}).get("Code")
                        != "ResourceNotFoundException"
                    ):
                        raise

                await dynamodb.create_table(
                    TableName=self.table_name,
                    KeySchema=[{"AttributeName": "event_id", "KeyType": "HASH"}],
                    AttributeDefinitions=[
                        {"AttributeName": "event_id", "AttributeType": "S"},
                        {"AttributeName": "city", "AttributeType": "S"},
                        {"AttributeName": "timestamp_epoch", "AttributeType": "N"},
                    ],
                    GlobalSecondaryIndexes=[
                        {
                            "IndexName": "city-timestamp-index",
                            "KeySchema": [
                                {"AttributeName": "city", "KeyType": "HASH"},
                                {
                                    "AttributeName": "timestamp_epoch",
                                    "KeyType": "RANGE",
                                },
                            ],
                            "Projection": {"ProjectionType": "ALL"},
                            "BillingMode": "PAY_PER_REQUEST",
                        }
                    ],
                    BillingMode="PAY_PER_REQUEST",
                )

                return True

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            raise DatabaseError(
                f"Failed to create DynamoDB table: {error_code} - {str(e)}"
            ) from e
        except Exception as e:
            raise DatabaseError(
                f"Unexpected error creating DynamoDB table: {str(e)}"
            ) from e

    def _validate_city_name(self, city: str) -> None:
        """Validate city name input"""
        if not city or not city.strip():
            raise ValueError("City name cannot be empty")

        if len(city.strip()) > 100:
            raise ValueError("City name too long (max 100 characters)")

        # Basic validation for malicious input
        if re.search(r'[<>"\\]', city):
            raise ValueError("City name contains invalid characters")

    def _validate_timestamp(self, timestamp: datetime) -> None:
        """Validate timestamp input"""
        now = datetime.now()

        # Don't allow timestamps too far in the future (1 hour tolerance)
        if timestamp > now + timedelta(hours=1):
            raise ValueError("Timestamp cannot be more than 1 hour in the future")

        # Don't allow very old timestamps (1 year)
        if timestamp < now - timedelta(days=365):
            raise ValueError("Timestamp cannot be more than 1 year in the past")
