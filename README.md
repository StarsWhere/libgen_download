# Libgen Download Script

这是一个用于从 Libgen 镜像站搜索并下载图书的 Python 脚本。支持多参数筛选、自动重试以及多镜像源容错下载。

## 功能特性

- **灵活搜索**：支持通过标题、作者、ISBN、出版社等多种字段进行搜索。
- **结果筛选**：支持在本地对搜索结果进行语言（Language）、格式（Extension）、年份（Year）的二次筛选。
- **智能下载**：
  - 自动解析镜像页面的最终下载链接。
  - 支持多镜像源（Mirrors）自动回退，如果第一个镜像失效，会自动尝试下一个。
  - 具备重试机制，应对网络波动。
- **文件名优化**：自动根据作者、标题、年份和出版社生成规范的文件名，并处理 Windows 下的非法字符。

## 安装依赖

在使用之前，请确保已安装 Python 3.x，并安装必要的第三方库：

```bash
pip install -r requirements.txt
```

主要依赖：
- `requests`: 用于处理 HTTP 请求。
- `beautifulsoup4`: 用于解析 HTML 页面。

## 使用方法

### 基本用法

搜索并下载第一条结果：

```bash
python libgen_download.py "搜索关键词"
```

### 常用参数

- `-n`, `--index`: 选择下载第几条结果（从 0 开始，默认为 0）。
- `-o`, `--out-dir`: 指定文件保存目录（默认为 `./downloads`）。
- `--language`: 筛选特定语言，如 `Chinese` 或 `English`。
- `--ext`: 筛选特定文件格式，如 `pdf`、`mobi`、`epub`。
- `--year-min` / `--year-max`: 筛选年份范围。
- `--limit`: 设置搜索返回的最大条数（默认 25）。

### 进阶示例

搜索“Python 编程”，只看中文的 PDF 结果，并下载第 2 条：

```bash
python libgen_download.py "Python 编程" --language Chinese --ext pdf -n 1
```

自定义搜索字段（仅搜索标题和作者）：

```bash
python libgen_download.py "Deep Learning" --columns t a
```

## 免责声明

本工具仅供学习和研究使用。请在使用时遵守当地法律法规，尊重版权。

## 许可证

本项目采用 [MIT License](LICENSE) 开源。
