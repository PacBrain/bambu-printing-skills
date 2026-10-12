# 自动化与文件接口

Python 3.10+，依赖见仓库 requirements。以技能目录为当前目录，替换示例路径：

若仓库有 `.venv`，优先使用该环境的 Python（macOS/Linux `.venv/bin/python`，Windows `.venv/Scripts/python.exe`）。没有依赖时按 README 安装，不跳过网格检查。

```bash
python scripts/bambu.py env
python scripts/bambu.py profiles --machine 'Bambu Lab H2S 0.4 nozzle' --process '0.20mm Standard @BBL H2S' --filament 'Bambu PLA Basic @BBL H2S' --output /tmp/job-config
python scripts/bambu.py slice --config-dir /tmp/job-config --bed 'Textured PEI Plate' --output /tmp/example.3mf /tmp/example.stl
python scripts/bambu.py inspect /tmp/example.3mf --output /tmp/inspection.json
```

`--binary`、`--profiles` 支持非默认安装。脚本不连接打印机。macOS 沙盒可能允许切片却阻断 OpenGL 缩略图；按需申请本地进程/图形访问，不关闭系统保护。

## 配置

递归读取 inherits/include，检查循环/缺失项，子项覆盖父项，记录源哈希。`--overrides` 的 JSON 顶层为 machine/process/filament；拒绝未知键和 G-code 改写。

CLI 对 User 配置通过 `inherits` 识别系统机型，因此 Prepared 配置在展开数值后仍保留官方身份字段。不能删除它或清空兼容列表绕过检查。[B24；本机测试]

保留变体数组，由原生切片器选择标准热端并核对最终路径参数。工具拒绝未经验证的非标准热端自动配置；多热端/多材料通过原生 Studio 配置、检查。

### 必须保留自定义差异

2.8.4 GUI 重开会用安装的系统预设刷新工程。只有完整数值但没有 `different_settings_to_system` 时，本机实测工艺改动会被恢复为默认。工具因此将显式 overrides 的键记录为差异，再核对输出值；最终仍要在 GUI 重开验证。

当前 `only_one_wall_top` 已废弃且被切片器忽略；对应现行字段为 `top_one_wall_type`，枚举 `not apply` / `all top` / `topmost`。关闭顶面单层墙使用 `not apply`。不能仅因旧字段存在于安装包的旧模板就认为它生效。依据：[官方 PrintConfig](https://github.com/bambulab/BambuStudio/blob/master/src/libslic3r/PrintConfig.cpp) 与本机输出/GUI 检查。

某些 macOS CLI 导出缺少 `slice_info.config` 的 `printer_model_id`，即使项目机型字段正确也不能直接标为机器执行文件已验收。最终板切片文件通过原生 Studio 导出，并核对机器 ID 与路径。

## 预检清单

`preflight manifest.json --machine-json machine.json --output report.json`：

```json
{
  "print_sequence": "by layer",
  "brim_width_mm": 5,
  "brim_gap_mm": 0.1,
  "additional_exclude_areas": [],
  "objects": [{"path": "/tmp/example.stl", "units": "mm", "center_xy_mm": [170, 160], "rotation_z_deg": 0}]
}
```

STL 无可靠单位，必须传 units；支持 mm/cm/m/inch，归一为 mm。静态预检包含封闭/法线/非流形、尺寸、裙边、禁止区和保守逐件净空；精确自交及壁厚明确标为 not_run。

## 验证与已知限制

`inspect` 跟随 3MF Production Extension 的多文件引用和变换，不仅读取根文件。[B21] 输出项目设置、对象/plate 元数据、路径和统计。

本机版本部分 G-code 体积字段的单位标签与数值不一致，不能直接当 cm³；交付优先用质量、长度、时间并核对量纲。

H2S 2.8.4 官方结束模板包含 `T65535`。原生时间解析器记录 `Invalid T command (T65535)` 但仍导出成功；测试确认指令来自未改动官方模板。保留日志并披露，不通过删除机器指令消除报错。其他错误不能类推忽略。

原生 Studio 重开属于验收。工程可打开、路径生成、实物打印分开记录，后缀不能替代检查。
