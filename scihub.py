"""Sci-Hub 下载器 —— 按 DOI 取 PDF。

流程：DOI → 镜像落地页 → 从 HTML 里解析 PDF 直链 → 下载并校验 → 返回路径。

关于 headers：始终使用只带 User-Agent 的自建 session。Sci-Hub 前有
DDoS-Guard，浏览器特征头（Sec-Ch-Ua / Accept-Encoding 等）反而更容易
触发拦截，所以这里刻意不模仿完整浏览器。
"""
import logging
import os
import tempfile
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

try:
    from .config import (
        DEFAULT_LANDING_TIMEOUT, DEFAULT_PDF_TIMEOUT,
        DEFAULT_USER_AGENT, DEFAULT_MIRRORS,
    )
    from .validate import is_valid_pdf
except ImportError:
    from config import (
        DEFAULT_LANDING_TIMEOUT, DEFAULT_PDF_TIMEOUT,
        DEFAULT_USER_AGENT, DEFAULT_MIRRORS,
    )
    from validate import is_valid_pdf
logger = logging.getLogger('doi2pdf')


def make_session(user_agent: str = DEFAULT_USER_AGENT) -> requests.Session:
    """创建极简 session（只带 User-Agent）。"""
    session = requests.Session()
    session.headers.update({'User-Agent': user_agent})
    return session


def parse_pdf_url(html: str) -> str | None:
    """从 Sci-Hub 落地页 HTML 中提取 PDF 直链。

    优先级：``<embed type="application/pdf">`` > ``<iframe id="pdf">``
    > 任意 ``.pdf`` 链接。三种结构在不同镜像版本中轮换出现。
    """
    soup = BeautifulSoup(html, 'html.parser')

    embed = soup.find('embed', type='application/pdf')
    if embed and embed.get('src'):
        return embed['src']

    iframe = soup.find('iframe', id='pdf')
    if iframe and iframe.get('src'):
        return iframe['src']

    link = soup.find('a', href=lambda x: x and '.pdf' in (x or '').lower())
    if link:
        return link['href']

    return None


def build_landing_url(mirror: str, doi: str) -> str:
    """构造镜像落地页 URL，DOI 必须整段编码。

    DOI 允许包含 ``?``、``&``、``#`` 等字符（如 ``10.1234/a?b``）。不编码直接
    拼进 URL，``?b`` 会被服务器当成查询参数解释，请求到的就不是这个 DOI。
    ``safe='/'`` 保留路径分隔符，其余一律百分号编码。
    """
    return f'{mirror.rstrip("/")}/{quote(doi, safe="/")}'


def resolve_pdf_url(pdf_url: str, landing_url: str) -> str:
    """把落地页里解析到的 PDF 链接补全成绝对 URL。

    镜像返回的链接形式不统一，四种都要处理：
    - ``https://host/x.pdf``  已是绝对地址，原样返回
    - ``//host/x.pdf``        协议相对 → 补 ``https:``
    - ``/x.pdf``              站点根相对 → 以镜像域名为准
    - ``files/x.pdf``         页面相对 → 以**实际落地页地址**为基准

    ``landing_url`` 必须是本次真正请求的落地页完整 URL，不能用镜像根地址
    代替：落地页 ``https://m/10.1234/a`` 里的 ``files/p.pdf`` 应解析成
    ``https://m/10.1234/files/p.pdf``，而不是 ``https://m/files/p.pdf``。
    """
    if not pdf_url:
        return pdf_url
    parsed = urlsplit(pdf_url)
    if parsed.scheme and parsed.netloc:
        return pdf_url
    if pdf_url.startswith('//'):
        return f'{urlsplit(landing_url).scheme or "https"}:' + pdf_url
    # urljoin 对 "/x.pdf" 走站点根，对 "files/x.pdf" 走落地页同级目录，
    # 两种情况都由同一个 base 正确处理。
    return urljoin(landing_url, pdf_url)


def _download_pdf(pdf_url: str, output_path: Path,
                  session: requests.Session, timeout: float) -> Path | None:
    """下载 PDF 并校验；先写 .part 再原子替换，避免留下半截文件。"""
    try:
        resp = session.get(pdf_url, timeout=timeout)
    except requests.RequestException as exc:
        logger.debug('PDF 下载失败: %s', exc)
        return None

    if resp.status_code != 200:
        logger.debug('PDF 下载 HTTP %s: %s', resp.status_code, pdf_url)
        return None
    if not is_valid_pdf(resp.content):
        logger.debug('响应不是有效 PDF (%d 字节), 拒绝保存', len(resp.content))
        return None

    # mkdir / mkstemp 也必须纳入异常处理：输出目录不可写时应算作本次
    # 下载失败，而不是把 PermissionError 抛到 CLI 变成 traceback。
    tmp_name = None
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f'.{output_path.name}.',
                                        suffix='.part', dir=output_path.parent)
        with os.fdopen(fd, 'wb') as fh:
            fh.write(resp.content)
        os.replace(tmp_name, output_path)
    except OSError as exc:
        logger.debug('PDF 写入失败: %s', exc)
        if tmp_name:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
        return None
    return output_path


def try_mirror(doi: str, output_path: Path, mirror: str,
               session: requests.Session,
               landing_timeout: float = DEFAULT_LANDING_TIMEOUT,
               pdf_timeout: float = DEFAULT_PDF_TIMEOUT) -> Path | None:
    """在单个镜像上尝试：取落地页 → 解析 PDF 直链 → 下载。失败返回 None。"""
    url = build_landing_url(mirror, doi)
    try:
        resp = session.get(url, timeout=landing_timeout)
    except requests.RequestException as exc:
        logger.debug('%s 落地页请求失败: %s', mirror, exc)
        return None

    if resp.status_code != 200:
        logger.debug('%s 落地页 HTTP %s', mirror, resp.status_code)
        return None

    pdf_url = parse_pdf_url(resp.text)
    if not pdf_url:
        logger.debug('%s 落地页未找到 PDF 链接 (该文献可能未收录)', mirror)
        return None

    # 用响应最终地址解析相对链接：镜像可能 302 到别的域名/路径，
    # 用请求前的 url 会把 files/x.pdf 错误地拼到原镜像上。
    pdf_url = resolve_pdf_url(pdf_url, resp.url or url)
    logger.debug('%s 解析到 PDF: %s', mirror, pdf_url)
    return _download_pdf(pdf_url, output_path, session, pdf_timeout)


def scihub_download(doi: str, output_path, mirrors: list | None = None,
                    landing_timeout: float = DEFAULT_LANDING_TIMEOUT,
                    pdf_timeout: float = DEFAULT_PDF_TIMEOUT,
                    user_agent: str = DEFAULT_USER_AGENT) -> Path | None:
    """按镜像顺序尝试下载 DOI 对应的 PDF。

    Args:
        doi: 已规范化的 DOI。
        output_path: 目标落盘路径。
        mirrors: 镜像列表；None 使用内置默认值。
        landing_timeout: 落地页请求超时（秒）。
        pdf_timeout: PDF 下载超时（秒）。
        user_agent: 请求使用的 User-Agent。

    Returns:
        成功时返回 ``Path``，全部镜像失败返回 ``None``。
    """
    output_path = Path(output_path)
    mirror_list = mirrors or list(DEFAULT_MIRRORS)
    session = make_session(user_agent)

    for mirror in mirror_list:
        logger.debug('尝试镜像: %s', mirror)
        result = try_mirror(doi, output_path, mirror, session,
                            landing_timeout, pdf_timeout)
        if result:
            logger.debug('成功 (%s): %s', mirror, result)
            return result

    return None
