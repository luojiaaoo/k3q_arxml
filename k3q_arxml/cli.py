"""内部 AUTOSAR XSD 发现及绑定生成工具，不注册用户 CLI；直接执行仅供维护者生成绑定。"""

import argparse
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from tempfile import TemporaryDirectory

import click

PACKAGE_ROOT = Path(__file__).resolve().parent
XSD_ROOT = PACKAGE_ROOT / 'assets' / 'xsd'
BINDING_ROOT = PACKAGE_ROOT / 'schemas'


def discover_schemas(root: Path = XSD_ROOT) -> dict[str, Path]:
    """扫描 autosar_* 目录，只列出存在对应主 XSD 文件的版本。"""
    schemas = {}
    for directory in sorted(root.glob('autosar_*')):
        version = directory.name.removeprefix('autosar_')
        schema = directory / f'AUTOSAR_{version.replace("_", "-")}.xsd'
        if schema.is_file():
            schemas[version.replace('_', '.')] = schema
    return schemas


SCHEMAS = discover_schemas()


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
    click.echo(f'已生成 {target}\n使用 from k3q_arxml.schemas import {target.stem} 导入类型；请在新的 Python 进程中使用。', err=stderr)


def build_binding(version: str, output: Path) -> Path:
    started = time.perf_counter()
    suffix = version.replace('.', '_')
    target = output / f'autosar_{suffix}.py'
    target.parent.mkdir(parents=True, exist_ok=True)
    _generate_binding(version, target, stderr=True)
    print(f'{version}: {target.stat().st_size / 1024:.0f} KiB, {time.perf_counter() - started:.1f}s', flush=True)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--versions', nargs='+', choices=tuple(SCHEMAS), default=list(SCHEMAS))
    parser.add_argument('--jobs', type=int, choices=range(1, 5), default=2)
    parser.add_argument('--output', type=Path, default=BINDING_ROOT)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = [executor.submit(build_binding, version, args.output) for version in dict.fromkeys(args.versions)]
        for future in as_completed(futures):
            future.result()


if __name__ == '__main__':
    main()
