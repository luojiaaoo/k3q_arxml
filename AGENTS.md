# 项目开发、MCP 操作与发布指南

本文件适用于整个仓库。协作说明、注释和变更总结优先使用中文；代码标识符沿用英文命名。修改前先阅读相关源码，以实际实现为准。

本文件统一维护仓库开发规范、MCP 操作说明和 PyPI 发布流程。用户安装和 Python 使用说明见 [README.md](README.md)。命令在仓库根目录执行；发布示例使用 Windows PowerShell。

- [项目概况](#项目概况)与[目录职责](#目录与职责)
- [环境与类型生成](#环境与类型生成)
- [核心行为与修改约束](#核心行为与修改约束)
- [验证与交付](#验证与交付)
- [ARXML MCP 使用说明](#arxml-mcp-使用说明)
- [开发与 PyPI 发布](#开发与-pypi-发布)

## 项目概况

通过本项目 MCP 分析或修改 ARXML 文件时，先读取 [`skills/arxml-mcp/SKILL.md`](skills/arxml-mcp/SKILL.md)，按任务需要读取其操作指南和 AUTOSAR 知识参考。源码开发仍遵循本文件；技能中的模型操作流程不替代仓库开发规范。

`k3q_arxml` 是基于 Python、xsdata 和 lxml 的 AUTOSAR ARXML 读取、查询、编辑和回写库，支持多文件对象索引、反向引用查询及 ADT / IDT 名称修改。

- 使用 uv 管理项目；`.python-version` 指定开发使用 Python 3.11，最低运行版本为 3.11。
- `pyproject.toml` 使用最低版本及兼容上界声明运行、可选及开发依赖，不用 `==` 固定单一版本；`uv.lock` 锁定完整依赖树及实际安装版本。
- xsdata 及 CLI 支持 `>=26.2,<27`，Click 支持 `>=8.2.1,<9`，lxml 支持 `>=5.4.0,<6`；Ruff 限定在 `>=0.13.3,<0.14`，避免生成配置受不兼容变更影响。
- 日志使用 Loguru `>=0.7.3,<0.8`，配置统一放在 `k3q_arxml/log.py`；其他模块只导入 logger，入口脚本通过 `configure_logging()` 设置级别。
- 使用 Hatchling 构建 wheel 和 sdist；`tool.uv.package = false` 保持仓库通过源码运行，避免中文路径下可编辑安装的编码问题。打包与发布流程见[开发与 PyPI 发布](#开发与-pypi-发布)。
- 保留所有 XSD；发布前生成全部 `k3q_arxml/schemas/schame/autosar_<版本>.py` 真实绑定并随包分发。所有 MCP 命令复用同一入口，仅按版本命令名称选择版本，在函数内部仅导入对应模块；启动不生成、解压、替换绑定或启动子进程。

## 目录与职责

| 路径 | 职责与维护方式 |
| --- | --- |
| `k3q_arxml/arxml_file.py` | `ArxmlFile`，负责单文件解析、索引初始化、节点增量更新和回写 |
| `k3q_arxml/k3q_arxml.py` | `IOArxml`，负责多文件管理和查询汇总 |
| `k3q_arxml/__init__.py` | 导出 `IOArxml`、`ArxmlFile`、`ArxmlNamedNode` 和 logger |
| `k3q_arxml/log.py` | Loguru 的输出、格式和日志级别配置，默认 INFO |
| `k3q_arxml/cli.py` | 内部的路径常量、XSD 发现与绑定生成工具；不对用户注册开发 CLI；直接执行仅供维护者批量生成绑定 |
| `k3q_arxml/schemas/__init__.py` | 定义 ARXML 核心 dataclass、Pydantic 模型和类型别名；不负责版本目录发现 |
| `k3q_arxml/mcp/schemas.py` | 集中定义 MCP 请求、响应模型及会话状态，与核心 ARXML 模型分开维护 |
| `k3q_arxml/schemas/xsd/autosar_*/` | 各版本 AUTOSAR XSD 及关联的 `xml.xsd`，均保留在版本控制中 |
| `k3q_arxml/schemas/schame/autosar_*.py` | 各版本真实生成绑定，不手动编辑；不保留旧的 autosar.py 兼容入口 |
| `k3q_arxml/script/serve_mcp.py` | 各版本 MCP 命令通过 project.scripts 安装到环境 Scripts / bin 目录，均复用同一启动文件 |
| `demo/chg_adt_name.py` | 按 SenderReceiverInterface 名称列表为关联 ADT 添加或恢复后缀 |
| `demo/chg_adt_idt_name.py` | 全局移除文本中的 ADT / IDT 前缀，再为目标数据类型及引用添加前缀 |
| `test.py`、`test3.py` | 历史手工示例，依赖缺失的 `test/model_merge.arxml`，不是自动化测试入口 |
| `tests/ThrottlePositionControlComposition.arxml`、`tests/SWC.arxml`、`tests/IoHwAb.arxml` | 已提交的 ARXML 测试样例 |
| `tests/` | pytest 回归测试，使用 fixture、参数化用例和临时文件 |
| `docs/` | DaVinci 与 AUTOSAR 兼容性参考 PDF |
| `README.md` | 环境、生成命令、Python 使用说明及 MCP 配置方法 |
| `AGENTS.md` | 仓库开发规范、MCP 工具与编辑流程、校验恢复及打包发布说明 |
| `pyproject.toml` | 项目元数据、依赖及 Ruff 配置（行宽 180、单引号） |
| `uv.lock`、`.python-version` | 完整依赖锁文件与开发 Python 版本 |

## 环境与类型生成

在仓库根目录执行：

```console
uv sync --locked
uv run python k3q_arxml/cli.py --versions 4.2.2
```

- uv 自动准备 Python 3.11、创建 `.venv` 并安装依赖；后续统一使用 `uv run`，无需激活环境。
- `uv sync --locked --no-dev` 也安装生成 CLI；Ruff 是 xsdata CLI 的间接运行依赖，开发组限定其兼容范围，实际版本由锁文件确定。
- 使用 `uv add` / `uv remove` 管理依赖，开发工具添加 `--dev`；将 `pyproject.toml` 与 `uv.lock` 一起提交。
- 不手动维护间接依赖列表，不为普通功能修改升级无关依赖。

## 核心行为与修改约束

### AUTOSAR 版本与类型

- 可用版本从 `schemas/xsd/autosar_*` 目录扫描，只包含存在对应主 XSD 的版本，不硬编码版本范围。维护者通过 k3q_arxml/cli.py 将指定版本平铺生成为 `schemas/schame/autosar_<版本>.py`，成功后原子替换该模块；失败保留旧文件，不影响其他版本。
- Python 明确导入版本，例如 `from k3q_arxml.schemas.schame import autosar_00044`，通过 `binding=autosar_00044` 传给文件、工程或 MCP 服务。模块是真实生成类型，不使用懒加载代理、全局切换或 sys.modules 别名。
- 包入口直接导入 ARXML 接口；绑定在使用它的函数内部 import，避免导入无关版本。所有版本均预先生成，不提供 autosar.py 兼容入口。cli.py 供内部导入和维护者直接执行，不注册 k3q-arxml 命令，也不提供 python -m k3q_arxml 入口。
- MCP 仅提供免参数的各版本命令，例如 `k3q-arxml-mcp-00044`。全部映射到 script/serve_mcp.py 的同一个无参数函数，仅按命令名固定版本，不提供通用命令及 --schema-version 参数。所有版本取自实际 XSD 目录，仅导入指定模块并显式传给服务。启动不运行 -m、不写入安装目录、不启动子进程。服务运行后版本固定，解析、引用索引及编辑复制均保留该绑定。AI 文件操作流程不额外生成、切换或重启，也不重复询问版本。
- `ArxmlFile` 在对象解析前核对文件 `xsi:schemaLocation` 声明的 AUTOSAR XSD 与当前绑定的 `SCHEMA_VERSION`；版本不一致时告警并继续解析，缺少声明时抛出 `ValueError`。MCP 将版本不匹配作为结构化 warning 返回，不仅凭版本号拒绝加载；实际绑定解析、XSD、引用及编辑往返校验仍正常执行，保存保留原文件声明，不自动切换版本。
- 重新生成某版本后使用新 Python 进程，避免模块缓存中的旧类型；每个文件和 MCP 服务使用自己的固定绑定。
- `ar(clazz)` 返回 `list[ArxmlNamedNode[T]]`，每项的 `.xml_obj` 保留具体类型。维护这些泛型信息，避免退化为 Any。

### 对象、路径与引用

- `IOArxml(filepaths=[...], binding=所需版本模块)` 为每个文件创建 `ArxmlFile`；文件层解析后调用一次 `scan_ref()`，全量建立初始索引。后续编辑通过 `update_node()` 增量维护。单文件也可以直接使用 `ArxmlFile`。
- 文件路径参数 `Filepath` 统一为 `Path`；加载、添加和查询时使用 `resolve()` 规范化，文件层保存绝对路径，IO 层按绝对路径去重。`append(filepath)` 加载已有 ARXML 文件，拒绝已加载、不存在或非普通文件的路径，以及与已加载文件重复的对象路径；解析并检查成功后才加入管理，添加时不写回文件。
- 路径使用元组，如 `('Package', 'Type')`；XML 引用使用 `/Package/Type`。使用 `str2ref()` / `ref2str()` 转换。
- `ref()` 返回唯一包装对象或 None；`ar()` 按具体类型与路径前缀返回对象列表。
- 每个 `ArxmlNamedNode` 保存实际 XML 对象 `.xml_obj`、索引路径 `.ref` 和所属文件路径 `.filepath`；需要文件对象时使用 `io_arxml.files[node.filepath]`。每次扫描直接创建新包装，增量更新成功后同步传入 `node` 的 `.ref`；后续编辑子节点时重新查询其包装。查询指定文件时用 `io_arxml.files[filepath.resolve()].ref(ref)`；`IOArxml.ref()` 发现多个匹配时抛出异常。
- `ref_to_ref()` 返回 `ArxmlRefNode` 列表，每项通过 `.xml_obj`、`.owner_ref` 和 `.filepath` 保存引用对象及来源位置；`set_dest(路径元组)` 使用 `ref2str()` 转换并修改引用节点的目标路径文本，后续仍需更新具名祖先索引并保存文件。
- 对象、反向引用和 UUID 索引由各文件维护，直接访问 `file.objects`、`file.references` 和 `file.uuids`。IO 层通过 `ref()`、`ar()`、`ref_to_ref()` 汇总查询结果，不提供 `objects` / `references` 汇总属性。常规流程是加载时全量初始化一次，后续调用 `IOArxml.edit(node)` 自动增量更新，或直接修改 `node.xml_obj` 后调用 `file.update_node(node)`，完成后再查询新结构。
- `scan_ref()` 从 `root` 生成全部包装和初始索引，不为初始化添加读取旧索引或复用旧包装的逻辑。`update_node()` 只扫描传入节点的整棵子树，并清理、合并三份索引；增删、替换或移动编辑根本身时，传入包含全部变化的共同具名祖先。
- 编辑接口信任当前文件查询返回的有效包装，不重复添加类型、文件归属、对象身份或过期校验。
- 保持最小实现，不顺便增加功能。`ArxmlFile.__scan_arobj_ref()` 扫描传入对象，遇到具名节点就直接创建新包装，返回对象索引、引用索引和 UUID 索引。调用方直接发布全量结果或增量合并，不增加旧包装复用逻辑或 `wrapped_objects` 转换层，修改应控制范围。
- 重命名需同步目标 `short_name.value` 和所有关联引用。明确批量处理使用旧索引还是新索引，不在迭代活动索引时重建它。

### 文件与生成代码

- `ArxmlFile.save()` 回写单个文件，`IOArxml.flush_to_file()` 调用各文件的保存方法；查询操作不回写。测试使用临时副本，不覆盖用户文件或已提交样例。
- 保留命名空间、schema、缩进和序列化配置；往返结果验证对象与引用语义，不要求逐字节一致。
- 编辑脚本使用当前绑定，不再提供版本参数。保留 main 入口，导入脚本不得执行参数解析或文件写入。
- `demo/chg_adt_idt_name.py` 在解析前执行全局文本替换；修改时注意非目标文本及重复执行的影响。
- 不删除 XSD，不修改无关版本。调整 schema 时同步检查本地关联 XSD 的相对路径。
- 生成使用 `--structure-style single-package --compound-fields --relative-imports -mll 999`。compound fields 用于保留重复 choice / sequence 的元素顺序。
- 不手动编辑生成的 `autosar_*.py`，不对其运行项目级格式化。调查生成类型时按类名定位，避免完整输出大型模块。全部绑定作为发行源码资源纳入版本控制。
- 通过 `uv run python k3q_arxml/cli.py` 更新全部独立绑定；可用 `--versions 00044` 只更新指定版本。修改 XSD 或生成规则后同步生成相应模块，发布前检查版本覆盖和统一入口参数选择；不再维护绑定 ZIP。

## 验证与交付

```console
uv run python k3q_arxml/cli.py --versions 4.2.2
uv run pytest -v
uv run ruff check k3q_arxml tests demo
uv run ruff format --check k3q_arxml tests demo
uv lock --check
git diff --check
```

MCP 是默认运行依赖，上面的 pytest 命令包含真实 stdio 客户端回归。

- 样例测试需要 4.2.2 绑定，缺失或版本不符会跳过；交付时区分实际执行与跳过的测试。
- 内部工具测试覆盖 XSD 目录发现、真实小型 XSD 生成、独立版本互不覆盖、失败保留旧文件及中文和空格路径；通常不在测试中重新生成全部版本。
- ARXML 测试覆盖解析回写、引用缓存、重命名同步及多文件对象。
- 涉及类型接口时检查直接导入及 `ar()` 返回项 `.xml_obj` 的静态类型。
- 不运行根目录历史示例作为测试，不导入有顶层副作用的旧版本脚本。
- 开始前检查 `git status --short` 并保留用户已有修改；按授权范围变更，不擅自提交。
- 交付前检查差异，不混入临时 ARXML、打印结果或缓存；发行资源包含按规则生成的全部 autosar_<版本>.py，不包含旧 autosar.py 或绑定 ZIP。
- 说明改动、验证结果和未验证事项；不能把未执行或跳过的检查描述为通过。
- 用户文档中的示例注释优先说明代码做什么、对应哪个 XML 节点、结果如何使用。解释 `.xml_obj`、`.value` 等必要写法，避免用泛型、类型保留或模块实现细节代替操作说明。

## ARXML MCP 使用说明

本项目通过本地 stdio MCP 提供 ARXML 查询、编辑、校验和保存工具。安装、启动及客户端配置见 [README](README.md#通过-mcp-供大模型使用)。

### 操作前置条件

客户端可以无参数启动 `Scripts/k3q-arxml-mcp-00044.exe`（Linux/macOS 使用 bin/k3q-arxml-mcp-00044）。当前源码规则见 [AUTOSAR 版本与类型](#autosar-版本与类型)。参数选定的绑定在运行期间固定。该改动尚未发布；已发布的 2.1.3 使用旧的 -m 入口。完整配置见 [README](README.md#通过-mcp-供大模型使用)。

文件声明版本与绑定不匹配时，返回 `SCHEMA_MISMATCH` 告警并继续尝试解析；解析成功后可以正常查询。`project_info` 的 `schema_version` 为当前绑定版本，告警信息同时列出文件声明版本。

版本告警会保留在工程信息、校验和差异预览中，本身不阻止编辑或保存。实际绑定无法识别的内容、XSD 错误及其他校验错误仍按原规则处理；保存保留文件原有的 schema 声明。不能仅凭 `4.2.2`、`00044` 等版本标签的形式推断高低或兼容性。

服务以进程启动目录作为文件访问范围，包含其子目录。相对文件路径以此目录为基准，不接受范围外的文件；客户端通过 `cwd` 指定业务模型目录。

### 智能体技能

面向编程智能体的操作技能位于 [`skills/arxml-mcp/SKILL.md`](skills/arxml-mcp/SKILL.md)，附带按需读取的操作指南和 AUTOSAR 基础知识。可以显式要求智能体读取该入口，或将整个 `skills/arxml-mcp/` 目录复制到所用智能体支持的技能目录；MCP 连接仍需单独配置。后续领域知识可继续添加到该技能的 `references/`，并在入口中注明适用任务。

发行包同时附带 `[site-packages]\k3q_arxml\skills\arxml-mcp`，这是本 MCP 的使用手册，操作 ARXML 前应优先读取。如果尚未加载 `arxml-mcp` Skill，先调用不带参数的 `get_skill_path()` 获取实际目录，再读取其中的 `SKILL.md` 和任务所需 `references`；无需先打开工程。建议将整个目录复制安装到客户端的 skills 目录后刷新加载，便于后续自动发现和加载，无需重新创建技能。工具只返回目录路径，不读取或解析文档内容。

使用 `uv run --with "k3q-arxml"` 启动时，该包及其依赖由临时环境提供；临时环境由 uv 缓存管理并可复用。当前工作目录用于确定 ARXML 文件访问范围，查找 Skill 时以 `get_skill_path()` 返回的实际安装路径为准。

### 工具与操作流程

| 工具 | 用途 |
| --- | --- |
| `get_skill_path` | 获取本 MCP 使用手册目录；操作前优先读取，建议安装为 arxml-mcp Skill，无需工程会话 |
| `open_project` | 加载明确指定的文件集合，获取 `project_id`、`file_id` 和 `revision` |
| `project_info` | 查看工程状态及未保存文件 |
| `find_nodes` | 按 XML 标签、名称子串、路径前缀和文件查询具名节点 |
| `get_node` | 读取摘要或分页 XML，也可以读取节点内一个 XPath 对应的元素 |
| `find_references` | 查询入向引用，返回来源节点和相对 XPath |
| `describe_type` | 查看当前绑定中 XML 标签的字段、枚举及 compound choices |
| `get_type_source` | 无需工程会话，查询当前版本的 XSD 或 Python 绑定定义片段、候选及关联定义 |
| `rename_node` | 重命名节点，自动同步指向它及后代的已加载引用 |
| `patch_xml` | 在指定节点内提交一批属性、文本或结构修改 |
| `validate_project` | 检查 XSD、重复对象路径、引用目标及 DEST |
| `preview_changes` | 分页预览全部未保存差异并获取 `preview_token` |
| `save_changes` | 使用预览凭据显式保存并生成备份 |
| `close_project` | 关闭会话；丢弃未保存修改必须指定 `discard_changes=true` |

例如，让模型将 `types.arxml` 中的 `/Types/Speed` 改名为 `Velocity`，同时同步 `interfaces.arxml` 中的引用：

1. 调用 `open_project`，传入 `{"filepaths":["types.arxml","interfaces.arxml"]}`。
2. 用返回的 `project_id` 调用 `get_node` 和 `find_references`，确认目标及影响范围。
3. 调用 `rename_node`，传入 `project_id`、`ref="/Types/Speed"`、`new_name="Velocity"` 和最新 `revision`。
4. 用返回的新路径 `/Types/Velocity` 继续查询；后续编辑使用新的 `revision`。
5. 调用 `validate_project` 和 `preview_changes`；按 `next_offset` 查看剩余差异。
6. 在客户端完成用户确认后，用返回的 `preview_token` 调用 `save_changes`。

查询默认返回摘要；`get_node(include_xml=true)` 才返回 XML。查询、引用和差异默认每页 50 项，最多 200 项；XML 默认每段 16,000 字符，通过 `xml_offset` / `xml_limit` 继续读取。差异中的超长行拆成最多 2,000 字符的片段，`continuation=true` 表示上一行的延续。两种分页都在 `next_offset=null` 时结束。

`preview_changes` 默认使用 `diff_mode="file"`，展示磁盘原文到待保存文件的完整差异，其中可能包含 `0` 到 `0.0` 等序列化规范化变化。可用 `diff_mode="model"` 聚焦本次对象修改：此视图对比加载时和当前对象经同一绑定序列化后的 XML。返回的 `serialization_changed_files` 列出受影响文件中原文与加载时序列化结果存在差异的文件；这些差异不会出现在 model 视图中，保存前仍需阅读 file 视图。分页时保持 `diff_mode` 不变，两种视图共用当前 revision 的预览凭据。

文件恢复到加载时或最近保存后的对象内容时，`dirty` 自动清除，预览不再列出该文件，保存也不写回该文件。成功恢复原值仍会增加 `revision` 并使旧预览凭据失效；其他文件尚有修改时仍需处理。

`describe_type` 也支持 SHORT-NAME、TYPE-TREF 等嵌套标签。同名标签可能对应不同类型，返回的 `alternative_types` 列出候选；可传入 `python_type` 精确选择，例如 `describe_type(xml_tag="TYPE-TREF", python_type="VariableDataPrototype.TypeTref")`。父标签描述中的 `type_names` 可用于确定选择。

确认 XSD 元素顺序、choice / sequence、出现次数或 Python 绑定声明时使用 `get_type_source`。参数 `name` 接受 XML 标签、XSD 定义名、Python 限定类型名或返回的 `definition_id`，`source` 为 `xsd`（默认）或 `binding`。例如 `{"name":"complexType:SW-BASE-TYPE"}` 读取 XSD 类型，`{"name":"VariableDataPrototype.TypeTref","source":"binding"}` 读取嵌套 Python 类。工具只读当前固定版本，无需工程会话，不接收文件路径；源码索引首次查询时建立，不在启动时解析大型文件。

同名 XSD group / complexType 或多角色标签返回 `candidates`，用选中的 `definition_id` 作为下一次 name。候选每页 50 项，通过 `candidate_offset=next_candidate_offset` 继续；有歧义时 content 为 null。选定定义后，源码默认每段 16,000 字符、最多 32,000，通过 `offset=next_offset` 继续，直至 null。`definition` 提供来源路径和行号；XSD 片段由原定义序列化，嵌套标签返回包含声明的顶层定义以保留分组上下文。`related_definitions` 最多列出 200 个关联标识，完整数量见 `total_related_definitions`，完整引用仍在源码中；可按标识继续查，不自动递归展开。查询范围包含当前主 XSD 和同目录 xml.xsd，不跟随外部 import/include。

### 局部 XML 修改

`patch_xml` 的 `operations` 按顺序在同一份候选树上执行，整批成功才发布到会话。XPath 相对于指定节点，`ar:` 对应 `http://autosar.org/schema/r4.0`。每项操作必须匹配一个元素；不支持绝对路径、父轴、XPath 函数或变量。

支持属性谓词，例如以包含该类型的包为 `ref` 时，用 `./ar:ELEMENTS/ar:SW-BASE-TYPE[@UUID='test-create-001']` 选择类型。不能漏掉 XML 中间的 ELEMENTS 层；匹配失败时错误会给出实际匹配数量，先读取 XML 核对结构，再调整选择器。重命名的 `ref` 使用当前已存在的旧路径，`new_name` 只填新名称。

下面的请求修改 `/Types/Velocity` 的 UUID 和 CATEGORY 文本：

```json
{
  "project_id": "使用 open_project 返回的 ID",
  "ref": "/Types/Velocity",
  "revision": 1,
  "operations": [
    {"op": "set_attribute", "xpath": ".", "attribute": "UUID", "value": "DCE:12345678-1234-1234-1234-123456789abc"},
    {"op": "set_text", "xpath": "./ar:CATEGORY", "value": "VALUE"}
  ]
}
```

可用操作为 `set_text`、`set_attribute`、`remove_attribute`、`append`、`insert_before`、`insert_after`、`replace` 和 `delete`。结构操作的 `xml` 必须是一个完整元素，并携带 AUTOSAR 命名空间。例如，在包的 ELEMENTS 末尾添加数据类型：

```json
{
  "op": "append",
  "xpath": "./ar:ELEMENTS",
  "xml": "<APPLICATION-PRIMITIVE-DATA-TYPE xmlns=\"http://autosar.org/schema/r4.0\"><SHORT-NAME>AddedType</SHORT-NAME><CATEGORY>VALUE</CATEGORY></APPLICATION-PRIMITIVE-DATA-TYPE>"
}
```

现有 SHORT-NAME 的修改使用 `rename_node`。`replace` 必须保持其中具名节点的路径集合；结构增删使用 `delete` 与 `append` / `insert`。删除后仍有已加载引用指向被删节点时，整批编辑失败。顶层包的增删使用 `ref="/"`，并明确提供 `file_id`；选择器仍相对于 AUTOSAR 根节点。

修改失败不会改变活动会话及原文件。过期 `revision` 会被拒绝；成功修改后旧预览凭据失效。服务拒绝 DTD、实体声明、未知绑定字段和不能往返保留的 XML；元素顺序由 compound fields 保留并通过往返核对。

### 校验、备份与恢复

引用同步和校验只覆盖明确加载的文件。已有未解析引用作为警告保留；编辑新增的悬空引用、重复路径或可检查的 DEST 类型错误会阻止修改。能由当前绑定表示但未通过 XSD 的输入允许加载查询，受影响文件必须修复到通过 XSD 后才能发布修改和保存。XSD 校验不覆盖全部 AUTOSAR 业务规则。

保存前会检查所有已加载文件是否在外部修改，并再次校验。原始文件备份位于同目录，名称类似 `.types.arxml.k3q-<唯一ID>.bak`；返回结果包含完整路径。工作目录下的 `.k3q-mcp-recovery-<唯一ID>.json` 记录文件路径、备份路径、前后 SHA-256 及状态。成功保存后状态为 `complete`，普通写入失败且恢复成功时为 `rolled_back`。

每个文件通过同目录原子替换保存；多文件保存不具备系统级原子性。进程中断或恢复失败留下 `pending` / `rollback_failed` 清单时，服务会阻止打开工程、继续编辑或保存。恢复步骤：

1. 停止所有可能写入这些文件的程序，读取清单中的文件与备份路径。
2. 比较当前文件与清单的 `old_sha256` / `new_sha256`；若两者均不匹配，先保留外部改动，不直接覆盖。
3. 对照 `old_sha256` 核对备份，将需要恢复的文件恢复为备份内容，并再次核对哈希。
4. 全部文件恢复完成后，将清单 `status` 改为 `rolled_back`，再重新打开工程。

服务不会自动推断用户已确认保存；确认交互由模型客户端负责。关闭服务会丢失尚未保存的内存修改。

## 开发与 PyPI 发布

本节面向维护者，说明打包、发行验证及 PyPI 发布步骤。

### 当前状态

当前发行名为 `k3q-arxml`，Python 导入名为 `k3q_arxml`，包版本由 `pyproject.toml` 的 `[project].version` 决定，当前为 `2.1.3`，对应 Git 标签 `v2.1.3`。Git 标签不会自动改变包版本。

仓库已配置 Hatchling 构建后端及发行文件范围，可直接按下文构建。`git push` 只更新 Git 仓库，上传 PyPI 还需要构建和发布发行文件。

依赖管理遵循[环境与类型生成](#环境与类型生成)中的规则；下文安装命令中的 `==2.1.3` 用于核验指定发行包。

### 打包配置

`pyproject.toml` 中的打包配置如下：

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.uv]
package = false

[tool.hatch.build.targets.wheel]
packages = ["k3q_arxml"]

[tool.hatch.build.targets.wheel.force-include]
"skills" = "k3q_arxml/skills"

[tool.hatch.build.targets.sdist]
include = [
    "/k3q_arxml",
    "/skills",
    "/README.md",
    "/LICENSE",
    "/pyproject.toml",
]

[tool.hatch.build]
exclude = [
    "**/__pycache__",
    "**/*.pyc",
    "/k3q_arxml/.codegen-*",
]
```

wheel 包含 Python 库、MCP 子包、全部真实 autosar_<版本>.py、统一 script/serve_mcp.py、所有 XSD 及关联 xml.xsd，以及完整技能目录。运行时读取所选模块与 XSD，不使用绑定 ZIP；不创建只有说明或空内容的 __init__.py。

`tool.uv.package = false` 保持仓库通过源码运行，`uv sync` 不自动安装项目自身，避免 Windows Python 3.11 在中文路径下读取可编辑安装的 `.pth` 文件时出现编码错误。`uv build` 仍使用 Hatchling 构建发行包，用户可正常安装 wheel。

sdist 包含构建 wheel 所需的包源码、`pyproject.toml`、包介绍 `README.md`、许可证 `LICENSE` 和原始 `skills/` 目录；从 sdist 构建 wheel 时使用同一映射。Hatchling 还会自动附带 `PKG-INFO` 和 `.gitignore`。测试、名称处理脚本及开发说明保留在 Git 仓库，不放入发行包。

用户可从仓库的 `skills/arxml-mcp` 或已安装包的 `k3q_arxml/skills/arxml-mcp` 复制完整目录到智能体的技能目录。安装包内路径可用 `python -c "from importlib.resources import files; print(files('k3q_arxml').joinpath('skills', 'arxml-mcp'))"` 查看；复制方式见 README。安装 Python 包不会自动复制 Skill 或注册 MCP。

`pyproject.toml` 的 `[project.scripts]` 声明覆盖全部可用版本的 k3q-arxml-mcp-<版本> 命令，全部指向同一无参数函数，安装器在 Scripts / bin 下创建命令。版本仅由命令名称决定。cli.py 仅为内部工具，不注册开发 CLI。构建规则见 [Hatchling 文档](https://hatch.pypa.io/latest/config/build/)。

### 发布前验证与版本号

先安装开发环境（默认包含 MCP）：

```powershell
uv sync --locked
uv run python -c "from k3q_arxml.schemas.schame import autosar_4_2_2 as autosar; print(autosar.SCHEMA_VERSION)"
```

发布包携带全部版本独立绑定，包括 `autosar_4_2_2.py`。没有 autosar.py 兼容入口；发布前检查模块 SCHEMA_VERSION 与文件名对应。

首次准备发行资源，或更新 XSD、xsdata 版本及生成规则后，在仓库根目录执行：

```powershell
uv run python k3q_arxml/cli.py
```

脚本每次并行生成两个版本，最终覆盖全部可用版本；输出 `k3q_arxml/schemas/schame/autosar_<版本>.py`，例如 autosar_00044.py。可用 --versions 00044 --jobs 1 只重建指定版本。全部真实模块纳入版本控制，构建 wheel / sdist 时直接分发；启动无需生成或解压。

发布回归需通过实际脚本入口建立 stdio 连接，覆盖 4.2.2 和 00044 的工具发现、查询、引用同步、编辑、预览与保存。检查入口仅导入对应绑定、默认模块未被额外导入、源文件不被启动过程改写；stdout 仅承载 MCP 协议。

检查目标 PyPI 项目的所有权、已有版本及待发布内容。以下以 `2.1.3` 为例；若该版本已使用，应选择新的版本，并同步替换后文目录、文件名和安装命令中的版本号。PyPI 已上传的发行文件不能用不同内容覆盖，即使删除也不能重用该文件名。详见 [PyPI 帮助](https://pypi.org/help/#file-name-reuse)。

修改 `[project].version` 后更新锁文件，并执行：

```powershell
uv lock
uv sync --locked
uv run pytest -v
uv run ruff check k3q_arxml tests demo
uv run ruff format --check k3q_arxml tests demo
uv lock --check
git diff --check
git status --short
```

确认测试实际执行，MCP stdio 测试必须实际执行。新增打包配置后，将 `pyproject.toml` 与更新后的 `uv.lock` 一起纳入本次发布提交。

### 构建与检查发行文件

使用本次版本的独立输出目录，避免上传旧版本文件：

```powershell
uv build --no-sources --out-dir dist/2.1.3
uvx --from twine twine check --strict dist/2.1.3/*.whl dist/2.1.3/*.tar.gz
uv run python -m zipfile -l dist/2.1.3/k3q_arxml-2.1.3-py3-none-any.whl
uv run python -m tarfile -l dist/2.1.3/k3q_arxml-2.1.3.tar.gz
```

应得到一个 wheel 和一个 sdist。确认两者包含覆盖全部 schema 的 autosar_<版本>.py、统一 script/serve_mcp.py、MCP、全部 XSD 和完整 Skill；wheel 的 console_scripts 中仅包含覆盖全部 schema 的版本专用命令，且都映射到同一启动函数。确认 Skill 本地链接可用，没有临时 ARXML、绑定 ZIP、空壳 __init__.py、备份或恢复清单。构建行为见 [uv 发布指南](https://docs.astral.sh/uv/guides/package/)。

在独立临时环境安装 wheel，避免误用仓库源码：

```powershell
$wheel = (Resolve-Path 'dist/2.1.3/k3q_arxml-2.1.3-py3-none-any.whl').Path
$checkDir = Join-Path ([System.IO.Path]::GetTempPath()) ('k3q-arxml-release-' + [guid]::NewGuid())
uv venv $checkDir --python 3.11
$checkPython = Join-Path $checkDir 'Scripts/python.exe'
uv pip install --python $checkPython "$wheel"
& $checkPython -I -c "from k3q_arxml import IOArxml; from k3q_arxml.schemas.schame import autosar_4_2_2 as autosar; from k3q_arxml.cli import SCHEMAS; print(autosar.SCHEMA_VERSION); print(SCHEMAS); assert SCHEMAS and all(p.is_file() for p in SCHEMAS.values())"
& $checkPython -I -c "from k3q_arxml.script.serve_mcp import main; assert callable(main)"
```

`-I` 避免当前目录及 `PYTHONPATH` 中的源码遮住已安装包。还应在这个环境中用真实 MCP 客户端完成一次连接和工具发现；测试编辑、保存时只使用临时模型副本。另建环境安装 sdist，确认它也能构建和导入。

### 可选：先上传 TestPyPI

分别注册 [TestPyPI](https://test.pypi.org/account/register/) 和 [PyPI](https://pypi.org/account/register/) 账号，按站点要求完成验证和双因素认证。两个站点的账号、项目与 API token 相互独立。

在 TestPyPI 的账号设置创建 API token。首次创建项目时可使用具有相应账号权限的 token，项目创建后使用项目范围 token。下面通过隐藏输入读取 token，不将实际 token 写进文件：

```powershell
$publishSecret = Read-Host 'TestPyPI API token' -AsSecureString
$env:UV_PUBLISH_TOKEN = [System.Net.NetworkCredential]::new('', $publishSecret).Password
try {
    uv publish --publish-url https://test.pypi.org/legacy/ dist/2.1.3/*.whl dist/2.1.3/*.tar.gz
    if ($LASTEXITCODE -ne 0) { throw 'TestPyPI 上传失败' }
} finally {
    Remove-Item Env:UV_PUBLISH_TOKEN
}
```

上传成功后，在另一个临时环境中验证测试站上的包。为避免从 TestPyPI 解析完整依赖树，先从正式 PyPI 安装与本次 wheel 相同的依赖，再只替换测试包：

```powershell
$testDir = Join-Path ([System.IO.Path]::GetTempPath()) ('k3q-arxml-testpypi-' + [guid]::NewGuid())
uv venv $testDir --python 3.11
$testPython = Join-Path $testDir 'Scripts/python.exe'
uv pip install --python $testPython "$wheel"
uv pip install --python $testPython --no-deps --reinstall --index-url https://test.pypi.org/simple/ 'k3q-arxml==2.1.3'
& $testPython -I -c "from k3q_arxml import IOArxml; from k3q_arxml.schemas.schame import autosar_4_2_2 as autosar; print(autosar.SCHEMA_VERSION)"
```

安装命令失败时先停止后续验证，不能把原有本地 wheel 的导入成功当作 TestPyPI 安装成功。测试站的上传和安装地址不同，前者是 `/legacy/`，后者是 `/simple/`。更多说明见 [PyPA 发布教程](https://packaging.python.org/en/latest/tutorials/packaging-projects/)。

### 上传正式 PyPI

完成发行文件检查和独立环境安装验证后，先提交发布内容、创建 `v2.1.3` 标签并推送远程仓库，再使用正式 PyPI 创建的 token 上传已经验证过的同一组文件。配置了 TestPyPI 时，可先完成上一节的测试发布。

```powershell
$publishSecret = Read-Host 'PyPI API token' -AsSecureString
$env:UV_PUBLISH_TOKEN = [System.Net.NetworkCredential]::new('', $publishSecret).Password
try {
    uv publish --publish-url https://upload.pypi.org/legacy/ dist/2.1.3/*.whl dist/2.1.3/*.tar.gz
    if ($LASTEXITCODE -ne 0) { throw 'PyPI 上传失败' }
} finally {
    Remove-Item Env:UV_PUBLISH_TOKEN
}
```

发布完成后，从仓库外的新环境安装并验证：

```powershell
$releaseDir = Join-Path ([System.IO.Path]::GetTempPath()) ('k3q-arxml-pypi-' + [guid]::NewGuid())
uv venv $releaseDir --python 3.11
$releasePython = Join-Path $releaseDir 'Scripts/python.exe'
uv pip install --python $releasePython 'k3q-arxml==2.1.3'
& $releasePython -I -c "from k3q_arxml import IOArxml; from k3q_arxml.schemas.schame import autosar_4_2_2 as autosar; print(autosar.SCHEMA_VERSION)"
```

客户端将 command 指向安装环境 Scripts/k3q-arxml-mcp-00044.exe（Linux/macOS 使用 bin 下同名命令），args 为空，cwd 指向业务模型目录。需要其他版本时改用对应命令，不传版本参数。安装后无需源码 PYTHONPATH；get_skill_path 返回内置手册目录。

确认 PyPI 页面、安装结果与远程发布提交及标签对应。后续更新按“新版本号 → 验证 → 构建 → 推送提交与标签 → 可选 TestPyPI → 正式 PyPI”重复；自动发布可后续接入 [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/)，不需要把长期 token 存入仓库。
