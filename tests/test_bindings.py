import ast
import hashlib
import json
from zipfile import ZipFile

import click
import pytest

from k3q_arxml.cli import _unpack_binding
from k3q_arxml.schemas import PACKAGE_ROOT, SCHEMAS


def test_bundled_bindings_cover_all_schemas_and_match_sources():
    archives = list((PACKAGE_ROOT / 'bindings').glob('*.zip'))
    assert {path.name for path in archives} == {f'autosar_{version.replace(".", "_")}.zip' for version in SCHEMAS}
    for version in SCHEMAS:
        with ZipFile(PACKAGE_ROOT / 'bindings' / f'autosar_{version.replace(".", "_")}.zip') as archive:
            assert set(archive.namelist()) == {'autosar.py', 'metadata.json'}
            metadata = json.loads(archive.read('metadata.json'))
            content = archive.read('autosar.py')
        assert metadata['schema_version'] == version
        assert metadata['xsd_sha256'] == hashlib.sha256(SCHEMAS[version].read_bytes()).hexdigest()
        assert metadata['python_sha256'] == hashlib.sha256(content).hexdigest()
        module = ast.parse(content)
        declared = next(
            ast.literal_eval(node.value)
            for node in module.body
            if isinstance(node, ast.Assign) and any(isinstance(item, ast.Name) and item.id == 'SCHEMA_VERSION' for item in node.targets)
        )
        assert declared == version


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    root = tmp_path / '中文 包目录'
    (root / 'bindings').mkdir(parents=True)
    schema = root / 'tiny.xsd'
    schema.write_bytes(b'<schema/>')
    content = b"SCHEMA_VERSION = '00044'\n"
    metadata = {
        'schema_version': '00044',
        'xsd_sha256': hashlib.sha256(schema.read_bytes()).hexdigest(),
        'python_sha256': hashlib.sha256(content).hexdigest(),
    }
    monkeypatch.setattr('k3q_arxml.cli.PACKAGE_ROOT', root)
    monkeypatch.setitem(SCHEMAS, '00044', schema)
    return root / 'bindings/autosar_00044.zip', metadata, content


def test_unpack_writes_selected_module_without_extracting_other_paths(bundle, tmp_path):
    path, metadata, content = bundle
    with ZipFile(path, 'w') as archive:
        archive.writestr('metadata.json', json.dumps(metadata))
        archive.writestr('autosar.py', content)
        archive.writestr('../unexpected.py', 'raise RuntimeError()')
    target = tmp_path / 'autosar.py'
    _unpack_binding('00044', target)
    assert target.read_bytes() == content
    assert not (path.parent.parent / 'unexpected.py').exists()
    assert sorted(item.name for item in tmp_path.iterdir()) == ['autosar.py', '中文 包目录']


@pytest.mark.parametrize('fault', ['missing', 'broken', 'missing_member', 'invalid_json', 'schema_version', 'xsd_sha256', 'python_sha256'])
def test_invalid_bundle_does_not_replace_target(bundle, tmp_path, fault):
    path, metadata, content = bundle
    if fault == 'broken':
        path.write_bytes(b'not a zip')
    elif fault != 'missing':
        if fault in metadata:
            metadata[fault] = 'wrong'
        with ZipFile(path, 'w') as archive:
            archive.writestr('metadata.json', '{' if fault == 'invalid_json' else json.dumps(metadata))
            if fault != 'missing_member':
                archive.writestr('autosar.py', content)
    target = tmp_path / 'autosar.py'
    target.write_bytes(b'# previous binding\n')
    with pytest.raises(click.ClickException, match='预生成绑定'):
        _unpack_binding('00044', target)
    assert target.read_bytes() == b'# previous binding\n'
