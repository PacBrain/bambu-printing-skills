---
name: bambu-printing
description: Prepare and verify Bambu Studio projects, select compatible filaments and hardware, tune slicing, and troubleshoot Bambu Lab FFF prints using official sources and local software. Use for material, print-preparation, slicing, calibration, and print-quality requests.
license: MIT
compatibility: Python 3.10+, packages in requirements.txt, and local Bambu Studio for slicing; native UI access for advanced workflows and visual inspection.
---

# 拓竹打印

把模型、机器和材料组织成可检查、可重新切片的工程。按任务读取参考资料，并使用脚本或原生 Studio 完成操作。

## 先确定影响结果的条件

读取模型、工程和本机配置，确认机器型号、喷嘴直径与标准/高流量热端、打印板、材料品牌及系列、单位、用途和交付形式。能从文件发现的事实自行读取；无法推断且会影响结果的关键条件才询问。按普通 PLA、PLA Silk、PLA-CF、TPU for AMS 等具体系列选择预设。

硬件待确定时先交付注明假设的可编辑工程；设备切片使用已确认的硬件。遵循用户指定的材料和形状，替代方案说明收益与代价。

## 按问题选资料

- 导入、修复、单位、对象/部件/修改器：[model-workflows.md](references/model-workflows.md)。
- 选材、干燥、材料限制：[materials.md](references/materials.md)。
- 机器、喷嘴、AMS、打印板、同盘和逐件净空：[hardware.md](references/hardware.md)。
- 层高、壳层、填充、支撑、速度和省料：[slicing.md](references/slicing.md)。
- 多盘、多材料/喷嘴、支撑界面和可变层高：[advanced-workflows.md](references/advanced-workflows.md)。
- 校准、缺陷、维护：[calibration-troubleshooting.md](references/calibration-troubleshooting.md)。
- 本地 CLI、配置继承、预检与重切片：[automation.md](references/automation.md)。
- 逐项来源与适用版本：[sources.md](references/sources.md)；实际验证边界：[validation.md](references/validation.md)。

## 选择执行方式

| 工作 | 方法 |
|---|---|
| 选材、参数比较、诊断、高级工作流 | 按对应资料选择参数、操作步骤与验收方法 |
| 原始 STL 的标准单喷头、单材料作业 | `scripts/bambu.py slice --manifest … --config-dir …`；预检与切片共用单位和摆放变换 |
| 保留已有工程设置的重切片 | `reslice --project … --output …`；适用于原生单盘、单材料、标准单喷头工程 |
| 多盘、多材料、多喷头、高流量或脚本拒绝的工程 | 使用原生 Studio，保留项目及局部设置，完成对应预览 |

从本文件的位置解析技能目录，以绝对路径调用脚本；依赖在技能目录的 `requirements.txt`。具体示例见自动化参考。

## 执行与验收

以对应机器和耗材的官方预设为起点，记录必要改动及理由。检查机器、材料、工艺，以及 plate/object/part/modifier 覆盖。记录软件完整版本和正式版/Beta 渠道；不同渠道的工程兼容性与发布条件单独核对。

根据载荷、承托跨度、表面、方向和时间设置打印壳层与填充。预览逐层检查首层、悬空、桥接、薄壁、封顶、接缝、支撑可拆性、材料切换及速度/流量变化。

导出后重新打开 `.3mf`，核对硬件、材料、板型、尺寸、对象数量、局部覆盖、路径和估算。检查切片文件中的实际挤出路径，分别交付可编辑工程、设置与板切片。发送到设备或启动打印按用户指示执行。

报告区分官方要求、工程选值、离线测试、原生软件验证和物理试验。未执行的检查写 `not_run`；承载、舒适性和耐热通过对应物理试验验证。版本改变时重新核对对应官方来源与本机配置，保留来源冲突和未核实项。
