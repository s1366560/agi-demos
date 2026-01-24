"""Enumerations for the application."""

from enum import Enum


class ProcessingStatus(str, Enum):
    """Status of memory processing."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class DataStatus(str, Enum):
    """Status of data availability."""

    ENABLED = "ENABLED"
    DISABLED = "DISABLED"
