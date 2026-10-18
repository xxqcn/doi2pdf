"""配置读取的类型与路径校验。"""
import pytest

from doi2pdf.config import load_config


class TestConfigTypeErrors:
    @pytest.mark.parametrize('content', [
        'mirrors = [1]\n',
        'mirrors = "https://x"\n',
        'mirrors = 42\n',
        'mirrors = []\n',
        'mirrors = [""]\n',
        'timeouts = {landing = "abc"}\n',
        'request = {user_agent = 123}\n',
        'scihub = 1\n',
        'scihub = "bad"\n',
    ])
    def test_bad_types_raise_value_error(self, tmp_path, content):
        cfg = tmp_path / 'c.toml'
        cfg.write_text(content)
        with pytest.raises(ValueError):
            load_config(cfg)

    def test_ok_config(self, tmp_path):
        cfg = tmp_path / 'c.toml'
        cfg.write_text('mirrors = ["https://a.example/"]\n'
                       'timeouts = {landing = 5}\n')
        loaded = load_config(cfg)
        assert loaded.mirrors == ['https://a.example']   # 尾部斜杠被去掉
        assert loaded.landing_timeout == 5.0

    def test_omitted_mirrors_use_defaults(self, tmp_path):
        cfg = tmp_path / 'c.toml'
        cfg.write_text('timeouts = {landing = 5}\n')
        loaded = load_config(cfg)
        assert loaded.mirrors

    def test_missing_explicit_path_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / 'nope.toml')

    def test_broken_toml_raises_value_error(self, tmp_path):
        cfg = tmp_path / 'c.toml'
        cfg.write_text('mirrors = [ broken\n')
        with pytest.raises(ValueError):
            load_config(cfg)
