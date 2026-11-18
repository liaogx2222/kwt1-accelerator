"""Check the exact one-pass PV opportunity; no changed RTL/PPA is claimed."""
import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
REV='595724b88858b142a407f6a5c4761945252d523b'

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True,type=Path);a=ap.parse_args();out=a.output.resolve()
    assert not out.exists(),'preserve evidence';out.mkdir(parents=True)
    sources={}
    for n in ['rtl/v2/kwt_mac_array.sv','rtl/v2/kwt_layer_banked.sv']:
        b=subprocess.check_output(['git','show',REV+':'+n],cwd=ROOT)
        sources[n]=hashlib.sha256(b).hexdigest()
        if n.endswith('kwt_mac_array.sv'):
            text=b.decode();assert 'input wire [ROWS*16-1:0] a' in text
            assert "unsigned_a?$signed({1'b0,a[r*16+:16]})" in text and 'reg signed [31:0] acc' in text
    # Exhaust every unsigned16 probability and signed8 V product. 17-bit
    # signed av represents unsigned16 exactly; b is sign-extended signed8.
    prob=np.arange(65536,dtype=np.int64)
    exhaustive=0
    for v in range(-128,128):
        old=(prob&255)*v+((prob>>8)*v)*256;new=prob*v
        assert np.array_equal(old,new)
        exhaustive+=int(prob.size)
    # All-prefix absolute bounds prove each99-term accumulator, each old
    # byte-plane accumulator, and the final reconstruction cannot overflow.
    bound=99*65535*128;plane_bound=99*255*128
    assert bound<2**31 and plane_bound<2**31
    # Independent full8x16 tile reductions exercise sums, not just products.
    rng=np.random.default_rng(20261113);tiles=4096;outputs=0
    for i in range(tiles):
        p=rng.integers(0,65536,(8,99),dtype=np.int64)
        v=rng.integers(-128,128,(99,16),dtype=np.int64)
        if i<8:
            p[:]=[0,255,256,32767,32768,65535,1,65280][i]
            v[:]=-128 if i%2 else 127
        old=(p&255)@v+((p>>8)@v)*256;new=p@v
        assert np.array_equal(old,new)
        assert np.max(np.abs(new))<=bound
        # These equal signed32 values become the same sign-extended input
        # to the unchanged requant/RNE consumer; no rounding is moved/fused.
        assert np.array_equal(old.astype(np.int32).astype(np.int64),new)
        outputs+=int(new.size)
    old_MAC=12*13*4*2*99;new_MAC=old_MAC//2
    old_setup=12*13*4*2*3;new_setup=old_setup//2 # CLEAR,READ,END per plane
    estimated_compute_saving=(old_MAC-new_MAC)+(old_setup-new_setup)
    assert estimated_compute_saving==63648
    old_bound=1674852
    # The prior loose bound counted P_MAC but omitted these setup states.
    amended_bound=old_bound-(old_MAC-new_MAC)
    result=dict(passed=True,analysis_and_software_equivalence_only=True,source_revision=REV,source_Git_blob_sha256=sources,
        identity='sum(p*v) = sum((p&255)*v) + 256*sum((p>>8)*v)',
        probabilities='all unsigned16 bit patterns',V='all signed8 bit patterns including-128',terms=99,
        exhaustive_product_pairs=exhaustive,full_tiles=tiles,full_tile_outputs=outputs,
        random_seed=20261113,signed32_absolute_accumulator_bound=bound,old_byte_plane_absolute_bound=plane_bound,
        RNE_input_bit_identity_checked=True,RNE_formula_changed=False,
        estimated_compute_cycles_saved=estimated_compute_saving,original_P_MAC_cycles=old_MAC,proposed_P_MAC_cycles=new_MAC,
        MAC_launches_before=672672,MAC_launches_after_estimate=672672-(old_MAC-new_MAC),
        prior_frozen_FSM_subset_lower_bound=old_bound,amended_compute_subset_lower_bound=amended_bound,
        amended_ideal_upper_tasks_per_second_at150MHz=float(Fraction(150000000,amended_bound)),
        alone_sufficient_for120=False,RTL_implementation_done=False,new_full_SoC_cycles_measured=None,
        new_RTL_or_four_state_or_gate_verification_done=False,area_mm2=None,power_mW=None,energy_uJ=None,
        tools=dict(python=sys.version,numpy=np.__version__))
    (out/'proof.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ['passed','exhaustive_product_pairs','full_tiles','full_tile_outputs',
        'signed32_absolute_accumulator_bound','estimated_compute_cycles_saved','amended_compute_subset_lower_bound',
        'amended_ideal_upper_tasks_per_second_at150MHz','alone_sufficient_for120','RTL_implementation_done']},indent=2))

if __name__=='__main__':main()
