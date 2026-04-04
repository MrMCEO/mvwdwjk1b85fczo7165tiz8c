# Import all models here so that Base.metadata is fully populated
# when init_db() calls Base.metadata.create_all().

from bot.models.immunity import Immunity, ImmunityBranch, ImmunityUpgrade  # noqa: F401
from bot.models.infection import Infection  # noqa: F401
from bot.models.resource import Currency, ResourceTransaction, TransactionReason  # noqa: F401
from bot.models.user import User  # noqa: F401
from bot.models.virus import Virus, VirusBranch, VirusUpgrade  # noqa: F401
