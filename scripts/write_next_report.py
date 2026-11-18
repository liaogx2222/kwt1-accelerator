"""Write measured comparison only after all evidence summaries exist."""
import json,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'testdata/next_stage_v1'
def load(p):return json.loads(p.read_text())
def main():
    verified=load(OUT/'verification.json');assert verified['passed']
    fixed=load(OUT/'cold_fixed/cold_tasks.json')['tasks'];fused=load(OUT/'cold_fused/cold_tasks.json')['tasks']
    schedule=load(OUT/'fused/summary.json')['layers'];regs=load(OUT/'register_assessment.json')
    pipe=load(OUT/'pipeline_final/summary.json');rtl=load(OUT/'layer_final/summary.json');audit=load(OUT/'fused_audit.json')
    core=sum(t['cycles'] for t in fused[0]['layers']);oldcore=sum(t['cycles'] for t in fixed[0]['layers'])
    improvement=(1-fused[0]['total_cycles']/fixed[0]['total_cycles'])*100
    rows='\n'.join(f'| {name} | '+ ' / '.join(str(t['total_cycles']) for t in data)+' | '+' / '.join(f"{t['total_cycles']/150000:.6f}" for t in data)+' |' for name,data in [('修复后的旧缓存/GELU8/槽切换对照',fixed),('同8×8、单lane融合流水',fused)])
    stages={s:sum(r['stages'].get(s,0) for r in schedule if r['mode']=='normal') for s in ['q','k','v','qk','softmax','pv','o','residual_ln1','fc1','gelu','fc2','residual_ln2']}
    traffic=[r for r in schedule if r['mode']=='normal'];reads=sum(r['reads'] for r in traffic);writes=sum(r['writes'] for r in traffic)
    body=f'''# 任务复位、II=1、融合调度与单层功能RTL v1.5

日期：2026-10-21。固定数值仍为INTEGER_NUMERICS_V1，NPZ/manifest、整数golden及原证据未改。
新验收：[verification.json](../../keyword-transformer/testdata/next_stage_v1/verification.json)，
[复现入口](../../keyword-transformer/integer_model/NEXT_STAGE_README.md)。本轮四项功能推进通过；60ms内部目标仍未达到。

## 1. 验收结果

| 工作 | 本轮结果 | 边界 |
|---|---|---|
| 复位、连续任务、完整I/O | 同一Stream/Banks复用，两不同冷任务各完整12层、重载13包，最终12672码0差异；融合方案也两任务0差异 | 外部两段链路/CPU为显式模型 |
| II=1算术 | 三套elastic流水逐拍19500cycle、连续mul1198/RQ{pipe['pipelines']['rq']['consecutive_accepts']}拍接受；864组固定profile RQ、582组精确迭代延迟、旧1818向量通过 | 功能及握手，不等于库时序 |
| 调度融合 | 12参数普通/边界24层152064码0差异；首套两输入{sum(r['complete'] for r in audit['layers'])}事件独立审计通过 | 完整事件独立重放覆盖profile0两输入；其余输出golden复核 |
| 单层功能RTL | 实际包/整数数据驱动，12个profile/class配对，{rtl['output_codes']}实际DUT输出码0差异，错误/stall/reset/同DUT连续冷装载通过 | 12例配对，不是144组合；行为内存尚未落实20宏端口 |

LN-E01固定profile局部例外延续，原6处1%质量失败保留。SOURCE-E01仍OPEN，无新历史线索，未再次猜测训练序列。

## 2. reset/abort与系统窗口

reset清除last_seen、长度、CRC、活动帧、FIFO、所有有效位、busy、层序和A槽映射。SRAM保持脏内容；完成common后reset再100idle不复活，header/directory/payload/FIFO/输入/输出/计算期间reset均验收。
TaskBanks/SystemIO以epoch取消旧任务：包括已完成未消费结果，旧计算不能再写银行，旧外部传输不能补发写回应答。TLAST后ready关闭，下一帧必须显式begin。坏CRC/长度/头/目录及忙时覆盖拒绝。

窗口从common第一段传输前开始，到最终主机写回应答结束。参数757312B、输入6336B、输出6336B都走三段32bit路径：host↔CPU staging↔device staging↔SRAM stream。外部两段按每beat600/MBps拍串行计费；CPU每word4拍+每frame500拍；设备端实际握手/CRC/SRAM；最终ack1拍。没有跨包max抵扣或免费预置输入。

五档25/50/100/200/600MB/s账本通过；100MB/s输入设备端13887拍，不能再使用旧5056拍情景值。两个任务使用全局连续时钟，周期相位可有数拍差异。该路径是可参数化的工程假设，仍需指定平台确认。
早期账本的output外部两段沿用正向链路标签；现输出顺序为device→CPU→host。两段带宽/字节/延迟完全相同，已在io_direction_assessment中只交换返回段标签，保留所有原始时间戳、周期和原账本；这项模型元数据校正不改变任何整窗结果。

## 3. 算术资源和周期契约

| 资源 | 无stall延迟 | II | 实现 |
|---|---:|---:|---|
| 32×32→64 mul | 3 | 1 | 4个16×16部分积→合并→符号修正 |
| S64 RNE/饱和 | 1 | 1 | 独立elastic级，保留tie-even和对称饱和 |
| RQ串接 | 4 | 1 | shift/sat/tag与产品共同受ready控制 |
| U64 div / isqrt | 64 / 32 | 64 / 32 | 共用迭代服务器，消费响应时可接新请求 |

修正了旧迭代实现接收后才做首步的多一拍问题；第一步现在在接受边沿执行。582向量逐拍测试含最小II与保持响应。reset取消在途tag，非reset背压不丢失/重复/乱序。独立审计确认实际模型的div/sqrt不重叠，允许映射到共用服务器。迭代错误响应与有效操作不同，性能契约绑定非零除数等合法域。

## 4. 同配置性能与暂存

保持8×8 PE、单个宽乘法/RNE/ALU、相同参数和100MB/s路径；均使用系数缓存、GELU8寄存器表和A槽切换。Dense bias由实际系数初始化PE；RQ多lane结果交错发射；Softmax常量移位连线化，LN归约/归一化/仿射按依赖流水。所有RNE/饱和点保持，结果在事件退休时计算，没有oracle代算。

| 同配置方案 | 两冷任务周期 | 假设150MHz，ms |
|---|---:|---:|
{rows}

核心含11次交接从{oldcore}降至{core}，减少{(1-core/oldcore)*100:.3f}%；整窗减少{improvement:.3f}%。目标9Mcycle仍差{fused[0]['total_cycles']-9000000}cycle。此处用修复I/O后的对照，不能直接拿原限定窗口92.78432ms当同边界基线。

单层核心810816→473871cycle。新12层普通输入阶段周期：`{json.dumps(stages,separators=(',',':'))}`。
每层新银行读/写总数保存在fused各summary；这些数含同样的离线初始化/交接，不能当作系统传输量。系统传输按冷任务ledger逐段核对。
普通12层离线模型实际记录合计读{reads}、写{writes}个16bit字；profile0读982804/写133466、系数供数29920B，并已完整独立SRAM重放通过（最高8端口，同银行0冲突）。该读写口径含每层独立装载输入/公共表，不能乘成13包连续任务的线上写次数。

动态数据/在途生存期峰值3424B；另常驻控制401B、物理RQ流水55B、迭代/响应池82B，保守总预算3962B，余134B。动态与物理池重叠数据仍重复计入，不借空闲池额度，全部12套普通/边界通过。
早期3880B未保留空闲迭代池，已由[register_assessment](../../keyword-transformer/testdata/next_stage_v1/register_assessment.json)取代，原lifetimes不改。旧缓存对照按同一物理池保守上界4126B，超30B，不能继续沿用旧3984B证明；融合方案提供满足4KiB的上界。160KiB SRAM和2580B模板ROM另计，均不是面积实测。

## 5. 单层RTL及下一步

kwt_layer直接加载canonical common/layer包；固定header/profile ROM与滚动CRC拒收坏包。完整Dense/QK/Softmax/PV/O/残差/LN/FC/GELU由整数RTL产生输出，expected只由TB读取。Dense包含8×8累加器，99尾块仅发有效lane；Attention控制器按单查询行推进。

主TB覆盖四种坏包、周期性供数/计算/输出stall、MAC中途reset、最终响应保持时reset和同DUT连续冷任务；补充控制TB覆盖部分输入reset、-128/错误TLAST/非法profile、忙时覆盖、Softmax div/LN sqrt/LN reciprocal在途reset。DUT实际输出保存observed hex，最终检查用冻结golden重新复算。

该功能原型使用行为多阵列内存。**P5功能已推进，但20单口宏wrapper/端口仲裁、整层RTL周期与融合模型等价、12层SoC/E203集成仍未完成。** 不用功能原型的仿真周期替代银行模型性能。后续优先完成该存储映射与控制集成，再评估有限非线性lane以缩小60ms差距；指定库/宏资料到位后做150MHz、面积和能耗签核。
RQ和div/sqrt已接入共享组件；原型中其它非线性组合乘法尚须落实到单lane仲裁，当前功能通过不构成整层算术资源共享或4KiB RTL放置证明。报告中的周期和暂存上界属于显式银行/事件模型。

## 6. 复现与证据

统一命令：`D:/anaconda/python.exe scripts/validate_next_stage.py --stage all --output testdata/next_stage_replay`。锁定CPython3.10.9、NumPy1.26.2及Icarus/vvp组件hash；check消费所有必需证据，拒绝缺项/quick。选择新的output，完整入口拒绝覆盖已发布目录。
源码、编译RTL源hash、工具组件、原始输出、生存期、逐段账本和清单在`testdata/next_stage_v1`。最终核验原数值包13项历史hash、20输入及冻结runtime/export/ABI/锁文件不变；未获取testing样本，未改用户input_data排序补丁。
'''
    evroot=os.path.relpath(OUT,ROOT.parent/'docs/architecture').replace('\\','/')
    body=body.replace('../../keyword-transformer/testdata/next_stage_v1/',evroot+'/').replace('`testdata/next_stage_v1`','`'+str(OUT.relative_to(ROOT)).replace('\\','/')+'`')
    (ROOT.parent/'docs/architecture/TASK_PIPELINE_LAYER_REPORT.md').write_text(body,encoding='utf-8')
    local_model=os.path.relpath(ROOT/'integer_model',OUT).replace('\\','/')
    (OUT/'REPORT.md').write_text(body.replace(evroot+'/','./').replace('../../keyword-transformer/integer_model/',local_model+'/'),encoding='utf-8')
if __name__=='__main__':main()
