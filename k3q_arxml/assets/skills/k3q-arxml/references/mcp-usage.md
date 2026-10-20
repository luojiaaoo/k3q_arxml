# MCP 用法（k3q-arxml-mcp）

k3q-arxml 的 MCP 服务按 AUTOSAR 版本拆分，一个命令绑定一个 schema 版本，通过 stdio 与智能体客户端通信。

约定：工作目录 = 服务启动目录，`open_project` 只能加载该目录及子目录内的 arxml，外部路径一律拒绝（`OUTSIDE_WORKSPACE`）。

## 工具清单（14 个）

| 工具 | 类型 | 作用 |
| --- | --- | --- |
| `get_skill_path` | 只读 | 返回内置手册（assets/skills/k3q-arxml）目录，无需工程会话 |
| `open_project` | 会话 | 加载明确指定的 ARXML 文件集合，返回 project_id 与 revision |
| `project_info` | 只读 | 工程 revision、文件清单、未保存状态、加载诊断 |
| `find_nodes` | 只读 | 按 XML 标签 / 名称子串 / 路径前缀查找具名节点（分页） |
| `get_node` | 只读 | 节点摘要；`include_xml=true` 分页返回 XML；`xpath` 限定子元素 |
| `find_references` | 只读 | 查找指向某路径的入向引用（分页） |
| `describe_type` | 只读 | 查询 XML 标签的字段、枚举、compound choices，无需会话 |
| `get_type_source` | 只读 | 查询当前版本 XSD 或 Python 绑定源码片段，无需会话 |
| `rename_node` | 编辑 | 重命名 SHORT-NAME 并同步已加载文件中的引用 |
| `patch_xml` | 编辑 | 对节点原子提交一批 XML 操作 |
| `validate_project` | 只读 | XSD、重复路径、已加载引用目标及 DEST 校验 |
| `preview_changes` | 只读 | 分页查看未保存差异，返回保存凭据 preview_token |
| `save_changes` | 写盘 | 凭 preview_token 显式写回（保留备份与恢复清单） |
| `close_project` | 会话 | 关闭会话，可选丢弃未保存修改 |

## 身份与分页

| 值 | 含义 | 使用方式 |
| --- | --- | --- |
| `project_id` | 一次加载得到的工程会话 | 所有工程查询及编辑都显式传入 |
| `file_id` | 会话内的一个文件 | 文件根 `/` 必填；其他场景可用于限定文件 |
| `ref` | 由各级 SHORT-NAME 组成的对象路径 | 如 `/Types/Speed`，不是磁盘路径或 XML XPath |
| `revision` | 当前会话修订号 | 编辑必须与当前值一致，用工具实际返回值 |
| `preview_token` | 当前修订的预览凭据 | 后续编辑及成功保存都会使旧凭据失效；不代表用户保存授权 |

分页规则：

- 列表（节点、引用、差异条目）默认每页 50 项，最多 200 项，用 `offset` 继续。
- XML 默认每段 16,000 字符，用 `xml_offset` / `xml_limit` 继续。
- 差异中的超长行拆成最多 2,000 字符片段，`continuation=true` 表示上一差异行的延续。
- `next_offset=null` 才表示读取结束；不要把截断片段当成完整内容。

`find_references` 返回每处入向引用，不合并同一来源的多次引用；返回的 `xpath` 相对于 `owner_ref`。

## 标准工作流

```
open_project → 查询定位 → 编辑（带 revision）→ validate_project
            → preview_changes → save_changes → close_project
```

1. **open_project**：传需要一起查询及同步引用的文件路径数组（相对路径以工作目录为基准）。返回 `project_id`、`revision`、各文件 `file_id`、加载诊断。版本不匹配仅告警。路径校验复用核心层规则：只有 schema 定义的叶子具名类型，其完整 SHORT-NAME 路径不允许重复，同文件和跨文件均检查。叶子根据当前版本绑定的字段类型（含可选字段、无名包装和 choices）判定，与实例是否包含子节点无关；包等可以包含具名后代的中间类型允许重复，包括空实例。
2. **查询定位**：
   - `find_nodes(xml_tag, name, ref_prefix)`——`xml_tag` 必须使用精确的全大写 XML 标签（如 `CAN-FRAME`，不能写成 `CAN-Frame` 或 `can-frame`；不是 Python 类名，不能用片段匹配）。含任何小写字母直接报 `XML_TAG_CASE_MISMATCH`，不自动转换大小写，也不依赖查询范围内是否存在该类型。`describe_type` 的 `xml_tag` 遵循同一规则；不确定标签时省略 `find_nodes` 的 `xml_tag` 先按 `name` 子串查。
     `ref_prefix` 是由各级 `SHORT-NAME` 组成的路径前缀，匹配自身及所有后代，允许末尾 `/`。例如 `find_nodes(project_id, xml_tag="CAN-FRAME", ref_prefix="/SystemWeaver/Frames")` 可直接找到包内的帧。默认 `/` 表示不限制路径；省略 `file_id` 查询工程中全部已加载文件。
   - `get_node(ref, include_xml=true, xpath=...)`——读节点 XML；`xpath` 相对节点，`ar:` 前缀表示 AUTOSAR 命名空间。同路径节点存在于多个文件时，读取和编辑必须传 `file_id`，否则报 `AMBIGUOUS_NODE`；先用 `find_nodes` 获取各文件标识。
   - `find_references(ref)`——入向引用，每项带 `xpath`（相对 owner），可直接用于局部编辑。
