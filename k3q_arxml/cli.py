"""跨平台、按需生成当前 AUTOSAR 绑定的命令行。"""

import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

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
def serve_mcp() -> None:
    """在当前目录启动 stdio MCP；所有诊断输出到 stderr。"""
    try:
        from .mcp.server import create_server
    except ModuleNotFoundError as exc:
        if exc.name == 'mcp' or (exc.name and exc.name.startswith('mcp.')):
            raise click.ClickException('缺少 MCP 可选依赖，请先运行 uv sync --locked --extra mcp。') from exc
        raise
    from .log import configure_logging

    configure_logging()
    create_server(Path.cwd()).run(transport='stdio')


@cli.command('generate')
@click.argument('version', type=click.Choice(tuple(SCHEMAS)))
def generate(version: str) -> None:
    """生成 VERSION 为 k3q_arxml.autosar，替换此前生成的版本。"""
    schema = SCHEMAS[version]
    if not schema.is_file():
        raise click.ClickException(f'找不到 schema：{schema}')

    # xsdata 会启动 ruff；显式加入当前解释器的脚本目录，无需激活虚拟环境。
    env = {**os.environ, 'PATH': str(Path(sys.executable).parent) + os.pathsep + os.environ.get('PATH', '')}
    target = PACKAGE_ROOT / 'autosar.py'
    click.echo(f'正在生成 AUTOSAR {version} ...')
    try:
        # 在同一文件系统的临时目录生成，成功后原子替换当前绑定。
        # xsdata 生成的临时 __init__.py 不会覆盖本库的公共入口。
        with TemporaryDirectory(prefix='.codegen-', dir=PACKAGE_ROOT) as directory:
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
    click.echo(f'已生成 {target}\n使用 from k3q_arxml import autosar 导入类型；请在新的 Python 进程中使用。')
