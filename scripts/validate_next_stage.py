"""One entry point for task reset / II=1 / fused scheduling / layer RTL evidence."""
import argparse,hashlib,json,sys,time,subprocess
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
OUT=ROOT/'testdata/next_stage_v1'
from validate_kwt1_r2 import artifacts
from integer_model.execution_banks import ExecutionBanks
from integer_model.packet_stream import PacketStream
from integer_model.system_io import SystemIO

def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2),encoding='utf-8')

def reset_tests(out):
    packets,p=artifacts();b=ExecutionBanks();s=PacketStream(b,packets,p);tests={}
    def cleared(label):
        s.reset();before={k:v.copy() for k,v in b.mem.items()}
        for _ in range(100):
            ready,accepted=s.beat();assert not ready and not accepted
            assert not s.common_valid and not s.layer_valid and not s.input_valid
            assert not s.last_seen and not s.fifo and s.position==0 and s.crc==0
            assert not b.a_swap and not s.busy and s.state=='idle'
        assert all(np.array_equal(v,b.mem[k]) for k,v in before.items())
        tests[label]='passed: 100 idle cycles, no old completion or write'
    s.transfer('common.bin');cleared('completed_common')
    for label,beats in [('header',5),('directory',18),('payload',70),('FIFO_drain',len(packets['common.bin'])//4)]:
        s.begin('common.bin')
        data=packets['common.bin']
        for i in range(beats):s.beat(True,int.from_bytes(data[4*i:4*i+4],'little'),4*i+4==len(data),True)
        cleared(label)
    s.busy=True;b.a_swap=True;cleared('compute_and_swapped_slot')
    s.transfer('common.bin');s.transfer('layer_00.bin');s.load_input(np.ones((99,64),np.int8));s.start(0)
    try:s.begin('layer_01.bin')
    except RuntimeError:tests['busy_overwrite']='rejected'
    else:raise AssertionError('busy accepted')
    cleared('active_layer')
    # Old A slot remains dirty; reset restores mapping before input writes.
    b.a_swap=True;s.reset();x=np.full((99,64),53,np.int8);s.load_input(x)
    from integer_model.bank_model import address
    for t in range(99):
        for c in range(64):
            bank,addr,byte=address('token',0,t,c,64)
            assert (b.peek_word('A'+str(bank),addr)>>(8*byte))&255==53
    tests['input_after_swapped_task']='6336 physical codes equal'
    # Reset during blocking packet/input/output, using an asynchronous edge.
    for phase in ('input','output'):
        s.reset();tick=b.tick;fired=[False]
        def interrupt(ops=(),tag='',issue=None):
            result=tick(ops,tag,issue)
            if not fired[0] and tag==('input_pair_bank_drain' if phase=='input' else 'output_accept'):
                fired[0]=True;s.reset()
            return result
        b.tick=interrupt
        if phase=='output':s.next_layer=12
        try:s.load_input(x) if phase=='input' else s.writeback()
        except RuntimeError as e:assert 'aborted by reset' in str(e)
        else:raise AssertionError('reset did not abort')
        b.tick=tick;cleared(phase+'_in_flight')
    # Hold TLAST pending bank drain: next frame must not be accepted.
    s.begin('common.bin');data=packets['common.bin']
    for i in range(len(data)//4):
        s.beat(True,int.from_bytes(data[4*i:4*i+4],'little'),i==len(data)//4-1)
    assert s.last_seen
    assert s.beat(True,0,False,False)==(False,False)
    tests['post_TLAST']='ready stays low until next explicit begin'
    s.reset();tick=b.tick;fired=[False]
    def packet_reset(*args,**kwargs):
        result=tick(*args,**kwargs)
        if not fired[0]:fired[0]=True;s.reset()
        return result
    b.tick=packet_reset
    try:s.transfer('common.bin')
    except RuntimeError as e:assert 'aborted by reset' in str(e)
    else:raise AssertionError('packet reset did not abort')
    b.tick=tick;cleared('packet_accept_edge')
    from integer_model.task_banks import TaskBanks
    from integer_model.event_arithmetic import Engine
    lease=TaskBanks(b);engine=Engine(lease);result=engine.issue('mul',[3,7],unit='mul')
    s.reset()
    try:engine.read(result)
    except RuntimeError as e:assert 'compute aborted' in str(e)
    else:raise AssertionError('old compute lease survived reset')
    tests['inflight_compute_owner']='old actor canceled, no post-reset bank write'
    lease=TaskBanks(b);engine=Engine(lease);result=engine.issue('mul',[3,7],unit='mul');engine.step(3)
    s.reset()
    try:engine.read(result)
    except RuntimeError as e:assert 'compute aborted' in str(e)
    else:raise AssertionError('completed stale result survived reset')
    tests['completed_compute_owner']='ready result also canceled by reset'
    io=SystemIO(s);s.reset();cycle=b.cycle
    try:io.packet('common.bin')
    except RuntimeError as e:assert 'I/O aborted' in str(e)
    else:raise AssertionError('old I/O owner survived reset')
    assert b.cycle==cycle
    tests['old_system_IO_owner']='canceled before transport or final ack'
    s.reset();s.next_layer=12;io=SystemIO(s);idle=b.idle
    def ack_reset(n,tag='idle'):
        result=idle(n,tag)
        if tag=='final_host_write_ack':s.reset()
        return result
    b.idle=ack_reset
    try:io.output()
    except RuntimeError as error:assert 'I/O aborted' in str(error)
    else:raise AssertionError('reset at final ack committed old result')
    b.idle=idle;assert not io.summary()['final_ack_included']
    tests['final_ack_reset']='reset during final host ack cannot commit old window'
    from integer_model.fused_layer import FusedLayer,FusedEngine,Node
    # Scheduler values, not expected/golden constants, feed every dependent node.
    for corrupt in (False,True):
        model=FusedLayer.__new__(FusedLayer)
        model.e=FusedEngine(corrupt=(lambda m:m['op']=='mul') if corrupt else None)
        nodes=[Node('rne_sat8',[Node('mul',[i,3],64,True,'mul'),0],8,True,'rne') for i in range(16)]
        result=model.graph(nodes);values=[model.e.consume(c) for c in result]
        for c in result:model.e.drop(c)
        assert (values==[i*3 for i in range(16)]) is (not corrupt)
        model.e.close()
    tests['fused_fault_detection']='corrupt retired multiplier result changes actual downstream RNE codes'
    engine=FusedEngine();root=engine.issue('sqrt',[4],32,False,'sqrt',advance=False)
    pair=engine.issue('divmod',[1<<40,2],64,False,'div',shape=(2,),advance=False)
    assert root.ready==32 and pair.ready==96
    assert engine.consume(root)==2 and engine.consume(pair).tolist()==[1<<39,0]
    engine.drop(root);engine.drop(pair);engine.close()
    tests['shared_iterative_resource']='independent sqrt/div serialize at 0 and32, matching one RTL server'
    rne_vectors=0
    for line in (ROOT/'testdata/r1r2/release/rtl/vectors.txt').read_text().splitlines():
        op,x,y,shift,q,r,error=line.split()
        if int(op)!=2:continue
        value=int(x,16);value=value-(1<<64) if value>>63 else value
        try:answer=Engine.compute('rne',[value,int(shift)])
        except OverflowError:assert int(error)==1
        else:assert not int(error) and answer&((1<<64)-1)==int(q,16)
        rne_vectors+=1
    tests['RNE_model_RTL_boundary_contract']=f'{rne_vectors} independent vectors, including negative shift reaching INT64_MIN'
    for label,mutate in [('body_CRC',lambda d:d[:-1]+bytes([d[-1]^1])),('short',lambda d:d[:-4]),
                         ('long',lambda d:d+b'\0'*4),('header',lambda d:b'X'+d[1:]),
                         ('directory',lambda d:d[:105]+bytes([d[105]^1])+d[106:])]:
        s.reset();bad=mutate(packets['common.bin']);stat=s.transfer('common.bin',bad,source_gap=7,write_gap=11)
        assert stat['error'] and not s.common_valid and not s.can_start(0)
        tests['packet_'+label]=stat['error']
    save(out/'reset.json',dict(passed=True,tests=tests));print('RESET PASS',flush=True)

def cold_tasks(out,fused=False):
    from run_r1r2_low_memory import install
    install()
    from integer_model.executable_layer import ExecutableLayer
    from integer_model.runtime import Encoder
    from integer_model.register_contract import budget
    packets,p=artifacts();b=ExecutionBanks();s=PacketStream(b,packets,p);rows=[]
    meta=json.loads((ROOT/'testdata/integer_v1/params/manifest.json').read_text())
    fixture=np.load(ROOT/'testdata/integer_v1/fixture/encoder_input.npy',mmap_mode='r')
    saved=np.load(ROOT/'testdata/integer_v1/validation/encoder_output_int8.npy',mmap_mode='r')
    for task,sample in enumerate((187,4444)):
        s.reset();assert not b.a_swap;io=SystemIO(s);task_start=b.cycle
        q=np.clip(np.rint(fixture[sample].astype(np.float64)/meta['decode_scales']['encoder_input']),-127,127).astype(np.int8)
        taps={};Encoder(p,lambda n,v,c:taps.update({n:v[0].copy()}) if n.count('/')==1 else None)(q[None])
        io.packet('common.bin');input_stat=io.input(q);current=q;layers=[]
        for i in range(12):
            b.a_swap=bool(i%2);io.packet(f'layer_{i:02d}.bin');s.start(i);start=b.cycle
            expected={n.split('/')[1]:v for n,v in taps.items() if n.startswith(f'layer_{i:02d}/')}
            cls=ExecutableLayer
            if fused:
                from integer_model.fused_layer import FusedLayer
                cls=FusedLayer
            from integer_model.task_banks import TaskBanks
            model=cls(p,out/'unused.gz',i,banks=TaskBanks(b),preloaded=True,coefficient_cache=True,gelu_ports=8,pingpong=True)
            current=model.run(current,expected);s.finish_layer()
            if fused:
                from validate_fused_schedule import fused_budget
                register=fused_budget(model.measured)
            else:register=budget(model.measured)
            layers.append(dict(layer=i,cycles=b.cycle-start,mismatches=0,register_budget=register))
            save(out/f'task_{task}_checkpoint.json',dict(sample=sample,layers=layers,complete=False))
            print('COLD',task,'layer',i,'cycles',b.cycle-task_start,flush=True)
        output,output_stat=io.output();assert output==saved[sample].tobytes()==current.tobytes()
        np.save(out/f'task_{task}_output.npy',current)
        row=dict(task=task,sample=sample,layers=layers,input=input_stat,output=output_stat,io=io.summary(),
                 total_cycles=b.cycle-task_start,mismatches=0,output_sha256=hashlib.sha256(output).hexdigest(),
                 same_stream_object=id(s),same_banks_object=id(b),cold_packets=13)
        rows.append(row);save(out/f'task_{task}.json',row)
    save(out/'cold_tasks.json',dict(passed=True,tasks=rows,same_objects=True,output_codes=12672))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--stage',choices=['all','reset','cold','pipeline','schedule','layer','control','audit','banks','io','check'],required=True)
    ap.add_argument('--output',type=Path,default=OUT);ap.add_argument('--fused',action='store_true');ap.add_argument('--quick',action='store_true')
    a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    if a.stage=='all':
        if a.quick:raise ValueError('--quick is only supported for individual debug stages')
        if (a.output/'verification.json').exists() and json.loads((a.output/'verification.json').read_text()).get('passed'):
            raise ValueError('released evidence exists; choose a fresh --output directory')
        for stage,folder,flags in [('reset','',[]),('io','io_final',[]),('pipeline','pipeline_final',[]),('cold','cold_fixed',[]),
                                   ('schedule','fused',[]),('banks','banks_final',[]),('cold','cold_fused',['--fused']),('audit','',[]),
                                   ('layer','layer_final',[]),('control','control_final',[]),('check','',[])]:
            subprocess.run([sys.executable,__file__,'--stage',stage,'--output',str(a.output/folder),*flags],check=True)
    elif a.stage=='reset':reset_tests(a.output)
    elif a.stage=='cold':cold_tasks(a.output,a.fused)
    else:
        import runpy
        sys.argv=[a.stage,'--output',str(a.output)]+(['--quick'] if a.quick else [])
        runpy.run_path(str(ROOT/'scripts'/('validate_'+{'pipeline':'pipeline_rtl','schedule':'fused_schedule','layer':'layer_rtl','control':'layer_control','audit':'fused_audit','banks':'fused_banks','io':'system_io','check':'next_evidence'}[a.stage]+'.py')),run_name='__main__')
if __name__=='__main__':main()
