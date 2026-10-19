"""按版本命令名称选择 AUTOSAR 绑定的 stdio MCP 入口。"""

from importlib import import_module
from pathlib import Path

import click

from k3q_arxml.cli import SCHEMAS


@click.command()
def main() -> None:
    """在当前目录启动 MCP，仅导入所选版本，不修改绑定文件。"""
    command = Path(click.get_current_context().info_name or '').stem
    schema_version = next((version for version in SCHEMAS if command == f'k3q-arxml-mcp-{version.replace(".", "-")}'), None)
    if schema_version is None:
        raise click.UsageError('请使用 k3q-arxml-mcp-<版本> 命令启动，例如 k3q-arxml-mcp-00044。')

    suffix = schema_version.replace('.', '_')
    binding = import_module(f'k3q_arxml.schemas.schame.autosar_{suffix}')

    from k3q_arxml.log import configure_logging
    from k3q_arxml.mcp.server import create_server

    configure_logging()
    create_server(Path.cwd(), binding=binding).run(transport='stdio')


if __name__ == '__main__':
    main()
