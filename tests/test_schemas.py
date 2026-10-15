from k3q_arxml.schemas import discover_schemas


class TestSchemaDiscovery:
    def test_discovers_new_versions_and_ignores_incomplete_directories(self, tmp_path):
        root = tmp_path
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

        assert discover_schemas(root) == expected
        expected['00053'].unlink()
        del expected['00053']
        assert discover_schemas(root) == expected

    def test_missing_schema_directory_has_no_supported_versions(self, tmp_path):
        assert discover_schemas(tmp_path / 'missing') == {}
