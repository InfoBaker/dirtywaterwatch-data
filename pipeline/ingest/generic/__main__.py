"""python -m ingest.generic <source-id> [--file saved] [--meta metadata.json] [--out path] | --list | --check"""
import sys

from ingest.generic.runner import main

sys.exit(main())
