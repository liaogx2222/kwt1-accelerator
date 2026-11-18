"""Python 3.6: external old-Bash argv fix, reusing only the verified VCS cache."""
import hashlib
from pathlib import Path
import subprocess
import sys

MANIFEST = '2c9225dfaaf97ad6c9be370463a27d6e902dc57e79ba5ba7897db4ba72178987'
RUNNER = '0a70a606f0eb679416194fd897d61ff362c5e106c21ec8288c6212141811400b'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def transform(text):
    original_out = 'OUT="$BASE/c$CASE$SUFFIX"'
    assert text.count(original_out) == 1 and text.count('"${INIT_ARGS[@]}"') == 1
    text = text.replace(original_out, 'OUT="$BASE/c${CASE}${SUFFIX}_resume_20261112"')
    first = text.index('if [[ -e "$MODEL" ]]; then')
    last = text.index('\nfi\n', first)+4
    text = text[:first]+'''test -f "$MODEL/ready" || { echo 'REQUIRE_EXISTING_READY_VCS_CACHE'; exit 2; }
cmp "$OUT/inputs.sha256" "$MODEL/inputs.sha256"
sha256sum -c "$MODEL/simv.sha256"
sha256sum "$ROOT/review_tools/run_gate_resume.sh" > "$OUT/resume_wrapper.sha256"
'''+text[last:]
    command = '"$MODEL/simv" +CASE="$CASE"'
    assert text.count(command) == 1
    text = text.replace(command, '''# Special positional argv remains defined even when empty under old Bash -u.
set --
case "$INIT_MODE" in
  zero) set -- +KWT_SRAM_INIT_ZERO ;;
  x) set -- +KWT_SRAM_INIT_X ;;
esac
'''+command).replace('"${INIT_ARGS[@]}"', '"$@"')
    assert 'vcs -full64' not in text and '"${INIT_ARGS[@]}"' not in text
    return text


def install(root):
    root = root.resolve()
    raw = (root/'flow/run_gate.sh').read_bytes()
    if sha((root/'manifest.json').read_bytes()) != MANIFEST or sha(raw) != RUNNER:
        raise SystemExit('GATE_RESUME_SOURCE_MISMATCH')
    subprocess.check_call([sys.executable, str(root/'flow/project.py'), 'check-dc'])
    cache = root/'build/gate/model'
    if not (cache/'ready').is_file() or not (cache/'simv').is_file():
        raise SystemExit('GATE_RESUME_READY_CACHE_MISSING')
    data = transform(raw.decode('utf-8')).encode('utf-8')
    target = root/'review_tools/run_gate_resume.sh'
    if target.exists() and target.read_bytes() != data:
        raise SystemExit('GATE_RESUME_REFUSE_OVERWRITE')
    target.parent.mkdir(exist_ok=True)
    if not target.exists():
        with target.open('xb') as stream:
            stream.write(data)
    print('KWT_GATE_RESUME_INSTALLED '+sha(data))
    print('KWT_GATE_RESUME_SCOPE frozen_source_unchanged cached_model_only new_result_directory')
    return target


if __name__ == '__main__':
    install(Path.cwd())
