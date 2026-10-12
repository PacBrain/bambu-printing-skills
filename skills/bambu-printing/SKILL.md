---
name: bambu-printing
description: Prepare and verify Bambu Studio projects, select compatible filaments and hardware, tune slicing, and troubleshoot Bambu Lab FFF prints using official sources and local software. Use for material, print-preparation, slicing, calibration, and print-quality requests.
---

# 拓竹打印

把用户的模型、机器和材料变成可检查、可重新切片的工程。按任务读取对应参考资料，不一次加载所有文档。

## 先确定影响结果的条件

读取模型、工程和本机配置，确认机器型号、喷嘴直径与标准/高流量热端、打印板、材料品牌及系列、单位、用途和交付形式。能从文件发现的事实自行读取；客户设备等无法推断的关键条件才询问。不要把普通 PLA、PLA Silk、PLA-CF 或 TPU for AMS 混为同一材料。

硬件不明时可交付带假设的可编辑工程，不能标记为对应机器可直接执行的最终切片。用户指定的材料和形状优先；提出替代建议说明收益和代价，不擅自换材或改外形。

## 按问题选资料

- 选材、干燥、材料限制：[materials.md](references/materials.md)。
- 机器、喷嘴、AMS、打印板、同盘和逐件净空：[hardware.md](references/hardware.md)。
- 层高、壳层、填充、支撑、速度和省料：[slicing.md](references/slicing.md)。
- 校准、缺陷、维护：[calibration-troubleshooting.md](references/calibration-troubleshooting.md)。
- 自动切片、配置继承、工程验证：[automation.md](references/automation.md)。
- 官方来源与核对日期：[sources.md](references/sources.md)；测试边界：[validation.md](references/validation.md)。

## 执行与验收

以对应机器和耗材的官方预设为起点，记录必要改动及理由。检查机器、材料、工艺，以及 plate/object/part/modifier 覆盖；导出工程和预设不是同一件事。

CAD 实体不等于 100% 填充。根据载荷、承托跨度、表面、方向和时间选择壳层与填充，不能固定使用某个百分比。切片预览检查首层、悬空、桥接、薄壁、封顶、接缝、支撑可拆性和速度/流量变化。

自动化使用 `scripts/bambu.py`，只调用本机软件，不连接打印机。目前验证的是标准单热端、单材料工作流。高流量或多热端/多材料项目先在 Studio 中选择实际硬件、材料分组和换料设置，不套用本脚本的假设。

导出后重新打开 `.3mf`，核对最终硬件、材料、板型、尺寸、对象数量、局部覆盖、路径和估算。`.gcode.3mf` 后缀不是已切片证明，必须包含有效路径。准备文件不隐含远程发送或启动打印授权。

报告区分官方要求、工程选值、软件实测和物理试验。未执行写 `not_run`；填充比例不能证明承载能力，软件验收不能证明舒适性、耐热、食品接触或医疗性能。

版本改变时重查对应官方资料和本机配置。官方资料冲突保留条件，优先核对具体型号/牌号最新文档。
