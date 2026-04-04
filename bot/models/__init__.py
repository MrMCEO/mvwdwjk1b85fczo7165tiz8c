# Import all models here so that Base.metadata is fully populated
# when init_db() calls Base.metadata.create_all().

from bot.models.alliance import (  # noqa: F401
    Alliance,
    AllianceJoinRequest,
    AllianceMember,
    AlliancePrivacy,
    AllianceRole,
    JoinRequestStatus,
)
from bot.models.attack_log import AttackAttempt  # noqa: F401
from bot.models.event import Event, EventParticipant, EventType, PandemicParticipant  # noqa: F401
from bot.models.immunity import Immunity, ImmunityBranch, ImmunityUpgrade  # noqa: F401
from bot.models.infection import Infection  # noqa: F401
from bot.models.item import Item, ItemType  # noqa: F401
from bot.models.market import ListingStatus, ListingType, MarketListing  # noqa: F401
from bot.models.mutation import Mutation, MutationRarity, MutationType  # noqa: F401
from bot.models.promo import PromoActivation, PromoCode  # noqa: F401
from bot.models.referral import Referral, ReferralReward  # noqa: F401
from bot.models.resource import Currency, ResourceTransaction, TransactionReason  # noqa: F401
from bot.models.user import User  # noqa: F401
from bot.models.virus import Virus, VirusBranch, VirusUpgrade  # noqa: F401
