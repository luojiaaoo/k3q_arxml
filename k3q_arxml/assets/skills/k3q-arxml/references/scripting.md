# 脚本批量处理 ARXML（直接调用 k3q_arxml）

批量同类修改（重命名、加前后缀、同步引用、按规则迁移）用 Python 脚本一次跑完，比用 MCP 工具循环调用更快也更可控。MCP 适合对话式单点操作，脚本适合可复现的批量任务。

## 环境

```bash
python -m pip install k3q-arxml
# 升级：python -m pip install --upgrade k3q-arxml
```

Python 3.11+。脚本用任意解释器运行，只要能 `import k3q_arxml`。

## 选择版本绑定

类型定义按 AUTOSAR 版本拆分在 `k3q_arxml.schemas.autosar_<版本>`。看文件头 `xsi:schemaLocation` 的 XSD 文件名定版本：

```python
from k3q_arxml.schemas import autosar_00044 as autosar   # AUTOSAR_00044.xsd
from k3q_arxml.schemas import autosar_4_2_2 as autosar   # AUTOSAR_4-2-2.xsd
```

可用：`autosar_00043` ~ `autosar_00052`、`autosar_4_2_2`。一个 `IOArxml` 只绑一个版本；混版本文件集分开处理。版本不匹配会告警但仍尝试解析，字段可能对不上，尽量匹配。

## 核心 API

### IOArxml —— 多文件管理

```python
from pathlib import Path
from k3q_arxml import IOArxml

io = IOArxml(filepaths=[Path('SWC.arxml'), Path('Types.arxml')], binding=autosar)
io.append(Path('More.arxml'))   # 运行中追加；拒绝重复文件与重复的 schema 叶子路径
io.flush_to_file()              # 只回写标记修改的文件
```

- `io.ref(('Types', 'Speed'))` —— 按完整路径查唯一对象；不存在返回 None；同路径出现在多个文件则抛异常。
- `io.ar(clazz, ref_prefix=())` —— 按 XML 对象类型（含子类）+ 路径前缀查对象列表。`clazz` 是绑定类，如 `autosar.SwBaseType`。
- `io.ref_to_ref(('Types', 'Speed'))` —— 跨文件查指向该路径的所有引用节点。
- `io.files` —— `dict[Path, ArxmlFile]`，可取单文件操作。

### ArxmlFile —— 单文件

```python
from k3q_arxml import ArxmlFile

file = ArxmlFile(binding=autosar).parse_file(Path('SWC.arxml'))      # 加载已有文件
file = ArxmlFile(binding=autosar).parse_autosar(Path('new.arxml'), root_obj)  # 从内存对象初始化新文件
file.render()        # 序列化为字符串，不写盘
file.save()          # 写盘（保留原缩进与根节点前注释）
file.update_node(node)  # 增量刷新某具名子树的索引（结构改动后）
```

### 节点包装

- `ArxmlNamedNode`（具名对象）：`.ref` 路径元组、`.short_name`、`.xml_obj` 实际 XML 对象、`.content` 按需序列化的 XML 文本。
- `ArxmlRefNode`（引用节点）：`.xml_obj.value` 引用目标路径、`.set_dest(ref_tuple)` 改写目标、`.owner_ref` 所属最近具名对象路径。

解析出的每个 XML 对象都注入两个属性：

- `arxml_parent` —— 父节点（根为 None）。
- `edited(refresh_index=True)` —— 标记修改并增量刷新最近具名祖先的索引；`refresh_index=False` 仅标记 dirty 不刷索引。

### 路径转换

```python
from k3q_arxml import str2ref, ref2str
str2ref('/Types/Speed')   # ('Types', 'Speed')
ref2str(('Types', 'Speed'))  # '/Types/Speed'
```

只支持绝对路径引用，不支持相对引用；引用路径不能含空段。

## 编辑模式

### 1. 改字段 + 事务刷新

```python
from k3q_arxml import ArxmlTransaction

node = io.ref(('Types', 'Speed'))
with ArxmlTransaction() as transaction:
    node.xml_obj.short_name.value = 'Velocity'
    transaction.add(node.xml_obj)
```

