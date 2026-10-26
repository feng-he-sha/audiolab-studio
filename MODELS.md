# 模型下载清单

模型权重**不随仓库分发**。工作台在第一次分析时会按需下载，也可以手动预下载：

```powershell
# 推荐集合（MDX HQ4 + 音色 + VAD，约 80MB）
python scripts\fetch_models.py --recommended

# 全部模型（含 BS-Roformer 639MB、AST 约 350MB，网络慢时很久）
python scripts\fetch_models.py

# 单个模型
python scripts\fetch_models.py --model separation.bs_roformer
python scripts\fetch_models.py --model tagging.ast
```

模型列表也以机器可读形式保存在 [`MODELS.json`](MODELS.json)。

## 清单

| id | 文件 | 大小 | 角色 | 必需性 | 来源 | 许可证 |
|---|---|---|---|---|---|---|
| `separation.bs_roformer` | `model_bs_roformer_ep_317_sdr_12.9755.ckpt` + `.yaml` | 639,333,486 B | 高质量人声/伴奏分离 | 可选（缺失自动降级 MDX） | [lainlives/audio-separator-models](https://huggingface.co/lainlives/audio-separator-models) | 社区权重，商用前确认上游 |
| `separation.mdx_fast` | `UVR-MDX-NET-Inst_HQ_4.onnx` | 59,074,342 B | 快速/CPU 兜底分离 | 推荐 | 同上 | 社区权重，商用前确认上游 |
| `timbre.colorsplitter` | `timbre-v1.pt` | 17,100,415 B | 音色嵌入 | 推荐 | ColorSplitter 仓库固定 commit | MIT |
| `vad.silero` | `silero_vad.onnx` | 1,888,608 B | 人声活动检测 | 推荐 | Silero VAD 仓库 | MIT |
| `tagging.ast` | Hugging Face snapshot | 约 350 MB | 场景标签（Music/Speech/Singing…） | 可选（缺失跳过） | [MIT/ast-finetuned-audioset-10-10-0.4593](https://huggingface.co/MIT/ast-finetuned-audioset-10-10-0.4593) | BSD-3-Clause |

`timbre.colorsplitter` 的 SHA256：

```text
7e975269badb2325bea04d2cec58218901d791aeb6b8d622f0136d45282a3cac
```

## 默认降级行为

- 没有 BS-Roformer：自动使用 `UVR-MDX-NET-Inst_HQ_4.onnx`（CPU/ONNX），并在结果中写 warning。
- 没有 AST：跳过场景标签，音乐判定退化为伴奏能量 + 谐波比。
- 没有 ColorSplitter 权重：音色模块自动回退 MFCC，并在 warnings 中说明。
- 没有 Silero ONNX：尝试 Silero 包内置模型 → JIT → 能量门限 VAD。

## 下载源与镜像

- 分离模型：`https://huggingface.co/lainlives/audio-separator-models/resolve/main/`
- 国内镜像：设置 `HF_ENDPOINT=https://hf-mirror.com`（`fetch_models.py` 默认会使用该镜像变量）
- 音色权重：GitHub Raw / jsDelivr（固定 commit `50c9616dbb82f179af0d432f53d5014857e7f9a5`）
- Silero：GitHub Raw / jsDelivr
- AST：Hugging Face；需要时可在模型页下载

## 手动放置位置

```text
models/
├─ separator/
│  ├─ model_bs_roformer_ep_317_sdr_12.9755.ckpt
│  ├─ model_bs_roformer_ep_317_sdr_12.9755.yaml
│  └─ UVR-MDX-NET-Inst_HQ_4.onnx
├─ colorsplitter/
│  └─ timbre-v1.pt
├─ silero/
│  └─ silero_vad.onnx
└─ hf/   # AST snapshot（由 huggingface_hub 管理）
```

`models/separator/download_checks.json`、`mdx_model_data.json`、`vr_model_data.json` 是 audio-separator 运行时文件，可忽略/删除。
