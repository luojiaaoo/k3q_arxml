<p align="center">
	<img alt="logo" src="logo.png" style="width: 128px; height: 128px;">
</p>
<h1 align="center" style="margin: 30px 0 30px; font-weight: bold;">k3q_arxml</h1>
<p align="center">
    <a href="https://gitee.com/luojiaaoo/k3q_arxml"><img src="https://gitee.com/luojiaaoo/k3q_arxml/badge/star.svg?theme=dark"></a>
    <a href="https://github.com/luojiaaoo/k3q_arxml"><img src="https://img.shields.io/github/stars/luojiaaoo/k3q_arxml?style=social"></a>
    <img src="https://img.shields.io/badge/license-Apache%20License%202.0-blue.svg">
    <img src="https://img.shields.io/badge/python-=3.11-blue">
</p>

读取与编辑 AUTOSAR ARXML 文件的轻量 Python 库，附带按 AUTOSAR 版本拆分的 MCP 服务，可接入 Claude Code 等智能体直接查询、修改、校验 ARXML。

- **Python 包 `k3q_arxml`**：加载一个或多个 ARXML，建立对象 / 反向引用 / UUID 索引，支持增量编辑与回写。
- **多版本绑定**：内置 `00043` ~ `00052` 与 `4.2.2` 共 11 个 AUTOSAR schema 版本的预生成 Python 绑定，按需导入，互不干扰。
- **MCP 服务**：按版本提供 `k3q-arxml-mcp-<版本>` 命令，14 个工具覆盖工程加载、节点查询、类型查询、重命名、XML 补丁、校验、差异预览与保存。

## 安装

