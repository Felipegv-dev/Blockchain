"""Pruebas de regresión: verifican las correcciones de seguridad/robustez.

Cada test reproduce un ataque/defecto detectado en la revisión y comprueba que
ahora se rechaza o se maneja correctamente.

    python tests_seguridad.py
"""

import os
import tempfile
import copy

from blockchain import Blockchain, Block
from blockchain.blockchain import BLOCK_REWARD, GENESIS_SUPPLY
from blockchain.transaction import Transaction, TxInput, TxOutput, build_coinbase
from blockchain.wallet import Wallet, verify_signature
from ecdsa import SECP256k1
from ecdsa.util import sigdecode_der


def base_chain():
    bc = Blockchain.create(difficulty=2)
    f = bc.wallets[bc.founder_address]
    a = bc.create_wallet("Alice")
    tx = bc.create_transaction(f, a.address, 100, 1.0)
    bc.add_transaction(tx)
    bc.mine_block(a.address)
    return bc, f, a


def test_coinbase_con_entradas_rechazada():
    """A: una coinbase con entradas (quemar UTXOs ajenos) invalida la cadena."""
    bc, f, a = base_chain()
    victim_key = next(iter(bc.utxos))  # un UTXO cualquiera
    coinbase = bc.chain[1].transactions[0]
    coinbase.inputs.append(TxInput(*victim_key.rsplit(":", 1)[0:1] + [int(victim_key.rsplit(":", 1)[1])]))
    coinbase.refresh_txid()
    bc.chain[1].mine()  # re-minar para que la PoW pase
    valid, msg = bc.is_valid_chain()
    assert not valid and "entradas" in msg, f"esperaba rechazo por entradas, got {valid} {msg}"
    print("OK A — coinbase con entradas rechazada:", msg)


def test_coinbase_dividida_rechazada():
    """A: dividir/redirigir la recompensa en varias salidas invalida la cadena."""
    bc, f, a = base_chain()
    cb = bc.chain[1].transactions[0]
    total = cb.total_output()
    cb.outputs = [TxOutput(total / 2, a.address), TxOutput(total / 2, f.address)]
    cb.refresh_txid()
    bc.chain[1].mine()
    valid, msg = bc.is_valid_chain()
    assert not valid and "una salida" in msg, f"got {valid} {msg}"
    print("OK A — coinbase con varias salidas rechazada:", msg)


def test_coinbase_negativa_rechazada():
    """A: salida de coinbase negativa invalida la cadena."""
    bc, f, a = base_chain()
    cb = bc.chain[1].transactions[0]
    total = cb.total_output()
    cb.outputs = [TxOutput(total + 1000, a.address)]  # una sola salida, pero...
    cb.fee = 0
    cb.refresh_txid()
    bc.chain[1].mine()
    valid, msg = bc.is_valid_chain()
    assert not valid, "debería invalidar (paga de más)"
    print("OK A — coinbase con monto incorrecto rechazada:", msg)


def test_tx_con_coinbase_data_rechazada():
    """A: una tx normal con entradas Y coinbase_data (inflación) debe rechazarse.

    Regresión: si _apply_tx_to_view no gastara las entradas de una tx con
    coinbase_data, el emisor conservaría su UTXO y crearía dinero de la nada.
    """
    bc = Blockchain.create(difficulty=2)
    f = bc.wallets[bc.founder_address]
    a = bc.create_wallet("Alice")
    # Construir a mano una tx normal pero con coinbase_data puesto.
    key = next(k for k, v in bc.utxos.items() if v["address"] == f.address)
    txid, idx = key.rsplit(":", 1)
    tin = TxInput(txid, int(idx), public_key=f.public_key_hex)
    tx = Transaction(
        inputs=[tin],
        outputs=[TxOutput(100, a.address), TxOutput(900, f.address)],  # balanceada
        fee=0,
        coinbase_data="evil",
    )
    tx.inputs[0].signature = f.sign(tx.signing_payload())
    tx.refresh_txid()
    # validate_transaction debe rechazarla
    ok, reason = bc.validate_transaction(tx, bc.utxos)
    assert not ok and "coinbase_data" in reason, f"got {ok} {reason}"
    # add_transaction también
    ok2, _ = bc.add_transaction(tx)
    assert not ok2, "el mempool no debería aceptarla"
    # Y si se colara en un bloque, is_valid_chain debe detectarla
    blk = Block(index=1, transactions=[build_coinbase(3, f.address, "block-1"), tx],
                prev_hash=bc.chain[-1].hash, difficulty=2)
    blk.mine()
    bc.chain.append(blk)
    valid, msg = bc.is_valid_chain()
    assert not valid and "coinbase_data" in msg, f"is_valid_chain debería rechazar: {valid} {msg}"
    print("OK A — tx con coinbase_data (inflación) rechazada:", reason)


def test_piso_dificultad():
    """B: bajar la dificultad a 0 y re-minar NO debe dar la cadena por válida."""
    bc, f, a = base_chain()
    blk = bc.chain[1]
    blk.difficulty = 0
    blk.nonce = 0
    blk.hash = blk.compute_hash()  # con dif 0 cualquier hash 'cumple'
    valid, msg = bc.is_valid_chain()
    assert not valid and "dificultad" in msg.lower(), f"got {valid} {msg}"
    print("OK B — piso de dificultad respetado:", msg)


