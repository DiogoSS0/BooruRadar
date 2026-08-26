from __future__ import annotations

from booruradar.models import Base


def test_initial_schema_contains_only_foundation_tables() -> None:
    assert set(Base.metadata.tables) == {
        "boorus",
        "booru_snapshots",
        "tags",
        "tag_snapshots",
        "crawl_runs",
    }


def test_collected_metrics_have_provenance_storage() -> None:
    booru_snapshot = Base.metadata.tables["booru_snapshots"]
    tag_snapshot = Base.metadata.tables["tag_snapshots"]

    assert "metrics" in booru_snapshot.c
    assert "health_provenance" in booru_snapshot.c
    assert "capabilities_provenance" in booru_snapshot.c
    assert "post_count" in tag_snapshot.c
    assert "post_count_provenance" in tag_snapshot.c
    assert "metrics" in tag_snapshot.c
