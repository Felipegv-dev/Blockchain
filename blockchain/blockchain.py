"""Módulo 4 — Génesis, Minería, UTXO set y Blockchain.

Esta clase es el corazón del sistema. Mantiene:

* ``chain``   : la lista de bloques (``chain[0]`` es el génesis).
* ``utxos``   : el conjunto de salidas no gastadas, ``{"<txid>:<idx>": {...}}``.
* ``mempool`` : transacciones válidas pendientes de incluir en un bloque.
* ``wallets`` : las carteras conocidas (para la simulación y la persistencia).

Reglas económicas del proyecto:

* El **bloque génesis** crea 1000 monedas (premine) mediante una coinbase y se
  las entrega a una *wallet fundadora*. Es el único dinero "creado de la nada".
* Cada **bloque nuevo** paga al minero ``3`` monedas de recompensa **más** la
  suma de las comisiones (*fees*) de las transacciones incluidas.
* Las comisiones no crean dinero: salen de las entradas de cada transacción
  (``Σ entradas = Σ salidas + fee``); el fee sólo cambia de manos hacia el minero.
"""

from __future__ import annotations

import json
import time
from typing import Optional

from .block import Block
from .transaction import (
    Transaction,
    TxInput,
    TxOutput,
    build_coinbase,
    round_amount,
    utxo_key,
)
from .wallet import Wallet, address_from_public_key_hex, verify_signature

# --------------------------- Parámetros del proyecto --------------------------- #
COIN_NAME = "DoggyCoin"   # nombre de la moneda
GENESIS_SUPPLY = 1000.0   # monedas iniciales (premine) del bloque génesis
BLOCK_REWARD = 3.0        # recompensa fija por bloque minado
DEFAULT_DIFFICULTY = 3    # ceros iniciales exigidos por la PoW
MIN_DIFFICULTY = 1        # piso de dificultad de consenso (ningún bloque por debajo)
# Tolerancia al comparar cantidades. Debe ser MENOR que la precisión del
# sistema (1e-8 = AMOUNT_DECIMALS) para que solo absorba ruido de coma flotante
# y no permita desbalances representables (inflación/quema encubierta).
AMOUNT_TOLERANCE = 1e-9


