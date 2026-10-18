"""配置读取 —— 镜像列表、超时、User-Agent。

配置来源按优先级从高到低：

1. ``--config`` / 调用方显式传入的路径
2. 环境变量 ``DOI2PDF_CONFIG``
3. 当前工作目录的 ``./doi2pdf.toml``
4. ``~/.config/doi2pdf/doi2pdf.toml``
5. 都没有 → 使用本模块内置默认值

Sci-Hub 镜像会失效或更换域名，用户只需改配置文件，无需改代码。
"""
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# ── 内置默认值 ──────────────────────────────────────────
# 镜像实测记录 (2026-10，DOI 10.1021/ol200992c):
#   sci-hub.st   直连 16s 无 PDF 链接 / 走代理 403      → 已剔除
#   sci-hub.shop 返回卖书页，无 PDF 链接                → 已剔除
#   sci-hub.ee   直连 0.7s  ✓ 真 PDF 531KB             ← 最快
#   sci-hub.al   直连 1.1s  ✓ 真 PDF 531KB
#   sci-hub.ren  直连 1.6s  ✓ 真 PDF 531KB
DEFAULT_MIRRORS = [
    'https://sci-hub.ee',
    'https://sci-hub.al',
    'https://sci-hub.ren',
]

DEFAULT_LANDING_TIMEOUT = 15  # 落地页请求超时 (秒)
DEFAULT_PDF_TIMEOUT = 60      # PDF 文件下载超时 (秒)

# 极简 UA：Sci-Hub 前置 DDoS-Guard，带上 Sec-Ch-Ua 等完整浏览器特征头
# 反而更容易被拦截，所以这里刻意只发一条 User-Agent。
DEFAULT_USER_AGENT = (
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
)


@dataclass
class Config:
    mirrors: list = field(default_factory=lambda: list(DEFAULT_MIRRORS))
    landing_timeout: float = DEFAULT_LANDING_TIMEOUT
    pdf_timeout: float = DEFAULT_PDF_TIMEOUT
    user_agent: str = DEFAULT_USER_AGENT
    source: str = '<built-in defaults>'

    def __post_init__(self):
        # 配置文件是用户手写的，类型可能写错（如 mirrors = [1]）。
        # 这里统一转成 ValueError，由 CLI 报"配置错误"并返回退出码 2，
        # 而不是让 AttributeError / TypeError 冒成 traceback。
        try:
            self.landing_timeout = float(self.landing_timeout)
            self.pdf_timeout = float(self.pdf_timeout)
        except (TypeError, ValueError) as exc:
            raise ValueError(f'timeouts 必须是数字: {exc}') from exc

        # str 也是可迭代的，必须先单独排除，否则 "https://x" 会被逐字符拆开
        if isinstance(self.mirrors, str):
            raise ValueError('mirrors 必须是字符串列表，不能是单个字符串')
        if not isinstance(self.mirrors, (list, tuple)):
            raise ValueError(f'mirrors 必须是字符串列表（当前 {type(self.mirrors).__name__}）')
        cleaned = []
        for m in self.mirrors:
            if not isinstance(m, str):
                raise ValueError(f'mirrors 中的元素必须是字符串（收到 {m!r}）')
            if m.strip():
                cleaned.append(m.strip().rstrip('/'))
        if not cleaned:
            raise ValueError('mirrors 不能为空')
        self.mirrors = cleaned


def load_config(path=None) -> Config:
    """读取配置；找不到配置文件则返回内置默认值。

    ``--config`` 或环境变量 ``DOI2PDF_CONFIG`` 属于"用户明确指定"，文件不
    存在时直接抛 ``FileNotFoundError``，不会退回去加载当前目录的配置——
    否则用户以为自己在用某份配置，实际运行的是另一份。
    只有隐式查找（./doi2pdf.toml、~/.config/...）才允许找不到。
    """
    if path is not None:
        explicit = Path(path).expanduser()
        if not explicit.is_file():
            raise FileNotFoundError(f'配置文件不存在: {explicit}')
        return _load_file(explicit)

    env = os.environ.get('DOI2PDF_CONFIG')
    if env:
        explicit = Path(env).expanduser()
        if not explicit.is_file():
            raise FileNotFoundError(
                f'环境变量 DOI2PDF_CONFIG 指向的配置文件不存在: {explicit}')
        return _load_file(explicit)

    for candidate in (Path.cwd() / 'doi2pdf.toml',
                      Path.home() / '.config' / 'doi2pdf' / 'doi2pdf.toml'):
        if candidate.is_file():
            return _load_file(candidate)
    return Config()


def _load_file(path: Path) -> Config:
    """读取单个 TOML 配置文件。"""
    try:
        with path.open('rb') as fh:
            raw = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f'无法读取配置文件 {path}: {exc}') from exc
    return _from_dict(raw, source=str(path))


def _from_dict(raw: dict, source: str) -> Config:
    """把 TOML 字典转成 Config。"""
    if not isinstance(raw, dict):
        raise ValueError('配置文件顶层必须是 TOML 表')
    scihub = raw.get('scihub')
    if scihub is not None and not isinstance(scihub, dict):
        raise ValueError('[scihub] 必须是 TOML 表')
    mirrors = raw.get('mirrors')
    # 兼容 [scihub] mirrors = [...] 这种从 litFlow 带过来的写法
    if mirrors is None:
        mirrors = (scihub or {}).get('mirrors')
    if mirrors is None:
        mirrors = list(DEFAULT_MIRRORS)
    # 类型必须在这里就判定：字符串是可迭代的，若留到 Config.__post_init__
    # 之前被 list 化，会变成逐字符拆开的镜像列表。
    if isinstance(mirrors, str):
        raise ValueError('mirrors 必须是字符串列表，不能是单个字符串')
    if not isinstance(mirrors, (list, tuple)):
        raise ValueError(f'mirrors 必须是字符串列表（当前 {type(mirrors).__name__}）')

    timeouts = raw.get('timeouts') or {}
    request = raw.get('request') or {}
    if not isinstance(timeouts, dict) or not isinstance(request, dict):
        raise ValueError('[timeouts] 与 [request] 必须是 TOML 表')

    user_agent = request.get('user_agent', DEFAULT_USER_AGENT)
    if not isinstance(user_agent, str) or not user_agent.strip():
        raise ValueError('request.user_agent 必须是非空字符串')

    return Config(
        mirrors=list(mirrors),
        landing_timeout=timeouts.get('landing', DEFAULT_LANDING_TIMEOUT),
        pdf_timeout=timeouts.get('pdf', DEFAULT_PDF_TIMEOUT),
        user_agent=user_agent,
        source=source,
    )
