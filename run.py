"""PyInstaller entry point. Keeps the package importable from the build folder."""

import sys

from voxapp.main import main

if __name__ == "__main__":
    sys.exit(main())
