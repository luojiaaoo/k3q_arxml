# 项目开发指南

本文件适用于整个仓库。协作说明、注释和变更总结优先使用中文；代码标识符沿用英文命名。修改前先阅读相关源码，以实际实现为准。

## 项目概况

`k3q_arxml` 是基于 Python、xsdata 和 lxml 的 AUTOSAR ARXML 读取、查询、编辑和回写库，支持多文件对象索引、反向引用查询及 ADT / IDT 名称修改。

- 使用 uv 管理项目；`.python-version` 指定开发使用 Python 3.11，最低运行版本为 3.11。
- `pyproject.toml` 声明运行及开发依赖，`uv.lock` 锁定完整依赖树。
- xsdata 及 CLI 使用 26.2，Click 使用 8.2.1，Ruff 使用兼容生成配置的 0.13.3，lxml 使用 5.4.0。
- 日志使用 Loguru 0.7.3，配置统一放在 `k3q_arxml/log.py`；其他模块只导入 logger，入口脚本通过 `configure_logging()` 设置级别。
- 暂不添加构建后端或打包配置。从仓库根目录运行命令。
- 保留所有 XSD，按需生成一个当前版本的真实 `autosar.py`，不预生成全版本绑定，不使用懒加载代理或全局版本切换函数。

## 目录与职责

| 路径 | 职责与维护方式 |
| --- | --- |
| `k3q_arxml/arxml_file.py` | `ArxmlFile`，负责单文件解析、原有引用扫描和回写 |
| `k3q_arxml/k3q_arxml.py` | `IOArxml`，负责多文件管理和查询汇总 |
| `k3q_arxml/__init__.py` | 导出 `IOArxml`、`ArxmlFile`、`ArxmlNamedNode` 和 logger |
| `k3q_arxml/log.py` | Loguru 的输出、格式和日志级别配置，默认 INFO |
| `k3q_arxml/__main__.py`、`cli.py` | `python -m k3q_arxml` 的 Click 命令行入口 |
| `k3q_arxml/schemas.py` | 集中定义 dataclass、Pydantic 模型和类型别名；扫描实际 schema 目录，建立可用版本与 XSD 路径映射 |
| `k3q_arxml/schemas/autosar_*/` | 各版本 AUTOSAR XSD 及关联的 `xml.xsd`，均保留在版本控制中 |
| `k3q_arxml/autosar.py` | 按需生成的当前版本类型模块，Git 忽略，不手动编辑 |
| `chg_adt_name.py` | 按 SenderReceiverInterface 名称列表为关联 ADT 添加或恢复后缀 |
| `chg_adt_idt_name.py` | 全局移除文本中的 ADT / IDT 前缀，再为目标数据类型及引用添加前缀 |
| `test.py`、`test3.py` | 历史手工示例，依赖缺失的 `test/model_merge.arxml`，不是自动化测试入口 |
| `test/ThrottlePositionControlComposition.arxml` | 4.2.2 schema 的已提交样例 |
| `tests/` | 标准库 unittest 回归测试，使用临时文件 |
| `docs/` | DaVinci 与 AUTOSAR 兼容性参考 PDF |
| `README.md` | 环境、生成命令及使用说明 |
| `pyproject.toml` | 项目元数据、依赖及 Ruff 配置（行宽 180、单引号） |
| `uv.lock`、`.python-version` | 完整依赖锁文件与开发 Python 版本 |

## 环境与类型生成

在仓库根目录执行：

```console
uv sync --locked
uv run python -m k3q_arxml versions
uv run python -m k3q_arxml generate 4.2.2
```

- uv 自动准备 Python 3.11、创建 `.venv` 并安装依赖；后续统一使用 `uv run`，无需激活环境。
- `uv sync --locked --no-dev` 也安装生成 CLI；Ruff 是 xsdata CLI 的间接运行依赖，开发组固定其兼容版本。
- 使用 `uv add` / `uv remove` 管理依赖，开发工具添加 `--dev`；将 `pyproject.toml` 与 `uv.lock` 一起提交。
- 不手动维护间接依赖列表，不为普通功能修改升级无关依赖。

## 核心行为与修改约束

### AUTOSAR 版本与类型

- 可用版本从 `schemas/autosar_*` 目录扫描，只包含存在对应主 XSD 的版本，不硬编码版本范围。CLI 只生成指定版本，成功后原子替换 `autosar.py`；生成失败保留旧绑定。
- 用户统一使用 `from k3q_arxml import IOArxml, autosar`，autosar 是真实生成模块。不要重新引入懒加载代理、动态版本导出或 `change_autosar_version()`。
- 生成文件不存在时，CLI 帮助、版本列表和生成命令必须可用；创建 `IOArxml` 应给出生成指引。
- `ArxmlFile` 在对象解析前核对文件 `xsi:schemaLocation` 声明的 AUTOSAR XSD 与当前绑定的 `SCHEMA_VERSION`；版本不一致或缺少声明时抛出 `ValueError`，不自动切换版本。
- 重新生成其他版本后使用新 Python 进程，避免模块缓存中的旧类型；一个运行进程使用一个版本。
- `ar(clazz)` 返回 `list[ArxmlNamedNode[T]]`，每项的 `.xml_obj` 保留具体类型。维护这些泛型信息，避免退化为 Any。

