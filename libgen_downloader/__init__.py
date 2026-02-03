"""
Libgen Downloader core package.

Exposes shared utilities for searching and downloading files from Libgen
along with CLI/GUI entry points.
"""

from .config import BASE_URL, SESSION, set_proxy  # noqa: F401
from .search import search, smart_search, filter_results  # noqa: F401
from .download import (  # noqa: F401
    build_filename_from_result,
    clean_filename,
    download_file_from_get_url,
    download_for_result,
    fetch_download_link_from_page,
)
from .pipeline import process_single_item  # noqa: F401
from .errors import DownloadError  # noqa: F401

__all__ = [
    "BASE_URL",
    "SESSION",
    "set_proxy",
    "search",
    "smart_search",
    "filter_results",
    "build_filename_from_result",
    "clean_filename",
    "download_file_from_get_url",
    "download_for_result",
    "fetch_download_link_from_page",
    "process_single_item",
    "DownloadError",
]
