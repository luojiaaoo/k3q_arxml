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

## 安装

需要 Python 3.11 或以上版本。发行包名为 `k3q-arxml`，Python 导入名为 `k3q_arxml`。

### 从 PyPI 安装

以下命令需有已发布到 PyPI 的可用版本；维护者的首次发布流程见 [AGENTS.md 的发布指南](AGENTS.md#开发与-pypi-发布)。

已有 Python 环境时执行：

```console
python -m pip install k3q-arxml
```

当前源码默认安装 MCP 依赖，构建并安装后即可使用 MCP 入口，无需额外选择安装项。已发布的 2.1.3 仍使用原来的可选依赖配置。

也可以使用 [uv](https://docs.astral.sh/uv/getting-started/installation/) 管理自己的项目，在项目目录执行：

```console
uv init --bare --python 3.11
uv add k3q-arxml
```

已有 uv 项目时跳过 `uv init`。后续运行脚本以 `uv run python example.py` 为例，pip 用户使用 `python example.py`。uv 的依赖管理方式见 [官方项目指南](https://docs.astral.sh/uv/guides/projects/)。

### 从源码安装开发环境

需要开发本库或运行仓库样例时，下载仓库并在仓库根目录执行：

```console
uv sync --locked
```

### 选择 AUTOSAR 绑定

当前源码已预生成全部支持版本的绑定，平铺在 `k3q_arxml/schemas/schame/` 中，例如 `autosar_4_2_2.py`、`autosar_00044.py`；对应 XSD 及关联的 `xml.xsd` 放在 `k3q_arxml/schemas/xsd/autosar_<版本>/` 中。用户直接选择所需模块，无需生成或切换文件；不提供旧的 autosar.py 兼容入口及 versions / generate 开发命令。

仓库样例使用 4.2.2。其他文件可查看开头 xsi:schemaLocation 中的 XSD 文件名，例如 AUTOSAR_4-2-2.xsd 对应 4.2.2。MCP 启动命令与 schemas/xsd 下的版本目录一一对应，例如 autosar_00044 对应 k3q-arxml-mcp-00044。

Python 中明确导入所需版本，并把模块传给文件或工程。例如处理 00044：

```python
from pathlib import Path
from k3q_arxml import IOArxml
from k3q_arxml.schemas.schame import autosar_00044

io = IOArxml([Path('types.arxml')], binding=autosar_00044)
for node in io.ar(autosar_00044.SwBaseType):
    print(node.ref)
```

`ArxmlFile(binding=autosar_00044)` 与 `ArxmlMcpService(workspace, binding=autosar_00044)` 使用同一写法。必须显式传入 binding，库本身不会导入任何 AUTOSAR 版本。各版本可以在同一环境中并存，不会互相覆盖。

本 README 的独立模块与启动入口对应当前源码，尚未发布；已发布的 2.1.3 使用旧接口。请先从源码构建并安装 wheel，再使用下方新入口。

## 读取文件

将下面的代码保存为项目目录下的 `example.py`，运行 `uv run python example.py`。示例使用仓库中的 `test/ThrottlePositionControlComposition.arxml`；从 PyPI 安装后，需另行下载该样例或将路径改为自己的 ARXML 文件：

```python
from pathlib import Path

from k3q_arxml import IOArxml
from k3q_arxml.schemas.schame import autosar_4_2_2 as autosar

filepath = Path('test/ThrottlePositionControlComposition.arxml')
io_arxml = IOArxml(filepaths=[filepath], binding=autosar)

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

每个已解析并扫描的 XML 对象（包括无名容器）都有 `edited()`。调用时，如果对象自身具名，就刷新自身及其子树；否则自动向上找到最近的具名祖先，刷新该祖先及其子树，不必手动找到具名父节点。若对象自身及其祖先都不具名，默认刷新会报错。

增删或替换子节点时，在承载相应字段或列表的父对象上调用 `edited()`；新建但尚未扫描的对象还没有此方法。跨父节点移动时，分别刷新原父对象和新父对象，或在覆盖两边变化的共同祖先对象上调用。

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

不确定是否影响索引时，使用 `transaction.add(node.xml_obj)` 即可。同一 XML 对象重复添加只调用一次 `edited()`；只要有一次添加要求刷新索引，就会刷新。增删或替换子节点时，添加承载相应字段或列表的父对象，也可以是无名容器；跨父节点移动时，添加原父对象和新父对象，或覆盖两边变化的共同祖先对象。

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

修改并调用 `edited()` 后，重新调用 `ref()` 或 `ar()` 获取节点。

## 处理多个文件

文件路径使用 `Path`，按实际文件位置替换下面的示例路径：

```python
io_arxml = IOArxml(filepaths=[Path('types.arxml'), Path('interfaces.arxml')], binding=autosar)

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

from k3q_arxml import ArxmlFile
from k3q_arxml.schemas.schame import autosar_4_2_2 as autosar

file = ArxmlFile(binding=autosar).parse_file(Path('test/ThrottlePositionControlComposition.arxml'))
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

以下脚本位于源码仓库，不随 PyPI 包安装。在仓库根目录查看参数用法：

```console
uv run python chg_adt_name.py --help
uv run python chg_adt_idt_name.py --help
```

- `chg_adt_name.py`：通过 `--suffix` 指定后缀、`--soa_interface_name` 指定接口名称列表，按接口处理关联 ADT 的后缀。
- `chg_adt_idt_name.py`：接收一个或多个 ARXML 文件路径，整理 ADT / IDT 名称前缀。它会先全局删除文件文本中的 `ADT_` 和 `IDT_`，也会影响非名称文本。

运行名称处理脚本前请备份输入文件，并在运行后检查修改结果。

## 通过 MCP 供大模型使用

MCP 服务使用本地 stdio。可以直接运行版本专用命令，例如 `k3q-arxml-mcp-00044` 或 `k3q-arxml-mcp-4-2-2`，无需填写版本参数。启动不接受版本参数，版本完全由命令名称决定。所有命令复用同一份启动代码，只导入选定版本的绑定，然后在同一进程启动服务。

先在仓库构建，并安装到专用环境（PowerShell）：

```powershell
uv sync --locked
uv build --no-sources --wheel --out-dir dist/local
uv venv C:/arxml-env --python 3.11
uv pip install --python C:/arxml-env/Scripts/python.exe "dist/local/k3q_arxml-2.1.3-py3-none-any.whl"
```

安装后，Windows 的 `Scripts` 目录下会有每个版本的 `k3q-arxml-mcp-<版本>.exe`；Linux/macOS 位于环境的 bin 目录，名称不带 .exe。版本号中的点用连字符表示，例如 4.2.2 对应 `k3q-arxml-mcp-4-2-2`。`pyproject.toml` 的 `[project.scripts]` 将全部命令映射到 `k3q_arxml.script.serve_mcp:main`，无参数函数按命令名称确定固定版本，规则见 [Python 打包指南](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/#creating-executable-scripts)。

客户端可直接启动对应版本命令，args 留空，cwd 指向业务模型目录。例如 Windows：

```json
{
  "mcpServers": {
    "arxml": {
      "command": "C:/arxml-env/Scripts/k3q-arxml-mcp-00044.exe",
      "args": [],
      "cwd": "D:/models"
    }
  }
}
```

Linux/macOS 将 command 改为环境的 `/path/to/env/bin/k3q-arxml-mcp-00044`，并填写模型目录。需要其他版本时改用对应版本的命令，再重新连接服务。args 留空，启动命令不接受 --schema-version 参数。

全部版本命令复用 `k3q_arxml/script/serve_mcp.py` 中的无参数入口。源码开发后按本节步骤构建并安装 wheel，即可使用这些命令；客户端工作目录仍为业务模型目录。

启动过程只读取选定的 Python 模块，不解压 ZIP、不修改安装目录、不通过 `-m k3q_arxml` 或子进程再次启动。不同版本的服务可使用同一个安装环境。服务启动后版本固定，文件访问范围为启动目录及子目录，日志和诊断写入 stderr，stdout 仅用于 MCP 协议。服务由客户端启动，无需手动再启动第二个服务。

历史发布版本的启动计时见 [MCP 启动耗时记录](docs/mcp-startup-performance.md)，其中旧实现的数据不代表当前统一入口。

### 安装随包提供的 Skill

从 `2.1.0` 起，wheel 和源码发行包都附带完整的 `arxml-mcp` 技能目录。

该 Skill 是本 MCP 的使用手册，操作 ARXML 前应优先读取。从 `2.1.1` 起，如果尚未加载 `arxml-mcp` Skill，先调用 MCP 工具 `get_skill_path()` 获取内置目录，再读取 `SKILL.md` 和任务所需参考文件；工具不解析内容，也不要求先打开工程。建议将整个目录安装到智能体的 skills 目录，便于后续自动发现和加载，无需重新创建技能。通过 `uv run --with` 启动时，Skill 位于该临时环境的 site-packages 中；也可用与服务相同的 Python 环境执行以下命令查询路径：

```console
python -c "from importlib.resources import files; print(files('k3q_arxml').joinpath('skills', 'arxml-mcp'))"
```

将输出路径中的整个 `arxml-mcp` 文件夹复制到智能体的技能目录，例如 Codex 的 `~/.codex/skills/`。也可以执行以下代码复制到 Codex 默认目录；目标已存在时会报错，先核对是否需要替换：

```python
from importlib.resources import files
from pathlib import Path
from shutil import copytree

source = files('k3q_arxml').joinpath('skills', 'arxml-mcp')
target = Path.home() / '.codex' / 'skills' / 'arxml-mcp'
copytree(str(source), target)
print(target)
```

源码仓库中的对应目录为 `skills/arxml-mcp`，复制其中的 `SKILL.md` 和全部 `references` 即可。Skill 的安装和 MCP 客户端连接需要分别配置。

工具说明、编辑流程、校验与恢复见 [AGENTS.md 的 MCP 说明](AGENTS.md#arxml-mcp-使用说明)。
