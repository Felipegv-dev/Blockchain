"""Módulo 1 — Wallets y Claves.

Cada usuario tiene un par de llaves ECDSA sobre la curva **secp256k1**:

* clave privada  -> ``SigningKey``   (lo que se usa para *firmar*).
* clave pública  -> ``VerifyingKey`` (lo que se usa para *verificar*).

La **dirección** del usuario se define como el ``SHA-256`` de su clave pública
(en formato hexadecimal). Esa dirección es el identificador único del usuario y
es lo que aparece en las salidas de las transacciones.
"""

from __future__ import annotations

import hashlib

from ecdsa import SECP256k1, SigningKey, VerifyingKey
from ecdsa.util import sigdecode_der, sigencode_der_canonize

# Mitad del orden de la curva: una firma ECDSA es canónica (low-S) si s <= n/2.
_HALF_ORDER = SECP256k1.order // 2


def sha256_hex(data: bytes) -> str:
    """Devuelve el SHA-256 de ``data`` en hexadecimal."""
    return hashlib.sha256(data).hexdigest()


def address_from_public_key_hex(public_key_hex: str) -> str:
    """Calcula la dirección (SHA-256 de la clave pública) a partir del hex."""
    return sha256_hex(bytes.fromhex(public_key_hex))


def verify_signature(public_key_hex: str, signature_hex: str, message: bytes) -> bool:
    """Verifica una firma ECDSA (DER) sobre ``message`` con la clave pública dada.

    Rechaza además las firmas **no canónicas** (high-S): ECDSA es maleable, así
    que ``(r, s)`` y ``(r, n - s)`` verifican ambas; exigir ``s <= n/2`` evita
    que un tercero altere la firma y, con ello, el ``txid`` de la transacción.

    Devuelve ``True`` si la firma es válida y canónica, ``False`` ante cualquier
    error (clave mal formada, firma inválida, high-S, etc.).
    """
    try:
        sig = bytes.fromhex(signature_hex)
        _r, s = sigdecode_der(sig, SECP256k1.order)
        if s > _HALF_ORDER:
            return False  # firma no canónica (maleable)
        vk = VerifyingKey.from_string(bytes.fromhex(public_key_hex), curve=SECP256k1)
        return vk.verify(sig, message, hashfunc=hashlib.sha256, sigdecode=sigdecode_der)
    except Exception:
        return False


class Wallet:
    """Una cartera: par de llaves ECDSA + dirección derivada.

    Es una *simulación educativa*: la clave privada se mantiene en memoria y
    puede serializarse a hex para persistir el estado. En un sistema real la
    clave privada **nunca** debería guardarse en claro.
    """

    def __init__(self, signing_key: SigningKey, name: str = "") -> None:
        self.signing_key: SigningKey = signing_key
        self.verifying_key: VerifyingKey = signing_key.get_verifying_key()
        self.name: str = name

    # ------------------------------------------------------------------ #
    # Creación
    # ------------------------------------------------------------------ #
    @classmethod
    def generate(cls, name: str = "") -> "Wallet":
        """Genera una wallet nueva con una clave privada aleatoria."""
        return cls(SigningKey.generate(curve=SECP256k1), name=name)

    @classmethod
    def from_private_key_hex(cls, private_key_hex: str, name: str = "") -> "Wallet":
        """Reconstruye una wallet a partir de su clave privada en hex."""
        sk = SigningKey.from_string(bytes.fromhex(private_key_hex), curve=SECP256k1)
        return cls(sk, name=name)

    # ------------------------------------------------------------------ #
    # Representaciones de las llaves
    # ------------------------------------------------------------------ #
    @property
    def private_key_hex(self) -> str:
        """Clave privada en hexadecimal (32 bytes)."""
        return self.signing_key.to_string().hex()

    @property
    def public_key_hex(self) -> str:
        """Clave pública (punto de la curva) en hexadecimal (64 bytes)."""
        return self.verifying_key.to_string().hex()

    @property
    def address(self) -> str:
        """Dirección del usuario: SHA-256 de la clave pública."""
        return sha256_hex(self.verifying_key.to_string())

    # ------------------------------------------------------------------ #
    # Firma
    # ------------------------------------------------------------------ #
    def sign(self, message: bytes) -> str:
        """Firma ``message`` con la clave privada y devuelve la firma en hex (DER).

        Usa firma determinista (RFC 6979) y forma canónica **low-S**
        (``sigencode_der_canonize``) para que la firma no sea maleable.
        """
        signature = self.signing_key.sign_deterministic(
            message,
            hashfunc=hashlib.sha256,
            sigencode=sigencode_der_canonize,
        )
        return signature.hex()

    # ------------------------------------------------------------------ #
    # Utilidades
    # ------------------------------------------------------------------ #
    def short_address(self, n: int = 10) -> str:
        """Versión corta de la dirección, útil para mostrar en tablas."""
        return f"{self.address[:n]}…"

    def to_dict(self) -> dict:
        """Serializa la wallet (incluye la clave privada) para persistir."""
        return {
            "name": self.name,
            "private_key": self.private_key_hex,
            "public_key": self.public_key_hex,
            "address": self.address,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Wallet":
        return cls.from_private_key_hex(data["private_key"], name=data.get("name", ""))

    def __repr__(self) -> str:  # pragma: no cover - sólo depuración
        label = self.name or self.short_address()
        return f"<Wallet {label} addr={self.address[:10]}…>"
