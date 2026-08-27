from booruradar.core.enums import MetricProvenance
from booruradar.services.quality import (
    GELBOORU_SNAPSHOT_POLICY,
    TotalPostsAnomalyPolicy,
    previous_total_posts,
)

def test_previous_estimated_posts_is_accepted():
    metrics = {
        "total_posts": {
            "value": 1000,
            "provenance": MetricProvenance.ESTIMATED,
            "unit": "posts"
        }
    }
    assert previous_total_posts(metrics) == 1000

def test_previous_observed_posts_is_ignored():
    metrics = {
        "total_posts": {
            "value": 1000,
            "provenance": MetricProvenance.OBSERVED,
            "unit": "posts"
        }
    }
    assert previous_total_posts(metrics) is None

def test_previous_owner_verified_posts_is_ignored():
    metrics = {
        "total_posts": {
            "value": 1000,
            "provenance": MetricProvenance.OWNER_VERIFIED,
            "unit": "posts"
        }
    }
    assert previous_total_posts(metrics) is None

def test_previous_estimated_incompatible_unit_is_ignored():
    metrics = {
        "total_posts": {
            "value": 1000,
            "provenance": MetricProvenance.ESTIMATED,
            "unit": "pages"
        }
    }
    assert previous_total_posts(metrics) is None


def test_gelbooru_policy_accepts_only_observed_posts_history():
    observed_posts = {
        "total_posts": {
            "value": 1000,
            "provenance": MetricProvenance.OBSERVED,
            "unit": "posts",
        }
    }
    estimated_posts = {
        "total_posts": {
            "value": 1000,
            "provenance": MetricProvenance.ESTIMATED,
            "unit": "posts",
        }
    }
    observed_pages = {
        "total_posts": {
            "value": 1000,
            "provenance": MetricProvenance.OBSERVED,
            "unit": "pages",
        }
    }

    assert GELBOORU_SNAPSHOT_POLICY.previous_total_posts(observed_posts) == 1000
    assert GELBOORU_SNAPSHOT_POLICY.previous_total_posts(estimated_posts) is None
    assert GELBOORU_SNAPSHOT_POLICY.previous_total_posts(observed_pages) is None

def test_catastrophic_change_behavior_works_for_compatible_history():
    policy = TotalPostsAnomalyPolicy()
    
    metrics = {
        "total_posts": {
            "value": 10_000_000,
            "provenance": MetricProvenance.ESTIMATED,
            "unit": "posts"
        }
    }
    previous = previous_total_posts(metrics)
    assert previous == 10_000_000
    
    flags = policy.suspicious_flags(previous, 1_000_000)
    assert flags == ("total_posts_catastrophic_drop",)
    
    metrics_low = {
        "total_posts": {
            "value": 1_000_000,
            "provenance": MetricProvenance.ESTIMATED,
            "unit": "posts"
        }
    }
    previous_low = previous_total_posts(metrics_low)
    assert previous_low == 1_000_000
    
    flags_growth = policy.suspicious_flags(previous_low, 6_000_000)
    assert flags_growth == ("total_posts_catastrophic_growth",)

    flags_normal = policy.suspicious_flags(previous, 10_000_100)
    assert flags_normal == ()


def test_invalid_or_missing_historical_values_are_ignored():
    invalid_metrics = (
        None,
        {},
        {"total_posts": {"value": True, "provenance": "estimated", "unit": "posts"}},
        {"total_posts": {"value": -1, "provenance": "estimated", "unit": "posts"}},
        {"total_posts": {"value": "1000", "provenance": "estimated", "unit": "posts"}},
        {"total_posts": "raw-payload"},
    )

    assert all(previous_total_posts(metrics) is None for metrics in invalid_metrics)
