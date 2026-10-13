> **文件元信息**
> - **用途**：说明 BOSS 直聘薪资字体加密（@font-face woff2 私用区映射）的原理与 `decrypt_salary()` 解密公式、映射表及 off-by-one 历史错误，供薪资解析时对照。
> - **职责范围**：仅覆盖薪资解密算法与验证数据；不涉及选择器、投递或筛选逻辑。
> - **关联模块**：`webbridge_client.py`（模块：共享 HTTP 客户端，提供 `decrypt_salary()`）；列表页薪资由 `surface_cache.py` / `recommend_loader.py` 经 `extract_jobs()` 提取后调用解密，JD 详情页薪资由 `jd_reader.py` 读取后解密。
> - **维护状态**：有效（基线 2026-06-15）；当前协同版本 v5.6.1；迭代明细见 `CHANGELOG.md`。

# Boss 直聘薪资字体加密与解密

## 加密原理

Boss 直聘通过自定义 `@font-face`（woff2）将数字 0-9 映射到 Unicode 私用区 U+E031~U+E03A。

## 解密公式 (2026-06-15 修正)

```python
def decrypt_salary(text):
    result = []
    for ch in text:
        cp = ord(ch)
        if 0xE031 <= cp <= 0xE03A:
            result.append(str(cp - 0xE031))
        else:
            result.append(ch)
    return ''.join(result)
```

## 映射表 (2026-06-15 修正)

| Unicode | 解密结果 | 旧版错误 |
|---------|---------|---------|
| U+E031 | 0 | (旧: 1) |
| U+E032 | 1 | (旧: 2) |
| U+E033 | 2 | (旧: 3) |
| U+E034 | 3 | (旧: 4) |
| U+E035 | 4 | (旧: 5) |
| U+E036 | 5 | (旧: 6) |
| U+E037 | 6 | (旧: 7) |
| U+E038 | 7 | (旧: 8) |
| U+E039 | 8 | (旧: 9) |
| U+E03A | 9 | — |

## 旧版错误

旧版使用 `ord(ch) - 0xE030`，导致 **每位数字偏移 +1**（6→被解析为7，21→被解析为32...）。

例如：`\ue036-\ue037K`
- 旧版: 6-7K ❌
- 新版: 5-6K ✅

## 验证数据

| 加密原文 | 旧版结果 | 新版结果 |
|---------|---------|---------|
| `\ue036-\ue037K` | 6-7K ❌ | 5-6K ✅ |
| `\ue039-\ue032\ue033K` | 9-23K ❌ | 8-12K ✅ |

## 影响范围（与当前三层循环对齐）

- 列表页薪资加密 → 由 `surface_cache.py` / `recommend_loader.py` 调用 `webbridge_client.extract_jobs()` 提取原始加密薪资后，统一经 `webbridge_client.decrypt_salary()` 解密。
- 详情页（JD）薪资同样加密 → 由 `jd_reader.py` 读取后调用 `decrypt_salary()` 解密。
- `decrypt_salary()` 统一实现于 `webbridge_client.py`（模块：共享 HTTP 客户端），所有薪资解析均复用此函数，不再分散在各 phase 脚本中。
