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

`k3q_arxml` 用于读取、查询和修改 AUTOSAR ARXML 文件，支持同时处理多个文件。

## 准备环境

先安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)，然后在仓库根目录执行：

```console
uv sync --locked
```

查看支持的 AUTOSAR 版本，并选择与 ARXML 文件匹配的版本：

```console
uv run python -m k3q_arxml versions
uv run python -m k3q_arxml generate 4.2.2
```

仓库自带样例使用 4.2.2。处理其他文件时，可查看文件开头 `xsi:schemaLocation` 中的 XSD 文件名来确认版本，例如 `AUTOSAR_4-2-2.xsd` 对应 `4.2.2`。

更换版本时，重新执行 `generate <版本>`，再重新启动 Python 脚本或交互环境。同一次运行中的文件应使用相同版本。

## 读取文件

将下面的代码保存为仓库根目录下的 `example.py`，运行 `uv run python example.py`：

```python
from pathlib import Path

from k3q_arxml import IOArxml, autosar

filepath = Path('test/ThrottlePositionControlComposition.arxml')
io_arxml = IOArxml(filepaths=[filepath])

# 查找所有 SW-BASE-TYPE 节点，打印路径和名称。
for node in io_arxml.ar(autosar.SwBaseType):
    print(node.ref, node.xml_obj.short_name.value)
```

`node.xml_obj` 用来读取或修改节点内容；`short_name.value` 是 XML 中 `<SHORT-NAME>` 的文本。`node.ref` 是节点路径，例如 `('AUTOSAR_Platform', 'BaseTypes', 'uint16')` 对应 `/AUTOSAR_Platform/BaseTypes/uint16`。

以下示例接着使用上面的 `io_arxml`。

## 查询节点

按完整路径查找，找不到时返回 `None`：

```python
node = io_arxml.ref(('AUTOSAR_Platform', 'BaseTypes', 'uint16'))
if node is not None:
    print(node.short_name)  # 输出 uint16。
    print(node.content)  # 查看这个节点及其子节点的 XML。
```

按类型查找，也可以限定在某个包下：

```python
base_types = io_arxml.ar(
    autosar.SwBaseType,
    ref_prefix=('AUTOSAR_Platform', 'BaseTypes'),
)
for node in base_types:
    print(node.ref)
```

常用类型包括 `autosar.ArPackage`（包）、`autosar.SenderReceiverInterface`（发送接收接口）、`autosar.ApplicationPrimitiveDataType`（应用基础数据类型）和 `autosar.ImplementationDataType`（实现数据类型）。

## 访问上一级 XML 标签

通过 XML 对象的 `arxml_parent` 可以访问上一级 XML 标签对象。例如，从 `<SHORT-NAME>` 返回它所属的 `<SW-BASE-TYPE>`：

```python
node = io_arxml.ref(('AUTOSAR_Platform', 'BaseTypes', 'uint16'))
if node is not None:
    short_name = node.xml_obj.short_name
    parent = short_name.arxml_parent  # 上一级 SW-BASE-TYPE 标签对象。
    print(parent.short_name.value)  # 输出 uint16。
```

可以继续通过 `parent.arxml_parent` 向上访问。上一级也可能是容器标签，不一定带有 `<SHORT-NAME>`；根对象的 `arxml_parent` 为 `None`。

## 查询引用

查找哪些节点引用了指定数据类型：

```python
target = ('AUTOSAR_Platform', 'BaseTypes', 'uint16')
for reference in io_arxml.ref_to_ref(target):
    print(reference.owner_ref)  # 引用所在节点的路径。
    print(reference.xml_obj.value)  # 引用指向的路径文本。
```

只会查找已加载文件中的引用；需要检查其他文件时，先将它们一起加载。

## 修改并保存

**修改任何 XML 对象后，都要调用该对象的 `edited()`，再继续查询或保存。直接赋值或调用 `set_dest()` 不会自动刷新。**

涉及多处关联修改时，先查齐并保存相关节点和引用，再使用 `ArxmlTransaction` 上下文收集需要刷新的 XML 对象，正常退出时统一调用 `edited()`。上下文内使用旧索引完成关联修改，退出后再查询新路径。

增删、替换或移动节点时，在包含全部变化的共同具名父节点对象上调用 `edited()`。

例如，修改节点的 UUID 后刷新并保存：

```python
node = io_arxml.ref(('AUTOSAR_Platform', 'BaseTypes', 'uint16'))
if node is not None:
    node.xml_obj.uuid = '12345678-1234-1234-1234-123456789abc'
    node.xml_obj.edited()
    io_arxml.flush_to_file()
```

`edited()` 默认刷新索引并标记文件已修改。**如果不确定修改是否影响索引，直接调用 `edited()`，不加参数即可。** 如果确认只修改普通属性，没有改变节点名称、UUID、引用或节点结构，可以调用 `edited(refresh_index=False)`，只标记文件已修改，省去索引刷新：

```python
node.xml_obj.s = 'updated-checksum'  # 修改 XML 的 S 校验和属性。
node.xml_obj.edited(refresh_index=False)
io_arxml.flush_to_file()
```

