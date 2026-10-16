"""发布前生成各 AUTOSAR 版本的绑定压缩包，不修改默认 autosar.py。"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from importlib.metadata import version as package_version
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from k3q_arxml.schemas import PACKAGE_ROOT, SCHEMAS


def build_binding(version: str, output: Path) -> Path:
    started = time.perf_counter()
    with TemporaryDirectory(prefix=f'k3q-binding-{version}-') as directory:
        target = Path(directory) / 'autosar.py'
        result = subprocess.run(
            [
                sys.executable,
                '-c',
                'import sys; from pathlib import Path; from k3q_arxml.cli import _generate_binding; _generate_binding(sys.argv[1], Path(sys.argv[2]), stderr=True)',
                version,
                str(target),
            ],
            cwd=Path(__file__).resolve().parent,
            env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding='utf-8',
        )
        if result.returncode:
            raise RuntimeError(f'{version} 生成失败：\n{result.stdout}')
        content = target.read_bytes()
        module = ast.parse(content)
        declared = next(
            ast.literal_eval(node.value)
            for node in module.body
            if isinstance(node, ast.Assign) and any(isinstance(item, ast.Name) and item.id == 'SCHEMA_VERSION' for item in node.targets)
        )
        if declared != version:
            raise ValueError(f'生成的绑定版本不匹配：{version} / {declared}')
        metadata = {
            'schema_version': version,
            'xsd_sha256': hashlib.sha256(SCHEMAS[version].read_bytes()).hexdigest(),
            'python_sha256': hashlib.sha256(content).hexdigest(),
            'xsdata_version': package_version('xsdata'),
        }
        archive = output / f'autosar_{version.replace(".", "_")}.zip'
        staged = Path(directory) / archive.name
        with ZipFile(staged, 'w', compression=ZIP_DEFLATED, compresslevel=9) as bundle:
            for name, data in [('autosar.py', content), ('metadata.json', json.dumps(metadata, sort_keys=True).encode('utf-8'))]:
                info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                bundle.writestr(info, data, compresslevel=9)
        # 先复制到同目录的临时文件，再原子替换，避免跨文件系统 rename。
        pending = archive.with_suffix('.zip.tmp')
        try:
            pending.write_bytes(staged.read_bytes())
            pending.replace(archive)
        finally:
            pending.unlink(missing_ok=True)
    print(f'{version}: {archive.stat().st_size / 1024:.0f} KiB, {time.perf_counter() - started:.1f}s', flush=True)
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--versions', nargs='+', choices=tuple(SCHEMAS), default=list(SCHEMAS))
    parser.add_argument('--jobs', type=int, choices=range(1, 5), default=2)
    parser.add_argument('--output', type=Path, default=PACKAGE_ROOT / 'bindings')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = [executor.submit(build_binding, version, args.output) for version in dict.fromkeys(args.versions)]
        for future in as_completed(futures):
            future.result()


if __name__ == '__main__':
    main()
