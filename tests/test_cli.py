"""命令行参数校验与退出码。"""
import json

import pytest

from doi2pdf.cli import main


def run(capsys, *argv):
    """运行 CLI，返回 (退出码, stdout, stderr)。"""
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


class TestArgumentValidation:
    # 注意用 -t=value 形式：argparse 会把 "-inf" 当选项前缀，用空格分隔时
    # 报的是 "expected one argument"，测不到我们的有限数校验。
    @pytest.mark.parametrize('value', ['-1', '0', 'inf', 'nan', '-inf'])
    def test_bad_timeout_exits_2(self, capsys, value):
        code, _, err = run(capsys, '10.1/x', f'-t={value}')
        assert code == 2

    @pytest.mark.parametrize('value', ['-1', 'inf', 'nan', '-inf'])
    def test_bad_delay_exits_2(self, capsys, value):
        code, _, err = run(capsys, '10.1/x', f'-d={value}')
        assert code == 2

    def test_negative_value_via_space_separator(self, capsys):
        # "-t -1"（空格分隔）也走我们自己的校验，返回 2 而不是 SystemExit
        code, _, err = run(capsys, '10.1/x', '-t', '-1')
        assert code == 2
        assert '有限数' in err

    def test_negative_infinity_as_separate_arg_is_parsed_by_argparse(self, capsys):
        # 唯独 "-t -inf" 会被 argparse 当成选项前缀，在解析阶段就以 2 退出
        with pytest.raises(SystemExit) as exc:
            main(['10.1/x', '-t', '-inf'])
        assert exc.value.code == 2

    def test_infinite_delay_does_not_reach_sleep(self, capsys):
        # 回归: inf 曾通过"非负数"校验，随后 time.sleep(inf) 抛 OverflowError
        code, _, err = run(capsys, '10.1/x', '10.1/y', '-d', 'inf')
        assert code == 2
        assert '有限数' in err

    def test_no_input_exits_2(self, capsys):
        code, _, _ = run(capsys)
        assert code == 2

    def test_invalid_doi_exits_2(self, capsys):
        code, _, err = run(capsys, 'not-a-doi')
        assert code == 2
        assert '有效 DOI' in err

    def test_missing_txt_input_reports_file_error(self, capsys, tmp_path):
        source = tmp_path / 'missing.txt'
        code, _, err = run(capsys, str(source))
        assert code == 2
        assert '无法读取输入文件' in err
        assert str(source) in err

    def test_doi_ending_in_txt_is_not_read_as_file(self, capsys, tmp_path, monkeypatch):
        from doi2pdf import cli
        monkeypatch.setattr(cli, 'scihub_download',
                            lambda doi, target, **kwargs: target)
        code, out, _ = run(capsys, '10.1234/paper.txt',
                           '-o', str(tmp_path), '--json')
        assert code == 0
        assert json.loads(out)[0]['doi'] == '10.1234/paper.txt'

    def test_mixed_input_reports_invalid_doi(self, capsys, tmp_path, monkeypatch):
        from doi2pdf import cli

        source = tmp_path / 'dois.txt'
        source.write_text('10.1234/good\nnot-a-doi\n')
        monkeypatch.setattr(cli, 'scihub_download',
                            lambda doi, target, **kwargs: target)

        code, out, _ = run(capsys, str(source), '-o', str(tmp_path), '--json')
        records = json.loads(out)
        assert code == 1
        assert [(r['doi'], r['status']) for r in records] == [
            ('10.1234/good', 'ok'), ('not-a-doi', 'failed')]
        assert records[1]['error'] == '无效 DOI'

    def test_missing_config_exits_2(self, capsys, tmp_path):
        code, _, err = run(capsys, '10.1/x', '-c', str(tmp_path / 'missing.toml'))
        assert code == 2
        assert '配置错误' in err

    def test_empty_mirror_argument_exits_2(self, capsys):
        code, _, err = run(capsys, '10.1/x', '-m', '')
        assert code == 2
        assert '--mirror 不能为空' in err

    def test_case_variants_share_cached_pdf(self, capsys, tmp_path, monkeypatch):
        from doi2pdf import cli
        from doi2pdf.doi import doi_to_safe_filename

        target = tmp_path / doi_to_safe_filename('10.1039/d5cc03627e')
        target.write_bytes(b'cached')
        monkeypatch.setattr(cli, 'is_valid_pdf_file', lambda path: True)
        def unexpected_download(*args, **kwargs):
            pytest.fail('缓存命中时不应重新下载')
        monkeypatch.setattr(cli, 'scihub_download', unexpected_download)

        code, out, _ = run(capsys, '10.1039/D5CC03627E',
                           '10.1039/d5cc03627e', '-o', str(tmp_path), '--json')
        assert code == 0
        assert json.loads(out) == [{
            'doi': '10.1039/d5cc03627e', 'status': 'cached',
            'path': str(target), 'error': None}]


class TestConfigValidation:
    def test_env_config_missing_is_error_not_silent(self, capsys, monkeypatch, tmp_path):
        # 回归: DOI2PDF_CONFIG 指向不存在的文件时曾静默退回 ./doi2pdf.toml
        monkeypatch.chdir(tmp_path)
        (tmp_path / 'doi2pdf.toml').write_text('mirrors = ["https://local.example"]\n')
        monkeypatch.setenv('DOI2PDF_CONFIG', str(tmp_path / 'nope.toml'))
        code, _, err = run(capsys, '10.1/x')
        assert code == 2
        assert 'DOI2PDF_CONFIG' in err

    def test_explicit_config_file_is_loaded(self, capsys, tmp_path, monkeypatch):
        cfg = tmp_path / 'c.toml'
        cfg.write_text('mirrors = ["https://solo.example"]\ntimeouts = {landing = 7}\n')
        from doi2pdf.config import load_config
        monkeypatch.setenv('DOI2PDF_CONFIG', str(cfg))
        loaded = load_config()
        assert loaded.mirrors == ['https://solo.example']
        assert loaded.landing_timeout == 7

    def test_broken_toml_is_config_error(self, capsys, tmp_path):
        cfg = tmp_path / 'bad.toml'
        cfg.write_text('mirrors = [ broken\n')
        code, _, err = run(capsys, '10.1/x', '-c', str(cfg))
        assert code == 2
        assert '配置错误' in err


class TestVersion:
    def test_version_flag(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(['--version'])
        assert exc.value.code == 0

    def test_help_shows_current_filename(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(['--help'])
        assert exc.value.code == 0
        assert '10.1021%2Fol200992c.pdf' in capsys.readouterr().out
