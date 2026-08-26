import pytest
from booruradar.core.enums import MetricProvenance
from booruradar.services.quality import previous_total_posts, TotalPostsAnomalyPolicy

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
