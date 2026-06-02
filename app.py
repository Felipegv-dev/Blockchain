"""Módulo 5 — Simulación con Streamlit.

Interfaz web para operar la mini-blockchain: crear wallets, enviar
transacciones, minar bloques (PoW) y visualizar balances y la cadena.

Ejecutar con:

    streamlit run app.py
"""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from blockchain import Blockchain
from blockchain.blockchain import BLOCK_REWARD, COIN_NAME, DEFAULT_DIFFICULTY, GENESIS_SUPPLY

AUTHORS = "Felipe Garcia · Rodrigo Lira · Diego Lara"

st.set_page_config(page_title=COIN_NAME, page_icon="🐶", layout="wide")


# --------------------------------------------------------------------------- #
# Estado de la sesión
#
# El estado vive en ``st.session_state`` (por sesión de navegador), de modo que
# cada visitante tiene su propia cadena. Esto funciona igual en local y en
# Streamlit Community Cloud (cuyo disco es efímero y compartido). Para no perder
# el trabajo, la barra lateral permite DESCARGAR el estado a un archivo JSON y
# volver a SUBIRLO más tarde.
# --------------------------------------------------------------------------- #
def get_chain() -> Blockchain:
    """Devuelve la blockchain de la sesión, creándola si aún no existe."""
    if "bc" not in st.session_state:
        st.session_state.bc = Blockchain.create(DEFAULT_DIFFICULTY)
    return st.session_state.bc


def wallet_options(bc: Blockchain) -> dict[str, str]:
    """Mapa etiqueta -> dirección, para los selectores de usuario."""
    options: dict[str, str] = {}
    for addr, w in bc.wallets.items():
        label = f"{w.name or 'Sin nombre'} · {addr[:10]}… · saldo {bc.get_balance(addr):g}"
        options[label] = addr
    return options


def short(text: str, n: int = 14) -> str:
    return f"{text[:n]}…" if len(text) > n else text


# --------------------------------------------------------------------------- #
# Barra lateral: navegación y persistencia
# --------------------------------------------------------------------------- #
bc = get_chain()

st.sidebar.title(f"🐶 {COIN_NAME}")
st.sidebar.caption("Proyecto Integrador · ECDSA · UTXO · PoW")
st.sidebar.caption(f"👥 Autores: {AUTHORS}")

section = st.sidebar.radio(
    "Navegación",
    ["🏠 Inicio", "👤 Usuarios", "💸 Transacciones", "⛏️ Minería", "🧱 Blockchain", "💰 Balances"],
)

st.sidebar.divider()
st.sidebar.subheader("Estado del sistema")

# Descargar el estado actual como JSON (para guardarlo y restaurarlo luego).
st.sidebar.download_button(
    "⬇️ Descargar estado (JSON)",
    data=json.dumps(bc.to_dict(), indent=2, ensure_ascii=False),
    file_name="blockchain_state.json",
    mime="application/json",
    width="stretch",
)

# Subir un estado previamente descargado. Se valida antes de aplicarlo y solo se
# procesa una vez por archivo (file_id) para no recargar en cada rerun.
uploaded = st.sidebar.file_uploader("⬆️ Cargar estado (.json)", type=["json"])
if uploaded is not None and st.session_state.get("last_upload_id") != uploaded.file_id:
    st.session_state.last_upload_id = uploaded.file_id
    try:
        data = json.load(uploaded)
        nuevo = Blockchain.from_dict(data)
        ok, reason = nuevo.is_valid_chain()
        if ok:
            st.session_state.bc = nuevo
            st.sidebar.success("Estado cargado correctamente.")
            st.rerun()
        else:
            st.sidebar.error(f"Estado inválido: {reason}")
    except Exception as exc:
        st.sidebar.error(f"No se pudo cargar el archivo: {exc}")

# Reiniciar es destructivo: confirmación en dos pasos con un flag de sesión propio
# (no un widget) que se limpia siempre, para que el botón no quede "armado".
if st.sidebar.button("🔄 Reiniciar (nueva cadena)", width="stretch"):
    st.session_state.confirm_reset = True
if st.session_state.get("confirm_reset"):
    st.sidebar.warning("Esto borra la cadena, las wallets y el mempool. ¿Continuar?")
    cc1, cc2 = st.sidebar.columns(2)
    if cc1.button("✅ Sí, borrar", width="stretch"):
        st.session_state.bc = Blockchain.create(bc.difficulty)
        st.session_state.confirm_reset = False
        st.rerun()
    if cc2.button("✖️ Cancelar", width="stretch"):
        st.session_state.confirm_reset = False
        st.rerun()