def test_mine_dificultad_imposible():
    """B: minar con dificultad >= 65 lanza ValueError (no cuelga)."""
    bc = Blockchain.create(difficulty=2)
    blk = Block(index=1, transactions=[build_coinbase(3, bc.founder_address, "x")],
                prev_hash=bc.chain[-1].hash, difficulty=65)
    try:
        blk.mine()
        assert False, "debería lanzar ValueError"
    except ValueError as e:
        print("OK B — dificultad imposible rechazada:", e)


def test_malleabilidad_low_s():
    """C: una firma high-S (maleada) es rechazada por verify_signature."""
    w = Wallet.generate("X")
    msg = b"mensaje de prueba"
    sig_hex = w.sign(msg)
    assert verify_signature(w.public_key_hex, sig_hex, msg), "la firma canónica debe verificar"
    # Maleamos s -> n - s y re-codificamos en DER
    r, s = sigdecode_der(bytes.fromhex(sig_hex), SECP256k1.order)
    from ecdsa.util import sigencode_der
    mal = sigencode_der(r, SECP256k1.order - s, SECP256k1.order).hex()
    assert not verify_signature(w.public_key_hex, mal, msg), "la firma high-S debe rechazarse"
    print("OK C — firma maleada (high-S) rechazada")


def test_conservacion_fraccionaria():
    """D: montos fraccionarios no queman valor (supply exacto)."""
    bc = Blockchain.create(difficulty=2)
    f = bc.wallets[bc.founder_address]
    a = bc.create_wallet("Alice")
    tx = bc.create_transaction(f, a.address, 999.9999995, fee=0)  # antes quemaba ~5e-7
    bc.add_transaction(tx)
    bc.mine_block(a.address)
    expected = GENESIS_SUPPLY + BLOCK_REWARD  # 1 bloque minado
    assert abs(bc.total_supply() - expected) < 1e-9, f"supply {bc.total_supply()} != {expected}"
    assert bc.is_valid_chain()[0]
    print("OK D — conservación exacta con montos fraccionarios:", bc.total_supply())


def test_inflacion_rechazada():
    """D: una tx que infla ~1e-7 (dentro de la antigua tolerancia) ahora se rechaza."""
    bc = Blockchain.create(difficulty=2)
    f = bc.wallets[bc.founder_address]
    a = bc.create_wallet("Alice")
    # Construimos manualmente una tx que crea dinero: entrada 1000, salida 1000.0000001
    utxo_key = next(k for k, v in bc.utxos.items() if v["address"] == f.address)
    txid, idx = utxo_key.rsplit(":", 1)
    tin = TxInput(txid, int(idx), public_key=f.public_key_hex)
    tx = Transaction(inputs=[tin], outputs=[TxOutput(1000.0000001, a.address)], fee=0)
    tx.inputs[0].signature = f.sign(tx.signing_payload())
    tx.refresh_txid()
    ok, reason = bc.validate_transaction(tx, bc.utxos)
    assert not ok and "conserva" in reason, f"got {ok} {reason}"
    print("OK D — inflación de 1e-7 rechazada:", reason)


def test_load_valida_estado_manipulado():
    """E: load() rechaza un estado manipulado (balances envenenados)."""
    bc, f, a = base_chain()
    path = os.path.join(tempfile.mkdtemp(), "state.json")
    bc.save(path)
    # Manipular el JSON: inflar una salida conservando el txid
    import json
    with open(path) as fh:
        data = json.load(fh)
    data["chain"][0]["transactions"][0]["outputs"][0]["amount"] = 999999
    with open(path, "w") as fh:
        json.dump(data, fh)
    try:
        Blockchain.load(path)
        assert False, "load debería rechazar el estado manipulado"
    except ValueError as e:
        print("OK E — load rechaza estado manipulado:", e)


def test_roundtrip_valido():
    """E: un estado legítimo se guarda y carga correctamente (con validación)."""
    bc, f, a = base_chain()
    path = os.path.join(tempfile.mkdtemp(), "state.json")
    bc.save(path)
    bc2 = Blockchain.load(path)
    assert bc.utxos == bc2.utxos
    assert bc.all_balances() == bc2.all_balances()
    assert bc2.is_valid_chain()[0]
    print("OK E — round-trip legítimo válido")


if __name__ == "__main__":
    for fn in [
        test_coinbase_con_entradas_rechazada,
        test_coinbase_dividida_rechazada,
        test_coinbase_negativa_rechazada,
        test_tx_con_coinbase_data_rechazada,
        test_piso_dificultad,
        test_mine_dificultad_imposible,
        test_malleabilidad_low_s,
        test_conservacion_fraccionaria,
        test_inflacion_rechazada,
        test_load_valida_estado_manipulado,
        test_roundtrip_valido,
    ]:
        fn()
    print("\n✅ TODAS LAS PRUEBAS DE SEGURIDAD PASARON")