class Blockchain:
    """Una blockchain UTXO con PoW, mempool y persistencia."""

    def __init__(self, difficulty: int = DEFAULT_DIFFICULTY) -> None:
        self.chain: list[Block] = []
        self.utxos: dict[str, dict] = {}
        self.mempool: list[Transaction] = []
        self.wallets: dict[str, Wallet] = {}   # address -> Wallet
        self.difficulty: int = difficulty
        self.founder_address: Optional[str] = None

    # ================================================================== #
    # Creación / Génesis
    # ================================================================== #
    @classmethod
    def create(cls, difficulty: int = DEFAULT_DIFFICULTY) -> "Blockchain":
        """Crea una blockchain nueva con su wallet fundadora y bloque génesis."""
        bc = cls(difficulty=difficulty)
        founder = Wallet.generate(name="Génesis")
        bc.register_wallet(founder)
        bc.founder_address = founder.address
        bc._create_genesis_block(founder.address)
        return bc

    def _create_genesis_block(self, founder_address: str) -> Block:
        """Construye, mina y aplica el bloque génesis (premine de 1000 monedas)."""
        coinbase = build_coinbase(GENESIS_SUPPLY, founder_address, tag="genesis")
        genesis = Block(
            index=0,
            transactions=[coinbase],
            prev_hash="0",
            difficulty=self.difficulty,
        )
        genesis.mine()
        self.chain.append(genesis)
        self._apply_block_to_utxos(genesis)
        return genesis

    # ================================================================== #
    # Wallets
    # ================================================================== #
    def register_wallet(self, wallet: Wallet) -> None:
        self.wallets[wallet.address] = wallet

    def create_wallet(self, name: str = "") -> Wallet:
        wallet = Wallet.generate(name=name)
        self.register_wallet(wallet)
        return wallet

    def name_for(self, address: str) -> str:
        """Nombre legible de una dirección (o la dirección corta si no hay)."""
        wallet = self.wallets.get(address)
        if wallet and wallet.name:
            return wallet.name
        return f"{address[:10]}…"

    # ================================================================== #
    # UTXO helpers
    # ================================================================== #
    def _mempool_view(self) -> dict[str, dict]:
        """UTXO set *proyectado* tras aplicar todas las transacciones pendientes.

        Parte del UTXO set confirmado y, en orden, gasta las entradas y añade
        las salidas de cada transacción del mempool. Así una transacción puede
        gastar el *cambio* aún no confirmado de otra (como en Bitcoin) y se
        impide el doble gasto entre transacciones pendientes.
        """
        view = dict(self.utxos)
        for tx in self.mempool:
            self._apply_tx_to_view(tx, view)
        return view

    def _spendable_utxos(self, address: str, view: dict[str, dict]) -> list[tuple[str, dict]]:
        """UTXOs de ``address`` disponibles dentro de ``view``."""
        return [(key, u) for key, u in view.items() if u["address"] == address]

    def get_balance(self, address: str) -> float:
        """Saldo confirmado: suma de los UTXOs a favor de ``address``."""
        return round_amount(
            sum(u["amount"] for u in self.utxos.values() if u["address"] == address)
        )

    def all_balances(self) -> dict[str, float]:
        """Saldo de todas las direcciones conocidas (incluye las del UTXO set)."""
        addresses = set(self.wallets.keys()) | {u["address"] for u in self.utxos.values()}
        return {addr: self.get_balance(addr) for addr in addresses}

    def total_supply(self) -> float:
        """Total de monedas en circulación (suma de todos los UTXOs)."""
        return round_amount(sum(u["amount"] for u in self.utxos.values()))

    # ================================================================== #
    # Construcción y validación de transacciones
    # ================================================================== #
    def create_transaction(
        self,
        sender: Wallet,
        recipient_address: str,
        amount: float,
        fee: float = 0.0,
    ) -> Transaction:
        """Construye, firma y devuelve una transacción del ``sender`` al receptor.

        Selecciona UTXOs del remitente hasta cubrir ``amount + fee``, crea la
        salida al receptor y, si sobra, una salida de **cambio** al remitente.
        No la añade al mempool (eso lo hace :meth:`add_transaction`).
        """
        amount = round_amount(amount)
        fee = round_amount(fee)
        if amount <= 0:
            raise ValueError("La cantidad a enviar debe ser positiva.")
        if fee < 0:
            raise ValueError("La comisión no puede ser negativa.")
        if recipient_address == sender.address:
            raise ValueError("No puedes enviarte dinero a ti mismo; elige otro destinatario.")

        need = round_amount(amount + fee)
        available = self._spendable_utxos(sender.address, self._mempool_view())

        # Selección "greedy": acumula UTXOs hasta cubrir lo necesario.
        selected: list[tuple[str, dict]] = []
        gathered = 0.0
        for key, u in available:
            selected.append((key, u))
            gathered = round_amount(gathered + u["amount"])
            if gathered >= need - AMOUNT_TOLERANCE:
                break

        if gathered < need - AMOUNT_TOLERANCE:
            raise ValueError(
                f"Fondos insuficientes: disponibles {gathered}, se necesitan {need} "
                f"(envío {amount} + comisión {fee})."
            )

        inputs: list[TxInput] = []
        for key, _u in selected:
            ref_txid, ref_index = key.rsplit(":", 1)
            inputs.append(
                TxInput(
                    txid=ref_txid,
                    index=int(ref_index),
                    public_key=sender.public_key_hex,
                )
            )

        outputs = [TxOutput(amount, recipient_address)]
        change = round_amount(gathered - need)
        # ``change`` ya está redondeado a la precisión del sistema (1e-8): si es
        # positivo, es >= 1e-8 y debe devolverse como salida de cambio. Así nunca
        # se "quema" un remanente y se conserva el valor (Σentradas = Σsalidas + fee).
        if change > 0:
            outputs.append(TxOutput(change, sender.address))

        tx = Transaction(inputs=inputs, outputs=outputs, fee=fee)

        # Cada entrada (todas del remitente) firma el mismo payload canónico.
        payload = tx.signing_payload()
        signature = sender.sign(payload)
        for tin in tx.inputs:
            tin.signature = signature
        tx.refresh_txid()
        return tx

    def validate_transaction(
        self,
        tx: Transaction,
        utxo_view: Optional[dict[str, dict]] = None,
    ) -> tuple[bool, str]:
        """Valida una transacción (NO coinbase) contra un conjunto de UTXOs.

        Comprueba: integridad del txid, existencia de los UTXOs, propiedad
        (la pubkey hashea a la dirección del UTXO), firma válida, ausencia de
        entradas duplicadas, salidas positivas y conservación del valor.
        Devuelve ``(es_valida, motivo)``.
        """
        view = self.utxos if utxo_view is None else utxo_view

        # Una transacción normal NUNCA puede declarar coinbase_data: si lo hace,
        # sería una coinbase encubierta y no debe procesarse por esta vía (evita
        # que una tx con entradas + coinbase_data eluda el gasto de sus entradas).
        if tx.coinbase_data is not None:
            return False, "Una transacción normal no puede declarar coinbase_data (sería una coinbase)."
        if not tx.inputs:
            return False, "La transacción no tiene entradas."
        if not tx.outputs:
            return False, "La transacción no tiene salidas."

        # Integridad: el txid debe coincidir con el contenido.
        if tx.txid != tx.compute_txid():
            return False, "El txid no coincide con el contenido (transacción alterada)."

        # Entradas duplicadas dentro de la misma transacción.
        seen: set[str] = set()
        for tin in tx.inputs:
            if tin.utxo_key in seen:
                return False, f"Entrada duplicada: {tin.utxo_key}."
            seen.add(tin.utxo_key)

        payload = tx.signing_payload()
        total_in = 0.0
        for tin in tx.inputs:
            utxo = view.get(tin.utxo_key)
            if utxo is None:
                return False, f"El UTXO {tin.utxo_key} no existe o ya fue gastado."
            # Propiedad: la clave pública debe corresponder a la dirección del UTXO.
            if address_from_public_key_hex(tin.public_key) != utxo["address"]:
                return False, "La clave pública no corresponde a la dirección del UTXO."
            # Firma sobre el payload de la transacción.
            if not verify_signature(tin.public_key, tin.signature, payload):
                return False, f"Firma inválida en la entrada {tin.utxo_key}."
            total_in = round_amount(total_in + utxo["amount"])

        for o in tx.outputs:
            if o.amount <= 0:
                return False, "Todas las salidas deben tener cantidad positiva."

        if tx.fee < 0:
            return False, "La comisión no puede ser negativa."

        # Conservación del valor: entradas = salidas + comisión.
        expected = round_amount(tx.total_output() + tx.fee)
        if abs(total_in - expected) > AMOUNT_TOLERANCE:
            return False, (
                f"El valor no se conserva: entradas {total_in} ≠ "
                f"salidas {tx.total_output()} + fee {tx.fee}."
            )

        return True, ""

    def add_transaction(self, tx: Transaction) -> tuple[bool, str]:
        """Valida una transacción contra el estado + mempool y, si es válida,
        la añade al mempool. Evita el doble gasto entre transacciones pendientes.
        """
        # Vista = UTXO set proyectado tras las transacciones ya pendientes.
        view = self._mempool_view()
        ok, reason = self.validate_transaction(tx, view)
        if not ok:
            return False, reason
        self.mempool.append(tx)
        return True, ""

    # ================================================================== #
    # Minería
    # ================================================================== #
    def mine_block(
        self,
        miner_address: str,
        difficulty: Optional[int] = None,
    ) -> dict:
        """Mina un bloque con las transacciones del mempool y paga al minero.

        Recompensa = ``BLOCK_REWARD`` + suma de comisiones de las transacciones
        incluidas. Devuelve estadísticas del minado (tiempo, nonce, etc.).
        """
        diff = self.difficulty if difficulty is None else difficulty
        # No mutamos self.difficulty todavía: si ``diff`` es inválida, block.mine()
        # lanzará ValueError y el objeto debe quedar intacto (operación atómica).

        # Validación secuencial del mempool sobre una vista temporal: así se
        # respetan las dependencias y se descarta cualquier conflicto.
        temp_view = dict(self.utxos)
        included: list[Transaction] = []
        total_fees = 0.0
        for tx in self.mempool:
            ok, _reason = self.validate_transaction(tx, temp_view)
            if not ok:
                continue  # se descarta (sus fondos ya no están disponibles)
            self._apply_tx_to_view(tx, temp_view)
            included.append(tx)
            total_fees = round_amount(total_fees + tx.fee)

        reward = round_amount(BLOCK_REWARD + total_fees)
        coinbase = build_coinbase(reward, miner_address, tag=f"block-{len(self.chain)}")
        transactions = [coinbase] + included

        block = Block(
            index=len(self.chain),
            transactions=transactions,
            prev_hash=self.chain[-1].hash,
            difficulty=diff,
        )

        start = time.time()
        hashes = block.mine()  # valida 1<=diff<=64 entero; lanza ValueError si no
        elapsed = time.time() - start

        # El minado tuvo éxito: ahora sí fijamos la dificultad del sistema.
        self.difficulty = diff

        # Confirmar el bloque: aplicar al UTXO set real y vaciar el mempool.
        self.chain.append(block)
        self._apply_block_to_utxos(block)
        self.mempool = []

        return {
            "index": block.index,
            "hash": block.hash,
            "nonce": block.nonce,
            "hashes_tried": hashes,
            "elapsed_seconds": elapsed,
            "difficulty": diff,
            "reward": reward,
            "base_reward": BLOCK_REWARD,
            "fees": total_fees,
            "n_transactions": len(included),
            "miner": miner_address,
        }

    # ================================================================== #
    # Aplicación de transacciones / bloques al UTXO set
    # ================================================================== #
    @staticmethod
    def _apply_tx_to_view(tx: Transaction, view: dict[str, dict]) -> None:
        """Aplica una transacción a una vista de UTXOs (gasta entradas, crea salidas).

        Solo una coinbase ESTRUCTURALMENTE válida (``is_coinbase``: con
        ``coinbase_data`` y SIN entradas) deja de gastar entradas. Cualquier otra
        transacción gasta sus entradas, de modo que una tx con entradas siempre
        las consume (no puede crear dinero) y una coinbase legítima no tiene
        entradas que gastar. El predicado es el MISMO que usa la validación.
        """
        if not tx.is_coinbase:
            for tin in tx.inputs:
                view.pop(tin.utxo_key, None)
        for idx, out in enumerate(tx.outputs):
            view[utxo_key(tx.txid, idx)] = {"address": out.address, "amount": out.amount}

    def _apply_block_to_utxos(self, block: Block) -> None:
        """Aplica todas las transacciones de un bloque al UTXO set real."""
        for tx in block.transactions:
            self._apply_tx_to_view(tx, self.utxos)

    # ================================================================== #
    # Validación de la cadena completa (inmutabilidad)
    # ================================================================== #
    @staticmethod
    def _validate_coinbase(coinbase: Transaction, expected_total: float, label: str) -> tuple[bool, str]:
        """Valida estructuralmente una coinbase (génesis o recompensa de bloque).

        Una coinbase debe: no tener entradas, tener exactamente una salida
        positiva, y pagar exactamente ``expected_total``. Así no puede quemar
        UTXOs ajenos (entradas), repartir/redirigir el premio en varias salidas
        ni crear cantidades negativas.
        """
        if not coinbase.is_coinbase:
            return False, f"{label} debe empezar con una coinbase (sin entradas)."
        if coinbase.inputs:
            return False, f"{label}: la coinbase no puede tener entradas."
        if len(coinbase.outputs) != 1:
            return False, f"{label}: la coinbase debe tener exactamente una salida."
        if coinbase.outputs[0].amount <= 0:
            return False, f"{label}: la salida de la coinbase debe ser positiva."
        if abs(coinbase.total_output() - expected_total) > AMOUNT_TOLERANCE:
            return False, (
                f"{label}: la coinbase paga {coinbase.total_output()} "
                f"pero debería pagar {expected_total}."
            )
        return True, ""

    def is_valid_chain(self) -> tuple[bool, str]:
        """Re-verifica toda la cadena desde cero y reconstruye el UTXO set.

        Comprueba el génesis, el encadenamiento de hashes, un piso de dificultad
        de consenso, la PoW de cada bloque, la validez de cada transacción y la
        corrección estructural de cada coinbase. Detecta cualquier manipulación
        (cadena inmutable).
        """
        if not self.chain:
            return False, "La cadena está vacía."

        # --- Génesis ---
        genesis = self.chain[0]
        if genesis.index != 0 or genesis.prev_hash != "0":
            return False, "El bloque génesis es inválido (index/prev_hash)."
        if not isinstance(genesis.difficulty, int) or genesis.difficulty < MIN_DIFFICULTY:
            return False, f"El génesis tiene una dificultad inválida (mínimo {MIN_DIFFICULTY}, entero)."
        if not genesis.is_valid_pow():
            return False, "El bloque génesis no cumple la PoW o su hash es incorrecto."
        if len(genesis.transactions) != 1:
            return False, "El génesis debe tener exactamente una transacción (coinbase)."
        ok, reason = self._validate_coinbase(genesis.transactions[0], GENESIS_SUPPLY, "El génesis")
        if not ok:
            return False, reason

        view: dict[str, dict] = {}
        self._apply_tx_to_view(genesis.transactions[0], view)

        # --- Bloques siguientes ---
        for i in range(1, len(self.chain)):
            block = self.chain[i]
            prev = self.chain[i - 1]

            if block.index != i:
                return False, f"El bloque {i} tiene un index incorrecto."
            if block.prev_hash != prev.hash:
                return False, f"El bloque {i} no enlaza con el hash del anterior."
            if not isinstance(block.difficulty, int) or block.difficulty < MIN_DIFFICULTY:
                return False, f"El bloque {i} tiene una dificultad inválida (mínimo {MIN_DIFFICULTY}, entero)."
            if not block.is_valid_pow():
                return False, f"El bloque {i} no cumple la PoW o su hash es incorrecto."
            if not block.transactions:
                return False, f"El bloque {i} no tiene transacciones."

            # Las transacciones normales deben ser válidas y se aplican en orden.
            total_fees = 0.0
            for tx in block.transactions[1:]:
                ok, reason = self.validate_transaction(tx, view)
                if not ok:
                    return False, f"Transacción inválida en el bloque {i}: {reason}"
                total_fees = round_amount(total_fees + tx.fee)
                self._apply_tx_to_view(tx, view)

            # La coinbase debe pagar exactamente recompensa + comisiones.
            coinbase = block.transactions[0]
            expected_reward = round_amount(BLOCK_REWARD + total_fees)
            ok, reason = self._validate_coinbase(coinbase, expected_reward, f"El bloque {i}")
            if not ok:
                return False, reason
            self._apply_tx_to_view(coinbase, view)

        return True, "La cadena es válida e íntegra."

    # ================================================================== #
    # Persistencia (JSON)
    # ================================================================== #
    def to_dict(self) -> dict:
        return {
            "difficulty": self.difficulty,
            "founder_address": self.founder_address,
            "chain": [b.to_dict() for b in self.chain],
            "mempool": [tx.to_dict() for tx in self.mempool],
            "wallets": [w.to_dict() for w in self.wallets.values()],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Blockchain":
        bc = cls(difficulty=data.get("difficulty", DEFAULT_DIFFICULTY))
        bc.founder_address = data.get("founder_address")
        for w in data.get("wallets", []):
            bc.register_wallet(Wallet.from_dict(w))
        chain_data = data.get("chain", [])
        if not isinstance(chain_data, list) or not chain_data:
            raise ValueError("Estado inválido: falta la cadena de bloques o está vacía.")
        bc.chain = [Block.from_dict(b) for b in chain_data]
        bc.mempool = [Transaction.from_dict(t) for t in data.get("mempool", [])]
        # Reconstruir el UTXO set aplicando la cadena (estado derivado).
        bc.utxos = {}
        for block in bc.chain:
            bc._apply_block_to_utxos(block)
        return bc

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, path: str, *, verify: bool = True) -> "Blockchain":
        """Carga el estado desde disco.

        Si ``verify`` es True (por defecto), valida la cadena cargada con
        :meth:`is_valid_chain` y lanza ``ValueError`` si el estado fue
        manipulado o está corrupto, en lugar de exponer balances envenenados.
        """
        with open(path, "r", encoding="utf-8") as f:
            bc = cls.from_dict(json.load(f))
        if verify:
            ok, reason = bc.is_valid_chain()
            if not ok:
                raise ValueError(f"Estado cargado inválido: {reason}")
        return bc
