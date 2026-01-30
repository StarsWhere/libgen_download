import argparse
import csv
import os
import re
import unicodedata
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs
import uuid
import shutil

import requests
from bs4 import BeautifulSoup
from threading import Event


# 搜索主站域名：改成你自己的入口（现在用的是示例）
BASE_URL = "https://libgen.vg"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; LibgenScript/1.0)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
})


# 轻量日志分发：优先调用传入的 logger/回调，否则退回 print。
def set_proxy(proxy_url):
    """设置全局代理"""
    if proxy_url:
        SESSION.proxies.update({
            "http": proxy_url,
            "https": proxy_url,
        })
    else:
        SESSION.proxies.clear()

def _log(message, level="info", logger=None):
    if logger:
        try:
            logger(level, message)
            return
        except Exception:
            # 防御性：即便 logger 出错也不影响主流程
            pass
    print(message)


class DownloadError(Exception):
    pass


def search(query, limit=25, columns=None, objects=None, topics=None,
           order=None, ordermode=None, filesuns="all"):
    """
    调用 index.php 做搜索，支持自定义 columns/objects/topics/order/filesuns 等参数。
    """
    params = {
        "req": query,
        "res": str(limit),
        "filesuns": filesuns,
    }

    # 默认搜索字段/对象/主题
    default_columns = ["t", "a", "s", "y", "p", "i"]
    default_objects = ["f", "e", "s", "a", "p", "w"]
    default_topics = ["l", "c", "f", "a", "m", "r", "s"]

    cols = columns if columns else default_columns
    objs = objects if objects else default_objects
    tops = topics if topics else default_topics

    params["columns[]"] = cols
    params["objects[]"] = objs
    params["topics[]"] = tops

    if order:
        params["order"] = order
    if ordermode:
        params["ordermode"] = ordermode

    url = urljoin(BASE_URL, "/index.php")
    resp = SESSION.get(url, params=params)
    resp.raise_for_status()
    return parse_search_results(resp.text)


def parse_search_results(html, base_url=BASE_URL):
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

    results = []
    for row in body.find_all("tr"):
        cols = row.find_all("td")
        if len(cols) != 9:
            continue

        # col0: 标题 + ISBN + badge + edition 链接
        col0 = cols[0]
        # 优先寻找带有具体书名链接的 a 标签（通常是第一个 a 标签，但要排除掉一些小图标链接）
        # 观察发现书名链接通常包含在第一个 <a> 中，或者直接在 td 文本中
        title_link = col0.find("a", href=lambda x: x and "edition.php" not in x)
        if title_link:
            raw_title = title_link.get_text(" ", strip=True)
        else:
            # 兜底：移除脚本和样式标签后获取纯文本
            for s in col0(["script", "style"]):
                s.decompose()
            raw_title = col0.get_text(" ", strip=True)
        
        # 清理标题：移除多余空格，处理可能的 ISBN 混入
        title = " ".join(raw_title.split())
        # 如果标题里包含 ISBN: ... 这种，尝试截断（Libgen 有时会把 ISBN 放在标题后面）
        title = re.split(r'ISBN[:\s]', title, flags=re.I)[0].strip()

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

        # col6: 大小 + file.php?id
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

        # col8: mirrors，含 ads.php?md5=xxx 等
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
            # 备用：从 /book/<md5> 这种链接里提取 md5
            if not md5 and "/book/" in href:
                m = re.search(r"/book/([0-9a-f]{32})", href)
                if m:
                    md5 = m.group(1)

        results.append({
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
        })
    return results


