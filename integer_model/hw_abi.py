"""KWT fixed profile packet v1: 64B header, 128B directory, LE integers.

Weights are stored in four output-lane banks. Unpacking restores original
logical arrays, including omitted all-zero QKV biases and exp[4096].
"""
import hashlib
import struct
import zlib
import numpy as np

MAGIC=b'KWT8PKT\x00'
HEADER=struct.Struct('<8sHBBIII32sII')
ENTRY=struct.Struct('<32s8sBBH3IIII32s28x')
assert HEADER.size==64 and ENTRY.size==128


def bank_weights(w):
    k,o=w.shape
    assert w.dtype==np.int8 and o%8==0
    return w.reshape(k,o//8,4,2).transpose(2,1,0,3).copy().reshape(-1).tobytes()


def unbank_weights(data,shape):
    k,o=shape
    return np.frombuffer(data,np.int8).reshape(4,o//8,k,2).transpose(2,1,0,3).reshape(k,o).copy()


def pack(arrays,profile,layer=None):
    kind=0 if layer is None else 1
    selected={k:v for k,v in arrays.items() if (k=='exp_lut' if layer is None else k.startswith(f'l{layer:02d}_'))}
    names=sorted(selected)
    records=[];payload=bytearray()
    for name in names:
        a=selected[name]
        if name.endswith(('_q_b','_k_b','_v_b')):
            if np.any(a):raise ValueError('Only proven zero bias may be omitted')
            continue
        original=a
        if name=='exp_lut':
            if a.shape!=(4097,) or a[-1]!=0:raise ValueError('Invalid exp sentinel')
            a=a[:4096]
        layout=1 if name.endswith('_w') else 0
        raw=bank_weights(a) if layout else a.astype(a.dtype.newbyteorder('<'),copy=False).tobytes()
        padding=(-len(payload))%16;payload.extend(bytes(padding));offset=len(payload)
        payload.extend(raw)
        shape=list(original.shape)+[0]*(3-original.ndim)
        records.append(ENTRY.pack(name.encode(),original.dtype.newbyteorder('<').str.encode(),original.ndim,layout,0,
            *shape,offset,len(raw),zlib.crc32(raw),hashlib.sha256(original.tobytes()).digest()))
    directory=b''.join(records);body=directory+payload
    header=HEADER.pack(MAGIC,1,kind,255 if layer is None else layer,len(records),len(directory),len(payload),bytes.fromhex(profile),zlib.crc32(body),0)
    crc=zlib.crc32(header[:-4]);header=header[:-4]+struct.pack('<I',crc)
    return header+body


def unpack(packet,profile,schema,layer=None):
    if len(packet)>65536:raise ValueError('Packet exceeds 64KiB slot capability')
    if len(packet)<HEADER.size:raise ValueError('Truncated header')
    magic,version,kind,lid,count,dlen,plen,digest,bodycrc,headercrc=HEADER.unpack(packet[:64])
    if magic!=MAGIC or version!=1 or kind!=(0 if layer is None else 1) or lid!=(255 if layer is None else layer):raise ValueError('Unsupported capability/version/layer')
    if digest.hex()!=profile:raise ValueError('Profile hash mismatch')
    if zlib.crc32(packet[:60])!=headercrc or zlib.crc32(packet[64:])!=bodycrc:raise ValueError('CRC mismatch')
    if dlen!=count*ENTRY.size or len(packet)!=64+dlen+plen:raise ValueError('Length mismatch')
    expected={k:v for k,v in schema.items() if (k=='exp_lut' if layer is None else k.startswith(f'l{layer:02d}_'))}
    actual={};ranges=[];last_name=''
    for pos in range(count):
        data=ENTRY.unpack(packet[64+pos*128:64+(pos+1)*128])
        nb,db,ndim,layout,reserved,*rest=data
        name=nb.rstrip(b'\0').decode('ascii');dtype=np.dtype(db.rstrip(b'\0').decode('ascii'))
        shapes=rest[:3];offset,length,crc=rest[3:6];logicalhash=rest[6]
        if name not in expected or name<=last_name or reserved or ndim>3 or layout not in [0,1]:raise ValueError('Invalid descriptor/name/order')
        if dtype.kind not in 'iu' or dtype.byteorder=='>':raise ValueError('Unsupported integer dtype/endian')
        shape=tuple(shapes[:ndim]);expected_shape=tuple(expected[name]['shape'])
        if shape!=expected_shape or dtype!=np.dtype(expected[name]['dtype']):raise ValueError('Schema mismatch')
        if offset%16 or offset+length>plen or any(offset<b and a<offset+length for a,b in ranges):raise ValueError('Overlapping/out-of-range data')
        ranges.append((offset,offset+length));last_name=name
        raw=packet[64+dlen+offset:64+dlen+offset+length]
        if zlib.crc32(raw)!=crc:raise ValueError('Array CRC mismatch')
        if layout!=(1 if name.endswith('_w') else 0):raise ValueError('Layout mismatch')
        elements=int(np.prod(shape,dtype=np.int64)) if shape else 1
        if name=='exp_lut':elements-=1
        if length!=elements*dtype.itemsize:raise ValueError('Array length mismatch')
        if layout:a=unbank_weights(raw,shape)
        else:
            a=np.frombuffer(raw,dtype).copy()
            if name=='exp_lut':a=np.append(a,np.array([0],dtype))
            a=a.reshape(shape)
        if hashlib.sha256(a.tobytes()).digest()!=logicalhash or logicalhash.hex()!=expected[name]['sha256']:raise ValueError('Logical hash mismatch')
        actual[name]=a
    for name,desc in expected.items():
        if name not in actual:
            if not name.endswith(('_q_b','_k_b','_v_b')):raise ValueError('Missing parameter')
            a=np.zeros(desc['shape'],dtype=desc['dtype'])
            if hashlib.sha256(a.tobytes()).hexdigest()!=desc['sha256']:raise ValueError('Omitted nonzero parameter')
            actual[name]=a
    return actual
