"""
Search related helpers for Libgen.
"""

import re
from typing import Iterable, List, Optional
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .config import BASE_URL, SESSION
from .errors import DownloadError


def search(
    query: str,
    limit: int = 25,
    columns: Optional[Iterable[str]] = None,
    objects: Optional[Iterable[str]] = None,
    topics: Optional[Iterable[str]] = None,
    order: Optional[str] = None,
    ordermode: Optional[str] = None,
    filesuns: str = "all",
):
    """
    调用 index.php 做搜索，支持自定义 columns/objects/topics/order/filesuns 等参数。
    """
    params = {
        "req": query,
        "res": str(limit),
        "filesuns": filesuns,
    }

    default_columns = ["t", "a", "s", "y", "p", "i"]
    default_objects = ["f", "e", "s", "a", "p", "w"]
    default_topics = ["l", "c", "f", "a", "m", "r", "s"]

    params["columns[]"] = columns if columns else default_columns
    params["objects[]"] = objects if objects else default_objects
    params["topics[]"] = topics if topics else default_topics

    if order:
        params["order"] = order
    if ordermode:
        params["ordermode"] = ordermode

    url = urljoin(BASE_URL, "/index.php")
    resp = SESSION.get(url, params=params)
    resp.raise_for_status()
    return parse_search_results(resp.text)


