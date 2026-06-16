"""shioaji-depth — generic Taiwan TAIFEX futures 5-level (五檔) depth recorder."""

from importlib.metadata import PackageNotFoundError, version

from .parquet_io import prune_old, write_depth_parquet
from .recorder import DepthRecorder, validate_book
from .session import ShioajiAuthError, login, logout

try:
    __version__ = version("shioaji-depth")
except PackageNotFoundError:  # pragma: no cover - source tree without install
    __version__ = "0.0.0+unknown"

__all__ = [
    "DepthRecorder",
    "validate_book",
    "write_depth_parquet",
    "prune_old",
    "login",
    "logout",
    "ShioajiAuthError",
]
