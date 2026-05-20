"""Allow `python -m gux ...`."""
from gux.cli import main
import sys

if __name__ == "__main__":
    sys.exit(main())
