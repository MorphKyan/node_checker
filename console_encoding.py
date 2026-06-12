import sys
from typing import TextIO


def configure_stream(stream: TextIO | None, encoding: str = "utf-8") -> None:
    reconfigure = getattr(stream, "reconfigure", None)
    if not callable(reconfigure):
        return
    try:
        reconfigure(encoding=encoding, errors="replace")
    except (OSError, TypeError, ValueError):
        return


def configure_standard_streams(encoding: str = "utf-8") -> None:
    configure_stream(sys.stdout, encoding)
    configure_stream(sys.stderr, encoding)
