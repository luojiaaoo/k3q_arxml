# 开发与 PyPI 发布

本文面向维护者，命令使用 Windows PowerShell，在仓库根目录执行。用户安装和使用说明见 [README.md](README.md)，MCP 操作说明见 [MCP.md](MCP.md)。

## 当前状态

当前发行名为 `k3q-arxml`，Python 导入名为 `k3q_arxml`，包版本由 `pyproject.toml` 的 `[project].version` 决定，当前为 `2.1.0`，对应 Git 标签 `v2.1.0`。Git 标签不会自动改变包版本。

仓库已配置 Hatchling 构建后端及发行文件范围，可直接按下文构建。`git push` 只更新 Git 仓库，上传 PyPI 还需要构建和发布发行文件。

依赖在 `pyproject.toml` 中声明最低版本和兼容上界，让安装者可以解析兼容版本；仓库开发通过 `uv.lock` 和 `uv sync --locked` 复现已验证的精确版本。下文安装命令中的 `==2.1.0` 用于核验指定发行包。

## 打包配置

`pyproject.toml` 中的打包配置如下：

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.uv]
package = false

[tool.hatch.build.targets.wheel]
packages = ["k3q_arxml"]

[tool.hatch.build.targets.wheel.force-include]
"skills" = "k3q_arxml/skills"

[tool.hatch.build.targets.sdist]
include = [
    "/k3q_arxml",
    "/skills",
    "/README.md",
    "/LICENSE",
    "/pyproject.toml",
]

