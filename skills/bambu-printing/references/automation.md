# 自动化与文件接口

脚本使用本机 Bambu Studio 准备与验证工程。Python 3.10+；依赖在技能目录的 `requirements.txt`，安装到选定虚拟环境。先把 `SKILL_DIR` 设为包含本文件上一级 `SKILL.md` 的实际绝对路径；以下为 POSIX shell 示例，Windows 可直接使用解释器与脚本的绝对路径。

```bash
SKILL_DIR='/absolute/path/to/bambu-printing'
python3 -m venv /tmp/bambu-skill-env
BAMBU_PYTHON=/tmp/bambu-skill-env/bin/python
"$BAMBU_PYTHON" -m pip install -r "$SKILL_DIR/requirements.txt"
"$BAMBU_PYTHON" "$SKILL_DIR/scripts/bambu.py" env
```

同一 Python 解释器用于后续命令。命令从任意当前目录调用，清单和输出路径建议显式使用绝对路径。`--binary`、`--profiles` 支持非默认安装；显式路径错误应直接修正，不应静默改用另一版本。

## 原始 STL：同一份清单贯穿预检和切片

```bash
"$BAMBU_PYTHON" "$SKILL_DIR/scripts/bambu.py" profiles \
  --machine 'Bambu Lab H2S 0.4 nozzle' \
  --process '0.20mm Standard @BBL H2S' \
  --filament 'Bambu PLA Basic @BBL H2S' \
  --output /tmp/job-config
"$BAMBU_PYTHON" "$SKILL_DIR/scripts/bambu.py" preflight /tmp/manifest.json \
  --machine-json /tmp/job-config/machine.json --process-json /tmp/job-config/process.json --output /tmp/preflight.json
"$BAMBU_PYTHON" "$SKILL_DIR/scripts/bambu.py" slice \
  --manifest /tmp/manifest.json --config-dir /tmp/job-config \
  --bed 'Textured PEI Plate' --output /tmp/result.3mf
"$BAMBU_PYTHON" "$SKILL_DIR/scripts/bambu.py" inspect /tmp/result.3mf --output /tmp/inspection.json
```

上例机型/材料只是已知配置示例，必须替换为任务中的实际硬件。`slice` 不再接受位置参数 STL；旧调用返回清单迁移示例。

清单沿用以下字段：

```json
{
  "print_sequence": "by layer",
  "brim_width_mm": 5,
  "brim_gap_mm": 0.1,
  "additional_exclude_areas": [],
  "objects": [
    {"path": "/tmp/example.stl", "units": "cm", "center_xy_mm": [170, 160], "rotation_z_deg": 30}
  ]
}
```

相对模型路径以清单所在目录解析。`objects` 不能为空，每对象一个 STL；`units` 支持 mm/cm/m/inch。准备函数将单位归一为毫米、以包围盒 XY 中心为旋转基准、底面放到 Z=0、绕 Z 旋转后放到给定中心。预检和 `slice` 共用这一准备结果，传给 Studio 的是毫米制临时 3MF；关闭自动排列，不传自动朝向或另一次缩放。

单独 `preflight` 传入 `--process-json` 时使用有效工艺；不传时仅检查清单声明值。`slice` 总是使用有效工艺。清单中的 `print_sequence`、`brim_width_mm`、`brim_gap_mm` 可省略；提供时必须与工艺一致。`brim_width_mm` / `brim_gap_mm` 参与预检缓冲并与有效工艺保持一致，预检缓冲采用实际裙边尺寸。`additional_exclude_areas` 是毫米制 XY 多边形数组，用于任务特有禁入区。所有数值需有限且符合范围；JSON 中 NaN、无穷值和无效坐标均不能作为可打印输入。

静态预检检查网格、封闭性、法线、非流形、尺寸、裙边、禁止区和保守逐件净空；一个对象的 `by object` 合法，多对象还需净空检查。精确自交、最小壁厚、全部打印路径碰撞及物理打印不是静态预检结论。

## 原生工程：保留设置再重切片

```bash
"$BAMBU_PYTHON" "$SKILL_DIR/scripts/bambu.py" reslice \
  --project /tmp/native-project.3mf --output /tmp/resliced.3mf
```

`reslice` 用于可编辑原生单盘、单材料、标准单喷头工程。它不加载替代 machine/process/filament JSON，不主动更新到最新系统预设，也不重新排列、朝向或重建网格。必须比较重切片前后的几何身份、变换和局部设置；无法可靠解析的工程转到原生 Studio。

