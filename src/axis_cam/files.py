"""Writing device diagnostics to disk.

Server reports, crash reports and parameter exports describe a device's
configuration in detail; Axis's privacy statement says the crash report "can
include user IDs, passwords, video images, and network traffic". Everything
this library writes for a user is therefore created owner-read/write only
(``0600``), and an existing file is tightened to the same mode rather than
inheriting whatever it had.
"""

import os
from pathlib import Path

PRIVATE_MODE = 0o600


def write_private(path: str | Path, content: bytes) -> Path:
    """Write ``content`` to ``path`` with permissions ``0600``.

    The file is created with the mode (subject to the umask, which can only
    tighten it) and then ``chmod``-ed, so a pre-existing file with wider
    permissions ends up ``0600`` as well. Parent directories are created.

    Args:
        path: Destination file.
        content: Bytes to write.

    Returns:
        The destination as a ``Path``.

    Raises:
        OSError: If the file cannot be created or written.
    """
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # O_TRUNC empties a pre-existing file before the chmod, so wider permissions
    # never apply to the new content even for an instant.
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, PRIVATE_MODE)
    with os.fdopen(fd, "wb") as handle:  # fdopen owns and closes the descriptor
        destination.chmod(PRIVATE_MODE)
        handle.write(content)  # buffered: writes everything, unlike os.write
    return destination
