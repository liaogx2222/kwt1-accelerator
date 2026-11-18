"""Python 3.6 immutable multi-source pool installer, no old build copies."""
import hashlib
import json
from pathlib import Path, PurePosixPath


def sha(data):return hashlib.sha256(data).hexdigest()


def install(base,capsule):
    base=base.resolve();meta=json.loads((capsule/'install.json').read_text())
    parent=base.parent;pool={}
    for name,allowed in meta['source_roots'].items():
        assert '/' not in name and '\\' not in name
        root=parent/name;raw=(root/'manifest.json').read_bytes()
        assert sha(raw) in allowed,'SOC_POOL_MANIFEST_MISMATCH '+name
        for n,row in json.loads(raw)['files'].items():
            path=PurePosixPath(n);assert not path.is_absolute() and '..' not in path.parts
            data=(root/n).read_bytes();assert sha(data)==row['sha256'],'SOC_POOL_SOURCE_CHANGED '+name+'/'+n
            pool[sha(data)]=data
    for h,size in meta['assets'].items():
        assert len(h)==64 and all(c in '0123456789abcdef' for c in h)
        data=(capsule/'assets'/h).read_bytes();assert len(data)==size and sha(data)==h,'SOC_ASSET_CHANGED'
        pool[h]=data
    for h,patch in meta['hex_patches'].items():
        words=pool[patch['base_sha256']].decode('ascii').splitlines()
        seen=set()
        for i,word in patch['changes']:
            assert i not in seen and 0<=i<len(words) and len(word)==8 and all(c in '0123456789abcdefABCDEF' for c in word)
            seen.add(i);words[i]=word
        newline=patch.get('newline','\n')
        assert newline in ['\n','\r\n']
        data=(newline.join(words)+(newline if patch.get('trailing_newline',True) else '')).encode('ascii')
        assert sha(data)==h,'SOC_HEX_PATCH_CHANGED'
        pool[h]=data
    planned={}
    for n,row in meta['files'].items():
        path=PurePosixPath(n);assert not path.is_absolute() and '..' not in path.parts and '\\' not in n
        data=pool[row['sha256']];assert len(data)==row['bytes'];planned[n]=data
    name=meta['directory'];assert name.startswith('kwt_soc_input16_metrics_') and '/' not in name and '\\' not in name
    target=parent/name;assert not target.exists(),'SOC_METRICS_TARGET_EXISTS_PRESERVE'
    target.mkdir()
    for n,data in planned.items():
        p=target/n;p.parent.mkdir(parents=True,exist_ok=True)
        with p.open('xb') as f:f.write(data)
    print('SOC_METRICS_INSTALLED '+str(target))
    print('SOC_SCOPE full_digital_reference_CAD_not_yet_run prior_jobs_untouched')
    return target


if __name__=='__main__':install(Path.cwd(),Path(__file__).resolve().parent)
