# Weather API Testing Commands

This document contains CURL commands for testing the weather API with local database and storage providers.

## Base URL
All commands assume the API is running on `http://localhost:8000/api/v1`

## 1. Weather Data Endpoints

### Get Weather Data for a City
Test basic weather functionality with local storage and database logging:

```bash
# Test with Kyiv
curl -X GET "http://localhost:8000/api/v1/weather?city=Kyiv"

# Test with London
curl -X GET "http://localhost:8000/api/v1/weather?city=London"

# Test with New York (space in name)
curl -X GET "http://localhost:8000/api/v1/weather?city=New%20York"

# Test with Tokyo
curl -X GET "http://localhost:8000/api/v1/weather?city=Tokyo"

# Test with Berlin
curl -X GET "http://localhost:8000/api/v1/weather?city=Berlin"
```

### Test Caching Behavior
Run the same request twice within 5 minutes to test cache functionality:

```bash
# First request (cache miss)
curl -X GET "http://localhost:8000/api/v1/weather?city=Paris"

# Second request within 5 minutes (should be cache hit)
curl -X GET "http://localhost:8000/api/v1/weather?city=Paris"
```

### Test Error Handling

```bash
# Invalid city name (empty)
curl -X GET "http://localhost:8000/api/v1/weather?city="

# Invalid city name (too long)
curl -X GET "http://localhost:8000/api/v1/weather?city=$(python3 -c 'print("A" * 200)')"

# Non-existent city
curl -X GET "http://localhost:8000/api/v1/weather?city=NonexistentCity12345"

# Missing city parameter
curl -X GET "http://localhost:8000/api/v1/weather"
```

## 2. Health Check Endpoints

### Full Health Check
Comprehensive health check of all components including database and storage:

```bash
curl -X GET "http://localhost:8000/api/v1/health"
```

### Readiness Check
Simple readiness probe for container orchestration:

```bash
curl -X GET "http://localhost:8000/api/v1/health/ready"
```

## 3. Cache Management Endpoints

### Get Cache Statistics
View current cache configuration and statistics:

```bash
curl -X GET "http://localhost:8000/api/v1/cache/stats"
```

### Invalidate Expired Cache Entries
Manually trigger cleanup of expired cache entries:

```bash
curl -X POST "http://localhost:8000/api/v1/cache/invalidate"
```

## 4. Testing Local Storage

### Verify File Storage
After making weather requests, check that files are stored locally:

```bash
# List weather data files
ls -la data/weather_files/

# View a specific weather data file
cat data/weather_files/kyiv_*.json
```

### Check Cache Files
If using local file cache provider, check cache files:

```bash
# List cache files (if using LocalFileStorageProvider for cache)
ls -la data/cache/

# View cache file content
cat data/cache/weather_*.json
```

## 5. Testing Local Database

### Check SQLite Database
Verify that events are being logged to the local SQLite database:

```bash
# Check if database file exists
ls -la data/local_db.sqlite

# Query database directly (requires sqlite3 command)
sqlite3 data/local_db.sqlite "SELECT * FROM weather_events ORDER BY timestamp_epoch DESC LIMIT 10;"

# Count total events
sqlite3 data/local_db.sqlite "SELECT COUNT(*) as total_events FROM weather_events;"

# Check events by city
sqlite3 data/local_db.sqlite "SELECT city_display, COUNT(*) as count FROM weather_events GROUP BY city_display ORDER BY count DESC;"

# Check recent events (last hour)
sqlite3 data/local_db.sqlite "SELECT event_id, city_display, status, timestamp FROM weather_events WHERE timestamp_epoch > strftime('%s', 'now') - 3600 ORDER BY timestamp_epoch DESC;"
```

## 6. Performance Testing

### Load Testing
Test multiple concurrent requests:

```bash
# Run 10 parallel requests for different cities
for city in "London" "Paris" "Berlin" "Madrid" "Rome" "Vienna" "Prague" "Warsaw" "Stockholm" "Oslo"; do
    curl -X GET "http://localhost:8000/api/v1/weather?city=$city" &
done
wait
```

### Rate Limit Testing
Test API rate limiting (if implemented):

```bash
# Rapid fire requests
for i in {1..20}; do
    echo "Request $i"
    curl -X GET "http://localhost:8000/api/v1/weather?city=TestCity$i"
    sleep 0.1
done
```

## 7. Data Validation Testing

### Test Response Format
Verify that responses contain expected fields:

```bash
# Get weather data and pipe through jq for formatted JSON
curl -s -X GET "http://localhost:8000/api/v1/weather?city=London" | jq '.'

# Check specific fields exist
curl -s -X GET "http://localhost:8000/api/v1/weather?city=London" | jq '.weather_data.temperature'
curl -s -X GET "http://localhost:8000/api/v1/weather?city=London" | jq '.metadata.event_id'
```

### Test Headers and Status Codes

```bash
# Get full response headers
curl -i -X GET "http://localhost:8000/api/v1/weather?city=London"

# Check only status code
curl -o /dev/null -s -w "%{http_code}\n" "http://localhost:8000/api/v1/weather?city=London"
```

## 8. Clean Up Commands

### Clear Cache Data

```bash
# Remove cache files
rm -rf data/cache/*

# Clear cache via API
curl -X POST "http://localhost:8000/api/v1/cache/invalidate"
```

### Clear Database (Caution!)

```bash
# Backup database before clearing
cp data/local_db.sqlite data/local_db.sqlite.backup

# Clear all events (use with caution)
sqlite3 data/local_db.sqlite "DELETE FROM weather_events;"
```

## 9. Monitoring and Logging

### Check Application Logs
Monitor application logs during testing:

```bash
# If running with uvicorn, logs will appear in the console
# For production deployments, check log files or use journalctl

# Example: tail logs if using file logging
tail -f logs/weather-api.log
```

### Monitor Storage Growth

```bash
# Check storage directory size
du -sh data/

# Count files
find data/weather_files -name "*.json" | wc -l

# Check database size
ls -lh data/local_db.sqlite
```

## Notes

- All timestamps in responses are in ISO 8601 format
- Weather data is cached for 5 minutes by default
- The local database logs all weather request events
- Storage files are named with city and timestamp: `{city}_{timestamp}.json`
- Cache hit/miss information is included in response metadata
- Event IDs are generated for each request for tracking purposes

## Expected Response Format

Successful weather request response:
```json
{
  "weather_data": {
    "city": "London",
    "temperature": 18.5,
    "description": "clear sky",
    "humidity": 65,
    "pressure": 1013.2,
    "wind_speed": 5.2,
    "wind_direction": 230,
    "visibility": 10.0,
    "timestamp": "2025-08-07T13:26:10.671810",
    "source": "openweathermap"
  },
  "metadata": {
    "cache_hit": false,
    "cache_age_seconds": 0,
    "storage_path": "data/weather_files/london_20250807_132610.json",
    "event_id": "7fc30260-07af-4dc5-8ba3-0414418dc0e2"
  }
}
```