含多盘、多材料、多热端、只含 G-code、损坏引用或无法证明可编辑模型的输入不属于这一路径。可变层高、涂色/支撑绘制、有效切割关联和自定义逐层 G-code 等当前无法完整核对的编辑数据也会被拒绝；普通对象/部件/盘级参数覆盖会逐项比较。高级原生操作见 [advanced-workflows.md](advanced-workflows.md)。保留工程设置时使用原生 3MF。

02.08.04.57 原生 CLI 在未提供材料槽列表时会将原生工程的 `filament_prime_volume` 强制改为 45。本工具传入一个保留现有材料的空槽（参数值为两个引号字符），不替换材料，并继续逐项验证所有设置，原生校验保持启用。本轮合成测试确认原值 30 和局部墙数 5 均保留。[B24、B42]

## 配置来源与优先级

官方 CLI 优先级是显式命令行值 > `--load-settings` / `--load-filaments` 完整 JSON > 工程内设置。`--load-settings` 最多接受一份机器和一份工艺；官方 resources 目录中的继承片段不能直接当完整配置使用。多材料原生 CLI 的分号列表中，空槽保留对应工程材料，不应过滤空字符串使槽位错位。[B24]

`profiles` 解析父预设，保留来源哈希与变体数组；`include` 的支持范围刻意收窄：

- include 片段不得自己包含 `inherits` 或嵌套 `include`。
- 纯 G-code 叶片段按原内容保留，不改写机器启动/结束逻辑。
- 参数片段仅接受代码中按 SHA-256 指纹登记、已与原生行为对照的 H2S 片段；同名不同内容不能复用这个结论。
- 其他参数片段使用原生 Studio 导出的完整配置或原生工程。原生 include 使用相对默认值的差异合并，按该规则核对实际配置。[B43]

`--overrides` JSON 顶层为 machine/process/filament，拒绝未知键、已废弃键和 G-code 改写。应用覆盖后再次校验机型、喷嘴数量/变体、材料兼容性；覆盖后使用同一套硬件检查。`printer_extruder_variant` 等数组不可任意截断。

CLI 的 User 配置通过 `inherits` 保留系统身份；保留身份字段和兼容列表。历史 2.8.4 GUI 重开验证发现：只展开数值而没有 `different_settings_to_system` 会使自定义工艺被系统预设刷新，因此显式覆盖需要记录差异，并以重开结果验收。[B24；历史本机记录]

`only_one_wall_top` 已被现行 `top_one_wall_type` 替代；可用枚举为 `not apply` / `all top` / `topmost`。字段存在于旧模板不证明当前切片器使用它。[B33]

## 文件验收和失败证据

每次作业使用独立工作目录保存准备模型、配置、命令、日志和诊断，验证通过后才发布目标输出。目标冲突时另选文件名，失败时保留该次证据。

验收至少包括：ZIP/XML 结构、可用有效网格面、真实挤出路径（不是注释或空移）、可用 G-code 校验和、机器/材料/喷嘴/板型和有效工艺。模型数量、身份及 `[min_x,min_y,min_z,max_x,max_y,max_z]` 要与准备结果一致，各坐标误差不超过 **0.01 mm**。该容差用于文件往返的一致性；打印精度通过试件测量。

解析 3MF 时跟随多文件引用、组件/实例变换和单位；按实际 build 实例统计对象。原生格式分别保存项目、对象、层高和切片信息。[B21、B40] 输出仍需原生 Studio 重开并检查关键预览，核对关键层的实际路径。

## 已知版本行为

- 记录完整版本、平台和发布渠道；`02.08.04.57` 对应 Public Beta。[B32] 更换版本后执行对应回归。
- 历史 macOS CLI 导出有缺少 `slice_info.config` 的 `printer_model_id` 的案例，此时设备执行文件的机型检查仍待完成。最终设备板切片应由原生 Studio 导出并核对机器标识。
- 历史 H2S 2.8.4 官方结束模板含 `T65535`；原生时间解析日志出现 `Invalid T command`。仅在确认来自未改动官方模板时作为已知例外记录，保留日志；其他错误逐项定位，保留官方机器命令。
- 某些路径统计字段的体积单位标签与数值不一致；交付优先核对质量、长度、时间及量纲，不直接把未知体积值当 cm³。
- macOS 图形访问限制可能使路径计算成功、缩略图或导出失败；按实际失败处理，不关闭系统保护或跳过验收。

实际执行记录见 [validation.md](validation.md)。
