# Bambu Printing Skills

依据拓竹官方资料编写的中文 Codex Skill，支持材料/硬件适配、切片策略、校准排错与可验证的 Bambu Studio 文件交付。独立项目，不是拓竹官方软件。

## 安装与调用

克隆本仓库后运行 `python install.py`，将技能链接到当前用户的 Codex 技能目录；已有不同技能不会被覆盖。Windows 若不支持符号链接，可将 `skills/bambu-printing` 文件夹复制到 Codex 的 `skills` 目录。重新加载技能目录或开启新对话后使用：

```text
使用 $bambu-printing，为 H2S 的 0.4 mm 标准喷嘴、纹理 PEI 和 PLA Basic 准备这个模型的省料打印工程，并检查实际切片。
```

自动选择默认启用。入口：[SKILL.md](skills/bambu-printing/SKILL.md)。软件无关的知识参考可直接阅读；自动化依赖本机 Bambu Studio，不代替它。

## 脚本环境

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python skills/bambu-printing/scripts/bambu.py env
python -m unittest discover -s tests -v
```

Windows 使用 `.venv\Scripts\activate`。非默认安装通过 `--binary`、`--profiles` 指定。用法与 JSON 示例：[自动化参考](skills/bambu-printing/references/automation.md)。

## 覆盖与边界

材料参考覆盖 PLA 系列、PETG、TPU、ABS/ASA、PC、尼龙、纤维增强和支撑材料；打印设置、AMS、干燥、校准、缺陷、同盘/逐件排布分别成文。只按当前任务加载对应参考，不需要读完整个库。

脚本已验证标准单热端、单材料 H2S 工作流，包含真实切片和原生工程重开；其他机器/材料的知识依据不等于已经实物打印过。高流量、多热端、多材料用原生 Studio 明确配置并验证。

工具不连接或启动打印机。CAD 有效、路径生成、GUI 重开和实物打印分开报告。[验证记录](skills/bambu-printing/references/validation.md)；[官方来源](skills/bambu-printing/references/sources.md)。

## 维护

修改参数知识先核对具体官方页面/配置版本，更新来源日期和适用条件；有行为变化时加入能暴露问题的测试。源码引用使用当前链接，不声称永远与最新版本一致。公开测试仅使用合成几何，不包含客户模型、原始专利或私人作业文件。

原创内容 MIT；第三方资料权利见 [NOTICE.md](NOTICE.md)。
