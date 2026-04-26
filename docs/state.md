# 当前单文件构建状态清单

这份清单不是旧 md 的复述，而是根据当前 builder 仓库和实际编译结果整理出来的状态说明，补上之前容易漏掉的依赖、步骤和验证结论。

## 最新验证结论

- `3.11`
  - 旧架构下已做过验证
- `3.12`
  - 旧架构下已做过验证
- `3.13`
  - 已在当前解耦架构下重新实际编译并通过全量验证
  - 验证报告：`verify-report-3.13-decoupled.json`
- `3.14`
  - 截至当前还没有做实际编译验证
- `3.15`
  - 截至当前还没有做实际编译验证

## 当前目标形态

- Windows x64
- builder 目标版本范围是 `3.11+`
- 当前最新实际全量验证版本是 `3.13.13`
- 最终输出是单个 `python.exe`
- 当前支持两个发布 profile：`stdlib` 只带静态标准库，`full` 额外带所有第三方库
- 不依赖 `python3*.dll`
- 不依赖 `vcruntime*.dll`
- 标准库主体通过冻结进入可执行文件
- 部分 C 扩展模块改成 builtin 或静态链接
- 第三方源码按需下载后放进 `Lib` 再冻结，归档缓存放在 `downloads`
- OpenSSL 和 libffi 都从上游源码归档静态编译，仓库不携带这些基础库的 `.lib` 二进制资产

如果把这套状态抽象成自动 builder，版本判断策略应该是：

- `>= 3.13`：按当前 3.13 路线，包含 `_pyrepl` 额外冻结
- `< 3.13`：按 3.12 及更早路线，跳过 `_pyrepl`

## 当前第三方库管理方式

第三方库已经不再集中写在主脚本或单个 manifest 字段里，而是改成：

- `config.json`
  - 控制当前构建启用哪些第三方库
  - `stdlib` 使用空第三方库列表
  - `full` 使用全部第三方库
- `Lib/<库名>/setup.py`
  - 每个库自己的集成入口
- `Lib/<库名>/**/*.patch`
  - 每个库自己的补丁
- `assets/overlay/...`
  - 每个库自己的非源码素材
- `downloads/...`
  - 上游源码归档缓存

也就是说，当前增删第三方库的最小操作单位已经是“一个库一个目录”。

当前已经切成独立 `setup.py` 的第三方库有：

- `annotated_doc`, `anyio`, `asgiref`, `attr`, `attrs`, `blinker`, `bs4`, `cattr`, `cattrs`, `certifi`, `charset_normalizer`, `click`, `colorama`, `comtypes`, `Crypto`, `dateutil`, `django`
- `dotenv`, `et_xmlfile`, `flask`, `h11`, `httpcore`, `httpx`, `idna`, `itsdangerous`, `jinja2`, `libui`, `loguru`, `markdown`, `markdown_it`, `markupsafe`, `mdurl`, `mistune`
- `mpmath`, `networkx`, `openpyxl`, `packaging`, `prompt_toolkit`, `pygments`, `pymysql`, `pypdf`, `pyperclip`, `redis`, `requests`, `rich`, `shellingham`, `six`, `sniffio`
- `soupsieve`, `sqlparse`, `sympy`, `tabulate`, `tenacity`, `tomlkit`, `tqdm`, `typer`, `typing_extensions`, `tzdata`, `urllib3`, `wcwidth`, `werkzeug`, `win32_setctime`, `xlsxwriter`

## 当前补丁原则

- CPython 核心工程文件优先按 XML 结构节点补丁，不按整段文本 diff 替换。
- C/Python 源码补丁优先按标记、函数签名、模块注册锚点做匹配，不做“这个版本一套、下个版本再特判一套”的 hunk 维护。
- 第三方原生库优先从上游元数据动态发现源文件。
  - 当前 `pycryptodome` 已经改成直接解析上游 `setup.py` 里的 `Extension(..., sources=...)`
  - `libui` 本身使用通配符项目项来覆盖 `py_module/*.c`、`common/*.c`、`windows/*.cpp`
  - `libffi` 根据 CPython 元数据识别版本后，从官方源码包生成头文件并用 `cl`/`ml64`/`lib` 产出静态 `ffi.lib`

## 当前已经带进去的原生静态工程

### libui

- `PCbuild/_libui_core.vcxproj`
- `libui_builtin/libui-ng/...`
- `libui_builtin/py_module/...`

输出：

- `_libui_core.lib`

