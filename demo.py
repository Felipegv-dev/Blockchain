"""Demostración por consola de la mini-blockchain (sin interfaz gráfica).

Ejecuta de principio a fin todos los módulos del proyecto y comprueba que:

* se generan al menos dos usuarios distintos, mostrando clave privada,
  clave pública y dirección (SHA-256 de la pública);
* el bloque génesis premina 1000 monedas a la wallet fundadora;
* se firman, verifican y minan transacciones con el modelo UTXO y comisiones;
* la recompensa del minero es 3 + comisiones;
* la cadena es válida y, si se altera un bloque, deja de serlo (inmutabilidad).

Uso:
    python demo.py
"""

from blockchain import Blockchain
from blockchain.blockchain import BLOCK_REWARD, GENESIS_SUPPLY


def sep(title: str) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def main() -> None:
    # --- Módulo 4: génesis (dificultad baja para que el demo sea rápido) ---
    sep("1) Creación de la blockchain y bloque génesis (premine 1000)")
    bc = Blockchain.create(difficulty=3)
    founder = bc.wallets[bc.founder_address]
    print(f"Wallet fundadora: {founder.name}  dir={founder.address[:16]}…")
    print(f"Saldo fundadora : {bc.get_balance(founder.address)} (premine={GENESIS_SUPPLY})")
    print(f"Hash génesis    : {bc.chain[0].hash}")

    # --- Módulo 1: usuarios y claves ---
    sep("2) Módulo 1 — Wallets y Claves (al menos dos usuarios distintos)")
    alice = bc.create_wallet("Alice")
    bob = bc.create_wallet("Bob")
    for w in (alice, bob):
        print(f"\nUsuario: {w.name}")
        print(f"  Clave privada : {w.private_key_hex}")
        print(f"  Clave pública : {w.public_key_hex[:32]}… ({len(w.public_key_hex)//2} bytes)")
        print(f"  Dirección     : {w.address}")
    assert alice.address != bob.address, "Las direcciones deben ser distintas"

    # --- Módulo 2: transacciones + UTXO ---
    sep("3) Módulo 2 — Transacciones: la fundadora financia a Alice y Bob")
    # Se añade cada transacción antes de crear la siguiente: así la 2ª ya "ve"
    # el cambio pendiente de la 1ª (gasto de salidas no confirmadas, como Bitcoin).
    tx1 = bc.create_transaction(founder, alice.address, amount=100, fee=1.0)
    ok1, r1 = bc.add_transaction(tx1)
    tx2 = bc.create_transaction(founder, bob.address, amount=50, fee=0.5)
    ok2, r2 = bc.add_transaction(tx2)
    print(f"tx1 (founder→Alice 100, fee 1.0): aceptada={ok1} {r1}")
    print(f"tx2 (founder→Bob   50,  fee 0.5): aceptada={ok2} {r2}")
    print(f"Mempool: {len(bc.mempool)} transacciones pendientes")
    assert ok1 and ok2

    # --- Módulo 4: minería (recompensa = 3 + fees) ---
    sep("4) Módulo 4 — Minería del primer bloque (mina = Bob)")
    stats = bc.mine_block(bob.address)
    print(f"Bloque #{stats['index']} minado: hash={stats['hash'][:20]}…")
    print(f"  nonce={stats['nonce']}  hashes probados={stats['hashes_tried']}")
    print(f"  tiempo={stats['elapsed_seconds']:.3f}s  dificultad={stats['difficulty']}")
    print(f"  recompensa={stats['reward']} (base {stats['base_reward']} + fees {stats['fees']})")
    expected_reward = BLOCK_REWARD + 1.0 + 0.5
    assert abs(stats["reward"] - expected_reward) < 1e-9, "Recompensa incorrecta"

    sep("5) Saldos tras el primer bloque")
    for name, w in (("Génesis", founder), ("Alice", alice), ("Bob", bob)):
        print(f"  {name:8s}: {bc.get_balance(w.address)}")
    assert bc.get_balance(alice.address) == 100
    # Bob: 50 recibidos + recompensa (3 + 1.5)
    assert abs(bc.get_balance(bob.address) - (50 + expected_reward)) < 1e-9
    # Fundadora: 1000 - 100 - 1 - 50 - 0.5 (las fees salieron de sus entradas)
    assert abs(bc.get_balance(founder.address) - (1000 - 100 - 1 - 50 - 0.5)) < 1e-9

    # --- Transacción entre usuarios + segundo bloque ---
    sep("6) Alice envía 30 a Bob y se mina un segundo bloque (mina = Alice)")
    tx3 = bc.create_transaction(alice, bob.address, amount=30, fee=2.0)
    ok3, r3 = bc.add_transaction(tx3)
    print(f"tx3 (Alice→Bob 30, fee 2.0): aceptada={ok3} {r3}")
    stats2 = bc.mine_block(alice.address)
    print(f"Bloque #{stats2['index']} minado: recompensa={stats2['reward']} (fees={stats2['fees']})")
    print(f"  Saldo Alice: {bc.get_balance(alice.address)}  Saldo Bob: {bc.get_balance(bob.address)}")

    # --- Rechazo de doble gasto / fondos insuficientes ---
    sep("7) Comprobación de seguridad: rechazo de fondos insuficientes")
    try:
        bc.create_transaction(alice, bob.address, amount=10_000, fee=0)
        print("  ERROR: debería haber fallado")
    except ValueError as e:
        print(f"  OK, rechazada: {e}")

    # --- Conservación del valor total ---
    sep("8) Conservación: supply total = 1000 + 3 por cada bloque minado")
    n_mined = len(bc.chain) - 1  # bloques después del génesis
    expected_supply = GENESIS_SUPPLY + BLOCK_REWARD * n_mined
    print(f"  Supply total = {bc.total_supply()}  (esperado {expected_supply})")
    assert abs(bc.total_supply() - expected_supply) < 1e-9

    # --- Módulo 3: inmutabilidad ---
    sep("9) Módulo 3 — Validez e inmutabilidad de la cadena")
    valid, msg = bc.is_valid_chain()
    print(f"  ¿Cadena válida? {valid} — {msg}")
    assert valid

    # Manipular una salida del bloque 1 debe invalidar la cadena.
    print("  Manipulando una salida del bloque #1 …")
    bc.chain[1].transactions[0].outputs[0].amount = 999999
    bc.chain[1].transactions[0].refresh_txid()  # incluso recalculando el txid local
    valid_after, msg_after = bc.is_valid_chain()
    print(f"  ¿Cadena válida tras manipular? {valid_after} — {msg_after}")
    assert not valid_after, "La manipulación debería invalidar la cadena"

    sep("✅ DEMO COMPLETADA: todos los módulos funcionan y las verificaciones pasan")


if __name__ == "__main__":
    main()