def fetch_download_link_from_page(entry_url):
    """
    打开任意入口页（ads.php、book 页面等），解析出最终 get.php/download 链接。
    如果入口本身直接返回二进制内容（非 HTML），则直接认为入口 URL 就是下载 URL。
    """
    resp = SESSION.get(entry_url, allow_redirects=True)
    resp.raise_for_status()

    ct = resp.headers.get("Content-Type", "")
    if not ct.lower().startswith("text/html"):
        # 不是 HTML，直接视为下载地址
        return resp.url

    html = resp.text
    soup = BeautifulSoup(html, "html.parser")

    # 优先找文本里带 GET / DOWNLOAD / 下载 的 a 标签，并且链接里带 get.php 或 download
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = (a.get_text(strip=True) or "").upper()
        href_lower = href.lower()
        if ("get.php" in href_lower or "download" in href_lower) and (
            "GET" in text or "DOWNLOAD" in text or "下载" in text
        ):
            return urljoin(resp.url, href)

    # 退回到正则扫描 get.php
    m = re.search(r'href="([^"]*get\.php\?[^"]+)"', html, flags=re.I)
    if m:
        return urljoin(resp.url, m.group(1))

    # 再退回到可能的 download.php / dl.php / d.php
    m2 = re.search(r'href="([^"]*(?:download|dl|d)\.php\?[^"]+)"', html, flags=re.I)
    if m2:
        return urljoin(resp.url, m2.group(1))

    return None


