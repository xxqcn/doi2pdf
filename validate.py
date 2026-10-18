"""PDF 有效性校验。

只检查 ``%PDF`` 魔数是不够的：Sci-Hub 在 DDoS-Guard 拦截或文献不存在时，
会返回 HTML 错误页、陷阱页，甚至被截断的字节流。这里用 pypdf 走 PDF
页树（``/Root`` → ``/Pages`` → Kids）实际解析一遍，能至少解出 1 页才认账。
"""
from io import BytesIO
from pathlib import Path


def _parse_pdf_pages(source) -> int:
    """按页树解析 PDF，返回页数；不可读返回 0。"""
    import warnings

    from pypdf import PdfReader

    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        reader = PdfReader(source, strict=False)
        if not reader.trailer.get('/Root'):
            return 0
        return len(reader.pages)


def is_valid_pdf(content: bytes) -> bool:
    """校验下载得到的字节流是否为至少一页的可解析 PDF。"""
    if not isinstance(content, bytes) or len(content) < 100:
        return False
    if not content.startswith(b'%PDF'):
        return False
    try:
        return _parse_pdf_pages(BytesIO(content)) >= 1
    except Exception:
        return False


def is_valid_pdf_file(path) -> bool:
    """校验磁盘上的 PDF 文件（用于跳过已下载的有效缓存）。"""
    try:
        path = Path(path)
        if not path.is_file() or path.stat().st_size < 100:
            return False
        with path.open('rb') as stream:
            if stream.read(4) != b'%PDF':
                return False
            stream.seek(0)
            return _parse_pdf_pages(stream) >= 1
    except Exception:
        return False