要求 Python 3.11+。使用 MCP 前须先把本库装进持久化环境（环境要求见 [MCP 配置](#mcp-配置)）。

从 PyPI 安装：

```bash
python -m pip install k3q-arxml
```

升级到最新版本：

```bash
python -m pip install --upgrade k3q-arxml
```

查看当前版本：

```bash
python -m pip show k3q-arxml
```

从源码安装（仅开发需要）：

```bash
python -m pip install .
```

安装后系统 Python 的 Scripts 目录会生成 `k3q-arxml-mcp-<版本>` 命令，例如 `k3q-arxml-mcp-00044`。验证安装：

```bash
python -c "import k3q_arxml; print(k3q_arxml.__file__)"
k3q-arxml-mcp-00044 --help
```

开发环境使用 uv 管理：

```bash
uv sync
uv run pytest
```

## Python 包用法

### 1. 选择版本绑定

ARXML 的类型定义按 AUTOSAR 版本拆分在 `k3q_arxml.schemas.autosar_<版本>` 模块中。查看文件头 `xsi:schemaLocation` 中的 XSD 文件名确定版本，例如 `AUTOSAR_00044.xsd` 对应 `autosar_00044`：

```python
from k3q_arxml.schemas import autosar_00044 as autosar  # AUTOSAR_00044.xsd
# from k3q_arxml.schemas import autosar_4_2_2 as autosar  # AUTOSAR_4-2-2.xsd
```

可用版本与命令对照：

| schema 版本 | 绑定模块 | MCP 命令 |
| --- | --- | --- |
| 00043 ~ 00052 | `autosar_00043` ~ `autosar_00052` | `k3q-arxml-mcp-00043` ~ `k3q-arxml-mcp-00052` |
| 4.2.2 | `autosar_4_2_2` | `k3q-arxml-mcp-4-2-2` |

### 2. 加载文件

`IOArxml` 管理一组文件，跨文件汇总查询结果；`ArxmlFile` 负责单文件的加载、索引与回写：

```python
from pathlib import Path
from k3q_arxml import IOArxml

io = IOArxml(filepaths=[Path('SWC.arxml'), Path('Types.arxml')], binding=autosar)

# 运行中追加文件（拒绝重复文件及跨文件重复对象路径）
io.append(Path('More.arxml'))
```

约束：同一路径元组（SHORT-NAME 链）不能在多个文件中重复出现；引用必须是绝对路径（`/Package/Type`），不支持相对引用。

### 3. 查询

路径用元组表示，`('Package', 'Type')` 对应 `/Package/Type`，用 `str2ref` / `ref2str` 互转：

```python
from k3q_arxml import str2ref, ref2str

node = io.ref(('Types', 'Speed'))          # 按完整路径查唯一对象，不存在返回 None
nodes = io.ar(clazz=autosar.SwBaseType)    # 按类型查对象（含子类），可加路径前缀过滤
rows = io.ref_to_ref(('Types', 'Speed'))   # 查指向该路径的所有引用节点
```

查询结果是包装节点：

- `ArxmlNamedNode`：`.ref` 路径元组、`.short_name` 名称、`.xml_obj` 实际 XML 对象、`.content` 按需序列化出的 XML 文本。
- `ArxmlRefNode`：`.xml_obj.value` 引用目标路径、`.set_dest(ref)` 改写引用、`.owner_ref` 包含该引用的最近具名对象。

### 4. 编辑

直接修改 `.xml_obj` 上的字段，然后通过 `edited()` 刷新索引；批量修改用 `ArxmlTransaction` 延迟统一刷新：

```python
from k3q_arxml import ArxmlTransaction

node = io.ref(('Types', 'Speed'))
rows = io.ref_to_ref(node.ref)
with ArxmlTransaction() as transaction:
    node.xml_obj.short_name.value = 'Velocity'   # 改 SHORT-NAME
    transaction.add(node.xml_obj)
    for row in rows:                             # 同步所有入向引用
        row.set_dest(('Types', 'Velocity'))
        transaction.add(row.xml_obj)
```

要点：

- 解析出的每个 XML 对象都注入了 `arxml_parent`（父节点）与 `edited()`（标记修改并增量刷新最近具名祖先的索引）。
- `ArxmlTransaction.add(xml_obj)` 只登记一次、退出上下文时统一调用 `edited()`；不回滚、不自动保存。
- 增删、移动子节点后，对改动所在的具名节点调用 `file.update_node(node)` 增量重建该子树的索引。
- 重命名时库只改对象本身，**指向它的引用要自己同步**（`ref_to_ref` + `set_dest`，如上例）。

### 5. 保存

```python
io.flush_to_file()   # 只回写标记为已修改的文件
```

单文件场景用 `ArxmlFile`：`ArxmlFile(binding=autosar).parse_file(path)` 加载已有文件，`parse_autosar(path, root_obj)` 从内存对象初始化新文件，`render()` 预览序列化结果，`save()` 写盘。回写保留原缩进与根节点前注释。

### 6. 批量处理示例

完整的批量脚本见 [demo/](demo/)：`chg_adt_name.py` 按接口列表批量给 ADT 加/去后缀并同步引用，`chg_adt_idt_name.py` 批量为 ADT/IDT 加前缀。典型骨架：

```python
from pathlib import Path
from k3q_arxml import ArxmlTransaction, IOArxml
from k3q_arxml.schemas import autosar_4_2_2 as autosar

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

批量场景的详细写法（多文件同步、事务、索引更新时机）见技能文档 [k3q_arxml/assets/skills/k3q-arxml/references/scripting.md](k3q_arxml/assets/skills/k3q-arxml/references/scripting.md)。

## MCP 配置

### 前提

1. **使用持久化的 Python 环境**：系统级 Python 或项目的 `.venv` 均可，但必须预先建好环境并安装本库——MCP 由智能体客户端独立拉起进程。用项目 venv 时通过 `uv run` 调起命令（如 `["/c", "uv", "run", "k3q-arxml-mcp-00044"]`）。本库内置 11 个版本的完整 schema 绑定，包体积较大，**不要用 `uvx`、`uv run --with` 这类临时环境语法启动**——每次拉起都要现场解析安装，很容易导致 MCP 启动超时。
2. **启动 MCP 之前先安装本库**：`python -m pip install k3q-arxml`，确认 `k3q-arxml-mcp-<版本>` 命令可用。
3. 按 ARXML 的 schema 版本选择命令；文件头 `xsi:schemaLocation="... AUTOSAR_00044.xsd"` → `k3q-arxml-mcp-00044`。

### Windows 启动方式

**Windows 上必须通过 `cmd /c` 启动**，由 cmd 解析 Scripts 目录下的命令：

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

写入 Claude Code 项目级 `.mcp.json`（或 `claude_desktop_config.json`）即可。注意事项：

- `command` 固定为 `cmd`，把实际命令放进 `args` 的 `/c` 之后，**不要**直接把 `k3q-arxml-mcp-00044` 写成 `command`。
- 命令不在 PATH 时写全路径：`["/c", "C:\\Python311\\Scripts\\k3q-arxml-mcp-00044"]`。
- 建议设置 `PYTHONUTF8=1`，避免中文路径/日志在 Windows 下乱码。
- **MCP 的工作目录 = 服务启动目录**。`open_project` 只能加载该目录及其子目录内的 ARXML 文件，路径之外的文件会被拒绝。请在存放 arxml 的工程目录下启动客户端，或按客户端能力指定 `cwd`。
- 需要多个版本时并列配置多个 server，名称区分即可，例如 `k3q-arxml-00044`、`k3q-arxml-4-2-2`。

Linux / macOS 直接调用命令：

```json
{
  "mcpServers": {
    "k3q-arxml-00044": {
      "command": "k3q-arxml-mcp-00044"
    }
  }
}
```

### MCP 工具一览

| 工具 | 作用 |
| --- | --- |
| `get_skill_path` | 返回内置使用手册（`k3q_arxml/assets/skills/k3q-arxml`）目录，操作 ARXML 前优先阅读 |
| `open_project` | 加载指定的 ARXML 文件集合，建立工程会话 |
| `project_info` | 查看工程 revision、文件清单、未保存状态、加载诊断 |
| `find_nodes` | 按 XML 标签 / 名称子串 / 路径前缀查找具名节点 |
| `get_node` | 读取节点摘要与 XML（可分页、可 XPath 限定） |
| `find_references` | 查找指向某路径的入向引用 |
| `describe_type` | 查询 XML 标签的字段、枚举、compound choices |
| `get_type_source` | 查询当前版本 XSD 或 Python 绑定源码片段 |
| `rename_node` | 重命名 SHORT-NAME 并同步已加载文件中的引用 |
| `patch_xml` | 对节点原子提交一批 XML 操作（set_text / append / replace / delete …） |
| `validate_project` | 校验 XSD、重复路径、引用目标与 DEST |
| `preview_changes` | 分页查看未保存差异，返回保存凭据 `preview_token` |
| `save_changes` | 凭 `preview_token` 显式写盘（保留备份与恢复清单） |
| `close_project` | 关闭会话，可选丢弃未保存修改 |

约定：所有编辑工具都要带最新的 `revision`（查询结果里返回）；保存前必须先 `preview_changes` 拿到 `preview_token`；引用检查仅覆盖已加载文件。详细工作流见技能文档。

## Skills

仓库自带智能体技能 [k3q_arxml/assets/skills/k3q-arxml/](k3q_arxml/assets/skills/k3q-arxml/)，内容包括 MCP 用法、批量脚本写法以及 AUTOSAR 领域知识（持续补充）。MCP 服务的 `get_skill_path` 工具会返回该目录，供智能体按需阅读。

可把 `k3q_arxml/assets/skills/k3q-arxml` 复制到智能体的 skills 目录（如 `~/.claude/skills/`）自动加载，也可直接让智能体经 `get_skill_path` 读取。

## 开发

```bash
uv sync                # 安装开发依赖
uv run pytest          # 运行测试
uv run ruff check .    # 静态检查
```

新增 schema 版本时把 XSD 放入 `k3q_arxml/assets/xsd/autosar_<版本>/`，运行 `python k3q_arxml/cli.py --versions <版本>` 重新生成绑定（内部工具，需 xsdata）。

维护者打包与 PyPI 发布流程见 [RELEASING.md](RELEASING.md)。

## License

Apache-2.0
