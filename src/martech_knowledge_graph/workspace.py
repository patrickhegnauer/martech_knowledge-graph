"""
Shared demo/org workspace resolution.

server.py and mcp_server.py are separate OS processes that both need to
agree on which workspace (the bundled read-only examples/ directory, or a
caller's own --data-dir) is currently active. They read that from the same
.mkg-mode marker file, but differently: server.py caches the mode in
memory for the life of the Flask process (updated the instant POST
/api/mode writes a new one), while mcp_server.py has no long-lived request
loop to invalidate a cache in, so it re-reads the marker fresh on every
tool call instead -- cheap (one small text file) and always correct.
"""

from pathlib import Path

MODE_MARKER_NAME = ".mkg-mode"


def resolve_active_dir(data_dir: Path, examples_dir: Path) -> Path:
    """Returns examples_dir (demo mode) or data_dir (org mode), per the marker file."""
    marker = Path(data_dir) / MODE_MARKER_NAME
    mode = marker.read_text(encoding="utf-8").strip() if marker.exists() else "demo"
    if mode not in ("demo", "org"):
        mode = "demo"
    return Path(examples_dir) if mode == "demo" else Path(data_dir)
