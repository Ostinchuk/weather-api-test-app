import logging
import sys
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.config.settings import Settings, settings
from app.services.weather_service import create_weather_service
from app.utils.exceptions import WeatherServiceError


def setup_logging(settings_obj: Settings) -> None:
    """Configure structured logging for the application."""

    log_level = getattr(logging, settings_obj.log_level.upper())

    if settings_obj.log_format == "json":
        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.stdlib.filter_by_level,
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.processors.StackInfoRenderer(),
                structlog.dev.ConsoleRenderer()
                if settings_obj.is_development
                else structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            logger_factory=structlog.stdlib.LoggerFactory(),
            context_class=dict,
            cache_logger_on_first_use=True,
        )
    else:
        # Console format for development
        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.stdlib.filter_by_level,
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.processors.StackInfoRenderer(),
                structlog.dev.ConsoleRenderer(),
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            logger_factory=structlog.stdlib.LoggerFactory(),
            context_class=dict,
            cache_logger_on_first_use=True,
        )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Manage application lifespan - startup and shutdown events.

    This context manager ensures proper initialization and cleanup
    of the weather service and its components.
    """
    logger = structlog.get_logger(__name__)

    logger.info("Starting Weather API service", version=settings.app_version)

    try:
        weather_service = await create_weather_service(settings)
        app.state.weather_service = weather_service

        logger.info("Weather service initialized successfully")

        health_status = await weather_service.health_check()
        if health_status["service"] != "healthy":
            logger.warning("Service startup health check failed", status=health_status)
        else:
            logger.info("Service startup health check passed")

    except Exception as e:
        logger.error(
            "Failed to initialize weather service during startup", error=str(e)
        )
        raise

    yield  # Application is running

    logger.info("Shutting down Weather API service")

    try:
        if hasattr(app.state, "weather_service"):
            await app.state.weather_service.cleanup()
        logger.info("Weather service cleanup completed")
    except Exception as e:
        logger.error("Error during service cleanup", error=str(e))


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.

    Returns:
        Configured FastAPI application instance
    """

    setup_logging(settings)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="A high-performance weather API service with caching and AWS integration",
        docs_url="/docs" if settings.is_development else None,
        redoc_url="/redoc" if settings.is_development else None,
        lifespan=lifespan,
    )

    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["*"] if settings.is_development else ["localhost", "127.0.0.1"],
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.is_development else ["https://yourdomain.com"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def logging_middleware(request: Request, call_next) -> Response:
        """Log requests and add processing time headers."""
        logger = structlog.get_logger(__name__)

        start_time = time.time()
        request_id = f"req_{int(start_time * 1000000)}"

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            client_ip=request.client.host if request.client else None,
        )

        logger.info("Request started")

        try:
            response = await call_next(request)

            process_time = time.time() - start_time
            response.headers["X-Process-Time"] = str(process_time)
            response.headers["X-Request-ID"] = request_id

            logger.info(
                "Request completed",
                status_code=response.status_code,
                process_time=process_time,
            )

            return response

        except Exception as e:
            process_time = time.time() - start_time
            logger.error(
                "Request failed",
                error=str(e),
                error_type=type(e).__name__,
                process_time=process_time,
            )
            raise

    @app.exception_handler(WeatherServiceError)
    async def weather_service_error_handler(
        _request: Request, exc: WeatherServiceError
    ) -> JSONResponse:
        """Handle weather service specific errors."""
        logger = structlog.get_logger(__name__)
        logger.error(
            "Weather service error", error=str(exc), error_type=type(exc).__name__
        )

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.error_code,
                "message": str(exc),
                "details": exc.details if hasattr(exc, "details") else None,
            },
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(
        _request: Request, exc: Exception
    ) -> JSONResponse:
        """Handle unexpected errors gracefully."""
        logger = structlog.get_logger(__name__)
        logger.error(
            "Unhandled exception", error=str(exc), error_type=type(exc).__name__
        )

        return JSONResponse(
            status_code=500,
            content={
                "error": "INTERNAL_SERVER_ERROR",
                "message": "An internal server error occurred",
                "details": str(exc) if settings.is_development else None,
            },
        )

    app.include_router(router, prefix="/api/v1")

    @app.get("/")
    async def root() -> dict[str, str]:
        """Root endpoint providing basic service information."""
        return {
            "service": settings.app_name,
            "version": settings.app_version,
            "status": "running",
            "docs": "/docs" if settings.is_development else "disabled",
        }

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        workers=settings.workers,
        reload=settings.is_development,
        log_level=settings.log_level.lower(),
    )
