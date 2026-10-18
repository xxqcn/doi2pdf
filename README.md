# doi2pdf

按 DOI 从 Sci-Hub 下载论文 PDF。只做下载论文这一件事。

## 安装

```bash
pip install -e .        # 开发安装
pip install .           # 或普通安装
```

依赖：`requests`、`beautifulsoup4`、`pypdf`，Python ≥ 3.11。

未安装时也可在源码根目录直接用 `python3 cli.py --help`。

## 用法

```bash
doi2pdf 10.1021/ol200992c                    # 下载到当前目录
doi2pdf 10.1021/ol200992c -o ~/papers        # 指定输出目录
doi2pdf dois.txt -o ~/papers                 # txt 每行一个 DOI（# 为注释）
doi2pdf - < dois.txt                         # 从标准输入读取
doi2pdf 10.1xxx/yyy -m https://sci-hub.al    # 临时指定镜像排错
doi2pdf --help                               # 完整参数说明
```

文件名由 DOI 百分号编码而来：`10.1039/d5cc03627e` → `10.1039%2Fd5cc03627e.pdf`。
这样不同 DOI 不会共用同一个文件名（`10.1234/a/b` 与 `10.1234/a_b` 分别是
`10.1234%2Fa%2Fb.pdf` 和 `10.1234%2Fa_b.pdf`），缓存判断不会串号。

已存在且有效的 PDF 默认跳过，`-f/--force` 强制重下。

含 `?` `&` `#` 的 DOI 会整段编码后再拼落地页 URL，不会被服务器当成查询参数。

## 配置

镜像会失效或更换域名。把 `doi2pdf.toml.example` 复制为 `doi2pdf.toml`（放当前目录、`~/.config/doi2pdf/`，或用 `--config`/环境变量 `DOI2PDF_CONFIG` 指定）后修改镜像列表，不用改代码。

用 `--config` 或 `DOI2PDF_CONFIG` 显式指定路径时，文件不存在会直接报错退出（退出码 2），不会静默退回其它配置。未提供配置时使用内置镜像 `sci-hub.ee` / `.al` / `.ren`。

## 说明

- 每个请求只发一条 `User-Agent`，这是绕过 Sci-Hub 前置 DDoS-Guard 的关键，补齐浏览器特征头反而容易被拦。
- PDF 用 `pypdf` 校验页树（至少 1 页），HTML 错误页和被截断的响应会被拒绝。
- 下载先写临时文件再原子替换，中断不会留下半截 PDF。
- 落地页里的 PDF 链接支持绝对地址、`//host/x.pdf`、`/x.pdf` 和 `files/x.pdf` 四种形式。

## 免责声明

仅供个人学术研究检索使用。使用者的下载行为需自行遵守所在地区法律及出版商订阅协议，作者不承担任何由此产生的责任。

## 退出码

| 码 | 含义 |
|----|------|
| 0 | 全部成功（含缓存命中） |
| 1 | 至少一篇失败 |
| 2 | 参数或配置错误 |

## 开发

```bash
pip install -e ".[dev]"
python -m pytest -q
```
