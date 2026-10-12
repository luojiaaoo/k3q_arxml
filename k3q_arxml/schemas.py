"""从实际文件目录中查找可用的 AUTOSAR schema。"""

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
SCHEMA_ROOT = PACKAGE_ROOT / 'schemas'


def discover_schemas(root: Path = SCHEMA_ROOT) -> dict[str, Path]:
    """扫描 autosar_* 目录，只列出存在对应主 XSD 文件的版本。"""
    schemas = {}
    for directory in sorted(root.glob('autosar_*')):
        version = directory.name.removeprefix('autosar_')
        schema = directory / f'AUTOSAR_{version.replace("_", "-")}.xsd'
        if schema.is_file():
            schemas[version.replace('_', '.')] = schema
    return schemas


SCHEMAS = discover_schemas()
