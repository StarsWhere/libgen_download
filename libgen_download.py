"""
兼容入口：请改用 `python -m libgen_downloader` 或 `python -m libgen_downloader.cli`。
保留此文件以避免现有脚本调用失效。
"""

from libgen_downloader import *  # noqa: F401,F403
from libgen_downloader.cli import main


if __name__ == "__main__":
    main()
