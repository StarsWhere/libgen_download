import argparse
import os
import re
import unicodedata
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup


# 搜索主站域名：改成你自己的入口（现在用的是示例）
BASE_URL = "https://libgen.vg"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; LibgenScript/1.0)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
})


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
        first_a = col0.find("a")
        if first_a:
            raw_title = first_a.get_text(" ", strip=True)
        else:
            raw_title = col0.get_text(" ", strip=True)
        title = " ".join(raw_title.split())

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
    - 去掉非法字符 < > : " / \ | ? *
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
    作者 - 标题 (年份, 出版社).扩展名
    """
    parts = []

    author = (result.get("author") or "").strip()
    title = (result.get("title") or "").strip()
    year = (result.get("year") or "").strip()
    publisher = (result.get("publisher") or "").strip()
    ext = (result.get("extension") or "bin").strip().lstrip(".")

    if author:
        parts.append(author)
    if title:
        if parts:
            parts.append(" - ")
        parts.append(title)

    extras = []
    if year:
        extras.append(year)
    if publisher:
        extras.append(publisher)

    if extras:
        parts.append(" (" + ", ".join(extras) + ")")

    if parts:
        base = "".join(parts)
    else:
        md5 = result.get("md5") or "download"
        base = md5

    filename = f"{base}.{ext}"
    return clean_filename(filename)


def download_file_from_get_url(get_url, out_dir=".", filename=None, max_retries=3, timeout=60):
    """
    针对一个 get.php/download 链接，带重试逻辑：
    - 网络错误/超时：自动重试
    - 5xx：视为服务器错误，重试
    - 4xx：视为客户端错误，不重试
    """
    last_exc = None
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

            fname = filename or "download.bin"
            fname = clean_filename(fname)

            os.makedirs(out_dir, exist_ok=True)
            path = os.path.join(out_dir, fname)

            try:
                with open(path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
            except OSError:
                # 如果因为文件名问题报错，再用一个更简单的名字
                safe_name = clean_filename("download.bin")
                path = os.path.join(out_dir, safe_name)
                with open(path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)

            return path

        except (requests.Timeout, requests.ConnectionError) as e:
            last_exc = e
            continue
        except requests.HTTPError as e:
            last_exc = e
            break

    raise DownloadError(f"下载失败（GET: {get_url}）：{last_exc}")


def download_for_result(result, out_dir=".", max_entry_urls=5, max_get_retries=3):
    """
    针对单个搜索结果：
    - 先按顺序尝试多个入口（ads_url + mirrors）
    - 每个入口解析 get.php/download 链接，再做带重试下载
    - 全部失败则抛 DownloadError
    """
    filename = build_filename_from_result(result)
    print(f"[*] 计划保存文件名: {filename}")

    candidate_urls = []
    if result.get("ads_url"):
        candidate_urls.append(result["ads_url"])
    for u in result.get("mirrors") or []:
        if u not in candidate_urls:
            candidate_urls.append(u)

    if not candidate_urls:
        raise DownloadError("没有可用的下载入口链接（既没有 ads_url 也没有 mirrors）")

    last_err = None
    for i, entry_url in enumerate(candidate_urls[:max_entry_urls]):
        print(f"[*] 尝试第 {i+1} 个下载入口: {entry_url}")
        try:
            get_url = fetch_download_link_from_page(entry_url)
        except requests.RequestException as e:
            print(f"[!] 打开入口页失败: {e}")
            last_err = e
            continue

        if not get_url:
            print("[!] 在入口页中没有找到 get/download 链接，尝试下一个入口")
            continue

        print(f"[*] 解析到下载链接: {get_url}")
        try:
            path = download_file_from_get_url(
                get_url,
                out_dir=out_dir,
                filename=filename,
                max_retries=max_get_retries,
            )
            print(f"[+] 使用入口 {entry_url} 下载成功")
            return path
        except DownloadError as e:
            print(f"[!] 使用入口 {entry_url} 下载失败: {e}")
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


def main():
    parser = argparse.ArgumentParser(
        description="从 dev1.example.test 搜索并下载文件的小脚本（支持多参数与容错下载）"
    )
    parser.add_argument("query", help="搜索关键词（例如：我们为什么要睡觉）")
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

    try:
        results = search(
            args.query,
            limit=args.limit,
            columns=args.columns,
            objects=args.objects,
            topics=args.topics,
            order=args.order,
            ordermode=args.ordermode,
            filesuns=args.filesuns,
        )
    except requests.RequestException as e:
        print(f"[!] 搜索请求失败: {e}")
        return

    if not results:
        print("[!] 搜索没有返回任何结果")
        return

    print(f"[*] 搜索结果总数: {len(results)} 条")

    filtered = filter_results(
        results,
        language=args.language,
        ext=args.ext,
        year_min=args.year_min,
        year_max=args.year_max,
    )

    if not filtered:
        print("[!] 筛选后结果为空，请放宽 language/ext/year 条件重试")
        return

    if len(filtered) != len(results):
        print(f"[*] 筛选后剩余 {len(filtered)} 条结果")

    print("[*] 展示前 10 条筛选后的结果：")
    for i, r in enumerate(filtered[:10]):
        print(f"{i:2d}. {r['title']}")
        print(f"    作者: {r['author']} | 出版社: {r['publisher']} | 年份: {r['year']} | 语言: {r['language']} | 大小: {r['size']} | 格式: {r['extension']}")
        if r.get("md5"):
            print(f"    md5: {r['md5']}")
        print()

    idx = args.index
    if idx < 0 or idx >= len(filtered):
        print(f"[!] 指定 index={idx} 不在筛选结果范围 0..{len(filtered)-1}")
        return

    # 候选结果顺序：先用户指定，再依次尝试其他结果
    candidate_indices = [idx] + [i for i in range(len(filtered)) if i != idx]
    candidate_indices = candidate_indices[:args.max_fallback_results]

    last_err = None
    for pos, i in enumerate(candidate_indices):
        chosen = filtered[i]
        print(f"[*] 尝试第 {pos+1} 个候选结果（筛选后索引 {i}）: {chosen['title']}")
        if not chosen.get("ads_url") and not chosen.get("mirrors"):
            print("[!] 该结果没有任何下载入口链接（ads_url/mirrors），跳过")
            continue
        try:
            path = download_for_result(
                chosen,
                out_dir=args.out_dir,
                max_entry_urls=args.max_entry_urls,
                max_get_retries=args.max_retries,
            )
            print(f"[+] 下载成功，文件保存在: {path}")
            return
        except DownloadError as e:
            print(f"[!] 该结果下载失败: {e}")
            last_err = e
            continue

    print("[!] 尝试了所有候选结果，仍然下载失败")
    if last_err:
        print(f"    最后一次错误信息: {last_err}")


if __name__ == "__main__":
    main()
