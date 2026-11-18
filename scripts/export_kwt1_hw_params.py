"""P4a hardware ABI export and strict roundtrip validation; no quantization."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from integer_model.hw_abi import pack,unpack
from integer_model.export import sha


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,default=ROOT/'testdata/p4a/hw_params_verified')
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    if (a.output/'manifest.json').exists():raise FileExistsError('Preserve hardware package')
    src=ROOT/'testdata/integer_v1/params';meta=json.loads((src/'manifest.json').read_text());profile=sha(src/'manifest.json')
    assert sha(src/'parameters.npz')==meta['parameters_sha256']
    arrays=dict(np.load(src/'parameters.npz'));restored={};packets=[]
    for layer in [None]+list(range(12)):
        packet=pack(arrays,profile,layer)
        if layer is not None:assert len(packet)<=65536
        name='common.bin' if layer is None else f'layer_{layer:02d}.bin'
        (a.output/name).write_bytes(packet)
        recovered=unpack(packet,profile,meta['array_schema'],layer);restored.update(recovered)
        packets.append({'file':name,'bytes':len(packet),'sha256':hashlib.sha256(packet).hexdigest(),'restored_arrays':len(recovered)})
    assert restored.keys()==arrays.keys()
    assert all(x.dtype==arrays[k].dtype and x.shape==arrays[k].shape and x.tobytes()==arrays[k].tobytes() for k,x in restored.items())
    np.savez(a.output/'roundtrip_parameters.npz',**restored)
    tests={}
    original=(a.output/'layer_00.bin').read_bytes()
    for label,mutated in [('truncated',original[:-1]),('trailing_bytes',original+b'\x00'),('payload_corrupt',original[:-1]+bytes([original[-1]^1])),
                          ('version_corrupt',original[:8]+b'\x02\x00'+original[10:]),('header_corrupt',b'X'+original[1:])]:
        try:unpack(mutated,profile,meta['array_schema'],0)
        except ValueError:tests[label]='rejected'
        else:raise AssertionError(label)
    try:unpack(original,'0'*64,meta['array_schema'],0)
    except ValueError:tests['wrong_profile']='rejected'
    else:raise AssertionError('wrong profile')
    # Recompute all packet CRCs: these must fail structural validation, not
    # merely the earlier checksum guard.
    import struct,zlib
    from integer_model.hw_abi import HEADER,ENTRY
    def fix(packet):
        b=bytearray(packet);h=list(HEADER.unpack(b[:64]));h[-2]=zlib.crc32(b[64:]);h[-1]=0
        header=HEADER.pack(*h);b[:64]=header[:-4]+struct.pack('<I',zlib.crc32(header[:-4]));return bytes(b)
    structural={}
    over=bytearray(original);h=list(HEADER.unpack(over[:64]));over.extend(bytes(65537-len(over)));h[6]=len(over)-64-h[5];over[:64]=HEADER.pack(*h)
    structural['valid_crc_oversize']=fix(over)
    first=list(ENTRY.unpack(original[64:192]))
    for label,index,value in [('valid_crc_offset_outside_payload',8,0xFFFFFFF0),('valid_crc_wrong_array_length',9,1),('valid_crc_invalid_layout',3,7)]:
        b=bytearray(original);r=first.copy();r[index]=value;b[64:192]=ENTRY.pack(*r);structural[label]=fix(b)
    for label,b in structural.items():
        try:unpack(b,profile,meta['array_schema'],0)
        except ValueError:tests[label]='rejected'
        else:raise AssertionError(label)
    result={'abi_version':1,'profile_sha256':profile,'endianness':'little','header_bytes':64,'descriptor_bytes':128,
        'weight_layout':'bank=(o%8)//2; byte=o%2; word=(o//8)*K+k; four bank-major byte streams',
        'omissions':['36 all-zero QKV biases','exp[4096]=0'],
        'original_arrays':len(arrays),'roundtrip_arrays':len(restored),'array_byte_mismatches':0,
        'effective_payload_bytes':696448,'cold_packet_bytes':sum(r['bytes'] for r in packets),
        'packets':packets,'negative_tests':tests,'abi_source_sha256':sha(ROOT/'integer_model/hw_abi.py'),
        'export_source_sha256':sha(__file__),'schema':meta['array_schema']}
    (a.output/'manifest.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ['schema','packets']},indent=2))


if __name__=='__main__':main()
