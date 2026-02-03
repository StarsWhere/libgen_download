"""
Download helpers: filename building, link extraction, mirror retries.
"""

import os
import re
import shutil
import unicodedata
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urljoin
from http.client import IncompleteRead

import requests
from bs4 import BeautifulSoup
from requests.exceptions import ChunkedEncodingError
from threading import Event

from .config import SESSION
from .errors import DownloadError


def fetch_download_link_from_page(entry_url: str) -> Optional[str]:
    """
    打开任意入口页（ads.php、book 页面等），解析出最终 get.php/download 链接。
    如果入口本身直接返回二进制内容（非 HTML），则直接认为入口 URL 就是下载 URL。
    """
    resp = SESSION.get(entry_url, allow_redirects=True)
    resp.raise_for_status()

    ct = resp.headers.get("Content-Type", "")
    if not ct.lower().startswith("text/html"):
        return resp.url

    html = resp.text
    soup = BeautifulSoup(html, "html.parser")

    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = (a.get_text(strip=True) or "").upper()
        href_lower = href.lower()
        if ("get.php" in href_lower or "download" in href_lower) and (
            "GET" in text or "DOWNLOAD" in text or "下载" in text
        ):
            return urljoin(resp.url, href)

    m = re.search(r'href="([^"]*get\.php\?[^"]+)"', html, flags=re.I)
    if m:
        return urljoin(resp.url, m.group(1))

    m2 = re.search(r'href="([^"]*(?:download|dl|d)\.php\?[^"]+)"', html, flags=re.I)
    if m2:
        return urljoin(resp.url, m2.group(1))

    return None


def clean_filename(name: str, max_length: int = 150) -> str:
    """
    清洗文件名（特别针对 Windows）：Unicode 规范化、移除非法字符、截断过长。
    """
    name = unicodedata.normalize("NFKD", name)
    prohibited = '<>:"/\\|?*'
    cleaned_chars = []
    for ch in name:
        if ord(ch) < 32:
            continue
        if ch in prohibited:
            continue
        cleaned_chars.append(ch)

    cleaned = "".join(cleaned_chars).strip()
    if not cleaned:
        cleaned = "download"

    if len(cleaned) > max_length:
        root, ext = os.path.splitext(cleaned)
        keep = max_length - len(ext)
        if keep < 1:
            keep = max_length
            ext = ""
        cleaned = root[:keep] + ext

    return cleaned


def build_filename_from_result(result: dict) -> str:
    """
    使用搜索结果构建文件名：书名-作者-出版社-年份-语言-页数-其他.扩展名。
    """

    def clean_field(text, max_len=None):
        if not text:
            return ""
        text = " ".join(str(text).split())
        if max_len and len(text) > max_len:
            text = text[:max_len].strip() + "..."
        return text

    title = (result.get("title") or "").strip()
    if not title:
        title = (result.get("_fallback_title") or "").strip()
    title = re.sub(r"[\(（](?:[^\(\)（）]{20,})[\)）]", "", title).strip()
    title = clean_field(title, 80)

    author = clean_field(result.get("author"), 30)
    publisher = clean_field(result.get("publisher"), 30)
    year = clean_field(result.get("year"))
    language = clean_field(result.get("language"))
    pages = clean_field(result.get("pages"))
    md5 = result.get("md5") or ""

    ext = (result.get("extension") or "bin").strip().lstrip(".")
    base_fields = [title, author, publisher, year, language, pages]
    base = "-".join([f for f in base_fields if f]) or md5 or "download"

    filename = clean_filename(f"{base}.{ext}")

    max_len = 150
    if len(filename) > max_len:
        fallback_title = clean_field(result.get("_fallback_title") or "") or (md5[:12] if md5 else "download")
        filename = clean_filename(f"{fallback_title}.{ext}")
    return filename


