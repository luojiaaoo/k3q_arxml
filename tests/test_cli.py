"""内部绑定生成工具回归；不提供用户命令行。"""

import runpy
from unittest.mock import patch

import click
import pytest

from k3q_arxml.cli import _generate_binding
from k3q_arxml.cli import main as build_bindings


class TestGenerate:
    @pytest.fixture(autouse=True)
    def setup_schema(self, tmp_path):
        self.root = tmp_path / 'k3q arxml 测试'
        self.root.mkdir()
        self.schema = self.root / 'tiny.xsd'
        self.schema.write_text(
            '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:element name="sample" type="xs:string"/></xs:schema>',
            encoding='utf-8',
        )
        with patch.dict('k3q_arxml.cli.SCHEMAS', {'4.2.2': self.schema, '00048': self.schema}):
            yield

    def test_generates_independent_modules_without_replacing_other_versions(self):
        entrypoint = self.root / '__init__.py'
        entrypoint.write_text('# public entrypoint\n', encoding='utf-8')
        outputs = {}
        for version in ('4.2.2', '00048'):
            target = self.root / f'autosar_{version.replace(".", "_")}.py'
            _generate_binding(version, target)
            module = runpy.run_path(str(target))
            assert module['SCHEMA_VERSION'] == version
            assert module['Sample'](value='typed').value == 'typed'
            outputs[target] = target.read_bytes()
            assert all(path.read_bytes() == content for path, content in outputs.items())
            assert entrypoint.read_text(encoding='utf-8') == '# public entrypoint\n'
            assert not list(self.root.glob('.codegen-*'))

    def test_generation_failure_keeps_previous_binding(self):
        target = self.root / 'autosar_4_2_2.py'
        target.write_text('# previous working binding\n', encoding='utf-8')
        self.schema.write_text('invalid XML', encoding='utf-8')
        with pytest.raises(click.ClickException, match='xsdata'):
            _generate_binding('4.2.2', target)
        assert target.read_text(encoding='utf-8') == '# previous working binding\n'
        assert not list(self.root.glob('.codegen-*'))

    def test_batch_generation_selects_versions_and_writes_beside_each_schema_directory(self):
        output = self.root / '批量 输出'
        with patch('sys.argv', ['cli.py', '--versions', '4.2.2', '00048', '4.2.2', '--output', str(output), '--jobs', '2']):
            build_bindings()
        assert {path.name for path in output.iterdir()} == {'autosar_4_2_2', 'autosar_00048'}
        for version in ('4.2.2', '00048'):
            suffix = version.replace('.', '_')
            target = output / f'autosar_{suffix}' / f'autosar_{suffix}.py'
            module = runpy.run_path(str(target))
            assert module['SCHEMA_VERSION'] == version
            assert module['Sample'](value='batch').value == 'batch'
            assert not list(target.parent.glob('.codegen-*'))
