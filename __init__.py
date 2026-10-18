"""doi2pdf —— 按 DOI 从 Sci-Hub 下载 PDF。"""
__version__ = '1.0.2'

from .scihub import build_landing_url, parse_pdf_url, resolve_pdf_url, scihub_download

__all__ = ['__version__', 'scihub_download', 'parse_pdf_url',
           'resolve_pdf_url', 'build_landing_url']
