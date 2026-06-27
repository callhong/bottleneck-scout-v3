"""Shared data-source error taxonomy.

The taxonomy mirrors the behavior-oriented idea from TradingAgents while
keeping this skill independent from that project.
"""

from __future__ import annotations


class DataSourceError(Exception):
    """Base class for conditions where a data source could not return usable data."""


class NoUsableDataError(DataSourceError):
    """The source responded but did not contain usable rows for the request."""

    def __init__(self, source: str, query: str, detail: str = ""):
        self.source = source
        self.query = query
        self.detail = detail
        message = f"{source} returned no usable data for {query!r}"
        if detail:
            message += f": {detail}"
        super().__init__(message)


class DataSourceRateLimitError(DataSourceError):
    """The source throttled or blocked the request."""


class DataSourceUnavailableError(DataSourceError):
    """The source is missing credentials, dependencies, or network availability."""
