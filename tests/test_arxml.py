import logging
import unittest
from pathlib import Path
from shutil import copy2
from tempfile import TemporaryDirectory
from types import ModuleType
from unittest.mock import patch

from k3q_arxml import ArxmlFile, IOArxml


class ArxmlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from k3q_arxml import autosar
        except ImportError:
            raise unittest.SkipTest('请先运行 uv run python -m k3q_arxml generate 4.2.2')
        if autosar.SCHEMA_VERSION != '4.2.2':
            raise unittest.SkipTest('ARXML 样例测试需要生成 4.2.2 绑定')
        cls.autosar = autosar

    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = str(Path(self.temporary.name) / 'sample.arxml')
        fixture = Path(__file__).resolve().parents[1] / 'test' / 'ThrottlePositionControlComposition.arxml'
        copy2(fixture, self.path)
        self.logger = logging.getLogger('k3q_arxml.arxml_file')
        self.previous_level = self.logger.level
        self.logger.setLevel(logging.ERROR)
        self.addCleanup(self.logger.setLevel, self.previous_level)

    def test_native_module_and_round_trip_preserve_objects_and_references(self):
        self.assertIsInstance(self.autosar, ModuleType)
        original = IOArxml([self.path])
        paths = set(original.objects)
        references = {ref: [(obj.value, owner) for obj, owner, _ in rows] for ref, rows in original.references.items()}
        self.assertTrue(paths)
        self.assertTrue(references)
        file = original.get_file(self.path)
        self.assertEqual(file.schema_version, '4.2.2')
        original.flush_to_file()
        reloaded = IOArxml([self.path])
        self.assertEqual(set(reloaded.objects), paths)
        self.assertEqual({ref: [(obj.value, owner) for obj, owner, _ in rows] for ref, rows in reloaded.references.items()}, references)
        self.assertEqual(reloaded.get_file(self.path).root, file.root)
        self.assertTrue(file.xml_schema_location.endswith('AUTOSAR_4-2-2.xsd'))

    def test_shared_paths_keep_separate_objects_and_file_identity(self):
        other_path = str(Path(self.temporary.name) / 'other.arxml')
        copy2(self.path, other_path)
        document = IOArxml([self.path, other_path])
        packages = document.ar(self.autosar.ArPackage)
        self.assertTrue(packages)
        matches = document.find(packages[0].ref)
        self.assertEqual([obj.filename for obj in matches], [self.path, other_path])
        self.assertTrue(all(obj.is_ar_package for obj in matches))
        self.assertIsNot(matches[0].xml_obj, matches[1].xml_obj)
        self.assertIs(matches[0].file, document.get_file(self.path))
        self.assertIs(matches[1].file, document.get_file(other_path))
        self.assertIs(document.ref(packages[0].ref, filename=self.path), matches[0])
        with self.assertRaises(ValueError):
            document.ref(packages[0].ref)
        self.assertIsNone(document.ref(('Missing',)))
        self.assertEqual(document.find(('Missing',)), [])

    def test_rename_updates_definition_and_references_after_rescan(self):
        document = IOArxml([self.path])
        ref = next(ref for ref, rows in document.references.items() if rows and document.ref(ref) is not None)
        target = document.ref(ref)
        assert target is not None
        updated_ref = (*ref[:-1], ref[-1] + '_renamed')
        target.xml_obj.short_name.value = updated_ref[-1]
        for obj, _, _ in document.ref_to_ref(ref):
            obj.value = document.ref2ref_str(updated_ref)
        document.scan_ref()
        self.assertIsNone(document.ref(ref))
        self.assertIsNotNone(document.ref(updated_ref))
        self.assertTrue(document.ref_to_ref(updated_ref))
        document.flush_to_file()
        reloaded = IOArxml([self.path])
        self.assertIsNotNone(reloaded.ref(updated_ref))
        self.assertTrue(reloaded.ref_to_ref(updated_ref))

    def test_file_can_be_used_independently(self):
        file = ArxmlFile(self.path)
        types = file.ar(self.autosar.SwBaseType)
        self.assertTrue(types)
        obj = types[0]
        self.assertIs(obj.file, file)
        self.assertIs(file.ref(obj.ref).xml_obj, obj.xml_obj)
        obj.xml_obj.short_name.value = 'NewName'
        self.assertEqual(obj.short_name, 'NewName')
        file.scan_ref()
        new_ref = (*obj.ref[:-1], 'NewName')
        self.assertIsNone(file.ref(obj.ref))
        self.assertIs(file.ref(new_ref).xml_obj, obj.xml_obj)
        file.save()
        self.assertIsNotNone(ArxmlFile(self.path).ref(new_ref))

    def test_schema_version_mismatch_is_rejected_before_object_parsing(self):
        path = Path(self.path)
        path.write_text(path.read_text(encoding='utf-8').replace('AUTOSAR_4-2-2.xsd', 'AUTOSAR_00048.xsd'), encoding='utf-8')
        with patch('k3q_arxml.arxml_file.XmlParser.parse') as parse:
            with self.assertRaises(ValueError) as error:
                ArxmlFile(self.path)
        parse.assert_not_called()
        self.assertIn(self.path, str(error.exception))
        self.assertIn('AUTOSAR_00048.xsd', str(error.exception))
        self.assertIn('schema_version=4.2.2', str(error.exception))

    def test_schema_check_selects_autosar_namespace_and_accepts_schema_paths(self):
        for schema in ('AUTOSAR_4-2-2.xsd', 'https://example.test/schemas/AUTOSAR_4-2-2.xsd', r'C:\schemas\AUTOSAR_4-2-2.xsd'):
            with self.subTest(schema=schema):
                Path(self.path).write_text(
                    '<AUTOSAR xmlns="http://autosar.org/schema/r4.0" xmlns:meta="http://www.w3.org/2001/XMLSchema-instance" '
                    f'meta:schemaLocation="urn:other other.xsd http://autosar.org/schema/r4.0 {schema}"><AR-PACKAGES/></AUTOSAR>',
                    encoding='utf-8',
                )
                self.assertEqual(ArxmlFile(self.path).schema_version, '4.2.2')

    def test_missing_autosar_schema_declaration_is_rejected(self):
        for declaration in ('', 'xsi:schemaLocation="urn:other other.xsd"'):
            with self.subTest(declaration=declaration):
                Path(self.path).write_text(
                    f'<AUTOSAR xmlns="http://autosar.org/schema/r4.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" {declaration}/>',
                    encoding='utf-8',
                )
                with self.assertRaisesRegex(ValueError, '无法核对 schema_version'):
                    ArxmlFile(self.path)
