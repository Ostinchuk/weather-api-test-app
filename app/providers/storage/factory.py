import logging

from app.config.settings import Settings
from app.providers.storage.base import StorageProvider

logger = logging.getLogger(__name__)


def create_storage_provider(settings: Settings) -> StorageProvider:
    """Factory function to create the appropriate storage provider based on settings"""
    if settings.use_aws_services:
        try:
            from app.providers.storage.s3 import S3StorageProvider

            logger.info("Creating S3 storage provider")
            return S3StorageProvider(settings)

        except ImportError as e:
            logger.error(
                "AWS dependencies not installed. Install with: pip install boto3 aioboto3"
            )
            raise ImportError(
                "AWS dependencies not available. Install with: pip install boto3 aioboto3"
            ) from e

    elif settings.use_local_services:
        try:
            from app.providers.storage.local_file import LocalFileStorageProvider

            logger.info("Creating local file storage provider")
            return LocalFileStorageProvider(settings)

        except ImportError as e:
            logger.error(
                "Local file dependencies not installed. Install with: pip install aiofiles"
            )
            raise ImportError(
                "Local file dependencies not available. Install with: pip install aiofiles"
            ) from e
    else:
        raise ValueError(
            f"Unsupported provider mode: {settings.provider_mode}. "
            "Supported modes: 'aws', 'local'"
        )
