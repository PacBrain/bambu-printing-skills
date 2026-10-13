# Bambu Printing Skills

Bambu Studio 选材、打印准备、切片、校准和排错 Skills。采用 [Agent Skills 格式](https://agentskills.io/specification)，从 [SKILL.md](skills/bambu-printing/SKILL.md) 按任务加载参考资料和脚本。

## 功能

- 材料、机器、喷嘴、AMS 与打印板适配。
- 模型修复、摆放、层高、填充、支撑、多盘与多材料工作流。
- 预设、切片、工程检查、校准和打印故障定位。

## 安装

```bash
git clone https://github.com/PacBrain/bambu-printing-skills.git
cd bambu-printing-skills
```

按需要选择安装命令：

```bash
# 安装到 ~/.agents/skills
python install.py
# 指定 agent 或项目使用的 skills 目录
python install.py --dest /path/to/skills
# 预览安装位置
python install.py --dest /path/to/skills --dry-run
# 链接源码目录，随仓库更新
python install.py --dest /path/to/skills --mode symlink
```

安装器使用 Python 3.10+，默认复制完整技能目录。相同版本可重复安装；更新副本时先保存本地修改，再替换目录。符号链接模式跟随源码更新。

也可直接复制 `skills/bambu-printing` 到 agent 的技能目录。使用自定义加载方式时，让 agent 读取其中的 `SKILL.md`；脚本和参考文件路径均以技能目录为基准。`agents/` 保存客户端使用的界面元数据。

## 使用

> 使用 bambu-printing，为指定机器、喷嘴、打印板和材料准备打印工程，并检查切片结果。

Python 3.10+ 和本机 Bambu Studio。依赖随技能目录提供：

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python skills/bambu-printing/scripts/bambu.py env
.venv/bin/python -m unittest discover -s tests -v
```

Windows 使用 `.venv\Scripts\python.exe`。安装后的技能可用 `python -m pip install -r /path/to/bambu-printing/requirements.txt` 配置依赖，并通过脚本绝对路径调用。

`profiles` 准备预设，`preflight` 检查模型与排布，`slice --manifest` 切片，`reslice --project` 保留工程设置重切片，`inspect` 读取 3MF。参数和示例见[自动化参考](skills/bambu-printing/references/automation.md)。

## 验证与资料

CI 覆盖 Windows、macOS、Linux 上的 Python 3.10/3.14 安装与离线测试，以及官方 `skills-ref` 格式校验。软件集成结果和待验证项目见[验证记录](skills/bambu-printing/references/validation.md)。

[来源索引](skills/bambu-printing/references/sources.md)记录官方文档、具体版本和适用条件。格式检查命令：`skills-ref validate skills/bambu-printing`。

## 许可

原创代码和文档采用 [MIT](LICENSE) 许可，引用资料见 [NOTICE.md](NOTICE.md)。许可文件随技能目录分发。
