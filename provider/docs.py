from collections.abc import Mapping
from typing import Any

from dify_plugin.interfaces.datasource import DatasourceProvider


class DocsDatasourceProvider(DatasourceProvider):
    def _validate_credentials(self, credentials: Mapping[str, Any]) -> None:
        # Public documentation sites need no credentials. Optional user_agent only.
        return None
