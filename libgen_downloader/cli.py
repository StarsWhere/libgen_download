"""
Command line entry point for Libgen downloader.
"""

import argparse
import csv
import os
from pathlib import Path

from .config import set_proxy
from .pipeline import process_single_item


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从 Libgen 搜索并下载文件的小脚本（支持 CSV 批量下载与智能回退）"
    )
    parser.add_argument("query", nargs="?", help="搜索关键词（如果不使用 --csv）")
    parser.add_argument("--csv", help="CSV 文件路径，用于批量下载")
    parser.add_argument("--col-query", default="书名", help="CSV 中作为搜索关键词的列名，默认 '书名'")
    parser.add_argument("--col-author", help="CSV 中作为作者筛选的列名")
    parser.add_argument("--col-language", help="CSV 中作为语言筛选的列名")
    parser.add_argument("--col-ext", default="类型", help="CSV 中作为扩展名筛选的列名，默认 '类型'")
    parser.add_argument("--col-year-min", help="CSV 中作为年份最小值的列名")
    parser.add_argument("--col-year-max", help="CSV 中作为年份最大值的列名")

    parser.add_argument("-n", "--index", type=int, default=0, help="选择第几条结果作为优先下载目标（从 0 开始，默认 0）")
    parser.add_argument("-o", "--out-dir", default="downloads", help="文件保存目录，默认 ./downloads")
    parser.add_argument("--limit", type=int, default=25, help="搜索返回的最大条数（对应 res 参数），默认 25")
    parser.add_argument("--language", help="只保留指定语言的结果，例如 Chinese、English")
    parser.add_argument("--author", help="作者筛选（默认包含匹配，不区分大小写）")
    parser.add_argument("--author-exact", action="store_true", help="作者精确匹配（优先级高于包含匹配）")
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
        choices=["author", "extension", "f_id", "filesize", "publisher", "series", "time_added", "title", "year"],
        help="排序字段（对应 order 参数）",
    )
    parser.add_argument("--ordermode", choices=["asc", "desc"], help="排序顺序（对应 ordermode 参数）")
    parser.add_argument("--filesuns", choices=["all", "sort", "unsort"], default="all", help="filesuns 参数：all/sort/unsort，默认 all")
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
    parser.add_argument("--max-retries", type=int, default=3, help="每个下载链接最多重试次数，默认 3")
    parser.add_argument("--proxy", help="使用 http(s) 代理，例如 http://127.0.0.1:7890")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.proxy:
        set_proxy(args.proxy)

    if args.csv:
        if not os.path.exists(args.csv):
            print(f"[!] CSV 文件不存在: {args.csv}")
            return

        with open(args.csv, mode="r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                query = row.get(args.col_query)
                if not query:
                    continue

                lang = row.get(args.col_language) if args.col_language else None
                author = row.get(args.col_author) if args.col_author else None
                ext = row.get(args.col_ext) if args.col_ext else None

                y_min = None
                if args.col_year_min and row.get(args.col_year_min):
                    try:
                        y_min = int(row[args.col_year_min])
                    except Exception:
                        pass

                y_max = None
                if args.col_year_max and row.get(args.col_year_max):
                    try:
                        y_max = int(row[args.col_year_max])
                    except Exception:
                        pass

                print(f"\n{'='*40}")
                print(f"[*] 正在处理: {query}")
                process_single_item(
                    query,
                    args,
                    language=lang,
                    ext=ext,
                    year_min=y_min,
                    year_max=y_max,
                    author=author,
                    author_exact=args.author_exact,
                )
    else:
        if not args.query:
            parser.print_help()
            return
        process_single_item(args.query, args)


if __name__ == "__main__":
    main()
