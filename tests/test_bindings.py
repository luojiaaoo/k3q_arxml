"""独立绑定、脚本入口与版本隔离回归。"""

import os
import subprocess
import sys
import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest

from k3q_arxml import ArxmlFile, IOArxml
from k3q_arxml.cli import PACKAGE_ROOT, SCHEMAS, SCHEMA_ROOT


def test_bundled_modules_and_entrypoints_cover_all_schemas():
    expected = {f'autosar_{version.replace(".", "_")}.py' for version in SCHEMAS}
    assert {path.name for path in SCHEMA_ROOT.glob('autosar_*/autosar_*.py')} == expected
    assert not (PACKAGE_ROOT / 'autosar.py').exists()
    assert not (PACKAGE_ROOT / 'bindings').exists()
    config = tomllib.loads((PACKAGE_ROOT.parent / 'pyproject.toml').read_text(encoding='utf-8'))
    entries = config['project']['scripts']
    commands = {f'k3q-arxml-mcp-{version.replace(chr(46), chr(45))}' for version in SCHEMAS}
    assert entries == dict.fromkeys(commands, 'k3q_arxml.script.serve_mcp:main')
    assert not list(SCHEMA_ROOT.glob('autosar_*/__init__.py'))
    assert not (PACKAGE_ROOT / 'script/__init__.py').exists()
    for version in SCHEMAS:
        suffix = version.replace('.', '_')
        assert f'SCHEMA_VERSION = {version!r}' in (SCHEMAS[version].parent / f'autosar_{suffix}.py').read_text(encoding='utf-8')[-100:]


@pytest.mark.parametrize('version', SCHEMAS)
def test_entrypoint_imports_only_selected_binding_inside_main(version):
    suffix = version.replace('.', '_')
    code = f"""import sys
from dataclasses import is_dataclass
from types import ModuleType
from unittest.mock import MagicMock
from click.testing import CliRunner
from k3q_arxml import IOArxml
assert 'k3q_arxml.cli' not in sys.modules
from k3q_arxml.script.serve_mcp import main
assert not any(name.startswith('k3q_arxml.schemas.autosar_') for name in sys.modules)
server = ModuleType('k3q_arxml.mcp.server')
server.create_server = MagicMock()
sys.modules['k3q_arxml.mcp.server'] = server
result = CliRunner().invoke(main, [], prog_name='k3q-arxml-mcp-{version.replace(chr(46), chr(45))}')
assert result.exit_code == 0, result.output
assert server.create_server.call_count == 1
binding = server.create_server.call_args.kwargs['binding']
assert binding.SCHEMA_VERSION == {version!r}
assert is_dataclass(binding.Autosar)
from pathlib import Path
from tempfile import TemporaryDirectory
from k3q_arxml import IOArxml
with TemporaryDirectory() as directory:
    path = Path(directory) / 'minimal.arxml'
    path.write_text('<AUTOSAR xmlns="http://autosar.org/schema/r4.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://autosar.org/schema/r4.0 AUTOSAR_{version.replace(chr(46), chr(45))}.xsd"/>', encoding='utf-8')
    io = IOArxml([path], binding=binding)
    assert isinstance(io.files[path.resolve()].root, binding.Autosar)
assert binding.Autosar.__module__ == 'k3q_arxml.schemas.autosar_{suffix}.autosar_{suffix}'
assert [name for name in sys.modules if name.startswith('k3q_arxml.schemas.autosar_')] == ['k3q_arxml.schemas.autosar_{suffix}', 'k3q_arxml.schemas.autosar_{suffix}.autosar_{suffix}']
"""
    result = subprocess.run(
        [sys.executable, '-c', code], cwd=PACKAGE_ROOT.parent, env={**os.environ, 'PYTHONIOENCODING': 'utf-8'}, capture_output=True, text=True, encoding='utf-8'
    )
    assert result.returncode == 0, result.stderr


def test_io_append_uses_explicit_binding(tmp_path):
    from k3q_arxml.schemas.autosar_00044 import autosar_00044

    path = tmp_path / 'types.arxml'
    path.write_text(
        '<AUTOSAR xmlns="http://autosar.org/schema/r4.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xsi:schemaLocation="http://autosar.org/schema/r4.0 AUTOSAR_00044.xsd"/>',
        encoding='utf-8',
    )
    io = IOArxml([path], binding=autosar_00044)
    assert io.files[path.resolve()].binding is autosar_00044
    assert isinstance(io.files[path.resolve()].root, autosar_00044.Autosar)


