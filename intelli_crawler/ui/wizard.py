"""Configuration wizard helpers."""

from __future__ import annotations

from typing import Any, Mapping

import yaml

from ..config import ConfigRepository, SourceConfig


class ConfigWizard:
    """Assist CLI in bootstrapping new source configurations."""

    def __init__(self, repository: ConfigRepository) -> None:
        self.repository = repository

    def from_template(self, source_name: str, template_name: str = "source_template.yaml") -> SourceConfig:
        template_path = self.repository.ensure_template(template_name)
        data = yaml.safe_load(template_path.read_text(encoding="utf-8"))
        data["source_name"] = source_name
        config = SourceConfig.model_validate(data)
        self.repository.save_source(config)
        return config

    def from_payload(self, payload: Mapping[str, Any]) -> SourceConfig:
        config = SourceConfig.model_validate(dict(payload))
        self.repository.save_source(config)
        return config


__all__ = ["ConfigWizard"]