3. **编辑**——两类工具，都必须带**最新 revision**（查询结果里返回；每次编辑成功后 revision 递增）：
   - `rename_node(ref, new_name, revision)`：`ref` 传旧路径，`new_name` 只传新 SHORT-NAME（字母开头，仅字母数字下划线）。自动同步已加载文件中指向它及后代的引用；共享中间节点通过 `file_id` 选择分支，仅迁移该分支，其他文件仍提供的路径及其引用保持原值。重命名后的中间节点允许与其他文件共享路径，但叶子路径仍须唯一。**不**改 LONG-NAME、符号字符串或未加载文件中的文本。**现有 SHORT-NAME 修改用它，不要用 patch_xml**。成功后用返回的 `new_ref` 回读节点并检查 `updated_references`：

     ```json
     {
       "project_id": "<open_project 返回>",
       "ref": "/Types/Speed",
       "new_name": "Velocity",
       "revision": 0
     }
     ```

     示例 `revision` 仅为参数形式，必须替换为当前值。
   - `patch_xml(ref, operations, revision)`：原子提交一批 XML 操作。`operations` 按顺序在候选树执行，整批成功才发布到会话；每项 `{op, xpath, value?, attribute?, xml?}`：

     | op | 说明 | 约束 |
     | --- | --- | --- |
     | `set_text` | 设置元素文本 | 仅作用于不含子元素的节点；不能改现有 SHORT-NAME |
     | `set_attribute` / `remove_attribute` | 设置/删除属性 | 单独指定属性名（如 UUID、DEST）；remove 时属性必须存在 |
     | `append` | 用 `xml` 片段追加到所选父元素末尾 | 先确认顺序合法 |
     | `insert_before` / `insert_after` | 在所选子元素前后插入 | — |
     | `replace` | 用 `xml` 替换所选元素 | 保持被替换范围内具名节点的路径集合 |
     | `delete` | 删除 xpath 命中元素 | 不能删除编辑根本身 |

     选择器与操作约束：

     - xpath 相对 `ref` 节点，`.` 表示节点自身；AUTOSAR 元素用 `ar:` 前缀（如 `./ar:CATEGORY`）。每项操作必须匹配一个元素，匹配数不为 1 时报 `XPATH_MATCH_COUNT`（含实际匹配数），用位置谓词或 SHORT-NAME 文本谓词消歧；不支持 XPath 函数、轴、变量、绝对路径。
     - 支持 `[@UUID='值']` 谓词；包内类型需经过 ELEMENTS 层（如 `./ar:ELEMENTS/ar:SW-BASE-TYPE[@UUID='…']`），漏层导致的零匹配不代表不支持谓词。
     - 文件根 `/` 需传 `file_id`；针对具名节点本身的删除、替换或前后插入，应选它的**具名祖先**作为 `ref`。
     - 改现有 SHORT-NAME 走 `rename_node`（否则报 `RENAME_REQUIRED`）；结构增删用 `delete` 与 `append` / `insert_*`。删除定义前先把入向引用改到合法目标，最后一次删除仍有已加载引用时整批失败。
     - 若修改的 XML 经绑定往返后发生元素/文本/属性/顺序变化，会以 `LOSSY_ROUND_TRIP` 拒绝。

     示例——修改节点 UUID：

     ```json
     {
       "project_id": "<会话 ID>",
       "ref": "/Types/Velocity",
       "revision": 1,
       "operations": [
         {"op": "set_attribute", "xpath": ".", "attribute": "UUID", "value": "DCE:12345678-1234-1234-1234-123456789abc"}
       ]
     }
     ```

     示例——向包的 ELEMENTS 末尾添加一个 ADT（`xml` 是带 AUTOSAR 命名空间的完整元素）：

     ```json
     {
       "op": "append",
       "xpath": "./ar:ELEMENTS",
       "xml": "<APPLICATION-PRIMITIVE-DATA-TYPE xmlns=\"http://autosar.org/schema/r4.0\"><SHORT-NAME>AddedType</SHORT-NAME><CATEGORY>VALUE</CATEGORY></APPLICATION-PRIMITIVE-DATA-TYPE>"
     }
     ```

     修改引用目标：用 `find_references` 返回的 `owner_ref`、`file_id` 和相对 `xpath` 定位，`set_text` 写目标绝对路径；需要改 DEST 时确认该角色允许的枚举并在同批操作中修改。
