import os,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'tools/rtl_v2_python'))
os.environ['YOWASP_CACHE_DIR']=str(root/'tools/yowasp-cache')
from yowasp_yosys import run_yosys
sys.exit(run_yosys(sys.argv[1:]))
