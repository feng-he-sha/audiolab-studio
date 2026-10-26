# 上传到 GitHub 指南

原则：**只提交原创代码、脚本、文档、测试和小截图；上游项目通过 PyPI 安装，模型权重通过清单 + 下载脚本获取。**

## 1. 仓库里放什么

| 提交 | 不提交 |
|---|---|
| `src/audiolab/`（原创编排代码 + 一个 MIT 派生编码器，见 `THIRD_PARTY.md`） | `.venv/` |
| `web/src/`、`web/package.json`、`web/pnpm-lock.yaml`、Vite/TS 配置 | `web/node_modules/` |
| `scripts/`（模型下载、样本生成、manifest 导出） | `web/dist/`（构建产物） |
| `tests/`、`docs/`、`README.md`、`MODELS.md`、`MODELS.json` | `models/`（权重） |
| `setup.ps1`、`run_workbench.bat`、`run_cli.bat`、`requirements.txt`、`pyproject.toml` | `workspace/`（数据库/输出/日志） |
| `web/screenshots/`（约 3MB，用于 README） | `outputs/`、`samples/generated/`、缓存 |
| `LICENSE`、`THIRD_PARTY.md` | 个人测试视频/音频、API key、`settings.json` |

`.gitignore` 已经覆盖上述排除项。

## 2. 提交前自检

```powershell
cd audio-lab

# 确认没有大文件/虚拟环境被扫入
git status --ignored --short | Select-Object -First 40
Get-ChildItem -Recurse -File | Where-Object { $_.Length -gt 20MB } |
  Select-Object FullName,Length

# 确认没有本机绝对路径/密钥
git grep -n -I -E "C:\\\\Users|E:\\\\(抖音|ComfyUI)|api[_-]?key|token" -- . 2>$null
```

如果 `git status` 里出现 `models/`、`workspace/`、`web/node_modules/`，先检查 `.gitignore`，不要用 `git add -f`。

## 3. 初始化并首次提交

```powershell
git init -b main
git add .
git status --short

# 设置提交身份（只对本仓库生效；也可用你自己的 GitHub 邮箱）
git config user.name "Your Name"
git config user.email "you@example.com"

git commit -m "feat: AudioLab Studio audio voice/music workbench"
```

建议首次提交前确认 `MODELS.json` 已生成：

```powershell
.\.venv\Scripts\python.exe scripts\export_model_manifest.py
```

## 4. 创建 GitHub 仓库并推送

### 方式 A：网页创建

1. GitHub → New repository → 名称如 `audiolab-studio`；
2. **不要**勾选 Add README / .gitignore / license（本地已有）；
3. 复制仓库地址，然后：

```powershell
git remote add origin https://github.com/<your-account>/audiolab-studio.git
git push -u origin main
```

### 方式 B：GitHub CLI

```powershell
gh auth login
gh repo create audiolab-studio --public --source=. --remote=origin --push
```

如果仓库已存在：

```powershell
git remote add origin https://github.com/<your-account>/audiolab-studio.git
git branch -M main
git pull --rebase origin main
git push -u origin main
```

## 5. 打标签 / 发布 Release

```powershell
git tag -a v0.1.0 -m "AudioLab Studio v0.1.0"
git push origin v0.1.0
```

在 GitHub Release 页面：

- 标题：`AudioLab Studio v0.1.0`
- 说明：功能、模型清单链接、已知限制；
- 附件：可选上传 `MODELS.json`，**不要上传模型权重**（GitHub 单文件 100MB 限制；BS-Roformer 639MB）。
- 源码 zip 由 GitHub 自动生成，已排除 `.gitignore` 中的文件。

## 6. 克隆后的首次安装

README 的快速开始应保持可用：

```powershell
git clone https://github.com/<your-account>/audiolab-studio.git
cd audiolab-studio
powershell -ExecutionPolicy Bypass -File setup.ps1
run_workbench.bat
```

`setup.ps1` 会安装依赖、构建前端、下载推荐模型（约 80MB）。BS-Roformer/AST 在模型页按需下载。

## 7. 第三方项目与许可证

- `requirements.txt` / `pyproject.toml` 通过 PyPI 拉取 upstream，不复制其源码；
- `src/audiolab/core/timbre_encoder.py` 是 Resemblyzer/ColorSplitter（MIT）的裁剪派生实现，已在文件头与 `THIRD_PARTY.md` 标注；如不想保留，可删除并改为依赖 ColorSplitter，或使用 MFCC 回退；
- 模型权重不提交，`MODELS.md` / `MODELS.json` 提供来源、大小、许可证；
- 如果仓库公开，建议在 README 和 Release 中再次说明「模型权重许可以上游为准，商用前确认」。

## 8. 半自动/全自动发布脚本

如果本机 Git Credential Manager 已登录 GitHub（`git credential-manager github login`），可以直接用脚本完成「创建仓库 → push main → push tag → 设置描述/topics → 创建 Release」：

```powershell
# 只打印计划，不改远程
powershell -ExecutionPolicy Bypass -File scripts\publish_github.ps1 -DryRun

# 默认创建 public 仓库 audiolab-studio，使用当前 GitHub 账号
powershell -ExecutionPolicy Bypass -File scripts\publish_github.ps1 -RepoName audiolab-studio -Visibility public

# 私有仓库 / 跳过 Release
powershell -ExecutionPolicy Bypass -File scripts\publish_github.ps1 -Visibility private -SkipRelease
```

脚本会从 Git Credential Manager 或 `GH_TOKEN` 读取凭据，**不会打印 token**。如果凭据没有 `repo` scope，创建仓库/Release 可能失败；此时先在 GitHub 网页手动创建空仓库，再用：

```powershell
git remote add origin https://github.com/<你的账号>/<仓库>.git
git push -u origin main
git push origin v0.1.0
```

## 9. 常见问题

| 问题 | 处理 |
|---|---|
| `git add .` 很慢/仓库巨大 | 检查 `.venv`、`models`、`workspace`、`node_modules` 是否被忽略；`git rm -r --cached` 后重新提交 |
| 推送被拒（远程已有文件） | `git pull --rebase origin main` 后重试 |
| Windows 换行警告 | 可加 `.gitattributes`：`* text=auto eol=lf`；不改也能用 |
| 想带示例媒体 | 只放几秒、无版权的测试音频；不要放电影/音乐片段 |
| 想加 CI | 可只加前端构建 job；Python 全量依赖较重，建议 CI 用 `AUDIOLAB_FAKE=1` 跑接口测试 |
| 之后更新代码 | `git add . && git commit -m "..." && git push`；模型/输出仍被忽略 |

## 9. 推荐仓库设置

- Description：`Local audio workbench: vocal/BGM classification, timbre clustering, ffmpeg processing.`
- Topics：`audio-processing`, `source-separation`, `vocal`, `timbre`, `fastapi`, `react`, `ffmpeg`
- License：MIT（与 `LICENSE` 一致）
- 关闭 Wiki/Projects（可选）
- 如需截图展示，README 已引用 `web/screenshots/final-timeline.png`。
