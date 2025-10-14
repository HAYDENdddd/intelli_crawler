from __future__ import annotations

import pytest

from intelli_crawler.ui import ConfigWizard, ProgressReporter


def test_progress_reporter_counts(snapshot) -> None:
    reporter = ProgressReporter(enabled=False)
    reporter.start(total=3)
    reporter.advance(success=True, current_url="https://example.com/a")
    reporter.advance(failed=True)
    reporter.advance(skipped=True)
    summary = reporter.summary()
    reporter.close()
    snapshot.assert_match(summary, key="progress_summary")


def test_progress_requires_start() -> None:
    reporter = ProgressReporter(enabled=False)
    with pytest.raises(RuntimeError):
        reporter.advance()


def test_config_wizard_from_template(temp_config_repository, snapshot) -> None:
    wizard = ConfigWizard(temp_config_repository)
    config = wizard.from_template("DemoSource")
    path = temp_config_repository.source_path("DemoSource")
    assert path.exists()
    snapshot.assert_match(config.model_dump(mode="json"), key="wizard_template")


def test_config_wizard_from_payload(temp_config_repository, sample_source_config) -> None:
    wizard = ConfigWizard(temp_config_repository)
    source = sample_source_config(source_name="PayloadDemo", target_url="https://demo")
    config = wizard.from_payload(source.model_dump(mode="json"))
    assert config.source_name == "PayloadDemo"
