"""Configuration loading helpers for Intelli-Crawler."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

from .models import GlobalConfig, SourceConfig

CONFIG_EXTENSIONS = (".yaml", ".yml", ".json")
GLOBAL_CONFIG_FILENAME = "global_config.yaml"
SOURCE_CONFIG_SUFFIX = ".yaml"


def _slugify(name: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in name).strip("-")


def _read_file(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        data = yaml.safe_load(text) or {}
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"Configuration file must contain a mapping: {path}")
    return data


def _write_file(path: Path, payload: dict) -> None:
    if path.suffix in (".yaml", ".yml"):
        yaml.safe_dump(
            payload, path.open("w", encoding="utf-8"), allow_unicode=True, sort_keys=False
        )
    else:
        json.dump(payload, path.open("w", encoding="utf-8"), indent=2, ensure_ascii=False)


@dataclass(slots=True)
class ConfigLocator:
    """Resolve important paths from project root."""

    project_root: Path | None = None
    data_dir: Path | None = None
    history_dir: Path | None = None
    outputs_dir: Path | None = None
    sources_dir: Path | None = None
    logs_dir: Path | None = None

    def __post_init__(self) -> None:
        env_root = os.environ.get("INTELLI_CRAWLER_HOME")
        if env_root:
            root = Path(env_root).expanduser().resolve()
        else:
            root = (self.project_root or Path(__file__).resolve().parents[2]).resolve()
        self.project_root = root
        self.data_dir = (root / "data").resolve()
        self.history_dir = (self.data_dir / "history").resolve()
        self.outputs_dir = (self.data_dir / "outputs").resolve()
        self.sources_dir = (self.data_dir / "sources").resolve()
        self.logs_dir = (root / "logs").resolve()
        self.ensure_directories()

    def ensure_directories(self) -> None:
        for directory in (
            self.data_dir,
            self.history_dir,
            self.outputs_dir,
            self.sources_dir,
            self.logs_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def global_config_path(self) -> Path:
        return self.data_dir / GLOBAL_CONFIG_FILENAME


class ConfigRepository:
    """Repository encapsulating config IO and schema validation."""

    def __init__(self, locator: ConfigLocator | None = None) -> None:
        self.locator = locator or ConfigLocator()
        self._global_cache: GlobalConfig | None = None

    # ------------------------------------------------------------------
    # Global configuration helpers
    # ------------------------------------------------------------------
    def load_global_config(self) -> GlobalConfig:
        if self._global_cache is not None:
            return self._global_cache
        path = self.locator.global_config_path()
        if path.exists():
            payload = _read_file(path)
            global_cfg = GlobalConfig.model_validate(payload)
        else:
            global_cfg = GlobalConfig()
            self.save_global_config(global_cfg)
        self._global_cache = global_cfg
        return global_cfg

    def save_global_config(self, config: GlobalConfig) -> None:
        path = self.locator.global_config_path()
        payload = config.model_dump(mode="json")
        _write_file(path, payload)
        self._global_cache = config

    # ------------------------------------------------------------------
    # Source configuration helpers
    # ------------------------------------------------------------------
    def source_path(self, source_name: str) -> Path:
        slug = _slugify(source_name)
        return self.locator.sources_dir / f"{slug}{SOURCE_CONFIG_SUFFIX}"

    def list_source_files(self) -> Iterable[Path]:
        for path in self.locator.sources_dir.glob("*"):
            if path.is_file() and path.suffix in CONFIG_EXTENSIONS:
                yield path

    def list_sources(self) -> list[SourceConfig]:
        return [self.load_source(path) for path in self.list_source_files()]

    def load_source(self, identifier: str | Path) -> SourceConfig:
        path = identifier if isinstance(identifier, Path) else self.source_path(identifier)
        if not path.exists():
            raise FileNotFoundError(f"Source configuration not found: {identifier}")
        payload = _read_file(path)
        cfg = SourceConfig.model_validate(payload)
        return cfg

    def save_source(self, config: SourceConfig) -> Path:
        path = self.source_path(config.source_name)
        payload = config.model_dump(mode="json")
        _write_file(path, payload)
        return path

    def delete_source(self, source_name: str) -> None:
        path = self.source_path(source_name)
        if path.exists():
            path.unlink()

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------
    def ensure_template(self, template_name: str) -> Path:
        """Return the template file path from the built-in templates directory.

        Historically this method copied the template into the `data/sources` directory,
        which caused `source_template.yaml` to be detected as a real source.
        We avoid polluting the sources directory by reading directly from the
        package `templates` folder.
        """
        templates_dir = Path(__file__).resolve().parent / "templates"
        template_path = templates_dir / template_name
        if not template_path.exists():
            raise FileNotFoundError(f"Template not found: {template_path}")
        return template_path


__all__ = ["ConfigLocator", "ConfigRepository", "CONFIG_EXTENSIONS"]
