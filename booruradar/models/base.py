from __future__ import annotations

from sqlalchemy import Enum, MetaData
from sqlalchemy.orm import DeclarativeBase

from booruradar.core.enums import CrawlRunStatus, MetricProvenance


NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def enum_values(enum_type: type[MetricProvenance] | type[CrawlRunStatus]) -> list[str]:
    return [member.value for member in enum_type]


metric_provenance_enum = Enum(
    MetricProvenance,
    name="metric_provenance",
    values_callable=enum_values,
    validate_strings=True,
)

crawl_run_status_enum = Enum(
    CrawlRunStatus,
    name="crawl_run_status",
    values_callable=enum_values,
    validate_strings=True,
)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
