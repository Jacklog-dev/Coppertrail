"""Entry point of the frozen build: the same as `python -m coppertrail.ui`."""

from coppertrail.ui.app import main

if __name__ == "__main__":
    raise SystemExit(main())
