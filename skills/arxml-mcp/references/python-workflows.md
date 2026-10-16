# Python 编写与执行指南

适用于 `k3q-arxml` 2.1.2 的 Python 对象接口及随包提供的 `ArxmlMcpService`。规则明确、目标可枚举、需要重复执行或检查多项结果时，可以将变更与验证写成任务脚本。先用交互 MCP 查明结构和引用，再将确认后的步骤固化；不必为已确定的每个节点反复调用工具。

## 选择接口和运行环境

| 需求 | 使用方式 |
| --- | --- |
| 自定义对象遍历、统计、业务断言或复杂结构计算 | `IOArxml` / `ArxmlFile` 和 `autosar` 对象 |
| 固化 MCP 的重命名、局部 XML 编辑、校验、预览和备份保存 | 在 Python 中直接实例化 `ArxmlMcpService` |
| 操作现有 MCP 会话中的未保存修改 | 继续调用该会话的工具；新脚本无法接管其他进程的对象 |

使用安装了对应绑定的同一个 Python 环境。源码仓库使用 `uv run python task.py ...`；已安装发行包的环境使用 `python task.py ...`。脚本不会自动生成或切换绑定，也不会重启正在运行的服务。

`mcp --schema-version` 选择的绑定仅用于该服务的独立临时包，不会改变同一 Python 安装环境里的默认绑定。独立任务脚本需由用户在自己的环境中准备所需绑定，并使用新进程；执行前可输出 `autosar.SCHEMA_VERSION` 核对，不能直接沿用 MCP 的临时版本假设。

`ArxmlMcpService` 位于 `k3q_arxml.mcp.service`，可直接调用，不需要启动 stdio 或额外编写协议客户端。它是当前版本的服务接口；调用签名以实际安装版本为准。Python 直接调用不会经过 MCP SDK 的参数校验，显式传入正确类型：`Path` 工作目录、文件路径字符串列表、`McpPatchOperation` 对象列表和服务实际返回的 revision。

任务脚本保存在用户指定的任务目录；不要改包内的 `autosar.py` 或 Skill 安装目录。保留 `main()` 和 `if __name__ == '__main__'`，导入脚本不得写文件或解析命令行参数。将变更、验证和保存分开，让同一套检查能用于预演和保存后复查。

## 核心对象接口的写法

文件参数使用 `Path`；对象路径使用由 SHORT-NAME 组成的元组。`node.xml_obj` 是 XML 对象，`short_name.value` 是 SHORT-NAME 文本，`node.content` 是节点 XML。`file_id` 属于 MCP 会话，核心对象接口用磁盘路径找到所属文件。

下面的代码只查询和修改内存中的对象，不写盘；`io` 是调用者用明确文件集合创建的 `IOArxml`：

```python
from pathlib import Path

from k3q_arxml import IOArxml, autosar


def load_files(filepaths):
    return IOArxml(filepaths=[Path(path).resolve() for path in filepaths])


def set_uuid(io, ref, value):
    node = io.ref(ref)
    if node is None:
        raise ValueError(f'节点不存在：{ref}')
    if node.xml_obj.uuid == value:
        return False
    node.xml_obj.uuid = value
    node.xml_obj.edited()  # UUID 属于索引内容，修改后刷新索引并标记文件。
    if io.ref(ref).xml_obj.uuid != value:
        raise RuntimeError(f'UUID 修改未生效：{ref}')
    return True


def list_base_types(io):
    return [(node.ref, node.xml_obj.short_name.value) for node in io.ar(autosar.SwBaseType)]
```

其他编辑遵循这些边界：

- 修改名称、UUID、引用或结构后调用实际对象的 `edited()`；也可将当前查询返回的包装传给所属文件的 `update_node(node)`。索引更新后重新查询包装。
- 仅修改已确认不影响索引的普通属性时，才使用 `edited(refresh_index=False)`。
- 修改引用使用 `reference.set_dest(目标路径元组)`，随后调用 `reference.xml_obj.edited()`。`set_dest()` 本身不会刷新索引，也不会修改 DEST。
- 增删、替换或移动子节点，通过父对象的实际字段或列表操作，再刷新覆盖全部变化的父对象或共同具名祖先。新建且未扫描的对象尚无 `edited()`。
- 多处关联修改先收集旧路径及引用，再用 `ArxmlTransaction.add(xml_obj)` 延迟刷新；上下文退出前不使用新索引查询。它不提供回滚或自动保存，失败后不得把当前内存对象视为已恢复。
- 重命名包或其他含后代的节点时，既要同步它自身的引用，也要同步所有后代的入向引用。可优先用下面的服务接口，避免只处理精确旧路径而漏掉后代。

核心库的 `edited()`、`save()` 和 `flush_to_file()` 不自动执行 MCP 校验。直接用核心对象编辑时，先验证 `file.render()` 生成的 XML，再检查业务条件；原文件备份、外部修改检测和写入失败处理由任务脚本负责。不要直接改本地服务的 `service.projects`、`_dirty` 或其他内部状态来发布任意对象修改。

下面的 XSD 检查函数使用当前绑定对应的本地 schema，不写盘；它只检查 XSD，不检查引用是否齐全或业务条件：

