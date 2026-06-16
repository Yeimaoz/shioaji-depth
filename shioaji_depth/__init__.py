"""shioaji-depth — generic Taiwan TAIFEX futures 5-level (五檔) depth recorder."""

from .parquet_io import prune_old, write_depth_parquet
from .recorder import TwDepthRecorder, validate_book
from .session import ShioajiAuthError, login, logout

__version__ = "0.1.0"

__all__ = [
    "TwDepthRecorder",
    "validate_book",
    "write_depth_parquet",
    "prune_old",
    "login",
    "logout",
    "ShioajiAuthError",
]