4. **validate_project**：XSD 校验、重复路径、已加载引用目标、DEST 匹配。既有外部引用只作警告，不阻塞。
5. **preview_changes**：`diff_mode='file'` 看磁盘原文到待保存内容的完整差异（保存前必须看这个），其中可能混有 `0` → `0.0` 等序列化规范化变化；`diff_mode='model'` 只看本次对象修改。`serialization_changed_files` 列出原文与加载时序列化结果存在差异的文件（这类差异不在 model 视图里）。切换视图后重新从 `offset=0` 开始；同一视图分页保持 `diff_mode` 不变，两视图共用当前 revision 的 `preview_token`。文件恢复到加载时或最近保存后的内容时，dirty 自动清除、不再出现在预览与保存列表（仍会递增 revision、作废旧凭据）。
6. **save_changes(preview_token)**：显式写盘，保留原文件备份与恢复清单（见「保存备份与恢复」）。外部文件被改动、预览过期、校验有 error 都会阻止保存。
7. **close_project**：有未保存修改时需 `discard_changes=true` 才丢弃。

## revision 与凭据规则

- 每个查询/编辑结果都带 `revision`；编辑请求的 `revision` 必须等于当前值，否则 `STALE_REVISION`，重新查询后再改。
- `preview_token` 在 `preview_changes` 时生成；改动后再次预览会刷新，保存只能用最新凭据，过期报 `STALE_PREVIEW`。
- 编辑失败不发布（不影响会话状态），修正参数后重试。

## 常见错误码

| code | 含义 | 处理 |
| --- | --- | --- |
| `OUTSIDE_WORKSPACE` | 路径不在服务启动目录内 | 把文件放进工程目录，或调整启动 cwd |
| `NODE_NOT_FOUND` / `FILE_NOT_FOUND` | 节点或文件不存在 | 用 `find_nodes` 确认当前路径与 `file_id` |
| `INVALID_REF` | 路径格式错误或混入 XML 标签、换行、控制字符 | 只传由各级 SHORT-NAME 组成的路径，如 `/SystemWeaver/Frames`；不要附加 `</ref_prefix>` 等标记 |
| `XML_TAG_CASE_MISMATCH` | `xml_tag` 含小写字母，查询前直接拒绝 | 按原始 XML 的精确拼写传全大写标签，如 `CAN-FRAME`；工具不自动转换大小写 |
| `STALE_REVISION` / `STALE_PREVIEW` | revision / preview_token 过期 | 重新查询 / 重新预览 |
| `DUPLICATE_PATH` | 叶子具名节点路径冲突或重命名后被占用 | 换名，或拆分文件集合 |
| `AMBIGUOUS_NODE` | 中间节点路径存在于多个文件 | 用 `find_nodes` 获取并传入 `file_id` |
| `INVALID_NAME` | SHORT-NAME 不符合 `^[A-Za-z][A-Za-z0-9_]*$` | 改名 |
| `XPATH_MATCH_COUNT` / `INVALID_XPATH` | 选择器非法或匹配数不为 1 | 读 XML 收窄选择器，不盲调位置数字 |
| `INVALID_OPERATION` | 操作参数不合法（如 `set_text` 作用于含子元素的节点、删/替编辑根本身） | 按 op 约束调整目标节点或改用其他操作 |
| `INVALID_NAMESPACE` | 新增 XML 片段未使用 AUTOSAR namespace | 在片段根标签声明 `xmlns="http://autosar.org/schema/r4.0"` |
| `RENAME_REQUIRED` | 试图用 patch_xml 修改现有 SHORT-NAME | 改用 `rename_node` |
| `BINDING_ERROR` / `VALIDATION_FAILED` | 绑定解析或校验失败 | 核对字段、类型、枚举、元素顺序及引用，不削弱校验 |
| `LOSSY_ROUND_TRIP` | 绑定无法无损保留该 XML | 用 `describe_type` / `get_type_source` 查类型约束后调整 |
| `SCHEMA_MISMATCH` | 文件声明版本与当前绑定不符 | warning 时报告两个版本并继续；`isError=true` 时核对根节点、命名空间或 schema 声明 |
| `XSD_ERROR` | 校验错误 | 看 diagnostics 的行号定位 |
| `UNRESOLVED_REFERENCE` / `DEST_MISMATCH` | 引用目标在已加载文件中不存在 / DEST 与目标标签不一致 | 既有问题只作警告；**新引入**的按 error 阻止编辑发布与保存 |
| `FILE_CONFLICT` | 保存前文件被外部改动 | 停止写回，重新加载并合并外部改动 |
| `SAVE_FAILED` | 写盘失败 | 核对恢复清单状态；确认已恢复后修复写入条件，再预览保存 |
| `RECOVERY_REQUIRED` | 存在未完成的恢复清单 | 停止写操作，按「保存备份与恢复」处理，不能只改 status 重试 |
| `UNSAVED_CHANGES` | `close_project` 时有未保存修改 | 先保存，或明确传 `discard_changes=true` 丢弃 |

