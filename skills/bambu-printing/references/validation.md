# 验证记录

## 脚本更新

[PR #1](https://github.com/PacBrain/bambu-printing-skills/pull/1) 于 2026-10-13 合并。测试环境为 macOS 27.0.1 arm64、Bambu Studio 02.08.04.57 Public Beta、Python 3.14。

| 项目 | 结果 | 范围 |
|---|---|---|
| 离线回归 | 64 项通过 | 配置、模型准备、3MF、路径、作业隔离、安装与技能包 |
| 跨平台 CI | 通过 | Windows、macOS、Linux × Python 3.10/3.14 |
| Agent Skills 格式 | 通过 | 官方 skills-ref，固定提交 `69ef37e9424c0a7ea9dd2293b559e43ec8176379` |
| 原生 CLI 切片与重切片 | 通过 | H2S、0.4 mm 标准喷头、PLA Basic、Textured PEI |
| 本次 GUI 重开 | 待确认（`not_run`） | 文件对话框操作后，窗口工具返回 `noWindowsAvailable` / `timeoutReached` |
| 高流量、多喷头、多材料、多盘和可变层高自动化 | `not_run` | 操作指导见对应参考资料 |
| 其他平台的原生 Studio、物理打印和性能试验 | `not_run` | 按目标环境与设备安排验证 |

离线命令：`python -m unittest discover -s tests -v`。原生维护者测试：`tests/native_integration.py run --output-dir NEW_DIRECTORY`。

## 原生 CLI 回归（2026-10-12）

- 两个不同位置的非等边合成箱体分别由厘米、英寸转换为毫米。
- 第一件旋转 90° 后为 10 × 20 × 7 mm，中心 (80, 95)；第二件约 12.7 × 7.62 × 5.08 mm，中心 (225, 180)。身份、数量、尺寸和全部边界坐标在 0.01 mm 容差内保持。
- 清单切片含 2105 次挤出移动，G-code MD5 校验通过。
- 第一件局部 `wall_loops` 设为 5，移除旧路径后重切片；局部、盘级与项目设置保持，含 2292 次挤出移动，MD5 校验通过。
- 空材料槽保留调用使 `filament_prime_volume` 保持 30，原生校验启用。[B42]
- 对应脚本 SHA-256：`4eb27540ab55996cba47f61ea5bc78fb208a77e7a7c8585995ce000c32b2f915`。完整输出与诊断保存在本地合成测试目录。

GUI 待核对工程打开、两个对象及局部墙数。几何预检采用保守包围盒与网格拓扑，路径碰撞、自交和壁厚按相应检查方法记录。`T65535` 日志、机器标识及统计单位说明见 [automation.md](automation.md)。

## 初始版本记录（2026-10-12）

环境：macOS arm64、Bambu Studio 02.08.04.57、Python 3.14、NumPy 2.5.4、trimesh 5.1.1、Shapely 2.2.0。以下记录对应脚本更新前的版本。

- 16 项离线测试通过，覆盖配置继承、来源、差异参数、输入几何、排布和 3MF 变换。
- 20 × 20 × 12 mm 合成模型以 H2S 0.4 标准热端、PLA Basic、纹理 PEI 切片，生成 60 层，并在原生 Studio 打开。
- Production Extension 的尺寸与平台位置解析通过。
- 自定义填充、墙数、封顶、接缝、裙边经 GUI 重开保留；`different_settings_to_system` 用于保存差异参数。
- 原生板切片包含 H2S 机器标识 `O1S`、0.4 mm 标准热端、路径、时间/质量和 MD5。

来源核查的日期、范围与版本见 [sources.md](sources.md)。物理性能记录包含试样、方向、材料状态和测试方法。
