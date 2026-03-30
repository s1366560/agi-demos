"""Enums for the InstanceTemplate bounded context."""

from enum import Enum


class TemplateItemType(str, Enum):
    """Type of item included in an instance template."""

    gene = "gene"
    genome = "genome"