对 Python 的暴露方式：

- `PC/config.c` 里注册 builtin 模块 `_libui_core`
- `Lib/libui/core.py` 再做 Python 层封装

### pycryptodome

- `PCbuild/_pycryptodome_raw.vcxproj`
- `pycryptodome_builtin/...`

输出：

- `_pycryptodome_raw.lib`

对 Python 的暴露方式：

- 不走 `PyInit_*` builtin 模块
- 纯 Python 的 `Crypto` 包被冻结
- `_raw_api.py` 运行时直接从 `python.exe` 读取原生导出

## 当前 `PC/config.c` 里的 builtin 扩展模块

你当前这棵树实际带进去的关键 builtin C 扩展包括：

- `_ctypes`
- `_socket`
- `select`
- `pyexpat`
- `unicodedata`
- `_sqlite3`
- `_decimal`
- `winsound`
- `_asyncio`
- `_hashlib`
- `_overlapped`
- `_multiprocessing`
- `_ssl`
- `_bz2`
- `_lzma`
- `_wmi`
- `_zoneinfo`
- `_uuid`
- `_queue`
- `_libui_core`

这份清单对“单文件静态构建到底依赖哪些 `.lib`”非常关键，因为最终 `python.exe` 的链接项需要和这些 builtin 模块对齐。

## `python.vcxproj` 里现在真实链接进去的 Release x64 依赖

下面这串是当前实际在 `python.vcxproj` 的 `AdditionalDependencies` 里出现的内容，不再只凭旧笔记回忆：

- `Propsys.lib`
- `libssl.lib`
- `libcrypto.lib`
- `winmm.lib`
- `oleaut32.lib`
- `wbemuuid.lib`
- `ole32.lib`
- `Crypt32.lib`
- `legacy_stdio_definitions.lib`
- `bcrypt.lib`
- `version.lib`
- `ws2_32.lib`
- `pathcch.lib`
- `comctl32.lib`
- `uxtheme.lib`
- `msimg32.lib`
- `comdlg32.lib`
- `d2d1.lib`
- `dwrite.lib`
- `oleacc.lib`
- `uuid.lib`
- `windowscodecs.lib`
- `_socket.lib`
- `_ctypes.lib`
- `select.lib`
- `pyexpat.lib`
- `unicodedata.lib`
- `Iphlpapi.lib`
- `Rpcrt4.lib`
- `_decimal.lib`
- `winsound.lib`
- `_asyncio.lib`
- `_hashlib.lib`
- `_multiprocessing.lib`
- `ffi.lib`
- `_sqlite3.lib`
- `_ssl.lib`
- `_elementtree.lib`
- `_bz2.lib`
- `_lzma.lib`
- `_wmi.lib`
- `_zoneinfo.lib`
- `_uuid.lib`
- `_queue.lib`
- `_libui_core.lib`
- `_pycryptodome_raw.lib`
- `sqlite3.lib`
- `_overlapped.lib`
- `liblzma.lib`

额外注意：

- 这里现在是 `ffi.lib`，不是旧记录里常见的 `libffi-8.lib`
- `pycryptodome` 还需要 `/WHOLEARCHIVE:_pycryptodome_raw.lib`

## 当前单文件构建还依赖哪些 externals

除了系统 SDK 自带的 `.lib`，当前构建仍然依赖 `get_externals.bat` 拉下来的这些组件：

- OpenSSL
  - builder 现在先自动识别当前 CPython 声明的 `openssl-<version>`
  - 源码归档优先从 GitHub OpenSSL tag 下载并缓存到 `downloads/openssl`
  - 解包后放入目标树 `externals/openssl-<version>`，再静态编译
  - 解包时会跳过 `NUL` 等 Windows 设备保留名，避免源码树在 Windows 上无法清理
  - 输出并链接 `externals/openssl-static/<arch>/libssl.lib`
  - 输出并链接 `externals/openssl-static/<arch>/libcrypto.lib`
  - 仓库不再携带 OpenSSL `.lib` 二进制资产
- SQLite
  - `sqlite3.lib`
- libffi
  - builder 现在先自动识别当前 CPython 声明的 `libffi-<version>`
  - 源码归档优先从 GitHub libffi release 下载并缓存到 `downloads/libffi`
  - 解包后放入目标树 `externals/libffi-<version>`，再静态编译
  - 输出并链接 `externals/libffi-<version>/<arch>/ffi.lib`
  - `PCbuild/libffi.props` 会改成链接 `ffi.lib`，并移除 `libffi-8.dll` 复制目标
  - 仓库不再携带 libffi `.lib` 二进制资产
