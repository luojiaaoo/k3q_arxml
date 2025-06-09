import argparse

# 参数设置
parser = argparse.ArgumentParser(description='change ApplicationDataTypeRef name')
## 添加的后缀名
parser.add_argument('-s', '--suffix', required=True, help='suffix')
## arxml版本
parser.add_argument('-v', '--autosar_version', nargs='?', default='autosar_4_2_2', help='autosar version, default autosar_4_2_2')
## arxml文件
parser.add_argument('arxml_files', nargs='+', help='arxml file list')
args = parser.parse_args()

from k3q_arxml import change_autosar_version

change_autosar_version(args.autosar_version)
from k3q_arxml import IOArxml, autosar, logger
import logging

logger.level = logging.DEBUG

suffix = args.suffix
io_arxml = IOArxml(filepaths=args.arxml_files)
for ref_s, arxml_ref_obj_filename_ref in io_arxml.ref_to_arxml_ref_obj_filename_ref.items():
    is_ApplicationDataTypeRef = False
    obj_s = io_arxml.ref(ref=ref_s).default
    for arxml_ref_obj, filename, ref in arxml_ref_obj_filename_ref:
        if isinstance(arxml_ref_obj, autosar.DataTypeMap.ApplicationDataTypeRef) and not arxml_ref_obj.value.endswith(suffix):
            arxml_ref_obj.value = arxml_ref_obj.value + suffix
            is_ApplicationDataTypeRef = True
    if is_ApplicationDataTypeRef:
        logger.debug(f'change {IOArxml.ref2ref_str(ref_s)} to {IOArxml.ref2ref_str(ref_s)}{suffix}')
        obj_s.short_name.value = obj_s.short_name.value + suffix
io_arxml.flush_to_file()
