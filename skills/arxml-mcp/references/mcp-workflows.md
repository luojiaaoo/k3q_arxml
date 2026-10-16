# MCP 操作指南

适用于本仓库当前 stdio MCP。工具名省略客户端前缀；实际输入输出以工具发现返回的 schema 为准。错误响应的 `isError=true` 表示失败，业务错误说明位于文本内容中的 JSON，包含 `code`、`message` 和 `suggestion`。

以下流程使用已启动的 MCP 服务，版本在服务启动时固定，文件范围为服务启动目录及其子目录。用户启动前的命令行准备见 SKILL.md；AI 不在文件操作过程中管理版本或重启服务。

## 身份、范围和读取

| 值 | 含义 | 使用方式 |
| --- | --- | --- |
| `project_id` | 一次加载得到的工程会话 | 所有工程查询及编辑都显式传入 |
| `file_id` | 会话内的一个文件 | 文件根 `/` 必填；其他场景可用于限定文件 |
| `ref` | 由各级 SHORT-NAME 组成的对象路径 | 如 `/Types/Speed`，不是磁盘路径或 XML XPath |
| `revision` | 当前会话修订号 | 编辑必须与当前值一致，使用工具实际返回值 |
| `preview_token` | 当前修订的预览凭据 | 后续编辑及成功保存都会使旧凭据失效，不代表用户授权 |

`find_nodes(name=...)` 是名称子串匹配，`ref_prefix` 按路径段匹配。`find_references` 返回每处入向引用，不合并同一来源的多次引用；返回的 `xpath` 相对于 `owner_ref`。

列表默认每页 50 项，最多 200 项，用 `offset` 继续。XML 默认每段 16,000 字符，用 `xml_offset` / `xml_limit` 继续。差异每项最多 2,000 字符，长行的后续片段带 `continuation=true`。`next_offset=null` 才表示读取结束。

预览默认 `diff_mode="file"`，包含将写入磁盘的全部差异。差异中混有大量数值或格式规范化变化时，可先用 `diff_mode="model"` 查看本次对象修改，再阅读 file 视图；`serialization_changed_files` 列出存在原文序列化差异的受影响文件。切换视图后重新从 `offset=0` 开始；同一视图分页保持 `diff_mode` 不变，凭据仍绑定当前 revision。恢复加载时或最近保存后的对象内容后，该文件自动清除 dirty，不再出现在预览和保存列表中。

## 重命名及跨文件同步

任务示例：将 `/Types/Speed` 改名为 `Velocity`，同步接口文件中的引用。

1. `open_project(filepaths=["types.arxml", "interfaces.arxml"])`，保留返回的会话、文件标识及修订号。
2. `get_node` 检查目标；`find_references` 阅读入向引用及来源。
3. 使用实际会话 ID 和最新修订号提交以下参数给 `rename_node`：

```json
{
  "project_id": "当前会话 ID",
  "ref": "/Types/Speed",
  "new_name": "Velocity",
  "revision": 0
}
```

4. 用返回的 `new_ref` 重新读取节点，检查新目标的引用及 `updated_references`。
5. 校验、预览；在保存授权范围内使用新凭据显式保存。

示例修订号 `0` 仅说明参数形式，必须替换为当前值。包重命名同样使用这个工具，它会更新后代对象路径和指向这些对象的已加载引用。该工具不负责重命名 LONG-NAME、符号字符串或未加载文件中的文本。

## 局部 XML 编辑

XPath 相对于指定的具名节点，`.` 表示该节点。AUTOSAR 元素使用 `ar:` 前缀，例如 `./ar:CATEGORY`。每项操作必须匹配一个元素；使用位置谓词或 SHORT-NAME 文本谓词消除歧义。当前服务不支持 XPath 函数、轴、变量、绝对路径和返回属性或文本的选择器。

也支持 `[@UUID='值']` 属性谓词。包内类型需经过 ELEMENTS 层，例如 `./ar:ELEMENTS/ar:SW-BASE-TYPE[@UUID='test-create-001']`；不能将漏层导致的零匹配判断为不支持属性谓词。`find_nodes` 的 `xml_tag` 是精确匹配，不确定完整标签时先省略此条件查询。

修改 `/Types/Velocity` 的 UUID，可给 `patch_xml` 传入：

```json
{
  "project_id": "当前会话 ID",
  "ref": "/Types/Velocity",
  "revision": 1,
  "operations": [
    {
      "op": "set_attribute",
      "xpath": ".",
      "attribute": "UUID",
      "value": "DCE:12345678-1234-1234-1234-123456789abc"
    }
  ]
}
```