def parse_search_results(html: str, base_url: str = BASE_URL):
    """
    从搜索结果页面 HTML 中解析结果列表。
    每行结构（9 列）：
    0: 标题(+ISBN+badge+edition 链接)
    1: 作者
    2: 出版社
    3: 年份
    4: 语言
    5: 页数
    6: 大小(+file.php?id)
    7: 扩展名
    8: mirrors（含 ads.php?md5=... 及其它镜像链接）
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="tablelibgen")
    if not table:
        return []
    body = table.find("tbody")
    if not body:
        return []

    results: List[dict] = []
    for row in body.find_all("tr"):
        cols = row.find_all("td")
        if len(cols) != 9:
            continue

        col0 = cols[0]
        title_link = col0.find("a", href=lambda x: x and "edition.php" not in x)
        if title_link:
            raw_title = title_link.get_text(" ", strip=True)
        else:
            for s in col0(["script", "style"]):
                s.decompose()
            raw_title = col0.get_text(" ", strip=True)

        title = " ".join(raw_title.split())
        title = re.split(r"ISBN[:\s]", title, flags=re.I)[0].strip()

        edition_id = None
        edition_url = None
        for a in col0.find_all("a", href=True):
            href = a["href"]
            if "edition.php" in href:
                edition_url = urljoin(base_url, href)
                qs = parse_qs(urlparse(edition_url).query)
                edition_id = qs.get("id", [None])[0]
                break

        author = cols[1].get_text(" ", strip=True)
        publisher = cols[2].get_text(" ", strip=True)
        year = cols[3].get_text(" ", strip=True)
        language = cols[4].get_text(" ", strip=True)
        pages = cols[5].get_text(" ", strip=True)

        col_size = cols[6]
        size_link = col_size.find("a", href=True)
        if size_link:
            size_text = size_link.get_text(" ", strip=True)
            href = size_link["href"]
            file_id = parse_qs(urlparse(href).query).get("id", [None])[0]
        else:
            size_text = col_size.get_text(" ", strip=True)
            file_id = None

        extension = cols[7].get_text(" ", strip=True)

        mirrors_col = cols[8]
        md5 = None
        ads_url = None
        mirrors = []
        for a in mirrors_col.find_all("a", href=True):
            href = a["href"]
            full = urljoin(base_url, href)
            mirrors.append(full)
            if "ads.php?md5=" in href and not ads_url:
                ads_url = full
                qs = parse_qs(urlparse(ads_url).query)
                md5 = qs.get("md5", [md5])[0]
            if not md5 and "/book/" in href:
                m = re.search(r"/book/([0-9a-f]{32})", href)
                if m:
                    md5 = m.group(1)

        results.append(
            {
                "title": title,
                "edition_id": edition_id,
                "edition_url": edition_url,
                "author": author,
                "publisher": publisher,
                "year": year,
                "language": language,
                "pages": pages,
                "size": size_text,
                "extension": extension,
                "file_id": file_id,
                "md5": md5,
                "ads_url": ads_url,
                "mirrors": mirrors,
            }
        )
    return results


def filter_results(
    results,
    language=None,
    ext=None,
    year_min=None,
    year_max=None,
    author=None,
    author_exact: bool = False,
):
    """
    在本地对搜索结果做二次筛选。
    """
    filtered = []
    author_keyword = (author or "").strip()
    author_keyword_norm = _normalize_text(author_keyword) if author_keyword else ""
    for r in results:
        if language and (r.get("language") or "").lower() != language.lower():
            continue
        if ext and (r.get("extension") or "").lower() != ext.lower():
            continue
        if year_min is not None or year_max is not None:
            year_str = (r.get("year") or "").strip()
            try:
                y = int(year_str)
            except ValueError:
                continue
            if year_min is not None and y < year_min:
                continue
            if year_max is not None and y > year_max:
                continue
        if author_keyword_norm:
            author_field = _normalize_text(r.get("author") or "")
            if not author_field:
                continue
            if author_exact:
                author_parts = [p.strip() for p in re.split(r"[;,/&|]+", author_field) if p.strip()]
                if author_keyword_norm not in author_parts:
                    continue
            else:
                if author_keyword_norm not in author_field:
                    continue
        filtered.append(r)
    return filtered


def smart_search(
    query: str,
    limit: int = 25,
    columns=None,
    objects=None,
    topics=None,
    order=None,
    ordermode=None,
    filesuns: str = "all",
    language=None,
    ext=None,
    year_min=None,
    year_max=None,
    author=None,
    author_exact: bool = False,
    fallback_level: int = 0,
    logger=None,
):
    """
    智能搜索：如果当前参数组合没有结果，则尝试减少过滤条件。
    fallback_level:
    0: 原始参数
    1: 忽略年份限制
    2: 忽略扩展名限制
    3: 忽略语言限制
    """
    _log(
        f"[*] 尝试搜索: '{query}' (Level {fallback_level}) | 语言={language}, 格式={ext}, 年份={year_min}-{year_max}, 作者={author}",
        logger=logger,
    )

    try:
        results = search(
            query,
            limit=limit,
            columns=columns,
            objects=objects,
            topics=topics,
            order=order,
            ordermode=ordermode,
            filesuns=filesuns,
        )
    except requests.RequestException as e:
        _log(f"[!] 搜索请求失败: {e}", level="error", logger=logger)
        return []

    if not results:
        return []

    filtered = filter_results(
        results,
        language=language,
        ext=ext,
        year_min=year_min,
        year_max=year_max,
        author=author,
        author_exact=author_exact,
    )

    if not filtered and fallback_level < 3:
        _log(f"[!] Level {fallback_level} 无结果，尝试降低过滤要求...", level="warning", logger=logger)
        if fallback_level == 0:
            return smart_search(
                query,
                limit,
                columns,
                objects,
                topics,
                order,
                ordermode,
                filesuns,
                language,
                ext,
                None,
                None,
                author,
                author_exact,
                fallback_level + 1,
                logger=logger,
            )
        if fallback_level == 1:
            return smart_search(
                query,
                limit,
                columns,
                objects,
                topics,
                order,
                ordermode,
                filesuns,
                language,
                None,
                None,
                None,
                author,
                author_exact,
                fallback_level + 2,
                logger=logger,
            )
        if fallback_level == 2:
            return smart_search(
                query,
                limit,
                columns,
                objects,
                topics,
                order,
                ordermode,
                filesuns,
                None,
                None,
                None,
                None,
                author,
                author_exact,
                fallback_level + 3,
                logger=logger,
            )

    return filtered


def _log(message, level: str = "info", logger=None):
    if logger:
        try:
            logger(level, message)
            return
        except Exception:
            pass
    print(message)


def _normalize_text(text: str) -> str:
    return " ".join(str(text).lower().split())
