"""路径约束属于核心层，叶子类型由 schema 定义决定。"""

from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

import pytest

from k3q_arxml import ArxmlFile, IOArxml
from k3q_arxml.schemas import autosar_4_2_2 as autosar
from k3q_arxml.validation import DuplicatePathError, is_schema_leaf


@dataclass
class Name:
    value: str


@dataclass
class Leaf:
    short_name: Name = field(metadata={'name': 'SHORT-NAME', 'type': 'Element'})


@dataclass
class Wrapper:
    leaf: Leaf | None = None


@dataclass
class Container:
    short_name: Name = field(metadata={'name': 'SHORT-NAME', 'type': 'Element'})
    wrapper: Wrapper | None = None


@dataclass
class RecursiveContainer:
    short_name: Name = field(metadata={'name': 'SHORT-NAME', 'type': 'Element'})
    child: 'RecursiveContainer | None' = None


@dataclass
class ChoiceContainer:
    short_name: Name = field(metadata={'name': 'SHORT-NAME', 'type': 'Element'})
    choice: list[object] = field(default_factory=list, metadata={'type': 'Elements', 'choices': ({'name': 'LEAF', 'type': Leaf},)})


@pytest.fixture
def binding():
    module = ModuleType('validation_test_binding')
    module.SCHEMA_VERSION = '4.2.2'
    module.Autosar = Container
    module.Ref = autosar.Ref
    return module


@pytest.mark.parametrize('clazz', [Container, RecursiveContainer, ChoiceContainer, autosar.ArPackage, autosar.SenderReceiverInterface])
def test_optional_wrapped_recursive_and_choice_children_prevent_schema_leaf_classification(clazz):
    assert not is_schema_leaf(clazz)


@pytest.mark.parametrize('clazz', [Leaf, autosar.XrefTarget, autosar.Caption])
def test_schema_leaf_classification(clazz):
    assert is_schema_leaf(clazz)


def test_empty_container_paths_may_repeat_in_core_engineering_api(tmp_path):
    paths = [tmp_path / f'{index}.arxml' for index in range(2)]
    for path in paths:
        path.write_text(
            '<AUTOSAR xmlns="http://autosar.org/schema/r4.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xsi:schemaLocation="http://autosar.org/schema/r4.0 AUTOSAR_4-2-2.xsd">'
            '<AR-PACKAGES><AR-PACKAGE><SHORT-NAME>Shared</SHORT-NAME></AR-PACKAGE></AR-PACKAGES></AUTOSAR>',
            encoding='utf-8',
        )
    io = IOArxml([paths[0]], binding=autosar)
    io.append([paths[1]])
    assert len(io.files) == 2
    assert len(io.ar(autosar.ArPackage)) == 2
    with pytest.raises(ValueError, match='存在于多个文件'):
        io.ref(('Shared',))


def test_core_add_file_checks_leaf_paths_and_keeps_project_atomic(tmp_path, binding):
    first = ArxmlFile(binding=binding).parse_autosar(tmp_path / 'first.arxml', Container(Name('Shared'), Wrapper(Leaf(Name('Unique')))))
    second = ArxmlFile(binding=binding).parse_autosar(tmp_path / 'second.arxml', Container(Name('Shared'), Wrapper(Leaf(Name('Other')))))
    duplicate = ArxmlFile(binding=binding).parse_autosar(tmp_path / 'duplicate.arxml', Container(Name('Shared'), Wrapper(Leaf(Name('Unique')))))
    io = IOArxml([], binding=binding)
    io.add_file(first)
    io.add_file(second)
    with pytest.raises(DuplicatePathError) as caught:
        io.add_file(duplicate)
    assert caught.value.ref == ('Shared', 'Unique')
    assert set(io.files) == {first.filepath, second.filepath}


@pytest.mark.parametrize('conflict_with', ['existing', 'batch'])
def test_batch_append_rejects_global_leaf_conflicts_atomically(tmp_path, conflict_with):
    def write_file(filename, package, leaf):
        path = tmp_path / filename
        path.write_text(
            '<AUTOSAR xmlns="http://autosar.org/schema/r4.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xsi:schemaLocation="http://autosar.org/schema/r4.0 AUTOSAR_4-2-2.xsd">'
            f'<AR-PACKAGES><AR-PACKAGE><SHORT-NAME>{package}</SHORT-NAME><DESC><L-2 L="EN">'
            f'<XREF-TARGET><SHORT-NAME>{leaf}</SHORT-NAME></XREF-TARGET>'
            '</L-2></DESC></AR-PACKAGE></AR-PACKAGES></AUTOSAR>',
            encoding='utf-8',
        )
        return path

    existing = write_file('existing.arxml', 'Existing', 'Keep')
    valid = write_file('valid.arxml', 'Shared', 'New')
    duplicate = write_file('duplicate.arxml', 'Existing' if conflict_with == 'existing' else 'Shared', 'Keep' if conflict_with == 'existing' else 'New')
    io = IOArxml([existing], binding=autosar)
    original = io.files.copy()
    with pytest.raises(DuplicatePathError):
        io.append([valid, duplicate])
    assert io.files == original


def test_add_files_rejects_conflicts_within_batch_atomically(tmp_path, binding):
    first = ArxmlFile(binding=binding).parse_autosar(tmp_path / 'first.arxml', Container(Name('Shared'), Wrapper(Leaf(Name('Repeated')))))
    second = ArxmlFile(binding=binding).parse_autosar(tmp_path / 'second.arxml', Container(Name('Shared'), Wrapper(Leaf(Name('Repeated')))))
    io = IOArxml([], binding=binding)
    with pytest.raises(DuplicatePathError):
        io.add_files(iter([first, second]))
    assert not io.files


def test_core_file_rejects_duplicate_schema_leaves_before_index_overwrite(binding):
    root = ChoiceContainer(Name('Shared'), [Leaf(Name('Repeated')), Leaf(Name('Repeated'))])
    with pytest.raises(DuplicatePathError) as caught:
        ArxmlFile(binding=binding).parse_autosar(Path('duplicate.arxml'), root)
    assert caught.value.ref == ('Shared', 'Repeated')


def test_core_flush_rejects_cross_file_leaf_collision_before_writing(tmp_path, binding):
    io = IOArxml([], binding=binding)
    first = io.add_file(ArxmlFile(binding=binding).parse_autosar(tmp_path / 'first.arxml', Container(Name('Shared'), Wrapper(Leaf(Name('Unique'))))))
    second = io.add_file(ArxmlFile(binding=binding).parse_autosar(tmp_path / 'second.arxml', Container(Name('Shared'), Wrapper(Leaf(Name('Other'))))))
    second.root.wrapper.leaf.short_name.value = 'Unique'
    second.root.wrapper.leaf.edited()
    with pytest.raises(DuplicatePathError):
        io.flush_to_file()
    assert not first.filepath.exists() and not second.filepath.exists()


def test_core_file_permits_duplicate_empty_nonleaf_instances(binding):
    root = [Container(Name('Shared')), Container(Name('Shared'))]
    file = ArxmlFile(binding=binding).parse_autosar(Path('containers.arxml'), root)
    assert file.ref(('Shared',)).xml_obj is root[-1]
