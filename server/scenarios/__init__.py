from .base import BaseScenario
from .db_outage import DbConnectionOutage
from .cascade import CascadingFailure
from .corruption import DataCorruption

SCENARIOS = {
    "task1_db_outage": DbConnectionOutage,
    "task2_cascade_failure": CascadingFailure,
    "task3_data_corruption": DataCorruption,
}

__all__ = ["BaseScenario", "SCENARIOS"]