st.sidebar.caption("💡 El estado vive en tu sesión. Descárgalo para conservarlo entre visitas.")


# --------------------------------------------------------------------------- #
# Sección: Inicio
# --------------------------------------------------------------------------- #
def render_inicio(bc: Blockchain) -> None:
    st.title("🏠 Resumen del sistema")
    st.write(
        "Mini-criptomoneda educativa con **wallets ECDSA (secp256k1)**, "
        "**modelo UTXO**, **firmas digitales** y **Prueba de Trabajo (PoW)**."
    )

    n_blocks = len(bc.chain)
    n_tx = sum(len(b.transactions) for b in bc.chain)
    n_tx_normales = sum(len(b.transactions) - 1 for b in bc.chain)  # sin coinbase
    rewards = sum(
        b.transactions[0].total_output() for b in bc.chain[1:]
    )  # recompensas de minería (excluye premine del génesis)

    c1, c2, c3 = st.columns(3)
    c1.metric("Bloques", n_blocks)
    c2.metric("Transacciones (con coinbase)", n_tx)
    c3.metric("Transacciones normales", n_tx_normales)

    c4, c5, c6 = st.columns(3)
    c4.metric("Supply total", f"{bc.total_supply():g}")
    c5.metric("Premine (génesis)", f"{GENESIS_SUPPLY:g}")
    c6.metric("Recompensas minadas", f"{rewards:g}")

    c7, c8, c9 = st.columns(3)
    c7.metric("Usuarios (wallets)", len(bc.wallets))
    c8.metric("Pendientes (mempool)", len(bc.mempool))
    c9.metric("Dificultad PoW", bc.difficulty)

    valid, msg = bc.is_valid_chain()
    if valid:
        st.success(f"✅ {msg}")
    else:
        st.error(f"❌ Cadena inválida: {msg}")

    st.caption(
        f"Regla económica: el génesis crea 1000 {COIN_NAME} (premine). "
        f"Cada bloque nuevo crea 3 {COIN_NAME} de recompensa; las comisiones no crean "
        "dinero, sólo pasan del remitente al minero. "
        f"Supply esperado = 1000 + 3 × (bloques − 1) = "
        f"{GENESIS_SUPPLY + BLOCK_REWARD * (n_blocks - 1):g}."
    )


# --------------------------------------------------------------------------- #
# Sección: Usuarios
# --------------------------------------------------------------------------- #
def render_usuarios(bc: Blockchain) -> None:
    st.title("👤 Usuarios (wallets)")
    st.write("Cada usuario tiene un par de llaves ECDSA. La **dirección** es el SHA-256 de la clave pública.")

    with st.form("crear_wallet"):
        name = st.text_input("Nombre del nuevo usuario", placeholder="p. ej. Carla")
        submitted = st.form_submit_button("➕ Crear wallet")
        if submitted:
            w = bc.create_wallet(name.strip() or f"Usuario-{len(bc.wallets)}")
            st.success(f"Wallet creada: **{w.name}** — dirección `{w.address}`")

    st.subheader("Usuarios existentes")
    rows = [
        {
            "Nombre": w.name or "—",
            "Dirección": addr,
            "Saldo": bc.get_balance(addr),
            "Fundador": "⭐" if addr == bc.founder_address else "",
        }
        for addr, w in bc.wallets.items()
    ]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    st.subheader("Claves (detalle)")
    st.caption("⚠️ Es una simulación: en un sistema real la clave privada jamás se mostraría.")
    for addr, w in bc.wallets.items():
        with st.expander(f"{w.name or 'Sin nombre'} · {addr[:16]}…"):
            st.text("Clave privada (hex):")
            st.code(w.private_key_hex, language="text")
            st.text("Clave pública (hex):")
            st.code(w.public_key_hex, language="text")
            st.text("Dirección (SHA-256 de la clave pública):")
            st.code(w.address, language="text")