[tool.hatch.build]
exclude = [
    "**/__pycache__",
    "**/*.pyc",
    "/k3q_arxml/.codegen-*",
]
```

wheel 包含 Python 库、MCP 子包、默认的真实 `autosar.py`、`schemas/` 下全部 AUTOSAR XSD 和关联 `xml.xsd`，以及 `k3q_arxml/skills/arxml-mcp` 技能目录。运行时通过包内路径查找 XSD，不能只打包 `.py` 文件。

`tool.uv.package = false` 保持仓库通过源码运行，`uv sync` 不自动安装项目自身，避免 Windows Python 3.11 在中文路径下读取可编辑安装的 `.pth` 文件时出现编码错误。`uv build` 仍使用 Hatchling 构建发行包，用户可正常安装 wheel。

sdist 包含构建 wheel 所需的包源码、`pyproject.toml`、包介绍 `README.md`、许可证 `LICENSE` 和原始 `skills/` 目录；从 sdist 构建 wheel 时使用同一映射。Hatchling 还会自动附带 `PKG-INFO` 和 `.gitignore`。测试、名称处理脚本及开发说明保留在 Git 仓库，不放入发行包。

用户可从仓库的 `skills/arxml-mcp` 或已安装包的 `k3q_arxml/skills/arxml-mcp` 复制完整目录到智能体的技能目录。安装包内路径可用 `python -c "from importlib.resources import files; print(files('k3q_arxml').joinpath('skills', 'arxml-mcp'))"` 查看；复制方式见 README。安装 Python 包不会自动复制 Skill 或注册 MCP。

无需添加控制台脚本入口，已有 `__main__.py` 支持 `python -m k3q_arxml`。Hatchling 的构建系统及文件选择规则见 [官方文档](https://hatch.pypa.io/latest/config/build/)。

## 发布前验证与版本号

先安装包含 MCP 的完整开发环境：

```powershell
uv sync --locked --extra mcp
uv run python -c "from k3q_arxml import autosar; print(autosar.SCHEMA_VERSION)"
```

发布包应携带默认的 4.2.2 绑定。如果输出其他版本，在停止使用本环境的 MCP 后执行 `uv run -m k3q_arxml generate 4.2.2`，再验证。不要在构建过程中生成全部版本。

检查目标 PyPI 项目的所有权、已有版本及待发布内容。以下以 `2.1.0` 为例；若该版本已使用，应选择新的版本，并同步替换后文目录、文件名和安装命令中的版本号。PyPI 已上传的发行文件不能用不同内容覆盖，即使删除也不能重用该文件名。详见 [PyPI 帮助](https://pypi.org/help/#file-name-reuse)。

修改 `[project].version` 后更新锁文件，并执行：

```powershell
uv lock
uv sync --locked --extra mcp
uv run pytest -v
uv run ruff check k3q_arxml tests chg_adt_name.py chg_adt_idt_name.py
uv run ruff format --check k3q_arxml tests chg_adt_name.py chg_adt_idt_name.py
uv lock --check
git diff --check
git status --short
```

确认测试实际执行，尤其是 MCP stdio 测试没有因缺少依赖而跳过。新增打包配置后，将 `pyproject.toml` 与更新后的 `uv.lock` 一起纳入本次发布提交。

## 构建与检查发行文件

使用本次版本的独立输出目录，避免上传旧版本文件：

```powershell
uv build --no-sources --out-dir dist/2.1.0
uvx --from twine twine check --strict dist/2.1.0/*.whl dist/2.1.0/*.tar.gz
uv run python -m zipfile -l dist/2.1.0/k3q_arxml-2.1.0-py3-none-any.whl
uv run python -m tarfile -l dist/2.1.0/k3q_arxml-2.1.0.tar.gz
```

应得到一个 `.whl` 和一个 `.tar.gz`。确认 wheel 中存在 `k3q_arxml/autosar.py`、`k3q_arxml/__main__.py`、`k3q_arxml/mcp/server.py`、所有 XSD，以及完整的 `k3q_arxml/skills/arxml-mcp` 目录；sdist 应包含同一份代码、schema 和 `skills/arxml-mcp`。确认 Skill 的所有本地文档链接在整目录复制后仍可用，且没有临时 ARXML、备份或恢复清单。构建目录和输出文件的行为见 [uv 发布指南](https://docs.astral.sh/uv/guides/package/)。

在独立临时环境安装 wheel，避免误用仓库源码：

```powershell
$wheel = (Resolve-Path 'dist/2.1.0/k3q_arxml-2.1.0-py3-none-any.whl').Path
$checkDir = Join-Path ([System.IO.Path]::GetTempPath()) ('k3q-arxml-release-' + [guid]::NewGuid())
uv venv $checkDir --python 3.11
$checkPython = Join-Path $checkDir 'Scripts/python.exe'
uv pip install --python $checkPython "$wheel[mcp]"
& $checkPython -I -c "from k3q_arxml import IOArxml, autosar; from k3q_arxml.schemas import SCHEMAS; print(autosar.SCHEMA_VERSION); print(SCHEMAS); assert SCHEMAS and all(p.is_file() for p in SCHEMAS.values())"
& $checkPython -I -m k3q_arxml versions
& $checkPython -I -m k3q_arxml mcp --help
```

`-I` 避免当前目录及 `PYTHONPATH` 中的源码遮住已安装包。还应在这个环境中用真实 MCP 客户端完成一次连接和工具发现；测试编辑、保存时只使用临时模型副本。另建环境安装 sdist，确认它也能构建和导入。

## 可选：先上传 TestPyPI

分别注册 [TestPyPI](https://test.pypi.org/account/register/) 和 [PyPI](https://pypi.org/account/register/) 账号，按站点要求完成验证和双因素认证。两个站点的账号、项目与 API token 相互独立。

在 TestPyPI 的账号设置创建 API token。首次创建项目时可使用具有相应账号权限的 token，项目创建后使用项目范围 token。下面通过隐藏输入读取 token，不将实际 token 写进文件：

```powershell
$publishSecret = Read-Host 'TestPyPI API token' -AsSecureString
$env:UV_PUBLISH_TOKEN = [System.Net.NetworkCredential]::new('', $publishSecret).Password
try {
    uv publish --publish-url https://test.pypi.org/legacy/ dist/2.1.0/*.whl dist/2.1.0/*.tar.gz
    if ($LASTEXITCODE -ne 0) { throw 'TestPyPI 上传失败' }
} finally {
    Remove-Item Env:UV_PUBLISH_TOKEN
}
```

上传成功后，在另一个临时环境中验证测试站上的包。为避免从 TestPyPI 解析完整依赖树，先从正式 PyPI 安装与本次 wheel 相同的依赖，再只替换测试包：

```powershell
$testDir = Join-Path ([System.IO.Path]::GetTempPath()) ('k3q-arxml-testpypi-' + [guid]::NewGuid())
uv venv $testDir --python 3.11
$testPython = Join-Path $testDir 'Scripts/python.exe'
uv pip install --python $testPython "$wheel[mcp]"
uv pip install --python $testPython --no-deps --reinstall --index-url https://test.pypi.org/simple/ 'k3q-arxml==2.1.0'
& $testPython -I -c "from k3q_arxml import IOArxml, autosar; print(autosar.SCHEMA_VERSION)"
& $testPython -I -m k3q_arxml versions
```

安装命令失败时先停止后续验证，不能把原有本地 wheel 的导入成功当作 TestPyPI 安装成功。测试站的上传和安装地址不同，前者是 `/legacy/`，后者是 `/simple/`。更多说明见 [PyPA 发布教程](https://packaging.python.org/en/latest/tutorials/packaging-projects/)。

## 上传正式 PyPI

完成发行文件检查和独立环境安装验证后，先提交发布内容、创建 `v2.1.0` 标签并推送远程仓库，再使用正式 PyPI 创建的 token 上传已经验证过的同一组文件。配置了 TestPyPI 时，可先完成上一节的测试发布。

```powershell
$publishSecret = Read-Host 'PyPI API token' -AsSecureString
$env:UV_PUBLISH_TOKEN = [System.Net.NetworkCredential]::new('', $publishSecret).Password
try {
    uv publish --publish-url https://upload.pypi.org/legacy/ dist/2.1.0/*.whl dist/2.1.0/*.tar.gz
    if ($LASTEXITCODE -ne 0) { throw 'PyPI 上传失败' }
} finally {
    Remove-Item Env:UV_PUBLISH_TOKEN
}
```

发布完成后，从仓库外的新环境安装并验证：

```powershell
$releaseDir = Join-Path ([System.IO.Path]::GetTempPath()) ('k3q-arxml-pypi-' + [guid]::NewGuid())
uv venv $releaseDir --python 3.11
$releasePython = Join-Path $releaseDir 'Scripts/python.exe'
uv pip install --python $releasePython 'k3q-arxml[mcp]==2.1.0'
& $releasePython -I -c "from k3q_arxml import IOArxml, autosar; print(autosar.SCHEMA_VERSION)"
& $releasePython -I -m k3q_arxml versions
```

客户端可将 `command` 指向安装环境的 `python.exe`，`args` 设为 `["-m", "k3q_arxml", "mcp"]`，`cwd` 指向业务模型目录；安装后的包无需额外设置源码 `PYTHONPATH`。Skill 仍单独安装。

确认 PyPI 页面、安装结果与远程发布提交及标签对应。后续更新按“新版本号 → 验证 → 构建 → 推送提交与标签 → 可选 TestPyPI → 正式 PyPI”重复；自动发布可后续接入 [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/)，不需要把长期 token 存入仓库。
