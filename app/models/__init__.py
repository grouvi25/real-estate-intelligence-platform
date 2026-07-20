"""ORM models package.

Importing this package registers every model with SQLAlchemy's mapper registry
(Base.metadata), so mappers configure correctly and relationships resolve.
"""
from app.models.activity_log import ActivityLog
from app.models.agency import Agency
from app.models.base import Base, CreatedAtMixin, UpdatedAtMixin
from app.models.deal_outcome import DealOutcome
from app.models.geo_location import GeoLocation
from app.models.lead import Lead
from app.models.manager import Manager
from app.models.match import LeadPropertyMatch
from app.models.match_exclusion import MatchExclusion
from app.models.partner_agency import PartnerAgency
from app.models.partner_referral import PartnerReferral
from app.models.property import Property
from app.models.protected_geo import ProtectedGeo
from app.models.signal import Signal
from app.models.source import Source
from app.models.source_discovery_log import SourceDiscoveryLog
from app.models.task import Task

__all__ = [
    "Base",
    "CreatedAtMixin",
    "UpdatedAtMixin",
    "ActivityLog",
    "Agency",
    "DealOutcome",
    "GeoLocation",
    "Lead",
    "Manager",
    "LeadPropertyMatch",
    "MatchExclusion",
    "PartnerAgency",
    "PartnerReferral",
    "Property",
    "ProtectedGeo",
    "Signal",
    "Source",
    "SourceDiscoveryLog",
    "Task",
]
