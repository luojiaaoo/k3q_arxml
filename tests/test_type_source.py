"""源码查询的定位、分页、关联定义及只读边界。"""

from pathlib import Path
from types import ModuleType

import pytest
from lxml import etree

from k3q_arxml.mcp.service import ArxmlMcpService
from k3q_arxml.mcp.source import index_binding, index_xsd
from k3q_arxml.mcp.xml import McpServiceError
from k3q_arxml.schemas import autosar_4_2_2 as autosar


@pytest.fixture(scope='module')
def service(tmp_path_factory):
    return ArxmlMcpService(tmp_path_factory.mktemp('源码 查询'), binding=autosar)


def test_xsd_candidates_fragment_dependencies_and_character_pagination(service):
    choices = service.get_type_source('SW-BASE-TYPE')
    assert choices.definition is None and choices.content is None
    assert {item.kind for item in choices.candidates} == {'group', 'complexType'}
    selected = next(item for item in choices.candidates if item.kind == 'complexType')
    complete = service.get_type_source(selected.definition_id, limit=32_000)
    assert complete.definition == selected and complete.next_offset is None
    root = etree.fromstring(complete.content.encode())
    assert root.get('name') == 'SW-BASE-TYPE'
    lines = Path(selected.filepath).read_text(encoding='utf-8').splitlines()
    assert 'name="SW-BASE-TYPE"' in lines[selected.line - 1]
    content, offset = '', 0
    while True:
        page = service.get_type_source(selected.definition_id, offset=offset, limit=137)
        content += page.content
        if page.next_offset is None:
            break
        offset = page.next_offset
    assert content == complete.content
    assert service.get_type_source(selected.definition_id, offset=len(content)).content == ''
    assert 'AUTOSAR_4-2-2.xsd#group:SW-BASE-TYPE' in complete.related_definitions
    dependency = service.get_type_source('AUTOSAR_4-2-2.xsd#group:SW-BASE-TYPE')
    assert dependency.definition.kind == 'group'


def test_nested_xml_tags_return_containing_xsd_definition_and_imported_xml_types(service):
    tref = service.get_type_source('TYPE-TREF')
    assert tref.total_candidates > 1
    assert all(item.kind == 'group' for item in tref.candidates)
    short_name = service.get_type_source('SHORT-NAME')
    assert short_name.definition.name == 'REFERRABLE'
    assert 'name="SHORT-NAME"' in short_name.content
    lang = service.get_type_source('xml.xsd#attribute:lang')
    assert Path(lang.definition.filepath).name == 'xml.xsd'
    assert lang.definition.name == 'lang'


def test_large_candidate_sets_are_paged_without_returning_source(service):
    first = service.get_type_source('DEST')
    assert first.total_candidates > 50 and len(first.candidates) == 50
    assert first.content is None and first.next_candidate_offset == 50
    second = service.get_type_source('DEST', candidate_offset=first.next_candidate_offset)
    assert len(second.candidates) == 50
    assert not {item.definition_id for item in first.candidates} & {item.definition_id for item in second.candidates}
    assert service.get_type_source(second.candidates[0].definition_id).definition == second.candidates[0]


def test_binding_xml_tags_nested_types_enums_and_source_lines(service):
    result = service.get_type_source('SW-BASE-TYPE', source='binding', limit=32_000)
    assert result.definition.name == 'SwBaseType'
    assert result.content.startswith('@dataclass(kw_only=True)\nclass SwBaseType:')
    assert 'Identifier' in result.related_definitions
    nested = service.get_type_source('VariableDataPrototype.TypeTref', source='binding')
    assert 'class TypeTref(Ref):' in nested.content and '"DEST"' in nested.content
    assert 'class VariableDataPrototype:' not in nested.content
    lines = Path(nested.definition.filepath).read_text(encoding='utf-8').splitlines(keepends=True)
    assert ''.join(lines[nested.definition.line - 1 :]).startswith(nested.content)
    enum = service.get_type_source('AutosarDataTypeSubtypesEnum', source='binding')
    assert 'class AutosarDataTypeSubtypesEnum(Enum):' in enum.content
    candidates = service.get_type_source('TYPE-TREF', source='binding')
    assert nested.definition in candidates.candidates and candidates.definition is None
    first = service.get_type_source(nested.definition.definition_id, source='binding', limit=31)
    second = service.get_type_source(nested.definition.definition_id, source='binding', offset=first.next_offset)
    assert first.content + second.content == nested.content


@pytest.mark.parametrize(('name', 'source'), [('missing', 'xsd'), ('missing', 'binding'), ('../outside.xsd', 'xsd'), ('autosar_00044.py', 'binding')])
def test_missing_names_and_paths_do_not_read_arbitrary_files(service, name, source):
    with pytest.raises(McpServiceError) as error:
        service.get_type_source(name, source=source)
    assert error.value.error.code == 'SOURCE_NOT_FOUND'
    assert not service.projects


@pytest.mark.parametrize('kwargs', [{'limit': 0}, {'limit': 32_001}, {'offset': -1}, {'candidate_offset': -1}, {'source': 'python'}, {'name': ''}])
def test_invalid_pagination_and_source_are_rejected(service, kwargs):
    with pytest.raises(McpServiceError) as error:
        service.get_type_source(**{'name': 'SW-BASE-TYPE', **kwargs})
    assert error.value.error.code == 'INVALID_REQUEST'


def test_source_indexes_are_lazy_and_do_not_compile_validation_schema(tmp_path, monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError('源码查询不应编译 XSD')

    monkeypatch.setattr(etree, 'XMLSchema', unexpected)
    service = ArxmlMcpService(tmp_path, binding=autosar)
    assert '_xsd_sources' not in vars(service) and '_binding_sources' not in vars(service)
    first = service.get_type_source('group:SW-BASE-TYPE')
    assert '_binding_sources' not in vars(service) and 'schema' not in vars(service)
    cached = service._xsd_sources
    assert service.get_type_source(first.definition.definition_id).content == first.content
    assert service._xsd_sources is cached and not service.projects


def test_binding_index_preserves_decorators_nested_classes_and_ignores_class_text_in_strings(tmp_path):
    path = tmp_path / 'generated.py'
    source = '''from dataclasses import dataclass

@dataclass(
    kw_only=True,
)
class Outer:
    """中文说明中的 class Fake: 不是声明。"""
    class Inner:
        value: str

class Last:
    pass
'''
    path.write_text(source, encoding='utf-8')
    binding = ModuleType('generated')
    binding.__file__ = str(path)
    index = index_binding(binding)
    assert set(index.definitions) == {'Outer', 'Outer.Inner', 'Last'}
    assert index.definitions['Outer'].text.startswith('@dataclass(\n')
    assert 'class Inner:' in index.definitions['Outer'].text
    assert index.definitions['Outer.Inner'].text == '    class Inner:\n        value: str\n'
    assert index.definitions['Last'].text == 'class Last:\n    pass\n'


def test_xsd_query_does_not_follow_external_imports(tmp_path):
    path = tmp_path / 'tiny.xsd'
    path.write_text(
        '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
        '<xs:import schemaLocation="https://example.invalid/external.xsd"/>'
        '<xs:simpleType name="Local"><xs:restriction base="xs:string"/></xs:simpleType></xs:schema>',
        encoding='utf-8',
    )
    index = index_xsd(path)
    assert list(index.definitions) == ['tiny.xsd#simpleType:Local']
