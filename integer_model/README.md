# KWT-1 整数参考

硬件边界为 `[batch,99,64] int8 -> [batch,99,64] int8`。`runtime.py` 从输入到输出仅执行整数运算，默认使用 NumPy INT32 MAC；`cuda_matmul.py` 可选用 `torch._int_mm` 执行真正的 INT8×INT8→INT32 Dense。CPU/GPU 后端必须输出相同整数码，GPU 仅用于缩短软件实验时间。

数值定义见 [INTEGER_NUMERICS_V1.md](../../docs/architecture/INTEGER_NUMERICS_V1.md)。权重和主干为对称 INT8（不使用 -128），QK/PV 累加为 INT32，Softmax 为 UINT16、尺度 1/65535，残差为 INT16；LayerNorm 使用 INT64 归约、`math.isqrt`、整数倒数和 Q20 affine；GELU 使用每层 256 字节表。非线性、残差和任何编码器层都不回退浮点。

`export.py` 是离线浮点参数转换。前端、输入编码、输出解码、冻结软件分类头、误差统计均在整数编码器以外。参数表只取决于冻结权重、训练标定尺度和算子公式，不含样本答案。

## 复现实验

在 `keyword-transformer` 工作目录执行。已有证据目录会被保护，复跑时选择新输出目录。默认 fixture 为完整 4445 条 Validation，`--max-samples 0` 表示全量。

```powershell
# TF2.4 + addons0.12.1 + numpy1.19.5 的既有环境，关闭增强与 TF32。
D:\anaconda\envs\kwt_ref\python.exe scripts/export_kwt1_integer_fixture.py --output testdata/integer_repeat/fixture

# 以下用现有默认 Python3.10 + NumPy（单元测试额外需要 SciPy）。
python scripts/export_kwt1_integer_params.py --raw testdata/integer_repeat/fixture/raw_parameters.npz --output testdata/integer_repeat/params
python tests/integer/test_integer.py --params testdata/integer_repeat/params --output testdata/integer_repeat/unit_tests.json
python scripts/validate_kwt1_integer_encoder.py --fixture testdata/integer_repeat/fixture --params testdata/integer_repeat/params --output testdata/integer_repeat/validation

# 可选：已安装 PyTorch2.6/CUDA12.6，Dense 使用整数 GPU 运算。
python scripts/validate_kwt1_integer_encoder.py --fixture testdata/integer_repeat/fixture --params testdata/integer_repeat/params --output testdata/integer_repeat/validation_cuda --dense-backend cuda-int8
```

本轮默认产物在 `testdata/integer_v1/`。可直接对已冻结 fixture 和 params 运行新的输出目录，省去再次处理音频。`tests/integer/test_cuda_backend.py` 针对本轮默认目录检查所有 72 个 Dense、完整首批输出及单样本全部阶段。

## 产物与边界

- `fixture/manifest.json`：checkpoint/原实现/前端导出脚本哈希、推理模式、批次和数据哈希；`samples.json` 为实际 Validation 顺序、路径、音频哈希和零波形静音标识。
- `params/parameters.npz`：全部整数权重、bias、M/shift、残差系数、LN 常数及 LUT；`manifest.json` 为逐数组 dtype/shape/hash、解码尺度及静态范围证明。NPZ 用于软件参考，后续 RTL 需按指定端序和布局导出二进制，不可直接把 ZIP 容器当硬件内存布局。
- `validation/encoder_output_int8.npy`：全部 99×64 输出；`integer_trace_first_batch.npz` 为首批全部 313 个阶段/诊断张量（含累加器）。
- `validation/metrics.json`、预测/分类别 CSV：同一批 FP32/整数 Top-1、混淆矩阵、最终全张量误差及源/产物哈希。
- `stage_ranges.csv`：全量范围、真实剪裁次数和边界命中数；二者分开统计。输入编码剪裁次数单列于 metrics。
- `local_nonlinear_errors.csv`：全量同一整数输入的 Softmax/LN 误差，LN 含剪裁/排除剪裁两种统计；p99 仅首批样本，并有明确列名。
- `stage_errors_first_batch.csv`：首批各阶段相对原 FP32 的累计误差，不冒称全量逐层误差。

运行时溢出是错误，不静默回绕。所有 12 层和全部 99 行都执行。模拟耗时是工作机软件运行时间，不代表 150MHz ASIC 延迟。此模型不提供 cycle、SRAM 端口、PPA 或 RTL 一致性签核。训练标定沿用既有 2048 条统计 CSV，原始标定缺少逐音频身份清单；本轮冻结 CSV 哈希，没有重新调标定或读取 testing batch。
