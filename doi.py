"""DOI 规范化与文件名生成。

从粘贴来源拿到的 DOI 往往带 URL 前缀、尾部标点，这些如果不清理会直接拼进
Sci-Hub 的落地页 URL 而导致 404。但清理必须保守：DOI 本身允许 ``.`` ``/``
``(`` ``)`` ``?`` ``&`` 等字符，过度剥离会把一篇文献改写成另一篇。
"""
import hashlib
import re
import urllib.parse

# 文件名 stem 的字节上限（常见文件系统 255，留出扩展名空间）
_MAX_STEM_BYTES = 200


def clean_doi(raw: str) -> str:
    """规范化 DOI：去 URL 前缀和尾部噪音，并统一为小写。

    刻意**不**做的事（这些会改写有效 DOI）：
    - 不剥离 ``?`` / ``&`` 及其后内容：DOI 可以合法包含它们
    - 不把 ``.pdf`` / ``/html`` 等当扩展名删掉：``10.1234/foo.pdf`` 与
      ``10.1234/foo`` 是两篇不同文献
    - 不截断 Wiley 的 ``journal.NNNNNNText`` 形式

    无效输入返回空字符串（不以 ``10.`` 开头或不含 ``/``）。
    """
    if not raw:
        return ''
    raw = raw.strip()
    # 去 HTML 标签 (如从链接里粘贴带出的 </a>)，但保留 SICI 的 <...>
    raw = re.sub(r'<[a-zA-Z/][^>]*>', '', raw)

    # DOI 解析器 URL：查询参数属于 URL，不属于 DOI，必须先剥离再解码。
    #   https://doi.org/10.1234/foo?utm_source=x  → 10.1234/foo
    #   https://doi.org/10.1234/foo%3Fbar         → 10.1234/foo?bar（%3F 编码在路径里，保留）
    #   https://doi.org/10.1234/foo%3Fbar?utm=x   → 10.1234/foo?bar
    m = re.match(r'^https?://(?:dx\.)?doi\.org/([^?#]*)(?:[?#].*)?$', raw, flags=re.I)
    if m:
        raw = urllib.parse.unquote(m.group(1))
    else:
        raw = urllib.parse.unquote(raw)

    # 去粘贴带出的尾部标点（DOI 合法字符集里没有 , ; : 收尾的用法）
    raw = raw.strip().rstrip('.,;:').lower()
    if not raw.startswith('10.'):
        return ''
    if '/' not in raw:
        return ''  # 有效 DOI 必须含斜杠
    return raw


def doi_to_safe_filename(doi: str, extension: str = '.pdf') -> str:
    """DOI → 不冲突的安全文件名。

    直接把 ``/`` 换成 ``_`` 会产生碰撞：``10.1234/a/b`` 与 ``10.1234/a_b``
    都会得到 ``10.1234_a_b.pdf``，导致缓存命中错误、甚至覆盖另一篇文献。

    这里改用可逆的百分号编码：``/`` → ``%2F``，``?`` → ``%3F`` 等。
    由于原始 DOI 里不会出现 ``%``（合法 DOI 字符集不含它），编码无歧义，
    不同 DOI 必然得到不同文件名，且常规 DOI 的文件名保持可读。

    例：
        10.1039/d5cc03627e          → 10.1039%2Fd5cc03627e.pdf
        10.1234/a/b                 → 10.1234%2Fa%2Fb.pdf
        10.1234/a_b                 → 10.1234%2Fa_b.pdf   (与上面不同)
    """
    doi = doi.lower()  # 直接调用本函数时也要与 clean_doi 的缓存键一致
    encoded = urllib.parse.quote(doi, safe='')  # 只保留字母数字和 . - _ ~
    if not encoded:  # 极端兜底：确保文件名非空
        encoded = hashlib.sha1(doi.encode('utf-8')).hexdigest()[:16]

    # 多数文件系统单个文件名上限 255 字节，留出扩展名余量。
    # 超长时不截断（截断会造成新碰撞），改为"前缀 + 全量哈希"，
    # 前缀仅用于人工辨识，唯一性由哈希保证。
    limit = _MAX_STEM_BYTES
    if len(encoded.encode('utf-8')) > limit:
        digest = hashlib.sha1(doi.encode('utf-8')).hexdigest()
        prefix_budget = limit - len(digest) - 1
        prefix = encoded.encode('utf-8')[:prefix_budget].decode('utf-8', 'ignore')
        encoded = f'{prefix}-{digest}'
    return encoded + extension
