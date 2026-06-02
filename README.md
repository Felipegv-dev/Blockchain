# 🐶 DoggyCoin — Proyecto Integrador

**DoggyCoin** es una mini-criptomoneda educativa que integra los conceptos del
proyecto: **wallets con ECDSA (secp256k1)**, **modelo UTXO**, **firmas
digitales**, **bloques encadenados**, **bloque génesis con premine**, **minería
con Prueba de Trabajo (PoW)** y una **interfaz interactiva en Streamlit**.

**Autores:** Felipe Garcia · Rodrigo Lira · Diego Lara

## Módulos

| Módulo | Archivo | Contenido |
|--------|---------|-----------|
| 1. Wallets y Claves | `blockchain/wallet.py` | Par de llaves ECDSA secp256k1. Dirección = `SHA-256(clave pública)`. Firma y verificación. |
| 2. Transacciones y UTXO | `blockchain/transaction.py` | Entradas, salidas, fee, `txid`. Firma del payload canónico. Modelo UTXO. |
| 3. Bloques y Blockchain | `blockchain/block.py` | Cabecera, hash, nonce, `prev_hash`. PoW y verificación. |
| 4. Génesis y Minería | `blockchain/blockchain.py` | Génesis (premine 1000), recompensa 3 + comisiones, UTXO set, mempool, validación de la cadena, persistencia. |
| 5. Simulación | `app.py` | Interfaz Streamlit (Inicio, Usuarios, Transacciones, Minería, Blockchain, Balances). |

## Instalación

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Uso

**Interfaz gráfica (Streamlit):**

```bash
streamlit run app.py
```

Se abre en el navegador (`http://localhost:8501`). Al iniciar se crea
automáticamente una *wallet fundadora* ("Génesis") con las **1000 monedas**
iniciales; desde ella puedes financiar al resto de usuarios. El estado vive en
la sesión del navegador (cada visitante tiene su propia cadena); en la barra
lateral puedes **descargar** el estado a un archivo JSON y **subirlo** después
para restaurarlo. Así funciona igual en local y en la nube.

**Demostración por consola (sin interfaz):**

```bash
python demo.py
```

Recorre todos los módulos y comprueba con asserts: generación de ≥2 usuarios
(mostrando clave privada/pública/dirección), firma y verificación, modelo UTXO
con cambio, recompensa `3 + comisiones`, conservación del supply
(`1000 + 3 × bloques`) y la **inmutabilidad** (alterar un bloque invalida la cadena).

**Pruebas de seguridad/robustez:**

```bash
python tests_seguridad.py
```

Reproduce ataques/defectos y verifica que se rechazan: coinbase con entradas o
con la recompensa dividida/redirigida, salidas negativas, dificultad por debajo
del mínimo, dificultad imposible, firmas maleables (high-S), inflación/quema por
redondeo y carga de un estado manipulado.

## Diseño en breve

- **Dirección** = `SHA-256` de la clave pública (identificador único del usuario).
- Cada **entrada** referencia un UTXO (`txid:index`) y lleva la clave pública y la
  firma del propietario. Verificación: `SHA-256(pubkey) == dirección del UTXO` **y**
  firma válida sobre el *payload* (entradas + salidas + fee).
- **Conservación del valor:** en una transacción normal, `Σ entradas = Σ salidas + fee`.
  El fee se lo lleva el minero; no se crea dinero salvo en la coinbase.
- **Bloque génesis:** una única coinbase de 1000 monedas, `prev_hash = "0"`.
- **PoW:** se busca un `nonce` tal que el hash del bloque empiece con `dificultad`
  ceros. La dificultad forma parte del hash, así que no puede rebajarse sin
  romper la cadena.
- **Inmutabilidad:** el hash de cada bloque depende de las transacciones (vía sus
  `txid`) y del `prev_hash`; cualquier cambio invalida ese bloque y los siguientes.

## Despliegue en Streamlit Community Cloud

1. Sube este proyecto a un repositorio de GitHub (debe contener `app.py`,
   la carpeta `blockchain/` y `requirements.txt` en la raíz).
2. Entra en [share.streamlit.io](https://share.streamlit.io) y conéctate con GitHub.
3. **New app** → elige el repositorio y la rama, *Main file path* = `app.py`.
4. (Opcional) En *Advanced settings* fija la versión de Python (3.11–3.13).
5. **Deploy**. La primera vez instala las dependencias de `requirements.txt`.

No hace falta `packages.txt`: el grafo de la cadena se dibuja con
`st.graphviz_chart` (lado cliente), sin el binario de Graphviz. El estado es por
sesión (no se comparte entre visitantes); usa los botones de descargar/subir JSON
de la barra lateral para conservar tu cadena entre visitas.

## Endurecimiento de seguridad aplicado

`is_valid_chain` valida la cadena de forma estricta para sostener la promesa de
inmutabilidad: la coinbase no puede tener entradas (no "quema" UTXOs ajenos),
debe tener exactamente una salida positiva y pagar el monto exacto; se exige un
piso de dificultad de consenso; las firmas son canónicas **low-S** (no maleables)
y la verificación rechaza las high-S; las cantidades se conservan con tolerancia
menor que la precisión (no hay inflación ni quema por redondeo); y `Blockchain.load`
**valida** el estado al cargarlo, rechazando ficheros manipulados en vez de mostrar
balances falsos.

> ⚠️ **Limitación inherente (proyecto educativo):** la dificultad de PoW es baja
> para que la demo sea rápida, así que *re-minar* bloques es barato. Como en
> cualquier PoW, la inmutabilidad real depende de que rehacer el trabajo sea
> costoso; con dificultad alta el coste crece exponencialmente. Además, las claves
> privadas se guardan en claro en el estado para poder firmar en la simulación.
> No usar en producción.