- liblzma
  - `liblzma.lib`
- zlib
  - 由 `pythoncore.vcxproj` 直接把 zlib 源码编进来
- bzip2
  - 由 `_bz2.vcxproj` 使用 externals 源码编译
- expat
  - `pyexpat.vcxproj` 使用 externals

所以“单文件”并不等于“完全不需要 externals”；它只是把最终运行时依赖压到了 exe 本体里。

## 当前必须保留的几个关键改动点

### `Lib/site.py`

必须把：

```python
ver_nodot = sys.winver.replace('.', '')
```

改成固定版本字符串形式。当前是：

```python
ver_nodot = "3.13".replace('.', '')
```

否则单文件静态构建下，Windows 用户 site-packages 路径推导会出问题。

### `Modules/getpath.py`

旧文档里提到的：

```python
warn('Could not find platform independent libraries <prefix>')
```

现在也一并在 builder 里自动处理了，会改成 `pass`，避免单文件静态构建下每次启动都弹这条旧警告。

### `Lib/_pyrepl/__main__.py`

必须补上：

```python
__package__ = '_pyrepl'
__path__ = [__name__]
```

否则单独冻结 `_pyrepl` 入口时包上下文不对。

### `Tools/build/freeze_modules.py`

你现在实际用的是一份大改版冻结脚本，和官方原版差异很大：

- 遍历整棵 `Lib`
- 自动生成 `Python/frozen_modules/*.h`
- 为包头自动补 `__package__` / `__path__`
- step 0 负责生成模块头
- step 1 负责重建 `Makefile.pre.in`、`PCbuild/_freeze_module.vcxproj`、`Python/frozen.c`
- 对 package entry 额外保留包元数据

所以新工程里直接带了一份当前可工作的版本，而不是试图只补几行小 patch。

### `Python/frozen_modules/getpath.h`

对 3.12 以及可能存在同类行为的其它版本，builder 现在会在冻结步骤之后检查：

- 如果 `Python/frozen_modules/getpath.h` 已经存在，就直接继续
- 如果只有 `PCbuild/obj/.../getpath.g.h`，就自动复制并重命名成 `Python/frozen_modules/getpath.h`

这样就不需要再手工去 `_freeze_module` 的中间产物目录里翻文件了。

## 当前冻结流程

顺序仍然是：

1. 先编 `_freeze_module.vcxproj`
2. `freeze_modules.py --step=0`
3. `freeze_modules.py --step=1`
4. 如有需要，自动补 `getpath.g.h -> Python/frozen_modules/getpath.h`
5. 当目标版本 `>= 3.13` 时，脚本额外再冻结一次 `_pyrepl`
6. 编自定义静态库
7. 编最终 `python.exe`

当目标版本 `>= 3.13` 时，`_pyrepl` 这一步仍然需要保留：

```powershell
PCbuild\amd64\_freeze_module.exe _pyrepl .\Lib\_pyrepl\__main__.py .\Python\frozen_modules\_pyrepl.h
```

## 当前验证结果

已经确认过的结果包括：

- `python.exe -m Crypto.SelfTest`:
  - `Ran 3553 tests ... OK`
- `Crypto` 各层包是 `origin='frozen'`
- `python.exe` 导入表里只有系统 DLL
- 最终确认没有：
  - `python3*.dll`
  - `vcruntime*.dll`
  - 第三方运行时 DLL

实际看到的系统 DLL 依赖是：

- `bcrypt.dll`
- `VERSION.dll`
- `WS2_32.dll`
- `api-ms-win-core-path-l1-1-0.dll`
- `IPHLPAPI.DLL`
- `RPCRT4.dll`
- `ADVAPI32.dll`
- `KERNEL32.dll`
- `USER32.dll`
- `GDI32.dll`
- `PROPSYS.dll`
- `WINMM.dll`
- `OLEAUT32.dll`
- `ole32.dll`
- `CRYPT32.dll`
- `COMCTL32.dll`
- `UxTheme.dll`
- `d2d1.dll`
- `DWrite.dll`

## libui 相关验证文件

当前树里已经有这几份验证脚本，可以继续沿用：

- `libui_smoke_test.py`
- `Lib/test/test_libui.py`
- `Lib/test/test_libui_gui.py`

如果你后续再扩 `libui` 绑定层，优先把测试补在这里，而不是只做一次手工点击验证。
