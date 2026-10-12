import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from k3q_arxml.schemas import discover_schemas


class SchemaDiscoveryTests(unittest.TestCase):
    def test_discovers_new_versions_and_ignores_incomplete_directories(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            expected = {}
            for folder, filename, version in (
                ('autosar_00053', 'AUTOSAR_00053.xsd', '00053'),
                ('autosar_4_3_1', 'AUTOSAR_4-3-1.xsd', '4.3.1'),
            ):
                schema = root / folder / filename
                schema.parent.mkdir()
                schema.touch()
                expected[version] = schema

            incomplete = root / 'autosar_00054'
            incomplete.mkdir()
            (incomplete / 'xml.xsd').touch()
            (root / 'autosar_00055').mkdir()
            unrelated = root / 'notes'
            unrelated.mkdir()
            (unrelated / 'AUTOSAR_00056.xsd').touch()

            self.assertEqual(discover_schemas(root), expected)
            expected['00053'].unlink()
            del expected['00053']
            self.assertEqual(discover_schemas(root), expected)

    def test_missing_schema_directory_has_no_supported_versions(self):
        with TemporaryDirectory() as directory:
            self.assertEqual(discover_schemas(Path(directory) / 'missing'), {})
