# KWT1 作品设计报告 — LN4 优化版

2026-11-17 定稿。以 `reports/submission_review_20261113` 为底稿，把周期与吞吐从 System Bus v1 的
门级实测值替换为 LN4 合并版的全 SoC RTL 实测值，其余章节、图表与版式保持不变。

## 本版数据来源

- 仿真：Verilator 5.48 编译完整 SoC（真实 E203 + 固定 ROM + 加速器 + 100 宏契约模型），
  case 0 冷任务，`host_gap=4`，输出 1,584 字与金标准逐字一致（`mismatches=0`）。
- 口径：门级 TB（`flow/soc_metrics/tb_soc_metrics.sv`）的 `first_tick` 在 `host_en && host_ready`
  记录，对应 RTL TB 的 `legacy_first_tick`；门级 `host_write` 内含 `repeat(4)`，与本版
  `--host-gap 4` 一致，故两版周期数严格可比。
- 复现：`scripts/prepare_ln4.py` → `scripts/check_pv16_soc.py --cases 0 --host-gap 4`。

## 关键数字

| 项 | 参考版本 | 本设计 LN4 |
|---|---|---|
| 成功任务拍数 | 2,407,596 | **2,256,857** |
| 吞吐量 @150 MHz | 62.3028 task/s | **66.4641 task/s** |
| 单任务耗时 @150 MHz | 16.0506 ms | **15.0457 ms** |
| 达成 60 task/s 所需时钟 | 144.46 MHz | **135.41 MHz** |

相对 System Bus v1（2,783,869 拍）减少 527,012 拍（−18.93%）；相对参考版本减少 150,739 拍（−6.26%）。

归因说明：−18.93% 是整条优化链（dense→score→softmax→iter→ln4）的累计收益，
其中 LN4 单步相对 iter_fast 仅省约 8,370 拍（0.37%）。9.2 节保留了 System Bus 接入本身
使周期增加 376,273 拍的历史事实，随后由优化链压回并反超。

## 已知限制

- 报告中的周期与吞吐为 **RTL 级**（Verilator）实测，非门级 VCS；同步设计下周期数应与门级一致，
  但不是同一网表。
- 150 MHz 时序仍有负裕量（r3 TT：异步 max 组 recovery WNS ≈ −0.78 ns、TNS −65.91 ns；
  hfclk setup WNS −0.76 ns、hold WNS −0.19 ns），66.46 task/s 为按目标频率折算值。
- 8.2 节注明本版本未取得完整任务功耗与能耗，参考版本实测另列。

## 生成方式

```bash
python build.py          # DOCX
python export_pdf.py     # PDF，需 Word COM（pywin32）
```

`build.py` 输出 `30022_uv_KWT1_作品设计报告_LN4优化版.docx`，`export_pdf.py` 更新目录与页码后
导出同名 PDF。`facts.py` 是唯一数字源，正文通过 `F.CYC_TASK`、`F.TPS_150`、`F.MS_TASK` 派生。
