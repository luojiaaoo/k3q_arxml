# 项目开发指南

本文件适用于整个仓库。协作说明、注释和变更总结优先使用中文；代码标识符沿用现有英文命名。修改前先阅读相关源码，以实际实现为准。

## 项目概况

`k3q_arxml` 是基于 Python、xsdata 和 lxml 的 AUTOSAR ARXML 读取、查询、编辑和回写库。核心能力包括多文件加载、对象路径索引、反向引用查询，以及 ADT / IDT 名称与引用的批量修改。

- README 标注 Python 3.11；开发优先使用该版本，其他版本的兼容性需要单独验证。
- 依赖及工具版本固定在 `requirements.txt`，包含 xsdata、lxml 和 Ruff。
- 当前没有 `pyproject.toml`、`setup.py`、正式测试框架配置或 CI 配置。从仓库根目录运行脚本，使本地包可以导入。

## 目录与职责

| 路径 | 职责与维护方式 |
| --- | --- |
| `k3q_arxml/k3q_arxml.py` | 手写核心：`IOArxml`、`ArxmlObject`、解析、索引、扫描与序列化 |
| `k3q_arxml/__init__.py` | 公共导出、各 AUTOSAR 版本入口及 `change_autosar_version()` |
| `k3q_arxml/lazy_import.py` | 延迟导入大型绑定模块 |
| `k3q_arxml/arxml_binding/autosar_*/` | 各版本 XSD 与生成的 Python 数据类、枚举及导出文件 |
| `k3q_arxml/arxml_binding/gen.bat` | Windows 下使用 xsdata 重新生成各版本绑定 |
| `chg_adt_name.py` | 按 SenderReceiverInterface 名称列表为关联 ADT 添加或恢复后缀 |
| `chg_adt_idt_name.py` | 先全局移除文件文本中的 `ADT_` / `IDT_`，再为目标数据类型及其引用添加前缀 |
| `test.py`、`test3.py` | 历史手工示例；执行时会回写输入文件，不能作为自动化测试入口 |
| `test/ThrottlePositionControlComposition.arxml` | 已提交的 ARXML 样例，schema 为 `AUTOSAR_4-2-2.xsd` |
| `docs/` | DaVinci 与 AUTOSAR 兼容性参考 PDF |
| `README.md` | 使用说明；部分示例依赖未提交的 `test/model_merge.arxml` |
| `ruff.toml` | 格式配置：行宽 180、单引号 |

## 环境准备

在仓库根目录使用 PowerShell：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

后续命令显式使用 `.venv` 的解释器，无需激活环境。不假设系统 Python 已安装项目依赖，也不为普通功能修改升级固定依赖版本。

## 核心行为与修改约束

### AUTOSAR 版本

- 库默认使用 `autosar_00048`；两个根目录命令行脚本默认使用 `autosar_4_2_2`。
- 当前版本入口为 `autosar_4_2_2`、`autosar_00043` 至 `autosar_00052`。
- 加载文件前显式选择匹配版本；当前实现不会根据输入文件的 schema 自动切换绑定。
- `change_autosar_version()` 会修改模块全局状态。先调用它，再执行 `from k3q_arxml import IOArxml, autosar`，然后创建实例。先前导入到局部变量的 `autosar` 不会随之更新。
- 避免在同一流程中交错操作不同版本的对象；新增版本时同步检查公共导出、生成脚本、XSD 与示例。

### 对象、路径与引用

- `IOArxml(filepaths=[...])` 构造时解析文件并调用 `scan_ref()` 建立索引。
- 路径使用元组，例如 `('Package', 'Type')`；XML 引用使用 `/Package/Type`。使用 `ref_str2ref()` / `ref2ref_str()` 转换。
- `ref()` 返回 `ArxmlObject`，找不到时实际返回 `None`；调用方需要处理未找到的情况。
- `ar(clazz, ref_prefix=...)` 返回路径到 `ArxmlObject` 的字典。
- 同一路径可对应多个文件中的同类型对象。此时 `.default` 和 `.default_filename` 会抛出异常；使用 `.filter(filename)` 或遍历包装对象获取 `(xml_obj, filename)`。
- `ref_to_ref()` 返回 `(引用对象, 所在对象路径, 文件名)` 的列表。注意此顺序，历史示例不能作为唯一依据。
- 对象路径索引和反向引用索引都是缓存。修改 `short_name`、引用值、对象结构或调用 `create_arxml()` 后，在依赖新结构查询前调用 `scan_ref()`。
- 重命名需同步修改目标 `short_name.value` 和所有关联引用。批量处理时明确使用旧索引还是新索引，避免在迭代活动索引时重建它。

