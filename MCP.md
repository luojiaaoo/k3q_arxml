# ARXML MCP 使用说明

本项目通过本地 stdio MCP 提供 ARXML 查询、编辑、校验和保存工具。安装、启动及客户端配置见 [README](README.md#通过-mcp-供大模型使用)。

## 操作前置条件

服务启动时载入当前绑定，之后版本固定。用户启动前的环境准备见 [技能说明](skills/arxml-mcp/SKILL.md#用户启动前准备)。文件声明版本与绑定不匹配时，返回 `SCHEMA_MISMATCH` 告警并继续尝试解析；解析成功后可以正常查询。`project_info` 的 `schema_version` 为当前绑定版本，告警信息同时列出文件声明版本。

版本告警会保留在工程信息、校验和差异预览中，本身不阻止编辑或保存。实际绑定无法识别的内容、XSD 错误及其他校验错误仍按原规则处理；保存保留文件原有的 schema 声明。不能仅凭 `4.2.2`、`00044` 等版本标签的形式推断高低或兼容性。

服务以进程启动目录作为文件访问范围，包含其子目录。相对文件路径以此目录为基准，不接受范围外的文件；客户端通过 `cwd` 指定业务模型目录。

## 智能体技能

面向编程智能体的操作技能位于 [`skills/arxml-mcp/SKILL.md`](skills/arxml-mcp/SKILL.md)，附带按需读取的操作指南和 AUTOSAR 基础知识。可以显式要求智能体读取该入口，或将整个 `skills/arxml-mcp/` 目录复制到所用智能体支持的技能目录；MCP 连接仍需单独配置。后续领域知识可继续添加到该技能的 `references/`，并在入口中注明适用任务。

## 工具与操作流程

| 工具 | 用途 |
| --- | --- |
| `open_project` | 加载明确指定的文件集合，获取 `project_id`、`file_id` 和 `revision` |
| `project_info` | 查看工程状态及未保存文件 |
| `find_nodes` | 按 XML 标签、名称子串、路径前缀和文件查询具名节点 |
| `get_node` | 读取摘要或分页 XML，也可以读取节点内一个 XPath 对应的元素 |
| `find_references` | 查询入向引用，返回来源节点和相对 XPath |
| `describe_type` | 查看当前绑定中 XML 标签的字段、枚举及 compound choices |
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

## 局部 XML 修改

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

## 校验、备份与恢复

引用同步和校验只覆盖明确加载的文件。已有未解析引用作为警告保留；编辑新增的悬空引用、重复路径或可检查的 DEST 类型错误会阻止修改。能由当前绑定表示但未通过 XSD 的输入允许加载查询，受影响文件必须修复到通过 XSD 后才能发布修改和保存。XSD 校验不覆盖全部 AUTOSAR 业务规则。

保存前会检查所有已加载文件是否在外部修改，并再次校验。原始文件备份位于同目录，名称类似 `.types.arxml.k3q-<唯一ID>.bak`；返回结果包含完整路径。工作目录下的 `.k3q-mcp-recovery-<唯一ID>.json` 记录文件路径、备份路径、前后 SHA-256 及状态。成功保存后状态为 `complete`，普通写入失败且恢复成功时为 `rolled_back`。

每个文件通过同目录原子替换保存；多文件保存不具备系统级原子性。进程中断或恢复失败留下 `pending` / `rollback_failed` 清单时，服务会阻止打开工程、继续编辑或保存。恢复步骤：

1. 停止所有可能写入这些文件的程序，读取清单中的文件与备份路径。
2. 比较当前文件与清单的 `old_sha256` / `new_sha256`；若两者均不匹配，先保留外部改动，不直接覆盖。
3. 对照 `old_sha256` 核对备份，将需要恢复的文件恢复为备份内容，并再次核对哈希。
4. 全部文件恢复完成后，将清单 `status` 改为 `rolled_back`，再重新打开工程。

服务不会自动推断用户已确认保存；确认交互由模型客户端负责。关闭服务会丢失尚未保存的内存修改。

安装 MCP 可选依赖后执行完整回归（包含真实 stdio 客户端测试）：

```console
uv run --extra mcp pytest -v
```