```python
from lxml import etree

from k3q_arxml import autosar
from k3q_arxml.schemas import SCHEMAS


def validate_xsd(io):
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    schema = etree.XMLSchema(etree.parse(str(SCHEMAS[autosar.SCHEMA_VERSION]), parser))
    for filepath, file in io.files.items():
        root = etree.fromstring(file.render().encode('utf-8'), parser)
        if not schema.validate(root):
            raise ValueError(f'{filepath}: {schema.error_log}')
```

文件声明版本和当前绑定不同，只能报告当前绑定 XSD 的校验结果；不能宣称已验证文件声明的其他版本。核心解析也不等同于 MCP 的严格绑定解析和 XML 往返校验。

## 将变更和验证固化为任务脚本

下面是一个可以保存为 `rename_task.py` 的完整模板。它使用本地服务执行重命名、同步已加载引用、检查预期路径，完整读取实际写盘差异；默认只预演，显式 `--save` 才写回。把业务变更集中在 `change_and_verify()`，其他固化操作也可以替换为 `patch_xml()`，并添加具体业务检查。

```python
import argparse
from pathlib import Path

from k3q_arxml.mcp.service import ArxmlMcpService


def verify(service, project_id, old_ref, new_ref):
    service.get_node(project_id, new_ref)
    if old_ref != new_ref:
        if service.find_nodes(project_id, ref_prefix=old_ref, limit=1).total:
            raise RuntimeError(f'旧节点或后代仍存在：{old_ref}')
        if service.find_references(project_id, old_ref, limit=1).total:
            raise RuntimeError(f'仍有引用指向旧节点：{old_ref}')
    validation = service.validate_project(project_id)
    print(validation.model_dump_json())
    if not validation.valid:
        raise RuntimeError('工程校验失败，停止保存。')


def change_and_verify(service, project_id, old_ref, new_name):
    service.get_node(project_id, old_ref)  # 原节点缺失就失败，不猜测已经执行成功。
    revision = service.project_info(project_id).revision
    result = service.rename_node(project_id, old_ref, new_name, revision)
    print(result.model_dump_json())
    verify(service, project_id, old_ref, result.new_ref)
    return result.new_ref


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('files', nargs='+')
    parser.add_argument('--workspace', type=Path, default=Path.cwd())
    parser.add_argument('--ref', required=True)
    parser.add_argument('--new-name', required=True)
    parser.add_argument('--save', action='store_true')
    args = parser.parse_args(argv)

    service = ArxmlMcpService(args.workspace)
    opened = service.open_project(args.files)
    print(opened.model_dump_json())
    project_id = opened.project_id
    new_ref = change_and_verify(service, project_id, args.ref, args.new_name)

    offset = 0
    while True:
        preview = service.preview_changes(project_id, offset=offset, limit=200, diff_mode='file')
        print(preview.model_dump_json())
        if preview.next_offset is None:
            break
        offset = preview.next_offset

    if args.save:
        saved = service.save_changes(project_id, preview.preview_token)
        print(saved.model_dump_json())  # 记录保存结果、备份路径和恢复清单。
        reloaded = service.open_project(args.files)
        verify(service, reloaded.project_id, args.ref, new_ref)
        service.close_project(reloaded.project_id)
    else:
        print('仅预演：未写盘；退出时丢弃本次脚本的候选修改。')
    service.close_project(project_id, discard_changes=not args.save)


if __name__ == '__main__':
    main()
```

运行时用实际目标替换示例路径，并加载所有希望同步引用的文件：

```console
python rename_task.py types.arxml interfaces.arxml --workspace "D:/模型目录" --ref /Types/Speed --new-name Velocity
python rename_task.py types.arxml interfaces.arxml --workspace "D:/模型目录" --ref /Types/Speed --new-name Velocity --save
```

若用户已授权修改并保存，可直接使用 `--save`，不重复请求确认。脚本失败时保留异常和已输出结果；最后的保存后复查如果失败，文件可能已经保存，不能报告成“完全未修改”。遇到冲突或恢复错误，按 [操作指南](mcp-workflows.md#错误处理与保存恢复)处理，不改用核心库直接覆盖原文件。

该模板第二次执行时旧路径已不存在，会明确失败；只有定义了具体“已完成”检查的任务才应支持跳过。批量任务需在修改前检查全部目标、重名冲突及规则覆盖范围；多次服务调用只各自原子，不构成整批事务。

## 需要固化的验证内容

把“预期变成什么”写进脚本，不只检查有没有异常：

1. 目标节点、类型、字段值及数量符合预期；确认没有误改相似名称的其他节点。
2. 重命名后新路径存在、旧路径消失；跨文件引用同步数量和来源符合任务预期。包重命名还要检查代表性的后代及其引用。
3. XSD、引用及往返检查分别说明实际执行了什么；既有外部引用警告不等于完整工程无问题。核心脚本需自行补齐服务没有执行的检查。
4. 测试使用临时副本；默认预演不改变原文件字节；失败不得继续保存；保存后重新加载并复查业务条件、备份和实际文件。
5. 重复执行要么经明确的完成条件安全跳过，要么因旧状态不符停止；不能把“没查到目标”一律视为成功。关键运行检查用显式异常，避免 `python -O` 去掉 assert 后继续写盘。

交付时提供脚本位置、实际执行命令、输入文件集合、修改和验证结果、是否保存及备份位置。脚本与 Skill 本身一起发布时，应验证导入无副作用、命令可运行和整目录复制后的本地链接；只更新仓库 Skill 不会改变已经上传的旧 PyPI 发行包。
