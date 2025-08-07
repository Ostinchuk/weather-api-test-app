"""Database provider factory for creating appropriate database implementations"""

from typing import TYPE_CHECKING

from app.config.settings import settings
from app.utils.exceptions import ConfigurationError

if TYPE_CHECKING:
    from .base import DatabaseProvider


def create_database_provider() -> "DatabaseProvider":
    """Create and return the appropriate database provider based on configuration"""
    if settings.use_aws_services:
        if not settings.aws_region:
            raise ConfigurationError("aws_region is required when using AWS services")

        if not settings.dynamodb_table_name:
            raise ConfigurationError(
                "dynamodb_table_name is required when using AWS services"
            )

        try:
            from .dynamodb import DynamoDBProvider

            return DynamoDBProvider()
        except ImportError as e:
            raise ConfigurationError(
                "aioboto3 is required for AWS DynamoDB support. "
                "Install with: pip install aioboto3"
            ) from e

    elif settings.use_local_services:
        if not settings.local_db_path:
            raise ConfigurationError(
                "local_db_path is required when using local services"
            )

        try:
            from .local_db import LocalDatabaseProvider

            return LocalDatabaseProvider()
        except ImportError as e:
            raise ConfigurationError(
                "aiosqlite is required for local database support. "
                "Install with: pip install aiosqlite"
            ) from e

    else:
        raise ConfigurationError(
            f"Invalid provider_mode: {settings.provider_mode}. "
            "Must be 'aws' or 'local'"
        )


# Global database provider instance
_database_provider: "DatabaseProvider | None" = None


def get_database_provider() -> "DatabaseProvider":
    """Get the global database provider instance (singleton pattern)"""
    global _database_provider

    if _database_provider is None:
        _database_provider = create_database_provider()

    return _database_provider


def reset_database_provider():
    """Reset the global database provider (useful for testing)"""
    global _database_provider
    _database_provider = None
