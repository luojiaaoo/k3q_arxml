import os
import runpy
import subprocess
from pathlib import Path
from unittest.mock import patch

import click
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

    def test_versions_lists_discovered_schemas(self):
        result = self.runner.invoke(cli, ['versions'])
        assert result.exit_code == 0
        assert '4.2.2' in result.output.splitlines()
        assert '00048' in result.output.splitlines()
        assert not (self.root / 'autosar.py').exists()

    @pytest.mark.parametrize('arguments', [[], ['--schema-version', '4.2.2']])
    def test_mcp_uses_current_binding_without_generation(self, arguments):
        pytest.importorskip('mcp')
        with patch('k3q_arxml.mcp.server.create_server') as create, patch('k3q_arxml.cli._generate_binding') as generate:
            result = self.runner.invoke(cli, ['mcp', *arguments])
        assert result.exit_code == 0, result.output
        generate.assert_not_called()
        create.return_value.run.assert_called_once_with(transport='stdio')

    def test_mcp_selected_version_runs_in_fresh_process_without_replacing_source(self):
        pytest.importorskip('mcp')
        original = self.root / 'autosar.py'
        original.write_text('# original binding\n', encoding='utf-8')
        packages = []

        def generate(version, target, *, stderr):
            assert version == '00048' and stderr
            assert target != original
            target.write_text("SCHEMA_VERSION = '00048'\n", encoding='utf-8')
            packages.append(target.parent)

        def run(arguments, *, env):
            assert arguments[1:] == ['-P', '-m', 'k3q_arxml', 'mcp']
            assert Path(env['PYTHONPATH'].split(os.pathsep)[0]) == packages[0].parent
            assert (packages[0] / 'autosar.py').read_text(encoding='utf-8') == "SCHEMA_VERSION = '00048'\n"
            return subprocess.CompletedProcess(arguments, 7)

        with patch('k3q_arxml.cli._generate_binding', side_effect=generate), patch('k3q_arxml.cli.subprocess.run', side_effect=run):
            result = self.runner.invoke(cli, ['mcp', '--schema-version', '00048'])
        assert result.exit_code == 7
        assert original.read_text(encoding='utf-8') == '# original binding\n'
        assert packages and not packages[0].exists()

    def test_mcp_generation_failure_does_not_start_or_replace_binding(self):
        pytest.importorskip('mcp')
        original = self.root / 'autosar.py'
        original.write_text('# original binding\n', encoding='utf-8')
        with patch('k3q_arxml.cli._generate_binding', side_effect=click.ClickException('generation failed')), patch('k3q_arxml.cli.subprocess.run') as run:
            result = self.runner.invoke(cli, ['mcp', '--schema-version', '00048'])
        assert result.exit_code == 1 and 'generation failed' in result.output
        run.assert_not_called()
        assert original.read_text(encoding='utf-8') == '# original binding\n'

    def test_mcp_invalid_version_is_rejected_before_generation(self):
        with patch('k3q_arxml.cli._generate_binding') as generate:
            result = self.runner.invoke(cli, ['mcp', '--schema-version', 'unknown'])
        assert result.exit_code == 2
        generate.assert_not_called()
