"""ARXML MCP 业务行为与真实 stdio 传输回归。"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from shutil import copy2, copytree, ignore_patterns

import pytest
from lxml import etree

from k3q_arxml import ArxmlFile
from k3q_arxml.schemas.schame import autosar_4_2_2 as autosar
from k3q_arxml.mcp import persistence
from k3q_arxml.mcp.schemas import McpPatchOperation
from k3q_arxml.mcp.service import ArxmlMcpService
from k3q_arxml.mcp.xml import NAMESPACE, McpServiceError, clone_file, read_xml


def document(package, elements):
    return (
        f'<AUTOSAR xmlns="{NAMESPACE}" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        f'xsi:schemaLocation="{NAMESPACE} AUTOSAR_4-2-2.xsd">'
        f'<AR-PACKAGES><AR-PACKAGE><SHORT-NAME>{package}</SHORT-NAME><ELEMENTS>{elements}</ELEMENTS></AR-PACKAGE></AR-PACKAGES></AUTOSAR>'
    )


def datatype(name, *, namespace=False):
    declaration = f' xmlns="{NAMESPACE}"' if namespace else ''
    return f'<APPLICATION-PRIMITIVE-DATA-TYPE{declaration}><SHORT-NAME>{name}</SHORT-NAME><CATEGORY>VALUE</CATEGORY></APPLICATION-PRIMITIVE-DATA-TYPE>'


def test_startup_defers_xsd_compilation_and_reuses_it_for_validation(tmp_path, monkeypatch):
    if autosar.SCHEMA_VERSION != '4.2.2':
        pytest.skip('MCP ARXML 回归需要 4.2.2 绑定')
    compile_schema = etree.XMLSchema
    compiled = []

    def compile_once(*args, **kwargs):
        schema = compile_schema(*args, **kwargs)
        compiled.append(schema)
        return schema

    monkeypatch.setattr(etree, 'XMLSchema', compile_once)
    service = ArxmlMcpService(tmp_path, binding=autosar)
    assert Path(service.get_skill_path()).is_dir()
    assert not compiled

    filepath = tmp_path / 'types.arxml'
    filepath.write_text(document('Types', datatype('Speed')), encoding='utf-8')
    info = service.open_project([filepath.name])
    assert len(compiled) == 1
    assert service.validate_project(info.project_id).valid
    assert len(compiled) == 1

    # 延后编译仍须报告真实的 XSD 错误，而非跳过加载和后续校验。
    filepath.write_text(document('Types', datatype('Invalid Name')), encoding='utf-8')
    invalid = service.open_project([filepath.name])
    assert any(item.code == 'XSD_ERROR' for item in invalid.diagnostics)
    assert len(compiled) == 1


@pytest.fixture
def project(tmp_path):
    if autosar.SCHEMA_VERSION != '4.2.2':
        pytest.skip('MCP ARXML 回归需要 4.2.2 绑定')
    workspace = tmp_path / '中文 工程'
    workspace.mkdir()
    types = workspace / '数据 类型.arxml'
    references = workspace / '引用.arxml'
    types.write_text(document('Types', datatype('Speed') + datatype('Other')), encoding='utf-8')
    variables = ''.join(
        f'<VARIABLE-DATA-PROTOTYPE><SHORT-NAME>Value{index}</SHORT-NAME><TYPE-TREF DEST="APPLICATION-PRIMITIVE-DATA-TYPE">/Types/Speed</TYPE-TREF></VARIABLE-DATA-PROTOTYPE>'
        for index in range(2)
    )
    references.write_text(
        document(
            'Interfaces',
            f'<SENDER-RECEIVER-INTERFACE><SHORT-NAME>Interface</SHORT-NAME><IS-SERVICE>false</IS-SERVICE><DATA-ELEMENTS>{variables}</DATA-ELEMENTS></SENDER-RECEIVER-INTERFACE>',
        ),
        encoding='utf-8',
    )
    service = ArxmlMcpService(workspace, binding=autosar)
    info = service.open_project([types.name, references.name])
    return service, info, [types, references]


def patch(service, info, ref, operations, **kwargs):
    revision = service.project_info(info.project_id).revision
    return service.patch_xml(info.project_id, ref, [McpPatchOperation(**operation) for operation in operations], revision, **kwargs)


def test_queries_pagination_xml_references_and_types(project):
    service, info, paths = project
    assert info.schema_version == '4.2.2'
    assert info.files[0].filepath == str(paths[0])
    page = service.find_nodes(info.project_id, xml_tag='APPLICATION-PRIMITIVE-DATA-TYPE', ref_prefix='/Types', limit=1)
    assert page.total == 2 and page.next_offset == 1
    assert page.items[0].file_id == 'f1' and page.items[0].ref == '/Types/Speed'
    detail = service.get_node(info.project_id, '/Types/Speed', include_xml=True, xml_limit=10)
    assert len(detail.xml) == 10 and detail.next_offset == 10
    assert service.get_node(info.project_id, '/Types/Speed').xml is None
    category = service.get_node(info.project_id, '/Types/Speed', xpath='./ar:CATEGORY')
    assert etree.fromstring(category.xml.encode()).text == 'VALUE'
    rows = service.find_references(info.project_id, '/Types/Speed', limit=1)
    assert rows.total == 2 and rows.next_offset == 1
    assert rows.items[0].owner_ref == '/Interfaces/Interface/Value0'
    assert rows.items[0].xpath == './ar:TYPE-TREF[1]'
    description = service.describe_type('SW-BASE-TYPE')
    assert any(field.xml_name == 'UUID' and field.kind == 'attribute' for field in description.fields)
    assert len([field for field in description.fields if field.python_field == 'choice']) > 1
    nested = service.describe_type('TYPE-TREF', python_type='VariableDataPrototype.TypeTref')
    assert any(field.xml_name == 'DEST' and field.enum_values for field in nested.fields)
    assert service.describe_type('SHORT-NAME').python_type == 'Identifier'
    assert service.validate_project(info.project_id).valid


@pytest.mark.parametrize(('ref', 'name', 'new_target'), [('/Types/Speed', 'Velocity', '/Types/Velocity'), ('/Types', 'NewTypes', '/NewTypes/Speed')])
def test_rename_updates_cross_file_references_and_saves_with_backup(project, ref, name, new_target):
    service, info, paths = project
    originals = [path.read_bytes() for path in paths]
    result = service.rename_node(info.project_id, ref, name, 0)
    assert result.revision == 1 and result.updated_references == 2
    assert result.affected_files == ['f1', 'f2']
    assert service.find_references(info.project_id, new_target).total == 2
    assert [path.read_bytes() for path in paths] == originals
    preview = service.preview_changes(info.project_id, limit=1)
    assert preview.total_lines > 1 and preview.next_offset == 1
    assert service.preview_changes(info.project_id, offset=1).preview_token == preview.preview_token
    saved = service.save_changes(info.project_id, preview.preview_token)
    assert saved.revision == 2 and len(saved.files) == 2
    assert [Path(item.backup_path).read_bytes() for item in saved.files] == originals
    assert json.loads(Path(saved.recovery_manifest).read_text(encoding='utf-8'))['status'] == 'complete'
    assert all(not file.dirty for file in service.project_info(info.project_id).files)
    reloaded = service.open_project([str(path) for path in paths])
    assert service.find_references(reloaded.project_id, new_target).total == 2


def test_failed_rename_does_not_publish_objects_or_indexes(project):
    service, info, paths = project
    state = service.projects[info.project_id]
    original = state.io.files[paths[0]]
    with pytest.raises(McpServiceError):
        service.rename_node(info.project_id, '/Types/Speed', 'Other', 0)
    assert state.io.files[paths[0]] is original
    assert original.ref(('Types', 'Speed')).short_name == 'Speed'
    assert service.find_references(info.project_id, '/Types/Speed').total == 2
    assert state.revision == 0 and not original._dirty


def test_declared_field_clone_does_not_bind_edits_to_old_file(project):
    service, info, paths = project
    original = service.projects[info.project_id].io.files[paths[0]]
    candidate = clone_file(original)
    node = candidate.ref(('Types', 'Speed'))
    node.xml_obj.uuid = 'candidate-only'
    node.xml_obj.edited()
    assert candidate._dirty and 'candidate-only' in candidate.index.uuids
    assert not original._dirty and not original.index.uuids
    assert node.xml_obj.arxml_parent is not original.ref(('Types', 'Speed')).xml_obj.arxml_parent


def test_patch_text_attributes_and_reference_target(project):
    service, info, _ = project
    patch(service, info, '/Types/Speed', [{'op': 'set_attribute', 'xpath': '.', 'attribute': 'UUID', 'value': 'uuid-one'}])
    patch(service, info, '/Types/Speed', [{'op': 'remove_attribute', 'xpath': '.', 'attribute': 'UUID'}, {'op': 'set_text', 'xpath': './ar:CATEGORY', 'value': 'VALUE'}])
    row = service.find_references(info.project_id, '/Types/Speed').items[0]
    patch(service, info, row.owner_ref, [{'op': 'set_text', 'xpath': row.xpath, 'value': '/Types/Other'}], file_id=row.file_id)
    assert service.find_references(info.project_id, '/Types/Other').total == 1
    assert service.find_references(info.project_id, '/Types/Speed').total == 1
    assert 'UUID=' not in service.get_node(info.project_id, '/Types/Speed', include_xml=True).xml


def test_patch_insert_replace_delete_and_order(project):
    service, info, _ = project
    patch(
        service,
        info,
        '/Types',
        [
            {'op': 'insert_before', 'xpath': './ar:ELEMENTS/ar:APPLICATION-PRIMITIVE-DATA-TYPE[2]', 'xml': datatype('Before', namespace=True)},
            {'op': 'insert_after', 'xpath': './ar:ELEMENTS/ar:APPLICATION-PRIMITIVE-DATA-TYPE[2]', 'xml': datatype('After', namespace=True)},
            {'op': 'append', 'xpath': './ar:ELEMENTS', 'xml': datatype('Last', namespace=True)},
        ],
    )
    names = [item.short_name for item in service.find_nodes(info.project_id, xml_tag='APPLICATION-PRIMITIVE-DATA-TYPE').items]
    assert names == ['Speed', 'Before', 'After', 'Other', 'Last']
    replacement = datatype('Before', namespace=True).replace('<CATEGORY>VALUE</CATEGORY>', '<CATEGORY>VALUE</CATEGORY><SW-DATA-DEF-PROPS/>')
    patch(service, info, '/Types', [{'op': 'replace', 'xpath': './ar:ELEMENTS/ar:APPLICATION-PRIMITIVE-DATA-TYPE[2]', 'xml': replacement}])
    patch(service, info, '/Types', [{'op': 'delete', 'xpath': './ar:ELEMENTS/ar:APPLICATION-PRIMITIVE-DATA-TYPE[2]'}])
    assert not service.find_nodes(info.project_id, name='Before').items


def test_document_root_supports_top_level_package_changes(project):
    service, info, _ = project
    fragment = f'<AR-PACKAGE xmlns="{NAMESPACE}"><SHORT-NAME>Added</SHORT-NAME></AR-PACKAGE>'
    patch(service, info, '/', [{'op': 'append', 'xpath': './ar:AR-PACKAGES', 'xml': fragment}], file_id='f1')
    assert service.get_node(info.project_id, '/Added').node.xml_tag == 'AR-PACKAGE'
    patch(service, info, '/', [{'op': 'delete', 'xpath': './ar:AR-PACKAGES/ar:AR-PACKAGE[2]'}], file_id='f1')
    assert not service.find_nodes(info.project_id, name='Added').items


@pytest.mark.parametrize(
    'operations',
    [
        [{'op': 'set_text', 'xpath': './ar:SHORT-NAME', 'value': 'HiddenRename'}],
        [{'op': 'replace', 'xpath': './ar:SHORT-NAME', 'xml': f'<SHORT-NAME xmlns="{NAMESPACE}">HiddenRename</SHORT-NAME>'}],
        [{'op': 'set_text', 'xpath': '../ar:SHORT-NAME', 'value': 'escape'}],
        [{'op': 'set_text', 'xpath': '/ar:AUTOSAR', 'value': 'escape'}],
        [{'op': 'set_attribute', 'xpath': './/ar:SHORT-NAME', 'attribute': 'S', 'value': 'ambiguous'}],
        [{'op': 'append', 'xpath': './ar:ELEMENTS', 'xml': '<INVALID/>'}],
        [{'op': 'append', 'xpath': './ar:ELEMENTS', 'xml': '<broken>'}],
        [{'op': 'append', 'xpath': './ar:ELEMENTS', 'xml': datatype('Speed', namespace=True)}],
        [{'op': 'delete', 'xpath': './ar:ELEMENTS/ar:APPLICATION-PRIMITIVE-DATA-TYPE[1]'}],
        [{'op': 'set_attribute', 'xpath': '.', 'attribute': 'UNKNOWN', 'value': 'lost'}],
        [{'op': 'set_attribute', 'xpath': '.', 'attribute': 'UUID', 'value': 'first'}, {'op': 'delete', 'xpath': './ar:MISSING'}],
    ],
)
def test_invalid_patch_is_atomic(project, operations):
    service, info, paths = project
    state = service.projects[info.project_id]
    old_file = state.io.files[paths[0]]
    original = old_file.render()
    with pytest.raises(McpServiceError):
        patch(service, info, '/Types', operations)
    assert state.io.files[paths[0]] is old_file
    assert old_file.render() == original and not old_file._dirty and state.revision == 0


@pytest.mark.parametrize(('value', 'attribute'), [('/Missing/Type', None), ('SW-BASE-TYPE', 'DEST')])
def test_new_unresolved_or_wrong_dest_reference_is_rejected(project, value, attribute):
    service, info, _ = project
    operation = (
        {'op': 'set_attribute', 'xpath': './ar:TYPE-TREF', 'attribute': attribute, 'value': value} if attribute else {'op': 'set_text', 'xpath': './ar:TYPE-TREF', 'value': value}
    )
    with pytest.raises(McpServiceError):
        patch(service, info, '/Interfaces/Interface/Value0', [operation])
    assert service.project_info(info.project_id).revision == 0


def test_existing_unloaded_references_are_warnings(project):
    service, _, paths = project
    info = service.open_project([str(paths[1])])
    assert any(item.code == 'UNRESOLVED_REFERENCE' for item in info.diagnostics)
    validation = service.validate_project(info.project_id)
    assert validation.valid and len(validation.diagnostics) == 2
    result = patch(service, info, '/Interfaces/Interface', [{'op': 'set_attribute', 'xpath': '.', 'attribute': 'UUID', 'value': 'updated'}])
    assert result.revision == 1


def test_revision_preview_and_unsaved_close_guards(project):
    service, info, _ = project
    preview = service.preview_changes(info.project_id)
    service.rename_node(info.project_id, '/Types/Speed', 'Velocity', 0)
    with pytest.raises(McpServiceError, match='revision'):
        service.rename_node(info.project_id, '/Types/Other', 'OtherName', 0)
    with pytest.raises(McpServiceError) as error:
        service.save_changes(info.project_id, preview.preview_token)
    assert error.value.error.code == 'STALE_PREVIEW'
    with pytest.raises(McpServiceError):
        service.close_project(info.project_id)
    assert service.close_project(info.project_id, discard_changes=True).closed


@pytest.mark.parametrize('edit', ['attribute', 'rename', 'structure'])
def test_reverted_edits_clear_dirty_without_writing(project, edit):
    service, info, paths = project
    originals = [path.read_bytes() for path in paths]
    if edit == 'attribute':
        patch(service, info, '/Types/Speed', [{'op': 'set_attribute', 'xpath': '.', 'attribute': 'UUID', 'value': 'temporary'}])
    elif edit == 'rename':
        service.rename_node(info.project_id, '/Types/Speed', 'Velocity', info.revision)
    else:
        patch(service, info, '/Types', [{'op': 'append', 'xpath': './ar:ELEMENTS', 'xml': datatype('Added', namespace=True)}])
    dirty_preview = service.preview_changes(info.project_id)
    if edit == 'attribute':
        patch(service, info, '/Types/Speed', [{'op': 'remove_attribute', 'xpath': '.', 'attribute': 'UUID'}])
    elif edit == 'rename':
        service.rename_node(info.project_id, '/Types/Velocity', 'Speed', dirty_preview.revision)
        assert service.find_references(info.project_id, '/Types/Speed').total == 2
    else:
        patch(service, info, '/Types', [{'op': 'delete', 'xpath': "./ar:ELEMENTS/ar:APPLICATION-PRIMITIVE-DATA-TYPE[ar:SHORT-NAME='Added']"}])
    assert all(not file.dirty for file in service.project_info(info.project_id).files)
    with pytest.raises(McpServiceError) as error:
        service.save_changes(info.project_id, dirty_preview.preview_token)
    assert error.value.error.code == 'STALE_PREVIEW'
    preview = service.preview_changes(info.project_id)
    assert not preview.lines and not preview.affected_files and preview.total_lines == 0
    saved = service.save_changes(info.project_id, preview.preview_token)
    assert not saved.files and saved.recovery_manifest is None
    assert [path.read_bytes() for path in paths] == originals
    assert not list(service.workspace.glob('.*.bak'))
    assert service.close_project(info.project_id).closed


def test_successful_save_refreshes_revert_baseline(project):
    service, info, paths = project
    renamed = service.rename_node(info.project_id, '/Types/Speed', 'Velocity', info.revision)
    saved = service.save_changes(info.project_id, service.preview_changes(info.project_id).preview_token)
    assert saved.revision > renamed.revision
    originals = [path.read_bytes() for path in paths]
    changed = service.rename_node(info.project_id, '/Types/Velocity', 'Speed', saved.revision)
    assert all(file.dirty for file in service.project_info(info.project_id).files)
    service.rename_node(info.project_id, '/Types/Speed', 'Velocity', changed.revision)
    assert all(not file.dirty for file in service.project_info(info.project_id).files)
    assert service.find_references(info.project_id, '/Types/Velocity').total == 2
    assert not service.preview_changes(info.project_id).lines
    assert [path.read_bytes() for path in paths] == originals
    assert service.close_project(info.project_id).closed


def test_model_preview_omits_existing_normalization_but_file_preview_preserves_it(project):
    service, _, _ = project
    path = service.workspace / 'normalization.arxml'
    copy2(Path(__file__).resolve().parents[1] / 'test/ThrottlePositionControlComposition.arxml', path)
    original = path.read_bytes()
    info = service.open_project([str(path)])
    node = service.find_nodes(info.project_id, xml_tag='SW-BASE-TYPE', limit=1).items[0]
    patch(service, info, node.ref, [{'op': 'set_attribute', 'xpath': '.', 'attribute': 'UUID', 'value': 'new-uuid'}])
    port = service.find_nodes(info.project_id, xml_tag='R-PORT-PROTOTYPE', limit=1).items[0]
    patch(service, info, port.ref, [{'op': 'set_text', 'xpath': './/ar:ALIVE-TIMEOUT', 'value': '1.0'}])
    full = service.preview_changes(info.project_id, limit=200)
    focused = service.preview_changes(info.project_id, diff_mode='model', limit=200)
    assert full.diff_mode == 'file' and focused.diff_mode == 'model'
    assert full.serialization_changed_files == focused.serialization_changed_files == ['f1']
    assert full.preview_token == focused.preview_token
    assert any('<ALIVE-TIMEOUT>0</ALIVE-TIMEOUT>' in line.text for line in full.lines)
    assert not any('<ALIVE-TIMEOUT>0</ALIVE-TIMEOUT>' in line.text for line in focused.lines)
    assert any('<ALIVE-TIMEOUT>1.0</ALIVE-TIMEOUT>' in line.text and line.text.startswith('+') for line in focused.lines)
    assert any('new-uuid' in line.text and line.text.startswith('+') for line in focused.lines)
    assert any('new-uuid' in line.text and line.text.startswith('+') for line in full.lines)
    page = service.preview_changes(info.project_id, diff_mode='model', limit=1)
    assert page.next_offset == 1 and page.total_lines == focused.total_lines
    assert service.preview_changes(info.project_id, offset=1, diff_mode='model').lines == focused.lines[1:]
    assert path.read_bytes() == original
    service.save_changes(info.project_id, full.preview_token)
    patch(service, info, node.ref, [{'op': 'set_attribute', 'xpath': '.', 'attribute': 'UUID', 'value': 'second-uuid'}])
    assert not service.preview_changes(info.project_id).serialization_changed_files


def test_attribute_predicate_targets_new_node_and_explains_missing_elements_layer(project):
    service, info, _ = project
    fragment = datatype('Added', namespace=True).replace('><SHORT-NAME>', ' UUID="created"><SHORT-NAME>', 1)
    patch(service, info, '/Types', [{'op': 'append', 'xpath': './ar:ELEMENTS', 'xml': fragment}])
    current = service.project_info(info.project_id)
    renamed = service.rename_node(info.project_id, '/Types/Added', 'Updated', current.revision)
    assert renamed.new_ref == '/Types/Updated'
    selector = "./ar:ELEMENTS/ar:APPLICATION-PRIMITIVE-DATA-TYPE[@UUID='created']"
    assert service.get_node(info.project_id, '/Types', xpath=selector).xml
    with pytest.raises(McpServiceError) as error:
        service.get_node(info.project_id, '/Types', xpath=selector.replace('ar:ELEMENTS/', ''))
    assert error.value.error.code == 'XPATH_MATCH_COUNT'
    assert '0' in error.value.error.message and 'ELEMENTS' in error.value.error.suggestion
    patch(service, info, '/Types', [{'op': 'delete', 'xpath': selector}])
    assert not service.find_nodes(info.project_id, name='Updated').items
    assert not service.project_info(info.project_id).files[0].dirty


def test_external_file_change_blocks_all_writes(project):
    service, info, paths = project
    original = paths[0].read_bytes()
    service.rename_node(info.project_id, '/Types/Speed', 'Velocity', 0)
    paths[1].write_bytes(paths[1].read_bytes() + b'\n<!-- external change -->')
    external = paths[1].read_bytes()
    with pytest.raises(McpServiceError) as error:
        service.save_changes(info.project_id, service.preview_changes(info.project_id).preview_token)
    assert error.value.error.code == 'FILE_CONFLICT'
    assert paths[0].read_bytes() == original and paths[1].read_bytes() == external


def test_save_failure_restores_already_replaced_file(project, monkeypatch):
    service, info, paths = project
    originals = [path.read_bytes() for path in paths]
    service.rename_node(info.project_id, '/Types/Speed', 'Velocity', 0)
    replace = os.replace

    def fail_second(source, destination):
        if Path(destination) == paths[1] and str(source).endswith('.tmp'):
            raise OSError('simulated second-file failure')
        return replace(source, destination)

    with monkeypatch.context() as context:
        context.setattr(persistence.os, 'replace', fail_second)
        with pytest.raises(McpServiceError) as error:
            service.save_changes(info.project_id, service.preview_changes(info.project_id).preview_token)
    assert error.value.error.code == 'SAVE_FAILED'
    assert [path.read_bytes() for path in paths] == originals
    manifests = list(service.workspace.glob('.k3q-mcp-recovery-*.json'))
    assert json.loads(manifests[0].read_text(encoding='utf-8'))['status'] == 'rolled_back'
    assert all(file.dirty for file in service.project_info(info.project_id).files)
    service.save_changes(info.project_id, service.preview_changes(info.project_id).preview_token)


def test_pending_recovery_blocks_open_and_edit(project):
    service, info, paths = project
    (service.workspace / '.k3q-mcp-recovery-interrupted.json').write_text('{"status":"pending","files":[]}', encoding='utf-8')
    with pytest.raises(McpServiceError) as error:
        service.open_project([str(paths[0])])
    assert error.value.error.code == 'RECOVERY_REQUIRED'
    with pytest.raises(McpServiceError):
        service.rename_node(info.project_id, '/Types/Speed', 'Velocity', 0)


def test_rollback_failure_preserves_manifest_and_backups(project, monkeypatch):
    service, info, paths = project
    originals = [path.read_bytes() for path in paths]
    service.rename_node(info.project_id, '/Types/Speed', 'Velocity', 0)
    replace = os.replace

    def fail_save_and_restore(source, destination):
        if Path(destination) == paths[1] or str(source).endswith('.restore.tmp'):
            raise OSError('simulated restore failure')
        return replace(source, destination)

    with monkeypatch.context() as context:
        context.setattr(persistence.os, 'replace', fail_save_and_restore)
        with pytest.raises(McpServiceError) as error:
            service.save_changes(info.project_id, service.preview_changes(info.project_id).preview_token)
    assert error.value.error.code == 'RECOVERY_REQUIRED'
    manifest = json.loads(next(service.workspace.glob('.k3q-mcp-recovery-*.json')).read_text(encoding='utf-8'))
    assert manifest['status'] == 'rollback_failed' and manifest['rollback_errors']
    assert [Path(item['backup_path']).read_bytes() for item in manifest['files']] == originals
    assert paths[0].read_bytes() != originals[0] and paths[1].read_bytes() == originals[1]


def test_external_change_in_untouched_file_also_blocks_save(project):
    service, info, paths = project
    patch(service, info, '/Types/Other', [{'op': 'set_attribute', 'xpath': '.', 'attribute': 'UUID', 'value': 'change'}])
    assert not service.project_info(info.project_id).files[1].dirty
    paths[1].write_bytes(paths[1].read_bytes() + b'\n')
    with pytest.raises(McpServiceError) as error:
        service.save_changes(info.project_id, service.preview_changes(info.project_id).preview_token)
    assert error.value.error.code == 'FILE_CONFLICT'


def test_preview_bounds_minified_xml_lines(project):
    service, info, _ = project
    patch(service, info, '/Types/Other', [{'op': 'set_attribute', 'xpath': '.', 'attribute': 'UUID', 'value': 'x' * 6000}])
    preview = service.preview_changes(info.project_id, limit=200)
    assert any(item.continuation for item in preview.lines)
    assert all(len(item.text) <= 2000 for item in preview.lines)


def test_parseable_invalid_xsd_can_be_loaded_and_repaired(project):
    service, _, paths = project
    paths[0].write_text(document('Types', datatype('9Speed')), encoding='utf-8')
    info = service.open_project([str(paths[0])])
    assert any(item.code == 'XSD_ERROR' for item in info.diagnostics)
    with pytest.raises(McpServiceError):
        patch(service, info, '/Types/9Speed', [{'op': 'set_attribute', 'xpath': '.', 'attribute': 'UUID', 'value': 'still-invalid'}])
    service.rename_node(info.project_id, '/Types/9Speed', 'Speed', 0)
    assert service.validate_project(info.project_id).valid


def test_batch_can_retarget_references_and_delete_definition_in_same_file(project):
    service, _, paths = project
    root = read_xml(paths[0].read_bytes())
    root.find(f'{{{NAMESPACE}}}AR-PACKAGES').append(read_xml(paths[1].read_bytes()).find(f'{{{NAMESPACE}}}AR-PACKAGES')[0])
    merged = service.workspace / 'merged.arxml'
    merged.write_bytes(etree.tostring(root, encoding='utf-8', xml_declaration=True))
    info = service.open_project([str(merged)])
    prefix = './ar:AR-PACKAGES/ar:AR-PACKAGE[2]/ar:ELEMENTS/ar:SENDER-RECEIVER-INTERFACE/ar:DATA-ELEMENTS'
    patch(
        service,
        info,
        '/',
        [
            {'op': 'set_text', 'xpath': prefix + '/ar:VARIABLE-DATA-PROTOTYPE[1]/ar:TYPE-TREF', 'value': '/Types/Other'},
            {'op': 'set_text', 'xpath': prefix + '/ar:VARIABLE-DATA-PROTOTYPE[2]/ar:TYPE-TREF', 'value': '/Types/Other'},
            {'op': 'delete', 'xpath': './ar:AR-PACKAGES/ar:AR-PACKAGE[1]/ar:ELEMENTS/ar:APPLICATION-PRIMITIVE-DATA-TYPE[1]'},
        ],
        file_id='f1',
    )
    assert service.find_references(info.project_id, '/Types/Other').total == 2
    assert not service.find_nodes(info.project_id, name='Speed').items


def test_rename_subtree_with_internal_references(project):
    service, _, paths = project
    elements = ''.join(
        f'<APPLICATION-RECORD-ELEMENT><SHORT-NAME>Self{index}</SHORT-NAME><TYPE-TREF DEST="APPLICATION-RECORD-DATA-TYPE">/Types/Record</TYPE-TREF></APPLICATION-RECORD-ELEMENT>'
        for index in range(2)
    )
    paths[0].write_text(
        document(
            'Types', f'<APPLICATION-RECORD-DATA-TYPE><SHORT-NAME>Record</SHORT-NAME><CATEGORY>STRUCTURE</CATEGORY><ELEMENTS>{elements}</ELEMENTS></APPLICATION-RECORD-DATA-TYPE>'
        ),
        encoding='utf-8',
    )
    info = service.open_project([str(paths[0])])
    result = service.rename_node(info.project_id, '/Types', 'NewTypes', 0)
    assert result.updated_references == 2
    assert service.find_references(info.project_id, '/NewTypes/Record').total == 2
    assert service.get_node(info.project_id, '/NewTypes/Record/Self0').node.short_name == 'Self0'


def test_schema_header_cannot_be_changed_by_patch(project):
    service, info, _ = project
    with pytest.raises(McpServiceError):
        patch(
            service,
            info,
            '/',
            [{'op': 'set_attribute', 'xpath': '.', 'attribute': '{http://www.w3.org/2001/XMLSchema-instance}schemaLocation', 'value': f'{NAMESPACE} AUTOSAR_00048.xsd'}],
            file_id='f1',
        )


def test_lossy_compound_element_order_is_rejected(project):
    service, info, _ = project
    with pytest.raises(McpServiceError) as error:
        patch(service, info, '/Types/Speed', [{'op': 'insert_before', 'xpath': './ar:SHORT-NAME', 'xml': f'<CATEGORY xmlns="{NAMESPACE}">VALUE</CATEGORY>'}])
    assert error.value.error.code in {'BINDING_ERROR', 'LOSSY_ROUND_TRIP', 'VALIDATION_FAILED'}


@pytest.mark.parametrize('version', ['00044', '00048'])
def test_version_mismatch_warns_and_allows_query_edit_and_save(project, version):
    service, _, paths = project
    mismatched = service.workspace / 'wrong.arxml'
    mismatched.write_text(paths[0].read_text(encoding='utf-8').replace('AUTOSAR_4-2-2.xsd', f'AUTOSAR_{version}.xsd'), encoding='utf-8')
    original = mismatched.read_bytes()
    info = service.open_project([str(mismatched)])
    warnings = [item for item in info.diagnostics if item.code == 'SCHEMA_MISMATCH']
    assert len(warnings) == 1 and warnings[0].severity == 'warning'
    assert warnings[0].file_id == 'f1' and warnings[0].ref == '/'
    assert version in warnings[0].message and info.schema_version in warnings[0].message
    assert service.get_node(info.project_id, '/Types/Speed').node.short_name == 'Speed'
    assert mismatched.read_bytes() == original
    validation = service.validate_project(info.project_id)
    assert validation.valid and warnings[0] in validation.diagnostics
    renamed = service.rename_node(info.project_id, '/Types/Speed', 'Velocity', info.revision)
    assert renamed.revision == 1
    preview = service.preview_changes(info.project_id)
    assert warnings[0] in preview.diagnostics
    saved = service.save_changes(info.project_id, preview.preview_token)
    assert Path(saved.files[0].backup_path).read_bytes() == original
    reloaded = service.open_project([str(mismatched)])
    assert service.get_node(reloaded.project_id, '/Types/Velocity').node.short_name == 'Velocity'
    assert warnings[0] in reloaded.diagnostics
    schema_location = read_xml(mismatched.read_bytes()).get('{http://www.w3.org/2001/XMLSchema-instance}schemaLocation')
    assert schema_location == f'{NAMESPACE} AUTOSAR_{version}.xsd'


def test_version_mismatch_does_not_ignore_unknown_xml(project):
    service, _, paths = project
    mismatched = service.workspace / 'unknown-version-element.arxml'
    content = paths[0].read_text(encoding='utf-8').replace('AUTOSAR_4-2-2.xsd', 'AUTOSAR_00044.xsd')
    mismatched.write_text(content.replace('</ELEMENTS>', '<UNKNOWN-VERSION-ELEMENT/></ELEMENTS>'), encoding='utf-8')
    original = mismatched.read_bytes()
    projects = set(service.projects)
    with pytest.raises(McpServiceError) as error:
        service.open_project([str(mismatched)])
    assert error.value.error.code == 'BINDING_ERROR'
    assert set(service.projects) == projects and mismatched.read_bytes() == original


def test_loading_rejects_missing_schema_duplicate_paths_and_workspace_escape(project, tmp_path):
    service, _, paths = project
    missing_schema = service.workspace / 'missing-schema.arxml'
    missing_schema.write_text(paths[0].read_text(encoding='utf-8').replace(f'xsi:schemaLocation="{NAMESPACE} AUTOSAR_4-2-2.xsd"', ''), encoding='utf-8')
    with pytest.raises(McpServiceError) as error:
        service.open_project([str(missing_schema)])
    assert error.value.error.code == 'SCHEMA_MISMATCH'
    with pytest.raises(McpServiceError):
        service.open_project([str(paths[0]), str(paths[0])])
    duplicate = service.workspace / 'duplicate.arxml'
    copy2(paths[0], duplicate)
    with pytest.raises(McpServiceError) as error:
        service.open_project([str(paths[0]), str(duplicate)])
    assert error.value.error.code == 'DUPLICATE_PATH'
    outside = tmp_path / 'outside.arxml'
    copy2(paths[0], outside)
    with pytest.raises(McpServiceError) as error:
        service.open_project([str(outside)])
    assert error.value.error.code == 'OUTSIDE_WORKSPACE'


@pytest.mark.parametrize('content', [b'<!DOCTYPE x [<!ENTITY e "secret">]><x>&e;</x>', b'<!DOCTYPE x SYSTEM "https://example.invalid/external"><x/>', b'<x>'])
def test_unsafe_and_malformed_xml_is_rejected(content):
    with pytest.raises(McpServiceError):
        read_xml(content)


def test_sample_round_trip_and_compound_order(tmp_path):
    if autosar.SCHEMA_VERSION != '4.2.2':
        pytest.skip('样例需要 4.2.2 绑定')
    path = tmp_path / 'sample.arxml'
    copy2(Path(__file__).resolve().parents[1] / 'test/ThrottlePositionControlComposition.arxml', path)
    service = ArxmlMcpService(tmp_path, binding=autosar)
    info = service.open_project([str(path)])
    node = service.find_nodes(info.project_id, xml_tag='SW-BASE-TYPE').items[0]
    before = read_xml(service.get_node(info.project_id, node.ref, include_xml=True).xml)
    patch(service, info, node.ref, [{'op': 'set_attribute', 'xpath': '.', 'attribute': 'UUID', 'value': 'sample-edit'}])
    service.save_changes(info.project_id, service.preview_changes(info.project_id).preview_token)
    after = read_xml(service.get_node(info.project_id, node.ref, include_xml=True).xml)
    assert [child.tag for child in before] == [child.tag for child in after]
    assert ArxmlFile(binding=autosar).parse_file(path).ref(tuple(node.ref.split('/')[1:])).xml_obj.uuid == 'sample-edit'


def test_only_mcp_entrypoint_is_exposed_and_requires_binding(tmp_path):
    root = Path(__file__).resolve().parents[1]
    isolated = tmp_path / '命令行 环境'
    copytree(root / 'k3q_arxml', isolated / 'k3q_arxml', ignore=ignore_patterns('__pycache__'))
    env = {**os.environ, 'PYTHONPATH': str(isolated), 'PYTHONIOENCODING': 'utf-8'}
    result = subprocess.run([sys.executable, '-m', 'k3q_arxml', '--help'], cwd=isolated, env=env, capture_output=True, text=True, encoding='utf-8')
    assert result.returncode != 0 and '__main__' in result.stderr and not result.stdout
    script = isolated / 'k3q-arxml-mcp-4-2-2.py'
    script.write_text('from k3q_arxml.script.serve_mcp import main\nmain()\n', encoding='utf-8')
    result = subprocess.run([sys.executable, str(script), '--help'], cwd=isolated, env=env, capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0 and '--schema-version' not in result.stdout
    (isolated / 'k3q_arxml/schemas/schame/autosar_4_2_2.py').unlink()
    result = subprocess.run([sys.executable, str(script)], cwd=isolated, env=env, capture_output=True, text=True, encoding='utf-8')
    assert result.returncode != 0 and 'autosar_4_2_2' in result.stderr and not result.stdout


@pytest.mark.parametrize('schema_version', ['4.2.2', '00044'])
def test_real_stdio_tools_errors_edit_preview_and_save(project, schema_version):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    service, _, paths = project
    paths[0].write_text(paths[0].read_text(encoding='utf-8').replace('AUTOSAR_4-2-2.xsd', 'AUTOSAR_00044.xsd'), encoding='utf-8')
    root = Path(__file__).resolve().parents[1]
    original_binding = (root / 'k3q_arxml/schemas/schame/autosar_4_2_2.py').read_bytes()
    # 从独立脚本启动，检查各版本服务的真实 stdio 行为及绑定文件保持不变。
    runtime = service.workspace / '服务 环境'
    copytree(root / 'k3q_arxml', runtime / 'k3q_arxml', ignore=ignore_patterns('__pycache__'))
    copytree(root / 'skills', runtime / 'skills')
    script = runtime / f'k3q-arxml-mcp-{schema_version.replace(chr(46), chr(45))}.py'
    script.write_text('from k3q_arxml.script.serve_mcp import main\nmain()\n', encoding='utf-8')
    arguments = [str(script)]
    parameters = StdioServerParameters(
        command=sys.executable,
        args=arguments,
        cwd=service.workspace,
        env={'PYTHONPATH': str(runtime), 'PYTHONIOENCODING': 'utf-8'},
    )

    async def run():
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                listed = await client.list_tools()
                assert len(listed.tools) == 14
                assert all(tool.input_schema and tool.output_schema for tool in listed.tools)
                source_tool = next(tool for tool in listed.tools if tool.name == 'get_type_source')
                assert source_tool.annotations.read_only_hint
                assert source_tool.input_schema['properties']['limit']['maximum'] == 32_000
                source = await client.call_tool('get_type_source', {'name': 'complexType:SW-BASE-TYPE', 'limit': 100})
                assert not source.is_error and source.structured_content['schema_version'] == schema_version
                assert len(source.structured_content['content']) == 100 and source.structured_content['next_offset'] == 100
                source = await client.call_tool('get_type_source', {'name': 'VariableDataPrototype.TypeTref', 'source': 'binding'})
                assert not source.is_error and 'class TypeTref(Ref):' in source.structured_content['content']
                missing = await client.call_tool('get_type_source', {'name': '../missing.xsd'})
                assert missing.is_error and json.loads(missing.content[0].text)['code'] == 'SOURCE_NOT_FOUND'
                skill = await client.call_tool('get_skill_path', {})
                assert not skill.is_error, skill.content
                skill_path = Path(skill.structured_content['result'])
                assert (skill_path / 'SKILL.md').is_file()
                assert skill_path == runtime / 'skills/arxml-mcp'
                outside = await client.call_tool('open_project', {'filepaths': [str(root / 'test/ThrottlePositionControlComposition.arxml')]})
                assert outside.is_error and json.loads(outside.content[0].text)['code'] == 'OUTSIDE_WORKSPACE'
                opened = await client.call_tool('open_project', {'filepaths': [path.name for path in paths]})
                assert not opened.is_error, opened.content
                assert opened.structured_content['schema_version'] == schema_version
                mismatch = [item for item in opened.structured_content['diagnostics'] if item['code'] == 'SCHEMA_MISMATCH']
                assert len(mismatch) == 1 and mismatch[0]['severity'] == 'warning'
                project_id = opened.structured_content['project_id']
                found = await client.call_tool('find_nodes', {'project_id': project_id, 'name': 'Speed'})
                assert found.structured_content['total'] == 1
                error = await client.call_tool('get_node', {'project_id': project_id, 'ref': '/Missing'})
                assert error.is_error and json.loads(error.content[0].text)['code'] == 'NODE_NOT_FOUND'
                changed = await client.call_tool('rename_node', {'project_id': project_id, 'ref': '/Types', 'new_name': 'Updated', 'revision': 0})
                assert not changed.is_error and changed.structured_content['updated_references'] == 2
                patched = await client.call_tool(
                    'patch_xml',
                    {
                        'project_id': project_id,
                        'ref': '/Updated/Speed',
                        'revision': 1,
                        'operations': [{'op': 'set_attribute', 'xpath': '.', 'attribute': 'UUID', 'value': 'stdio-edit'}],
                    },
                )
                assert not patched.is_error, patched.content
                preview = await client.call_tool('preview_changes', {'project_id': project_id})
                focused = await client.call_tool('preview_changes', {'project_id': project_id, 'diff_mode': 'model'})
                assert not focused.is_error and focused.structured_content['diff_mode'] == 'model'
                assert focused.structured_content['serialization_changed_files'] == ['f1', 'f2']
                assert focused.structured_content['preview_token'] == preview.structured_content['preview_token']
                invalid_mode = await client.call_tool('preview_changes', {'project_id': project_id, 'diff_mode': 'unknown'})
                assert invalid_mode.is_error
                saved = await client.call_tool('save_changes', {'project_id': project_id, 'preview_token': preview.structured_content['preview_token']})
                assert not saved.is_error and len(saved.structured_content['files']) == 2
                closed = await client.call_tool('close_project', {'project_id': project_id})
                assert not closed.is_error

    asyncio.run(asyncio.wait_for(run(), timeout=180))
    assert (runtime / 'k3q_arxml/schemas/schame/autosar_4_2_2.py').read_bytes() == original_binding
    assert (root / 'k3q_arxml/schemas/schame/autosar_4_2_2.py').read_bytes() == original_binding
