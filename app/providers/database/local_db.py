import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import aiosqlite
import structlog

from app.config.settings import settings
from app.models.events import EventStatus, EventType, WeatherRequestEvent
from app.utils.exceptions import DatabaseError

from .base import DatabaseProvider


class LocalDatabaseProvider(DatabaseProvider):
    """SQLite implementation of the database provider"""

    def __init__(self):
        self.db_path = settings.local_db_path
        self._ensure_db_directory()
        self.logger = structlog.get_logger(__name__).bind(
            provider="local_db", db_path=self.db_path
        )

    def _ensure_db_directory(self):
        """Ensure the database directory exists"""
        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

    async def _get_connection(self):
        """Get async SQLite connection"""
        return aiosqlite.connect(self.db_path)

    async def _initialize_tables(self):
        """Initialize database tables if they don't exist"""
        async with await self._get_connection() as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS weather_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    city TEXT NOT NULL,
                    city_display TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    timestamp_epoch INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    storage_path TEXT,
                    error_message TEXT,
                    response_time_ms INTEGER,
                    cached BOOLEAN DEFAULT FALSE,
                    external_api_called BOOLEAN DEFAULT TRUE,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_city_timestamp ON weather_events(city, timestamp_epoch DESC)
                """
            )
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_timestamp_epoch ON weather_events(timestamp_epoch)
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_status ON weather_events(status)"
            )

            await db.commit()

    async def log_weather_request(
        self,
        city: str,
        timestamp: datetime,
        storage_path: str,
        success: bool = True,
        error_message: str | None = None,
    ) -> str:
        """Log a weather API request event to SQLite"""
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
            await self._initialize_tables()

            async with await self._get_connection() as db:
                await db.execute(
                    """
                    INSERT INTO weather_events (
                        event_id, event_type, city, city_display, timestamp,
                        timestamp_epoch, status, storage_path, error_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        EventType.WEATHER_REQUEST,
                        city.lower(),  # Normalized for querying
                        city,  # Original case for display
                        timestamp.isoformat(),
                        int(timestamp.timestamp()),
                        EventStatus.SUCCESS if success else EventStatus.FAILED,
                        storage_path,
                        error_message,
                    ),
                )
                await db.commit()

                self.logger.info(
                    "weather_request_logged",
                    event_id=event_id,
                    city=city,
                    success=success,
                )
                return event_id

        except Exception as e:
            self.logger.error(
                "sqlite_log_failed", event_id=event_id, city=city, error=str(e)
            )
            raise DatabaseError(
                f"Failed to log weather request to SQLite: {str(e)}"
            ) from e

    async def get_recent_requests(
        self, city: str | None = None, hours: int = 24, limit: int = 100
    ) -> list[dict]:
        """Get recent weather requests from SQLite"""
        if city:
            self._validate_city_name(city)

        self.logger.info("getting_recent_requests", city=city, hours=hours, limit=limit)

        try:
            await self._initialize_tables()

            cutoff_time = datetime.now() - timedelta(hours=hours)
            cutoff_epoch = int(cutoff_time.timestamp())

            async with await self._get_connection() as db:
                if city:
                    cursor = await db.execute(
                        """
                        SELECT event_id, event_type, city_display, timestamp, status,
                               storage_path, error_message, response_time_ms, cached,
                               external_api_called
                        FROM weather_events
                        WHERE city = ? AND timestamp_epoch >= ?
                        ORDER BY timestamp_epoch DESC
                        LIMIT ?
                        """,
                        (city.lower(), cutoff_epoch, limit),
                    )
                else:
                    cursor = await db.execute(
                        """
                        SELECT event_id, event_type, city_display, timestamp, status,
                               storage_path, error_message, response_time_ms, cached, external_api_called
                        FROM weather_events
                        WHERE timestamp_epoch >= ?
                        ORDER BY timestamp_epoch DESC
                        LIMIT ?
                        """,
                        (cutoff_epoch, limit),
                    )

                rows = await cursor.fetchall()

                results = []
                for row in rows:
                    result = {
                        "event_id": row[0],
                        "event_type": row[1],
                        "city": row[2],
                        "timestamp": row[3],
                        "status": row[4],
                        "storage_path": row[5],
                    }
                    if row[6]:  # error_message
                        result["error_message"] = row[6]
                    if row[7]:  # response_time_ms
                        result["response_time_ms"] = row[7]
                    result["cached"] = bool(row[8]) if row[8] is not None else False
                    result["external_api_called"] = (
                        bool(row[9]) if row[9] is not None else True
                    )

                    results.append(result)

                self.logger.info(
                    "recent_requests_retrieved", city=city, count=len(results)
                )
                return results

        except Exception as e:
            self.logger.error("get_recent_requests_failed", city=city, error=str(e))
            raise DatabaseError(
                f"Failed to get recent requests from SQLite: {str(e)}"
            ) from e

    async def get_request_stats(self, hours: int = 24) -> dict:
        """Get request statistics from SQLite"""
        self.logger.info("getting_request_stats", hours=hours)

        try:
            await self._initialize_tables()

            cutoff_time = datetime.now() - timedelta(hours=hours)
            cutoff_epoch = int(cutoff_time.timestamp())

            async with await self._get_connection() as db:
                cursor = await db.execute(
                    """
                    SELECT
                        COUNT(*) as total_requests,
                        SUM(CASE WHEN status = ? THEN 1 ELSE 0 END) as successful_requests,
                        SUM(CASE WHEN status = ? THEN 1 ELSE 0 END) as failed_requests,
                        SUM(CASE WHEN cached = 1 THEN 1 ELSE 0 END) as cache_hits,
                        SUM(CASE WHEN cached = 0 THEN 1 ELSE 0 END) as cache_misses,
                        AVG(CASE WHEN response_time_ms IS NOT NULL THEN response_time_ms END) as avg_response_time
                    FROM weather_events
                    WHERE timestamp_epoch >= ?
                    """,
                    (EventStatus.SUCCESS, EventStatus.FAILED, cutoff_epoch),
                )

                row = await cursor.fetchone()
                total_requests = row[0] or 0
                successful_requests = row[1] or 0
                failed_requests = row[2] or 0
                cache_hits = row[3] or 0
                cache_misses = row[4] or 0
                avg_response_time = row[5]

                cursor = await db.execute(
                    """
                    SELECT city_display, COUNT(*) as request_count
                    FROM weather_events
                    WHERE timestamp_epoch >= ?
                    GROUP BY city_display
                    ORDER BY request_count DESC
                    LIMIT 10
                    """,
                    (cutoff_epoch,),
                )

                city_rows = await cursor.fetchall()
                most_requested_cities = [row[0] for row in city_rows]

                stats = {
                    "total_requests": total_requests,
                    "successful_requests": successful_requests,
                    "failed_requests": failed_requests,
                    "cache_hits": cache_hits,
                    "cache_misses": cache_misses,
                    "average_response_time_ms": avg_response_time,
                    "period_hours": hours,
                    "most_requested_cities": most_requested_cities,
                }

                self.logger.info(
                    "request_stats_retrieved",
                    stats={
                        "total_requests": total_requests,
                        "successful_requests": successful_requests,
                        "failed_requests": failed_requests,
                        "cache_hits": cache_hits,
                        "cache_misses": cache_misses,
                    },
                )
                return stats

        except Exception as e:
            self.logger.error("get_request_stats_failed", error=str(e))
            raise DatabaseError(
                f"Failed to get request stats from SQLite: {str(e)}"
            ) from e

    async def cleanup_old_records(self, days: int = 30) -> int:
        """Remove old records from SQLite"""
        self.logger.info("starting_cleanup", days=days)

        try:
            await self._initialize_tables()

            cutoff_time = datetime.now() - timedelta(days=days)
            cutoff_epoch = int(cutoff_time.timestamp())

            async with await self._get_connection() as db:
                cursor = await db.execute(
                    "DELETE FROM weather_events WHERE timestamp_epoch < ?",
                    (cutoff_epoch,),
                )

                deleted_count = cursor.rowcount
                await db.commit()

                self.logger.info("cleanup_completed", deleted_count=deleted_count)
                return deleted_count

        except Exception as e:
            self.logger.error("cleanup_failed", error=str(e))
            raise DatabaseError(
                f"Failed to cleanup old records in SQLite: {str(e)}"
            ) from e

    async def health_check(self) -> bool:
        """Check if SQLite database is accessible"""
        try:
            async with await self._get_connection() as db:
                cursor = await db.execute("SELECT 1")
                result = await cursor.fetchone()
                is_healthy = result is not None

                self.logger.info("health_check_completed", is_healthy=is_healthy)
                return is_healthy

        except Exception as e:
            self.logger.error("health_check_failed", error=str(e))
            return False

    async def log_event_with_details(
        self,
        event: WeatherRequestEvent,
    ) -> str:
        """Log a detailed event with all fields (utility method)"""
        try:
            await self._initialize_tables()

            async with await self._get_connection() as db:
                await db.execute(
                    """
                    INSERT INTO weather_events (
                        event_id, event_type, city, city_display, timestamp,
                        timestamp_epoch, status, storage_path, error_message,
                        response_time_ms, cached, external_api_called
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id or str(uuid.uuid4()),
                        event.event_type,
                        event.city.lower(),
                        event.city,
                        event.timestamp.isoformat(),
                        int(event.timestamp.timestamp()),
                        event.status,
                        event.storage_path,
                        event.error_message,
                        event.response_time_ms,
                        event.cached,
                        event.external_api_called,
                    ),
                )
                await db.commit()
                return event.event_id or str(uuid.uuid4())

        except Exception as e:
            raise DatabaseError(
                f"Failed to log detailed event to SQLite: {str(e)}"
            ) from e

    async def get_database_info(self) -> dict:
        """Get database information (utility method)"""
        try:
            await self._initialize_tables()

            async with await self._get_connection() as db:
                cursor = await db.execute("SELECT COUNT(*) FROM weather_events")
                total_records = (await cursor.fetchone())[0]

                db_file = Path(self.db_path)
                file_size = db_file.stat().st_size if db_file.exists() else 0

                return {
                    "database_path": str(self.db_path),
                    "total_records": total_records,
                    "file_size_bytes": file_size,
                    "file_size_mb": round(file_size / (1024 * 1024), 2),
                }

        except Exception as e:
            raise DatabaseError(f"Failed to get database info: {str(e)}") from e

    def _validate_city_name(self, city: str) -> None:
        """Validate city name input"""
        if not city or not city.strip():
            raise ValueError("City name cannot be empty")

        if len(city.strip()) > 100:
            raise ValueError("City name too long (max 100 characters)")

        if re.search(r'[<>"\\]', city):
            raise ValueError("City name contains invalid characters")

    def _validate_timestamp(self, timestamp: datetime) -> None:
        """Validate timestamp input"""
        now = datetime.now()

        if timestamp > now + timedelta(hours=1):
            raise ValueError("Timestamp cannot be more than 1 hour in the future")

        if timestamp < now - timedelta(days=365):
            raise ValueError("Timestamp cannot be more than 1 year in the past")
