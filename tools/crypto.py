"""
Encrypts/decrypts sensitive user-provided secrets (Claude API keys) 
before they touch the database.

The encryption key itself lives in .env as ENCRYPTION_KEY — 
never in code, never in the database, never logged.

Generate a key once with:
    python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Then put that value in .env as:
    ENCRYPTION_KEY=<generated value>
"""

import os
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()

_ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

if not _ENCRYPTION_KEY:
    raise RuntimeError(
        "ENCRYPTION_KEY not found in .env. Generate one with:\n"
        "python3 -c \"from cryptography.fernet import Fernet; "
        "print(Fernet.generate_key().decode())\"\n"
        "Then add it to .env as ENCRYPTION_KEY=<value>"
    )

_fernet = Fernet(_ENCRYPTION_KEY.encode())


def encrypt_secret(plaintext: str) -> str:
    """
    Encrypts a plaintext secret (e.g. a Claude API key) for storage.
    Returns a string safe to store in the database.
    """
    if not plaintext:
        return ""
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    """
    Decrypts a previously encrypted secret.
    Returns the original plaintext.

    Raises cryptography.fernet.InvalidToken if the ciphertext
    is corrupted or was encrypted with a different key.
    """
    if not ciphertext:
        return ""
    return _fernet.decrypt(ciphertext.encode()).decode()