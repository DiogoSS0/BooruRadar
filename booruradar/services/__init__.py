"""Application services independent of transport and persistence frameworks."""

from booruradar.services.inspection import BooruInspectionService, InspectionResult

__all__ = ["BooruInspectionService", "InspectionResult"]
