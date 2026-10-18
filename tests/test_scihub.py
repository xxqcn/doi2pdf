"""落地页 URL 构造与 PDF 链接解析。"""
from doi2pdf.scihub import build_landing_url, parse_pdf_url, resolve_pdf_url


class TestBuildLandingUrl:
    def test_plain_doi(self):
        assert (build_landing_url('https://sci-hub.ee', '10.1039/d5cc03627e')
                == 'https://sci-hub.ee/10.1039/d5cc03627e')

    def test_trailing_slash_on_mirror(self):
        assert (build_landing_url('https://sci-hub.ee/', '10.1/x')
                == 'https://sci-hub.ee/10.1/x')

    def test_doi_query_char_is_encoded(self):
        # 不编码的话 ?b 会被服务器当成查询参数，请求到的是别的地址
        url = build_landing_url('https://sci-hub.ee', '10.1234/a?b')
        assert url == 'https://sci-hub.ee/10.1234/a%3Fb'
        from urllib.parse import urlsplit
        assert urlsplit(url).query == ''

    def test_doi_hash_and_ampersand_encoded(self):
        assert build_landing_url('https://m', '10.1/a#b').endswith('/10.1/a%23b')
        assert build_landing_url('https://m', '10.1/a&b').endswith('/10.1/a%26b')

    def test_slash_stays_as_separator(self):
        assert build_landing_url('https://m', '10.1/a/b') == 'https://m/10.1/a/b'


class TestResolvePdfUrl:
    LANDING = 'https://m.example/10.1234/a'

    def test_absolute_unchanged(self):
        assert (resolve_pdf_url('https://cdn/x.pdf', self.LANDING)
                == 'https://cdn/x.pdf')

    def test_protocol_relative(self):
        assert (resolve_pdf_url('//cdn/x.pdf', self.LANDING)
                == 'https://cdn/x.pdf')

    def test_root_relative(self):
        assert (resolve_pdf_url('/x.pdf', self.LANDING)
                == 'https://m.example/x.pdf')

    def test_page_relative_uses_landing_path(self):
        # 相对链接必须以落地页真实地址为基准，而不是镜像根地址
        assert (resolve_pdf_url('files/paper.pdf', self.LANDING)
                == 'https://m.example/10.1234/files/paper.pdf')

    def test_bare_filename_uses_landing_dir(self):
        assert (resolve_pdf_url('paper.pdf', self.LANDING)
                == 'https://m.example/10.1234/paper.pdf')

    def test_keeps_query_fragment(self):
        out = resolve_pdf_url('/p.pdf#view=FitH', self.LANDING)
        assert out == 'https://m.example/p.pdf#view=FitH'


class TestParsePdfUrl:
    def test_embed_wins(self):
        html = ('<embed type="application/pdf" src="/a.pdf">'
                '<iframe id="pdf" src="/b.pdf"></iframe>')
        assert parse_pdf_url(html) == '/a.pdf'

    def test_iframe_when_no_embed(self):
        html = '<iframe id="pdf" src="/b.pdf"></iframe>'
        assert parse_pdf_url(html) == '/b.pdf'

    def test_anchor_fallback(self):
        html = '<a href="/c.pdf">download</a>'
        assert parse_pdf_url(html) == '/c.pdf'

    def test_none_when_absent(self):
        assert parse_pdf_url('<html><body>no pdf here</body></html>') is None