`edited()` 不会保存文件，完成修改并调用后，再用 `flush_to_file()` 将修改写回原文件。保存前请备份需要保留的文件。

事务上下文的 `add()` 接收实际 XML 对象，即查询结果的 `.xml_obj`，也支持 `refresh_index` 参数，默认值为 `True`。例如，只修改校验和属性时可以这样写：

```python
from k3q_arxml import ArxmlTransaction

with ArxmlTransaction() as transaction:
    node.xml_obj.s = 'updated-checksum'
    transaction.add(node.xml_obj, refresh_index=False)
io_arxml.flush_to_file()
```

不确定是否影响索引时，使用 `transaction.add(node.xml_obj)` 即可。同一 XML 对象重复添加只调用一次 `edited()`；只要有一次添加要求刷新索引，就会刷新。增删、替换或移动节点时，添加包含全部变化的共同具名父节点对象。

上下文正常退出时按添加顺序执行 `edited()`，之后再查询或保存。上下文内抛出异常时不执行刷新，也不撤销已发生的对象修改；退出时某次刷新失败会停止后续刷新，已经完成的刷新保留。事务上下文不会自动保存文件。

修改引用目标时，先查齐引用并使用 `set_dest()` 修改，将引用对象加入上下文，退出时统一刷新：

```python
old_target = ('AUTOSAR_Platform', 'BaseTypes', 'uint16')
new_target = ('AUTOSAR_Platform', 'BaseTypes', 'sint16')
references = io_arxml.ref_to_ref(old_target)
with ArxmlTransaction() as transaction:
    for reference in references:
        reference.set_dest(new_target)
        transaction.add(reference.xml_obj)
io_arxml.flush_to_file()
```

## 重命名并同步引用

重命名节点时，需要同时修改引用它的路径。下面将 `uint16` 改为 `uint16_custom`；请在包含原名称的文件上单独运行此示例：

```python
old_ref = ('AUTOSAR_Platform', 'BaseTypes', 'uint16')
new_ref = (*old_ref[:-1], 'uint16_custom')
node = io_arxml.ref(old_ref)
if node is not None:
    # 先查出使用旧名称的全部引用，再统一修改。
    references = io_arxml.ref_to_ref(old_ref)
    with ArxmlTransaction() as transaction:
        node.xml_obj.short_name.value = new_ref[-1]
        transaction.add(node.xml_obj)
        for reference in references:
            reference.set_dest(new_ref)
            transaction.add(reference.xml_obj)
    # 目标名称和所有引用都已修改并刷新，再保存文件。
    io_arxml.flush_to_file()

    print(io_arxml.ref(new_ref).short_name)  # 输出 uint16_custom。
```

修改并调用 `edited()` 后，重新调用 `ref()` 或 `ar()` 获取节点。增删或移动子节点时，在包含全部变化的共同具名父节点对象上调用 `edited()`。

## 处理多个文件

文件路径使用 `Path`，按实际文件位置替换下面的示例路径：

```python
io_arxml = IOArxml(filepaths=[Path('types.arxml'), Path('interfaces.arxml')])

# 后续还可以加入其他已有文件。
io_arxml.append(Path('components.arxml'))

# ar()、ref() 和 ref_to_ref() 会查询所有已加载文件。
for node in io_arxml.ar(autosar.SenderReceiverInterface):
    print(node.ref)

# 只查询某个文件。
file = io_arxml.files[Path('types.arxml').resolve()]
node = file.ref(('DataTypes', 'Speed'))

# 完成修改并调用 edited() 后，保存所有已修改文件。
io_arxml.flush_to_file()
```

`append()` 要求文件存在且尚未加载；不同文件中出现相同节点路径时会报错。

## 只处理一个文件

也可以直接使用 `ArxmlFile`：

```python
from pathlib import Path

from k3q_arxml import ArxmlFile, autosar

file = ArxmlFile().parse_file(Path('test/ThrottlePositionControlComposition.arxml'))
for node in file.ar(autosar.SwBaseType):
    print(node.ref, node.short_name)

# 修改对象后先调用 edited()，再执行 file.save() 写回这个文件。
```

## 导出内容供查看

```python
io_arxml.print()  # 在终端查看文件内容。
io_arxml.print(print_filepath=Path('model.txt'))  # 输出到文本文件。
```

这里导出的是便于查看的对象内容；保存 ARXML 请使用 `flush_to_file()` 或 `file.save()`。

## 名称处理脚本

查看参数用法：

```console
uv run python chg_adt_name.py --help
uv run python chg_adt_idt_name.py --help
```

- `chg_adt_name.py`：通过 `--suffix` 指定后缀、`--soa_interface_name` 指定接口名称列表，按接口处理关联 ADT 的后缀。
- `chg_adt_idt_name.py`：接收一个或多个 ARXML 文件路径，整理 ADT / IDT 名称前缀。它会先全局删除文件文本中的 `ADT_` 和 `IDT_`，也会影响非名称文本。

运行名称处理脚本前请备份输入文件，并在运行后检查修改结果。
