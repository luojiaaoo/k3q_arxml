---
name: k3q-arxml
description: 使用 k3q-arxml 处理 AUTOSAR ARXML 文件——涵盖 MCP 工具用法（工程会话、节点查询、重命名、patch、校验、预览保存）与直接调用 k3q_arxml Python 包批量处理 ARXML 的脚本写法。当用户要读取、查询、修改、校验、批量处理 .arxml 文件，配置 k3q-arxml MCP，或询问 AUTOSAR schema/绑定类型相关问题时使用。
---

# k3q-arxml 技能

k3q-arxml 提供两条互补的 ARXML 处理路径，先判断任务形态再选路：

1. **MCP 交互式处理**——单文件或少量文件的查询、定位、修改、校验、预览保存。走 MCP 工具，全程留有 revision 与预览凭据，适合在对话中逐步操作。
2. **Python 脚本批量处理**——同类修改施加到大量对象/文件（批量重命名、加前后缀、同步引用、按规则迁移）。直接调用 `k3q_arxml` 包写脚本一次跑完，不要用 MCP 工具循环调用几百次。

操作 ARXML 前先阅读对应参考文档，不要凭猜测构造 XML 或路径：

| 场景 | 阅读 |
| --- | --- |
| 配置 / 启动 MCP、使用 MCP 工具 | [references/mcp-usage.md](references/mcp-usage.md) |
| 写脚本批量处理 ARXML | [references/scripting.md](references/scripting.md) |
| AUTOSAR 领域知识（概念、建模惯例） | [references/autosar-domain.md](references/autosar-domain.md) |

若当前环境已接入 k3q-arxml MCP 但未加载本技能，先调用 `get_skill_path` 获取手册目录，再读取其中的 `SKILL.md` 与 `references/`。

## 通用规则

- **版本先行**：看文件头 `xsi:schemaLocation` 中的 XSD 文件名定版本，如 `AUTOSAR_00044.xsd` → 绑定 `autosar_00044`、MCP 命令 `k3q-arxml-mcp-00044`；`AUTOSAR_4-2-2.xsd` → `autosar_4_2_2` / `k3q-arxml-mcp-4-2-2`。版本不符只告警不阻断，但类型字段可能对不上，尽量匹配。
- **路径即元组**：AUTOSAR 路径 `/Package/Type` 与元组 `('Package', 'Type')` 用 `str2ref` / `ref2str` 互转。只支持绝对路径引用，不支持相对引用。
- **重命名必须同步引用**：改 SHORT-NAME 后，所有指向旧路径的引用都要改。MCP 的 `rename_node` 自动同步已加载文件；脚本里用 `ref_to_ref` 收集后逐个改。
- **先预览后落盘**：MCP 保存前必须 `preview_changes` 拿 `preview_token`；脚本里确认无误再 `flush_to_file()`。破坏性批量操作前先备份或在副本上试跑。
- **引用检查范围有限**：反向引用索引只覆盖已加载文件 / 已解析的文件集合。跨工程引用不会被发现，重要重命名前自行确认还有哪些外部文件可能引用。

## MCP 快速入口

Windows 下 MCP 必须经 `cmd /c` 启动，且 k3q-arxml 要预先装进**持久化的 Python 环境**（系统环境或项目 `.venv` 均可；项目 venv 用 `uv run` 调起命令）：本库体积较大，`uvx`、`uv run --with` 等临时环境语法容易导致 MCP 启动超时，必须预先安装。

```json
{
  "mcpServers": {
    "k3q-arxml-00044": {
      "command": "cmd",
      "args": ["/c", "k3q-arxml-mcp-00044"],
      "env": { "PYTHONUTF8": "1" }
    }
  }
}
```

典型工作流：`open_project` 加载文件集合 → `find_nodes` / `get_node` / `find_references` 查询定位 → `rename_node` 或 `patch_xml` 修改（带最新 revision）→ `validate_project` 校验 → `preview_changes` 预览 → `save_changes` 保存 → `close_project` 关闭。详见 [references/mcp-usage.md](references/mcp-usage.md)。

## 脚本批量处理快速入口

```python
from pathlib import Path
from k3q_arxml import ArxmlTransaction, IOArxml
from k3q_arxml.schemas.schame import autosar_4_2_2 as autosar

io = IOArxml(filepaths=list(Path('.').glob('**/*.arxml')), binding=autosar)
for node in io.ar(clazz=autosar.ApplicationPrimitiveDataType):
    rows = io.ref_to_ref(node.ref)
    with ArxmlTransaction() as transaction:
        node.xml_obj.short_name.value += '_Suffix'
        transaction.add(node.xml_obj)
        for row in rows:
            row.xml_obj.value += '_Suffix'
            transaction.add(row.xml_obj)
io.flush_to_file()
```

完整 API 与模式见 [references/scripting.md](references/scripting.md)；可运行示例在仓库 `demo/` 目录。
