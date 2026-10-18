#!/usr/bin/env python3
"""doi2pdf 命令行入口 —— 按 DOI 从 Sci-Hub 下载 PDF。

原理：DOI → 镜像落地页 → 解析 PDF 直链 → 下载并校验 → 落盘。
只做这一件事，不抓元数据、不转 Markdown、不写数据库。
"""
import argparse
import json
import logging
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from .config import load_config
    from .doi import clean_doi, doi_to_safe_filename
    from .scihub import scihub_download
    from .validate import is_valid_pdf_file
except ImportError:
    from config import load_config
    from doi import clean_doi, doi_to_safe_filename
    from scihub import scihub_download
    from validate import is_valid_pdf_file

__version__ = '1.0.2'

EPILOG = """\
示例:
  doi2pdf 10.1021/ol200992c       # 生成 10.1021%2Fol200992c.pdf
  doi2pdf dois.txt -o ~/papers    # 批量下载，每行一个 DOI
  doi2pdf - < dois.txt            # 从标准输入读取

配置优先级: --config > DOI2PDF_CONFIG > ./doi2pdf.toml
            > ~/.config/doi2pdf/doi2pdf.toml > 内置默认值
退出码: 0 成功，1 有失败，2 参数或配置错误
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='doi2pdf',
        description='按 DOI 从 Sci-Hub 下载论文 PDF。',
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )
    parser.add_argument(
        'inputs', nargs='*', metavar='INPUT',
        help='DOI、.txt 文件或 -（标准输入）')
    parser.add_argument(
        '-o', '--output', default='.', metavar='DIR',
        help='输出目录（默认当前目录）')
    parser.add_argument(
        '-f', '--force', action='store_true',
        help='强制重新下载')
    parser.add_argument(
        '-c', '--config', default=None, metavar='FILE',
        help='配置文件路径')
    parser.add_argument(
        '-m', '--mirror', action='append', default=None, metavar='URL',
        help='覆盖镜像列表（可重复）')
    parser.add_argument(
        '-t', '--timeout', type=float, default=None, metavar='SEC',
        help='请求超时秒数')
    parser.add_argument(
        '-d', '--delay', type=float, default=0.0, metavar='SEC',
        help='每篇之间等待秒数（默认 0）')
    parser.add_argument(
        '-q', '--quiet', action='store_true',
        help='只输出错误')
    parser.add_argument(
        '-v', '--verbose', action='store_true',
        help='显示镜像尝试过程')
    parser.add_argument(
        '--json', dest='as_json', action='store_true',
        help='输出 JSON 结果')
    parser.add_argument(
        '-V', '--version', action='version',
        version=f'doi2pdf {__version__}', help='显示版本')
    parser.add_argument(
        '-h', '--help', action='help',
        help='显示帮助')
    return parser


def read_inputs(inputs: list, invalid: list | None = None) -> list:
    """把命令行输入展开成 DOI 列表。

    支持的输入形式：DOI、txt 文件（每行一个，``#`` 开头为注释）、``-`` 读 stdin。
    """
    dois: list = []
    for item in inputs:
        if item == '-':
            lines = sys.stdin.read().splitlines()
        else:
            path = Path(item)
            # DOI 后缀本身也可能是 .txt，先识别 DOI 再把其它 .txt 当文件。
            # 缺失或不可读的文件由 main 报输入错误，不能误报成无效 DOI。
            if path.suffix.lower() == '.txt' and (path.is_file() or not clean_doi(item)):
                lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
            else:
                lines = [item]
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            # 一行可能有多个空白分隔的 DOI，逐个规范化
            for token in line.split():
                cleaned = clean_doi(token)
                if cleaned and cleaned not in dois:
                    dois.append(cleaned)
                elif not cleaned and invalid is not None:
                    invalid.append(token)
    return dois


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format='%(levelname)s %(name)s: %(message)s',
        stream=sys.stderr,
    )

    # 数值参数先校验，避免非法值一路传到 requests/time.sleep 才抛异常。
    # 必须同时排除 NaN 与 ±inf：inf > 0 会通过"正数"检查，随后
    # time.sleep(inf) 抛 OverflowError；nan 的比较恒为 False 也会漏过。
    if args.timeout is not None and not (math.isfinite(args.timeout) and args.timeout > 0):
        print(f'参数错误: --timeout 必须是大于 0 的有限数（收到 {args.timeout}）',
              file=sys.stderr)
        return 2
    if not (math.isfinite(args.delay) and args.delay >= 0):
        print(f'参数错误: --delay 必须是大于等于 0 的有限数（收到 {args.delay}）',
              file=sys.stderr)
        return 2

    try:
        cfg = load_config(args.config)
    except (FileNotFoundError, ValueError) as exc:
        print(f'配置错误: {exc}', file=sys.stderr)
        return 2

    for name, value in (('timeouts.landing', cfg.landing_timeout),
                        ('timeouts.pdf', cfg.pdf_timeout)):
        if not (math.isfinite(value) and value > 0):
            print(f'配置错误: {name} 必须是大于 0 的有限数（当前 {value}）',
                  file=sys.stderr)
            return 2

    if args.mirror is not None and any(not m.strip() for m in args.mirror):
        print('参数错误: --mirror 不能为空', file=sys.stderr)
        return 2
    mirrors = args.mirror if args.mirror is not None else cfg.mirrors
    if not mirrors:
        print('配置错误: 镜像列表为空，请在 doi2pdf.toml 中设置 mirrors', file=sys.stderr)
        return 2

    if not args.inputs:
        parser.print_help(sys.stderr)
        return 2

    invalid_inputs = []
    try:
        dois = read_inputs(args.inputs, invalid_inputs)
    except OSError as exc:
        print(f'无法读取输入文件: {exc}', file=sys.stderr)
        return 2
    if not dois:
        print('未从输入中解析出任何有效 DOI（应以 10. 开头且包含 /）', file=sys.stderr)
        for token in invalid_inputs:
            print(f'无效 DOI: {token}', file=sys.stderr)
        return 2

    output_dir = Path(args.output).expanduser()
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f'无法创建输出目录 {output_dir}: {exc}', file=sys.stderr)
        return 2

    landing_timeout = args.timeout if args.timeout is not None else cfg.landing_timeout
    pdf_timeout = args.timeout if args.timeout is not None else cfg.pdf_timeout

    if args.verbose and not args.as_json:
        print(f'配置文件: {cfg.source}', file=sys.stderr)
        print(f'镜像顺序: {", ".join(mirrors)}', file=sys.stderr)

    results = []
    for index, doi in enumerate(dois):
        if index and args.delay > 0:
            time.sleep(args.delay)

        target = output_dir / doi_to_safe_filename(doi)
        record = {'doi': doi, 'status': 'failed', 'path': None, 'error': None}

        if target.exists() and not args.force and is_valid_pdf_file(target):
            record.update(status='cached', path=str(target))
            results.append(record)
            if not args.quiet and not args.as_json:
                print(f'SKIP: {doi}  (已存在: {target})')
            continue

        result = scihub_download(
            doi, target, mirrors=mirrors,
            landing_timeout=landing_timeout, pdf_timeout=pdf_timeout,
            user_agent=cfg.user_agent,
        )
        if result:
            record.update(status='ok', path=str(result))
            if not args.quiet and not args.as_json:
                print(f'OK: {result}')
        else:
            record['error'] = '全部镜像均未能取到该 PDF'
            if not args.as_json:
                print(f'FAIL: {doi}  (镜像: {len(mirrors)} 个均失败；'
                      f'文献可能未收录，或镜像已失效，可用 -m 指定镜像重试)',
                      file=sys.stderr)
        results.append(record)

    for token in invalid_inputs:
        results.append({'doi': token, 'status': 'failed', 'path': None,
                        'error': '无效 DOI'})
        if not args.as_json:
            print(f'FAIL: {token}  (无效 DOI)', file=sys.stderr)

    if args.as_json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    elif not args.quiet:
        ok = sum(1 for r in results if r['status'] == 'ok')
        cached = sum(1 for r in results if r['status'] == 'cached')
        failed = sum(1 for r in results if r['status'] == 'failed')
        print(f'\n完成: 新下载 {ok} | 已存在跳过 {cached} | 失败 {failed} '
              f'| 共 {len(results)}')

    return 1 if any(r['status'] == 'failed' for r in results) else 0


if __name__ == '__main__':
    sys.exit(main())
