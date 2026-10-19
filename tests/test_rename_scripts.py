import sys

import pytest

from demo import chg_adt_idt_name, chg_adt_name
from k3q_arxml import IOArxml


@pytest.fixture
def rename_files(tmp_path):
    from k3q_arxml.schemas import autosar_4_2_2 as autosar

    if autosar.SCHEMA_VERSION != '4.2.2':
        pytest.skip('重命名脚本测试需要生成 4.2.2 绑定')

    def create(types, interface_names=('Interface',)):
        def write(filename, package, elements):
            path = tmp_path / filename
            path.write_text(
                '<AUTOSAR xmlns="http://autosar.org/schema/r4.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
                'xsi:schemaLocation="http://autosar.org/schema/r4.0 AUTOSAR_4-2-2.xsd">'
                f'<AR-PACKAGES><AR-PACKAGE><SHORT-NAME>{package}</SHORT-NAME><ELEMENTS>{elements}</ELEMENTS>'
                '</AR-PACKAGE></AR-PACKAGES></AUTOSAR>',
                encoding='utf-8',
            )
            return path

        definitions = ''.join(f'<{tag}><SHORT-NAME>{name}</SHORT-NAME></{tag}>' for tag, name in types)
        # 每个接口对每个目标引用两次，引用文件与定义文件分开。
        variables = ''.join(
            f'<VARIABLE-DATA-PROTOTYPE><SHORT-NAME>Value{i}_{j}</SHORT-NAME><TYPE-TREF DEST="{tag}">/Types/{name}</TYPE-TREF></VARIABLE-DATA-PROTOTYPE>'
            for i, (tag, name) in enumerate(types)
            for j in range(2)
        )
        interface = ''.join(
            f'<SENDER-RECEIVER-INTERFACE><SHORT-NAME>{name}</SHORT-NAME><DATA-ELEMENTS>{variables}</DATA-ELEMENTS></SENDER-RECEIVER-INTERFACE>' for name in interface_names
        )
        return [write('types.arxml', 'Types', definitions), write('references.arxml', 'Interfaces', interface)]

    return create


def run_script(monkeypatch, module, paths, options, expected_names, reference_count=2):
    documents = []

    def load(filepaths, *, binding):
        document = IOArxml(filepaths, binding=binding)
        documents.append(document)
        return document

    with monkeypatch.context() as patch:
        patch.setattr('k3q_arxml.IOArxml', load)
        patch.setattr(sys, 'argv', [module.__file__, *map(str, paths), *options])
        module.main()

    # 同时检查运行时索引和实际落盘内容，避免只更新内存或只更新定义文件。
    for document in (documents[0], IOArxml(paths, binding=documents[0].binding)):
        assert {node.short_name for ref, node in document.files[paths[0]].index.objects.items() if len(ref) == 2} == set(expected_names)
        assert set(document.files[paths[1]].index.references) == {('Types', name) for name in expected_names}
        for name in expected_names:
            assert document.ref(('Types', name)) is not None
            references = document.ref_to_ref(('Types', name))
            assert len(references) == reference_count
            assert all(row.xml_obj.value == f'/Types/{name}' for row in references)


@pytest.mark.parametrize(('original', 'selected', 'expected'), [('Speed', 'Interface', 'Speed_Suffix'), ('Speed_Suffix', 'Other', 'Speed')])
@pytest.mark.parametrize('interface_names', [('Interface',), ('Interface', 'SharedInterface'), ('SharedInterface', 'Interface')])
def test_suffix_script_refreshes_indexes_and_saves_both_files(monkeypatch, rename_files, original, selected, expected, interface_names):
    paths = rename_files([('APPLICATION-PRIMITIVE-DATA-TYPE', original)], interface_names)
    run_script(monkeypatch, chg_adt_name, paths, ['-s', '_Suffix', '-a', selected], [expected], reference_count=2 * len(interface_names))


def test_prefix_script_refreshes_all_type_indexes_and_saves_both_files(monkeypatch, rename_files):
    paths = rename_files(
        [
            ('APPLICATION-PRIMITIVE-DATA-TYPE', 'Primitive'),
            ('APPLICATION-ARRAY-DATA-TYPE', 'Array'),
            ('APPLICATION-RECORD-DATA-TYPE', 'Record'),
            ('IMPLEMENTATION-DATA-TYPE', 'Implementation'),
        ]
    )
    expected = ['ADT_Primitive', 'ADT_Array', 'ADT_Record', 'IDT_Implementation']
    run_script(monkeypatch, chg_adt_idt_name, paths, [], expected)
    run_script(monkeypatch, chg_adt_idt_name, paths, [], expected)
