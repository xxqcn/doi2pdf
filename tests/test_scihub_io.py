"""下载路径的 IO 与重定向行为（全部使用模拟响应，不访问网络）。"""
import requests

from doi2pdf import scihub


class _Resp:
    def __init__(self, text='', content=b'', status=200, url=''):
        self.text = text
        self.content = content
        self.status_code = status
        self.url = url


class _Session:
    """记录请求 URL，并按预设返回响应。"""

    def __init__(self, landing, pdf):
        self._landing = landing
        self._pdf = pdf
        self.requested = []

    def get(self, url, timeout=None):
        self.requested.append(url)
        return self._pdf if url != self._landing_url else self._landing

    @property
    def _landing_url(self):
        return self.requested[0] if self.requested else ''


PDF_BYTES = b'%PDF-1.4\n' + b'\x00' * 200


def _valid_pdf_response(url):
    return _Resp(content=PDF_BYTES, url=url)


class TestRedirectBase:
    def test_relative_link_uses_final_response_url(self, tmp_path, monkeypatch):
        """落地页 302 到 CDN 后，相对链接必须基于 resp.url 解析。"""
        monkeypatch.setattr(scihub, 'is_valid_pdf', lambda c: c == PDF_BYTES)

        landing = _Resp(
            text='<embed type="application/pdf" src="files/paper.pdf">',
            url='https://cdn.example.com/papers/10.1234/a',
        )
        pdf = _valid_pdf_response('https://cdn.example.com/papers/10.1234/files/paper.pdf')

        class S:
            def get(self, url, timeout=None):
                if 'cdn.example.com' in url and url.endswith('paper.pdf'):
                    return pdf
                return landing

        out = tmp_path / 'x.pdf'
        result = scihub.try_mirror('10.1234/a', out, 'https://mirror.example', S())
        assert result == out

    def test_resolve_uses_final_url(self):
        landing = 'https://cdn.example.com/papers/10.1234/a'
        assert (scihub.resolve_pdf_url('files/paper.pdf', landing)
                == 'https://cdn.example.com/papers/10.1234/files/paper.pdf')


class TestWriteFailure:
    def test_mkstemp_permission_error_is_download_failure(self, tmp_path, monkeypatch):
        """mkstemp 抛 PermissionError 时应返回 None，不向 CLI 冒 traceback。"""
        monkeypatch.setattr(scihub, 'is_valid_pdf', lambda c: c == PDF_BYTES)

        def boom(*a, **k):
            raise PermissionError('read-only')

        monkeypatch.setattr(scihub.tempfile, 'mkstemp', boom)

        resp = _valid_pdf_response('https://m/x.pdf')
        session = type('S', (), {'get': lambda self, u, timeout=None: resp})()
        result = scihub._download_pdf('https://m/x.pdf', tmp_path / 'a.pdf',
                                      session, 5)
        assert result is None

    def test_mkdir_permission_error_is_download_failure(self, tmp_path, monkeypatch):
        monkeypatch.setattr(scihub, 'is_valid_pdf', lambda c: c == PDF_BYTES)

        def boom(*a, **k):
            raise PermissionError('denied')

        monkeypatch.setattr(scihub.Path, 'mkdir', boom, raising=False)

        resp = _valid_pdf_response('https://m/x.pdf')
        session = type('S', (), {'get': lambda self, u, timeout=None: resp})()
        result = scihub._download_pdf('https://m/x.pdf',
                                      tmp_path / 'deep' / 'a.pdf', session, 5)
        assert result is None
