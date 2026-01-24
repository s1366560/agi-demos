"""
API Key Encryption Service

Provides AES-256-GCM encryption for LLM provider API keys at rest.
Uses environment variable for encryption key management.
"""

import base64
import os
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr


class EncryptionService:
    """
    Service for encrypting and decrypting sensitive data using AES-256-GCM.

    Encryption key is loaded from environment variable LLM_ENCRYPTION_KEY.
    If not set, a warning is logged and a development key is used (NOT FOR PRODUCTION).
    """

    def __init__(self, encryption_key: Optional[str] = None):
        """
        Initialize encryption service.

        Args:
            encryption_key: 32-byte (256-bit) encryption key as hex string.
                          If None, loads from LLM_ENCRYPTION_KEY environment variable.
        """
        self.key = self._load_or_generate_key(encryption_key)
        self.aesgcm = AESGCM(self.key)

    def _load_or_generate_key(self, provided_key: Optional[str]) -> bytes:
        """
        Load encryption key from environment or generate a development key.

        Args:
            provided_key: Optional encryption key

        Returns:
            32-byte encryption key
        """
        import warnings

        def try_parse_hex(key: str, source: str) -> Optional[bytes]:
            """Try to parse a hex string, return None if invalid."""
            try:
                key_bytes = bytes.fromhex(key)
                if len(key_bytes) == 32:
                    return key_bytes
                else:
                    warnings.warn(
                        f"{source} must be exactly 32 bytes (64 hex characters), "
                        f"got {len(key_bytes)} bytes. Using development key.",
                        RuntimeWarning,
                        stacklevel=4,
                    )
                    return None
            except ValueError:
                warnings.warn(
                    f"{source} is not a valid hex string. Using development key. "
                    'Generate a valid key with: python -c "import os; print(os.urandom(32).hex())"',
                    RuntimeWarning,
                    stacklevel=4,
                )
                return None

        # Try provided key first
        if provided_key:
            result = try_parse_hex(provided_key, "Provided encryption key")
            if result:
                return result

        # Try environment variable
        env_key = os.environ.get("LLM_ENCRYPTION_KEY")
        if env_key and env_key.strip() and not env_key.startswith("your_"):
            result = try_parse_hex(env_key, "LLM_ENCRYPTION_KEY")
            if result:
                return result

        # Generate a warning and use development key (NOT FOR PRODUCTION)
        warnings.warn(
            "LLM_ENCRYPTION_KEY not set or invalid. Using insecure development key. "
            "DO NOT USE IN PRODUCTION!",
            RuntimeWarning,
            stacklevel=2,
        )
        return os.urandom(32)  # Generate random key for development

    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt plaintext string using AES-256-GCM.

        Args:
            plaintext: String to encrypt

        Returns:
            Base64-encoded encrypted data (nonce + ciphertext)
        """
        if not plaintext:
            raise ValueError("Cannot encrypt empty string")

        # Generate random nonce (96 bits for GCM)
        nonce = os.urandom(12)

        # Encrypt
        ciphertext = self.aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)

        # Combine nonce + ciphertext and encode as base64
        encrypted_bytes = nonce + ciphertext
        return base64.b64encode(encrypted_bytes).decode("utf-8")

    def decrypt(self, encrypted_text: str) -> str:
        """
        Decrypt encrypted string using AES-256-GCM.

        Args:
            encrypted_text: Base64-encoded encrypted data (nonce + ciphertext)

        Returns:
            Decrypted plaintext string
        """
        if not encrypted_text:
            raise ValueError("Cannot decrypt empty string")

        # Decode base64
        encrypted_bytes = base64.b64decode(encrypted_text.encode("utf-8"))

        # Extract nonce (first 12 bytes) and ciphertext
        nonce = encrypted_bytes[:12]
        ciphertext = encrypted_bytes[12:]

        # Decrypt
        plaintext = self.aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext.decode("utf-8")

    def encrypt_secret_str(self, secret: SecretStr) -> str:
        """
        Encrypt a Pydantic SecretStr.

        Args:
            secret: SecretStr to encrypt

        Returns:
            Encrypted string
        """
        return self.encrypt(secret.get_secret_value())

    def decrypt_to_secret_str(self, encrypted_text: str) -> SecretStr:
        """
        Decrypt to a Pydantic SecretStr.

        Args:
            encrypted_text: Encrypted string

        Returns:
            SecretStr containing decrypted value
        """
        return SecretStr(self.decrypt(encrypted_text))


# Singleton instance for use in dependency injection
_encryption_service: Optional[EncryptionService] = None


def get_encryption_service() -> EncryptionService:
    """
    Get or create singleton encryption service instance.

    Returns:
        EncryptionService instance
    """
    global _encryption_service
    if _encryption_service is None:
        # Import Settings here to ensure .env file is loaded via pydantic-settings
        from src.configuration.config import get_settings

        settings = get_settings()
        encryption_key = settings.llm_encryption_key
        _encryption_service = EncryptionService(encryption_key)
    return _encryption_service
