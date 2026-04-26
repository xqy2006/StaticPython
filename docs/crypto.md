# pycryptodome 静态集成笔记

## 目标

把完整的 `pycryptodome` 带进单文件静态 CPython：

- 不生成独立 `.pyd`
- 不引入第三方 DLL
- `Crypto` 纯 Python 包整体冻结进 `python.exe`
- 原生 C 部分编译成一个静态库 `_pycryptodome_raw.lib`
- 运行时从 `python.exe` 本体导出符号给 `Crypto.Util._raw_api` 使用

## 最终结构

### 纯 Python 层

- `Lib/Crypto/...`
  来自 `pycryptodome` 的整个 Python 包，直接参与冻结

### 原生层

- `pycryptodome_builtin/src/...`
  原始 C 源码
- `pycryptodome_builtin/embedded_marker.c`
  向最终可执行文件导出一个 `pycryptodome_embedded` 标记符号
- `PCbuild/_pycryptodome_raw.vcxproj`
  把所有原生源码编译成单个静态库 `_pycryptodome_raw.lib`

### 链接层

- `PCbuild/python.vcxproj`
  链接 `_pycryptodome_raw.lib`
- 同时使用 `/WHOLEARCHIVE:_pycryptodome_raw.lib`
  防止只靠延迟符号引用时被链接器裁掉对象文件

## 为什么不做成 builtin 扩展模块

这次没有把 `pycryptodome` 的原生部分做成一组 `PyInit_*` builtin 扩展模块，原因是它原本的设计并不是“每个原生文件都直接作为 Python 扩展模块导入”，而是：

- Python 层通过 `Crypto.Util._raw_api.load_pycryptodome_raw_lib(...)`
- 再用 `ctypes` / `cffi` 去找底层导出的 C 符号

所以更自然的方案是：

1. 保留 Python 层调用模型。
2. 把底层原生符号静态链接进最终 exe。
3. 让 `_raw_api.py` 优先从 `sys.executable` 里取符号。

## 关键改动

## 1. `Crypto.Util._raw_api`

修改文件：

- `Lib/Crypto/Util/_raw_api.py`

做了两件事。

### 优先从 `sys.executable` 读取原生符号

新增 `_load_embedded_process_lib()`：

- 仅在 `os.name == "nt"` 且 `backend == "ctypes"` 时启用
- 直接把 `sys.executable` 当作动态库加载
- 检查是否存在 `pycryptodome_embedded` 标记导出
- 命中后缓存句柄，并让 `load_pycryptodome_raw_lib()` 直接返回这个句柄

这样 `Crypto.Hash._poly1305`、`Crypto.Cipher._raw_aes`、`Crypto.PublicKey._ec_ws` 等符号就都从最终 exe 里解析，而不是去磁盘找 `.pyd`。

### 兼容静态构建里缺失的 `ctypes.pythonapi.PyObject_GetBuffer`

静态单文件构建下，`ctypes.pythonapi` 并不一定导出：

- `PyObject_GetBuffer`
- `PyBuffer_Release`

所以这里增加了回退路径：

- 如果拿不到这两个 API，就改用 `memoryview`
- 再配合 `ctypes.from_buffer()` / `from_buffer_copy()`
- 生成 `uint8_t*` 可读视图

这一步解决的是“没有 `python3*.dll` 可供 `ctypes.pythonapi` 找到导出”这一类问题。

## 2. Poly1305 符号改名

修改文件：

- `pycryptodome_builtin/src/poly1305.c`
- `Lib/Crypto/Hash/Poly1305.py`

原始导出名：

- `poly1305_init`
- `poly1305_destroy`
- `poly1305_update`
- `poly1305_digest`

改成：

- `pycryptodome_poly1305_init`
- `pycryptodome_poly1305_destroy`
- `pycryptodome_poly1305_update`
- `pycryptodome_poly1305_digest`

原因是静态链接环境里这些通用名字和其他库发生碰撞的风险很高，尤其你这棵树里本来就带 OpenSSL。Python 层的 `Poly1305.py` 也同步改成按新名字声明和调用。

## 3. `bignum.c` 的 `sub_mod` 改成内部符号

修改文件：

- `pycryptodome_builtin/src/bignum.c`

把：

```c
int sub_mod(...)
```

改成：

```c
STATIC int sub_mod(...)
```

这是为了解决静态全局符号暴露过多时的碰撞风险。这个函数本来就是内部实现细节，不需要出现在最终可执行文件的全局符号表里。

## 4. 独立静态工程 `_pycryptodome_raw.vcxproj`

这个工程做的事是：

- 包含 `pycryptodome_builtin/src` 和 `src/libtom`
- 定义：
  - `NO_CPYTHON_MODULE`
  - `HAVE_STDINT_H`
  - `PYCRYPTO_LITTLE_ENDIAN`
  - `LTC_NO_ASM`
- x64 下再加：
  - `SYS_BITS=64`
  - `HAVE_INTRIN_H`
  - `USE_SSE2`
  - `HAVE_WMMINTRIN_H`
  - `HAVE_TMMINTRIN_H`
- 输出静态库 `_pycryptodome_raw.lib`
- 使用 `/MT`

ARM / ARM64 会移除：

- `AESNI.c`
- `ghash_clmul.c`

避免不支持的指令路径被编译进去。

## 冻结层

`Crypto` 整包不是 zip，也不是旁路目录，而是进入了当前自定义的冻结流程：

- `Tools/build/freeze_modules.py --step=0`
- `Tools/build/freeze_modules.py --step=1`

这份冻结脚本会遍历 `Lib`，把合法模块名和包名全部生成到 `Python/frozen_modules`。

后面又补了一次修正，让包模块在 `frozen.c` 里保留正确的 package 元数据，因此现在：

- `__spec__.origin == "frozen"`
- `__package__ == __spec__.parent` 对包不再错位

## 验证结果

已经确认过的结果：

- `Crypto`, `Crypto.Cipher.AES`, `Crypto.Hash.SHA256`, `Crypto.PublicKey.RSA`, `Crypto.Util._raw_api` 都来自 `origin='frozen'`
- `python.exe -m Crypto.SelfTest` 最终结果是 `Ran 3553 tests ... OK`
- 没有再出现 `__package__ != __spec__.parent` 的 warning
- 最终 exe 导入表里没有 `python3*.dll`
- 没有 `vcruntime*.dll`
- 没有第三方非系统 DLL

## 许可证

`pycryptodome` 是开源的。

按 `pycryptodome_builtin/LICENSE.rst`：

- 一部分代码来自 `PyCrypto`，按 public domain 处理
- 直接贡献给 `PyCryptodome` 的部分按 BSD 2-Clause license 发布

所以它非常适合这种静态整合方案，但分发时仍然建议把许可证文本一起保留。
