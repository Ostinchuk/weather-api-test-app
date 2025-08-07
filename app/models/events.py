from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EventType(str, Enum):
    """Types of events that can be logged"""

    WEATHER_REQUEST = "weather_request"
    CACHE_HIT = "cache_hit"
    CACHE_MISS = "cache_miss"
    API_ERROR = "api_error"
    STORAGE_ERROR = "storage_error"
    DATABASE_ERROR = "database_error"


class EventStatus(str, Enum):
    """Status of an event"""

    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"


class WeatherRequestEvent(BaseModel):
    """Model for logging weather request events"""

    event_id: str | None = Field(None, description="Unique event identifier")
    event_type: EventType = Field(..., description="Type of event")
    city: str = Field(..., description="City name requested")
    timestamp: datetime = Field(..., description="When the event occurred")
    status: EventStatus = Field(..., description="Event status")
    storage_path: str | None = Field(None, description="Path where data is stored")
    error_message: str | None = Field(None, description="Error message if failed")
    response_time_ms: int | None = Field(
        None, ge=0, description="Response time in milliseconds"
    )
    cached: bool = Field(False, description="Whether response was served from cache")
    external_api_called: bool = Field(
        True, description="Whether external API was called"
    )

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class EventData(BaseModel):
    """Generic event data model used by the weather service"""
    
    event_id: str | None = Field(None, description="Unique event identifier")
    event_type: EventType = Field(..., description="Type of event")
    city: str = Field(..., description="City name")
    timestamp: datetime = Field(..., description="Event timestamp")
    status: EventStatus = Field(default=EventStatus.PENDING, description="Event status")
    storage_path: str | None = Field(None, description="Storage path for data")
    error_message: str | None = Field(None, description="Error message if failed")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    
    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class RequestStats(BaseModel):
    """Statistics model for request analytics"""

    total_requests: int = Field(..., ge=0, description="Total number of requests")
    successful_requests: int = Field(
        ..., ge=0, description="Number of successful requests"
    )
    failed_requests: int = Field(..., ge=0, description="Number of failed requests")
    cache_hits: int = Field(..., ge=0, description="Number of cache hits")
    cache_misses: int = Field(..., ge=0, description="Number of cache misses")
    average_response_time_ms: float | None = Field(
        None, ge=0, description="Average response time"
    )
    period_hours: int = Field(..., ge=1, description="Time period for these stats")
    most_requested_cities: list[str] = Field(
        default_factory=list, description="Most frequently requested cities"
    )

    @property
    def success_rate(self) -> float:
        """Calculate success rate percentage"""
        if self.total_requests == 0:
            return 0.0
        return (self.successful_requests / self.total_requests) * 100

    @property
    def cache_hit_rate(self) -> float:
        """Calculate cache hit rate percentage"""
        total_cache_operations = self.cache_hits + self.cache_misses
        if total_cache_operations == 0:
            return 0.0
        return (self.cache_hits / total_cache_operations) * 100
