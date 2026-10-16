"""带外部修改检测、备份和恢复清单的多文件保存。"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from shutil import copymode
from uuid import uuid4

from ..log import logger
from .xml import fail


def checked_path(workspace: Path, path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(workspace):
        fail('OUTSIDE_WORKSPACE', f'路径不在工作目录内：{path}', '只使用服务启动目录及其子目录中的普通 ARXML 文件。')
    if not resolved.is_file():
        fail('FILE_NOT_FOUND', f'不是已存在的普通文件：{path}', '检查文件路径和访问权限。')
    return resolved


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def check_recovery(workspace: Path) -> None:
    for path in workspace.glob('.k3q-mcp-recovery-*.json'):
        try:
            manifest = json.loads(path.read_text(encoding='utf-8'))
            status = manifest['status']
        except (OSError, ValueError, KeyError, TypeError):
            fail('RECOVERY_REQUIRED', f'恢复清单不可读取：{path}', '检查恢复清单和备份文件；确认文件状态后移走该清单再重新打开工程。')
        if status not in {'complete', 'rolled_back'}:
            fail('RECOVERY_REQUIRED', f'存在未完成保存：{path}', '按清单比较文件哈希并恢复备份；确认所有文件已恢复后将清单 status 改为 rolled_back。')


def _write_file(path: Path, content: bytes) -> None:
    with path.open('xb') as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _write_manifest(path: Path, manifest: dict) -> None:
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def save_files(workspace: Path, contents: dict[Path, bytes], baseline: dict[Path, bytes]) -> tuple[dict[Path, Path], Path | None]:
    """每个文件使用同目录原子替换；发生普通异常时恢复已替换的文件。"""
    check_recovery(workspace)
    if not contents:
        return {}, None
    for path in contents:
        if checked_path(workspace, path) != path or digest(path.read_bytes()) != digest(baseline[path]):
            fail('FILE_CONFLICT', f'文件已在外部修改：{path}', '先保留会话修改，重新加载文件并合并外部改动。')

    transaction_id = uuid4().hex
    manifest_path = workspace / f'.k3q-mcp-recovery-{transaction_id}.json'
    entries = []
    temporary_paths = []
    replaced = []
    manifest = {'status': 'pending', 'files': entries}
    try:
        for path, content in contents.items():
            backup = path.with_name(f'.{path.name}.k3q-{transaction_id}.bak')
            temporary = path.with_name(f'.{path.name}.k3q-{transaction_id}.tmp')
            temporary_paths.append(temporary)
            _write_file(backup, baseline[path])
            _write_file(temporary, content)
            copymode(path, temporary)
            entries.append({'filepath': str(path), 'backup_path': str(backup), 'old_sha256': digest(baseline[path]), 'new_sha256': digest(content)})
        _write_manifest(manifest_path, manifest)
        for path, temporary in zip(contents, temporary_paths):
            if checked_path(workspace, path) != path or digest(path.read_bytes()) != digest(baseline[path]):
                fail('FILE_CONFLICT', f'保存期间检测到外部修改：{path}', '重新加载并合并外部改动。')
            os.replace(temporary, path)
            replaced.append(path)
        manifest['status'] = 'complete'
        _write_manifest(manifest_path, manifest)
    except Exception as exc:
        rollback_errors = []
        for path in reversed(replaced):
            try:
                if checked_path(workspace, path) != path or digest(path.read_bytes()) != digest(contents[path]):
                    raise OSError(f'{path} 在替换后被外部修改，不覆盖新内容')
                restore = path.with_name(f'.{path.name}.k3q-{transaction_id}.restore.tmp')
                temporary_paths.append(restore)
                _write_file(restore, baseline[path])
                copymode(path, restore)
                os.replace(restore, path)
            except Exception as rollback_error:
                rollback_errors.append(str(rollback_error))
        manifest['status'] = 'rollback_failed' if rollback_errors else 'rolled_back'
        manifest['error'] = str(exc)
        manifest['rollback_errors'] = rollback_errors
        try:
            _write_manifest(manifest_path, manifest)
        except OSError as manifest_error:
            rollback_errors.append(str(manifest_error))
        code = 'RECOVERY_REQUIRED' if rollback_errors else 'SAVE_FAILED'
        fail(code, f'保存失败：{exc}；恢复清单：{manifest_path}', '检查清单和备份；未恢复时先手动恢复，已恢复时可修复写入条件后重新预览保存。')
    finally:
        for temporary in temporary_paths:
            try:
                temporary.unlink(missing_ok=True)
            except OSError as cleanup_error:
                logger.warning('无法清理保存临时文件 {}：{}', temporary, cleanup_error)
    return {Path(entry['filepath']): Path(entry['backup_path']) for entry in entries}, manifest_path
