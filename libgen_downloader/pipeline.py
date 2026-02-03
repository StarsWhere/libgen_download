"""
High level orchestration helpers used by CLI/GUI.
"""

from threading import Event

from .download import download_for_result
from .errors import DownloadError
from .search import smart_search


def process_single_item(
    query: str,
    args,
    language=None,
    ext=None,
    year_min=None,
    year_max=None,
    author=None,
    author_exact: bool | None = None,
    logger=None,
    progress_cb=None,
    cancel_event: Event | None = None,
):
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
        author=author if author is not None else getattr(args, "author", None),
        author_exact=author_exact if author_exact is not None else getattr(args, "author_exact", False),
        logger=logger,
    )

    if not filtered:
        _log(f"[!] '{query}' 最终未找到匹配结果", level="warning", logger=logger)
        return False

    idx = args.index
    if idx < 0 or idx >= len(filtered):
        idx = 0

    candidate_indices = [idx] + [i for i in range(len(filtered)) if i != idx]
    candidate_indices = candidate_indices[: args.max_fallback_results]

    last_err = None
    for pos, i in enumerate(candidate_indices):
        chosen = filtered[i]
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


def _log(message, level: str = "info", logger=None):
    if logger:
        try:
            logger(level, message)
            return
        except Exception:
            pass
    print(message)
