"""Create full-validation diagnostics and a standalone report figure."""
import csv
import json
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "testdata/integer_v1"


def main():
    v = BASE / "validation"
    m = json.loads((v / "metrics.json").read_text())
    with (v / "stage_ranges.csv").open(encoding="utf-8-sig",newline="") as f:
        stages = list(csv.DictReader(f))
    with (v / "local_nonlinear_errors.csv").open(encoding="utf-8-sig",newline="") as f:
        local = list(csv.DictReader(f))
    signed = [r for r in stages if r["dtype"] in ["int8","int16"] and "/" in r["tensor"]]
    worst = sorted(signed,key=lambda r:int(r["clipped"])/int(r["elements"]),reverse=True)[:10]
    ln = [r for r in local if r["name"].endswith("/same_integer_residual")]
    lnc = [r for r in local if r["name"].endswith("clip_excluded")]
    soft = [r for r in local if r.get("max_row_l1")]
    out = {"ln_gt_1percent_with_clipping":[r["name"] for r in ln if float(r["nrmse"])>.01],
           "ln_gt_1percent_clip_excluded":[r["name"] for r in lnc if float(r["nrmse"])>.01],
           "ln_first16_p99_lsb_gt_1":[r["name"] for r in ln if float(r["first_batch_p99_abs_output_lsb"])>1],
           "softmax_l1_gt_0_005":[r["name"] for r in soft if float(r["max_row_l1"])>.005],
           "residual_clip_count":sum(int(r["clipped"]) for r in stages if r["tensor"].endswith(("residual1_sum","residual2_sum"))),
           "worst_clipping":worst}
    (v / "diagnostic_summary.json").write_text(json.dumps(out,indent=2),encoding="utf-8")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family":"DejaVu Sans","font.size":10,"axes.spines.top":False,"axes.spines.right":False})
    fig, axs = plt.subplots(1,2,figsize=(11,4.1),layout="constrained")
    rates = [100*m["fp_accuracy"],100*m["integer_accuracy"]]
    bars = axs[0].bar(["FP32","Integer v1"],rates,color=["#758ca4","#188977"],width=.55)
    axs[0].set_ylim(94,100)
    axs[0].set_ylabel("Top-1 accuracy (%)")
    axs[0].set_title(f"Same {m['samples']:,} Validation samples")
    for b,rate,count in zip(bars,rates,[m["fp_correct"],m["integer_correct"]]):
        axs[0].text(b.get_x()+b.get_width()/2,rate+.12,f"{rate:.4f}%\n{count}/{m['samples']}",ha="center",fontsize=10)
    axs[0].text(.5,.05,f"Drop: {m['accuracy_drop_pp']:.4f} percentage points",transform=axs[0].transAxes,ha="center")
    axs[1].plot(np.arange(1,25),[100*float(r["nrmse"]) for r in ln],"o-",color="#b96240",label="Including output clipping",markersize=3)
    axs[1].plot(np.arange(1,25),[100*float(r["nrmse"]) for r in lnc],"o-",color="#188977",label="Output clipping excluded",markersize=3)
    axs[1].axhline(1,color="#708090",ls="--",lw=1,label="1% development target")
    axs[1].set_ylabel("NRMSE vs float LN on same integer input (%)")
    axs[1].set_xlabel("LayerNorm stage (LN1 / LN2 for layers 0-11)")
    axs[1].set_title("Local LN error across the full validation set")
    axs[1].legend(frameon=False,fontsize=8)
    axs[1].grid(axis="y",alpha=.2)
    fig.savefig(ROOT.parent / "docs/architecture/evidence/integer_validation.png",dpi=180)
    plt.close(fig)
    print(json.dumps({"ln_fail_with_clipping":len(out['ln_gt_1percent_with_clipping']),
                      "ln_fail_clip_excluded":len(out['ln_gt_1percent_clip_excluded']),
                      "softmax_fail":out['softmax_l1_gt_0_005'],"residual_clip_count":out['residual_clip_count'],
                      "worst_clipping":worst[:3]},indent=2))


if __name__ == "__main__":
    main()