def test_version_services_keep_bindings_during_edit_clone_and_root_patch(tmp_path):
    from k3q_arxml.schemas.autosar_00044 import autosar_00044
    from k3q_arxml.schemas.autosar_4_2_2 import autosar_4_2_2
    from k3q_arxml.mcp.schemas import McpPatchOperation
    from k3q_arxml.mcp.service import ArxmlMcpService

    for binding in (autosar_00044, autosar_4_2_2):
        path = tmp_path / f'{binding.SCHEMA_VERSION}.arxml'
        schema = binding.SCHEMA_VERSION.replace('.', '-')
        path.write_text(
            '<AUTOSAR xmlns="http://autosar.org/schema/r4.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            f'xsi:schemaLocation="http://autosar.org/schema/r4.0 AUTOSAR_{schema}.xsd">'
            '<AR-PACKAGES><AR-PACKAGE><SHORT-NAME>Types</SHORT-NAME></AR-PACKAGE></AR-PACKAGES></AUTOSAR>',
            encoding='utf-8',
        )
        service = ArxmlMcpService(tmp_path, binding=binding)
        info = service.open_project([path.name])
        renamed = service.rename_node(info.project_id, '/Types', 'Updated', info.revision)
        operation = McpPatchOperation(op='set_attribute', xpath='./ar:AR-PACKAGES/ar:AR-PACKAGE', attribute='UUID', value='version-test')
        service.patch_xml(info.project_id, '/', [operation], renamed.revision, file_id='f1')
        file = next(iter(service.projects[info.project_id].io.files.values()))
        assert file.binding is binding and file.parse_schema_version == binding.SCHEMA_VERSION
        assert isinstance(file.root, binding.Autosar)
        assert service.project_info(info.project_id).schema_version == binding.SCHEMA_VERSION
        assert service.describe_type('AUTOSAR').xml_tag == 'AUTOSAR'
        assert service.validate_project(info.project_id).valid
    with pytest.raises(TypeError, match='binding'):
        IOArxml([])
    with pytest.raises(TypeError, match='binding'):
        ArxmlFile()


def test_main_passes_selected_binding_and_cwd_without_subprocess(tmp_path, monkeypatch):
    from k3q_arxml.schemas.autosar_00044 import autosar_00044
    from click.testing import CliRunner
    from k3q_arxml.script.serve_mcp import main

    monkeypatch.chdir(tmp_path)
    with patch('k3q_arxml.mcp.server.create_server') as create:
        result = CliRunner().invoke(main, [], prog_name='k3q-arxml-mcp-00044')
    assert result.exit_code == 0, result.output
    create.assert_called_once_with(Path.cwd(), binding=autosar_00044)
    create.return_value.run.assert_called_once_with(transport='stdio')


@pytest.mark.parametrize('args', [[], ['--schema-version', 'unknown'], ['--help']])
def test_invalid_or_help_arguments_do_not_import_binding(args):
    from click.testing import CliRunner
    from k3q_arxml.script.serve_mcp import main

    with patch('k3q_arxml.script.serve_mcp.import_module') as load:
        result = CliRunner().invoke(main, args)
    assert result.exit_code == (0 if args == ['--help'] else 2)
    load.assert_not_called()


@pytest.mark.parametrize('command', ['k3q-arxml-mcp-00044', 'k3q-arxml-mcp-00044.exe'])
def test_version_command_needs_no_arguments(command, tmp_path, monkeypatch):
    from click.testing import CliRunner
    from k3q_arxml.schemas.autosar_00044 import autosar_00044
    from k3q_arxml.script.serve_mcp import main

    monkeypatch.chdir(tmp_path)
    with patch('k3q_arxml.mcp.server.create_server') as create:
        result = CliRunner().invoke(main, [], prog_name=command)
    assert result.exit_code == 0, result.output
    create.assert_called_once_with(Path.cwd(), binding=autosar_00044)


def test_version_command_rejects_removed_version_option_before_import():
    from click.testing import CliRunner
    from k3q_arxml.script.serve_mcp import main

    with patch('k3q_arxml.script.serve_mcp.import_module') as load:
        result = CliRunner().invoke(main, ['--schema-version', '4.2.2'], prog_name='k3q-arxml-mcp-00044')
    assert result.exit_code == 2 and '--schema-version' in result.output
    load.assert_not_called()
