# 开发验证

本项目已经启用 Git 版本管理，并用 Git LFS 管理仍需随软件发布的 `.lmp/.cfg` 结构资产。`config.json`、虚拟环境、构建产物、运行输出、私有脚本、视频脚本、论文参考和 Atomsk 中间文件不会进入版本库；本机配置可参考根目录的 `config.example.json`。

提交前建议运行：

```bash
python tools/verify_core.py
```

需要连同打包目录一起验证时运行：

```bash
python tools/verify_project.py
```

需要生成可分发压缩包时运行：

```bash
python tools/create_release.py
```

该脚本会执行三类检查：

1. 编译检查 `hea_mea_designer.py`、入口文件、测试和验证脚本，且不依赖写入 `__pycache__` 作为判断依据。
2. 运行 `tests/` 下的核心单元测试，覆盖配方解析、计数分配、掺杂选择、严格数值输入、近距离清理、LAMMPS 数据读写、生成元数据、log 诊断和外部命令失败诊断。
3. 读取 `data/` 与精选 `models/` 中随软件发布的 `.lmp` 文件，确认更严格的解析规则仍兼容内置科研素材。

`verify_project.py` 会在上述基础上检查 `dist\HEA_MEA_Designer`，确认 exe、内置 `data/`、`docs/`、`models/`、`config.json` 和打包后 `.lmp` 资产仍然有效，同时确认非发布文档、运行输出和中间文件没有进入分发目录。当前 release 文档包括快速说明、使用教程、验证说明、数据来源和文献参考。

`create_release.py` 会先执行项目级验证，再在 `releases/` 下生成 zip、SHA256 校验文件、manifest 和 release notes；发布 zip 内的 `config.json` 来自 `config.example.json`，不会包含本机路径。`releases/` 是本地分发产物，不进入版本库。

如果只想快速跑单元测试：

```bash
python -m unittest discover -s tests
```
