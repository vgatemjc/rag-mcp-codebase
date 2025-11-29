from enum import Enum
from typing import Dict, Optional, TypedDict, Union


class EdgeType(str, Enum):
    """Standard structural edge types across stacks."""

    BINDS_LAYOUT = "BINDS_LAYOUT"
    NAV_DESTINATION = "NAV_DESTINATION"
    NAV_ACTION = "NAV_ACTION"
    NAVIGATES_TO = "NAVIGATES_TO"
    USES_VIEWMODEL = "USES_VIEWMODEL"
    CALLS_API = "CALLS_API"


class EdgePayload(TypedDict, total=False):
    type: str
    target: str
    meta: Dict[str, Union[str, int, float, bool, None, Dict[str, object]]]


EdgeLike = Union[EdgePayload, Dict[str, object]]
