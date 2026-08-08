"""Backward-compatible launcher for the packaged OmniSonic application."""

from omnisonic.app import main


if __name__ == "__main__":
    raise SystemExit(main())
