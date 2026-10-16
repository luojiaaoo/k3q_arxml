"""跨平台、按需生成当前 AUTOSAR 绑定的命令行。"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from zipfile import BadZipFile, ZipFile

import click

from .schemas import PACKAGE_ROOT, SCHEMAS


@click.group()
def cli() -> None:
    """管理当前项目的 AUTOSAR 类型绑定。"""


@cli.command('versions')
def versions() -> None:
    """列出可生成的 AUTOSAR schema 版本。"""
    for version in SCHEMAS:
        click.echo(version)


@cli.command('mcp')
@click.option('--schema-version', type=click.Choice(tuple(SCHEMAS)), help='按需用预生成的 AUTOSAR 绑定覆盖当前库的 autosar.py，再以新进程启动。')
def serve_mcp(schema_version: str | None) -> None:
    """在当前目录启动 stdio MCP；所有诊断输出到 stderr。"""
    from . import autosar
    from .log import configure_logging

    if schema_version is not None and schema_version != autosar.SCHEMA_VERSION:
        _unpack_binding(schema_version, PACKAGE_ROOT / 'autosar.py')
        # 当前进程已导入旧类型，覆盖后必须由新进程加载；下一次同版本启动无需再次解压。
        result = subprocess.run([sys.executable, '-m', 'k3q_arxml', 'mcp'])
        raise SystemExit(result.returncode)

    # 指定其他绑定时由子进程加载 SDK，父进程只负责准备绑定，避免重复导入。
    try:
        from .mcp.server import create_server
    except ModuleNotFoundError as exc:
        if exc.name == 'mcp' or (exc.name and exc.name.startswith('mcp.')):
            raise click.ClickException('缺少 MCP 可选依赖，请先运行 uv sync --locked --extra mcp。') from exc
        raise

    configure_logging()
    create_server(Path.cwd()).run(transport='stdio')


def _unpack_binding(version: str, target: Path) -> None:
    archive = PACKAGE_ROOT / 'bindings' / f'autosar_{version.replace(".", "_")}.zip'
    try:
        with ZipFile(archive) as bundle:
            metadata = json.loads(bundle.read('metadata.json'))
            content = bundle.read('autosar.py')
        if (
            metadata['schema_version'] != version
            or metadata['xsd_sha256'] != hashlib.sha256(SCHEMAS[version].read_bytes()).hexdigest()
            or metadata['python_sha256'] != hashlib.sha256(content).hexdigest()
        ):
            raise ValueError('绑定版本、XSD 或代码哈希不匹配')
    except (OSError, BadZipFile, KeyError, ValueError, TypeError) as exc:
        raise click.ClickException(f'无法读取预生成绑定 {archive}：{exc}；请检查发行包是否完整。') from exc
    # 只写入固定文件；同目录暂存后原子替换，不复制包或直接截断现有绑定。
    temporary = None
    try:
        with NamedTemporaryFile(dir=target.parent, prefix='.autosar-', suffix='.tmp', delete=False) as output:
            temporary = Path(output.name)
            output.write(content)
        temporary.replace(target)
    except OSError as exc:
        raise click.ClickException(f'无法替换当前绑定 {target}：{exc}；请检查安装目录的写入权限，原绑定未修改。') from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@cli.command('generate')
@click.argument('version', type=click.Choice(tuple(SCHEMAS)))
def generate(version: str) -> None:
    """生成 VERSION 为 k3q_arxml.autosar，替换此前生成的版本。"""
    _generate_binding(version, PACKAGE_ROOT / 'autosar.py')


def _generate_binding(version: str, target: Path, *, stderr: bool = False) -> None:
    schema = SCHEMAS[version]
    if not schema.is_file():
        raise click.ClickException(f'找不到 schema：{schema}')

    # xsdata 会启动 ruff；显式加入当前解释器的脚本目录，无需激活虚拟环境。
    env = {**os.environ, 'PATH': str(Path(sys.executable).parent) + os.pathsep + os.environ.get('PATH', '')}
    click.echo(f'正在生成 AUTOSAR {version} ...', err=stderr)
    try:
        # 在同一文件系统的临时目录生成，成功后原子替换当前绑定。
        # xsdata 生成的临时 __init__.py 不会覆盖本库的公共入口。
        with TemporaryDirectory(prefix='.codegen-', dir=target.parent) as directory:
            subprocess.run(
                [
                    sys.executable,
                    '-m',
                    'xsdata',
                    'generate',
                    str(schema),
                    '--package',
                    'autosar',
                    '--structure-style',
                    'single-package',
                    '--compound-fields',
                    '--relative-imports',
                    '-mll',
                    '999',
                ],
                cwd=directory,
                env=env,
                check=True,
                stdout=sys.stderr if stderr else None,
            )
            generated = Path(directory) / 'autosar.py'
            if not generated.is_file():
                raise click.ClickException('xsdata 未生成预期的 autosar.py，当前绑定未修改。')
            with generated.open('a', encoding='utf-8') as output:
                output.write(f'\n\nSCHEMA_VERSION = {version!r}\n')
            generated.replace(target)
    except subprocess.CalledProcessError as exc:
        raise click.ClickException(f'xsdata 生成失败（退出码 {exc.returncode}），当前绑定未修改。') from exc
    except OSError as exc:
        raise click.ClickException(f'无法生成绑定：{exc}') from exc
    click.echo(f'已生成 {target}\n使用 from k3q_arxml import autosar 导入类型；请在新的 Python 进程中使用。', err=stderr)
