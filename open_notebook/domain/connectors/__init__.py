from typing import Dict, List, Type

from open_notebook.domain.connectors.base import (
    BaseConnector,
    ConnectorItem,
    ImportedDoc,
    TokenSet,
)

# Adapters register themselves here as they are added (Tasks 3–5).
CONNECTOR_REGISTRY: Dict[str, Type[BaseConnector]] = {}

COMING_SOON: List[dict] = [
    {"provider": "sharepoint", "display_name": "SharePoint",
     "description": "Microsoft 365 SharePoint and OneDrive for Business"},
    {"provider": "box", "display_name": "Box",
     "description": "Enterprise content management with folder permissions"},
    {"provider": "dropbox", "display_name": "Dropbox",
     "description": "Cloud storage with shared folder access"},
    {"provider": "confluence", "display_name": "Confluence",
     "description": "Wiki pages, blog posts, and attachments"},
    {"provider": "msteams", "display_name": "Microsoft Teams",
     "description": "Meeting transcripts, channels, wiki, and files"},
    {"provider": "gmail", "display_name": "Gmail",
     "description": "Your email — indexed only for you, not your teammates"},
    {"provider": "s3", "display_name": "S3 Bucket",
     "description": "Connect your S3 bucket via cross-account IAM role"},
]


def get_connector(provider: str) -> BaseConnector:
    cls = CONNECTOR_REGISTRY.get(provider)
    if cls is None:
        raise ValueError(f"Unknown or unsupported connector: {provider}")
    return cls()


def _register(cls: Type[BaseConnector]) -> None:
    CONNECTOR_REGISTRY[cls.provider] = cls


__all__ = [
    "BaseConnector", "ConnectorItem", "ImportedDoc", "TokenSet",
    "CONNECTOR_REGISTRY", "COMING_SOON", "get_connector", "_register",
]

# Import adapters for their registration side effects. Kept at the bottom to
# avoid a circular import (adapters import from this module).
from open_notebook.domain.connectors import gdrive  # noqa: E402,F401
