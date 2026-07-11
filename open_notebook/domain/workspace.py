from typing import Any, ClassVar, Dict

from open_notebook.database.repository import ensure_record_id
from open_notebook.domain.base import ObjectModel


class Workspace(ObjectModel):
    table_name: ClassVar[str] = "workspace"
    name: str
    slug: str
    kind: str  # "personal" | "company"
    owner: str  # "user:<id>" record link

    def _prepare_save_data(self) -> Dict[str, Any]:
        data = super()._prepare_save_data()
        if data.get("owner") is not None:
            data["owner"] = ensure_record_id(data["owner"])
        return data


class Membership(ObjectModel):
    table_name: ClassVar[str] = "membership"
    user: str  # "user:<id>" record link
    workspace: str  # "workspace:<id>" record link
    role: str  # owner | admin | member
    status: str = "active"  # active | invited | revoked

    def _prepare_save_data(self) -> Dict[str, Any]:
        data = super()._prepare_save_data()
        if data.get("user") is not None:
            data["user"] = ensure_record_id(data["user"])
        if data.get("workspace") is not None:
            data["workspace"] = ensure_record_id(data["workspace"])
        return data
