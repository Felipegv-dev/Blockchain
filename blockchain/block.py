"""Módulo 3 — Bloques y Prueba de Trabajo (PoW).

Un bloque agrupa un conjunto de transacciones y se encadena con el anterior:

* ``index``        : posición en la cadena (0 = génesis).
* ``timestamp``    : fecha/hora de minado (epoch).
* ``transactions`` : lista de transacciones (la 1ª es la coinbase).
* ``prev_hash``    : hash del bloque anterior (mantiene la integridad).
* ``difficulty``   : nº de ceros iniciales que exige la PoW.
* ``nonce``        : número que se ajusta hasta cumplir la PoW.
* ``hash``         : SHA-256 del contenido del bloque.

La **Prueba de Trabajo** consiste en encontrar un ``nonce`` tal que el hash del
bloque empiece con ``difficulty`` ceros. Como el hash depende de las
transacciones (vía sus ``txid``), del ``prev_hash`` y de la dificultad, alterar
cualquier bloque cambia su hash e invalida todos los siguientes: la cadena es
**inmutable**.
"""

from __future__ import annotations

import hashlib
import time
from typing import Optional

from .transaction import Transaction, canonical_json


class Block:
    """Un bloque de la cadena."""

    def __init__(
        self,
        index: int,
        transactions: list[Transaction],
        prev_hash: str,
        difficulty: int,
        timestamp: Optional[float] = None,
        nonce: int = 0,
        block_hash: Optional[str] = None,
    ) -> None:
        self.index = index
        self.transactions = transactions
        self.prev_hash = prev_hash
        self.difficulty = difficulty
        # Guardamos el epoch tal cual: así el hash es reproducible al recargar.
        self.timestamp = timestamp if timestamp is not None else time.time()
        self.nonce = nonce
        self.hash = block_hash if block_hash is not None else self.compute_hash()

    # ------------------------------------------------------------------ #
    # Hashing
    # ------------------------------------------------------------------ #
    def header(self) -> dict:
        """Cabecera que se hashea.

        Incluye los ``txid`` de las transacciones: como cada txid es el hash de
        toda la transacción, basta con incluirlos para que cualquier cambio en
        una transacción altere el hash del bloque. La dificultad también entra
        en el hash, de modo que no se puede "rebajar" la PoW sin romper la cadena.
        """
        return {
            "index": self.index,
            "timestamp": self.timestamp,
            "prev_hash": self.prev_hash,
            "difficulty": self.difficulty,
            "nonce": self.nonce,
            "tx_ids": [tx.txid for tx in self.transactions],
        }

    def compute_hash(self) -> str:
        """SHA-256 del contenido del bloque (con el nonce actual)."""
        return hashlib.sha256(canonical_json(self.header())).hexdigest()

    # ------------------------------------------------------------------ #
    # Prueba de Trabajo
    # ------------------------------------------------------------------ #
    @staticmethod
    def hash_meets_difficulty(block_hash: str, difficulty: int) -> bool:
        """¿El hash empieza con ``difficulty`` ceros?"""
        return block_hash.startswith("0" * difficulty)

    # Un hash SHA-256 en hex tiene 64 caracteres: una dificultad >= 65 sería
    # imposible de cumplir y el minado nunca terminaría.
    MAX_DIFFICULTY = 64

    def mine(self) -> int:
        """Busca un ``nonce`` cuyo hash cumpla la dificultad. Devuelve nº de hashes.

        Recorre nonces de forma incremental (determinista y exhaustiva) hasta
        encontrar uno válido. Al terminar, ``self.hash`` cumple la PoW.
        """
        if not isinstance(self.difficulty, int) or not (1 <= self.difficulty <= self.MAX_DIFFICULTY):
            raise ValueError(
                f"Dificultad inválida: {self.difficulty!r}. Debe ser un entero entre "
                f"1 y {self.MAX_DIFFICULTY}."
            )
        self.nonce = 0
        self.hash = self.compute_hash()
        while not self.hash_meets_difficulty(self.hash, self.difficulty):
            self.nonce += 1
            self.hash = self.compute_hash()
        return self.nonce + 1  # nº de hashes probados

    def is_valid_pow(self) -> bool:
        """El hash almacenado es correcto Y cumple la dificultad declarada."""
        return (
            self.hash == self.compute_hash()
            and self.hash_meets_difficulty(self.hash, self.difficulty)
        )

    # ------------------------------------------------------------------ #
    # Serialización
    # ------------------------------------------------------------------ #
    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "timestamp": self.timestamp,
            "transactions": [tx.to_dict() for tx in self.transactions],
            "prev_hash": self.prev_hash,
            "difficulty": self.difficulty,
            "nonce": self.nonce,
            "hash": self.hash,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Block":
        return cls(
            index=data["index"],
            transactions=[Transaction.from_dict(t) for t in data["transactions"]],
            prev_hash=data["prev_hash"],
            difficulty=data["difficulty"],
            timestamp=data["timestamp"],
            nonce=data["nonce"],
            block_hash=data["hash"],
        )

    def __repr__(self) -> str:  # pragma: no cover - sólo depuración
        return (
            f"<Block #{self.index} hash={self.hash[:12]}… "
            f"txs={len(self.transactions)} nonce={self.nonce}>"
        )
