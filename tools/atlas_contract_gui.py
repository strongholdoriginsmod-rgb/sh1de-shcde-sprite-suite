"""Entry point for the unchanged, separately packaged atlas contract CLI."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'extras/atlas-contract'))
from atlas_contract.__main__ import main
if __name__=='__main__':
    raise SystemExit(main())