# --------------------------------------------------------------------------- #
# Sección: Transacciones
# --------------------------------------------------------------------------- #
def render_transacciones(bc: Blockchain) -> None:
    st.title("💸 Transacciones")
    options = wallet_options(bc)
    if len(options) < 2:
        st.warning("Crea al menos dos usuarios en la sección **Usuarios** para enviar transacciones.")
        return

    labels = list(options.keys())
    with st.form("crear_tx"):
        col1, col2 = st.columns(2)
        sender_label = col1.selectbox("Remitente", labels, index=0)
        recipient_label = col2.selectbox("Destinatario", labels, index=min(1, len(labels) - 1))
        col3, col4 = st.columns(2)
        amount = col3.number_input("Cantidad a enviar", min_value=0.0, value=10.0, step=1.0)
        fee = col4.number_input("Comisión (mining fee)", min_value=0.0, value=0.0, step=0.5)
        submitted = st.form_submit_button("📤 Crear y enviar al mempool")

    if submitted:
        sender_addr = options[sender_label]
        recipient_addr = options[recipient_label]
        sender_wallet = bc.wallets[sender_addr]
        try:
            tx = bc.create_transaction(sender_wallet, recipient_addr, amount, fee)
            ok, reason = bc.add_transaction(tx)
            if ok:
                st.success(f"Transacción aceptada en el mempool. txid `{tx.txid}`")
                st.caption(f"Firmada por {bc.name_for(sender_addr)} y verificada con su clave pública.")
            else:
                st.error(f"Transacción rechazada: {reason}")
        except ValueError as exc:
            st.error(str(exc))

    st.subheader("Mempool (transacciones pendientes)")
    if not bc.mempool:
        st.info("No hay transacciones pendientes. Ve a **Minería** para crear un bloque.")
    else:
        rows = []
        for tx in bc.mempool:
            destinos = ", ".join(
                f"{bc.name_for(o.address)}: {o.amount:g}" for o in tx.outputs
            )
            rows.append(
                {"txid": short(tx.txid, 16), "Salidas": destinos, "Fee": tx.fee, "Entradas": len(tx.inputs)}
            )
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        st.caption(f"Comisiones pendientes para el minero: {sum(tx.fee for tx in bc.mempool):g}")

    with st.expander("Ver conjunto de UTXOs actual"):
        utxo_rows = [
            {"UTXO (txid:idx)": short(k, 20), "Dueño": bc.name_for(v["address"]), "Cantidad": v["amount"]}
            for k, v in bc.utxos.items()
        ]
        st.dataframe(pd.DataFrame(utxo_rows), width="stretch", hide_index=True)


# --------------------------------------------------------------------------- #
# Sección: Minería
# --------------------------------------------------------------------------- #
def render_mineria(bc: Blockchain) -> None:
    st.title("⛏️ Minería (Prueba de Trabajo)")
    options = wallet_options(bc)
    if not options:
        st.warning("Crea al menos un usuario para poder minar.")
        return

    labels = list(options.keys())
    miner_label = st.selectbox("Minero (recibe la recompensa)", labels)
    difficulty = st.slider(
        "Dificultad (nº de ceros iniciales del hash)",
        min_value=1, max_value=6, value=bc.difficulty,
        help="Más ceros = más trabajo. 1–3 es rápido; 5–6 puede tardar.",
    )

    st.info(
        f"Recompensa al minar = **{BLOCK_REWARD:g}** + comisiones pendientes "
        f"(**{sum(tx.fee for tx in bc.mempool):g}**) "
        f"= **{BLOCK_REWARD + sum(tx.fee for tx in bc.mempool):g}** {COIN_NAME}. "
        f"Transacciones que se incluirán: {len(bc.mempool)}."
    )

    if st.button("⛏️ Minar bloque", type="primary"):
        miner_addr = options[miner_label]
        with st.spinner(f"Minando con dificultad {difficulty}…"):
            stats = bc.mine_block(miner_addr, difficulty=difficulty)
        st.success(f"¡Bloque #{stats['index']} minado por {bc.name_for(miner_addr)}!")
        c1, c2, c3 = st.columns(3)
        c1.metric("Tiempo de minado", f"{stats['elapsed_seconds']:.3f} s")
        c2.metric("Nonce encontrado", stats["nonce"])
        c3.metric("Hashes probados", f"{stats['hashes_tried']:,}")
        c4, c5, c6 = st.columns(3)
        c4.metric("Recompensa total", f"{stats['reward']:g}")
        c5.metric("Base", f"{stats['base_reward']:g}")
        c6.metric("Comisiones", f"{stats['fees']:g}")
        st.text("Hash del bloque:")
        st.code(stats["hash"], language="text")


