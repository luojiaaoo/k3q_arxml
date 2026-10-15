import sys
import unittest
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from k3q_arxml import ArxmlFile, ArxmlNamedNode, ArxmlNode, ArxmlRefNode, IOArxml


@dataclass
class Text:
    value: str = ''


@dataclass
class Reference(Text):
    base: str | None = field(default=None, metadata={'name': 'BASE', 'type': 'Attribute'})


@dataclass
class ReferenceInner(Reference):
    dest: str = field(default='TYPE', metadata={'name': 'DEST', 'type': 'Attribute'})


@dataclass
class IndirectReference(ReferenceInner):
    pass


@dataclass
class LookalikeRef:
    value: str
    dest: str = 'TYPE'


@dataclass
class NamedBase:
    short_name: Text = field(metadata={'name': 'SHORT-NAME', 'type': 'Element'})
    uuid: str | None = field(default=None, metadata={'name': 'UUID', 'type': 'Attribute'})


@dataclass
class NamedNode(NamedBase):
    child: object = field(default=None, metadata={'type': 'Element'})
    content: list[object] = field(default_factory=list, metadata={'type': 'Elements'})


@dataclass
class Container:
    value: object = None
    content: list[object] = field(default_factory=list, metadata={'type': 'Wildcard'})
    attributes: dict[str, object] = field(default_factory=dict, metadata={'type': 'Attributes'})
    attribute: object = field(default=None, metadata={'type': 'Attribute'})


