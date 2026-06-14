# 开发验证

本项目已经启用 Git 版本管理，并用 Git LFS 管理大体积模型、势函数和论文文件。`config.json`、虚拟环境、构建产物和运行输出不会进入版本库；本机配置可参考根目录的 `config.example.json`。

提交前建议运行：

```bash
python tools/verify_core.py
```

该脚本会执行三类检查：

1. 编译检查 `hea_mea_designer.py`、入口文件、测试和验证脚本，且不依赖写入 `__pycache__` 作为判断依据。
2. 运行 `tests/` 下的核心单元测试，覆盖配方解析、计数分配、掺杂选择、近距离清理、LAMMPS 数据读写和外部命令失败诊断。
3. 读取 `data/` 与 `models/` 中随软件发布的 `.lmp` 文件，确认更严格的解析规则仍兼容内置科研素材。

如果只想快速跑单元测试：

```bash
python -m unittest discover -s tests
```
