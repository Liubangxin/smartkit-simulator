"""Persistent, one-file dataset workspace for SmartKit Simulator."""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from pathlib import Path


DATASET_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_WORKSPACE_LOCK = threading.RLock()


class WorkspaceError(ValueError):
    pass


class ConflictError(WorkspaceError):
    pass


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class DatasetWorkspace:
    """Hide directory layout, validation and atomic writes behind a small interface."""

    def __init__(self, app_data_dir):
        self.app_data_dir = Path(app_data_dir).resolve()
        self.settings_path = self.app_data_dir / "settings.json"

    @property
    def dataset_dir(self) -> Path:
        settings = self._read_json(self.settings_path, {})
        configured = settings.get("dataset_directory")
        return Path(configured).resolve() if configured else self.app_data_dir / "datasets"

    def switch_directory(self, path: str) -> dict:
        if not path or not str(path).strip():
            raise WorkspaceError("数据集目录不能为空")
        target = Path(path).expanduser().resolve()
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise WorkspaceError(f"无法创建数据集目录: {error}") from error
        if not target.is_dir():
            raise WorkspaceError("数据集目录不是有效目录")
        (target / ".smartkit").mkdir(exist_ok=True)
        settings = self._read_json(self.settings_path, {})
        settings["dataset_directory"] = str(target)
        _atomic_json(self.settings_path, settings)
        return {"path": str(target), **self.scan_summary()}

    def migrate_legacy(self, config_path) -> bool:
        settings = self._read_json(self.settings_path, {})
        if settings.get("legacy_migration_complete"):
            return False
        source = Path(config_path)
        migrated = False
        if source.is_file() and not any(self.dataset_dir.glob("*.json")):
            legacy = self._read_json(source, None)
            if isinstance(legacy, dict):
                dataset = {**legacy, "id": "legacy-default", "name": "迁移的默认数据集",
                           "description": "从 config.json 自动迁移"}
                self.create_dataset(dataset)
                migrated = True
        settings = self._read_json(self.settings_path, {})
        settings["legacy_migration_complete"] = True
        _atomic_json(self.settings_path, settings)
        return migrated

    def validate_directory(self, path: str) -> dict:
        if not path or not str(path).strip():
            raise WorkspaceError("数据集目录不能为空")
        target = Path(path).expanduser().resolve()
        if not target.is_dir():
            raise WorkspaceError("目录不存在或不可访问")
        valid = invalid = 0
        for dataset_file in target.glob("*.json"):
            try:
                dataset = self._read_json(dataset_file, None)
                if not isinstance(dataset, dict) or dataset.get("id") != dataset_file.stem:
                    raise WorkspaceError("文件名与数据集 ID 不一致")
                self._normalize_dataset(dataset, creating=False)
                valid += 1
            except (OSError, ValueError, json.JSONDecodeError):
                invalid += 1
        return {"status": "valid", "path": str(target),
                "dataset_count": valid, "invalid_count": invalid}

    def scan_summary(self) -> dict:
        valid = invalid = 0
        self.dataset_dir.mkdir(parents=True, exist_ok=True)
        for path in self.dataset_dir.glob("*.json"):
            try:
                self._load_dataset_path(path)
                valid += 1
            except (OSError, ValueError, json.JSONDecodeError):
                invalid += 1
        return {"dataset_count": valid, "invalid_count": invalid}

    def create_dataset(self, payload: dict) -> dict:
        with _WORKSPACE_LOCK:
            dataset = self._normalize_dataset(payload, creating=True)
            path = self._dataset_path(dataset["id"])
            if path.exists():
                raise ConflictError(f"数据集 {dataset['id']} 已存在")
            _atomic_json(path, dataset)
            return dataset

    def get_dataset(self, dataset_id: str) -> dict:
        path = self._dataset_path(dataset_id)
        if not path.exists():
            raise FileNotFoundError(dataset_id)
        return self._load_dataset_path(path)

    def update_dataset(self, dataset_id: str, payload: dict) -> dict:
        with _WORKSPACE_LOCK:
            current = self.get_dataset(dataset_id)
            if payload.get("id", dataset_id) != dataset_id:
                raise WorkspaceError("数据集 ID 创建后不可修改")
            try:
                supplied_revision = int(payload.get("revision"))
            except (TypeError, ValueError):
                raise WorkspaceError("保存数据集必须携带 revision") from None
            if supplied_revision != current["revision"]:
                raise ConflictError(
                    f"数据集已更新，当前 revision 为 {current['revision']}")
            updated = self._normalize_dataset({**payload, "id": dataset_id}, creating=False)
            updated["revision"] = current["revision"] + 1
            _atomic_json(self._dataset_path(dataset_id), updated)
            return updated

    def copy_dataset(self, source_id, target_id, name="") -> dict:
        source = self.get_dataset(source_id)
        copied = {**source, "id": str(target_id).strip(),
                  "name": str(name).strip() or f"{source['name']} 副本"}
        copied.pop("revision", None)
        return self.create_dataset(copied)

    def import_dataset(self, dataset) -> dict:
        if not isinstance(dataset, dict):
            raise WorkspaceError("dataset 必须是 JSON 对象")
        imported = dict(dataset)
        imported.pop("revision", None)
        return self.create_dataset(imported)

    def list_datasets(self, page, page_size, keyword="") -> dict:
        page = max(1, int(page))
        page_size = min(100, max(1, int(page_size)))
        needle = str(keyword).strip().casefold()
        items = []
        self.dataset_dir.mkdir(parents=True, exist_ok=True)
        for path in sorted(self.dataset_dir.glob("*.json"), key=lambda item: item.name.casefold()):
            try:
                dataset = self._load_dataset_path(path)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            searchable = " ".join(str(dataset.get(key, "")) for key in ("id", "name", "description")).casefold()
            if needle and needle not in searchable:
                continue
            items.append({"id": dataset["id"], "name": dataset["name"],
                          "description": dataset["description"], "revision": dataset["revision"],
                          "filename": path.name, "modified_at": path.stat().st_mtime,
                          "command_count": len(dataset["commands"]),
                          "route_count": len(dataset["rest_routes"])})
        total = len(items)
        start = (page - 1) * page_size
        return {"items": items[start:start + page_size], "page": page,
                "page_size": page_size, "total": total}

    def sync_cases(self, cases) -> dict:
        if not isinstance(cases, list):
            raise WorkspaceError("cases 必须是数组")
        normalized = {}
        for item in cases:
            if not isinstance(item, dict) or not str(item.get("case_id", "")).strip():
                raise WorkspaceError("每个测试用例都必须包含 case_id")
            case_id = str(item["case_id"]).strip()
            normalized[case_id] = {"case_id": case_id,
                                   "name": str(item.get("name") or case_id),
                                   "module": str(item.get("module") or "")}
        _atomic_json(self._metadata_path("case-catalog.json"),
                     {"cases": sorted(normalized.values(), key=lambda item: item["case_id"])})
        return {"status": "ok", "total": len(normalized)}

    def list_cases(self, page, page_size, keyword="", module="", binding_status="") -> dict:
        bindings = self._bindings()
        cases = self._read_json(self._metadata_path("case-catalog.json"), {"cases": []}).get("cases", [])
        needle = str(keyword).strip().casefold()
        items = []
        for item in cases:
            bound = item["case_id"] in bindings
            if needle and needle not in f"{item['case_id']} {item.get('name', '')}".casefold():
                continue
            if module and item.get("module") != module:
                continue
            if binding_status == "bound" and not bound or binding_status == "unbound" and bound:
                continue
            items.append({**item, "dataset_id": bindings.get(item["case_id"])})
        return self._page(items, page, page_size)

    def bind_case(self, case_id, dataset_id) -> dict:
        case_id = str(case_id).strip()
        if not case_id:
            raise WorkspaceError("case_id 不能为空")
        with _WORKSPACE_LOCK:
            self.get_dataset(dataset_id)
            bindings = self._bindings()
            bindings[case_id] = dataset_id
            self._save_bindings(bindings)
        return {"case_id": case_id, "dataset_id": dataset_id}

    def unbind_case(self, case_id) -> bool:
        bindings = self._bindings()
        existed = bindings.pop(case_id, None) is not None
        if existed:
            self._save_bindings(bindings)
        return existed

    def import_bindings(self, items) -> dict:
        if not isinstance(items, list):
            raise WorkspaceError("bindings 必须是数组")
        updates = {}
        for item in items:
            if not isinstance(item, dict):
                raise WorkspaceError("每条绑定必须是 JSON 对象")
            case_id = str(item.get("case_id", "")).strip()
            dataset_id = str(item.get("dataset_id", "")).strip()
            if not case_id:
                raise WorkspaceError("case_id 不能为空")
            self.get_dataset(dataset_id)
            updates[case_id] = dataset_id
        bindings = self._bindings()
        bindings.update(updates)
        self._save_bindings(bindings)
        return {"status": "ok", "imported": len(updates)}

    def list_bindings(self, page, page_size, dataset_id="", keyword="") -> dict:
        catalog = {item["case_id"]: item for item in
                   self._read_json(self._metadata_path("case-catalog.json"), {"cases": []}).get("cases", [])}
        needle = str(keyword).strip().casefold()
        items = []
        for case_id, bound_dataset in sorted(self._bindings().items()):
            case = catalog.get(case_id, {"case_id": case_id, "name": case_id, "module": ""})
            if dataset_id and bound_dataset != dataset_id:
                continue
            if needle and needle not in f"{case_id} {case.get('name', '')}".casefold():
                continue
            items.append({**case, "dataset_id": bound_dataset,
                          "valid": case_id in catalog and (self.dataset_dir / f"{bound_dataset}.json").exists()})
        return self._page(items, page, page_size)

    def resolve_case(self, case_id) -> tuple[str, dict]:
        dataset_id = self._bindings().get(case_id)
        if not dataset_id:
            raise WorkspaceError(f"测试用例 {case_id} 未绑定数据集")
        return dataset_id, self.get_dataset(dataset_id)

    def _metadata_path(self, name):
        path = self.dataset_dir / ".smartkit" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _bindings(self):
        value = self._read_json(self._metadata_path("case-bindings.json"), {"bindings": {}})
        return dict(value.get("bindings", {}))

    def _save_bindings(self, bindings):
        _atomic_json(self._metadata_path("case-bindings.json"), {"bindings": bindings})

    @staticmethod
    def _page(items, page, page_size):
        page = max(1, int(page))
        page_size = min(100, max(1, int(page_size)))
        start = (page - 1) * page_size
        return {"items": items[start:start + page_size], "page": page,
                "page_size": page_size, "total": len(items)}

    def _dataset_path(self, dataset_id: str) -> Path:
        if not DATASET_ID.fullmatch(str(dataset_id or "")):
            raise WorkspaceError("数据集 ID 只能包含字母、数字、点、下划线和连字符")
        self.dataset_dir.mkdir(parents=True, exist_ok=True)
        return self.dataset_dir / f"{dataset_id}.json"

    def _load_dataset_path(self, path: Path) -> dict:
        dataset = self._read_json(path, None)
        if not isinstance(dataset, dict) or dataset.get("id") != path.stem:
            raise WorkspaceError(f"无效的数据集文件: {path.name}")
        return self._normalize_dataset(dataset, creating=False)

    def _normalize_dataset(self, payload, creating):
        if not isinstance(payload, dict):
            raise WorkspaceError("数据集必须是 JSON 对象")
        dataset_id = str(payload.get("id", "")).strip()
        if not DATASET_ID.fullmatch(dataset_id):
            raise WorkspaceError("数据集 ID 只能包含字母、数字、点、下划线和连字符")
        result = dict(payload)
        result.update(id=dataset_id, name=str(payload.get("name") or dataset_id).strip(),
                      description=str(payload.get("description") or ""),
                      revision=1 if creating else max(1, int(payload.get("revision", 1))))
        for key, default in (("server", {}), ("rest_server", {}), ("commands", []),
                             ("command_groups", []), ("rest_routes", []), ("rest_groups", [])):
            result.setdefault(key, default)
        if not isinstance(result["commands"], list) or not isinstance(result["rest_routes"], list):
            raise WorkspaceError("commands 和 rest_routes 必须是数组")
        return result

    @staticmethod
    def _read_json(path: Path, default):
        if not path.exists():
            return default
        with path.open("r", encoding="utf-8") as stream:
            return json.load(stream)