### 对象、路径与引用

- `IOArxml(filepaths=[...])` 为每个文件创建 `ArxmlFile`；文件层负责解析并调用 `scan_ref()` 建立索引。单文件也可以直接使用 `ArxmlFile`。
- 文件路径参数 `Filename` 统一为 `Path`；加载、添加和查询时使用 `resolve()` 规范化，文件层保存绝对路径，IO 层按绝对路径去重。`append(filepath)` 加载已有 ARXML 文件，拒绝已加载、不存在或非普通文件的路径；解析成功后才加入管理，添加时不写回文件。
- 路径使用元组，如 `('Package', 'Type')`；XML 引用使用 `/Package/Type`。使用 `ref_str2ref()` / `ref2ref_str()` 转换。
- `ref()` 返回唯一包装对象或 None；`ar()` 按具体类型与路径前缀返回对象列表。
- 每个 `ArxmlNamedNode` 只保存一个 `.xml_obj`，通过 `.file` 关联所属文件。跨文件同路径查询用 `IOArxml.find()` 获取列表，或用 `ref(..., filename=...)` 指定文件；不指定文件且匹配多个时抛出异常。
- `ref_to_ref()` 返回 `(引用对象, 所在对象路径, 文件名)` 列表。
- 对象和反向引用索引由各文件维护，IO 层汇总已有索引。修改名称、引用或对象结构后，在依赖新结构查询前重新 `scan_ref()`。
- 保持最小实现，不顺便增加功能。`ArxmlFile.__scan_arobj_ref()` 是核心扫描函数，本次拆分仅搬移原逻辑，后续修改应控制范围。
- 重命名需同步目标 `short_name.value` 和所有关联引用。明确批量处理使用旧索引还是新索引，不在迭代活动索引时重建它。

### 文件与生成代码

- `ArxmlFile.save()` 回写单个文件，`IOArxml.flush_to_file()` 调用各文件的保存方法；查询操作不回写。测试使用临时副本，不覆盖用户文件或已提交样例。
- 保留命名空间、schema、缩进和序列化配置；往返结果验证对象与引用语义，不要求逐字节一致。
- 编辑脚本使用当前绑定，不再提供版本参数。保留 main 入口，导入脚本不得执行参数解析或文件写入。
- `chg_adt_idt_name.py` 在解析前执行全局文本替换；修改时注意非目标文本及重复执行的影响。
- 不删除 XSD，不修改无关版本。调整 schema 时同步检查本地关联 XSD 的相对路径。
- 生成使用 `--structure-style single-package --compound-fields --relative-imports -mll 999`。compound fields 用于保留重复 choice / sequence 的元素顺序。
- 不手动编辑或提交生成的 `autosar.py`，不对其运行项目级格式化。调查生成类型时按类名定位相关片段，避免完整输出大型模块。

## 验证与交付

```console
uv run python -m k3q_arxml generate 4.2.2
uv run python -m unittest discover -s tests -v
uv run ruff check k3q_arxml tests chg_adt_name.py chg_adt_idt_name.py
uv run ruff format --check k3q_arxml tests chg_adt_name.py chg_adt_idt_name.py
uv lock --check
git diff --check
```

- 样例测试需要 4.2.2 绑定，缺失或版本不符会跳过；交付时区分实际执行与跳过的测试。
- CLI 测试覆盖真实小型 XSD 生成、版本替换、失败保留旧绑定以及中文和空格路径；不生成所有版本。
- ARXML 测试覆盖解析回写、引用缓存、重命名同步及多文件对象。
- 涉及类型接口时检查直接导入及 `ar()` 返回项 `.xml_obj` 的静态类型。
- 不运行根目录历史示例作为测试，不导入有顶层副作用的旧版本脚本。
- 开始前检查 `git status --short` 并保留用户已有修改；按授权范围变更，不擅自提交。
- 交付前检查差异，不混入临时 ARXML、打印结果、缓存或生成的 Python 绑定。
- 说明改动、验证结果和未验证事项；不能把未执行或跳过的检查描述为通过。
- 用户文档中的示例注释优先说明代码做什么、对应哪个 XML 节点、结果如何使用。解释 `.xml_obj`、`.value` 等必要写法，避免用泛型、类型保留或模块实现细节代替操作说明。
