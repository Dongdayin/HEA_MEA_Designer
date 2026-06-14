# 迭代记录

## 2026-06-15：第 6-10 轮升级

- 第 6 轮：收紧 LAMMPS 输入数值校验。步数、弛豫步数、热输出间隔、轨迹输出间隔必须是正整数；步长和温度必须是正有限数；压力仍允许负值但必须是有限数。
- 第 7 轮：优化 `Atoms # atomic` 热路径解析。将逐行正则匹配改为 token 解析，保留尾部注释支持和严格列数校验。
- 第 8 轮：生成的 LAMMPS data 第一行写入追溯元信息，包括生成时间、源文件、原子数和类型数。
- 第 9 轮：增强 LAMMPS log 诊断。跳过 NaN/inf 热力学行，诊断摘要会包含常见失稳建议以及最多 3 条原始 ERROR/WARNING 行。
- 第 10 轮：用 `python tools/verify_core.py` 做最终回归，覆盖源码编译、单元测试和内置 `.lmp` 资产读取。

当前核心验证命令：

```bash
python tools/verify_core.py
```

## 2026-06-15：第 11 轮升级

- 第 11 轮：建立首版分发链路。新增 `VERSION` 作为单一版本源，窗口标题和启动界面显示版本号，PyInstaller 包内携带 `VERSION`，项目级验证会检查版本文件一致性。
- 新增 `tools/create_release.py`，用于在 `releases/` 下生成可分发 zip、SHA256 校验文件、manifest 和 release notes。

当前项目级验证与分发命令：

```bash
python tools/verify_project.py
python tools/create_release.py
```

## 2026-06-15：第 12 轮升级

- 第 12 轮：发布包去本机化。`tools/create_release.py` 会用 `config.example.json` 替换 zip 内的本机 `config.json`，避免分发包带出本机工作目录和 LAMMPS 绝对路径。
- 相对工作目录现在按程序根目录解析，默认 `generated` 会稳定落在软件目录内；新增单元测试覆盖该行为。