def download_file_from_get_url(
    get_url: str,
    out_dir: str | Path = ".",
    filename: Optional[str] = None,
    max_retries: int = 3,
    timeout: int = 60,
    logger=None,
    progress_cb=None,
    cancel_event: Event | None = None,
    stop_event: Event | None = None,
    temp_dir=None,
) -> str:
    """
    针对一个 get.php/download 链接，带重试逻辑：网络/5xx 自动重试，4xx 直接失败。
    """
    last_exc = None
    target_name = filename or "download.bin"
    out_path = Path(out_dir)
    tmp_root = Path(temp_dir) if temp_dir else out_path / ".partial"
    tmp_root.mkdir(parents=True, exist_ok=True)
    fname = clean_filename(target_name)
    temp_path = tmp_root / f"{fname}.part"
    final_path = out_path / fname

    for attempt in range(1, max_retries + 1):
        try:
            offset = temp_path.stat().st_size if temp_path.exists() else 0
            headers = {"Range": f"bytes={offset}-"} if offset > 0 else {}

            resp = SESSION.get(
                get_url,
                stream=True,
                allow_redirects=True,
                timeout=timeout,
                headers=headers or None,
            )
            status = resp.status_code

            if status >= 500:
                last_exc = requests.HTTPError(f"Server error: {status}", response=resp)
                continue
            if status >= 400:
                raise requests.HTTPError(f"Client error: {status}", response=resp)

            os.makedirs(out_dir, exist_ok=True)

            total = None
            if "Content-Range" in resp.headers:
                m = re.search(r"bytes\\s+(\\d+)-(\\d+)/(\\d+)", resp.headers["Content-Range"])
                if m:
                    start, end, full = map(int, m.groups())
                    total = full
                    offset = start
            else:
                total = resp.headers.get("Content-Length")
                try:
                    total = int(total) if total else None
                except ValueError:
                    total = None

            if offset > 0 and status == 200:
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception:
                    pass
                offset = 0

            mode = "ab" if offset > 0 else "wb"
            downloaded = 0

            try:
                with open(temp_path, mode) as f:
                    if offset:
                        downloaded = offset
                    for chunk in resp.iter_content(chunk_size=8192):
                        if (cancel_event and cancel_event.is_set()) or (stop_event and stop_event.is_set()):
                            raise DownloadError("下载已被取消")
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if progress_cb:
                                progress_cb(downloaded, total)
            except OSError:
                short_base = clean_filename(Path(fname).stem)[:80] or "download"
                ext = Path(fname).suffix or ".bin"
                alt_name = f"{short_base}{ext}"
                final_path = out_path / alt_name
                temp_path = tmp_root / f"{alt_name}.part"
                with open(temp_path, mode) as f:
                    if offset:
                        downloaded = offset
                    for chunk in resp.iter_content(chunk_size=8192):
                        if (cancel_event and cancel_event.is_set()) or (stop_event and stop_event.is_set()):
                            raise DownloadError("下载已被取消")
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if progress_cb:
                                progress_cb(downloaded, total)

            try:
                shutil.move(str(temp_path), str(final_path))
            except Exception:
                os.replace(temp_path, final_path)

            return str(final_path)

        except (requests.Timeout, requests.ConnectionError, ChunkedEncodingError, IncompleteRead) as e:
            last_exc = e
            continue
        except requests.HTTPError as e:
            last_exc = e
            break
        except DownloadError as e:
            last_exc = e
            if cancel_event or stop_event:
                for p in [locals().get("temp_path"), locals().get("final_path")]:
                    if p and os.path.exists(p):
                        try:
                            os.remove(p)
                        except OSError:
                            pass
            break

    raise DownloadError(f"下载失败（GET: {get_url}）：{last_exc}")


def download_for_result(
    result: dict,
    out_dir: str | Path = ".",
    max_entry_urls: int = 5,
    max_get_retries: int = 3,
    logger=None,
    progress_cb=None,
    cancel_event: Event | None = None,
) -> str:
    """
    针对单个搜索结果：尝试多个入口，解析下载链接并执行带重试的下载。
    """
    filename = build_filename_from_result(result)
    _log(f"[*] 计划保存文件名: {filename}", logger=logger)
    expected_ext = (result.get("extension") or "").lower()

    candidate_urls: list[str] = []
    if result.get("ads_url"):
        candidate_urls.append(result["ads_url"])
    for u in result.get("mirrors") or []:
        if u not in candidate_urls:
            candidate_urls.append(u)

    if not candidate_urls:
        raise DownloadError("没有可用的下载入口链接（既没有 ads_url 也没有 mirrors）")

    entries = candidate_urls[:max_entry_urls]

    def validate_file(path):
        try:
            if not os.path.exists(path):
                return False
            size = os.path.getsize(path)
            if size < 10 * 1024:
                return False
            with open(path, "rb") as f:
                sig = f.read(8)
            if expected_ext == "pdf" and not sig.startswith(b"%PDF"):
                return False
            if expected_ext in {"epub", "zip"} and not sig.startswith(b"PK"):
                return False
            return True
        except Exception:
            return False

    last_err = None

    for i, entry_url in enumerate(entries):
        _log(f"[*] 尝试第 {i+1} 个下载入口: {entry_url}", logger=logger)
        try:
            get_url = fetch_download_link_from_page(entry_url)
        except requests.RequestException as e:
            _log(f"[!] 打开入口页失败: {e}", level="error", logger=logger)
            last_err = e
            continue

        if not get_url:
            _log("[!] 在入口页中没有找到 get/download 链接，尝试下一个入口", level="warning", logger=logger)
            continue

        _log(f"[*] 解析到下载链接: {get_url}", logger=logger)
        try:
            temp_root = Path(out_dir) / ".partial"
            path = download_file_from_get_url(
                get_url,
                out_dir=out_dir,
                filename=filename,
                max_retries=max_get_retries,
                logger=logger,
                progress_cb=progress_cb,
                cancel_event=cancel_event,
                stop_event=None,
                temp_dir=temp_root,
            )
            if not validate_file(path):
                _log("[!] 下载文件校验失败，尝试其他镜像", level="warning", logger=logger)
                try:
                    os.remove(path)
                except OSError:
                    pass
                continue
            _log(f"[+] 使用入口 {entry_url} 下载成功", level="success", logger=logger)
            return path
        except DownloadError as e:
            _log(f"[!] 使用入口 {entry_url} 下载失败: {e}", level="error", logger=logger)
            last_err = e
            continue

    raise DownloadError(f"该条目所有尝试的镜像/入口均下载失败: {last_err}")


def _log(message, level: str = "info", logger=None):
    if logger:
        try:
            logger(level, message)
            return
        except Exception:
            pass
    print(message)
