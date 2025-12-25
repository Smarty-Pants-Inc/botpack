"""Stub Letta client interface for Botpack integration.

This module defines the interface for interacting with the Letta API.
The actual implementation is stubbed out to avoid network dependencies;
real implementations can be provided by injecting a concrete client.

Key design principles:
- No network calls in this stub implementation
- Interface is designed for dependency injection
- All methods return placeholder/error results by default
- Real client implementations should match this interface

Usage:
    # Default stub (offline, for testing/development)
    client = create_letta_client()

    # With real implementation (future)
    client = create_letta_client(config=LettaClientConfig(api_url="..."))
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from .models import (
    LettaBlock,
    LettaTemplate,
    LettaTool,
    LettaMcpServer,
    LettaFolder,
    LettaAgentConfig,
    LettaObservedState,
)


# ---------------------------------------------------------------------------
# Client configuration
# ---------------------------------------------------------------------------


@dataclass
class LettaClientConfig:
    """Configuration for connecting to a Letta server.

    Authentication can be provided via:
    1. Explicit api_key parameter
    2. Environment variable LETTA_API_KEY
    3. Local settings file (~/.letta/settings.local.json)

    Attributes:
        api_url: Base URL for the Letta API (default: http://localhost:8283)
        api_key: API key for authentication (optional, can use env var)
        agent_id: Default agent ID to operate on (optional)
        timeout: Request timeout in seconds
        verify_ssl: Whether to verify SSL certificates
    """

    api_url: str = "http://localhost:8283"
    api_key: str | None = None
    agent_id: str | None = None
    timeout: float = 30.0
    verify_ssl: bool = True

    @classmethod
    def from_env(cls) -> "LettaClientConfig":
        """Create config from environment variables.

        Environment variables:
        - LETTA_API_URL: API base URL
        - LETTA_API_KEY: API key
        - LETTA_AGENT_ID: Default agent ID
        """
        import os

        return cls(
            api_url=os.environ.get("LETTA_API_URL", "http://localhost:8283"),
            api_key=os.environ.get("LETTA_API_KEY"),
            agent_id=os.environ.get("LETTA_AGENT_ID"),
        )

    @classmethod
    def from_settings_file(cls, path: Path | None = None) -> "LettaClientConfig":
        """Load config from a settings file.

        Checks in order:
        1. Provided path
        2. .letta/settings.local.json (project-local)
        3. ~/.letta/settings.local.json (user-level)

        Args:
            path: Explicit path to settings file (optional)

        Returns:
            LettaClientConfig with values from file, falling back to defaults
        """
        import json
        import os

        # Determine path to check
        paths_to_check: list[Path] = []
        if path:
            paths_to_check.append(path)
        else:
            # Project-local settings
            cwd_settings = Path.cwd() / ".letta" / "settings.local.json"
            paths_to_check.append(cwd_settings)
            # User-level settings
            home_settings = Path.home() / ".letta" / "settings.local.json"
            paths_to_check.append(home_settings)

        # Try each path
        for p in paths_to_check:
            if p.exists():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    return cls(
                        api_url=data.get("api_url", "http://localhost:8283"),
                        api_key=data.get("api_key") or os.environ.get("LETTA_API_KEY"),
                        agent_id=data.get("agent_id") or os.environ.get("LETTA_AGENT_ID"),
                    )
                except (json.JSONDecodeError, OSError):
                    continue

        # Fall back to environment/defaults
        return cls.from_env()


# ---------------------------------------------------------------------------
# Client interface (abstract base class)
# ---------------------------------------------------------------------------


class LettaClient(ABC):
    """Abstract interface for Letta API operations.

    This defines the contract that client implementations must fulfill.
    The stub implementation returns offline/error results; real implementations
    would make actual API calls.

    All methods are designed to be non-blocking and return results or raise
    exceptions for error conditions.
    """

    @abstractmethod
    def get_observed_state(self, agent_id: str | None = None) -> LettaObservedState:
        """Fetch current state from Letta server.

        Retrieves all managed resource types for the specified agent
        (or default agent if none specified).

        Args:
            agent_id: Letta agent ID to query (optional, uses config default)

        Returns:
            LettaObservedState containing all discovered resources

        Raises:
            LettaClientError: On connection or API errors
        """
        ...

    # --- Block operations ---

    @abstractmethod
    def get_block(self, label: str, agent_id: str | None = None) -> LettaBlock | None:
        """Get a specific memory block by label.

        Args:
            label: Block label (e.g., "project")
            agent_id: Agent ID (optional)

        Returns:
            LettaBlock if found, None otherwise
        """
        ...

    @abstractmethod
    def create_block(self, block: LettaBlock, agent_id: str | None = None) -> LettaBlock:
        """Create a new memory block.

        Args:
            block: Block to create
            agent_id: Agent ID (optional)

        Returns:
            Created block with Letta ID populated

        Raises:
            LettaClientError: On creation failure
        """
        ...

    @abstractmethod
    def update_block(self, block: LettaBlock, agent_id: str | None = None) -> LettaBlock:
        """Update an existing memory block.

        Args:
            block: Block with updated values (must have letta_id)
            agent_id: Agent ID (optional)

        Returns:
            Updated block

        Raises:
            LettaClientError: On update failure
        """
        ...

    @abstractmethod
    def delete_block(self, label: str, agent_id: str | None = None) -> bool:
        """Delete a memory block.

        Args:
            label: Block label to delete
            agent_id: Agent ID (optional)

        Returns:
            True if deleted, False if not found
        """
        ...

    # --- Agent operations ---

    @abstractmethod
    def list_agents(self) -> list[LettaAgentConfig]:
        """List all agents accessible to this client.

        Returns:
            List of agent configurations
        """
        ...

    @abstractmethod
    def get_agent(self, agent_id: str) -> LettaAgentConfig | None:
        """Get agent configuration by ID.

        Args:
            agent_id: Letta agent ID

        Returns:
            Agent config if found, None otherwise
        """
        ...

    @abstractmethod
    def create_agent(self, agent: LettaAgentConfig) -> LettaAgentConfig:
        """Create a new agent.

        Args:
            agent: Agent configuration to create

        Returns:
            Created agent with Letta ID populated
        """
        ...

    # --- Template operations ---

    @abstractmethod
    def get_template(self, template_id: str) -> LettaTemplate | None:
        """Get agent template by ID."""
        ...

    @abstractmethod
    def list_templates(self) -> list[LettaTemplate]:
        """List all available templates."""
        ...

    # --- Connection management ---

    @abstractmethod
    def ping(self) -> bool:
        """Check if the Letta server is reachable.

        Returns:
            True if server responds, False otherwise
        """
        ...

    @property
    @abstractmethod
    def config(self) -> LettaClientConfig:
        """Get the client configuration."""
        ...


# ---------------------------------------------------------------------------
# Client errors
# ---------------------------------------------------------------------------


class LettaClientError(Exception):
    """Base exception for Letta client errors."""

    def __init__(self, message: str, cause: Exception | None = None):
        super().__init__(message)
        self.cause = cause


class LettaConnectionError(LettaClientError):
    """Raised when unable to connect to Letta server."""

    pass


class LettaAuthError(LettaClientError):
    """Raised when authentication fails."""

    pass


class LettaNotFoundError(LettaClientError):
    """Raised when a requested resource is not found."""

    pass


class LettaOfflineError(LettaClientError):
    """Raised when attempting network operations in offline mode."""

    pass


# ---------------------------------------------------------------------------
# Stub client implementation (offline)
# ---------------------------------------------------------------------------


class StubLettaClient(LettaClient):
    """Stub client that operates offline without network calls.

    This implementation is used for:
    - Testing without a Letta server
    - Development/offline mode
    - Validating managed state before deployment

    All read operations return empty results.
    All write operations raise LettaOfflineError.
    """

    def __init__(self, config: LettaClientConfig | None = None):
        self._config = config or LettaClientConfig()
        self._offline_msg = "Cannot perform operation: Letta client is in offline/stub mode"

    @property
    def config(self) -> LettaClientConfig:
        return self._config

    def get_observed_state(self, agent_id: str | None = None) -> LettaObservedState:
        """Return empty observed state (offline mode)."""
        return LettaObservedState(agent_id=agent_id or self._config.agent_id)

    def get_block(self, label: str, agent_id: str | None = None) -> LettaBlock | None:
        """Return None (offline mode)."""
        return None

    def create_block(self, block: LettaBlock, agent_id: str | None = None) -> LettaBlock:
        """Raise offline error."""
        raise LettaOfflineError(self._offline_msg)

    def update_block(self, block: LettaBlock, agent_id: str | None = None) -> LettaBlock:
        """Raise offline error."""
        raise LettaOfflineError(self._offline_msg)

    def delete_block(self, label: str, agent_id: str | None = None) -> bool:
        """Raise offline error."""
        raise LettaOfflineError(self._offline_msg)

    def list_agents(self) -> list[LettaAgentConfig]:
        """Return empty list (offline mode)."""
        return []

    def get_agent(self, agent_id: str) -> LettaAgentConfig | None:
        """Return None (offline mode)."""
        return None

    def create_agent(self, agent: LettaAgentConfig) -> LettaAgentConfig:
        """Raise offline error."""
        raise LettaOfflineError(self._offline_msg)

    def get_template(self, template_id: str) -> LettaTemplate | None:
        """Return None (offline mode)."""
        return None

    def list_templates(self) -> list[LettaTemplate]:
        """Return empty list (offline mode)."""
        return []

    def ping(self) -> bool:
        """Return False (offline mode)."""
        return False


# ---------------------------------------------------------------------------
# Factory function
# ---------------------------------------------------------------------------


def create_letta_client(
    config: LettaClientConfig | None = None,
    *,
    offline: bool = False,
) -> LettaClient:
    """Create a Letta client instance.

    By default, creates a stub client for offline operation.
    When a real client implementation is available, this factory
    will return it based on the configuration.

    Args:
        config: Client configuration (optional, loads from env/file if not provided)
        offline: Force offline/stub mode even if config is provided

    Returns:
        LettaClient instance (stub or real, depending on availability)

    Example:
        # Offline stub (default)
        client = create_letta_client()

        # With explicit config
        config = LettaClientConfig(api_url="http://letta.local:8283")
        client = create_letta_client(config)

        # From environment
        config = LettaClientConfig.from_env()
        client = create_letta_client(config)
    """
    if config is None:
        config = LettaClientConfig.from_env()

    if offline:
        return StubLettaClient(config)

    # TODO: When real client implementation is available, instantiate it here
    # For now, always return stub client
    # if config.api_key or config.api_url != "http://localhost:8283":
    #     return RealLettaClient(config)

    return StubLettaClient(config)
