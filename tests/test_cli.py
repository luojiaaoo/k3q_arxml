import runpy
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from click.testing import CliRunner

from k3q_arxml.cli import cli


class GenerateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory(prefix='k3q arxml 测试 ')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.schema = self.root / 'tiny.xsd'
        self.schema.write_text(
            '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:element name="sample" type="xs:string"/></xs:schema>',
            encoding='utf-8',
        )
        self.root_patch = patch('k3q_arxml.cli.PACKAGE_ROOT', self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.schemas_patch = patch.dict('k3q_arxml.cli.SCHEMAS', {'4.2.2': self.schema, '00048': self.schema})
        self.schemas_patch.start()
        self.addCleanup(self.schemas_patch.stop)
        self.runner = CliRunner()

    def test_generates_real_module_and_replaces_current_version(self):
        entrypoint = self.root / '__init__.py'
        entrypoint.write_text('# public entrypoint\n', encoding='utf-8')
        for version in ('4.2.2', '00048'):
            with self.subTest(version=version):
                result = self.runner.invoke(cli, ['generate', version])
                self.assertEqual(result.exit_code, 0, result.output)
                # 每次执行源文件，避免同一进程的模块缓存干扰版本更换验证。
                module = runpy.run_path(str(self.root / 'autosar.py'))
                self.assertEqual(module['SCHEMA_VERSION'], version)
                self.assertEqual(module['Sample'](value='typed').value, 'typed')
                self.assertEqual(entrypoint.read_text(encoding='utf-8'), '# public entrypoint\n')
                self.assertFalse(list(self.root.glob('.codegen-*')))

    def test_generation_failure_keeps_previous_binding(self):
        previous = self.root / 'autosar.py'
        previous.write_text('# previous working binding\n', encoding='utf-8')
        self.schema.write_text('invalid XML', encoding='utf-8')
        result = self.runner.invoke(cli, ['generate', '4.2.2'])
        self.assertEqual(result.exit_code, 1)
        self.assertIn('xsdata', result.output)
        self.assertEqual(previous.read_text(encoding='utf-8'), '# previous working binding\n')
        self.assertFalse(list(self.root.glob('.codegen-*')))

    def test_invalid_version_does_not_generate_a_binding(self):
        result = self.runner.invoke(cli, ['generate', 'unknown'])
        self.assertEqual(result.exit_code, 2)
        self.assertFalse((self.root / 'autosar.py').exists())

    def test_versions_does_not_require_a_generated_module(self):
        result = self.runner.invoke(cli, ['versions'])
        self.assertEqual(result.exit_code, 0)
        self.assertIn('4.2.2', result.output.splitlines())
        self.assertIn('00048', result.output.splitlines())
        self.assertFalse((self.root / 'autosar.py').exists())
