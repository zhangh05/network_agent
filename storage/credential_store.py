"""Authenticated workspace credential storage.

The filesystem key protects credentials from accidental plaintext exposure and
detects tampering.  It is created atomically with owner-only permissions.  An
attacker who can read the whole local account can also read this key; stronger
host protection belongs in the operating-system credential vault.
"""

from __future__ import annotations

import base64
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from storage.locking import FileLock
from storage.records import workspace_record_file

CREDENTIAL_DECRYPT_FAILED = "\x00\x00CREDENTIAL_DECRYPT_FAILED\x00\x00"
_PREFIX = "cred:v3:"


def seal_credential(workspace_id: str, value: str) -> str:
    if not value:
        return ""
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(_workspace_key(workspace_id)).encrypt(
        nonce,
        value.encode("utf-8"),
        workspace_id.encode("utf-8"),
    )
    return _PREFIX + base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")


def open_credential(workspace_id: str, sealed: str) -> str:
    opened = open_credential_strict(workspace_id, sealed)
    return "" if opened == CREDENTIAL_DECRYPT_FAILED else opened


def open_credential_strict(workspace_id: str, sealed: str) -> str:
    if not sealed:
        return ""
    if not sealed.startswith(_PREFIX):
        return CREDENTIAL_DECRYPT_FAILED
    try:
        payload = base64.urlsafe_b64decode(sealed[len(_PREFIX):].encode("ascii"))
        if len(payload) < 12 + 16:
            return CREDENTIAL_DECRYPT_FAILED
        nonce, ciphertext = payload[:12], payload[12:]
        plaintext = AESGCM(_workspace_key(workspace_id)).decrypt(
            nonce,
            ciphertext,
            workspace_id.encode("utf-8"),
        )
        return plaintext.decode("utf-8")
    except Exception:
        return CREDENTIAL_DECRYPT_FAILED


def _workspace_key(workspace_id: str) -> bytes:
    path = workspace_record_file(workspace_id, "cmdb", ".credential_key")
    lock_path = path.with_name(path.name + ".lock")
    with FileLock(lock_path):
        if not path.exists():
            key = AESGCM.generate_key(bit_length=256)
            fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                os.write(fd, key)
                os.fsync(fd)
            finally:
                os.close(fd)
        key = path.read_bytes()
        if len(key) != 32:
            raise ValueError("invalid workspace credential key")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return key
