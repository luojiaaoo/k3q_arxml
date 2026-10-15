import sys
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from k3q_arxml import ArxmlFile, ArxmlObject, ArxmlReference


@dataclass(slots=True)
class Text:
    value: str = ''


@dataclass(slots=True)
class Reference(Text):
    base: str | None = field(default=None, metadata={'name': 'BASE', 'type': 'Attribute'})


@dataclass(slots=True)
class ReferenceInner(Reference):
    dest: str = field(default='TYPE', metadata={'name': 'DEST', 'type': 'Attribute'})


@dataclass(slots=True)
class IndirectReference(ReferenceInner):
    pass


@dataclass
class LookalikeRef:
    value: str
    dest: str = 'TYPE'


@dataclass(slots=True)
class NamedBase:
    short_name: Text = field(metadata={'name': 'SHORT-NAME', 'type': 'Element'})
    uuid: str | None = field(default=None, metadata={'name': 'UUID', 'type': 'Attribute'})


@dataclass(slots=True)
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

    def test_fields_sequences_inheritance_and_reference_identity(self):
        first = Reference('/Types/Target')
        second = ReferenceInner('/Types/Target')
        third = IndirectReference('/Types/Target')
        child = NamedNode(Text('Child'), uuid='child-id', child=Container(value=second))
        package = NamedNode(Text('Package'), child=first, content=['mixed text', child, (None, 42, third)])
        root = Container(value=package)

        file = self.scan(root)

        self.assertEqual(list(file.objects), [('Package',), ('Package', 'Child')])
        self.assertIs(file.ref(('Package',)).xml_obj, package)
        self.assertIs(file.ref(('Package', 'Child')).xml_obj, child)
        rows = file.references[('Types', 'Target')]
        self.assertEqual([row.owner_ref for row in rows], [('Package',), ('Package', 'Child'), ('Package',)])
        for row, expected in zip(rows, (first, second, third), strict=True):
            self.assertIsInstance(row, ArxmlReference)
            node = row.node
            self.assertIsInstance(node, ArxmlObject)
            self.assertIs(node.xml_obj, expected)
            self.assertIs(row.xml_obj, expected)
            self.assertIs(node.file, file)
            self.assertEqual(node.ref, row.owner_ref)
            self.assertEqual(node.filename, Path('scan.arxml').resolve())
            self.assertEqual(row.filename, node.filename)
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
        self.assertTrue(all(row.node.xml_obj is reference for row in rows))

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
        self.assertEqual(file.references, {('Package', 'New'): [ArxmlReference(ArxmlObject(reference, file, ('Package',)), ('Package',))]})
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

        self.assertIs(file.references[('Target',)][0].node.xml_obj, reference)
        self.assertEqual(file.references[('Target',)][0].owner_ref, ('Package',))

    def test_wrapper_failure_does_not_publish_partial_indexes(self):
        file = self.scan(NamedNode(Text('Package'), uuid='package-id'))
        previous = file.objects, file.references, file.uuids
        with patch('k3q_arxml.arxml_file.ArxmlObject', side_effect=RuntimeError('wrapper failure')):
            with self.assertRaisesRegex(RuntimeError, 'wrapper failure'):
                file.scan_ref()
        for current, old in zip((file.objects, file.references, file.uuids), previous, strict=True):
            self.assertIs(current, old)

    def test_reference_without_named_owner_can_be_edited_through_wrapper(self):
        reference = Reference('/Old')
        file = self.scan(Container(value=reference))
        row = file.references[('Old',)][0]
        node = row.node
        self.assertIs(node.xml_obj, reference)
        self.assertIs(node.file, file)
        self.assertEqual(node.ref, ())
        self.assertEqual(row.owner_ref, ())

        node.xml_obj.value = '/New'
        file.scan_ref()

        self.assertNotIn(('Old',), file.references)
        self.assertIs(file.references[('New',)][0].node.xml_obj, reference)

    def test_reference_record_failure_keeps_previous_indexes(self):
        file = self.scan(Container(value=Reference('/Target')))
        previous = file.objects, file.references, file.uuids
        with patch('k3q_arxml.arxml_file.ArxmlReference', side_effect=RuntimeError('reference record failure')):
            with self.assertRaisesRegex(RuntimeError, 'reference record failure'):
                file.scan_ref()
        for current, old in zip((file.objects, file.references, file.uuids), previous, strict=True):
            self.assertIs(current, old)

    def test_reference_wrapper_failure_keeps_previous_indexes(self):
        file = self.scan(Container(value=Reference('/Target')))
        previous = file.objects, file.references, file.uuids
        with patch('k3q_arxml.arxml_file.ArxmlObject', side_effect=RuntimeError('reference wrapper failure')):
            with self.assertRaisesRegex(RuntimeError, 'reference wrapper failure'):
                file.scan_ref()
        for current, old in zip((file.objects, file.references, file.uuids), previous, strict=True):
            self.assertIs(current, old)