### 文件回写

- `flush_to_file()` 会覆盖当前实例管理的全部文件；仅调用查询方法不会回写。
- 修改及验证使用临时副本，避免覆盖用户原始 ARXML 或已提交样例。
- 保留现有命名空间、schema、缩进和序列化配置；往返序列化不保证与原文件逐字节一致，应验证对象与引用语义。
- 两个命令行脚本均会原地修改文件。尤其 `chg_adt_idt_name.py` 在解析前就执行全局文本替换；修改该脚本时需要覆盖对非目标文本和重复执行的影响。

## 生成代码维护

- 优先修改手写核心代码。不要对整个 `arxml_binding/` 运行格式化或批量重构；生成文件很大，且其格式与手写代码不同。
- 调查绑定时先按版本、类名定位，只读取相关片段，避免完整输出大型模块或生成的 `__init__.py`。
- 修改绑定应优先从对应 XSD 或生成流程入手，使用固定版本 xsdata 保持可复现；确需手动修补时说明原因及重新生成后的处理方式。
- 生成入口为 `k3q_arxml/arxml_binding/gen.bat`，需要 xsdata 命令可用；执行前审阅脚本，因为它会生成所有列出的版本。
- 保留生成参数 `--compound-fields --relative-imports -mll 999`；脚本注释说明 `--compound-fields` 用于保留原始 XML 顺序。
- 脚本部分路径使用大写 `AUTOSAR_000xx`，实际目录为小写 `autosar_000xx`；迁移到大小写敏感环境时需检查路径。
- 重新生成后检查差异范围，仅保留与任务相关的版本和文件变更。

## 验证方式

当前没有可直接运行的完整自动化测试套件。不要直接执行 `test.py`、`test3.py` 或默认运行 pytest 来代替验证：历史脚本依赖缺失文件，且有顶层回写操作。

对发生修改的手写 Python 文件执行定向检查，例如核心模块变更时：

```powershell
.\.venv\Scripts\python.exe -m ruff check k3q_arxml/k3q_arxml.py
.\.venv\Scripts\python.exe -m ruff format --check k3q_arxml/k3q_arxml.py
```

将路径替换为本次实际修改文件。若发现历史问题，区分已有问题与本次引入的问题，避免无关的整库修复。

涉及解析、索引或序列化时，可使用以下临时副本完成基础往返检查：

```powershell
@'
from pathlib import Path
from shutil import copy2
from tempfile import TemporaryDirectory

from k3q_arxml import change_autosar_version

change_autosar_version('autosar_4_2_2')
from k3q_arxml import IOArxml

with TemporaryDirectory() as tmp:
    path = Path(tmp) / 'sample.arxml'
    copy2('test/ThrottlePositionControlComposition.arxml', path)
    original = IOArxml(filepaths=[str(path)])
    paths_before = set(original.ref_to_arxml_obj)
    assert paths_before, '样例应包含可索引的对象'
    original.flush_to_file()
    reloaded = IOArxml(filepaths=[str(path)])
    assert set(reloaded.ref_to_arxml_obj) == paths_before
    assert reloaded.xml_schema_location == original.xml_schema_location
print('ARXML 往返检查通过')
'@ | .\.venv\Scripts\python.exe -
```

该检查只验证基础往返能力，不能代替具体功能验证：

- 修改引用扫描：检查实际引用对象、所在路径、文件名，以及刷新缓存后的结果。
- 修改重命名：覆盖目标定义和引用同步、共享类型、多文件、重复执行，以及脚本支持的后缀恢复场景。
- 修改版本选择或序列化：使用匹配版本的样例，检查重载结果、命名空间与输出 schema。
- 新增回归测试时使用独立临时文件，并避免导入会执行顶层参数解析或文件写入的历史脚本。

## 变更交付

- 开始前检查 `git status --short`，保留用户已有修改；不擅自移动目录、删除历史脚本或提交生成结果。
- 按任务范围修改文件，保持现有公共 API 和延迟导入方式；行为变化同步更新说明或示例。
- 提交前检查 `git diff --check` 和实际差异，避免混入临时 ARXML、打印结果、缓存或无关生成文件。
- 交付时说明改动内容、验证结果和未验证事项。缺少依赖或样例时如实说明，不能将未运行的检查描述为通过。
