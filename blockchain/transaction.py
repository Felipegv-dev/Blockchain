"""Módulo 2 — Transacciones y modelo UTXO.

Una transacción está formada por:

* **entradas** (*inputs*): cada una referencia un UTXO existente
  (``txid`` + ``index``) y lleva la **clave pública** del que gasta y su
  **firma**.
* **salidas** (*outputs*): cada una indica una ``cantidad`` y la
  ``direccion`` del receptor.
* **fee** (comisión opcional): se la queda el minero que incluya la
  transacción en un bloque.
* **txid**: hash SHA-256 de todo el contenido (identificador único).

Modelo **UTXO** (*Unspent Transaction Output*): el "saldo" de un usuario es la
suma de las salidas que tiene a su favor y que todavía nadie ha gastado. Para
gastar, una transacción consume UTXOs completos como entradas y crea UTXOs
nuevos como salidas (incluyendo, si sobra, una salida de *cambio* a sí mismo).

Cada entrada firma un *payload* canónico que compromete las entradas (qué
UTXOs se gastan), las salidas (a quién y cuánto) y la comisión. Así, si alguien
altera cualquiera de esos campos, la firma deja de ser válida.
"""

from __future__ import annotations

import hashlib
import json
from typing import Optional

# Precisión de las cantidades. Trabajamos con float pero redondeamos para
# evitar errores de coma flotante al comprobar la conservación del valor.
AMOUNT_DECIMALS = 8


def round_amount(value: float) -> float:
    """Redondea una cantidad a la precisión del sistema."""
    return round(float(value), AMOUNT_DECIMALS)


def canonical_json(obj) -> bytes:
    """Serialización JSON determinista (claves ordenadas, sin espacios).

    Se usa tanto para firmar como para hashear: dos estructuras iguales
    producen siempre exactamente los mismos bytes.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def utxo_key(txid: str, index: int) -> str:
    """Llave de un UTXO en el conjunto: ``"<txid>:<index>"``."""
    return f"{txid}:{index}"


class TxInput:
    """Entrada de una transacción: referencia a un UTXO + prueba de propiedad."""

    def __init__(
        self,
        txid: str,
        index: int,
        public_key: str = "",
        signature: str = "",
    ) -> None:
        self.txid = txid          # txid de la transacción que creó el UTXO
        self.index = index        # índice de la salida dentro de esa transacción
        self.public_key = public_key  # clave pública del que gasta (hex)
        self.signature = signature    # firma sobre el payload de la transacción

    @property
    def utxo_key(self) -> str:
        return utxo_key(self.txid, self.index)

    def reference_dict(self) -> dict:
        """Sólo la referencia al UTXO (lo que entra en el payload firmado)."""
        return {"txid": self.txid, "index": self.index}

    def to_dict(self) -> dict:
        return {
            "txid": self.txid,
            "index": self.index,
            "public_key": self.public_key,
            "signature": self.signature,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TxInput":
        return cls(
            txid=data["txid"],
            index=data["index"],
            public_key=data.get("public_key", ""),
            signature=data.get("signature", ""),
        )


class TxOutput:
    """Salida de una transacción: una cantidad para una dirección."""

    def __init__(self, amount: float, address: str) -> None:
        self.amount = round_amount(amount)
        self.address = address

    def to_dict(self) -> dict:
        return {"amount": self.amount, "address": self.address}

    @classmethod
    def from_dict(cls, data: dict) -> "TxOutput":
        return cls(amount=data["amount"], address=data["address"])


class Transaction:
    """Una transacción del modelo UTXO."""

    def __init__(
        self,
        inputs: list[TxInput],
        outputs: list[TxOutput],
        fee: float = 0.0,
        coinbase_data: Optional[str] = None,
    ) -> None:
        self.inputs = inputs
        self.outputs = outputs
        self.fee = round_amount(fee)
        # Marca que distingue las coinbase (no tienen entradas reales) y hace
        # único su txid aunque dos premios sean idénticos (p. ej. "block-1").
        self.coinbase_data = coinbase_data
        self.txid = self.compute_txid()

    # ------------------------------------------------------------------ #
    # Identidad y firma
    # ------------------------------------------------------------------ #
    @property
    def is_coinbase(self) -> bool:
        """Una coinbase no gasta UTXOs: crea monedas (premine o recompensa).

        Exige explícitamente **cero entradas**: una transacción que se declare
        coinbase (``coinbase_data`` puesto) pero traiga entradas NO se considera
        coinbase, de modo que la validación de la cadena la rechaza en vez de
        dejar que "queme" UTXOs ajenos sin firma.
        """
        return self.coinbase_data is not None and len(self.inputs) == 0

    def signing_payload(self) -> bytes:
        """Bytes que firma cada entrada.

        Compromete las *referencias* a los UTXOs gastados, las salidas y la
        comisión, pero NO las firmas/claves (evita circularidad). Cualquier
        manipulación de a quién/cuánto se paga invalida la firma.
        """
        payload = {
            "inputs": [i.reference_dict() for i in self.inputs],
            "outputs": [o.to_dict() for o in self.outputs],
            "fee": self.fee,
            "coinbase_data": self.coinbase_data,
        }
        return canonical_json(payload)

    def compute_txid(self) -> str:
        """txid = SHA-256 de TODO el contenido (incluidas firmas y claves)."""
        payload = {
            "inputs": [i.to_dict() for i in self.inputs],
            "outputs": [o.to_dict() for o in self.outputs],
            "fee": self.fee,
            "coinbase_data": self.coinbase_data,
        }
        return hashlib.sha256(canonical_json(payload)).hexdigest()

    def refresh_txid(self) -> str:
        """Recalcula y fija el txid (tras firmar las entradas)."""
        self.txid = self.compute_txid()
        return self.txid

    # ------------------------------------------------------------------ #
    # Totales
    # ------------------------------------------------------------------ #
    def total_output(self) -> float:
        return round_amount(sum(o.amount for o in self.outputs))

    # ------------------------------------------------------------------ #
    # Serialización
    # ------------------------------------------------------------------ #
    def to_dict(self) -> dict:
        return {
            "txid": self.txid,
            "inputs": [i.to_dict() for i in self.inputs],
            "outputs": [o.to_dict() for o in self.outputs],
            "fee": self.fee,
            "coinbase_data": self.coinbase_data,
            "is_coinbase": self.is_coinbase,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Transaction":
        tx = cls(
            inputs=[TxInput.from_dict(i) for i in data["inputs"]],
            outputs=[TxOutput.from_dict(o) for o in data["outputs"]],
            fee=data.get("fee", 0.0),
            coinbase_data=data.get("coinbase_data"),
        )
        # El txid almacenado debe coincidir con el recalculado; si no, los
        # datos fueron alterados. Lo conservamos para que la validación de la
        # cadena pueda detectar la manipulación.
        if "txid" in data:
            tx.txid = data["txid"]
        return tx

    def __repr__(self) -> str:  # pragma: no cover - sólo depuración
        kind = "coinbase" if self.is_coinbase else "tx"
        return f"<{kind} {self.txid[:10]}… outs={len(self.outputs)} fee={self.fee}>"


# ---------------------------------------------------------------------- #
# Constructores de alto nivel
# ---------------------------------------------------------------------- #
def build_coinbase(reward: float, address: str, tag: str) -> Transaction:
    """Crea una transacción coinbase que entrega ``reward`` a ``address``.

    ``tag`` (p. ej. ``"genesis"`` o ``"block-3"``) hace único el txid.
    """
    return Transaction(
        inputs=[],
        outputs=[TxOutput(reward, address)],
        fee=0.0,
        coinbase_data=tag,
    )