## 保存备份与恢复

- 保存成功返回每个文件的 `backup_path` 与恢复清单路径。备份在原文件同目录，命名形如 `.types.arxml.k3q-<唯一ID>.bak`。
- 工作目录下的 `.k3q-mcp-recovery-<唯一ID>.json` 记录文件路径、备份路径、前后 SHA-256 及状态：`complete`（保存完成）、`rolled_back`（已恢复原内容）、`pending` / `rollback_failed`（恢复未完成）。
- 每个文件通过同目录原子替换写入；多文件保存逐文件进行，**不具备系统级事务原子性**。
- 存在 `pending` / `rollback_failed` 清单时，服务会阻止打开工程、继续编辑和保存。人工恢复步骤：
  1. 停止所有可能写入相关文件的程序，读取清单中的文件、备份路径及 `old_sha256` / `new_sha256`。
  2. 比较当前文件的 SHA-256；若与两个记录值都不相同，先保留外部改动，不直接覆盖。
  3. 核对备份哈希等于 `old_sha256`，把需要恢复的文件恢复为备份内容并再次核对。
  4. 全部文件确认恢复后，把清单 `status` 改为 `rolled_back`，再重新打开工程。不能只改 status 绕过恢复。

## 类型知识查询（无需工程会话）

1. `describe_type('APPLICATION-PRIMITIVE-DATA-TYPE')` → 字段列表（xml_name、kind、python_field、type_names、required、repeated、enum_values）。同名标签有多个绑定时从 `alternative_types` 选 `python_type` 再查，例如 `describe_type(xml_tag="TYPE-TREF", python_type="VariableDataPrototype.TypeTref")`；父标签字段的 `type_names` 可用来确定选择。
2. `get_type_source(name, source='xsd'|'binding')` → XSD 定义或 Python 绑定源码。`name` 可以是 XML 标签、XSD 定义名、Python 限定类型名（如 `VariableDataPrototype.TypeTref`）或上次返回的 `definition_id`，也可用 `complexType:SW-BASE-TYPE` 等形式限定定义种类：
   - 同名 XSD 可能同时存在 group、complexType 等定义：有歧义时不返回源码，返回 `candidates`（每页 50 项，用 `next_candidate_offset` 继续），选定 `definition_id` 作为下次 name。
   - `related_definitions` 列出关联定义（最多 200 项，完整数量见 `total_related_definitions`），按需继续查，不自动递归展开整个依赖树。
   - 嵌套 XML 标签（如 `TYPE-TREF`）的 XSD 查询返回包含声明的顶层定义，以保留 sequence / choice 上下文。
   - 源码默认每段 16,000 字符，`limit` 最多 32,000，用 `next_offset` 继续直到 null；`definition` 的 `filepath` / `line` 用于核对来源。
   - 找不到定义报 `SOURCE_NOT_FOUND`（换标签/定义名重查）；参数非法报 `INVALID_REQUEST`（`source` 只能是 `xsd`/`binding`，`name` 长度 1–512，`limit` 1–32,000）。

建议：写 patch 前先 `describe_type` 确认目标字段的 XML 名称与层级，避免 `LOSSY_ROUND_TRIP`；需要元素顺序、choice / sequence、出现次数时查 `get_type_source`，不要把 `describe_type` 的字段列表当插入顺序规则。
