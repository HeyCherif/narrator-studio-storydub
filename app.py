"""Legacy PyWebView launcher; the desktop bridge shares backend.engine."""
from backend.engine import main

if __name__ == "__main__":
    raise SystemExit(main())
