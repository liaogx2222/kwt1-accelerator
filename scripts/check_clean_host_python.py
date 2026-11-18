"""Check child environment and Tcl argument forwarding without Synopsys."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tkinter


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    a = ap.parse_args()
    out = a.output.resolve()
    if out.exists():
        raise ValueError("choose a fresh test directory")
    out.mkdir(parents=True)
    t = tkinter.Tcl()
    t.call("set", "::env(KWT_PDK_ROOT)", str(out))
    t.call("set", "::env(KWT_SRAM_DB_DIR)", str(out))
    t.call("set", "::env(KWT_HOST_PYTHON)", sys.executable)
    t.call("source", (a.project.resolve()/"flow/project.tcl").as_posix())
    keys = ["LD_LIBRARY_PATH", "LD_PRELOAD", "PYTHONHOME", "PYTHONPATH"]
    for key in keys:
        t.call("set", "::env("+key+")", "PARENT_EDA_TEST_VALUE")
    calls = []

    def execute(*args):
        expected = ["/usr/bin/env"] + [v for k in keys for v in ["-u", k]]
        assert list(args[:len(expected)]) == expected, args
        assert args[len(expected)] == sys.executable
        env = dict(os.environ)
        for k in keys:
            env.pop(k, None)
        calls.append(list(args))
        p = subprocess.run(list(args[len(expected):]), env=env, capture_output=True, text=True)
        if p.returncode:
            raise RuntimeError("child failed")
        return p.stdout.rstrip("\n")

    t.createcommand("exec", execute)
    code = "import os,json;print(json.dumps({k:os.environ.get(k) for k in " + repr(keys) + "}))"
    result = json.loads(t.call("kwt_host_python", "-c", code))
    assert all(v is None for v in result.values())
    try:
        t.call("kwt_host_python", "-c", "raise SystemExit(9)")
        raise AssertionError("child error suppressed")
    except tkinter.TclError:
        pass
    assert all(t.call("set", "::env("+k+")") == "PARENT_EDA_TEST_VALUE" for k in keys)
    report = dict(passed=True, child_environment_clean=True, parent_environment_preserved=True,
                  child_failure_propagated=True, argument_forwarding=True, EDA_execution=False,
                  scope="Tcl exec adapter checked; real env utility and DC library loader require server retry")
    (out/"summary.json").write_text(json.dumps(report,indent=2))
    (out/"calls.json").write_text(json.dumps(calls,indent=2))
    print(json.dumps(report,indent=2))


if __name__ == "__main__":
    main()
