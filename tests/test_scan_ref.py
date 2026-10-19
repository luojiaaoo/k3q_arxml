from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest

from k3q_arxml import ArxmlFile, ArxmlNamedNode, ArxmlNode, ArxmlRefNode, ArxmlTransaction


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


class TestScanRef:
    @pytest.fixture(autouse=True)
    def setup_binding(self):
        # 用小型 dataclass 绑定验证遍历规则，显式替换测试使用的绑定模块。
        binding = ModuleType('k3q_arxml.schemas.autosar_4_2_2')
        binding.SCHEMA_VERSION = 'test'
        binding.Autosar = Container
        binding.Ref = Reference
        self.binding = binding

    def scan(self, root):
        return ArxmlFile(binding=self.binding).parse_autosar(Path('scan.arxml'), root)

    def test_rejects_dataclass_without_instance_dict(self):
        @dataclass(slots=True)
        class SlotNode:
            value: str = 'child'

        with pytest.raises(TypeError, match='scan\\.arxml.*SlotNode.*__dict__.*arxml_parent'):
            self.scan(Container(value=SlotNode()))

    def test_parent_field_is_not_overwritten(self):
        @dataclass
        class HasParent:
            parent: str = 'original'
            child: object = None

        root = HasParent(child=Container())
        self.scan(root)

        assert root.parent == 'original'
        assert root.arxml_parent is None
        assert root.child.arxml_parent is root
        assert callable(root.edited)
        assert callable(root.child.edited)

    def test_rejects_arxml_parent_field_collision(self):
        @dataclass
        class HasArxmlParent:
            arxml_parent: str = 'original'

        with pytest.raises(TypeError, match='HasArxmlParent.*已声明 arxml_parent 字段'):
            self.scan(HasArxmlParent())

    def test_rejects_edited_field_collision(self):
        @dataclass
        class HasEdited:
            edited: str = 'original'

        with pytest.raises(TypeError, match='HasEdited.*已声明 edited 字段'):
            self.scan(HasEdited())

    def test_fields_sequences_inheritance_and_reference_identity(self):
        first = Reference('/Types/Target')
        second = ReferenceInner('/Types/Target')
        third = IndirectReference('/Types/Target')
        child = NamedNode(Text('Child'), uuid='child-id', child=Container(value=second))
        package = NamedNode(Text('Package'), child=first, content=['mixed text', child, (None, 42, third)])
        root = Container(value=package)

        file = self.scan(root)

        assert list(file.index.objects) == [('Package',), ('Package', 'Child')]
        assert all((isinstance(node, ArxmlNode) for node in file.index.objects.values()))
        assert file.ref(('Package',)).xml_obj is package
        assert file.ref(('Package', 'Child')).xml_obj is child
        rows = file.index.references[('Types', 'Target')]
        assert [row.owner_ref for row in rows] == [('Package',), ('Package', 'Child'), ('Package',)]
        for row, expected in zip(rows, (first, second, third), strict=True):
            assert isinstance(row, ArxmlRefNode)
            assert isinstance(row, ArxmlNode)
            assert not isinstance(row, ArxmlNamedNode)
            assert row.xml_obj is expected
            assert callable(row.xml_obj.edited)
        assert file.index.uuids == {'child-id': ('Package', 'Child')}

    def test_only_declared_child_fields_and_ref_instances_are_indexed(self):
        ignored = Reference('/Ignored')
        root = Container(
            content=[LookalikeRef('/Lookalike'), '/Text', {'key': ignored}],
            attributes={'custom': ignored},
            attribute='/Ignored',  # XML 属性使用普通文本；路径形式的文本也不应被登记为引用。
        )
        root.extra = ignored

        file = self.scan(root)

        assert file.index.objects == {}
        assert file.index.references == {}
        assert file.index.uuids == {}

    def test_shared_branches_and_repeated_references_are_not_deduplicated(self):
        reference = Reference('/Unloaded/Target')
        shared = Container(value=reference)
        root = Container(content=[NamedNode(Text('A'), content=[shared, shared]), NamedNode(Text('B'), child=shared)])

        file = self.scan(root)

        rows = file.index.references[('Unloaded', 'Target')]
        assert [row.owner_ref for row in rows] == [('A',), ('A',), ('B',)]
        assert all((row.xml_obj is reference for row in rows))

    def test_uuid_and_duplicate_path_overwrite_order_is_preserved(self):
        first = NamedNode(Text('Same'), uuid='duplicate')
        last = NamedNode(Text('Same'), uuid='')
        other = NamedNode(Text('Other'), uuid='duplicate')
        root = Container(content=[first, last, other, NamedNode(Text('WithoutUuid'))])

        file = self.scan(root)

        assert file.ref(('Same',)).xml_obj is last
        assert file.index.uuids == {'duplicate': ('Other',)}

    def test_rescan_replaces_paths_and_does_not_accumulate_references(self):
        reference = Reference('/Package/Old')
        target = NamedNode(Text('Old'), uuid='target-id')
        root = NamedNode(Text('Package'), child=reference, content=[target])
        file = self.scan(root)
        target.short_name.value = 'New'
        reference.value = '/Package/New'

        file.scan_ref()
        file.scan_ref()

        assert file.ref(('Package', 'Old')) is None
        assert file.ref(('Package', 'New')).xml_obj is target
        assert file.index.references == {('Package', 'New'): [ArxmlRefNode(xml_obj=reference, owner_ref=('Package',))]}
        assert file.index.uuids == {'target-id': ('Package', 'New')}

    @pytest.mark.parametrize('value', (None, 123, '', '/', '/Package/', '/Package//Target', 'Package/Target'))
    def test_invalid_references_report_location_and_keep_previous_indexes(self, value):
        reference = Reference('/Target')
        file = self.scan(NamedNode(Text('Package'), uuid='package-id', child=reference))
        previous = file.index.objects, file.index.references, file.index.uuids
        reference.value = value
        with pytest.raises(ValueError) as caught:
            file.scan_ref()
        message = str(caught.value)
        for text in ('scan.arxml', '/Package', 'Reference.value'):
            assert text in message
        for current, old in zip((file.index.objects, file.index.references, file.index.uuids), previous, strict=True):
            assert current is old

    @pytest.mark.parametrize('short_name', (None, Text(''), Text('  '), Text('Bad/Name'), Text(42)))
    def test_invalid_short_names_report_the_field(self, short_name):
        with pytest.raises(ValueError, match='scan.arxml: /Package .*NamedNode.short_name.*SHORT-NAME'):
            self.scan(NamedNode(Text('Package'), child=NamedNode(short_name)))

    def test_invalid_uuid_reports_the_field(self):
        with pytest.raises(ValueError, match='NamedNode.uuid.*UUID'):
            self.scan(NamedNode(Text('Package'), uuid=42))

    def test_nested_containment_preserves_reference_owner(self):
        reference = Reference('/Target')
        nested = reference
        for _ in range(64):
            nested = Container(value=nested)

        file = self.scan(NamedNode(Text('Package'), child=nested))

        assert file.index.references[('Target',)][0].xml_obj is reference
        assert file.index.references[('Target',)][0].owner_ref == ('Package',)

    def test_wrapper_failure_does_not_publish_partial_indexes(self):
        file = self.scan(NamedNode(Text('Package'), uuid='package-id'))
        previous = file.index.objects, file.index.references, file.index.uuids
        with patch('k3q_arxml.arxml_file.ArxmlNamedNode', side_effect=RuntimeError('wrapper failure')):
            with pytest.raises(RuntimeError, match='wrapper failure'):
                file.scan_ref()
        for current, old in zip((file.index.objects, file.index.references, file.index.uuids), previous, strict=True):
            assert current is old

    def test_reference_without_named_owner_can_be_edited_through_wrapper(self):
        reference = Reference('/Old')
        file = self.scan(Container(value=reference))
        row = file.index.references[('Old',)][0]
        assert row.xml_obj is reference
        assert row.owner_ref == ()

        with pytest.raises(ValueError, match='没有具名祖先'):
            reference.edited()

        row.xml_obj.value = '/New'
        file.scan_ref()

        assert ('Old',) not in file.index.references
        assert file.index.references[('New',)][0].xml_obj is reference

    def test_reference_record_failure_keeps_previous_indexes(self):
        file = self.scan(Container(value=Reference('/Target')))
        previous = file.index.objects, file.index.references, file.index.uuids
        with patch('k3q_arxml.arxml_file.ArxmlRefNode', side_effect=RuntimeError('reference record failure')):
            with pytest.raises(RuntimeError, match='reference record failure'):
                file.scan_ref()
        for current, old in zip((file.index.objects, file.index.references, file.index.uuids), previous, strict=True):
            assert current is old

    def test_reference_does_not_use_named_node_wrapper(self):
        reference = Reference('/Target')
        with patch('k3q_arxml.arxml_file.ArxmlNamedNode', side_effect=RuntimeError('unexpected named node wrapper')):
            file = self.scan(Container(value=reference))
        assert file.index.objects == {}
        assert file.index.references[('Target',)][0].xml_obj is reference

    def test_edit_nested_named_root_refreshes_objects_references_and_uuids(self):
        reference = Reference('/Package/Owner/Old')
        target = NamedNode(Text('Old'), uuid='old-target')
        owner = NamedNode(Text('Owner'), uuid='old-owner', child=reference, content=[target])
        file = self.scan(Container(content=[NamedNode(Text('Package'), content=[owner]), NamedNode(Text('Other'))]))

        assert file.ref(('Package', 'Owner')).xml_obj is owner
        owner.short_name.value = 'Renamed'
        owner.uuid = 'new-owner'
        target.short_name.value = 'New'
        target.uuid = 'new-target'
        reference.value = '/Package/Renamed/New'
        owner.content.append(NamedNode(Text('Added')))
        assert owner.edited() is owner

        assert file.ref(('Package', 'Owner')) is None
        assert file.ref(('Package', 'Renamed', 'New')).xml_obj is target
        assert file.ref(('Package', 'Renamed', 'Added')) is not None
        assert file.ref(('Other',)) is not None
        assert ('Package', 'Owner', 'Old') not in file.index.references
        assert file.index.references[('Package', 'Renamed', 'New')][0].owner_ref == ('Package', 'Renamed')
        assert file.index.uuids == {'new-owner': ('Package', 'Renamed'), 'new-target': ('Package', 'Renamed', 'New')}

    def test_edit_removal_refreshes_indexes(self):
        target = NamedNode(Text('Child'), uuid='child-id', child=Reference('/Target'))
        file = self.scan(NamedNode(Text('Package'), content=[target]))

        package = file.ref(('Package',)).xml_obj
        package.content.clear()
        package.edited()

        assert file.ref(('Package', 'Child')) is None
        assert file.index.references == {}
        assert file.index.uuids == {}

    def test_edit_updates_only_when_called(self):
        file = self.scan(NamedNode(Text('Package')))
        obj = file.ref(('Package',)).xml_obj
        obj.short_name.value = 'Renamed'
        assert file.ref(('Package',)) is not None
        assert file.ref(('Renamed',)) is None
        assert obj.edited() is obj
        assert file.ref(('Package',)) is None
        assert file.ref(('Renamed',)) is not None

    @pytest.mark.parametrize('target', ['root', 'named', 'child'])
    def test_edit_without_refresh_only_marks_dirty(self, target):
        child = Text('before')
        named = NamedNode(Text('Package'), uuid='package-id', child=child, content=[Reference('/Target')])
        root = Container(value='before', content=[named])
        file = self.scan(root)
        previous = file.index
        obj = {'root': root, 'named': named, 'child': child}[target]
        root.value = 'after'
        child.value = 'after'
        assert not file._dirty

        with patch.object(file, 'update_node') as update, patch.object(file, '_get_fields') as get_fields:
            assert obj.edited(refresh_index=False) is obj
            update.assert_not_called()
            get_fields.assert_not_called()

        assert file._dirty
        assert file.index is previous
        assert file.ref(('Package',)).xml_obj is named
        assert file.index.references[('Target',)][0].xml_obj is named.content[0]
        assert file.index.uuids == {'package-id': ('Package',)}

    def test_edit_invalid_data_preserves_previous_indexes(self):
        reference = Reference('/Target')
        file = self.scan(NamedNode(Text('Package'), child=reference))
        previous = file.index.objects, file.index.references, file.index.uuids
        reference.value = 'invalid-relative-ref'
        with pytest.raises(ValueError):
            reference.edited()
        for current, old in zip((file.index.objects, file.index.references, file.index.uuids), previous, strict=True):
            assert current is old

    def test_transaction_defers_related_edits_across_files(self):
        target = NamedNode(Text('Target'), uuid='old-id')
        reference = Reference('/Target')
        target_file = self.scan(target)
        source_file = ArxmlFile(binding=self.binding).parse_autosar(Path('source.arxml'), NamedNode(Text('Source'), child=reference))
        previous_target = target_file.index
        previous_source = source_file.index

        with ArxmlTransaction() as transaction:
            target.short_name.value = 'Renamed'
            target.uuid = 'new-id'
            transaction.add(target)
            reference.value = '/Renamed'
            transaction.add(reference)
            assert target_file.index is previous_target
            assert source_file.index is previous_source
            assert not target_file._dirty
            assert not source_file._dirty

        assert target_file.ref(('Target',)) is None
        assert target_file.ref(('Renamed',)).xml_obj is target
        assert target_file.index.uuids == {'new-id': ('Renamed',)}
        assert ('Target',) not in source_file.index.references
        assert source_file.index.references[('Renamed',)][0].xml_obj is reference
        assert target_file._dirty and source_file._dirty

    @pytest.mark.parametrize('flags', [(False, False), (False, True), (True, False)])
    def test_transaction_duplicate_add_keeps_refresh_requirement(self, flags):
        obj = NamedNode(Text('Package'), child=Text('before'))
        file = self.scan(obj)
        previous = file.index

        with patch.object(file, 'update_node', wraps=file.update_node) as update:
            with ArxmlTransaction() as transaction:
                obj.child.value = 'after'
                for refresh_index in flags:
                    transaction.add(obj, refresh_index=refresh_index)
                update.assert_not_called()
            assert update.call_count == int(any(flags))

        assert file._dirty
        assert (file.index is previous) == (not any(flags))

    def test_transaction_body_exception_skips_refresh_without_reverting_objects(self):
        obj = NamedNode(Text('Package'))
        file = self.scan(obj)
        previous = file.index

        with pytest.raises(RuntimeError, match='edit failed'):
            with ArxmlTransaction() as transaction:
                transaction.add(obj)
                obj.short_name.value = 'Renamed'
                raise RuntimeError('edit failed')

        assert obj.short_name.value == 'Renamed'
        assert file.index is previous
        assert not file._dirty

    def test_transaction_refresh_failure_keeps_completed_updates_and_stops(self):
        first = NamedNode(Text('First'))
        invalid = NamedNode(Text('Invalid'), child=Reference('/Target'))
        last = NamedNode(Text('Last'))
        file = self.scan(Container(content=[first, invalid, last]))

        with pytest.raises(ValueError, match='不支持相对引用'):
            with ArxmlTransaction() as transaction:
                first.short_name.value = 'RenamedFirst'
                transaction.add(first)
                invalid.child.value = 'relative'
                transaction.add(invalid)
                last.short_name.value = 'RenamedLast'
                transaction.add(last)

        assert file.ref(('RenamedFirst',)).xml_obj is first
        assert file.ref(('Last',)).xml_obj is last
        assert file.ref(('RenamedLast',)) is None
        assert file.index.references[('Target',)][0].xml_obj is invalid.child

    def test_edit_scans_only_its_subtree_and_keeps_other_wrappers(self):
        changed = NamedNode(Text('A'), child=Reference('/Shared'))
        untouched = NamedNode(Text('B'), child=Reference('/Shared'))
        root = Container(content=[changed, untouched])
        file = self.scan(root)
        other = file.ref(('B',))
        other_reference = file.index.references[('Shared',)][1]

        with patch.object(file, 'scan_ref', side_effect=AssertionError('unexpected full scan')):
            with patch.object(file, '_get_fields', wraps=file._get_fields) as get_fields:
                changed.child.value = '/Changed'
                changed.child.edited()
        visited = [call.args[0] for call in get_fields.call_args_list]
        assert any((value is changed for value in visited))
        assert not any((value is root or value is untouched or value is untouched.child for value in visited))
        assert file.ref(('B',)) is other
        assert file.index.references[('Shared',)] == [other_reference]
        assert file.index.references[('Shared',)][0] is other_reference
        assert file.index.references[('Changed',)][0].owner_ref == ('A',)

    def test_edit_rename_keeps_external_incoming_references(self):
        target = NamedNode(Text('A'))
        reference = Reference('/A')
        file = self.scan(Container(content=[target, NamedNode(Text('B'), child=reference)]))
        incoming = file.index.references[('A',)][0]
        target.short_name.value = 'Renamed'
        target.short_name.edited()
        assert file.ref(('A',)) is None
        assert file.ref(('Renamed',)).xml_obj is target
        assert file.index.references[('A',)][0] is incoming
        assert reference.value == '/A'

    def test_edit_uuid_duplicates_keep_document_order_and_restore_previous_owner(self):
        first = NamedNode(Text('A'), uuid='duplicate')
        last = NamedNode(Text('B'), uuid='duplicate')
        file = self.scan(Container(content=[first, last]))
        first.uuid = 'duplicate'
        first.edited()
        assert file.index.uuids['duplicate'] == ('B',)
        last.uuid = None
        last.edited()
        assert file.index.uuids['duplicate'] == ('A',)

    def test_edit_path_conflict_and_wrapper_failure_preserve_previous_indexes(self):
        file = self.scan(Container(content=[NamedNode(Text('A'), child=NamedNode(Text('Child'))), NamedNode(Text('B'))]))
        previous = file.index.objects, file.index.references, file.index.uuids
        node = file.ref(('A',))
        child_node = file.ref(('A', 'Child'))
        obj = node.xml_obj
        obj.short_name.value = 'B'
        with pytest.raises(ValueError, match='路径.*冲突'):
            obj.edited()
        for current, old in zip((file.index.objects, file.index.references, file.index.uuids), previous, strict=True):
            assert current is old
        assert node.ref == ('A',)
        node.xml_obj.short_name.value = 'A'
        obj.short_name.value = 'Renamed'
        obj.child.short_name.value = 'RenamedChild'
        obj.content.append(NamedNode(Text('Added')))
        with patch('k3q_arxml.arxml_file.ArxmlNamedNode.__init__', side_effect=RuntimeError('wrapper failure')):
            with pytest.raises(RuntimeError, match='wrapper failure'):
                obj.edited()
        for current, old in zip((file.index.objects, file.index.references, file.index.uuids), previous, strict=True):
            assert current is old
        assert node.ref == ('A',)
        assert child_node.ref == ('A', 'Child')
        obj.edited()
        assert file.ref(('B',)) is previous[0][('B',)]
        assert node.ref == ('Renamed',)
        assert file.ref(('Renamed',)).xml_obj is node.xml_obj
        assert file.ref(('Renamed', 'RenamedChild')).xml_obj is child_node.xml_obj

    def test_nested_edit_of_renamed_root_refreshes_current_path(self):
        file = self.scan(NamedNode(Text('Package'), child=NamedNode(Text('Child'))))
        node = file.ref(('Package',))
        package = node.xml_obj
        package.short_name.value = 'Renamed'
        assert package.edited() is package
        package.uuid = 'new-id'
        package.edited()
        package.child.short_name.value = 'NewChild'
        package.edited()
        assert set(file.index.objects) == {('Renamed',), ('Renamed', 'NewChild')}
        assert file.index.uuids == {'new-id': ('Renamed',)}

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
        outside_reference = file.index.references[('Package', 'Removed')][0]
        previous_rows = file.index.references[('Shared',)]
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

        assert list(file.index.objects) == [
            ('Before',),
            ('Renamed',),
            ('Renamed', 'Right'),
            ('Renamed', 'Right', 'NewMoved'),
            ('Renamed', 'Replaced'),
            ('Renamed', 'Left'),
            ('Renamed', 'Added'),
            ('PackageExtra',),
        ]
        assert file.ref(('Renamed', 'Replaced')).xml_obj is replacement
        assert file.ref(('Renamed',)) is not node
        assert file.ref(('Renamed',)).xml_obj is node.xml_obj
        assert node.ref == ('Renamed',)
        assert file.ref(('Renamed', 'Right', 'NewMoved')) is not moved_node
        assert file.ref(('Renamed', 'Right', 'NewMoved')).xml_obj is moved
        assert file.ref(('Renamed', 'Right', 'NewMoved')).ref == ('Renamed', 'Right', 'NewMoved')
        assert file.ref(('PackageExtra',)) is outside
        assert file.index.references[('Package', 'Removed')][0] is outside_reference
        assert incoming.value == '/Package/Removed'
        assert [id(row) for row in previous_rows] == previous_row_ids
        for target in ('RemovedOnly', 'ReplacedOnly', 'OldOnly'):
            assert (target,) not in file.index.references
        assert len(file.index.references[('Shared',)]) == 5
        assert sum((row.xml_obj is shared for row in file.index.references[('Shared',)])) == 2
        assert file.index.references[('AddedTarget',)][1].owner_ref == ('Renamed', 'Right', 'NewMoved')
        for uuid in ('package-id', 'removed-id', 'replaced-id', 'moved-id'):
            assert uuid not in file.index.uuids
        assert file.index.uuids['replacement-id'] == ('Renamed', 'Replaced')
        assert file.index.uuids['new-moved-id'] == ('Renamed', 'Right', 'NewMoved')

        # 用独立的全量扫描核对对象身份、引用来源与重复次数、UUID，不依赖合并的实现细节。
        expected = self.scan(root)
        assert list(file.index.objects) == list(expected.index.objects)
        for ref, current in expected.index.objects.items():
            assert file.index.objects[ref].xml_obj is current.xml_obj
        assert Counter(((target, row.owner_ref, id(row.xml_obj)) for target, rows in file.index.references.items() for row in rows)) == Counter(
            ((target, row.owner_ref, id(row.xml_obj)) for target, rows in expected.index.references.items() for row in rows)
        )
        assert file.index.uuids == expected.index.uuids

    @pytest.mark.parametrize('attribute, value', (('short_name', Text('Bad/Name')), ('uuid', 42), ('child', Reference('relative'))))
    def test_update_node_invalid_descendant_keeps_all_previous_indexes(self, attribute, value):
        child = NamedNode(Text('Child'), uuid='child-id', child=Reference('/Shared'))
        file = self.scan(NamedNode(Text('Package'), uuid='package-id', content=[child]))
        previous = file.index.objects, file.index.references, file.index.uuids
        node = file.ref(('Package',))
        node.xml_obj.short_name.value = 'Renamed'
        setattr(child, attribute, value)

        with pytest.raises(ValueError):
            file.update_node(node)

        for current, old in zip((file.index.objects, file.index.references, file.index.uuids), previous, strict=True):
            assert current is old
        assert previous[1][('Shared',)][0].owner_ref == ('Package', 'Child')

    def test_update_node_uuid_order_handles_reordering_and_removal(self):
        first = NamedNode(Text('First'), uuid='duplicate')
        last = NamedNode(Text('Last'), uuid='duplicate')
        package = NamedNode(Text('Package'), content=[first, last])
        outside = NamedNode(Text('Outside'), uuid='duplicate')
        file = self.scan(Container(content=[package, outside]))
        node = file.ref(('Package',))

        package.content.reverse()
        file.update_node(node)
        assert file.index.uuids['duplicate'] == ('Outside',)
        outside.uuid = ''
        file.update_node(file.ref(('Outside',)))
        assert file.index.uuids['duplicate'] == ('Package', 'First')
        package.content.remove(first)
        file.update_node(node)
        assert file.index.uuids['duplicate'] == ('Package', 'Last')
        last.uuid = None
        file.update_node(node)
        assert 'duplicate' not in file.index.uuids

    def test_update_node_creates_new_wrappers_and_refreshes_input_ref(self):
        child = NamedNode(Text('Child'), uuid='child-id')
        file = self.scan(NamedNode(Text('Package'), child=child))
        parent_node = file.ref(('Package',))
        child_node = file.ref(('Package', 'Child'))

        parent_node.xml_obj.short_name.value = 'Renamed'
        file.update_node(parent_node)
        assert file.ref(('Renamed',)) is not parent_node
        assert file.ref(('Renamed',)).xml_obj is parent_node.xml_obj
        assert parent_node.ref == ('Renamed',)
        assert file.ref(('Renamed', 'Child')) is not child_node
        assert child_node.ref == ('Package', 'Child')
        child_node = file.ref(('Renamed', 'Child'))
        assert child_node.ref == ('Renamed', 'Child')
        child.short_name.value = 'NewChild'
        file.update_node(child_node)

        assert list(file.index.objects) == [('Renamed',), ('Renamed', 'NewChild')]
        assert file.ref(('Renamed', 'NewChild')) is not child_node
        assert file.ref(('Renamed', 'NewChild')).xml_obj is child
        assert child_node.ref == ('Renamed', 'NewChild')
        assert file.index.uuids == {'child-id': ('Renamed', 'NewChild')}

        parent_node.xml_obj.short_name.value = 'RenamedAgain'
        assert parent_node.xml_obj.edited() is parent_node.xml_obj
        assert file.ref(('RenamedAgain',)) is not parent_node
        assert file.ref(('RenamedAgain',)).xml_obj is parent_node.xml_obj
        assert parent_node.ref == ('Renamed',)
        assert file.ref(('RenamedAgain', 'NewChild')).xml_obj is child
        assert file.ref(('RenamedAgain', 'NewChild')).ref == ('RenamedAgain', 'NewChild')
