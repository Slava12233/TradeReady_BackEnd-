"""SHA-256 checksum utilities for model file integrity verification.

Provides defence-in-depth against insecure deserialization (OWASP A8) for
pickle-based model files (SB3 ``.zip``) and joblib-serialised classifier files
(``.joblib``).

Usage::

    from agent.strategies.checksum import save_checksum, verify_checksum, SecurityError

    # After saving a model:
    save_checksum(Path("agent/strategies/rl/models/ppo_seed42.zip"))
    # Creates: ppo_seed42.zip.sha256

    # Before loading a model:
    verify_checksum(Path("agent/strategies/rl/models/ppo_seed42.zip"))
    # Raises SecurityError if digest does not match.
    # Logs a WARNING and returns True (backwards compat) if no .sha256 sidecar.

Protocol
--------
- Sidecar file: ``<original_filename>.<original_suffix>.sha256``
  e.g. ``ppo_seed42.zip.sha256`` or ``regime_classifier.joblib.sha256``.
- File format: a single lowercase hex SHA-256 digest with no trailing newline.
- Missing sidecar: warning + proceed (backwards compatibility with pre-checksum
  models — callers may tighten this in future by checking the return value).
- Digest mismatch: raises :class:`SecurityError` immediately.  The caller must
  not proceed with loading the file.

Security note
-------------
The checksum provides integrity verification, not authentication.  It detects
accidental corruption and opportunistic tampering (a file dropped into the
models directory).  For a stronger guarantee, store checksums in a version-
controlled manifest file and sign the manifest with a private key.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

# Read files in 8 KiB chunks — balances memory usage against syscall overhead.
_CHUNK_SIZE: int = 8192


class SecurityError(Exception):
    """Raised when a model file's checksum does not match its sidecar.

    This exception signals a potential integrity violation.  The caller must
    not load or execute the file.  Common causes:

    - The file was corrupted in transit or on disk.
    - The file was replaced by a different (potentially malicious) artifact.
    - The checksum sidecar belongs to a different version of the file.

    Args:
        message: Human-readable description including the file path and the
            expected/actual digest prefixes so the caller can log it without
            truncating useful context.
    """


def compute_checksum(file_path: Path) -> str:
    """Compute the SHA-256 hex digest of a file.

    Reads the file in :data:`_CHUNK_SIZE`-byte chunks so that large model
    files (SB3 `.zip` files can exceed 100 MB) are never fully buffered in
    memory.

    Args:
        file_path: Absolute or relative path to the file to hash.

    Returns:
        Lowercase hexadecimal SHA-256 digest string (64 characters).

    Raises:
        FileNotFoundError: If ``file_path`` does not exist.
        OSError: On any other I/O error.
    """
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def save_checksum(file_path: Path) -> Path:
    """Compute the SHA-256 digest of *file_path* and write it as a sidecar.

    The sidecar file is written to the same directory as the model file.  Its
    name is ``<original_filename>.<original_suffix>.sha256``
    (e.g. ``ppo_seed42.zip.sha256``).

    Args:
        file_path: Path to the model file that was just saved.

    Returns:
        Path to the written ``.sha256`` sidecar file.

    Raises:
        FileNotFoundError: If ``file_path`` does not exist yet.
        OSError: On any I/O error during writing.
    """
    file_path = Path(file_path)
    digest = compute_checksum(file_path)
    checksum_path = file_path.with_suffix(file_path.suffix + ".sha256")
    checksum_path.write_text(digest, encoding="ascii")
    logger.info(
        "checksum.saved",
        path=str(file_path),
        digest_prefix=digest[:16],
        sidecar=str(checksum_path),
    )
    return checksum_path


def verify_checksum(file_path: Path) -> bool:
    """Verify that *file_path* matches its ``.sha256`` sidecar.

    Behaviour:

    - **No sidecar**: logs a WARNING at ``checksum.no_sidecar`` and returns
      ``True`` for backwards compatibility with pre-checksum model artifacts.
      Callers that require strict verification should check the return value
      and refuse to load the model when ``False`` would be safer.
    - **Sidecar present, digest matches**: logs ``checksum.verified`` at INFO
      and returns ``True``.
    - **Sidecar present, digest mismatches**: raises :class:`SecurityError`.
      The caller must not proceed.

    Args:
        file_path: Path to the model file about to be loaded.

    Returns:
        ``True`` when verification passed (or was skipped due to missing sidecar).

    Raises:
        SecurityError: When the computed digest does not match the stored digest.
        FileNotFoundError: If ``file_path`` itself does not exist.
    """
    file_path = Path(file_path)
    checksum_path = file_path.with_suffix(file_path.suffix + ".sha256")

    if not checksum_path.exists():
        logger.warning(
            "checksum.no_sidecar",
            path=str(file_path),
            expected_sidecar=str(checksum_path),
            msg="Loading model without integrity verification — no .sha256 sidecar found.",
        )
        return True

    expected = checksum_path.read_text(encoding="ascii").strip()
    actual = compute_checksum(file_path)

    if actual != expected:
        raise SecurityError(
            f"Checksum mismatch for {file_path}: "
            f"expected {expected[:16]}..., got {actual[:16]}... "
            "Do not load — the file may be corrupted or tampered with."
        )

    logger.info(
        "checksum.verified",
        path=str(file_path),
        digest_prefix=actual[:16],
    )
    return True
