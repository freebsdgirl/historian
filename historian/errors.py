"""Project-specific errors."""


class HistorianError(Exception):
    """Base Historian error."""


class ConfigError(HistorianError):
    """Invalid runtime configuration."""


class StorageError(HistorianError):
    """Persistent storage failure."""


class AuthenticationError(HistorianError):
    """Missing or invalid credentials."""


class AuthorizationError(HistorianError):
    """Authenticated caller lacks a required scope."""


class ValidationError(HistorianError):
    """Invalid manifest, schema, event, or query input."""


class ConflictError(HistorianError):
    """A durable identifier was reused with conflicting data."""


class ResolverError(HistorianError):
    """Local model request or output failure."""


class HistorianConnectionError(HistorianError):
    """The Historian server could not be reached (transport failure)."""


class QueryError(HistorianError):
    """Historian could not execute a query safely."""

