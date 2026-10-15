import runpy
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from k3q_arxml.cli import cli


class TestGenerate:
    @pytest.fixture(autouse=True)
    def setup_cli(self, tmp_path):
        self.root = tmp_path / 'k3q arxml 测试'
        self.root.mkdir()
        self.schema = self.root / 'tiny.xsd'
        self.schema.write_text(
            '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:element name="sample" type="xs:string"/></xs:schema>',
            encoding='utf-8',
        )
        self.runner = CliRunner()
        with patch('k3q_arxml.cli.PACKAGE_ROOT', self.root), patch.dict('k3q_arxml.cli.SCHEMAS', {'4.2.2': self.schema, '00048': self.schema}):
            yield

    def test_generates_real_module_and_replaces_current_version(self):
        entrypoint = self.root / '__init__.py'
        entrypoint.write_text('# public entrypoint\n', encoding='utf-8')
        for version in ('4.2.2', '00048'):
            result = self.runner.invoke(cli, ['generate', version])
            assert result.exit_code == 0, result.output
            # 每次执行源文件，避免同一进程的模块缓存干扰版本更换验证。
            module = runpy.run_path(str(self.root / 'autosar.py'))
            assert module['SCHEMA_VERSION'] == version
            assert module['Sample'](value='typed').value == 'typed'
            assert entrypoint.read_text(encoding='utf-8') == '# public entrypoint\n'
            assert not list(self.root.glob('.codegen-*'))

    def test_generation_failure_keeps_previous_binding(self):
        previous = self.root / 'autosar.py'
        previous.write_text('# previous working binding\n', encoding='utf-8')
        self.schema.write_text('invalid XML', encoding='utf-8')
        result = self.runner.invoke(cli, ['generate', '4.2.2'])
        assert result.exit_code == 1
        assert 'xsdata' in result.output
        assert previous.read_text(encoding='utf-8') == '# previous working binding\n'
        assert not list(self.root.glob('.codegen-*'))

    def test_invalid_version_does_not_generate_a_binding(self):
        result = self.runner.invoke(cli, ['generate', 'unknown'])
        assert result.exit_code == 2
        assert not (self.root / 'autosar.py').exists()

    def test_versions_does_not_require_a_generated_module(self):
        result = self.runner.invoke(cli, ['versions'])
        assert result.exit_code == 0
        assert '4.2.2' in result.output.splitlines()
        assert '00048' in result.output.splitlines()
        assert not (self.root / 'autosar.py').exists()