`ArxmlTransaction` 退出上下文时按添加顺序统一调用 `edited()`；同一对象只执行一次；不回滚、不自动保存。异常退出时不刷新。

### 2. 重命名 + 同步引用（最常见批量任务）

改 SHORT-NAME 后**必须自己同步引用**（库不自动改引用文本）：

```python
from k3q_arxml import ArxmlTransaction, str2ref

old_ref = str2ref('/Types/Speed')
node = io.ref(old_ref)
rows = io.ref_to_ref(old_ref)          # 先收集全部入向引用
with ArxmlTransaction() as transaction:
    node.xml_obj.short_name.value = 'Velocity'
    transaction.add(node.xml_obj)
    for row in rows:
        row.set_dest(('Types', 'Velocity'))
        transaction.add(row.xml_obj)
```

注意：`ref_to_ref` 按目标路径查索引，**先收集再改**，改完再查会查不到旧路径。

### 3. 结构改动（增删移动子节点）

直接改父对象的字段/列表，然后对改动所在的**具名节点**调 `file.update_node(node)` 重建该子树索引。修改范围必须包含在 `node.xml_obj` 内；删除/替换/移动具名根对象本身时，改其共同具名祖先的 `update_node`。

### 4. 单点小改动

`obj.edited()` 即时刷新最近具名祖先索引；批量场景用事务合并，避免反复扫描。

## 批量脚本模板

```python
import argparse
from pathlib import Path

from k3q_arxml import ArxmlTransaction, IOArxml, logger, ref2str
from k3q_arxml.log import configure_logging
from k3q_arxml.schemas import autosar_4_2_2 as autosar


def main() -> None:
    parser = argparse.ArgumentParser(description='batch rename ADT with suffix')
    parser.add_argument('-s', '--suffix', required=True)
    parser.add_argument('arxml_files', nargs='+', type=Path)
    args = parser.parse_args()
    configure_logging('DEBUG')

    io = IOArxml(filepaths=args.arxml_files, binding=autosar)
    for node in io.ar(clazz=autosar.ApplicationPrimitiveDataType):
        if node.short_name.endswith(args.suffix):
            continue
        rows = io.ref_to_ref(node.ref)
        with ArxmlTransaction() as transaction:
            node.xml_obj.short_name.value += args.suffix
            transaction.add(node.xml_obj)
            for row in rows:
                row.xml_obj.value += args.suffix
                transaction.add(row.xml_obj)
        logger.info('renamed {}', ref2str(node.ref))

    io.flush_to_file()


if __name__ == '__main__':
    main()
```

可运行的完整示例见仓库 `demo/`：

- `demo/chg_adt_name.py` —— 按 SOA 接口列表给 ApplicationDataType 加/去后缀，跨文件同步引用。
- `demo/chg_adt_idt_name.py` —— 批量给 ADT/IDT 加前缀，同文件文本替换 + 索引同步。

## 注意事项

- **索引时效**：直接改 `xml_obj` 后索引不自动更新，后续查询前要么 `edited()`、要么事务统一刷新、要么 `update_node`。忘记刷新是批量脚本最常见的 bug。
- **叶子路径唯一**：核心层统一检查 schema 叶子具名类型的完整 SHORT-NAME 链，禁止同文件及跨文件重复。叶子按当前版本绑定的字段类型（含可选字段、无名包装和 choices）判定，与实例是否包含子节点无关。中间类型允许重复；`IOArxml.ref` 遇到多个匹配仍报错，可通过所属文件的 `ArxmlFile.ref` 定位。
- **跨文件引用**：`ref_to_ref` 汇总所有已加载文件；引用目标可在其他文件甚至未加载文件中。只加载需要同步的那批文件。
- **回写格式**：保存保留原缩进与根节点前注释，但绑定序列化可能产生数值/空白规范化差异，批量前后建议 `git diff` 抽查。
- **先试跑**：破坏性批量操作先在副本目录或 `git stash` 可回退的环境跑一遍，确认 `render()` / diff 无误再 `flush_to_file()`。
- **类型不确定时**：`from k3q_arxml.schemas.autosar_4_2_2 import X` 查模块源码，或用 MCP 的 `describe_type` / `get_type_source` 查字段与 XSD 约束。
