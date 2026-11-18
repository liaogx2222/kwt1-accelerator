"""Verify canonical CRC replay into compact RTL storage and map the bank path."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import struct
import subprocess

from local_tools import ROOT, sha


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True)
    rel = out.relative_to(ROOT).as_posix()
    fixtures = ROOT/'testdata/input16_rtl_20261105/trim2_e203'
    manifest = json.loads((fixtures/'manifest.json').read_text())
    packets = [fixtures/'common.bin.hex'] + [fixtures/f'layer_{i:02d}.bin.hex' for i in range(12)]
    layout = dict(fc1_w=(8032,16384,64,256), fc2_w=(25184,16384,256,64),
                  k_w=(42336,4096,64,64), o_w=(48320,4096,64,64),
                  q_w=(52928,4096,64,64), v_w=(57632,4096,64,64))
    for layer, path in enumerate(packets, -1):
        assert sha(path)==manifest[path.name], path
        raw = b''.join(int(w,16).to_bytes(4,'little') for w in path.read_text().split())
        header = struct.unpack_from('<8sHBBIII32sII',raw)
        assert header[5]==header[4]*128 and len(raw)==64+header[5]+header[6], path
        if layer<0:
            continue
        weights = {}
        for index in range(header[4]):
            fields = struct.unpack_from('<32s8sBBH3IIII32s28x',raw,64+index*128)
            name = fields[0].rstrip(b'\0').decode()
            if name.endswith('_w'):
                assert name.startswith(f'l{layer:02d}_') and fields[3]==1 and fields[2]==2
                weights[name[4:]] = (64+header[5]+fields[8],fields[9],*fields[5:7])
        assert weights==layout, (path,weights)

    block = ROOT/'rtl/block_transfer'
    trim = ROOT/'rtl/input16_trim2'
    bank = block/'kwt_compact_weight_banks.sv'
    frontend = block/'kwt_verified_block_reader.sv'
    tb = block/'tb_compact_weight_banks.sv'
    sram = trim/'kwt_sram_sp.sv'
    blackbox = trim/'kwt_tech_sram_blackbox.sv'
    liberty = ROOT/'third_party/nangate45_reference/lib/NangateOpenCellLibrary_typical.lib'
    cwd = '/mnt/e/project/ChipCompetition/keyword-transformer'

    def linux(command, log):
        with (out/log).open('w') as handle:
            subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc',f'cd {cwd} && {command}'],
                           stdout=handle, stderr=subprocess.STDOUT, check=True)

    sources = ' '.join(p.relative_to(ROOT).as_posix() for p in (bank,frontend,tb,sram))
    top = 'tb_compact_weight_banks'
    linux(f'verilator --binary --timing -j 2 -Wno-fatal -DKWT_SIM --top-module {top} --Mdir {rel}/model '
          f'-Irtl/input16_trim2/generated {sources}','build.log')
    linux(f'{rel}/model/V{top} +root={fixtures.relative_to(ROOT).as_posix()}','simulation.log')
    log = (out/'simulation.log').read_text()
    pattern = r'PASS NORMAL cycles=\s*(\d+) source_reads=\s*(\d+) replay_words=\s*(\d+) halfwords=\s*(\d+) matrices=\s*(\d+) disjoint_ops=\s*(\d+)'
    cycles, reads, replay, halfwords, matrices, overlap = map(int,re.search(pattern,log).groups())
    assert (reads,replay,halfwords,matrices,overlap)==(378656,189328,294912,72,589824)
    assert 'PASS FAULTS' in log

    lib = liberty.relative_to(ROOT).as_posix()
    top = 'kwt_compact_weight_banks'
    (out/'mapping.ys').write_text(f'''read_liberty -lib {lib}
read_verilog -sv -DKWT_TECH_SRAM {bank.relative_to(ROOT).as_posix()} {sram.relative_to(ROOT).as_posix()} {blackbox.relative_to(ROOT).as_posix()}
synth -top {top} -flatten -noabc
dfflibmap -liberty {lib}
abc -liberty {lib}
clean
check -assert
stat -liberty {lib}
write_json {rel}/mapped.json
''')
    linux(f'yosys -Q -s {rel}/mapping.ys','synthesis.log')
    mapped = json.loads((out/'mapped.json').read_text())
    cells = Counter(item['type'] for item in mapped['modules'][top]['cells'].values())
    assert cells['kwt_tech_sram_1024x16']==16 and cells['kwt_tech_sram_4096x16']==4
    area = float(re.search(r'Chip area for module .*?:\s+([\d.]+)',(out/'synthesis.log').read_text())[1])/1e6
    bound = [Path(__file__),*packets,bank,frontend,tb,sram,blackbox,liberty,trim/'generated/kwt_profile.svh']
    report = dict(passed=True,scope='portable dual-pass CRC, compact weight-bank consumer fixture',
                  actual_E203=False,full_encoder=False,frame_count=13,cycles_after_staging=cycles,staging_reads=reads,
                  replay_words=replay,weight_halfwords=halfwords,weight_matrix_count=matrices,mismatches=0,
                  concurrent_disjoint_bank_accesses=overlap,private_SRAM_bytes=65536,
                  mapped_macro_instances={'1024x16':16,'4096x16':4},bank_partition_area_mm2=area,
                  throughput_tasks_per_second=None,mean_SoC_power_mW=None,complete_counted_area_mm2=None,
                  source_sha256={p.relative_to(ROOT).as_posix():sha(p) for p in bound})
    (out/'verification.json').write_text(json.dumps(report,indent=2))
    (out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2))
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
