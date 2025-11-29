from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from server.config import Config
from server.services.initializers import Initializer
from server.services.repository_registry import RepositoryRegistry

logger = logging.getLogger(__name__)


class DatastoreResetService:
    """Coordinates deletion of local registry + Qdrant storage."""

    def __init__(self, config: Config, registry: RepositoryRegistry, initializer: Initializer):
        self.config = config
        self.registry = registry
        self.initializer = initializer

    def describe_targets(self) -> Dict[str, object]:
        registry_path = self._registry_db_path()
        qdrant_storage = self._qdrant_storage_path()
        return {
            "allow_data_reset": self.config.ALLOW_DATA_RESET,
            "registry_db_path": str(registry_path) if registry_path else None,
            "registry_db_exists": registry_path.exists() if registry_path else False,
            "qdrant_storage_path": str(qdrant_storage) if qdrant_storage else None,
            "qdrant_storage_exists": qdrant_storage.exists() if qdrant_storage else False,
            "host_repo_path": str(self.config.HOST_REPO_PATH) if self.config.HOST_REPO_PATH else None,
            "registry_collections": self._registry_collections(),
            "qdrant_url": self.config.QDRANT_URL,
        }

    def reset(self) -> Dict[str, object]:
        collections = self._registry_collections()
        registry_result = self._reset_registry_db()
        qdrant_result = self._reset_qdrant(collections)
        if registry_result.get("removed"):
            try:
                self.registry.reinitialize()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to reinitialize registry after reset: %s", exc)
        try:
            self.initializer.reset()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to reset initializer after datastore reset: %s", exc)
        return {
            "registry_db": registry_result,
            "qdrant": qdrant_result,
        }

    def _registry_db_path(self) -> Optional[Path]:
        if self.registry.db_path:
            return Path(self.registry.db_path)
        return self.config.REGISTRY_DB_PATH

    def _qdrant_storage_path(self) -> Optional[Path]:
        return self.config.QDRANT_STORAGE_PATH

    def _registry_collections(self) -> List[str]:
        entries = self.registry.list_repositories(include_archived=True)
        names = {entry.collection_name for entry in entries if entry.collection_name}
        return sorted(names)

    def _reset_registry_db(self) -> Dict[str, object]:
        path = self._registry_db_path()
        result: Dict[str, object] = {
            "path": str(path) if path else None,
            "removed": False,
        }
        if not path:
            result["status"] = "skipped"
            result["message"] = "Registry DB path not available."
            return result
        if not path.exists():
            result["status"] = "skipped"
            result["message"] = "Registry DB missing; treated as already removed."
            return result
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            result["removed"] = True
            result["status"] = "removed"
            logger.info("Removed registry DB at %s", path)
        except Exception as exc:  # noqa: BLE001
            result["status"] = "failed"
            result["message"] = str(exc)
            logger.error("Failed to remove registry DB at %s: %s", path, exc)
        return result

    def _reset_qdrant(self, collections: List[str]) -> Dict[str, object]:
        result: Dict[str, object] = {
            "url": self.config.QDRANT_URL,
            "target_collections": collections,
            "dropped": [],
            "failed": {},
        }
        client = None
        try:
            client = self.initializer._qdrant()
        except Exception as exc:  # noqa: BLE001
            result["connect_error"] = str(exc)
            logger.warning("Could not connect to Qdrant for reset: %s", exc)
        if client:
            for name in collections:
                try:
                    client.delete_collection(collection_name=name)
                    result["dropped"].append(name)
                    logger.info("Dropped Qdrant collection %s", name)
                except Exception as exc:  # noqa: BLE001
                    result["failed"][name] = str(exc)
                    logger.warning("Failed to drop collection %s: %s", name, exc)
        storage_path, storage_removed, storage_message = self._clear_qdrant_storage()
        result["storage_path"] = storage_path
        result["storage_removed"] = storage_removed
        if storage_message:
            result["storage_message"] = storage_message
        return result

    def _clear_qdrant_storage(self) -> Tuple[Optional[str], bool, Optional[str]]:
        path = self._qdrant_storage_path()
        if not path:
            return None, False, "Qdrant storage path not configured; skipping filesystem wipe."
        resolved = path.expanduser()
        path_str = str(resolved)
        if not resolved.exists():
            return path_str, False, "Storage path missing; nothing to delete."
        if not resolved.is_dir():
            return path_str, False, "Storage path is not a directory."
        if self.config.HOST_REPO_PATH:
            try:
                resolved.resolve().relative_to(self.config.HOST_REPO_PATH.resolve())
            except Exception:  # noqa: BLE001
                return path_str, False, "Storage path is outside HOST_REPO_PATH; skipping."
        try:
            shutil.rmtree(resolved, ignore_errors=False)
        except FileNotFoundError:
            logger.info("Qdrant storage path %s already cleared.", resolved)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to clear Qdrant storage at %s: %s", resolved, exc)
            return path_str, False, str(exc)
        try:
            resolved.mkdir(parents=True, exist_ok=True)
            logger.info("Cleared Qdrant storage at %s", resolved)
            return path_str, True, None
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to clear Qdrant storage at %s: %s", resolved, exc)
            return path_str, False, str(exc)
