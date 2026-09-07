"""World Bank Indicators API provider."""

from platform.providers.world_bank.client import (  # noqa: F401
    HISTORY_OBSERVATIONS,
    SCHEMA_VERSION,
    WorldBankError,
    fetch_snapshot,
)
from platform.providers.world_bank.normalizer import normalize_snapshot  # noqa: F401
