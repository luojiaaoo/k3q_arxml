from contextlib import chdir
from dataclasses import is_dataclass
from pathlib import Path
from shutil import copy2
from types import ModuleType
from unittest.mock import patch

import pytest
from lxml import etree
from xsdata.formats.dataclass.parsers import XmlParser

from k3q_arxml import ArxmlFile, ArxmlNamedNode, ArxmlNode, ArxmlRefNode, IOArxml, ref2ref_str


class TestArxml:
    @pytest.fixture(autouse=True)
    def setup_arxml(self, tmp_path):
        try:
            from k3q_arxml import autosar
        except ImportError:
            pytest.skip('请先运行 uv run python -m k3q_arxml generate 4.2.2')
        if autosar.SCHEMA_VERSION != '4.2.2':
            pytest.skip('ARXML 样例测试需要生成 4.2.2 绑定')
        self.autosar = autosar
        self.directory = tmp_path
        self.path = tmp_path / 'sample.arxml'
        fixture = Path(__file__).resolve().parents[1] / 'test' / 'ThrottlePositionControlComposition.arxml'
        copy2(fixture, self.path)
        with patch('k3q_arxml.arxml_file.logger'):
            yield

    @staticmethod
    def _rename_root_packages(tree):
        for name in tree.xpath('/ar:AUTOSAR/ar:AR-PACKAGES/ar:AR-PACKAGE/ar:SHORT-NAME', namespaces={'ar': 'http://autosar.org/schema/r4.0'}):
            name.text += '_Other'

    def _copy_with_distinct_paths(self, path):
        tree = etree.parse(self.path)
        self._rename_root_packages(tree)
        tree.write(path, encoding='utf-8', xml_declaration=True)

    def test_native_module_and_round_trip_preserve_objects_and_references(self):
        assert isinstance(self.autosar, ModuleType)
        original = IOArxml([self.path])
        file = original.files[self.path]
        paths = set(file.index.objects)
        references = {ref: [(row.xml_obj.value, row.owner_ref) for row in rows] for ref, rows in file.index.references.items()}
        assert paths
        assert references
        assert file.parse_schema_version == '4.2.2'
        assert file.header.file_schema_version == '4.2.2'
        original.flush_to_file()
        reloaded = IOArxml([self.path]).files[self.path]
        assert set(reloaded.index.objects) == paths
        assert {ref: [(row.xml_obj.value, row.owner_ref) for row in rows] for ref, rows in reloaded.index.references.items()} == references
        assert reloaded.root == file.root
        assert file.header.xml_schema_location.endswith('AUTOSAR_4-2-2.xsd')

    def test_parse_sets_parent_on_generated_dataclasses(self):
        file = ArxmlFile().parse_file(self.path)
        root = file.root
        packages = root.ar_packages
        package = packages.ar_package[0]

        assert root.arxml_parent is None
        assert packages.arxml_parent is root
        assert package.arxml_parent is packages
        assert package.short_name.arxml_parent is package
        assert callable(root.edited)
        assert callable(packages.edited)
        assert callable(package.edited)
        assert callable(package.short_name.edited)

        file.save()
        reloaded = ArxmlFile().parse_file(self.path)
        assert reloaded.root.ar_packages.arxml_parent is reloaded.root

    def test_update_node_sets_parent_on_new_generated_dataclasses(self):
        autosar = self.autosar
        package = autosar.ArPackage(short_name=autosar.Identifier(value='Package'), elements=autosar.ArPackage.Elements(choice=[]))
        root = autosar.Autosar(ar_packages=autosar.Autosar.ArPackages(ar_package=[package]))
        file = ArxmlFile().parse_autosar(self.path, root)

        gateway = autosar.Gateway(short_name=autosar.Identifier(value='Gateway'))
        package.elements.choice.append(gateway)
        file.update_node(file.ref(('Package',)))

        assert package.arxml_parent is root.ar_packages
        assert package.elements.arxml_parent is package
        assert gateway.arxml_parent is package.elements
        assert gateway.short_name.arxml_parent is gateway
        assert callable(gateway.edited)
        assert callable(gateway.short_name.edited)
        assert file.ref(('Package', 'Gateway')).xml_obj is gateway

    def test_named_node_edit_refreshes_indexes_and_content(self):
        document = IOArxml([self.path])
        file = document.files[self.path]
        node = file.ar(self.autosar.SwBaseType)[0]
        ref = node.ref
        original_content = node.content
        assert not original_content.startswith('<?xml')
        assert etree.QName(etree.fromstring(original_content.encode('utf-8'))).namespace == file.header.xml_namespace
        assert XmlParser().from_string(original_content, self.autosar.SwBaseType) == node.xml_obj

        obj = node.xml_obj
        obj.short_name.value = 'NewName'
        obj.uuid = 'new-uuid'
        assert file.ref(ref) is node
        assert obj.edited() is obj
        assert node.content != original_content

        updated = file.ref((*ref[:-1], 'NewName'))
        assert file.ref(ref) is None
        assert updated is not node
        assert updated.xml_obj is node.xml_obj
        assert node.ref == (*ref[:-1], 'NewName')
        assert file.index.uuids['new-uuid'] == updated.ref
        # 同一 XML 对象可再次更新索引。
        obj.uuid = 'second-uuid'
        obj.edited()
        assert 'new-uuid' not in file.index.uuids
        assert file.index.uuids['second-uuid'] == updated.ref

    def test_scan_and_edit_do_not_serialize_content(self):
        document = IOArxml([self.path])
        file = document.files[self.path]
        with patch('k3q_arxml.schemas.XmlSerializer', side_effect=RuntimeError('unexpected serialization')):
            file.scan_ref()
            obj = file.ar(self.autosar.SwBaseType)[0].xml_obj
            obj.uuid = 'edited-without-serialization'
            obj.edited()
        assert 'edited-without-serialization' in file.index.uuids

    def test_swc_arxml_can_be_parsed(self):
        fixture = Path(__file__).resolve().parents[1] / 'test' / 'SWC.arxml'
        swc_path = self.directory / 'SWC.arxml'
        copy2(fixture, swc_path)

        file = ArxmlFile().parse_file(swc_path)

        assert file.header.file_schema_version == '4.2.2'
        assert file.index.objects
        assert file.ar(self.autosar.ArPackage)
        assert file.format.leading_comments
        assert 'Auto generated XML Component Description' in file.format.leading_comments

    def test_equivalent_file_paths_load_once_and_preserve_saved_edits(self):
        with chdir(self.directory):
            Path('nested').mkdir()
            aliases = [self.path, Path('sample.arxml'), Path('./sample.arxml'), Path('nested/../sample.arxml'), Path(self.path.as_posix())]
            with patch.object(ArxmlFile, 'parse_file', autospec=True, side_effect=ArxmlFile.parse_file) as parse:
                document = IOArxml(iter(aliases))
            assert parse.call_count == 1
            assert list(document.files) == [self.path]
            file = document.files[self.path]
            for alias in aliases:
                assert document.files[alias.resolve()] is file
            ref = next(iter(file.index.objects))
            assert document.ref(ref) is file.ref(ref)
            assert isinstance(file.filepath, Path)
            assert not hasattr(file.ref(ref).xml_obj, 'arxml_filepath')
            obj = file.ar(self.autosar.SwBaseType)[0].xml_obj
            obj.uuid = 'saved-once'
            obj.edited()

        # 离开原工作目录后仍写入原文件，且没有另一份旧对象覆盖本次修改。
        document.flush_to_file()
        assert 'saved-once' in ArxmlFile().parse_file(self.path).index.uuids

    def test_flush_saves_only_updated_files_and_retries_failed_save(self):
        other_path = self.path.with_name('other.arxml')
        self._copy_with_distinct_paths(other_path)
        document = IOArxml([self.path, other_path])
        first = document.files[self.path]
        second = document.files[other_path]

        with patch.object(first, 'save', wraps=first.save) as first_save, patch.object(second, 'save', wraps=second.save) as second_save:
            document.flush_to_file()
            first_save.assert_not_called()
            second_save.assert_not_called()

            obj = first.ar(self.autosar.SwBaseType)[0].xml_obj
            obj.uuid = 'first-edited'
            obj.edited()
            document.flush_to_file()
            first_save.assert_called_once_with()
            second_save.assert_not_called()

            node = second.ar(self.autosar.SwBaseType)[0]
            node.xml_obj.uuid = 'second-edited'
            second.update_node(node)
            with patch.object(second, 'save', side_effect=OSError('save failed')):
                with pytest.raises(OSError, match='save failed'):
                    document.flush_to_file()
            document.flush_to_file()
            assert first_save.call_count == 1
            second_save.assert_called_once_with()

        assert 'first-edited' in ArxmlFile().parse_file(self.path).index.uuids
        assert 'second-edited' in ArxmlFile().parse_file(other_path).index.uuids

    def test_standalone_file_keeps_resolved_path(self):
        with chdir(self.directory):
            file = ArxmlFile().parse_file(Path('sample.arxml'))
        assert file.filepath == self.path
        file.format.leading_comments = '<!-- absolute path -->'
        file.save()
        assert ArxmlFile().parse_file(self.path).format.leading_comments == '<!-- absolute path -->'

    def test_append_resolves_paths_and_rejects_loaded_aliases(self):
        document = IOArxml([self.path])
        original = document.files[self.path]
        original.format.leading_comments = '<!-- unsaved edit -->'
        other_path = self.path.with_name('other.arxml')
        self._copy_with_distinct_paths(other_path)
        with chdir(self.directory):
            with pytest.raises(ValueError, match='已加载'):
                document.append(Path('sample.arxml'))
            added = document.append(Path('other.arxml'))
            assert document.files[Path('other.arxml').resolve()] is added

        assert document.files[self.path] is original
        assert original.format.leading_comments == '<!-- unsaved edit -->'
        assert added.filepath == other_path
        assert document.files[added.filepath] is added
        assert added.index.objects

    def test_ref_inner_subclass_is_indexed_and_can_be_edited_and_saved(self):
        autosar = self.autosar
        source = autosar.IPduMapping.SourceIPduRef(value='/Network/Trigger', dest=autosar.PduTriggeringSubtypesEnum.PDU_TRIGGERING)
        target = autosar.TargetIPduRef.TargetIPduRefInner(value='/Network/Trigger', dest=autosar.PduTriggeringSubtypesEnum.PDU_TRIGGERING)
        mapping = autosar.IPduMapping(source_i_pdu_ref=source, target_i_pdu=autosar.TargetIPduRef(target_i_pdu_ref=target))
        gateway = autosar.Gateway(short_name=autosar.Identifier(value='Gateway'), i_pdu_mappings=autosar.Gateway.IPduMappings(i_pdu_mapping=[mapping]))
        package = autosar.ArPackage(short_name=autosar.Identifier(value='Package'), elements=autosar.ArPackage.Elements(choice=[gateway]))
        root = autosar.Autosar(ar_packages=autosar.Autosar.ArPackages(ar_package=[package]))

        file = ArxmlFile().parse_autosar(self.path, root)

        assert source.arxml_parent is mapping
        assert target.arxml_parent is mapping.target_i_pdu
        rows = file.index.references[('Network', 'Trigger')]
        assert len(rows) == 2
        assert rows[0].xml_obj is source
        assert rows[1].xml_obj is target
        assert all((row.owner_ref == ('Package', 'Gateway') for row in rows))
        assert file.index.uuids == {}
        rows[1].xml_obj.value = '/Network/NewTrigger'
        assert rows[1].xml_obj.edited() is rows[1].xml_obj
        file.save()

        reloaded = ArxmlFile().parse_file(self.path)
        row = reloaded.index.references[('Network', 'NewTrigger')][0]
        assert isinstance(row, ArxmlNode)
        assert not isinstance(row, ArxmlNamedNode)
        assert isinstance(row.xml_obj, autosar.TargetIPduRef.TargetIPduRefInner)
        assert not hasattr(row, 'filepath')
        assert callable(row.xml_obj.edited)
        assert row.owner_ref == ('Package', 'Gateway')
        assert len(reloaded.index.references[('Network', 'Trigger')]) == 1

    def test_shared_paths_reject_second_file_without_changing_loaded_files(self):
        other_path = self.path.with_name('other.arxml')
        copy2(self.path, other_path)
        document = IOArxml([self.path])
        first = document.files[self.path]
        with pytest.raises(ValueError, match='/AUTOSAR_Platform'):
            document.append(other_path)
        assert document.files == {self.path: first}
        with pytest.raises(ValueError, match='/AUTOSAR_Platform'):
            IOArxml([self.path, other_path])

    def test_io_queries_observe_node_edit_in_its_owning_file(self):
        other_path = self.path.with_name('other.arxml')
        self._copy_with_distinct_paths(other_path)
        document = IOArxml([self.path, other_path])
        node = document.files[self.path].ar(self.autosar.SwBaseType)[0]
        old_ref = node.ref
        other = document.files[other_path]
        with patch.object(other, 'scan_ref') as other_scan:
            node.xml_obj.short_name.value = 'Renamed'
            node.xml_obj.edited()
            other_scan.assert_not_called()
        updated_ref = (*node.ref[:-1], 'Renamed')
        assert document.files[self.path].ref(updated_ref).xml_obj is node.xml_obj
        assert document.files[other_path].ref(updated_ref) is None
        assert document.ref(old_ref) is None

    def test_reference_results_preserve_nodes_and_owners(self):
        other_path = self.path.with_name('other.arxml')
        self._copy_with_distinct_paths(other_path)
        document = IOArxml([self.path, other_path])
        ref = next(iter(document.files[self.path].index.references))
        results = document.ref_to_ref(ref)
        expected = [row for file in document.files.values() for row in file.index.references[ref]]
        assert len(results) == len(expected)
        for result, row in zip(results, expected, strict=True):
            assert result is row
            assert isinstance(result, ArxmlRefNode)
            assert is_dataclass(result)
            assert isinstance(result, ArxmlNode)
            assert not isinstance(result, ArxmlNamedNode)
            assert isinstance(result.xml_obj, self.autosar.Ref)
            assert callable(result.xml_obj.edited)
            assert not hasattr(result, 'filepath')
        assert document.ref_to_ref(('Missing',)) == []

    def test_reference_target_edit_round_trips(self):
        file = ArxmlFile().parse_file(self.path)
        target_ref, reference = next(
            (target_ref, row)
            for target_ref, rows in file.index.references.items()
            for row in rows
            if isinstance(getattr(row.xml_obj, 'dest', None), self.autosar.DataPrototypeSubtypesEnum)
        )
        updated_ref = (*target_ref[:-1], target_ref[-1] + '_New')
        original_dest = reference.xml_obj.dest
        reference.set_dest(updated_ref)
        assert reference.xml_obj.value == ref2ref_str(updated_ref)
        assert reference.xml_obj.dest is original_dest

        owner = file.ref(reference.owner_ref)
        assert owner is not None
        file.update_node(owner)
        file.save()

        reloaded = ArxmlFile().parse_file(self.path)
        assert any((row.owner_ref == reference.owner_ref and row.xml_obj.value == ref2ref_str(updated_ref) for row in reloaded.index.references[updated_ref]))

        plain_reference = ArxmlRefNode(xml_obj=self.autosar.Ref(value='/Target'), owner_ref=())
        plain_reference.set_dest(('Other', 'Target'))
        assert plain_reference.xml_obj.value == '/Other/Target'

    def test_rename_updates_definition_and_references_incrementally(self):
        other_path = self.path.with_name('references.arxml')
        tree = etree.parse(self.path)
        base_types = tree.xpath('//ar:AR-PACKAGE[ar:SHORT-NAME="BaseTypes"]', namespaces={'ar': 'http://autosar.org/schema/r4.0'})[0]
        base_types.getparent().remove(base_types)
        self._rename_root_packages(tree)
        tree.write(other_path, encoding='utf-8', xml_declaration=True)
        document = IOArxml([self.path, other_path])
        ref = ('AUTOSAR_Platform', 'BaseTypes', 'float32')
        assert document.files[other_path].ref(ref) is None
        assert len(document.ref_to_ref(ref)) == sum((len(file.index.references.get(ref, [])) for file in document.files.values()))
        target = document.ref(ref)
        assert target is not None
        updated_ref = (*ref[:-1], ref[-1] + '_renamed')
        references = document.ref_to_ref(ref)
        target.xml_obj.short_name.value = updated_ref[-1]
        for reference in references:
            reference.set_dest(updated_ref)
        target.xml_obj.edited()
        for reference in references:
            reference.xml_obj.edited()
        assert document.ref(ref) is None
        assert document.ref(updated_ref) is not None
        assert document.ref_to_ref(updated_ref)
        document.flush_to_file()
        reloaded = IOArxml([self.path, other_path])
        assert reloaded.ref(updated_ref) is not None
        assert len(reloaded.ref_to_ref(updated_ref)) == len(references)

    def test_file_can_be_used_independently(self):
        file = ArxmlFile().parse_file(self.path)
        types = file.ar(self.autosar.SwBaseType)
        assert types
        obj = types[0]
        old_ref = obj.ref
        assert isinstance(obj, ArxmlNamedNode)
        assert isinstance(obj, ArxmlNode)
        assert not hasattr(obj, 'filepath')
        assert not hasattr(obj.xml_obj, 'arxml_filepath')
        assert file.ref(obj.ref).xml_obj is obj.xml_obj
        obj.xml_obj.short_name.value = 'NewName'
        assert obj.short_name == 'NewName'
        file.scan_ref()
        new_ref = (*old_ref[:-1], 'NewName')
        assert file.ref(old_ref) is None
        assert file.ref(new_ref).xml_obj is obj.xml_obj
        file.save()
        assert ArxmlFile().parse_file(self.path).ref(new_ref) is not None

    def test_parse_autosar_can_create_and_save_a_file(self):
        source = ArxmlFile().parse_file(self.path)
        path = self.directory / 'created.arxml'
        comments = '<!-- 新建文件 -->\n<!-- 第二条注释 -->'

        file = ArxmlFile().parse_autosar(path, source.root, indent='\t', leading_comments=comments)
        assert file.format.leading_comments == comments
        assert not path.exists()
        file.save()

        reloaded = ArxmlFile().parse_file(path)
        assert reloaded.root == source.root
        assert set(reloaded.index.objects) == set(source.index.objects)
        assert reloaded.format.indent == '\t'
        assert reloaded.format.leading_comments == comments
        assert reloaded.header.file_schema_version == self.autosar.SCHEMA_VERSION

    def test_append_loads_existing_file_without_writing(self):
        document = IOArxml([])
        original_content = self.path.read_bytes()

        file = document.append(self.path)

        assert document.files[self.path] is file
        assert file.index.objects
        assert file.index.references
        assert self.path.read_bytes() == original_content
        file.format.leading_comments = '<!-- 通过 IOArxml 保存 -->'
        file.save()

        reloaded = ArxmlFile().parse_file(self.path)
        assert reloaded.format.leading_comments == file.format.leading_comments
        assert reloaded.root == file.root
        assert set(reloaded.index.objects) == set(file.index.objects)

    def test_append_rejects_missing_paths_directories_and_invalid_xml(self):
        document = IOArxml([])
        original_content = self.path.read_bytes()
        invalid_path = self.path.with_name('invalid.arxml')
        invalid_path.write_text('invalid XML', encoding='utf-8')
        cases = (
            (self.path.with_name('missing.arxml'), FileNotFoundError),
            (self.path.parent, IsADirectoryError),
            (self.path.parent / 'missing' / 'new.arxml', FileNotFoundError),
            (invalid_path, etree.XMLSyntaxError),
        )
        for path, error in cases:
            with pytest.raises(error):
                document.append(path)
            assert document.files == {}
        assert self.path.read_bytes() == original_content
        assert not (self.path.parent / 'missing').exists()

    def test_round_trip_preserves_leading_comment_order(self):
        path = Path(self.path)
        comments = '<!-- first -->\n<!-- 第二条\n多行注释 -->\n<!-- third -->'
        path.write_text(path.read_text(encoding='utf-8').replace('<AUTOSAR', comments + '\n<AUTOSAR', 1), encoding='utf-8')

        file = ArxmlFile().parse_file(path)
        assert file.format.leading_comments == comments
        original_root = file.root
        for _ in range(2):
            file.save()
            file = ArxmlFile().parse_file(path)
            assert file.format.leading_comments == comments
            assert file.root == original_root

    def test_schema_version_mismatch_is_warned_and_saved_declaration_is_preserved(self):
        path = Path(self.path)
        path.write_text(path.read_text(encoding='utf-8').replace('AUTOSAR_4-2-2.xsd', 'AUTOSAR_00048.xsd'), encoding='utf-8')
        with patch('k3q_arxml.arxml_file.logger.warning') as warning:
            file = ArxmlFile().parse_file(self.path)
        warning.assert_called_once()
        assert file.parse_schema_version == '4.2.2'
        assert file.header.file_schema_version == '00048'
        schema_location = file.header.xml_schema_location
        file.save()
        root = etree.parse(str(path)).getroot()
        assert root.get('{http://www.w3.org/2001/XMLSchema-instance}schemaLocation') == schema_location
        assert etree.QName(root).namespace == file.header.xml_namespace
        reloaded = ArxmlFile().parse_file(path)
        assert reloaded.header.file_schema_version == '00048'
        assert reloaded.root == file.root

    @pytest.mark.parametrize('schema', ('AUTOSAR_4-2-2.xsd', 'https://example.test/schemas/AUTOSAR_4-2-2.xsd', 'C:\\schemas\\AUTOSAR_4-2-2.xsd'))
    def test_schema_check_selects_autosar_namespace_and_accepts_schema_paths(self, schema):
        Path(self.path).write_text(
            '<AUTOSAR xmlns="http://autosar.org/schema/r4.0" xmlns:meta="http://www.w3.org/2001/XMLSchema-instance" '
            f'meta:schemaLocation="urn:other other.xsd http://autosar.org/schema/r4.0 {schema}"><AR-PACKAGES/></AUTOSAR>',
            encoding='utf-8',
        )
        file = ArxmlFile().parse_file(self.path)
        assert file.parse_schema_version == '4.2.2'
        assert file.header.file_schema_version == '4.2.2'

    @pytest.mark.parametrize('declaration', ('', 'xsi:schemaLocation="urn:other other.xsd"'))
    def test_missing_autosar_schema_declaration_is_rejected(self, declaration):
        Path(self.path).write_text(
            f'<AUTOSAR xmlns="http://autosar.org/schema/r4.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" {declaration}/>',
            encoding='utf-8',
        )
        with pytest.raises(ValueError, match='无法核对 schema_version'):
            ArxmlFile().parse_file(self.path)
