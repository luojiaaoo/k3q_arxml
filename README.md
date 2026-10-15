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

## 介绍

极简的 ARXML 编辑库，使用 Python、xsdata 和 lxml 实现。

代码分三层：`ArxmlNode` 包装实际 XML 对象，`ArxmlFile` 负责单个文件的解析、扫描和保存，`IOArxml` 负责管理多个文件和汇总查询结果。`ArxmlNamedNode` 和 `ArxmlRefNode` 都继承 `ArxmlNode`，分别表示具名节点和引用节点。

项目自定义的数据模型统一定义在 `k3q_arxml/schemas.py`：`ArxmlNode`、`ArxmlNamedNode`、`ArxmlRefNode` 使用 dataclass，`ArxmlFormat`、`ArxmlHeader` 使用 Pydantic；该文件也负责发现可用的 AUTOSAR XSD。

## 安装与生成类型

项目使用 [uv](https://docs.astral.sh/uv/getting-started/installation/) 管理环境。在仓库根目录执行：

```console
uv sync --locked
uv run python -m k3q_arxml versions
uv run python -m k3q_arxml generate 4.2.2
```

仓库保留所有版本的 XSD，位于 `k3q_arxml/schemas/`，不再预生成、提交所有版本的 Python 绑定。生成命令使用 Click 实现，可在 Windows、Linux 和 macOS 上使用。

- 可用版本从 `schemas/autosar_*` 目录自动查找，以 `versions` 命令输出为准。新增版本时，放入对应的目录和主 XSD 即可，例如 `autosar_00053/AUTOSAR_00053.xsd`，无需修改版本列表。
- 每次只生成指定版本，输出为真实的 `k3q_arxml/autosar.py`，支持 IDE 补全和静态类型检查。
- 当前绑定未生成时，CLI 的帮助、版本列表和生成命令仍可使用；创建 `IOArxml` 会提示先生成。
- 生成成功后替换当前绑定；生成失败保留原有绑定。生成文件已加入 Git 忽略规则。
- 更换版本只需重新运行生成命令，例如 `uv run python -m k3q_arxml generate 00048`。随后使用新的 Python 进程；IDE 如仍显示旧类型，刷新语言服务。
- 选择与输入 ARXML 的 schema 相匹配的版本。当前只使用一个生成版本，不再提供 `change_autosar_version()`、旧版模块入口或懒加载代理。
- 导入文件时先核对 `xsi:schemaLocation` 声明的 AUTOSAR XSD 与当前绑定版本；版本不一致或缺少声明时抛出 `ValueError`，不会自动切换版本。

Python 开发版本固定为 3.11，运行依赖使用 xsdata 26.2、lxml 5.4.0 和 Click 8.2.1。Ruff 0.13.3 与 xsdata 的生成配置兼容。暂不配置包构建，从仓库根目录执行命令。

日志使用 Loguru，配置集中在 `k3q_arxml/log.py`，默认输出 INFO 及以上日志。需要调试输出时调用 `from k3q_arxml.log import configure_logging`，再执行 `configure_logging('DEBUG')`。

## 使用

先生成与仓库样例匹配的 4.2.2 绑定，再运行以下代码：

```python
from pathlib import Path

from k3q_arxml import IOArxml, autosar

io_arxml = IOArxml(
    filepaths=[Path('test/ThrottlePositionControlComposition.arxml')],
)

# 找出文件中所有的基础数据类型（XML 中的 SW-BASE-TYPE 节点）。
base_types = io_arxml.ar(clazz=autosar.SwBaseType)
for result in base_types:
    base_type = result.xml_obj  # 取出这个节点对应的 ARXML 对象。
    name = base_type.short_name.value  # 读取它的 SHORT-NAME 内容。
    print(result.ref, name)  # 打印这个数据类型的路径和名称。

# 按路径查找 BaseTypes 包；没有找到时返回 None。
package = io_arxml.ref(('AUTOSAR_Platform', 'BaseTypes'))
if package is not None:
    print(package.short_name)  # 打印找到的包名 BaseTypes。

# 查找文件中哪些位置使用了 uint8 这个数据类型。
references = io_arxml.ref_to_ref(('AUTOSAR_Platform', 'BaseTypes', 'uint8'))
for reference in references:
    # xml_obj.value 是目标路径，owner_ref 是引用所在具名节点的路径。
    print(reference.xml_obj.value, reference.owner_ref)

# 修改数据类对象后，调用其 edited() 更新最近具名节点的索引。

# 把读取到的全部内容输出到 model.txt，方便查看。
io_arxml.print(print_filepath=Path('model.txt'))

# 把修改保存回原来的 ARXML 文件。确认已备份后再取消下面的注释。
# io_arxml.flush_to_file()
```

上面的查询过程分为几步：

1. `autosar.SwBaseType` 表示要查找的节点类型，对应 XML 中的 `<SW-BASE-TYPE>`。
2. `ar()` 返回对象列表，每一项只对应一个文件里的一个节点。
3. `result.xml_obj` 取出实际的 ARXML 对象，`result.ref` 是节点路径。
4. `base_type.short_name.value` 读取这个对象的 `<SHORT-NAME>` 文本，也就是它的名称。

每个文件加载时由 `scan_ref()` 全量扫描一次，建立 `objects`、`references` 和 `uuids` 三份初始索引。后续节点编辑使用 `update_node()` 增量维护已有索引。

`result.content` 按需导出当前节点及其子节点的 XML 字符串，不缓存完整文本。修改 XML 对象后调用对象的 `edited()`，更新最近具名节点及其子树的索引：

```python
result = io_arxml.ar(autosar.SwBaseType)[0]
base_type = result.xml_obj
base_type.uuid = 'updated-base-type'  # 修改这个 SW-BASE-TYPE 节点的 UUID 属性。
base_type.edited()  # 更新所属文件的对象、引用和 UUID 索引；返回 base_type 自己。

print(io_arxml.ref(result.ref).xml_obj.uuid)  # 再次查询可读到新 UUID。
```

解析时会为每个数据类对象设置 `.arxml_parent` 和 `.edited()`。在没有 `SHORT-NAME` 的对象上调用 `edited()`，会沿父对象向上找到最近的具名节点；例如修改引用的 `.value` 后，可以直接调用该引用对象的 `edited()`。该方法完成索引更新并返回调用它的对象。增删或移动具名节点本身时，应在包含全部变化的共同具名祖先上调用 `edited()`。若对象没有具名祖先，需由文件层调用 `scan_ref()` 全量重建。查询新名称和引用应在 `edited()` 成功后进行；旧包装的 `.ref` 可能仍是上次查询时的路径，重新调用 `ref()` / `ar()` 获取当前包装。重命名仍需自行同步引用文本。保存到磁盘需调用 `file.save()` 或 `io_arxml.flush_to_file()`。

文件路径参数统一使用 `pathlib.Path`。加载、添加和查询文件时使用 `resolve()` 转为绝对路径；同一文件的相对路径、绝对路径以及 Windows 下不同斜杠写法只加载一次。`file.filepath` 和 `io_arxml.files` 的键均为绝对路径 `Path`。需要文件对象时，通过已知路径从 `io_arxml.files` 获取。

使用 `io_arxml.append(Path('other.arxml'))` 加载已有 ARXML 文件并加入管理，返回对应的 `ArxmlFile`。路径必须存在且为普通文件；重复加载同一文件或与已加载文件存在相同对象路径时抛出异常，文件不会加入管理。`append()` 不写回磁盘，修改后调用 `file.save()` 或 `io_arxml.flush_to_file()` 保存。

对象、引用和 UUID 索引保存在各个 `ArxmlFile` 中，通过 `io_arxml.files[Path('文件路径').resolve()]` 获取对应文件后访问 `file.objects`、`file.references` 和 `file.uuids`。跨文件查询使用 `io_arxml.ar()`、`io_arxml.ref()` 和 `io_arxml.ref_to_ref()`。

`io_arxml.ref(path)` 返回唯一对象或 None，发现多个匹配时抛出异常。查询指定文件时，使用 `io_arxml.files[Path('文件路径').resolve()].ref(path)`。对象上不再提供 `.default`、`.filter()` 或多对象遍历。

只处理一个文件时，可以直接使用文件层：

```python
from pathlib import Path

from k3q_arxml import ArxmlFile, autosar

file = ArxmlFile().parse_file(Path('test/ThrottlePositionControlComposition.arxml'))
for result in file.ar(autosar.SwBaseType):
    print(result.ref, result.xml_obj.short_name.value)

# 查看指向 uint8 数据类型的引用；每项 ArxmlRefNode 保存实际引用节点和来源路径。
for reference in file.references.get(('AUTOSAR_Platform', 'BaseTypes', 'uint8'), []):
    print(reference.xml_obj.value, reference.owner_ref)
    # owner_ref 是包含该引用的具名对象路径；修改引用后，调用 reference.xml_obj.edited() 更新索引。

# 直接修改某个 result.xml_obj 后，调用 result.xml_obj.edited()，再调用 file.save() 保存。
```

`reference.set_dest(('AUTOSAR_Platform', 'BaseTypes', 'float32'))` 将路径元组转为 `/AUTOSAR_Platform/BaseTypes/float32`，写入实际引用节点的文本值。调用后仍需执行 `reference.xml_obj.edited()` 更新索引，并保存文件。

扫描沿嵌套对象和列表递归查找节点，用 `SHORT-NAME` 组成对象路径，并用 `isinstance(node, autosar.Ref)` 识别引用，包含直接和间接子类。引用结果保留实际引用节点，修改其 `.value` 后可以回写文件；引用目标可以位于其他文件或尚未加载。

扫描按 XML 的树形包含结构处理，使用 Python 默认的递归深度限制。目前只支持 `/Package/Type` 形式的绝对引用，不解析 `BASE / REFERENCE-BASES` 相对引用。空名称和无效引用路径会抛出带文件及节点位置的 `ValueError`，扫描失败时保留上一轮索引；缺失或为空的 UUID 不进入索引。加载时由 `scan_ref()` 全量建立索引；后续修改数据类对象并调用其 `edited()` 增量更新。重命名仍需自行同步定义与引用。

如果要新建一个名称字段，可以这样写：

```python
# 创建一个值为 newName 的名称字段，后续可以赋给对象的 short_name。
identifier = autosar.Identifier(value='newName')
print(identifier.value)  # 输出 newName。
```

这里只创建了一个 Python 对象，还没有将它添加到 ARXML 或保存到文件。

## 编辑脚本

两个脚本使用当前已生成的绑定，无需传入或切换版本：

```console
uv run python chg_adt_name.py --help
uv run python chg_adt_idt_name.py --help
```

实际运行会原地修改输入文件。`chg_adt_idt_name.py` 会先全局移除文本中的 `ADT_` / `IDT_`，再为目标数据类型及引用添加前缀，使用前应备份文件。

根目录 `test.py`、`test3.py` 是历史手工示例，依赖未提交的 `test/model_merge.arxml`，不作为自动化测试入口。

## 开发与验证

```console
uv run python -m k3q_arxml generate 4.2.2
uv run python -m unittest discover -s tests -v
uv run ruff check k3q_arxml tests chg_adt_name.py chg_adt_idt_name.py
uv run ruff format --check k3q_arxml tests chg_adt_name.py chg_adt_idt_name.py
uv lock --check
```

CLI 测试在临时目录中生成小型 schema，覆盖版本替换、失败保留和含空格及中文的路径。ARXML 测试使用样例的临时副本，验证解析回写、多文件路径和重命名引用；未生成 4.2.2 绑定时会跳过这些样例测试。

依赖和 Ruff 配置统一维护在 `pyproject.toml`，完整依赖树锁定在 `uv.lock`。使用 `uv add` / `uv remove` 管理依赖，开发依赖添加 `--dev`。运行依赖已包含生成 CLI；`uv sync --locked --no-dev` 也可使用生成命令。不要手动编辑生成的 `autosar.py` 或将其提交。