def clean_filename(name, max_length=150):
    """
    清洗文件名（特别针对 Windows）：
    - Unicode 规范化
    - 去掉控制字符
    - 截断过长文件名
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


def build_filename_from_result(result):
    """
    使用搜索结果构建文件名：
    书名-作者-出版社-年份-语言-页数-其他.扩展名
    优化：截断过长的字段，移除标题中括号内的冗余推广信息，并清理空白字符。

    特别处理：
    - 如果解析到的标题为空，则尝试使用搜索时的关键词作为保底标题（由上游写入 _fallback_title 字段）。
    """
    def clean_field(text, max_len=None):
        if not text:
            return ""
        # 将所有空白字符（包括换行、制表符、多个空格）替换为单个空格
        text = " ".join(text.split())
        if max_len and len(text) > max_len:
            text = text[:max_len].strip() + "..."
        return text

    # 1. 书名
    title = (result.get("title") or "").strip()
    if not title:
        # 当解析结果中没有标题时，使用搜索关键词作为保底标题
        title = (result.get("_fallback_title") or "").strip()
    # 移除括号及其内容（通常是推广语），但保留一些可能有意义的（如 [2nd ed.]）
    # 这里简单处理，只移除常见的推广或冗余括号
    title = re.sub(r'[\(（](?:[^\(\)（）]{20,})[\)）]', '', title).strip()
    title = clean_field(title, 80)
    
    # 2. 作者
    author = clean_field(result.get("author"), 30)
        
    # 3. 出版社
    publisher = clean_field(result.get("publisher"), 30)
        
    # 4. 年份
    year = clean_field(result.get("year"))
    
    # 5. 语言
    language = clean_field(result.get("language"))
    
    # 6. 页数
    pages = clean_field(result.get("pages"))
    
    # 7. 其他 (使用 MD5 前 8 位作为唯一标识)
    md5 = result.get("md5") or ""

    ext = (result.get("extension") or "bin").strip().lstrip(".")

    # 组合
    fields = [title, author, publisher, year, language, pages]
    # 过滤掉空字段并用连字符连接
    base = "-".join([f for f in fields if f])
    
    if not base:
        base = md5 or "download"

    filename = f"{base}.{ext}"
    filename = clean_filename(filename)

    # 控制总长度：若超过 150，则直接退回搜索关键词（或 md5）作为标题，避免冗长路径
    max_len = 150
    if len(filename) > max_len:
        fallback_title = clean_field(result.get("_fallback_title") or "") or (md5[:12] if md5 else "download")
        filename = clean_filename(f"{fallback_title}.{ext}")

    return filename


def download_file_from_get_url(
    get_url,
    out_dir=".",
    filename=None,
    max_retries=3,
    timeout=60,
    logger=None,
    progress_cb=None,
    cancel_event: Event | None = None,
    stop_event: Event | None = None,
    temp_dir=None,
):
    """
    针对一个 get.php/download 链接，带重试逻辑：
    - 网络错误/超时：自动重试
    - 5xx：视为服务器错误，重试
    - 4xx：视为客户端错误，不重试
    """
    last_exc = None
    target_name = filename or "download.bin"
    out_path = Path(out_dir)
    tmp_root = Path(temp_dir) if temp_dir else out_path / ".partial"
    tmp_root.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, max_retries + 1):
        try:
            resp = SESSION.get(get_url, stream=True, allow_redirects=True, timeout=timeout)
            status = resp.status_code

            if status >= 500:
                # 服务端错误，记录后重试
                last_exc = requests.HTTPError(f"Server error: {status}", response=resp)
                continue
            if status >= 400:
                # 4xx 客户端错误，不再重试
                raise requests.HTTPError(f"Client error: {status}", response=resp)

            fname = clean_filename(target_name)

            os.makedirs(out_dir, exist_ok=True)
            final_path = out_path / fname
            temp_path = tmp_root / f"{uuid.uuid4().hex}.part"

            total = resp.headers.get("Content-Length")
            try:
                total = int(total) if total else None
            except ValueError:
                total = None

            downloaded = 0

            try:
                with open(temp_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        if (cancel_event and cancel_event.is_set()) or (stop_event and stop_event.is_set()):
                            raise DownloadError("下载已被取消")
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if progress_cb:
                                progress_cb(downloaded, total)
            except OSError:
                # 文件名/路径过长等问题，尝试更短的安全文件名
                short_base = clean_filename(Path(fname).stem)[:80] or "download"
                ext = Path(fname).suffix or ".bin"
                alt_name = f"{short_base}{ext}"
                final_path = out_path / alt_name
                temp_path = tmp_root / f"{uuid.uuid4().hex}.part"
                with open(temp_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        if (cancel_event and cancel_event.is_set()) or (stop_event and stop_event.is_set()):
                            raise DownloadError("下载已被取消")
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if progress_cb:
                                progress_cb(downloaded, total)
            # 写完再原子移动到最终位置
            try:
                shutil.move(str(temp_path), str(final_path))
            except Exception:
                # 如果移动失败，尝试替换
                os.replace(temp_path, final_path)

            return str(final_path)

        except (requests.Timeout, requests.ConnectionError) as e:
            last_exc = e
            continue
        except requests.HTTPError as e:
            last_exc = e
            break
        except DownloadError as e:
            last_exc = e
            for p in [locals().get("temp_path"), locals().get("final_path")]:
                if p and os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
            break

    raise DownloadError(f"下载失败（GET: {get_url}）：{last_exc}")


def download_for_result(
    result,
    out_dir=".",
    max_entry_urls=5,
    max_get_retries=3,
    logger=None,
    progress_cb=None,
    cancel_event: Event | None = None,
):
    """
    针对单个搜索结果：
    - 先按顺序尝试多个入口（ads_url + mirrors）
    - 每个入口解析 get.php/download 链接，再做带重试下载
    - 全部失败则抛 DownloadError
    """
    filename = build_filename_from_result(result)
    _log(f"[*] 计划保存文件名: {filename}", logger=logger)
    expected_ext = (result.get("extension") or "").lower()

    candidate_urls = []
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
            if size < 10 * 1024:  # 小于10KB认为异常
                return False
            sig = b""
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


def filter_results(results, language=None, ext=None, year_min=None, year_max=None):
    """
    在本地对搜索结果做二次筛选：
    - language 精确匹配
    - ext 精确匹配（不区分大小写）
    - year_min/year_max 年份范围过滤
    """
    filtered = []
    for r in results:
        if language:
            if (r.get("language") or "").lower() != language.lower():
                continue

        if ext:
            if (r.get("extension") or "").lower() != ext.lower():
                continue

        if year_min is not None or year_max is not None:
            year_str = (r.get("year") or "").strip()
            try:
                y = int(year_str)
            except ValueError:
                # 如果用户指定了年份过滤，无法解析年份的记录就忽略
                continue
            if year_min is not None and y < year_min:
                continue
            if year_max is not None and y > year_max:
                continue

        filtered.append(r)
    return filtered


def smart_search(query, limit=25, columns=None, objects=None, topics=None,
                 order=None, ordermode=None, filesuns="all",
                 language=None, ext=None, year_min=None, year_max=None,
                 fallback_level=0, logger=None):
    """
    智能搜索：如果当前参数组合没有结果，则尝试减少过滤条件。
    fallback_level:
    0: 原始参数
    1: 忽略年份限制
    2: 忽略扩展名限制
    3: 忽略语言限制
    """
    _log(
        f"[*] 尝试搜索: '{query}' (Level {fallback_level}) | 语言={language}, 格式={ext}, 年份={year_min}-{year_max}",
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
        # 如果搜索本身就没结果，且 query 包含多个词，可以考虑简化 query，但这里先只处理过滤条件的 fallback
        return []

    filtered = filter_results(
        results,
        language=language,
        ext=ext,
        year_min=year_min,
        year_max=year_max,
    )

    if not filtered and fallback_level < 3:
        _log(f"[!] Level {fallback_level} 无结果，尝试降低过滤要求...", level="warning", logger=logger)
        if fallback_level == 0:
            # 降级 1: 忽略年份
            return smart_search(query, limit, columns, objects, topics, order, ordermode, filesuns,
                                language, ext, None, None, fallback_level + 1, logger=logger)
        elif fallback_level == 1:
            # 降级 2: 忽略扩展名
            return smart_search(query, limit, columns, objects, topics, order, ordermode, filesuns,
                                language, None, None, None, fallback_level + 2, logger=logger)
        elif fallback_level == 2:
            # 降级 3: 忽略语言
            return smart_search(query, limit, columns, objects, topics, order, ordermode, filesuns,
                                None, None, None, None, fallback_level + 3, logger=logger)

    return filtered


def process_single_item(query, args, language=None, ext=None, year_min=None, year_max=None, logger=None,
                       progress_cb=None, cancel_event: Event | None = None):
    """处理单个条目的搜索与下载逻辑"""
    filtered = smart_search(
        query,
        limit=args.limit,
        columns=args.columns,
        objects=args.objects,
        topics=args.topics,
        order=args.order,
        ordermode=args.ordermode,
        filesuns=args.filesuns,
        language=language or args.language,
        ext=ext or args.ext,
        year_min=year_min or args.year_min,
        year_max=year_max or args.year_max,
        logger=logger,
    )

    if not filtered:
        _log(f"[!] '{query}' 最终未找到匹配结果", level="warning", logger=logger)
        return False

    # 候选结果顺序：先用户指定，再依次尝试其他结果
    idx = args.index
    if idx < 0 or idx >= len(filtered):
        idx = 0
        
    candidate_indices = [idx] + [i for i in range(len(filtered)) if i != idx]
    candidate_indices = candidate_indices[:args.max_fallback_results]

    last_err = None
    for pos, i in enumerate(candidate_indices):
        chosen = filtered[i]
        # 当解析出来的标题为空时，在结果对象中写入搜索关键词，供文件名构建时兜底使用
        if not (chosen.get("title") or "").strip():
            chosen["_fallback_title"] = query
        _log(f"[*] 尝试第 {pos+1} 个候选结果: {chosen['title']}", logger=logger)
        try:
            path = download_for_result(
                chosen,
                out_dir=args.out_dir,
                max_entry_urls=args.max_entry_urls,
                max_get_retries=args.max_retries,
                logger=logger,
                progress_cb=progress_cb,
                cancel_event=cancel_event,
            )
            _log(f"[+] 下载成功: {path}", level="success", logger=logger)
            return True
        except DownloadError as e:
            _log(f"[!] 下载失败: {e}", level="error", logger=logger)
            last_err = e
            continue
    return False


def main():
    parser = argparse.ArgumentParser(
        description="从 Libgen 搜索并下载文件的小脚本（支持 CSV 批量下载与智能回退）"
    )
    parser.add_argument("query", nargs="?", help="搜索关键词（如果不使用 --csv）")
    parser.add_argument("--csv", help="CSV 文件路径，用于批量下载")
    parser.add_argument("--col-query", default="书名", help="CSV 中作为搜索关键词的列名，默认 '书名'")
    parser.add_argument("--col-language", help="CSV 中作为语言筛选的列名")
    parser.add_argument("--col-ext", default="类型", help="CSV 中作为扩展名筛选的列名，默认 '类型'")
    parser.add_argument("--col-year-min", help="CSV 中作为年份最小值的列名")
    parser.add_argument("--col-year-max", help="CSV 中作为年份最大值的列名")

    parser.add_argument("-n", "--index", type=int, default=0,
                        help="选择第几条结果作为优先下载目标（从 0 开始，默认 0）")
    parser.add_argument("-o", "--out-dir", default="downloads",
                        help="文件保存目录，默认 ./downloads")
    parser.add_argument("--limit", type=int, default=25,
                        help="搜索返回的最大条数（对应 res 参数），默认 25")
    parser.add_argument("--language", help="只保留指定语言的结果，例如 Chinese、English")
    parser.add_argument("--ext", help="只保留指定扩展名的结果，例如 pdf、mobi（不区分大小写）")
    parser.add_argument("--year-min", type=int, help="筛选条件：年份 >= year_min")
    parser.add_argument("--year-max", type=int, help="筛选条件：年份 <= year_max")
    parser.add_argument(
        "--columns",
        nargs="+",
        choices=["t", "a", "s", "y", "p", "i"],
        help="自定义搜索字段：t=标题 a=作者 s=系列 y=年份 p=出版社 i=ISBN",
    )
    parser.add_argument(
        "--objects",
        nargs="+",
        choices=["f", "e", "s", "a", "p", "w"],
        help="自定义搜索对象：f=Files e=Editions s=Series a=Authors p=Publishers w=Works",
    )
    parser.add_argument(
        "--topics",
        nargs="+",
        choices=["l", "c", "f", "a", "m", "r", "s"],
        help="自定义搜索主题：l=Libgen c=Comics f=Fiction a=Articles m=Magazines r=Fiction RUS s=Standards",
    )
    parser.add_argument(
        "--order",
        choices=["author", "extension", "f_id", "filesize",
                 "publisher", "series", "time_added", "title", "year"],
        help="排序字段（对应 order 参数）",
    )
    parser.add_argument(
        "--ordermode",
        choices=["asc", "desc"],
        help="排序顺序（对应 ordermode 参数）",
    )
    parser.add_argument(
        "--filesuns",
        choices=["all", "sort", "unsort"],
        default="all",
        help="filesuns 参数：all/sort/unsort，默认 all",
    )
    parser.add_argument(
        "--max-fallback-results",
        type=int,
        default=3,
        help="最多尝试多少个不同的搜索结果进行下载（包含主结果），默认 3",
    )
    parser.add_argument(
        "--max-entry-urls",
        type=int,
        default=5,
        help="每个结果最多尝试多少个镜像/入口链接，默认 5",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="每个下载链接最多重试次数，默认 3",
    )
    parser.add_argument(
        "--proxy",
        help="使用 http(s) 代理，例如 http://127.0.0.1:7890",
    )
    args = parser.parse_args()

    if args.proxy:
        SESSION.proxies.update({
            "http": args.proxy,
            "https": args.proxy,
        })

    if args.csv:
        if not os.path.exists(args.csv):
            print(f"[!] CSV 文件不存在: {args.csv}")
            return
        
        with open(args.csv, mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                query = row.get(args.col_query)
                if not query:
                    continue
                
                lang = row.get(args.col_language) if args.col_language else None
                ext = row.get(args.col_ext) if args.col_ext else None
                
                y_min = None
                if args.col_year_min and row.get(args.col_year_min):
                    try: y_min = int(row[args.col_year_min])
                    except: pass
                
                y_max = None
                if args.col_year_max and row.get(args.col_year_max):
                    try: y_max = int(row[args.col_year_max])
                    except: pass

                print(f"\n{'='*40}")
                print(f"[*] 正在处理: {query}")
                process_single_item(query, args, language=lang, ext=ext, year_min=y_min, year_max=y_max)
    else:
        if not args.query:
            parser.print_help()
            return
        process_single_item(args.query, args)


if __name__ == "__main__":
    main()