# --------------------------------------------------------------------------- #
# Sección: Blockchain
# --------------------------------------------------------------------------- #
def build_dot(bc: Blockchain) -> str:
    """Genera el grafo DOT de la cadena (cada bloque enlaza con el anterior)."""
    lines = ["digraph blockchain {", "  rankdir=LR;", '  node [shape=box, style="rounded,filled", fillcolor="#e8f0fe", fontname="Helvetica"];']
    for b in bc.chain:
        label = (
            f"#{b.index}\\n{b.hash[:12]}…\\n"
            f"txs: {len(b.transactions)} | nonce: {b.nonce}"
        )
        fill = "#fff3cd" if b.index == 0 else "#e8f0fe"
        lines.append(f'  b{b.index} [label="{label}", fillcolor="{fill}"];')
    for i in range(1, len(bc.chain)):
        lines.append(f"  b{i - 1} -> b{i} [label=\"prev_hash\"];")
    lines.append("}")
    return "\n".join(lines)


def render_blockchain(bc: Blockchain) -> None:
    st.title("🧱 Cadena de bloques")

    valid, msg = bc.is_valid_chain()
    (st.success if valid else st.error)(("✅ " if valid else "❌ ") + msg)

    st.subheader("Grafo de la cadena")
    try:
        st.graphviz_chart(build_dot(bc), width="stretch")
    except Exception as exc:  # fallback si el render del grafo falla
        st.caption(f"(No se pudo dibujar el grafo: {exc})")

    st.subheader("Bloques (tabla)")
    rows = [
        {
            "Index": b.index,
            "Hash": short(b.hash, 18),
            "Prev hash": short(b.prev_hash, 18),
            "Nonce": b.nonce,
            "Dif.": b.difficulty,
            "Txs": len(b.transactions),
        }
        for b in bc.chain
    ]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    st.subheader("Detalle de cada bloque")
    for b in reversed(bc.chain):
        titulo = "🌱 Génesis" if b.index == 0 else f"Bloque #{b.index}"
        with st.expander(f"{titulo} — {b.hash[:16]}…"):
            st.write(f"**Index:** {b.index}  |  **Nonce:** {b.nonce}  |  **Dificultad:** {b.difficulty}")
            st.write(f"**Prev hash:** `{b.prev_hash}`")
            st.write(f"**Hash:** `{b.hash}`")
            for j, tx in enumerate(b.transactions):
                tipo = "coinbase" if tx.is_coinbase else "transacción"
                st.markdown(f"**{tipo} {j}** · txid `{tx.txid[:24]}…`  · fee {tx.fee:g}")
                outs = [
                    {"#": k, "Para": bc.name_for(o.address), "Dirección": short(o.address, 16), "Cantidad": o.amount}
                    for k, o in enumerate(tx.outputs)
                ]
                st.dataframe(pd.DataFrame(outs), width="stretch", hide_index=True)


# --------------------------------------------------------------------------- #
# Sección: Balances
# --------------------------------------------------------------------------- #
def render_balances(bc: Blockchain) -> None:
    st.title("💰 Balances")
    balances = bc.all_balances()
    rows = [
        {
            "Usuario": bc.name_for(addr),
            "Dirección": addr,
            "Saldo": saldo,
            "Fundador": "⭐" if addr == bc.founder_address else "",
        }
        for addr, saldo in sorted(balances.items(), key=lambda kv: -kv[1])
    ]
    df = pd.DataFrame(rows)
    st.dataframe(df, width="stretch", hide_index=True)

    st.subheader("Distribución de saldos")
    chart_df = pd.DataFrame(
        {"Saldo": [r["Saldo"] for r in rows]},
        index=[r["Usuario"] for r in rows],
    )
    st.bar_chart(chart_df)

    st.metric("Supply total en circulación", f"{bc.total_supply():g}")


# --------------------------------------------------------------------------- #
# Enrutado
# --------------------------------------------------------------------------- #
if section.endswith("Inicio"):
    render_inicio(bc)
elif section.endswith("Usuarios"):
    render_usuarios(bc)
elif section.endswith("Transacciones"):
    render_transacciones(bc)
elif section.endswith("Minería"):
    render_mineria(bc)
elif section.endswith("Blockchain"):
    render_blockchain(bc)
elif section.endswith("Balances"):
    render_balances(bc)
