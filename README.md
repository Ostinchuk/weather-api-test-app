# Weather API Service

A high-performance FastAPI weather service with async operations, caching, and dual storage support (AWS/local).

## Features

- **FastAPI** with async/await throughout
- **5-minute caching** with automatic expiration
- **Dual storage modes**: AWS (S3/DynamoDB) or Local (file/SQLite)

## Quick Start

### Prerequisites

- Python 3.12
- Poetry (recommended) or pip
- OpenWeatherMap API key

### Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd weather-api-test-app
```

2. Install dependencies:
```bash
# With Poetry (recommended)
make install-local    # For local storage only
make install-all      # For both AWS and local storage

# Or with pip
pip install -e ".[local]"
```

3. Set up environment:
```bash
make setup-local-env
# Edit .env file with your OpenWeatherMap API key
```

4. Configure your API key in `.env`:
```bash
WEATHER_API_KEY=your_actual_openweathermap_api_key
AWS_ACCESS_KEY_ID=your_aws_key_id  # optional, required for AWS mode
AWS_SECRET_ACCESS_KEY=your_aws_access_key  # optional, required for AWS mode
```

### Running the Service

**Development mode:**
```bash
make run
# or
poetry run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Docker:**
```bash
make docker-run
# or
docker-compose up
```

## API Usage

### Get Weather Data
```bash
# Get current weather for a city
curl "http://localhost:8000/api/v1/weather?city=Madrid"

# Response includes cached flag and external API call status
{
   "weather_data":{
      "city":"Madrid",
      "temperature":37.27,
      "description":"clear sky",
      "humidity":13,
      "pressure":1014.0,
      "wind_speed":2.68,
      "wind_direction":239,
      "visibility":10.0,
      "timestamp":"2025-08-07T14:51:33.354334Z",
      "source":"openweathermap"
   },
   "metadata":{
      "cache_hit":false,
      "cache_age_seconds":0,
      "storage_path":"/app/data/weather_files/madrid_20250807_145133.json",
      "event_id":"fe7723aa-519d-4c9f-8d2e-3415bb9dec92"
   }
}
```

### Health Checks
```bash
# Basic health check
curl "http://localhost:8000/api/v1/health"

# Detailed readiness check
curl "http://localhost:8000/api/v1/health/ready"
```

### Service Info
```bash
curl "http://localhost:8000/"
```

## Configuration

The service supports two provider modes via the `PROVIDER_MODE` environment variable:

- **`local`**: Uses local file storage and SQLite database
- **`aws`**: Uses AWS S3 and DynamoDB

Key environment variables:
- `WEATHER_API_KEY`: Your OpenWeatherMap API key (required)
- `PROVIDER_MODE`: Storage provider mode (`local` or `aws`)
- `AWS_ACCESS_KEY_ID`: AWS access key (optional, required for AWS mode)
- `AWS_SECRET_ACCESS_KEY`: AWS secret key (optional, required for AWS mode)

See `.env.example` for complete configuration options.

## Development

### Testing
```bash
make test
```

### Project Structure
```
app/
├── api/           # API routes and endpoints
├── config/        # Configuration and settings
├── models/        # Pydantic data models
├── providers/     # Storage and database providers
├── services/      # Business logic services
└── utils/         # Utilities and exceptions
```

## Caching Strategy

- Weather data is cached for 5 minutes per city
- Cache hits return stored data without external API calls
- Expired cache entries trigger fresh API requests
- Cache status is included in API responses
