"""Inventory fixed-commit public SRAM models; never infer unavailable macro PPA."""
import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path
from local_tools import ROOT, sha


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    out = args.output.resolve()
    assert not out.exists(), 'Use a new inventory revision'
    out.mkdir(parents=True)
    commit = 'c9ac73efc603ec3b830caecd7874b1419c1b7d41'
    url = 'https://api.github.com/repos/The-OpenROAD-Project/OpenROAD-flow-scripts/contents/flow/platforms/nangate45/lib?ref=' + commit
    request = urllib.request.Request(url, headers={'User-Agent': 'ChipCompetition-reference-inventory'})
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = response.read()
    except urllib.error.HTTPError as error:
        failure=dict(inventory_complete=False,directory_url=url,commit=commit,
                     HTTP_status=error.code,reason=str(error),
                     exact_4096x16_availability='unknown; failed catalog access does not prove absence',
                     macro_PPA_claimed=False,script_sha256=sha(Path(__file__)))
        (out/'failure.json').write_text(json.dumps(failure,indent=2))
        (out/'manifest.json').write_text(json.dumps({'failure.json':sha(out/'failure.json')},indent=2))
        raise SystemExit('Public catalog unavailable; failure preserved without inferred macro PPA')
    (out / 'upstream_directory.json').write_bytes(payload)
    listing = json.loads(payload)
    models = [dict(name=item['name'], url=item.get('download_url'), git_blob=item['sha'])
              for item in listing if 'ram' in item['name'].lower() or 'sram' in item['name'].lower()]
    result = dict(inventory_complete=True, upstream='The-OpenROAD-Project/OpenROAD-flow-scripts',
                  commit=commit, directory_url=url, models=models,
                  exact_4096x16_named_candidates=[item for item in models if '4096x16' in item['name']],
                  SRAM_model_bound_to_design=False, macro_PPA_claimed=False,
                  scope='public reference discovery only; geometry/pin/timing/power compatibility must be checked before use',
                  script_sha256=sha(Path(__file__)))
    (out / 'summary.json').write_text(json.dumps(result, indent=2))
    (out / 'manifest.json').write_text(json.dumps({path.name:sha(path) for path in out.iterdir() if path.is_file()}, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