修改引用目标时，先读取目标和引用角色。使用 `find_references` 返回的 `owner_ref`、`file_id` 和相对 `xpath` 定位引用，通过 `set_text` 设置目标绝对路径；需要改 DEST 时确认该角色允许的枚举并在同批操作中修改。

| 操作 | 需要的附加参数 | 约束 |
| --- | --- | --- |
| `set_text` | `value` | 仅作用于不含子元素的节点；不能改现有 SHORT-NAME |
| `set_attribute` | `attribute`、`value` | 选择元素，单独指定属性名，如 UUID 或 DEST |
| `remove_attribute` | `attribute` | 属性必须存在 |
| `append` | `xml` | 添加到所选父元素的末尾，先确认顺序合法 |
| `insert_before` / `insert_after` | `xml` | 在所选子元素前后插入 |
| `replace` | `xml` | 保持被替换范围内具名节点的路径集合 |
| `delete` | 无 | 删除所选子元素，不能删除当前编辑根本身 |

结构操作中的 `xml` 是一个带 AUTOSAR 命名空间的完整元素，例如：

```json
{
  "op": "append",
  "xpath": "./ar:ELEMENTS",
  "xml": "<APPLICATION-PRIMITIVE-DATA-TYPE xmlns=\"http://autosar.org/schema/r4.0\"><SHORT-NAME>AddedType</SHORT-NAME><CATEGORY>VALUE</CATEGORY></APPLICATION-PRIMITIVE-DATA-TYPE>"
}
```

这只是新增节点的操作参数，调用时还需提供外层 `project_id`、`ref` 和 `revision`。示例表示将一个 ADT 添加到包含 ELEMENTS 的包中，不表示适用于所有父节点。

同批操作按顺序执行，后续位置谓词依据前面操作后的树定位。针对具名节点本身的删除、替换或前后插入，应选择它的具名祖先作为 `ref`；顶层包用 `ref="/"` 并提供 `file_id`。

原子性仅覆盖单次编辑调用；`patch_xml` 只修改一个文件内选定的子树，不提供任意跨文件批处理。删定义前先将外部引用改到合法目标或按用户意图删除引用所在结构；最后一次删除仍有入向引用时会失败。没有合法的分步修改路径时，说明当前接口边界，不临时引入悬空引用绕过校验。

## 错误处理与保存恢复

| 错误码 | 下一步 |
| --- | --- |
| `NODE_NOT_FOUND` / `FILE_NOT_FOUND` | 重新查询当前会话；检查新路径及 file_id |
| `STALE_REVISION` | 读取最新状态与节点，重新判断原修改是否仍适用，再提交 |
| `STALE_PREVIEW` | 重新预览当前修改，再使用返回的新凭据 |
| `XPATH_MATCH_COUNT` / `INVALID_XPATH` | 阅读 XML，收窄选择器；不盲目调整位置数字 |
| `RENAME_REQUIRED` | 改用 `rename_node`，结构增删按独立操作表达 |
| `BINDING_ERROR` / `LOSSY_ROUND_TRIP` / `VALIDATION_FAILED` | 核对具体字段、类型、枚举、元素顺序及引用，不削弱校验 |
| `SCHEMA_MISMATCH` | `diagnostics` 中 severity 为 warning 时，报告两个版本并继续操作；若工具返回 `isError=true`，则核对缺失的根节点、命名空间或 schema 声明 |
| `FILE_CONFLICT` | 停止写回；保留需要的会话 XML 和差异，重新加载并合并外部改动 |
| `SAVE_FAILED` | 核对返回的恢复清单状态；确认已恢复后，修复写入条件，再预览和保存 |
| `RECOVERY_REQUIRED` | 停止写操作，核对备份及清单，不仅修改 status 就重新尝试 |

编辑工具在候选对象上执行，失败不会发布到当前会话。保存涉及磁盘，不能套用同一结论：普通失败会尝试恢复，但恢复失败时需要人工处理。

保存成功返回每个文件的 `backup_path` 和恢复清单路径。清单 `complete` 表示保存完成，`rolled_back` 表示已恢复原内容。多文件保存采用逐文件原子替换，不具备系统级事务原子性。

清单为 `pending` / `rollback_failed` 时，先停止写操作，再按以下步骤恢复：

1. 停止可能写入相关文件的程序，读取清单中的文件、备份路径及 `old_sha256` / `new_sha256`。
2. 比较当前文件的 SHA-256；若与两个记录值均不相同，先保留外部改动，不直接覆盖。
3. 核对备份哈希等于 `old_sha256`，将需要恢复的文件恢复为备份内容，并再次核对。
4. 全部文件确认恢复后，将清单 `status` 改为 `rolled_back`，再重新打开工程；不能只修改状态绕过恢复。
