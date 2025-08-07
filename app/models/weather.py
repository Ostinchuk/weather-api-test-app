from datetime import datetime

from pydantic import BaseModel, Field


class WeatherData(BaseModel):
    """Weather data model"""

    city: str = Field(..., description="City name")
    temperature: float = Field(..., description="Temperature in Celsius")
    description: str = Field(..., description="Weather description")
    humidity: int = Field(..., ge=0, le=100, description="Humidity percentage")
    pressure: float = Field(..., description="Atmospheric pressure in hPa")
    wind_speed: float = Field(..., ge=0, description="Wind speed in m/s")
    wind_direction: int | None = Field(
        None, ge=0, le=360, description="Wind direction in degrees"
    )
    visibility: float | None = Field(None, ge=0, description="Visibility in km")
    timestamp: datetime = Field(..., description="When the data was fetched")
    source: str = Field(..., description="Source API (e.g., 'openweathermap')")

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class WeatherRequest(BaseModel):
    """Weather API request model"""

    city: str = Field(
        ..., min_length=1, max_length=100, description="City name to fetch weather for"
    )

    class Config:
        str_strip_whitespace = True


class WeatherResponse(BaseModel):
    """Weather API response model"""

    data: WeatherData = Field(..., description="Weather data")
    cached: bool = Field(..., description="Whether data was served from cache")
    cache_age_seconds: int | None = Field(
        None, description="Age of cached data in seconds"
    )

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}
