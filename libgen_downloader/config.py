import os
from typing import Optional

import requests

# 默认搜索主站域名，可通过环境变量覆盖
BASE_URL: str = os.getenv("LIBGEN_BASE_URL", "https://libgen.vg")

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; LibgenScript/2.0)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _create_session(proxy_url: Optional[str] = None) -> requests.Session:
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    if proxy_url:
        session.proxies.update({"http": proxy_url, "https": proxy_url})
    return session


# 全局共享 Session，避免重复 TCP/TLS 握手
SESSION: requests.Session = _create_session(os.getenv("LIBGEN_PROXY"))


def set_proxy(proxy_url: Optional[str]) -> None:
    """
    更新全局代理配置。传入 None/空串时清空代理。
    """
    if proxy_url:
        SESSION.proxies.update({"http": proxy_url, "https": proxy_url})
    else:
        SESSION.proxies.clear()
