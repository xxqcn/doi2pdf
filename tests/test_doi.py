"""DOI 清洗与文件名生成。"""
from doi2pdf.doi import clean_doi, doi_to_safe_filename


class TestCleanDoi:
    def test_keeps_doi_verbatim(self):
        assert clean_doi('10.1039/d5cc03627e') == '10.1039/d5cc03627e'

    def test_keeps_query_characters(self):
        # DOI 允许 ? & #，剥离会把文献改写成另一篇
        assert clean_doi('10.1234/a?b') == '10.1234/a?b'
        assert clean_doi('10.1234/a&b') == '10.1234/a&b'

    def test_keeps_pdf_suffix(self):
        # 10.1234/foo.pdf 与 10.1234/foo 是两篇不同文献
        assert clean_doi('10.1234/foo.pdf') == '10.1234/foo.pdf'
        assert clean_doi('10.1234/foo') == '10.1234/foo'

    def test_strips_resolver_prefix_and_trailing_punctuation(self):
        assert clean_doi('https://doi.org/10.1039/d5cc03627e.') == '10.1039/d5cc03627e'
        assert clean_doi('http://dx.doi.org/10.1039/d5cc03627e') == '10.1039/d5cc03627e'

    def test_normalizes_sici_case(self):
        doi = '10.1002/(SICI)1099-0682(199806)1998:6<843::aid-ejic843>3.0.co;2-y'
        assert clean_doi(doi) == doi.lower()

    def test_normalizes_doi_case(self):
        assert clean_doi('10.1039/D5CC03627E') == '10.1039/d5cc03627e'
        assert clean_doi('https://doi.org/10.1039/D5CC03627E') == '10.1039/d5cc03627e'

    def test_rejects_invalid(self):
        assert clean_doi('') == ''
        assert clean_doi('not-a-doi') == ''
        assert clean_doi('10.1234') == ''      # 无斜杠
        assert clean_doi('abc/def') == ''      # 无 10. 前缀


class TestFilename:
    def test_slash_and_underscore_do_not_collide(self):
        a = doi_to_safe_filename('10.1234/a/b')
        b = doi_to_safe_filename('10.1234/a_b')
        assert a != b

    def test_filename_is_reversible(self):
        from urllib.parse import unquote
        for doi in ['10.1039/d5cc03627e', '10.1234/a/b', '10.1234/a?b']:
            name = doi_to_safe_filename(doi)
            assert name.endswith('.pdf')
            assert unquote(name[:-4]) == doi

    def test_no_path_separators(self):
        for doi in ['10.1234/a/b', '10.1234/a?b', '10.1234/a b']:
            name = doi_to_safe_filename(doi)
            assert '/' not in name and '\\' not in name

    def test_stable(self):
        assert doi_to_safe_filename('10.1/x') == doi_to_safe_filename('10.1/x')

    def test_filename_is_case_insensitive(self):
        assert (doi_to_safe_filename('10.1039/D5CC03627E')
                == doi_to_safe_filename('10.1039/d5cc03627e'))


class TestResolverUrlQuery:
    """粘贴带查询参数的解析器链接，不能把参数带进 DOI。"""

    def test_strips_url_query(self):
        assert clean_doi('https://doi.org/10.1234/foo?utm_source=example') == '10.1234/foo'

    def test_strips_url_fragment(self):
        assert clean_doi('https://doi.org/10.1234/foo#section') == '10.1234/foo'

    def test_keeps_encoded_question_mark_in_path(self):
        # %3F 编码在 DOI 路径里，属于 DOI 本身
        assert clean_doi('https://doi.org/10.1234/foo%3Fbar') == '10.1234/foo?bar'

    def test_encoded_question_mark_with_tracking_query(self):
        assert (clean_doi('https://doi.org/10.1234/foo%3Fbar?utm=x')
                == '10.1234/foo?bar')

    def test_bare_doi_keeps_question_mark(self):
        # 裸 DOI 里的 ? 不是 URL 查询参数，必须保留
        assert clean_doi('10.1234/foo?bar') == '10.1234/foo?bar'


class TestFilenameLength:
    def test_long_doi_stays_within_filesystem_limit(self):
        name = doi_to_safe_filename('10.1234/' + 'a' * 250)
        assert len(name.encode('utf-8')) <= 255

    def test_long_doi_filename_is_unique(self):
        a = doi_to_safe_filename('10.1234/' + 'a' * 250)
        b = doi_to_safe_filename('10.1234/' + 'a' * 249)
        assert a != b

    def test_long_doi_file_can_be_created(self, tmp_path):
        name = doi_to_safe_filename('10.1234/' + 'a' * 250)
        (tmp_path / name).write_bytes(b'x')
        assert (tmp_path / name).exists()
