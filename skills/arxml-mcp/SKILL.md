---
name: arxml-mcp
description: 使用 k3q_arxml MCP 或 Python 脚本读取、查询、修改、校验和保存 AUTOSAR ARXML 文件，处理节点重命名、跨文件引用同步及局部 XML 编辑。适用于交互操作和规则明确的批量变更、验证。
---

# ARXML MCP

通过 `k3q_arxml` MCP 或 Python 脚本完成用户指定的 ARXML 分析或编辑，返回可核对的节点路径、引用影响范围和实际保存结果。

## 按需读取

- 重命名、修改属性或引用、增删节点、处理工具错误时，读 [MCP 操作指南](references/mcp-workflows.md)。
- 变更规则、目标和验证条件已明确，需要批量执行、复用脚本或编写回归验证时，读 [Python 编写与执行指南](references/python-workflows.md)。可以将固化步骤写成 Python 运行，不必逐项调用 MCP；探索阶段仍可用 MCP 确定结构与引用。脚本编写完成后，在当前任务目录用 `uv venv --python=3.11` 创建环境，通过 `uv pip install` 安装依赖，再用 `uv run python script.py` 运行，具体命令见该指南。
- 涉及 ADT / IDT、数据类型映射、SenderReceiverInterface 或 AUTOSAR 路径含义时，读 [AUTOSAR 基础知识](references/autosar-basics.md)。
- MCP 未连接或需要启动参数时，先看下面的用户启动前准备；完整客户端配置见 [README 的 MCP 说明](https://github.com/luojiaaoo/k3q_arxml/blob/v2.1.3/README.md#通过-mcp-供大模型使用)。此目录可从源码仓库或已安装包的 `k3q_arxml/skills/arxml-mcp` 整体复制到智能体支持的技能目录。
- 保存恢复步骤见 [MCP 操作指南](references/mcp-workflows.md#错误处理与保存恢复)；完整工具说明及回归命令见 [MCP.md](https://github.com/luojiaaoo/k3q_arxml/blob/v2.1.3/MCP.md)。
- 不默认加载整个知识目录、全部 XSD 或大型生成绑定。按标签、类型和任务查找相关片段。

## 用户启动前准备

用户准备 Python 3.11 以上环境，并在客户端的 MCP 启动参数中选择 AUTOSAR 版本。发行包默认携带 4.2.2 绑定，以下以指定 00044 为例：

```bash
python -m pip install "k3q-arxml[mcp]==2.1.3"
python -m k3q_arxml versions
python -m k3q_arxml mcp --schema-version 00044
```

服务应由 MCP 客户端以 `command="python"`、`args=["-m", "k3q_arxml", "mcp", "--schema-version", "00044"]` 启动；有多个 Python 环境时，将 command 换成已安装包的 Python 可执行文件路径。也可通过 `uv run --python 3.11 --with "k3q-arxml[mcp]==2.1.3" -m k3q_arxml mcp --schema-version 00044` 启动。上面的 mcp 命令只说明服务入口，不需要额外手动启动第二个服务。源码开发环境在仓库根目录使用 `uv sync --locked --extra mcp` 和 `uv run -m k3q_arxml ...`。

当前源码在指定版本与当前绑定不同时，CLI 校验包内对应版本的预生成 ZIP，直接原子替换当前库的 `autosar.py`，再通过新进程启动 MCP；退出后保留所选绑定。同版本再次启动不再解压或启动子进程。不指定版本时使用当前环境最后准备的绑定；同一环境共享该绑定，需要多个版本时分别使用独立环境。此改动尚未发布，上述固定安装的 `2.1.3` 仍使用临时包；已发布的 `2.1.2` / `2.1.3` 不覆盖原安装包，`2.1.1` 使用运行时生成。

服务启动后版本固定。用户需要其他版本时修改客户端的 `--schema-version` 并重新启动服务。AI 的文件操作流程不额外执行生成命令、切换或重启，也不将版本确认作为每次对话的前置提问。独立 Python 脚本启动前应核对其实际环境的 `autosar.SCHEMA_VERSION`；当前源码的版本选择会保留在库中，而已发布 `2.1.3` 的临时绑定不影响原安装环境。

服务以进程启动目录作为文件访问范围，包含其子目录。使用 MCP 客户端时，由客户端的 `cwd` 指定业务模型目录；源码运行所需的 Python 路径与 uv 项目配置见上面链接的 README。

## 先确定操作上下文

1. 从用户请求和现有会话确定输入文件、目标对象、预期变化及保存授权。只在缺失信息会影响结果时提问，不重复索取已有授权。
2. 发现实际可用的 MCP 工具并读取参数 schema。客户端可能给工具名加前缀；下面使用服务内的工具名，不假设客户端前缀。
3. 用 `open_project` 加载明确的文件集合。希望同步其他文件中的引用时，将这些文件一起加载；不要把未加载文件视为已检查。
4. 保留返回的 `project_id`、文件清单和 `revision`。`file_id` 仅在当前会话内有效；不要跨会话沿用。

文件版本不匹配时，报告文件声明版本、当前绑定版本及 `SCHEMA_MISMATCH` 告警。只要工具成功加载，就继续查询和用户授权的操作，不因版本告警停止，也不自行推断版本高低。实际解析或校验失败时，根据具体错误处理。

## 查询与修改

- 先选择交互 MCP 或独立 Python 脚本。以下工具流程适用于交互 MCP；脚本按 Python 指南使用对象接口或服务接口，不要求为脚本另建一个 stdio 客户端。
- 先用 `find_nodes` 按标签、名称子串、路径前缀筛选，再用 `get_node` 查看准确路径对应的 XML。名称相似不表示对象相同。
- 查询结果默认只有摘要。需要 XML 时设置 `include_xml=true`；存在 `next_offset` 时继续读取，不能把截断片段当成完整 XML。节点列表和引用列表也要按分页读取。
- 不确定标签的字段或枚举时调用 `describe_type`。同名标签有多个 `alternative_types` 时，依据父字段的 `type_names` 指定 `python_type`，不能假定默认候选适用当前角色。
- 重命名调用 `rename_node`，由服务同步指向该节点及后代的已加载引用。不要用字符串全局替换或 `patch_xml` 修改现有 SHORT-NAME。
- 其他修改用 `patch_xml`。选择包含全部变化的最小节点范围，提交一批局部操作；跨节点关联修改的具体边界见操作指南。
- 所有编辑使用最近返回的 `revision`；成功后重新查询新路径及相关引用。以实际返回值为准，不自行推算修订号。

脚本与已连接的 MCP 服务不共享工程会话或未保存对象。不能将旧服务的 `project_id`、`file_id`、`revision` 传给新建的本地服务；切换执行方式时先处理需要保留的内存修改，再从磁盘加载。Python 的核心对象赋值与 `edited()` 不会自动执行 MCP 的 XSD、引用及保存保护，按 Python 指南显式验证。

## 校验与写回

1. 用 `validate_project` 检查结果，区分错误与已有外部引用警告。XSD 通过不能替代 AUTOSAR 业务规则或目标工具验证。
2. 用 `preview_changes` 查看影响文件和差异；完整检查分页，`continuation=true` 是上一差异行的延续。
3. 若用户已授权修改并保存，使用最新预览的 `preview_token` 调用 `save_changes`，无需重复确认。若只要求分析或预览，保留内存结果，不写回。
4. 根据工具返回值报告保存是否成功及备份路径。`rename_node` / `patch_xml` 成功只表示修改会话，不能报告为已经保存。
5. 使用 `close_project` 结束不再需要的会话。未保存且需保留的修改不能通过 `discard_changes=true` 静默丢弃。

发现 `FILE_CONFLICT` 或 `RECOVERY_REQUIRED` 时停止保存，不通过改凭据、直接覆盖文件或反复重试绕过。按操作指南保留结果、核对恢复状态并处理冲突。

## 结果表达

说明修改了哪些文件和对象、同步了多少引用、哪些校验实际执行、是否保存以及备份位置。引用结论注明“仅覆盖已加载文件”；只加载部分工程时，不宣称整个工程没有悬空引用。

## 扩充知识库

将新的专题知识写到 `references/`，并在上面的“按需读取”中加入具体触发条件。专题应写明平台和适用版本、依据来源、会改变编辑决策的规则及一个必要示例。区分标准规则、项目命名约定和工具限制；版本相关结论以目标版本的规范、本地 XSD 和实际文件为准。
