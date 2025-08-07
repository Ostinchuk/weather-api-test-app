"""Database providers for event logging and analytics"""

from .base import DatabaseProvider
from .factory import create_database_provider, get_database_provider, reset_database_provider

# Conditionally import providers based on available dependencies
try:
    from .dynamodb import DynamoDBProvider
except ImportError:
    DynamoDBProvider = None

try:
    from .local_db import LocalDatabaseProvider
except ImportError:
    LocalDatabaseProvider = None

__all__ = [
    "DatabaseProvider",
    "create_database_provider",
    "get_database_provider", 
    "reset_database_provider",
    "DynamoDBProvider",
    "LocalDatabaseProvider",
]