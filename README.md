# Libgen 智能批量下载工具 (Libgen Downloader)

基于标准化架构的 Libgen 搜索/下载器，提供 CLI 与 PyQt6 GUI，支持批量导入、智能回退与多镜像重试。

## 目录结构
```
libgen_downloader/
  ├── config.py          # 全局配置与 Session/代理
  ├── search.py          # 搜索、解析、智能回退
  ├── download.py        # 链接解析、重试下载、文件名规范化
  ├── pipeline.py        # 单任务编排（搜索+下载）
  ├── cli.py             # CLI 入口
  └── gui/               # GUI 组件、线程、样式
pyproject.toml            # 打包/脚本入口
libgen_download.py        # 兼容旧入口（委托到新包）
libgen_gui.py             # 兼容旧 GUI 入口
```

## 安装
```bash
python -m pip install -r requirements.txt
# 或使用项目脚本名（需本地可编辑安装）
pip install -e .
```
运行环境：Python 3.9+，依赖 `requests`, `beautifulsoup4`, `PyQt6`, `openpyxl`。

## 使用
### CLI
- 基础搜索下载：
  ```bash
  python -m libgen_downloader "深入理解计算机系统"
  # 等价：libgen-cli "深入理解计算机系统"  (pip -e 安装后)
  ```
- 带筛选：
  ```bash
  python -m libgen_downloader "Python 编程" --language Chinese --ext pdf --year-min 2010
  python -m libgen_downloader "Python 编程" --author "张三" --author-exact
  ```
- CSV 批量：
  ```bash
  python -m libgen_downloader --csv books.csv --col-query 书名 --col-author 作者 --col-ext 类型
  ```

### GUI
```bash
python -m libgen_downloader.gui
# 或安装后：libgen-gui
```
GUI 支持作者筛选（包含/精确）、搜索结果表、多选下载、并行队列、进度与日志、拖拽/导入 CSV & XLSX、Toast 提示、代理与并行/重试配置持久化。

## 参数速查（CLI 与 GUI 共享核心逻辑）
- `--language` / `--ext` / `--year-min` / `--year-max`：精确过滤，若无结果自动逐步放宽（年份→格式→语言）。
- `--author`：作者筛选（默认包含匹配，不区分大小写）；`--author-exact` 为精确匹配。
- `--max-entry-urls`：每个条目最多尝试的镜像入口，默认 5。
- `--max-fallback-results`：当首选结果失败时向后尝试的候选数，默认 3。
- `--proxy`：HTTP/HTTPS 代理，也可通过环境变量 `LIBGEN_PROXY` 设置。
- `--columns/--objects/--topics/--order/--ordermode/--filesuns`：原生 Libgen 搜索参数直通。

## 注意
- 默认主站 `https://libgen.vg`，可通过环境变量 `LIBGEN_BASE_URL` 覆盖。
- 文件名会自动清理非法字符并在 150 字符内截断。

## 许可证
MIT License，详见 [LICENSE](LICENSE)。
