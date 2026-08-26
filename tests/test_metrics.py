from __future__ import annotations

import pytest
from pydantic import ValidationError

from booruradar.adapters.schemas import TagStatistic
from booruradar.core.enums import MetricProvenance
from booruradar.models.metrics import MetricEnvelope, MetricMap


def test_metric_map_preserves_metric_level_provenance() -> None:
    metrics = MetricMap.model_validate(
        {
            "exact": {"value": 12, "provenance": "observed", "unit": "posts"},
            "sampled": {"value": 9.5, "provenance": "estimated"},
            "declared": {"value": 20, "provenance": "owner_verified"},
        }
    )

    stored = metrics.to_storage()

    assert stored["exact"]["provenance"] == "observed"
    assert stored["sampled"]["provenance"] == "estimated"
    assert stored["declared"]["provenance"] == "owner_verified"


def test_metric_rejects_missing_provenance() -> None:
    with pytest.raises(ValidationError):
        MetricEnvelope.model_validate({"value": 12})


def test_tag_count_rejects_non_integer_metric() -> None:
    with pytest.raises(ValidationError, match="non-negative integer"):
        TagStatistic.model_validate(
            {
                "name": "tag",
                "post_count": {
                    "value": 1.5,
                    "provenance": MetricProvenance.ESTIMATED,
                },
                "collected_at": "2026-08-26T00:00:00Z",
            }
        )
