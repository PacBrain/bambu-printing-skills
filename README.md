# Bambu Printing Skills

面向各类智能体的 Bambu Studio 打印准备、材料与硬件适配、切片检查和排错技能，采用开放的 [Agent Skills 格式](https://agentskills.io/specification)。依据拓竹官方资料编写，独立维护，不是拓竹官方软件。技能内容不依赖特定模型、客户端或 MCP 服务。

## 使用与安装

- 支持 Agent Skills 的客户端：将完整 `skills/bambu-printing` 目录安装到该客户端实际扫描的技能目录。
- 能读取文件、但没有技能发现功能的智能体：直接读取 [SKILL.md](skills/bambu-printing/SKILL.md)，再按任务读取其中引用的资料。
- 没有本机 Studio 访问能力的智能体：可以用于选材、切片方案、工程清单和已有文件分析；实际切片、原生重开与打印验收仍需对应软件或设备环境。

```bash
# 默认复制到 ~/.agents/skills；不需要符号链接权限
python install.py
# 指定客户端或项目的技能父目录
python install.py --dest /path/to/agent/skills
# 查看操作，不写入文件
python install.py --dest /path/to/agent/skills --dry-run
# 开发时可将技能链接到当前源码目录
python install.py --dest /path/to/agent/skills --mode symlink
```

安装器不会覆盖不同内容；同一链接或内容一致的副本可重复安装。源码更新后，已有副本不同会被拒绝，需先保存自己的改动并选择新的目标位置或手动替换；符号链接跟随源码更新。保留显式 `--codex-home DIR`，等价于 `--dest DIR/skills`；默认路径不读取 `CODEX_HOME`，也不自动迁移旧安装。Windows 使用同样的 Python 命令和本机路径。

`~/.agents/skills` 是跨客户端约定，具体发现和启用方式取决于客户端。[Gemini CLI](https://geminicli.com/docs/cli/skills/) 明确支持此路径；[Claude Code](https://code.claude.com/docs/en/skills) 可用 `--dest ~/.claude/skills`，项目安装则指定 `.claude/skills`。其他客户端以其文档为准。`agents/openai.yaml` 仅为可选的 OpenAI 界面元数据，不参与脚本运行，也不表示仅限 Codex。

通用调用示例：

> 使用 bambu-printing 技能，为指定机器、喷嘴、打印板和材料准备这个模型的省料打印工程，并检查实际切片。

客户端可能使用 `/bambu-printing`、`$bambu-printing` 或自动选择；安装本身不保证这些调用方式均可用。

## 脚本环境

Python 3.10+。依赖文件随技能分发；仓库根目录的 `requirements.txt` 引用同一份文件。建议使用独立环境，从仓库根目录运行：

```bash
python -m venv .venv
# macOS / Linux
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python skills/bambu-printing/scripts/bambu.py --help
.venv/bin/python -m unittest discover -s tests -v
```

Windows 将 `.venv/bin/python` 换成 `.venv\Scripts\python.exe`。若只安装了技能目录，在自己选择的环境中运行 `python -m pip install -r /absolute/skill/requirements.txt`，再用绝对路径调用 `/absolute/skill/scripts/bambu.py`；不依赖仓库根目录或固定工作目录。

非默认 Studio 安装通过全局 `--binary`、`--profiles` 参数指定。`env` 检查本机软件与配置；`profiles` 准备预设；`preflight` 检查模型与排布；`slice --manifest` 将明确的模型清单应用到切片；`reslice --project` 用于已有工程；`inspect` 检查 3MF 内容。具体参数和 JSON 示例见[自动化参考](skills/bambu-printing/references/automation.md)，以各子命令 `--help` 为准。

## 覆盖与证据

材料参考覆盖 PLA 系列、PETG、TPU、ABS/ASA、PC、尼龙、纤维增强和支撑材料；硬件、AMS、干燥、校准、缺陷及同盘/逐件排布按主题整理。只按任务加载相关参考。

[验证记录](skills/bambu-printing/references/validation.md)列明实际切片与原生工程重开的软件版本、机器组合和边界。标准单热端、单材料的实测证据不能推广到全部机型、材料或多热端组合。高流量和多材料项目需按实际配置验证。

CI 只检查 Linux、macOS、Windows 的技能安装包与离线 Python 行为；通过 CI 不代表对应平台已运行 Studio，也不代表每种智能体客户端均已实测。CAD 有效、路径生成、原生重开和实物打印分别报告。工具不连接或启动打印机，文件准备不隐含发送或打印授权。

格式验证另用官方 Agent Skills `skills-ref`，CI 固定到提交 `69ef37e9424c0a7ea9dd2293b559e43ec8176379` 并使用 Python 3.14。安装该校验器后运行 `skills-ref validate skills/bambu-printing`。这项检查验证标准元数据；客户端自带的旧版校验器可能尚不认识 `compatibility` 等标准字段，不能以此判断技能格式无效。

## 维护与许可

修改参数知识时核对具体[官方来源](skills/bambu-printing/references/sources.md)、配置版本和适用条件；行为变化需有能暴露问题的测试。公开测试只使用合成几何，不含客户模型、专利原件或私人作业文件。

原创内容 [MIT](LICENSE)；第三方权利见 [NOTICE.md](NOTICE.md)。完整技能目录自带同样的许可和说明，可独立分发。