class ScanRefTests(unittest.TestCase):
    def setUp(self):
        # 用小型 dataclass 绑定验证遍历规则，不依赖本地是否生成了 autosar.py。
        binding = ModuleType('k3q_arxml.autosar')
        binding.SCHEMA_VERSION = 'test'
        binding.Autosar = Container
        binding.Ref = Reference
        binding_patch = patch.dict(sys.modules, {'k3q_arxml.autosar': binding})
        binding_patch.start()
        self.addCleanup(binding_patch.stop)

    def scan(self, root):
        return ArxmlFile().parse_autosar(Path('scan.arxml'), root)

    def edit(self, file, node):
        document = IOArxml([])
        document.files[file.filepath] = file
        return document.edit(node)

    def test_rejects_dataclass_without_instance_dict(self):
        @dataclass(slots=True)
        class SlotNode:
            value: str = 'child'

        with self.assertRaisesRegex(TypeError, r'scan\.arxml.*SlotNode.*__dict__.*arxml_parent'):
            self.scan(Container(value=SlotNode()))

    def test_parent_field_is_not_overwritten(self):
        @dataclass
        class HasParent:
            parent: str = 'original'
            child: object = None

        root = HasParent(child=Container())
        self.scan(root)

        self.assertEqual(root.parent, 'original')
        self.assertIsNone(root.arxml_parent)
        self.assertIs(root.child.arxml_parent, root)
        self.assertEqual(root.arxml_filepath, Path('scan.arxml').resolve())
        self.assertEqual(root.child.arxml_filepath, root.arxml_filepath)

    def test_rejects_arxml_parent_field_collision(self):
        @dataclass
        class HasArxmlParent:
            arxml_parent: str = 'original'

        with self.assertRaisesRegex(TypeError, r'HasArxmlParent.*已声明 arxml_parent 字段'):
            self.scan(HasArxmlParent())

    def test_rejects_arxml_filepath_field_collision(self):
        @dataclass
        class HasArxmlFilepath:
            arxml_filepath: Path = Path('original.arxml')

        with self.assertRaisesRegex(TypeError, r'HasArxmlFilepath.*已声明 arxml_filepath 字段'):
            self.scan(HasArxmlFilepath())

    def test_fields_sequences_inheritance_and_reference_identity(self):
        first = Reference('/Types/Target')
        second = ReferenceInner('/Types/Target')
        third = IndirectReference('/Types/Target')
        child = NamedNode(Text('Child'), uuid='child-id', child=Container(value=second))
        package = NamedNode(Text('Package'), child=first, content=['mixed text', child, (None, 42, third)])
        root = Container(value=package)

        file = self.scan(root)

        self.assertEqual(list(file.objects), [('Package',), ('Package', 'Child')])
        self.assertTrue(all(isinstance(node, ArxmlNode) for node in file.objects.values()))
        self.assertIs(file.ref(('Package',)).xml_obj, package)
        self.assertIs(file.ref(('Package', 'Child')).xml_obj, child)
        rows = file.references[('Types', 'Target')]
        self.assertEqual([row.owner_ref for row in rows], [('Package',), ('Package', 'Child'), ('Package',)])
        for row, expected in zip(rows, (first, second, third), strict=True):
            self.assertIsInstance(row, ArxmlRefNode)
            self.assertIsInstance(row, ArxmlNode)
            self.assertNotIsInstance(row, ArxmlNamedNode)
            self.assertIs(row.xml_obj, expected)
            self.assertEqual(row.xml_obj.arxml_filepath, Path('scan.arxml').resolve())
        self.assertEqual(file.uuids, {'child-id': ('Package', 'Child')})

    def test_only_declared_child_fields_and_ref_instances_are_indexed(self):
        ignored = Reference('/Ignored')
        root = Container(
            content=[LookalikeRef('/Lookalike'), '/Text', {'key': ignored}],
            attributes={'custom': ignored},
            attribute=ignored,
        )
        root.extra = ignored

        file = self.scan(root)

        self.assertEqual(file.objects, {})
        self.assertEqual(file.references, {})
        self.assertEqual(file.uuids, {})

    def test_shared_branches_and_repeated_references_are_not_deduplicated(self):
        reference = Reference('/Unloaded/Target')
        shared = Container(value=reference)
        root = Container(content=[NamedNode(Text('A'), content=[shared, shared]), NamedNode(Text('B'), child=shared)])

        file = self.scan(root)

        rows = file.references[('Unloaded', 'Target')]
        self.assertEqual([row.owner_ref for row in rows], [('A',), ('A',), ('B',)])
        self.assertTrue(all(row.xml_obj is reference for row in rows))

    def test_uuid_and_duplicate_path_overwrite_order_is_preserved(self):
        first = NamedNode(Text('Same'), uuid='duplicate')
        last = NamedNode(Text('Same'), uuid='')
        other = NamedNode(Text('Other'), uuid='duplicate')
        root = Container(content=[first, last, other, NamedNode(Text('WithoutUuid'))])

        file = self.scan(root)

        self.assertIs(file.ref(('Same',)).xml_obj, last)
        self.assertEqual(file.uuids, {'duplicate': ('Other',)})

    def test_rescan_replaces_paths_and_does_not_accumulate_references(self):
        reference = Reference('/Package/Old')
        target = NamedNode(Text('Old'), uuid='target-id')
        root = NamedNode(Text('Package'), child=reference, content=[target])
        file = self.scan(root)
        target.short_name.value = 'New'
        reference.value = '/Package/New'

        file.scan_ref()
        file.scan_ref()

        self.assertIsNone(file.ref(('Package', 'Old')))
        self.assertIs(file.ref(('Package', 'New')).xml_obj, target)
        self.assertEqual(file.references, {('Package', 'New'): [ArxmlRefNode(xml_obj=reference, owner_ref=('Package',))]})
        self.assertEqual(file.uuids, {'target-id': ('Package', 'New')})

    def test_invalid_references_report_location_and_keep_previous_indexes(self):
        reference = Reference('/Target')
        file = self.scan(NamedNode(Text('Package'), uuid='package-id', child=reference))
        previous = file.objects, file.references, file.uuids
        for value in (None, 123, '', '/', '/Package/', '/Package//Target', 'Package/Target'):
            with self.subTest(value=value):
                reference.value = value
                with self.assertRaises(ValueError) as caught:
                    file.scan_ref()
                message = str(caught.exception)
                for text in ('scan.arxml', '/Package', 'Reference.value'):
                    self.assertIn(text, message)
                for current, old in zip((file.objects, file.references, file.uuids), previous, strict=True):
                    self.assertIs(current, old)

    def test_invalid_short_names_and_uuids_report_the_field(self):
        for short_name in (None, Text(''), Text('  '), Text('Bad/Name'), Text(42)):
            with self.subTest(short_name=short_name):
                with self.assertRaisesRegex(ValueError, r'scan.arxml: /Package .*NamedNode.short_name.*SHORT-NAME'):
                    self.scan(NamedNode(Text('Package'), child=NamedNode(short_name)))
        with self.assertRaisesRegex(ValueError, r'NamedNode.uuid.*UUID'):
            self.scan(NamedNode(Text('Package'), uuid=42))

    def test_nested_containment_preserves_reference_owner(self):
        reference = Reference('/Target')
        nested = reference
        for _ in range(64):
            nested = Container(value=nested)

        file = self.scan(NamedNode(Text('Package'), child=nested))

        self.assertIs(file.references[('Target',)][0].xml_obj, reference)
        self.assertEqual(file.references[('Target',)][0].owner_ref, ('Package',))

    def test_wrapper_failure_does_not_publish_partial_indexes(self):
        file = self.scan(NamedNode(Text('Package'), uuid='package-id'))
        previous = file.objects, file.references, file.uuids
        with patch('k3q_arxml.arxml_file.ArxmlNamedNode', side_effect=RuntimeError('wrapper failure')):
            with self.assertRaisesRegex(RuntimeError, 'wrapper failure'):
                file.scan_ref()
        for current, old in zip((file.objects, file.references, file.uuids), previous, strict=True):
            self.assertIs(current, old)

    def test_reference_without_named_owner_can_be_edited_through_wrapper(self):
        reference = Reference('/Old')
        file = self.scan(Container(value=reference))
        row = file.references[('Old',)][0]
        self.assertIs(row.xml_obj, reference)
        self.assertEqual(row.xml_obj.arxml_filepath, file.filepath)
        self.assertEqual(row.owner_ref, ())

        row.xml_obj.value = '/New'
        file.scan_ref()

        self.assertNotIn(('Old',), file.references)
        self.assertIs(file.references[('New',)][0].xml_obj, reference)

    def test_reference_record_failure_keeps_previous_indexes(self):
        file = self.scan(Container(value=Reference('/Target')))
        previous = file.objects, file.references, file.uuids
        with patch('k3q_arxml.arxml_file.ArxmlRefNode', side_effect=RuntimeError('reference record failure')):
            with self.assertRaisesRegex(RuntimeError, 'reference record failure'):
                file.scan_ref()
        for current, old in zip((file.objects, file.references, file.uuids), previous, strict=True):
            self.assertIs(current, old)

    def test_reference_does_not_use_named_node_wrapper(self):
        reference = Reference('/Target')
        with patch('k3q_arxml.arxml_file.ArxmlNamedNode', side_effect=RuntimeError('unexpected named node wrapper')):
            file = self.scan(Container(value=reference))
        self.assertEqual(file.objects, {})
        self.assertIs(file.references[('Target',)][0].xml_obj, reference)

    def test_edit_nested_named_root_refreshes_objects_references_and_uuids(self):
        reference = Reference('/Package/Owner/Old')
        target = NamedNode(Text('Old'), uuid='old-target')
        owner = NamedNode(Text('Owner'), uuid='old-owner', child=reference, content=[target])
        file = self.scan(Container(content=[NamedNode(Text('Package'), content=[owner]), NamedNode(Text('Other'))]))

        with self.edit(file, file.ref(('Package', 'Owner'))) as obj:
            self.assertIs(obj, owner)
            obj.short_name.value = 'Renamed'
            obj.uuid = 'new-owner'
            target.short_name.value = 'New'
            target.uuid = 'new-target'
            reference.value = '/Package/Renamed/New'
            obj.content.append(NamedNode(Text('Added')))

        self.assertIsNone(file.ref(('Package', 'Owner')))
        self.assertIs(file.ref(('Package', 'Renamed', 'New')).xml_obj, target)
        self.assertIsNotNone(file.ref(('Package', 'Renamed', 'Added')))
        self.assertIsNotNone(file.ref(('Other',)))
        self.assertNotIn(('Package', 'Owner', 'Old'), file.references)
        self.assertEqual(file.references[('Package', 'Renamed', 'New')][0].owner_ref, ('Package', 'Renamed'))
        self.assertEqual(file.uuids, {'new-owner': ('Package', 'Renamed'), 'new-target': ('Package', 'Renamed', 'New')})

    def test_edit_removal_refreshes_indexes(self):
        target = NamedNode(Text('Child'), uuid='child-id', child=Reference('/Target'))
        file = self.scan(NamedNode(Text('Package'), content=[target]))

        with self.edit(file, file.ref(('Package',))) as package:
            package.content.clear()

        self.assertIsNone(file.ref(('Package', 'Child')))
        self.assertEqual(file.references, {})
        self.assertEqual(file.uuids, {})

    def test_edit_refreshes_completed_changes_when_body_raises(self):
        file = self.scan(NamedNode(Text('Package')))
        with self.assertRaisesRegex(RuntimeError, 'body failure'):
            with self.edit(file, file.ref(('Package',))) as obj:
                obj.short_name.value = 'Renamed'
                raise RuntimeError('body failure')
        self.assertIsNone(file.ref(('Package',)))
        self.assertIsNotNone(file.ref(('Renamed',)))

    def test_edit_invalid_data_preserves_previous_indexes(self):
        reference = Reference('/Target')
        file = self.scan(NamedNode(Text('Package'), child=reference))
        previous = file.objects, file.references, file.uuids
        with self.assertRaises(ValueError):
            with self.edit(file, file.ref(('Package',))) as obj:
                obj.child.value = 'invalid-relative-ref'
        for current, old in zip((file.objects, file.references, file.uuids), previous, strict=True):
            self.assertIs(current, old)

    def test_edit_scans_only_its_subtree_and_keeps_other_wrappers(self):
        changed = NamedNode(Text('A'), child=Reference('/Shared'))
        untouched = NamedNode(Text('B'), child=Reference('/Shared'))
        root = Container(content=[changed, untouched])
        file = self.scan(root)
        other = file.ref(('B',))
        other_reference = file.references[('Shared',)][1]

        with patch.object(file, 'scan_ref', side_effect=AssertionError('unexpected full scan')):
            with patch.object(file, '_get_fields', wraps=file._get_fields) as get_fields:
                with self.edit(file, file.ref(('A',))) as obj:
                    obj.child.value = '/Changed'
        visited = [call.args[0] for call in get_fields.call_args_list]
        self.assertTrue(any(value is changed for value in visited))
        self.assertFalse(any(value is root or value is untouched or value is untouched.child for value in visited))
        self.assertIs(file.ref(('B',)), other)
        self.assertEqual(file.references[('Shared',)], [other_reference])
        self.assertIs(file.references[('Shared',)][0], other_reference)
        self.assertEqual(file.references[('Changed',)][0].owner_ref, ('A',))

    def test_edit_rename_keeps_external_incoming_references(self):
        target = NamedNode(Text('A'))
        reference = Reference('/A')
        file = self.scan(Container(content=[target, NamedNode(Text('B'), child=reference)]))
        incoming = file.references[('A',)][0]
        with self.edit(file, file.ref(('A',))) as obj:
            obj.short_name.value = 'Renamed'
        self.assertIsNone(file.ref(('A',)))
        self.assertIs(file.ref(('Renamed',)).xml_obj, target)
        self.assertIs(file.references[('A',)][0], incoming)
        self.assertEqual(reference.value, '/A')

    def test_edit_uuid_duplicates_keep_document_order_and_restore_previous_owner(self):
        first = NamedNode(Text('A'), uuid='duplicate')
        last = NamedNode(Text('B'), uuid='duplicate')
        file = self.scan(Container(content=[first, last]))
        with self.edit(file, file.ref(('A',))) as obj:
            obj.uuid = 'duplicate'
        self.assertEqual(file.uuids['duplicate'], ('B',))
        with self.edit(file, file.ref(('B',))) as obj:
            obj.uuid = None
        self.assertEqual(file.uuids['duplicate'], ('A',))

    def test_edit_path_conflict_and_wrapper_failure_preserve_previous_indexes(self):
        file = self.scan(Container(content=[NamedNode(Text('A'), child=NamedNode(Text('Child'))), NamedNode(Text('B'))]))
        previous = file.objects, file.references, file.uuids
        node = file.ref(('A',))
        child_node = file.ref(('A', 'Child'))
        with self.assertRaisesRegex(ValueError, '路径.*冲突'):
            with self.edit(file, node) as obj:
                obj.short_name.value = 'B'
        for current, old in zip((file.objects, file.references, file.uuids), previous, strict=True):
            self.assertIs(current, old)
        self.assertEqual(node.ref, ('A',))
        node.xml_obj.short_name.value = 'A'
        with self.edit(file, node) as obj:
            obj.short_name.value = 'Renamed'
            obj.child.short_name.value = 'RenamedChild'
            obj.content.append(NamedNode(Text('Added')))
            with patch('k3q_arxml.arxml_file.ArxmlNamedNode.__init__', side_effect=RuntimeError('wrapper failure')):
                with self.assertRaisesRegex(RuntimeError, 'wrapper failure'):
                    file.update_node(node)
            for current, old in zip((file.objects, file.references, file.uuids), previous, strict=True):
                self.assertIs(current, old)
            self.assertEqual(node.ref, ('A',))
            self.assertEqual(child_node.ref, ('A', 'Child'))
        self.assertIs(file.ref(('B',)), previous[0][('B',)])
        self.assertEqual(node.ref, ('Renamed',))
        self.assertIs(file.ref(('Renamed',)).xml_obj, node.xml_obj)
        self.assertIs(file.ref(('Renamed', 'RenamedChild')).xml_obj, child_node.xml_obj)

    def test_nested_edit_of_renamed_root_refreshes_current_path(self):
        file = self.scan(NamedNode(Text('Package'), child=NamedNode(Text('Child'))))
        node = file.ref(('Package',))
        with self.edit(file, node) as package:
            package.short_name.value = 'Renamed'
            with self.edit(file, node) as same_package:
                same_package.uuid = 'new-id'
            package.child.short_name.value = 'NewChild'
        self.assertEqual(set(file.objects), {('Renamed',), ('Renamed', 'NewChild')})
        self.assertEqual(file.uuids, {'new-id': ('Renamed',)})

    def test_update_node_merges_all_subtree_changes_like_full_scan(self):
        moved = NamedNode(Text('Moved'), uuid='moved-id', child=Reference('/Shared'))
        removed = NamedNode(Text('Removed'), uuid='removed-id', child=Reference('/RemovedOnly'))
        replaced = NamedNode(Text('Replaced'), uuid='replaced-id', child=Reference('/ReplacedOnly'))
        left = NamedNode(Text('Left'), content=[moved])
        right = NamedNode(Text('Right'))
        package = NamedNode(Text('Package'), uuid='package-id', child=Reference('/OldOnly'), content=[removed, replaced, left, right])
        incoming = Reference('/Package/Removed')
        root = Container(
            content=[
                NamedNode(Text('Before'), uuid='before-id', child=Reference('/Shared')),
                package,
                NamedNode(Text('PackageExtra'), uuid='outside-id', content=[incoming, Reference('/Shared')]),
            ]
        )
        file = self.scan(root)
        node = file.ref(('Package',))
        moved_node = file.ref(('Package', 'Left', 'Moved'))
        outside = file.ref(('PackageExtra',))
        outside_reference = file.references[('Package', 'Removed')][0]
        previous_rows = file.references[('Shared',)]
        previous_row_ids = [id(row) for row in previous_rows]

        package.short_name.value = 'Renamed'
        package.uuid = None
        shared = Reference('/Shared')
        package.child = Container(content=[shared, shared, Reference('/AddedTarget')])
        replacement = NamedNode(Text('Replaced'), uuid='replacement-id', child=Reference('/Shared'))
        added = NamedNode(Text('Added'), uuid='added-id')
        package.content = [right, replacement, left, added]
        left.content.clear()
        right.content.append(moved)
        moved.short_name.value = 'NewMoved'
        moved.uuid = 'new-moved-id'
        moved.child.value = '/AddedTarget'

        # 同一包装重复提交，验证改名后路径已同步，且引用不会越积越多。
        file.update_node(node)
        file.update_node(node)

        self.assertEqual(
            list(file.objects),
            [
                ('Before',),
                ('Renamed',),
                ('Renamed', 'Right'),
                ('Renamed', 'Right', 'NewMoved'),
                ('Renamed', 'Replaced'),
                ('Renamed', 'Left'),
                ('Renamed', 'Added'),
                ('PackageExtra',),
            ],
        )
        self.assertIs(file.ref(('Renamed', 'Replaced')).xml_obj, replacement)
        self.assertIsNot(file.ref(('Renamed',)), node)
        self.assertIs(file.ref(('Renamed',)).xml_obj, node.xml_obj)
        self.assertEqual(node.ref, ('Renamed',))
        self.assertIsNot(file.ref(('Renamed', 'Right', 'NewMoved')), moved_node)
        self.assertIs(file.ref(('Renamed', 'Right', 'NewMoved')).xml_obj, moved)
        self.assertEqual(file.ref(('Renamed', 'Right', 'NewMoved')).ref, ('Renamed', 'Right', 'NewMoved'))
        self.assertIs(file.ref(('PackageExtra',)), outside)
        self.assertIs(file.references[('Package', 'Removed')][0], outside_reference)
        self.assertEqual(incoming.value, '/Package/Removed')
        self.assertEqual([id(row) for row in previous_rows], previous_row_ids)
        for target in ('RemovedOnly', 'ReplacedOnly', 'OldOnly'):
            self.assertNotIn((target,), file.references)
        self.assertEqual(len(file.references[('Shared',)]), 5)
        self.assertEqual(sum(row.xml_obj is shared for row in file.references[('Shared',)]), 2)
        self.assertEqual(file.references[('AddedTarget',)][1].owner_ref, ('Renamed', 'Right', 'NewMoved'))
        for uuid in ('package-id', 'removed-id', 'replaced-id', 'moved-id'):
            self.assertNotIn(uuid, file.uuids)
        self.assertEqual(file.uuids['replacement-id'], ('Renamed', 'Replaced'))
        self.assertEqual(file.uuids['new-moved-id'], ('Renamed', 'Right', 'NewMoved'))

        # 用独立的全量扫描核对对象身份、引用来源与重复次数、UUID，不依赖合并的实现细节。
        expected = self.scan(root)
        self.assertEqual(list(file.objects), list(expected.objects))
        for ref, current in expected.objects.items():
            self.assertIs(file.objects[ref].xml_obj, current.xml_obj)
        self.assertEqual(
            Counter((target, row.owner_ref, id(row.xml_obj)) for target, rows in file.references.items() for row in rows),
            Counter((target, row.owner_ref, id(row.xml_obj)) for target, rows in expected.references.items() for row in rows),
        )
        self.assertEqual(file.uuids, expected.uuids)

    def test_update_node_invalid_descendant_keeps_all_previous_indexes(self):
        for attribute, value in (('short_name', Text('Bad/Name')), ('uuid', 42), ('child', Reference('relative'))):
            with self.subTest(attribute=attribute):
                child = NamedNode(Text('Child'), uuid='child-id', child=Reference('/Shared'))
                file = self.scan(NamedNode(Text('Package'), uuid='package-id', content=[child]))
                previous = file.objects, file.references, file.uuids
                node = file.ref(('Package',))
                node.xml_obj.short_name.value = 'Renamed'
                setattr(child, attribute, value)

                with self.assertRaises(ValueError):
                    file.update_node(node)

                for current, old in zip((file.objects, file.references, file.uuids), previous, strict=True):
                    self.assertIs(current, old)
                self.assertEqual(previous[1][('Shared',)][0].owner_ref, ('Package', 'Child'))

    def test_update_node_uuid_order_handles_reordering_and_removal(self):
        first = NamedNode(Text('First'), uuid='duplicate')
        last = NamedNode(Text('Last'), uuid='duplicate')
        package = NamedNode(Text('Package'), content=[first, last])
        outside = NamedNode(Text('Outside'), uuid='duplicate')
        file = self.scan(Container(content=[package, outside]))
        node = file.ref(('Package',))

        package.content.reverse()
        file.update_node(node)
        self.assertEqual(file.uuids['duplicate'], ('Outside',))
        outside.uuid = ''
        file.update_node(file.ref(('Outside',)))
        self.assertEqual(file.uuids['duplicate'], ('Package', 'First'))
        package.content.remove(first)
        file.update_node(node)
        self.assertEqual(file.uuids['duplicate'], ('Package', 'Last'))
        last.uuid = None
        file.update_node(node)
        self.assertNotIn('duplicate', file.uuids)

    def test_update_node_creates_new_wrappers_and_refreshes_input_ref(self):
        child = NamedNode(Text('Child'), uuid='child-id')
        file = self.scan(NamedNode(Text('Package'), child=child))
        parent_node = file.ref(('Package',))
        child_node = file.ref(('Package', 'Child'))

        parent_node.xml_obj.short_name.value = 'Renamed'
        file.update_node(parent_node)
        self.assertIsNot(file.ref(('Renamed',)), parent_node)
        self.assertIs(file.ref(('Renamed',)).xml_obj, parent_node.xml_obj)
        self.assertEqual(parent_node.ref, ('Renamed',))
        self.assertIsNot(file.ref(('Renamed', 'Child')), child_node)
        self.assertEqual(child_node.ref, ('Package', 'Child'))
        child_node = file.ref(('Renamed', 'Child'))
        self.assertEqual(child_node.ref, ('Renamed', 'Child'))
        child.short_name.value = 'NewChild'
        file.update_node(child_node)

        self.assertEqual(list(file.objects), [('Renamed',), ('Renamed', 'NewChild')])
        self.assertIsNot(file.ref(('Renamed', 'NewChild')), child_node)
        self.assertIs(file.ref(('Renamed', 'NewChild')).xml_obj, child)
        self.assertEqual(child_node.ref, ('Renamed', 'NewChild'))
        self.assertEqual(file.uuids, {'child-id': ('Renamed', 'NewChild')})

        with self.edit(file, parent_node) as obj:
            obj.short_name.value = 'RenamedAgain'
        self.assertIsNot(file.ref(('RenamedAgain',)), parent_node)
        self.assertIs(file.ref(('RenamedAgain',)).xml_obj, parent_node.xml_obj)
        self.assertEqual(parent_node.ref, ('RenamedAgain',))
        self.assertIs(file.ref(('RenamedAgain', 'NewChild')).xml_obj, child)
        self.assertEqual(file.ref(('RenamedAgain', 'NewChild')).ref, ('RenamedAgain', 'NewChild'))
