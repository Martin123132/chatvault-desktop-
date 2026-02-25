from __future__ import annotations

from typing import Dict, Any

from chatvault_db import get_archive_stats


def collect_stats(con) -> Dict[str, Any]:
    """Collect and return aggregate ChatVault stats."""
    return get_archive_stats(con)
