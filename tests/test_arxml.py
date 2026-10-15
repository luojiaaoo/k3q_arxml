import unittest
from contextlib import chdir
from dataclasses import is_dataclass
from pathlib import Path
from shutil import copy2
from tempfile import TemporaryDirectory
from types import ModuleType
from unittest.mock import patch

from lxml import etree
from xsdata.formats.dataclass.parsers import XmlParser

from k3q_arxml import ArxmlFile, ArxmlNamedNode, ArxmlNode, ArxmlRefNode, IOArxml


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
        self.path = (Path(self.temporary.name) / 'sample.arxml').resolve()
        fixture = Path(__file__).resolve().parents[1] / 'test' / 'ThrottlePositionControlComposition.arxml'
        copy2(fixture, self.path)
        logger_patch = patch('k3q_arxml.arxml_file.logger')
        logger_patch.start()
        self.addCleanup(logger_patch.stop)

    def test_native_module_and_round_trip_preserve_objects_and_references(self):
        self.assertIsInstance(self.autosar, ModuleType)
        original = IOArxml([self.path])
        file = original.get_file(self.path)
        paths = set(file.objects)
        references = {ref: [(row.xml_obj.value, row.owner_ref) for row in rows] for ref, rows in file.references.items()}
        self.assertTrue(paths)
        self.assertTrue(references)
        self.assertEqual(file.parse_schema_version, '4.2.2')
        self.assertEqual(file.header.file_schema_version, '4.2.2')
        original.flush_to_file()
        reloaded = IOArxml([self.path]).get_file(self.path)
        self.assertEqual(set(reloaded.objects), paths)
        self.assertEqual({ref: [(row.xml_obj.value, row.owner_ref) for row in rows] for ref, rows in reloaded.references.items()}, references)
        self.assertEqual(reloaded.root, file.root)
        self.assertTrue(file.header.xml_schema_location.endswith('AUTOSAR_4-2-2.xsd'))

    def test_named_node_edit_refreshes_indexes_and_content(self):
        document = IOArxml([self.path])
        file = document.get_file(self.path)
        node = file.ar(self.autosar.SwBaseType)[0]
        ref = node.ref
        original_content = node.content
        self.assertFalse(original_content.startswith('<?xml'))
        self.assertEqual(etree.QName(etree.fromstring(original_content.encode('utf-8'))).namespace, file.header.xml_namespace)
        self.assertEqual(XmlParser().from_string(original_content, self.autosar.SwBaseType), node.xml_obj)

        with document.edit(node) as obj:
            self.assertIs(obj, node.xml_obj)
            obj.short_name.value = 'NewName'
            obj.uuid = 'new-uuid'
            self.assertIs(file.ref(ref), node)
        self.assertNotEqual(node.content, original_content)

        updated = file.ref((*ref[:-1], 'NewName'))
        self.assertIsNone(file.ref(ref))
        self.assertIsNot(updated, node)
        self.assertIs(updated.xml_obj, node.xml_obj)
        self.assertEqual(node.ref, (*ref[:-1], 'NewName'))
        self.assertEqual(file.uuids['new-uuid'], updated.ref)
        # 原包装同步了新路径，可以再次进入编辑上下文。
        with document.edit(node) as obj:
            obj.uuid = 'second-uuid'
        self.assertNotIn('new-uuid', file.uuids)
        self.assertEqual(file.uuids['second-uuid'], updated.ref)

    def test_scan_and_edit_do_not_serialize_content(self):
        document = IOArxml([self.path])
        file = document.get_file(self.path)
        with patch('k3q_arxml.schemas.XmlSerializer', side_effect=RuntimeError('unexpected serialization')):
            file.scan_ref()
            with document.edit(file.ar(self.autosar.SwBaseType)[0]) as obj:
                obj.uuid = 'edited-without-serialization'
        self.assertIn('edited-without-serialization', file.uuids)

    def test_swc_arxml_can_be_parsed(self):
        fixture = Path(__file__).resolve().parents[1] / 'test' / 'SWC.arxml'
        swc_path = Path(self.temporary.name) / 'SWC.arxml'
        copy2(fixture, swc_path)

        file = ArxmlFile().parse_file(swc_path)

        self.assertEqual(file.header.file_schema_version, '4.2.2')
        self.assertTrue(file.objects)
        self.assertTrue(file.ar(self.autosar.ArPackage))
        self.assertTrue(file.format.leading_comments)
        self.assertIn('Auto generated XML Component Description', file.format.leading_comments)

    def test_equivalent_file_paths_load_once_and_preserve_saved_edits(self):
        with chdir(self.temporary.name):
            Path('nested').mkdir()
            aliases = [self.path, Path('sample.arxml'), Path('./sample.arxml'), Path('nested/../sample.arxml'), Path(self.path.as_posix())]
            with patch.object(ArxmlFile, 'parse_file', autospec=True, side_effect=ArxmlFile.parse_file) as parse:
                document = IOArxml(iter(aliases))
            self.assertEqual(parse.call_count, 1)
            self.assertEqual(list(document.files), [self.path])
            file = document.get_file(self.path)
            for alias in aliases:
                self.assertIs(document.get_file(alias), file)
            ref = next(iter(file.objects))
            self.assertIs(document.ref(ref), file.ref(ref))
            self.assertIs(document.ref(ref, filename=Path('sample.arxml')), file.ref(ref))
            self.assertIsInstance(file.filepath, Path)
            self.assertEqual(file.ref(ref).filepath, self.path)
            with document.edit(file.ar(self.autosar.SwBaseType)[0]) as obj:
                obj.uuid = 'saved-once'

        # 离开原工作目录后仍写入原文件，且没有另一份旧对象覆盖本次修改。
        document.flush_to_file()
        self.assertIn('saved-once', ArxmlFile().parse_file(self.path).uuids)

    def test_flush_saves_only_updated_files_and_retries_failed_save(self):
        other_path = self.path.with_name('other.arxml')
        copy2(self.path, other_path)
        document = IOArxml([self.path, other_path])
        first = document.get_file(self.path)
        second = document.get_file(other_path)

        with patch.object(first, 'save', wraps=first.save) as first_save, patch.object(second, 'save', wraps=second.save) as second_save:
            document.flush_to_file()
            first_save.assert_not_called()
            second_save.assert_not_called()

            with document.edit(first.ar(self.autosar.SwBaseType)[0]) as obj:
                obj.uuid = 'first-edited'
            document.flush_to_file()
            first_save.assert_called_once_with()
            second_save.assert_not_called()

            node = second.ar(self.autosar.SwBaseType)[0]
            node.xml_obj.uuid = 'second-edited'
            second.update_node(node)
            with patch.object(second, 'save', side_effect=OSError('save failed')):
                with self.assertRaisesRegex(OSError, 'save failed'):
                    document.flush_to_file()
            document.flush_to_file()
            self.assertEqual(first_save.call_count, 1)
            second_save.assert_called_once_with()

        self.assertIn('first-edited', ArxmlFile().parse_file(self.path).uuids)
        self.assertIn('second-edited', ArxmlFile().parse_file(other_path).uuids)

    def test_standalone_file_keeps_resolved_path(self):
        with chdir(self.temporary.name):
            file = ArxmlFile().parse_file(Path('sample.arxml'))
        self.assertEqual(file.filepath, self.path)
        file.format.leading_comments = '<!-- absolute path -->'
        file.save()
        self.assertEqual(ArxmlFile().parse_file(self.path).format.leading_comments, '<!-- absolute path -->')

    def test_append_resolves_paths_and_rejects_loaded_aliases(self):
        document = IOArxml([self.path])
        original = document.get_file(self.path)
        original.format.leading_comments = '<!-- unsaved edit -->'
        other_path = self.path.with_name('other.arxml')
        copy2(self.path, other_path)
        with chdir(self.temporary.name):
            with self.assertRaisesRegex(ValueError, '已加载'):
                document.append(Path('sample.arxml'))
            added = document.append(Path('other.arxml'))
            self.assertIs(document.get_file(Path('other.arxml')), added)

        self.assertIs(document.get_file(self.path), original)
        self.assertEqual(original.format.leading_comments, '<!-- unsaved edit -->')
        self.assertEqual(added.filepath, other_path)
        self.assertIs(document.files[added.filepath], added)
        self.assertTrue(added.objects)

    def test_ref_inner_subclass_is_indexed_and_can_be_edited_and_saved(self):
        autosar = self.autosar
        source = autosar.IPduMapping.SourceIPduRef(value='/Network/Trigger', dest=autosar.PduTriggeringSubtypesEnum.PDU_TRIGGERING)
        target = autosar.TargetIPduRef.TargetIPduRefInner(value='/Network/Trigger', dest=autosar.PduTriggeringSubtypesEnum.PDU_TRIGGERING)
        mapping = autosar.IPduMapping(source_i_pdu_ref=source, target_i_pdu=autosar.TargetIPduRef(target_i_pdu_ref=target))
        gateway = autosar.Gateway(short_name=autosar.Identifier(value='Gateway'), i_pdu_mappings=autosar.Gateway.IPduMappings(i_pdu_mapping=[mapping]))
        package = autosar.ArPackage(short_name=autosar.Identifier(value='Package'), elements=autosar.ArPackage.Elements(choice=[gateway]))
        root = autosar.Autosar(ar_packages=autosar.Autosar.ArPackages(ar_package=[package]))

        file = ArxmlFile().parse_autosar(self.path, root)
        document = IOArxml([])
        document.files[file.filepath] = file

        rows = file.references[('Network', 'Trigger')]
        self.assertEqual(len(rows), 2)
        self.assertIs(rows[0].xml_obj, source)
        self.assertIs(rows[1].xml_obj, target)
        self.assertTrue(all(row.owner_ref == ('Package', 'Gateway') for row in rows))
        self.assertEqual(file.uuids, {})
        with document.edit(file.ref(('Package', 'Gateway'))):
            rows[1].xml_obj.value = '/Network/NewTrigger'
        file.save()

        reloaded = ArxmlFile().parse_file(self.path)
        row = reloaded.references[('Network', 'NewTrigger')][0]
        self.assertIsInstance(row, ArxmlNode)
        self.assertNotIsInstance(row, ArxmlNamedNode)
        self.assertIsInstance(row.xml_obj, autosar.TargetIPduRef.TargetIPduRefInner)
        self.assertEqual(row.filepath, reloaded.filepath)
        self.assertEqual(row.owner_ref, ('Package', 'Gateway'))
        self.assertEqual(len(reloaded.references[('Network', 'Trigger')]), 1)

    def test_shared_paths_keep_separate_objects_and_file_identity(self):
        other_path = self.path.with_name('other.arxml')
        copy2(self.path, other_path)
        document = IOArxml([self.path, other_path])
        packages = document.ar(self.autosar.ArPackage)
        self.assertTrue(packages)
        matches = document.find(packages[0].ref)
        self.assertEqual([obj.filepath for obj in matches], [self.path, other_path])
        self.assertTrue(all(isinstance(obj.xml_obj, self.autosar.ArPackage) for obj in matches))
        self.assertIsNot(matches[0].xml_obj, matches[1].xml_obj)
        self.assertTrue(all(isinstance(obj, ArxmlNode) for obj in matches))
        self.assertIs(document.ref(packages[0].ref, filename=self.path), matches[0])
        with self.assertRaises(ValueError):
            document.ref(packages[0].ref)
        self.assertIsNone(document.ref(('Missing',)))
        self.assertEqual(document.find(('Missing',)), [])

    def test_io_queries_observe_node_edit_in_its_owning_file(self):
        other_path = self.path.with_name('other.arxml')
        copy2(self.path, other_path)
        document = IOArxml([self.path, other_path])
        node = document.get_file(self.path).ar(self.autosar.SwBaseType)[0]
        old_ref = node.ref
        other = document.get_file(other_path)
        with patch.object(other, 'scan_ref') as other_scan:
            with document.edit(node) as obj:
                obj.short_name.value = 'Renamed'
            other_scan.assert_not_called()
        updated_ref = (*node.ref[:-1], 'Renamed')
        self.assertIs(document.ref(updated_ref, filename=self.path).xml_obj, node.xml_obj)
        self.assertIsNone(document.ref(updated_ref, filename=other_path))
        self.assertEqual([result.filepath for result in document.find(old_ref)], [other_path])

    def test_reference_results_preserve_nodes_owners_and_file_identity(self):
        other_path = self.path.with_name('other.arxml')
        copy2(self.path, other_path)
        document = IOArxml([self.path, other_path])
        ref = next(iter(document.get_file(self.path).references))
        results = document.ref_to_ref(ref)
        expected_count = 0

        for file in document.files.values():
            cached = file.references[ref]
            file_results = [result for result in results if result.filepath == file.filepath]
            self.assertEqual(len(file_results), len(cached))
            expected_count += len(cached)
            for result, row in zip(file_results, cached):
                self.assertIs(result, row)
                self.assertIsInstance(result, ArxmlRefNode)
                self.assertTrue(is_dataclass(result))
                self.assertIsInstance(result, ArxmlNode)
                self.assertNotIsInstance(result, ArxmlNamedNode)
                self.assertIsInstance(result.xml_obj, self.autosar.Ref)
                self.assertIsNotNone(file.ref(result.owner_ref))
                self.assertEqual(result.filepath, file.filepath)

        self.assertEqual(len(results), expected_count)
        self.assertEqual({result.filepath for result in results}, {self.path, other_path})
        self.assertEqual(document.ref_to_ref(('Missing',)), [])

    def test_rename_updates_definition_and_references_incrementally(self):
        other_path = self.path.with_name('references.arxml')
        tree = etree.parse(self.path)
        base_types = tree.xpath('//ar:AR-PACKAGE[ar:SHORT-NAME="BaseTypes"]', namespaces={'ar': 'http://autosar.org/schema/r4.0'})[0]
        base_types.getparent().remove(base_types)
        tree.write(other_path, encoding='utf-8', xml_declaration=True)
        document = IOArxml([self.path, other_path])
        ref = ('AUTOSAR_Platform', 'BaseTypes', 'float32')
        self.assertIsNone(document.get_file(other_path).ref(ref))
        self.assertEqual({row.filepath for row in document.ref_to_ref(ref)}, {self.path, other_path})
        target = document.ref(ref)
        assert target is not None
        updated_ref = (*ref[:-1], ref[-1] + '_renamed')
        references = document.ref_to_ref(ref)
        target.xml_obj.short_name.value = updated_ref[-1]
        for reference in references:
            reference.xml_obj.value = document.ref2ref_str(updated_ref)
        document.get_file(target.filepath).update_node(target)
        for filepath, owner_ref in {(reference.filepath, reference.owner_ref) for reference in references}:
            file = document.get_file(filepath)
            owner = file.ref(owner_ref)
            assert owner is not None
            file.update_node(owner)
        self.assertIsNone(document.ref(ref))
        self.assertIsNotNone(document.ref(updated_ref))
        self.assertTrue(document.ref_to_ref(updated_ref))
        document.flush_to_file()
        reloaded = IOArxml([self.path, other_path])
        self.assertIsNotNone(reloaded.ref(updated_ref))
        self.assertEqual({row.filepath for row in reloaded.ref_to_ref(updated_ref)}, {self.path, other_path})

    def test_file_can_be_used_independently(self):
        file = ArxmlFile().parse_file(self.path)
        types = file.ar(self.autosar.SwBaseType)
        self.assertTrue(types)
        obj = types[0]
        old_ref = obj.ref
        self.assertIsInstance(obj, ArxmlNamedNode)
        self.assertIsInstance(obj, ArxmlNode)
        self.assertEqual(obj.filepath, file.filepath)
        self.assertIs(file.ref(obj.ref).xml_obj, obj.xml_obj)
        obj.xml_obj.short_name.value = 'NewName'
        self.assertEqual(obj.short_name, 'NewName')
        file.scan_ref()
        new_ref = (*old_ref[:-1], 'NewName')
        self.assertIsNone(file.ref(old_ref))
        self.assertIs(file.ref(new_ref).xml_obj, obj.xml_obj)
        file.save()
        self.assertIsNotNone(ArxmlFile().parse_file(self.path).ref(new_ref))

    def test_parse_autosar_can_create_and_save_a_file(self):
        source = ArxmlFile().parse_file(self.path)
        path = Path(self.temporary.name) / 'created.arxml'
        comments = '<!-- 新建文件 -->\n<!-- 第二条注释 -->'

        file = ArxmlFile().parse_autosar(path, source.root, indent='\t', leading_comments=comments)
        self.assertEqual(file.format.leading_comments, comments)
        self.assertFalse(path.exists())
        file.save()

        reloaded = ArxmlFile().parse_file(path)
        self.assertEqual(reloaded.root, source.root)
        self.assertEqual(set(reloaded.objects), set(source.objects))
        self.assertEqual(reloaded.format.indent, '\t')
        self.assertEqual(reloaded.format.leading_comments, comments)
        self.assertEqual(reloaded.header.file_schema_version, self.autosar.SCHEMA_VERSION)

    def test_append_loads_existing_file_without_writing(self):
        document = IOArxml([])
        original_content = self.path.read_bytes()

        file = document.append(self.path)

        self.assertIs(document.get_file(self.path), file)
        self.assertTrue(file.objects)
        self.assertTrue(file.references)
        self.assertEqual(self.path.read_bytes(), original_content)
        file.format.leading_comments = '<!-- 通过 IOArxml 保存 -->'
        file.save()

        reloaded = ArxmlFile().parse_file(self.path)
        self.assertEqual(reloaded.format.leading_comments, file.format.leading_comments)
        self.assertEqual(reloaded.root, file.root)
        self.assertEqual(set(reloaded.objects), set(file.objects))

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
            with self.subTest(path=path), self.assertRaises(error):
                document.append(path)
            self.assertEqual(document.files, {})
        self.assertEqual(self.path.read_bytes(), original_content)
        self.assertFalse((self.path.parent / 'missing').exists())

    def test_round_trip_preserves_leading_comment_order(self):
        path = Path(self.path)
        comments = '<!-- first -->\n<!-- 第二条\n多行注释 -->\n<!-- third -->'
        path.write_text(path.read_text(encoding='utf-8').replace('<AUTOSAR', comments + '\n<AUTOSAR', 1), encoding='utf-8')

        file = ArxmlFile().parse_file(path)
        self.assertEqual(file.format.leading_comments, comments)
        original_root = file.root
        for _ in range(2):
            file.save()
            file = ArxmlFile().parse_file(path)
            self.assertEqual(file.format.leading_comments, comments)
            self.assertEqual(file.root, original_root)

    def test_schema_version_mismatch_is_warned_and_saved_declaration_is_preserved(self):
        path = Path(self.path)
        path.write_text(path.read_text(encoding='utf-8').replace('AUTOSAR_4-2-2.xsd', 'AUTOSAR_00048.xsd'), encoding='utf-8')
        with patch('k3q_arxml.arxml_file.logger.warning') as warning:
            file = ArxmlFile().parse_file(self.path)
        warning.assert_called_once()
        self.assertEqual(file.parse_schema_version, '4.2.2')
        self.assertEqual(file.header.file_schema_version, '00048')
        schema_location = file.header.xml_schema_location
        file.save()
        root = etree.parse(str(path)).getroot()
        self.assertEqual(root.get('{http://www.w3.org/2001/XMLSchema-instance}schemaLocation'), schema_location)
        self.assertEqual(etree.QName(root).namespace, file.header.xml_namespace)
        reloaded = ArxmlFile().parse_file(path)
        self.assertEqual(reloaded.header.file_schema_version, '00048')
        self.assertEqual(reloaded.root, file.root)

    def test_schema_check_selects_autosar_namespace_and_accepts_schema_paths(self):
        for schema in ('AUTOSAR_4-2-2.xsd', 'https://example.test/schemas/AUTOSAR_4-2-2.xsd', r'C:\schemas\AUTOSAR_4-2-2.xsd'):
            with self.subTest(schema=schema):
                Path(self.path).write_text(
                    '<AUTOSAR xmlns="http://autosar.org/schema/r4.0" xmlns:meta="http://www.w3.org/2001/XMLSchema-instance" '
                    f'meta:schemaLocation="urn:other other.xsd http://autosar.org/schema/r4.0 {schema}"><AR-PACKAGES/></AUTOSAR>',
                    encoding='utf-8',
                )
                file = ArxmlFile().parse_file(self.path)
                self.assertEqual(file.parse_schema_version, '4.2.2')
                self.assertEqual(file.header.file_schema_version, '4.2.2')

    def test_missing_autosar_schema_declaration_is_rejected(self):
        for declaration in ('', 'xsi:schemaLocation="urn:other other.xsd"'):
            with self.subTest(declaration=declaration):
                Path(self.path).write_text(
                    f'<AUTOSAR xmlns="http://autosar.org/schema/r4.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" {declaration}/>',
                    encoding='utf-8',
                )
                with self.assertRaisesRegex(ValueError, '无法核对 schema_version'):
                    ArxmlFile().parse_file(self.path)
