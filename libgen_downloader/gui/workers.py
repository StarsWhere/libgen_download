from threading import Event

from PyQt6.QtCore import QObject, pyqtSignal

from ..errors import DownloadError
from ..pipeline import process_single_item
from ..search import smart_search
from ..download import download_for_result


class SearchWorker(QObject):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    log = pyqtSignal(str, str)  # level, message

    def __init__(self, query, limit, language, ext, year_min, year_max):
        super().__init__()
        self.query = query
        self.limit = limit
        self.language = language or None
        self.ext = ext or None
        self.year_min = year_min
        self.year_max = year_max

    def run(self):
        def logger(level, message):
            self.log.emit(level, message)

        try:
            results = smart_search(
                self.query,
                limit=self.limit,
                language=self.language,
                ext=self.ext,
                year_min=self.year_min,
                year_max=self.year_max,
                logger=logger,
            )
            self.finished.emit(results)
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))


class DownloadWorker(QObject):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)
    progress = pyqtSignal(int, int)  # downloaded, total (-1 when unknown)
    log = pyqtSignal(str, str)

    def __init__(self, result, out_dir, max_entry_urls=5, max_retries=3):
        super().__init__()
        self.result = result
        self.out_dir = out_dir
        self.max_entry_urls = max_entry_urls
        self.max_retries = max_retries
        self.cancel_event = Event()

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        def logger(level, message):
            self.log.emit(level, message)

        def progress_cb(downloaded, total):
            self.progress.emit(downloaded, total if total is not None else -1)

        try:
            path = download_for_result(
                self.result,
                out_dir=self.out_dir,
                max_entry_urls=self.max_entry_urls,
                max_get_retries=self.max_retries,
                logger=logger,
                progress_cb=progress_cb,
                cancel_event=self.cancel_event,
            )
            if self.cancel_event.is_set():
                raise DownloadError("下载已被取消")
            self.finished.emit(path)
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))


class TaskWorker(QObject):
    """统一处理两类任务：已有搜索结果 or 仅有查询参数"""

    finished = pyqtSignal(str)
    error = pyqtSignal(str)
    progress = pyqtSignal(int, int)
    log = pyqtSignal(str, str)

    def __init__(self, task, out_dir, limit=25, max_entry_urls=5, max_retries=3):
        super().__init__()
        self.task = task
        self.out_dir = out_dir
        self.limit = limit
        self.max_entry_urls = max_entry_urls
        self.max_retries = max_retries
        self.cancel_event = Event()

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        def logger(level, message):
            self.log.emit(level, message)

        def progress_cb(downloaded, total):
            self.progress.emit(downloaded, total if total is not None else -1)

        try:
            if self.task.get("type") == "result":
                result = self.task["result"]
            else:
                result = self._search_first_match(logger)
                if not result:
                    raise DownloadError("未找到匹配结果")

            path = download_for_result(
                result,
                out_dir=self.out_dir,
                max_entry_urls=self.max_entry_urls,
                max_get_retries=self.max_retries,
                logger=logger,
                progress_cb=progress_cb,
                cancel_event=self.cancel_event,
            )
            if self.cancel_event.is_set():
                raise DownloadError("下载已被取消")
            self.finished.emit(path)
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))

    def _search_first_match(self, logger):
        res = smart_search(
            self.task["query"],
            limit=self.limit,
            language=self.task.get("language"),
            ext=self.task.get("ext"),
            year_min=self.task.get("year_min"),
            year_max=self.task.get("year_max"),
            logger=logger,
        )
        return res[0] if res else None
