"""Proyecto Integrador - Mini blockchain educativa.

Paquete con los módulos del proyecto:

1. wallet      -> Wallets y Claves (ECDSA secp256k1, dirección = SHA-256(pubkey)).
2. transaction -> Transacciones y modelo UTXO (entradas, salidas, firma, fee).
3. block       -> Estructura de bloque y Prueba de Trabajo (PoW).
4. blockchain  -> Génesis, minería, conjunto de UTXOs, validación y persistencia.

La interfaz de usuario (Módulo 5) vive en ``app.py`` (Streamlit), en la raíz.
"""

from .wallet import Wallet
from .transaction import Transaction, TxInput, TxOutput
from .block import Block
from .blockchain import Blockchain

__all__ = [
    "Wallet",
    "Transaction",
    "TxInput",
    "TxOutput",
    "Block",
    "Blockchain",
]
