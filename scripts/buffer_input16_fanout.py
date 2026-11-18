"""Insert auditable non-inverting buffer trees in the frozen S16 netlist."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path

from local_tools import ROOT, sha


def cell_digest(cells, names, aliases):
    digest = hashlib.sha256()
    for name in names:
        cell = cells[name]
        connections = {
            port: [aliases.get(bit, bit) if cell['port_directions'][port] == 'input' else bit for bit in bits]
            for port, bits in cell['connections'].items()
        }
        digest.update(json.dumps([name, {**cell, 'connections': connections}], sort_keys=True).encode())
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source', type=Path, default=ROOT / 'testdata/input16_rtl_20261105/mapping_trim')
    parser.add_argument('--fanout', type=int, default=12)
    parser.add_argument('--net', action='append', default=[])
    args = parser.parse_args()
    assert 2 <= args.fanout <= 32
    source = args.source.resolve()
    out = args.output.resolve()
    out.mkdir(parents=True)
    manifest = json.loads((source / 'manifest.json').read_text())
    original = source / 'mapped.json'
    assert sha(original) == manifest['mapped.json']
    design = json.loads(original.read_text())
    top = design['modules']['kwt_input16_icb_top']
    cells = top['cells']
    nets = top['netnames']
    names = sorted(cells)
    before = cell_digest(cells, names, {})
    next_bit = max(bit for net in nets.values() for bit in net['bits'] if isinstance(bit, int)) + 1
    targets = args.net or ['accelerator.accel.task_rst_n']
    aliases = {}
    records = []
    for net in targets:
        assert len(nets[net]['bits']) == 1, net
        root = nets[net]['bits'][0]
        assert isinstance(root, int)
        sinks = [(name, pin, index) for name in sorted(cells) for pin, bits in cells[name]['connections'].items()
                 if cells[name]['port_directions'][pin] == 'input' for index, bit in enumerate(bits) if bit == root]
        assert len(sinks) > args.fanout, (net, len(sinks))
        pending = sinks
        tree = []
        while len(pending) > args.fanout:
            parents = []
            for start in range(0, len(pending), args.fanout):
                name = f'p1_tree_{len(records)}_{len(tree)}'
                bit = next_bit
                next_bit += 1
                assert name not in cells and name + '_net' not in nets
                nets[name + '_net'] = dict(hide_name=0, bits=[bit], attributes={})
                cells[name] = dict(hide_name=0, type='BUF_X1', parameters={}, attributes={},
                                   port_directions={'A': 'input', 'Z': 'output'}, connections={'A': [root], 'Z': [bit]})
                for sink, pin, index in pending[start:start+args.fanout]:
                    cells[sink]['connections'][pin][index] = bit
                aliases[bit] = root
                tree.append(name)
                parents.append((name, 'A', 0))
            pending = parents
        drivers = {cells[name]['connections']['Z'][0]: cells[name]['connections']['A'][0] for name in tree}
        for output in drivers:
            path = set()
            while output != root:
                assert output not in path and output in drivers
                path.add(output)
                output = drivers[output]
        records.append(dict(net=net, original_sinks=len(sinks), root_sinks=len(pending), added_buffers=len(tree)))
    assert before == cell_digest(cells, names, aliases)
    loads = defaultdict(int)
    for cell in cells.values():
        for pin, bits in cell['connections'].items():
            if cell['port_directions'][pin] == 'input':
                for bit in bits:
                    loads[bit] += 1
    assert max(loads[bit] for bit in aliases) <= args.fanout
    with (out / 'mapped.json').open('w') as handle:
        json.dump(design, handle, separators=(',', ':'))
    report = dict(passed=True, structural_projection_verified=True, original_cell_sha256=before, trees=records,
                  buffers=len(aliases), area_increment_mm2=len(aliases)*0.798e-6, complete_gate_regression=False,
                  source=str(original.relative_to(ROOT)), source_sha256=manifest['mapped.json'])
    (out / 'verification.json').write_text(json.dumps(report, indent=2))
    (out / 'source_bindings.json').write_text(json.dumps({str(p.relative_to(ROOT)): sha(p) for p in [original, Path(__file__)]}, indent=2))
    (out / 'manifest.json').write_text(json.dumps({p.name: sha(p) for p in out.iterdir()}, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
