# 第三方库解耦集成布局

## 目标

当前 builder 已经把第三方库集成从单一主脚本里的集中配置，拆成“每个库一个目录、每个库一份 setup 脚本”的布局，方便按库增删、更新和排错。

当前实现还有两个硬约束：

- 不依赖“某个 CPython 版本的固定 diff hunk”去打补丁
  - 优先按源码特征、标记位、XML 结构节点做匹配和注入
- 不手写原生源文件总表
  - 优先从上游项目元数据或目录规则动态发现 `c/cpp` 源文件

## 当前布局

- `manifest.json`
  - 只保留 CPython 核心构建元数据
  - 例如标准扩展静态化、OpenSSL/libffi/liblzma 等基础依赖
  - OpenSSL 和 libffi 的 `.lib` 不作为仓库资产保存，而是在 builder 运行时按 CPython 元数据识别版本、下载源码并静态编译
- `config.json`
  - 控制构建 profile
  - 当前内置 `stdlib` 和 `full`
  - `stdlib` 不启用 `Lib/*/setup.py` 第三方库，只构建静态标准库
  - `full` 使用全部第三方库集成
  - `third_party_libraries` 可以是 `"all"`，也可以是具体库名列表
- `Lib/<库名>/setup.py`
  - 每个第三方库自己的集成入口
  - 描述这个库如何取源、要复制哪些非源码素材、验证什么、是否带原生工程、是否要注册 builtin、是否需要额外链接项
- `Lib/<库名>/**/*.patch`
  - 这个库自己的补丁
  - 只存放 unified diff，不再和别的库混在一起
- `downloads`
  - 上游源码归档缓存
  - 第二次构建时直接复用，不重复下载
- `.vendor-stage`
  - 上游归档解包后的临时工作区
- `assets/overlay/...`
  - 只保留非源码素材
  - `setup.py` 只声明要用哪些 overlay 条目

## `setup.py` 可声明的内容

`libs.py` 里统一定义了 `LibraryIntegration`，当前已经用到这些字段：

- `overlay_entries`
  - 需要复制到 CPython 源树的目录或文件
- `python_packages`
  - 导入验证时要检查的顶层包
- `verification_imports`
  - 额外要验证的子模块导入
- `static_library_projects_release_x64`
  - 需要参与构建的额外 `.vcxproj`
- `native_static_projects`
  - 需要补进 `python.vcxproj` 的 `ProjectReference`
- `builtin_module_registrations`
  - 要写进 `PC/config.c` 的 builtin 模块注册
- `python_link_dependencies_release_x64`
  - 要追加到 `python.vcxproj` 的静态链接库
- `python_link_wholearchive_release_x64`
  - 要追加的 `/WHOLEARCHIVE:*`
- `verification_steps`
  - 这个库自己的额外验证步骤
- `prepare_source_hooks`
  - 在复制 overlay 之前执行的取源 / 落地逻辑
- `post_patch_hooks`
  - 在通用补丁完成后执行的库专属逻辑

## 当前特殊库

### `Lib/Crypto/setup.py`

- 从 PyPI 下载 `pycryptodome`
- 把 `Crypto` 和 `src` 分别落到 `Lib/Crypto`、`pycryptodome_builtin/src`
- 额外保留一份上游 `setup.py`，供 builder 动态解析 `Extension(..., sources=...)`
- `_pycryptodome_raw.vcxproj` 不再维护手写源文件名单，而是按上游 `setup.py` 自动汇总原生源文件
- 负责 `_pycryptodome_raw.lib` 和 `/WHOLEARCHIVE:_pycryptodome_raw.lib`
- 负责 `Crypto.SelfTest`

### `Lib/libui/setup.py`

- 从 PyPI 下载 `libui`
- 把 `libui`、`src/libui-ng`、`src/py_module` 分别落到 `Lib/libui`、`libui_builtin/libui-ng`、`libui_builtin/py_module`
- 负责 `test_libui.py` / `test_libui_gui.py` / `libui_smoke_test.py`
- 负责 `_libui_core.vcxproj`
- 负责 `_libui_core` builtin 注册
- 负责 GUI 相关链接项
- 负责 libui smoke + unit + GUI unit 测试

### `Lib/tzdata/setup.py`

- 从 PyPI 下载 `tzdata`
- 负责把 `tzdata` 压进 `Lib/tzdata/__init__.py`
- 负责补 `zoneinfo/_common.py` 和 `zoneinfo/_tzpath.py`

## 普通库的最小写法

大部分纯 Python 库只需要：

```python
from libs import simple_library


LIBRARY_INTEGRATION = simple_library(name="requests", overlay_entries=["Lib/requests"])
```

## 增加一个新库

1. 在 `Lib/<库名>/setup.py` 里声明这个库的取源方式，优先 PyPI，不够时用 GitHub archive。
2. 如果这个库需要额外的非源码素材，再把这些素材整理到 `assets/overlay`。
3. 如果这个库需要改源码，优先在 `setup.py` 里写基于特征的文本或结构变换，而不是写死版本相关的 hunk。
4. 如果这个库带原生扩展，优先从上游 `setup.py`、`pyproject.toml`、`meson.build` 或稳定目录规则自动发现源文件。
5. 如果默认全量构建要带上这个库，确认 `config.json` 的 `full` profile 仍然是 `"all"`，或者把库名加入自定义 profile。
6. 运行 builder 和 verifier，确认实际编译通过。

## 删除一个库

1. 删除 `Lib/<库名>/setup.py`。
2. 删除这个库对应的非源码 `assets/overlay` 素材。
3. 删除这个库自己的 `.patch`。
4. 如果 `config.json` 里有显式 profile 列表，也要删除对应库名。
5. 重新编译验证。

## 当前验证状态

- `3.11`、`3.12`
  - 之前旧架构下做过验证
- `3.13`
  - 已在新解耦架构下重新实际编译并通过全量验证
  - 报告：`verify-report-3.13-decoupled.json`
- `3.14`、`3.15`
  - 截至当前还没有做实际编译验证

## 当前已解耦管理的第三方库

当前 `Lib/*/setup.py` 已覆盖：

- `annotated_doc`, `anyio`, `asgiref`, `attr`, `attrs`, `blinker`, `bs4`, `cattr`, `cattrs`, `certifi`, `charset_normalizer`, `click`, `colorama`, `comtypes`, `Crypto`, `dateutil`, `django`
- `dotenv`, `et_xmlfile`, `flask`, `h11`, `httpcore`, `httpx`, `idna`, `itsdangerous`, `jinja2`, `libui`, `loguru`, `markdown`, `markdown_it`, `markupsafe`, `mdurl`, `mistune`
- `mpmath`, `networkx`, `openpyxl`, `packaging`, `prompt_toolkit`, `pygments`, `pymysql`, `pypdf`, `pyperclip`, `redis`, `requests`, `rich`, `shellingham`, `six`, `sniffio`
- `soupsieve`, `sqlparse`, `sympy`, `tabulate`, `tenacity`, `tomlkit`, `tqdm`, `typer`, `typing_extensions`, `tzdata`, `urllib3`, `wcwidth`, `werkzeug`, `win32_setctime`, `xlsxwriter`
