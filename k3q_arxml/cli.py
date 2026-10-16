"""跨平台、按需生成当前 AUTOSAR 绑定的命令行。"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from shutil import copytree, ignore_patterns
from tempfile import TemporaryDirectory
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
@click.option('--schema-version', type=click.Choice(tuple(SCHEMAS)), help='按需解压预生成的 AUTOSAR 绑定，在独立临时目录中运行；不修改已安装的绑定。')
def serve_mcp(schema_version: str | None) -> None:
    """在当前目录启动 stdio MCP；所有诊断输出到 stderr。"""
    try:
        from .mcp.server import create_server
    except ModuleNotFoundError as exc:
        if exc.name == 'mcp' or (exc.name and exc.name.startswith('mcp.')):
            raise click.ClickException('缺少 MCP 可选依赖，请先运行 uv sync --locked --extra mcp。') from exc
        raise
    from . import autosar
    from .log import configure_logging

    if schema_version is not None and schema_version != autosar.SCHEMA_VERSION:
        with TemporaryDirectory(prefix='k3q-arxml-mcp-') as directory:
            package = Path(directory) / 'k3q_arxml'
            copytree(PACKAGE_ROOT, package, ignore=ignore_patterns('__pycache__', '.codegen-*', 'bindings'))
            # 源码仓库将 Skill 放在包外；安装后的 wheel 已将其放入包内。
            if not (package / 'skills').is_dir() and (PACKAGE_ROOT.parent / 'skills').is_dir():
                copytree(PACKAGE_ROOT.parent / 'skills', package / 'skills')
            _unpack_binding(schema_version, package / 'autosar.py')
            env = {**os.environ, 'PYTHONPATH': os.pathsep.join(filter(None, [directory, os.environ.get('PYTHONPATH')]))}
            # -P 避免当前目录的源码遮住临时包；新进程不会复用父进程已导入的旧类型。
            result = subprocess.run([sys.executable, '-P', '-m', 'k3q_arxml', 'mcp'], env=env)
        raise SystemExit(result.returncode)

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
    # 仅写入固定文件，不使用 extractall，压缩包中的其他路径不会被解压。
    target.write_bytes(content)


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
