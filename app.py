import streamlit as st
import sqlite3
from datetime import datetime, date
import pandas as pd
from calendar import monthrange
import os

# ====== hashing de contraseñas ======
from passlib.hash import bcrypt as bcrypt_hash

st.set_page_config(page_title="Gestión Ventas 2025 (Ventas + Compras)", layout="wide")

DB_PATH = "ventas.db"

# =========================
# DB Helpers & Migrations
# =========================
def get_conn():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.execute("PRAGMA foreign_keys = ON;")
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    return con

def column_exists(cur, table, column):
    cur.execute(f"PRAGMA table_info({table});")
    cols = [r[1] for r in cur.fetchall()]
    return column in cols

def init_db():
    with get_conn() as con:
        cur = con.cursor()

        # =========================
        # Tablas base
        # =========================
        # OPERATIONS (ventas)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS operations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo TEXT NOT NULL,          -- 'VENTA'
            descripcion TEXT,            -- celular vendido
            cliente TEXT,                -- nombre del cliente
            zona TEXT,                   -- vendedor
            nombre TEXT,                 -- inversor
            L REAL,                      -- costo (neto)
            N REAL,                      -- venta
            O INTEGER,                   -- cuotas
            estado TEXT,                 -- estado venta (CANCELADO/VIGENTE)
            y_pagado REAL DEFAULT 0,     -- suma cobrada (venta)
            comision REAL,               -- comisión vendedor (total)
            sale_date TEXT,              -- fecha de la venta (ISO)
            purchase_price REAL,         -- precio de compra (costo o costo*1.18 según inversor)
            created_at TEXT DEFAULT (datetime('now'))
        );
        """)

        # INSTALLMENTS (cuotas)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS installments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation_id INTEGER NOT NULL,
            idx INTEGER NOT NULL,
            amount REAL NOT NULL,
            paid INTEGER NOT NULL DEFAULT 0,
            paid_at TEXT,
            is_purchase INTEGER NOT NULL DEFAULT 0, -- 0: venta (cliente) | 1: compra (pago a inversor)
            FOREIGN KEY(operation_id) REFERENCES operations(id) ON DELETE CASCADE
        );
        """)

        # =========================
        # MIGRACIONES DEFENSIVAS (operations)
        # =========================
        cur.execute("PRAGMA table_info(operations);")
        op_cols = [r[1] for r in cur.fetchall()]
        if "comision" not in op_cols:
            cur.execute("ALTER TABLE operations ADD COLUMN comision REAL;")
        if "sale_date" not in op_cols:
            cur.execute("ALTER TABLE operations ADD COLUMN sale_date TEXT;")
        if "purchase_price" not in op_cols:
            cur.execute("ALTER TABLE operations ADD COLUMN purchase_price REAL;")
        if "cliente" not in op_cols:
            cur.execute("ALTER TABLE operations ADD COLUMN cliente TEXT;")
        if "created_at" not in op_cols:
            cur.execute("ALTER TABLE operations ADD COLUMN created_at TEXT DEFAULT (datetime('now'));")

        # =========================
        # USERS (login y roles)
        # =========================
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
            -- 'role' y 'vendedor' se agregan abajo si faltan
        );
        """)
        cur.execute("PRAGMA table_info(users);")
        user_cols = [r[1] for r in cur.fetchall()]
        if "role" not in user_cols:
            cur.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'admin';")
        if "vendedor" not in user_cols:
            cur.execute("ALTER TABLE users ADD COLUMN vendedor TEXT;")

        # Semilla: crear usuarios por defecto si la tabla está vacía
        cur.execute("SELECT COUNT(*) FROM users;")
        if (cur.fetchone() or [0])[0] == 0:
            try:
                cur.execute(
                    "INSERT INTO users (username, password_hash, role, vendedor) VALUES (?,?,?,?)",
                    ("admin", bcrypt_hash.hash("admin"), "admin", None)
                )
                cur.execute(
                    "INSERT INTO users (username, password_hash, role, vendedor) VALUES (?,?,?,?)",
                    ("vendedor", bcrypt_hash.hash("vendedor"), "seller", "Vendedor 1")
                )
            except Exception as e:
                print("Seed de usuarios omitido:", e)

        # =========================
        # VENDORS (maestro de vendedores)
        # =========================
        cur.execute("""
        CREATE TABLE IF NOT EXISTS vendors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL,
            activo INTEGER NOT NULL DEFAULT 1
        );
        """)

        # =========================
        # ÍNDICES
        # =========================
        cur.execute("CREATE INDEX IF NOT EXISTS idx_inst_op_purchase_paid ON installments(operation_id, is_purchase, paid);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ops_nombre ON operations(nombre);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ops_zona ON operations(zona);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ops_cliente ON operations(cliente);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ops_estado ON operations(estado);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ops_sale_date ON operations(sale_date);")

# =========================
# CRUD básicos
# =========================
def upsert_operation(op):
    with get_conn() as con:
        cur = con.cursor()
        if op.get("id"):
            q = """UPDATE operations
                   SET tipo=?, descripcion=?, cliente=?, zona=?, nombre=?, L=?, N=?, O=?, estado=?, y_pagado=?, comision=?, sale_date=?, purchase_price=?
                   WHERE id=?"""
            cur.execute(q, (op["tipo"], op.get("descripcion"), op.get("cliente"), op.get("zona"), op["nombre"],
                            op.get("L"), op.get("N"), op.get("O"), op.get("estado"), op.get("y_pagado"),
                            op.get("comision"), op.get("sale_date"), op.get("purchase_price"), op["id"]))
            return op["id"]
        else:
            q = """INSERT INTO operations (tipo, descripcion, cliente, zona, nombre, L, N, O, estado, y_pagado, comision, sale_date, purchase_price)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
            cur.execute(q, (op["tipo"], op.get("descripcion"), op.get("cliente"), op.get("zona"), op["nombre"],
                            op.get("L"), op.get("N"), op.get("O"), op.get("estado"), op.get("y_pagado"),
                            op.get("comision"), op.get("sale_date"), op.get("purchase_price")))
            return cur.lastrowid

def delete_operation(operation_id: int):
    with get_conn() as con:
        con.execute("DELETE FROM operations WHERE id=?", (operation_id,))

def list_operations(filters=None):
    filters = filters or {}
    where = []
    params = []
    if "estado" in filters and filters["estado"]:
        where.append("estado=?"); params.append(filters["estado"])
    # Exactos
    if "inversor" in filters and filters["inversor"]:
        where.append("UPPER(nombre)=UPPER(?)"); params.append(filters["inversor"])
    if "vendedor" in filters and filters["vendedor"]:
        where.append("UPPER(zona)=UPPER(?)"); params.append(filters["vendedor"])
    if "cliente" in filters and filters["cliente"]:
        where.append("UPPER(cliente)=UPPER(?)"); params.append(filters["cliente"])
    # Parciales
    if "inversor_like" in filters and filters["inversor_like"]:
        where.append("UPPER(nombre) LIKE UPPER(?)"); params.append(f"%{filters['inversor_like']}%")
    if "vendedor_like" in filters and filters["vendedor_like"]:
        where.append("UPPER(zona) LIKE UPPER(?)"); params.append(f"%{filters['vendedor_like']}%")
    if "cliente_like" in filters and filters["cliente_like"]:
        where.append("UPPER(cliente) LIKE UPPER(?)"); params.append(f"%{filters['cliente_like']}%")
    q = "SELECT * FROM operations"
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " ORDER BY id DESC"
    with get_conn() as con:
        cur = con.cursor()
        cur.execute(q, params)
        rows = cur.fetchall()
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in rows]

def get_operation(operation_id):
    with get_conn() as con:
        cur = con.cursor()
        cur.execute("SELECT * FROM operations WHERE id=?", (operation_id,))
        row = cur.fetchone()
        if not row: return None
        cols = [c[0] for c in cur.description]
        return dict(zip(cols, row))

def delete_installments(operation_id, is_purchase=None):
    with get_conn() as con:
        if is_purchase is None:
            con.execute("DELETE FROM installments WHERE operation_id=?", (operation_id,))
        else:
            con.execute("DELETE FROM installments WHERE operation_id=? AND is_purchase=?", (operation_id, 1 if is_purchase else 0))

def create_installments(operation_id, amounts, is_purchase=False):
    with get_conn() as con:
        for i, amt in enumerate(amounts, start=1):
            con.execute(
                "INSERT INTO installments (operation_id, idx, amount, paid, is_purchase) VALUES (?, ?, ?, 0, ?)",
                (operation_id, i, float(amt), 1 if is_purchase else 0)
            )

def list_installments(operation_id, is_purchase=None):
    with get_conn() as con:
        cur = con.cursor()
        if is_purchase is None:
            cur.execute("SELECT * FROM installments WHERE operation_id=? ORDER BY idx ASC", (operation_id,))
        else:
            cur.execute("SELECT * FROM installments WHERE operation_id=? AND is_purchase=? ORDER BY idx ASC",
                        (operation_id, 1 if is_purchase else 0))
        rows = cur.fetchall()
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in rows]

def set_installment_paid(installment_id, paid=True, paid_at_iso=None):
    with get_conn() as con:
        cur = con.cursor()
        cur.execute("UPDATE installments SET paid=?, paid_at=? WHERE id=?", 
                    (1 if paid else 0, paid_at_iso, installment_id))

def sum_paid(operation_id, is_purchase=False):
    with get_conn() as con:
        cur = con.cursor()
        cur.execute(
            "SELECT COALESCE(SUM(amount),0) FROM installments WHERE operation_id=? AND paid=1 AND is_purchase=?",
            (operation_id, 1 if is_purchase else 0)
        )
        return float(cur.fetchone()[0])

def count_paid_installments(operation_id, is_purchase=False):
    with get_conn() as con:
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM installments WHERE operation_id=? AND paid=1 AND is_purchase=?",
                    (operation_id, 1 if is_purchase else 0))
        return int(cur.fetchone()[0])

def recalc_status_for_operation(op_id):
    op = get_operation(op_id)
    if not op: return
    # Estado de VENTA (cobros del cliente)
    y_venta = sum_paid(op_id, is_purchase=False)
    venta_total = op.get("N") or 0.0
    estado_venta = "CANCELADO" if abs(y_venta - venta_total) < 0.01 else "VIGENTE"
    with get_conn() as con:
        con.execute("UPDATE operations SET estado=?, y_pagado=? WHERE id=?", (estado_venta, y_venta, op_id))

# =========================
# Lógica de negocio
# =========================
INVERSORES = ["GONZA", "MARTIN", "TOBIAS (YO)"]

def calcular_precio_compra(costo, inversor):
    if inversor in ("GONZA", "MARTIN"):
        return float(costo) * 1.18
    return float(costo)

# Comisión = 40% del margen bruto (margen = Venta - Precio de compra)
COMISION_PCT = 0.40
def calc_comision_auto(venta: float, purchase_price: float) -> float:
    margen_bruto = float(venta or 0) - float(purchase_price or 0)
    if margen_bruto <= 0:
        return 0.0
    return COMISION_PCT * margen_bruto

def distribuir(importe, cuotas):
    from decimal import Decimal, ROUND_HALF_UP, getcontext
    getcontext().prec = 28
    if not cuotas or cuotas <= 0 or importe is None:
        return []
    total = Decimal(str(importe))
    n = int(cuotas)
    base = (total / n).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    partes = [base for _ in range(n)]
    delta = total - sum(partes)
    if delta != 0:
        partes[-1] = (partes[-1] + delta).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return [float(p) for p in partes]

def to_iso(d: date):
    return datetime(d.year, d.month, d.day).isoformat(timespec="seconds")

def parse_iso_or_today(s: str):
    """Devuelve date desde ISO (con o sin tiempo); si falla, hoy."""
    if not s:
        return date.today()
    try:
        return datetime.fromisoformat(s).date()
    except Exception:
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except Exception:
            return date.today()

def add_months(d: date, months: int) -> date:
    """Suma 'months' meses a la fecha 'd'."""
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    last_day = monthrange(y, m)[1]
    return date(y, m, min(d.day, last_day))

# ========= Helpers analíticos =========
def build_ops_df(ops):
    rows = []
    for op in ops:
        venta = float(op.get("N") or 0.0)
        costo_neto = float(op.get("L") or 0.0)
        price = float(op.get("purchase_price") or 0.0)
        comision = float(op.get("comision") or 0.0)
        cuotas = int(op.get("O") or 0)
        ganancia = venta - price - comision
        rows.append({
            "id": op["id"],
            "descripcion": op.get("descripcion"),
            "cliente": op.get("cliente"),
            "vendedor": op.get("zona"),
            "inversor": op.get("nombre"),
            "venta_total": venta,
            "costo_neto": costo_neto,
            "precio_compra": price,
            "comision": comision,
            "cuotas": cuotas,
            "estado": op.get("estado"),
            "sale_date": parse_iso_or_today(op.get("sale_date") or op.get("created_at")),
            "ganancia": ganancia
        })
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=[
        "id","descripcion","cliente","vendedor","inversor","venta_total","costo_neto",
        "precio_compra","comision","cuotas","estado","sale_date","ganancia"
    ])

def build_installments_df(ops):
    rows = []
    for op in ops:
        base = parse_iso_or_today(op.get("sale_date") or op.get("created_at"))
        op_id = op["id"]
        cliente = op.get("cliente")
        vendedor = op.get("zona")
        inversor = op.get("nombre")
        for c in list_installments(op_id, is_purchase=False):
            due = add_months(base, int(c["idx"]) - 1)
            rows.append({
                "operation_id": op_id, "tipo": "VENTA", "idx": int(c["idx"]),
                "amount": float(c["amount"]), "paid": bool(c["paid"]),
                "paid_at": None if not c["paid_at"] else parse_iso_or_today(c["paid_at"]),
                "due_date": due, "cliente": cliente, "vendedor": vendedor, "inversor": inversor
            })
        for c in list_installments(op_id, is_purchase=True):
            due = add_months(base, int(c["idx"]) - 1)
            rows.append({
                "operation_id": op_id, "tipo": "COMPRA", "idx": int(c["idx"]),
                "amount": float(c["amount"]), "paid": bool(c["paid"]),
                "paid_at": None if not c["paid_at"] else parse_iso_or_today(c["paid_at"]),
                "due_date": due, "cliente": cliente, "vendedor": vendedor, "inversor": inversor
            })
    cols = ["operation_id","tipo","idx","amount","paid","paid_at","due_date","cliente","vendedor","inversor"]
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=cols)

# ========= Autenticación y roles =========
def auth_get_user(username: str):
    with get_conn() as con:
        cur = con.cursor()
        cur.execute("SELECT id, username, password_hash, role, vendedor FROM users WHERE username=?", (username,))
        row = cur.fetchone()
        if not row: return None
        return {"id": row[0], "username": row[1], "password_hash": row[2], "role": row[3], "vendedor": row[4]}

def require_login():
    if st.session_state.get("auth_ok") and st.session_state.get("user"):
        return
    st.title("🔒 Iniciar sesión")
    username = st.text_input("Usuario")
    password = st.text_input("Contraseña", type="password")
    if st.button("Entrar", type="primary"):
        user = auth_get_user(username.strip())
        if user and bcrypt_hash.verify(password, user["password_hash"]):
            st.session_state.auth_ok = True
            st.session_state.user = {"username": user["username"], "role": user["role"], "vendedor": user["vendedor"]}
            st.rerun()
        else:
            st.error("Usuario o contraseña inválidos")
            st.stop()
    st.stop()

def user_scope_filters(base_filters=None):
    """Aplica restricción por rol: los vendedores solo ven su 'zona'."""
    base_filters = base_filters or {}
    user = st.session_state.get("user") or {}
    if user.get("role") == "seller":
        if user.get("vendedor"):
            base_filters = dict(base_filters)
            base_filters["vendedor"] = user["vendedor"]
    return base_filters

def is_admin():
    return (st.session_state.get("user") or {}).get("role") == "admin"

# ===== Helpers VENDORS =====
def list_vendors(active_only=True):
    with get_conn() as con:
        cur = con.cursor()
        if active_only:
            cur.execute("SELECT id, nombre FROM vendors WHERE activo=1 ORDER BY nombre;")
            rows = cur.fetchall()
            return [{"id": r[0], "nombre": r[1]} for r in rows]
        else:
            cur.execute("SELECT id, nombre, activo FROM vendors ORDER BY nombre;")
            rows = cur.fetchall()
            return [{"id": r[0], "nombre": r[1], "activo": r[2]} for r in rows]

def add_vendor(nombre: str):
    if not nombre or not nombre.strip():
        return False, "Nombre vacío"
    try:
        with get_conn() as con:
            con.execute("INSERT INTO vendors (nombre, activo) VALUES (?,1);", (nombre.strip(),))
        return True, "Vendedor creado"
    except sqlite3.IntegrityError:
        return False, "Ese vendedor ya existe"

def deactivate_vendor(vendor_id: int):
    with get_conn() as con:
        con.execute("UPDATE vendors SET activo=0 WHERE id=?", (vendor_id,))

# ===== Helpers USERS (admin) =====
def create_user(username: str, password: str, role: str, vendedor_nombre: str | None):
    if not username or not password:
        return False, "Usuario/contraseña vacíos"
    if role not in ("admin", "seller"):
        return False, "Rol inválido"
    try:
        pwd_hash = bcrypt_hash.hash(password)
        with get_conn() as con:
            con.execute(
                "INSERT INTO users (username, password_hash, role, vendedor) VALUES (?,?,?,?)",
                (username.strip(), pwd_hash, role, vendedor_nombre if role=="seller" else None)
            )
        return True, "Usuario creado"
    except sqlite3.IntegrityError:
        return False, "Ya existe un usuario con ese nombre"

def delete_user(username: str):
    with get_conn() as con:
        con.execute("DELETE FROM users WHERE username=?", (username,))

# =========================
# UI
# =========================
init_db()
require_login()  # pide login antes de mostrar la app

# Sidebar sesión
with st.sidebar:
    u = st.session_state.get("user") or {}
    st.markdown(f"**Usuario:** {u.get('username','-')}  \n**Rol:** {u.get('role','-')}")
    if u.get("role") == "seller" and u.get("vendedor"):
        st.markdown(f"**Vendedor:** {u['vendedor']}")
    if st.button("Cerrar sesión"):
        st.session_state.clear()
        st.rerun()

st.title("Gestión Ventas 2025 — Ventas + Compras (inversor)")

# =========================
# Tabs según rol
# =========================
is_admin_user = is_admin()
if is_admin_user:
    tab_admin, tab_listar, tab_reportes, tab_inversores, tab_crear = st.tabs(
        ["👤 Administración", "📋 Listado & gestión", "📊 Reportes KPI", "🤝 Inversores", "➕ Nueva venta"]
    )
else:
    tab_listar = st.tabs(
        ["📋 Listado & gestión"]
    )[0]

# --------- 👤 ADMINISTRACIÓN (solo admin) ---------
if is_admin_user:
    with tab_admin:
        st.subheader("👤 Administración")

        # --- Vendedores (maestro)
        st.markdown("### 📇 Vendedores")
        colv1, colv2 = st.columns([2,1])
        with colv1:
            nuevo_vend = st.text_input("Nombre del vendedor (tal cual querés que figure en las ventas)")
        with colv2:
            if st.button("Agregar vendedor"):
                ok, msg = add_vendor(nuevo_vend)
                (st.success if ok else st.error)(msg)
                if ok: st.rerun()

        vendors_all = list_vendors(active_only=False)
        if vendors_all:
            st.markdown("**Vendedores cargados**")
            for v in vendors_all:
                cols = st.columns([4,2,2])
                cols[0].markdown(f"- {v['nombre']} {'✅' if v.get('activo',1)==1 else '⛔'}")
                cols[1].markdown("")
                if v.get('activo',1)==1:
                    if cols[2].button("Desactivar", key=f"deact_v_{v['id']}"):
                        deactivate_vendor(v["id"])
                        st.rerun()

        st.divider()

        # --- Usuarios vendedores
        st.markdown("### 👥 Usuarios (vendedores)")
        vend_list = list_vendors(active_only=True)
        vend_names = [v["nombre"] for v in vend_list]
        cu1, cu2, cu3, cu4 = st.columns([2,2,2,1])
        with cu1:
            u_username = st.text_input("Usuario")
        with cu2:
            u_password = st.text_input("Contraseña", type="password")
        with cu3:
            u_vendedor = st.selectbox("Vincular a vendedor", options=vend_names, index=0 if vend_names else None, placeholder="Cargá vendedores primero")
        with cu4:
            if st.button("Crear usuario"):
                if not vend_names:
                    st.error("Primero cargá al menos un vendedor.")
                else:
                    ok, msg = create_user(u_username, u_password, role="seller", vendedor_nombre=u_vendedor)
                    (st.success if ok else st.error)(msg)
                    if ok: st.rerun()

        # Listado rápido de usuarios
        with get_conn() as con:
            cur = con.cursor()
            cur.execute("SELECT username, role, vendedor FROM users ORDER BY role DESC, username ASC;")
            rows = cur.fetchall()
        if rows:
            st.markdown("**Usuarios existentes**")
            for (uname, role, vend) in rows:
                cols = st.columns([3,2,3,2])
                cols[0].write(uname)
                cols[1].write(role)
                cols[2].write(vend or "-")
                if role != "admin":
                    if cols[3].button("Eliminar", key=f"deluser_{uname}"):
                        delete_user(uname)
                        st.rerun()

# --------- CREAR / EDITAR VENTA (solo admin crea) ---------
if is_admin_user:
    with tab_crear:
        st.subheader("Crear venta")

        # Traer vendedores activos (para asignar la venta)
        vend_options = [v["nombre"] for v in list_vendors(active_only=True)]
        if not vend_options:
            st.warning("No hay vendedores cargados. Cargá uno desde 👤 Administración.")
        col1, col2, col3 = st.columns(3)
        with col1:
            descripcion = st.text_input("Descripción (celular vendido) *", value="")
            cliente = st.text_input("Cliente", value="")
            vendedor = st.selectbox("Vendedor", options=vend_options, index=0 if vend_options else None, placeholder="Cargá vendedores en Administración")
        with col2:
            inversor = st.select_slider("Inversor", options=INVERSORES, value="GONZA")
            costo = st.number_input("Costo (neto)", min_value=0.0, value=0.0, step=0.01, format="%.2f")
            venta = st.number_input("Venta", min_value=0.0, value=0.0, step=0.01, format="%.2f")
        with col3:
            cuotas = st.number_input("Cuotas", min_value=0, value=0, step=1)
            fecha_venta = st.date_input("Fecha de la venta", value=date.today())

        precio_compra = calcular_precio_compra(costo, inversor)
        # Comisión y ganancia (automático)
        comision_auto = calc_comision_auto(venta, precio_compra)
        ganancia_neta = (venta - precio_compra) - comision_auto

        st.info(
            f"**Precio de compra (al inversor):** ${precio_compra:,.2f}\n\n"
            f"**Comisión vendedor (auto, 40% del margen):** ${comision_auto:,.2f}\n\n"
            f"**Ganancia neta (Venta - Compra - Comisión):** ${ganancia_neta:,.2f}"
        )

        dist_venta = distribuir(venta, cuotas)
        dist_compra = distribuir(precio_compra, cuotas)

        if st.button("Guardar venta", type="primary"):
            if not descripcion.strip():
                st.error("La descripción es obligatoria.")
            elif cuotas <= 0:
                st.error("Indicá la cantidad de cuotas (mayor a 0).")
            elif not vend_options:
                st.error("Cargá al menos un vendedor en 👤 Administración.")
            else:
                op = {
                    "tipo": "VENTA",
                    "descripcion": descripcion.strip(),
                    "cliente": cliente.strip() or None,
                    "zona": (vendedor or "").strip() or None,
                    "nombre": inversor.strip(),
                    "L": float(costo) if costo else 0.0,
                    "N": float(venta) if venta else 0.0,
                    "O": int(cuotas) if cuotas else 0,
                    "estado": "VIGENTE",
                    "y_pagado": 0.0,
                    "comision": float(comision_auto),
                    "sale_date": to_iso(fecha_venta) if isinstance(fecha_venta, date) else None,
                    "purchase_price": float(precio_compra)
                }
                op_id = upsert_operation(op)
                delete_installments(op_id, is_purchase=None)
                if dist_venta:
                    create_installments(op_id, dist_venta, is_purchase=False)
                if dist_compra:
                    create_installments(op_id, dist_compra, is_purchase=True)
                recalc_status_for_operation(op_id)
                st.success(f"Venta guardada (ID {op_id}).")

# --------- LISTADO & GESTIÓN ---------
with tab_listar:
    st.subheader("Listado de ventas + fila de 'COMPRA' por venta")

    f1, f2, f3 = st.columns(3)
    with f1:
        filtro_cliente = st.text_input("Filtro Cliente", value="")
    with f2:
        # Si seller, el filtro de vendedor queda fijo
        seller = (st.session_state.get("user") or {}).get("role") == "seller"
        seller_name = (st.session_state.get("user") or {}).get("vendedor")
        filtro_vendedor = st.text_input("Filtro Vendedor", value=(seller_name or "" if seller else ""), disabled=seller)
    with f3:
        filtro_inversor = st.text_input("Filtro Inversor", value="")

    busqueda_parcial = st.checkbox("Búsqueda parcial (contiene)", value=True)

    filtros = {}
    if busqueda_parcial:
        if filtro_cliente.strip(): filtros["cliente_like"] = filtro_cliente.strip()
        if (not seller) and filtro_vendedor.strip(): filtros["vendedor_like"] = filtro_vendedor.strip()
        if filtro_inversor.strip(): filtros["inversor_like"] = filtro_inversor.strip()
    else:
        if filtro_cliente.strip(): filtros["cliente"] = filtro_cliente.strip()
        if (not seller) and filtro_vendedor.strip(): filtros["vendedor"] = filtro_vendedor.strip()
        if filtro_inversor.strip(): filtros["inversor"] = filtro_inversor.strip()

    # Aplicar scope por rol
    filtros = user_scope_filters(filtros)

    ops = list_operations(filtros)
    if ops:
        rows = []
        for op in ops:
            total_cuotas = int(op.get("O") or 0)
            fecha_mostrar = op.get("sale_date") or op.get("created_at")
            pagado_venta = sum_paid(op["id"], is_purchase=False)
            pagadas_venta = count_paid_installments(op["id"], is_purchase=False)
            pendientes_venta = max(total_cuotas - pagadas_venta, 0)
            pendiente_venta = float(op.get("N") or 0.0) - pagado_venta
            comision_total = float(op.get("comision") or 0.0)
            comision_x_cuota = (comision_total / total_cuotas) if total_cuotas > 0 else 0.0
            price = float(op.get("purchase_price") or 0.0)
            pagado_compra = sum_paid(op["id"], is_purchase=True)
            pagadas_compra = count_paid_installments(op["id"], is_purchase=True)
            pendientes_compra = max(total_cuotas - pagadas_compra, 0)
            pendiente_compra = price - pagado_compra
            estado_compra = "CANCELADO" if abs(pagado_compra - price) < 0.01 else "VIGENTE"
            # Fila COMPRA
            rows.append({
                "Tipo": "COMPRA","ID venta": op["id"],"Descripción": f"Compra de {op.get('descripcion','')}",
                "Cliente": "","Inversor": op.get("nombre"),"Vendedor": "",
                "Costo": "","Precio Compra": price,"Venta": "","Comisión": "",
                "Comisión x cuota": "","Ganancia": "","Cuotas": total_cuotas,
                "Cuotas pendientes": pendientes_compra,"$ Pagado": pagado_compra,
                "$ Pendiente": pendiente_compra,"Estado": estado_compra,"Fecha": fecha_mostrar
            })
            # Fila VENTA
            ganancia = (float(op.get("N") or 0.0) - price - comision_total)
            rows.append({
                "Tipo": "VENTA","ID venta": op["id"],"Descripción": op.get("descripcion"),
                "Cliente": op.get("cliente"),"Inversor": op.get("nombre"),"Vendedor": op.get("zona"),
                "Costo": float(op.get("L") or 0.0),"Precio Compra": "","Venta": float(op.get("N") or 0.0),
                "Comisión": comision_total,"Comisión x cuota": comision_x_cuota,
                "Ganancia": ganancia,"Cuotas": total_cuotas,"Cuotas pendientes": pendientes_venta,
                "$ Pagado": pagado_venta,"$ Pendiente": pendiente_venta,"Estado": op.get("estado"),
                "Fecha": fecha_mostrar
            })

        df_ops = pd.DataFrame(rows)
        cols_order = ["Tipo","ID venta","Descripción","Cliente","Inversor","Vendedor","Costo",
                      "Precio Compra","Venta","Comisión","Comisión x cuota","Ganancia","Cuotas",
                      "Cuotas pendientes","$ Pagado","$ Pendiente","Estado","Fecha"]
        df_ops = df_ops[cols_order]
        st.dataframe(df_ops, use_container_width=True)

        # Gestión de cuotas
        selected_id = st.number_input("ID de venta para gestionar", min_value=0, step=1, value=int(df_ops["ID venta"].iloc[0]))
        op = get_operation(selected_id) if selected_id else None

        if op:
            st.markdown(
                f"### Venta #{op['id']} — **{op.get('descripcion','')}** | Cliente: **{op.get('cliente','')}** | Inversor: **{op.get('nombre','')}** | Vendedor: **{op.get('zona','')}**"
            )
            total_cuotas = int(op.get("O") or 0)
            venta_total = float(op.get("N") or 0.0)
            y_venta = sum_paid(op["id"], is_purchase=False)
            pendientes_venta = max(total_cuotas - count_paid_installments(op["id"], is_purchase=False), 0)
            pendiente_venta = venta_total - y_venta
            price = float(op.get("purchase_price") or 0.0)
            y_compra = sum_paid(op["id"], is_purchase=True)
            pendientes_compra = max(total_cuotas - count_paid_installments(op["id"], is_purchase=True), 0)
            pendiente_compra = price - y_compra

            st.markdown(
                f"**VENTA** — Total: ${venta_total:.2f} | Cobrado (Y): ${y_venta:.2f} | "
                f"Cuotas: {total_cuotas} | Pendientes: {pendientes_venta} | Pendiente: ${pendiente_venta:.2f}"
            )
            st.markdown(
                f"**COMPRA (pago al inversor)** — Precio compra: ${price:.2f} | Pagado: ${y_compra:.2f} | "
                f"Cuotas: {total_cuotas} | Pendientes: {pendientes_compra} | Pendiente: ${pendiente_compra:.2f}"
            )
            if total_cuotas > 0:
                st.markdown(
                    f"**Valor por cuota (VENTA):** ${venta_total/total_cuotas:.2f} &nbsp;&nbsp; | "
                    f"**Valor por cuota (COMPRA):** ${price/total_cuotas:.2f}"
                )

            # Permisos: solo admin puede editar/eliminar
            puede_editar = is_admin()

            # --- Editar venta ---
            with st.expander("✏️ Editar datos de la venta"):
                if not puede_editar:
                    st.info("Solo un administrador puede editar esta venta.")
                inv_now = op.get("nombre") or "GONZA"
                new_inversor = st.select_slider("Inversor", options=INVERSORES,
                                                value=inv_now if inv_now in INVERSORES else "GONZA",
                                                key=f"inv_{op['id']}", disabled=not puede_editar)
                new_vendedor = st.text_input("Vendedor", value=op.get("zona") or "", key=f"vend_{op['id']}", disabled=not puede_editar)
                new_cliente = st.text_input("Cliente", value=op.get("cliente") or "", key=f"cli_{op['id']}", disabled=not puede_editar)

                new_costo = st.number_input("Costo (neto)", min_value=0.0, value=float(op.get("L") or 0.0), step=0.01, format="%.2f", key=f"costo_{op['id']}", disabled=not puede_editar)
                new_venta = st.number_input("Venta", min_value=0.0, value=float(op.get("N") or 0.0), step=0.01, format="%.2f", key=f"venta_{op['id']}", disabled=not puede_editar)
                new_cuotas = st.number_input("Cuotas", min_value=0, value=int(op.get("O") or 0), step=1, key=f"cuotas_{op['id']}", disabled=not puede_editar)
                default_date = parse_iso_or_today(op.get("sale_date") or op.get("created_at"))
                new_fecha = st.date_input("Fecha de la venta", value=default_date, key=f"fv_{op['id']}", disabled=not puede_editar)

                # Recalcular compra, comisión y ganancia (preview)
                new_price = calcular_precio_compra(new_costo, new_inversor)
                new_comision_auto = calc_comision_auto(new_venta, new_price)
                new_ganancia_neta = (new_venta - new_price) - new_comision_auto

                st.caption(
                    f"**Preview:** Precio compra = ${new_price:,.2f} | "
                    f"Comisión (auto, 40% margen) = ${new_comision_auto:,.2f} | "
                    f"Ganancia neta = ${new_ganancia_neta:,.2f}"
                )

                if puede_editar and st.button("Guardar cambios de venta", key=f"save_op_{op['id']}"):
                    new_price = calcular_precio_compra(new_costo, new_inversor)
                    op["nombre"] = new_inversor
                    op["zona"] = new_vendedor
                    op["cliente"] = new_cliente
                    op["L"] = new_costo
                    op["N"] = new_venta
                    op["O"] = int(new_cuotas)
                    op["comision"] = float(new_comision_auto)
                    op["sale_date"] = to_iso(new_fecha)
                    op["purchase_price"] = new_price
                    upsert_operation(op)
                    delete_installments(op["id"], is_purchase=None)
                    if new_cuotas > 0:
                        create_installments(op["id"], distribuir(new_venta, new_cuotas), is_purchase=False)
                        create_installments(op["id"], distribuir(new_price, new_cuotas), is_purchase=True)
                    recalc_status_for_operation(op["id"])
                    st.success("Venta actualizada y cuotas recalculadas.")
                    st.rerun()

            # --- Cuotas de VENTA (cobros) con casilleros ---
            with st.expander("💳 Gestión de cuotas — VENTA (cobros)", expanded=False):
                cuotas_venta = list_installments(op["id"], is_purchase=False)
                if not cuotas_venta:
                    st.info("No hay cuotas de VENTA registradas.")
                else:
                    df_qv = pd.DataFrame([{
                        "id": c["id"], "Cuota": c["idx"], "Monto": float(c["amount"]),
                        "Pagada": bool(c["paid"]), "Fecha pago (registrada)": c["paid_at"] or ""
                    } for c in cuotas_venta])
                    edited_qv = st.data_editor(
                        df_qv, hide_index=True, use_container_width=True, num_rows="fixed",
                        column_config={
                            "Pagada": st.column_config.CheckboxColumn("Pagada", help="Marcar si la cuota está pagada"),
                            "Monto": st.column_config.NumberColumn("Monto", step=0.01, format="%.2f", disabled=False),
                            "Cuota": st.column_config.NumberColumn("Cuota", disabled=True),
                            "id": st.column_config.TextColumn("id", disabled=True),
                            "Fecha pago (registrada)": st.column_config.TextColumn("Fecha pago (registrada)", disabled=True),
                        },
                        key=f"qv_editor_{op['id']}"
                    )
                    fecha_pago_v = st.date_input("Fecha de cobro a registrar (para las que marques como pagas)", value=date.today(), key=f"fpv_{op['id']}")
                    if st.button("Guardar estado de cuotas VENTA", key=f"btn_pagar_v_{op['id']}"):
                        iso_v = to_iso(fecha_pago_v)
                        orig_by_id = {c["id"]: bool(c["paid"]) for c in cuotas_venta}
                        for _, row in edited_qv.iterrows():
                            iid = int(row["id"])
                            new_paid = bool(row["Pagada"])
                            old_paid = orig_by_id.get(iid, False)
                            if new_paid != old_paid:
                                set_installment_paid(iid, new_paid, paid_at_iso=(iso_v if new_paid else None))
                        recalc_status_for_operation(op["id"])
                        st.success("Cuotas de VENTA actualizadas.")
                        st.rerun()

            # --- Cuotas de COMPRA (pagos al inversor) con casilleros ---
            with st.expander("💸 Pagos al inversor — COMPRA", expanded=False):
                cuotas_compra = list_installments(op["id"], is_purchase=True)
                if not cuotas_compra:
                    st.info("No hay cuotas de COMPRA registradas.")
                else:
                    df_qc = pd.DataFrame([{
                        "id": c["id"], "Cuota": c["idx"], "Monto": float(c["amount"]),
                        "Pagada": bool(c["paid"]), "Fecha pago (registrada)": c["paid_at"] or ""
                    } for c in cuotas_compra])
                    edited_qc = st.data_editor(
                        df_qc, hide_index=True, use_container_width=True, num_rows="fixed",
                        column_config={
                            "Pagada": st.column_config.CheckboxColumn("Pagada", help="Marcar si la cuota está pagada"),
                            "Monto": st.column_config.NumberColumn("Monto", step=0.01, format="%.2f", disabled=False),
                            "Cuota": st.column_config.NumberColumn("Cuota", disabled=True),
                            "id": st.column_config.TextColumn("id", disabled=True),
                            "Fecha pago (registrada)": st.column_config.TextColumn("Fecha pago (registrada)", disabled=True),
                        },
                        key=f"qc_editor_{op['id']}"
                    )
                    fecha_pago_c = st.date_input("Fecha de pago al inversor a registrar (para las que marques como pagas)", value=date.today(), key=f"fpc_{op['id']}")
                    if st.button("Guardar estado de cuotas COMPRA", key=f"btn_pagar_c_{op['id']}"):
                        iso_c = to_iso(fecha_pago_c)
                        orig_by_id = {c["id"]: bool(c["paid"]) for c in cuotas_compra}
                        for _, row in edited_qc.iterrows():
                            iid = int(row["id"])
                            new_paid = bool(row["Pagada"])
                            old_paid = orig_by_id.get(iid, False)
                            if new_paid != old_paid:
                                set_installment_paid(iid, new_paid, paid_at_iso=(iso_c if new_paid else None))
                        recalc_status_for_operation(op["id"])
                        st.success("Cuotas de COMPRA actualizadas.")
                        st.rerun()

            # --- Eliminar venta ---
            with st.expander("🗑️ Eliminar esta venta", expanded=False):
                if not is_admin():
                    st.info("Solo un administrador puede eliminar ventas.")
                confirmar = st.checkbox(f"Sí, quiero eliminar la venta #{op['id']}", key=f"delchk_{op['id']}")
                if is_admin() and st.button("Eliminar definitivamente", key=f"delbtn_{op['id']}"):
                    if confirmar:
                        delete_operation(op["id"])
                        st.success("Venta eliminada.")
                        st.rerun()
                    else:
                        st.error("Marcá la casilla de confirmación para eliminar.")

        else:
            st.info("Seleccioná un ID de venta para ver el detalle.")
    else:
        st.info("No hay ventas registradas todavía.")

# --------- REPORTES KPI (AMPLIADO) ---------
if is_admin_user:
    with tab_reportes:
        st.subheader("📊 Reportes KPI (Clientes)")

        # Scope por rol (si seller, restringir por vendedor)
        filtros = user_scope_filters({})
        ops = list_operations(filtros)
        if not ops:
            st.info("No hay ventas registradas todavía.")
        else:
            ops_df = build_ops_df(ops)
            ins_df = build_installments_df(ops)

            hoy = date.today()
            start_default = hoy.replace(day=1)
            end_default = hoy
            c1, c2 = st.columns(2)
            start_date = c1.date_input("Desde (sale_date)", value=start_default)
            end_date = c2.date_input("Hasta (sale_date)", value=end_default)
            if start_date > end_date:
                st.error("El rango de fechas es inválido.")
            period_ops = ops_df[(ops_df["sale_date"] >= start_date) & (ops_df["sale_date"] <= end_date)]

            total_ventas = float(period_ops["venta_total"].sum())
            total_cobrado = float(ins_df[(ins_df["tipo"]=="VENTA") & (ins_df["paid"]==True)]["amount"].sum())
            total_por_cobrar = float(ins_df[(ins_df["tipo"]=="VENTA") & (ins_df["paid"]==False)]["amount"].sum())
            total_ganancia = float(period_ops["ganancia"].sum())
            total_comision = float(period_ops["comision"].sum())

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Ventas (monto total)", f"${total_ventas:,.2f}")
            m2.metric("Cobrado (todas las ventas)", f"${total_cobrado:,.2f}")
            m3.metric("Por cobrar (pendiente)", f"${total_por_cobrar:,.2f}")
            m4.metric("Ganancia (N - compra - comisión)", f"${total_ganancia:,.2f}")

            tickets = period_ops["venta_total"]
            avg_ticket = float(tickets.mean()) if not tickets.empty else 0.0
            margen_pct = (total_ganancia / total_ventas * 100.0) if total_ventas > 0 else 0.0

            r1, r2, r3 = st.columns(3)
            r1.metric("Ticket promedio", f"${avg_ticket:,.2f}")
            r2.metric("Margen (%)", f"{margen_pct:,.2f}%")
            r3.metric("Comisiones del período", f"${total_comision:,.2f}")

            st.divider()
            st.markdown("**Aging de cuentas por cobrar (VENTA)**")
            vencidas = ins_df[(ins_df["tipo"]=="VENTA") & (ins_df["paid"]==False) & (ins_df["due_date"] < hoy)]
            mes_actual = ins_df[(ins_df["tipo"]=="VENTA") & (ins_df["paid"]==False) &
                                (ins_df["due_date"].apply(lambda d: d.year==hoy.year and d.month==hoy.month))]
            futuras = ins_df[(ins_df["tipo"]=="VENTA") & (ins_df["paid"]==False) &
                            (ins_df["due_date"] > hoy) & (~ins_df.index.isin(mes_actual.index))]
            a1, a2, a3 = st.columns(3)
            a1.metric("Vencidas (impagas)", f"${float(vencidas['amount'].sum()):,.2f}")
            a2.metric("Vencen este mes (impagas)", f"${float(mes_actual['amount'].sum()):,.2f}")
            a3.metric("Futuras (impagas)", f"${float(futuras['amount'].sum()):,.2f}")

            st.divider()
            st.markdown("**Rankings (período seleccionado)**")
            top_cli = (period_ops.groupby("cliente", dropna=False)["venta_total"].sum().sort_values(ascending=False).head(10)).reset_index()
            top_vend = (period_ops.groupby("vendedor", dropna=False)["venta_total"].sum().sort_values(ascending=False).head(10)).reset_index()
            ctc1, ctc2 = st.columns(2)
            ctc1.markdown("**Top 10 clientes por ventas**")
            ctc1.dataframe(top_cli.rename(columns={"cliente":"Cliente","venta_total":"Ventas $"}), use_container_width=True)
            ctc2.markdown("**Top 10 vendedores por ventas**")
            ctc2.dataframe(top_vend.rename(columns={"vendedor":"Vendedor","venta_total":"Ventas $"}), use_container_width=True)

            st.divider()
            st.markdown("**Flujo de caja del mes actual (por fecha de pago)**")
            paid_this_month = ins_df[ins_df["paid_at"].apply(lambda d: (d is not None) and (d.year==hoy.year and d.month==hoy.month))]
            cobros_mes = float(paid_this_month[paid_this_month["tipo"]=="VENTA"]["amount"].sum())
            pagos_inv_mes = float(paid_this_month[paid_this_month["tipo"]=="COMPRA"]["amount"].sum())
            neto_mes = cobros_mes - pagos_inv_mes
            f1, f2, f3 = st.columns(3)
            f1.metric("Cobros a clientes (este mes)", f"${cobros_mes:,.2f}")
            f2.metric("Pagos a inversores (este mes)", f"${pagos_inv_mes:,.2f}")
            f3.metric("Flujo neto (este mes)", f"${neto_mes:,.2f}")

            st.divider()
            st.markdown("**Proyección de vencimientos (mes que viene, impagos)**")
            prox_mes = add_months(hoy.replace(day=1), 1)
            due_next_month = ins_df[(ins_df["tipo"]=="VENTA") & (ins_df["paid"]==False) &
                                    (ins_df["due_date"].apply(lambda d: d.year==prox_mes.year and d.month==prox_mes.month))]
            st.metric("Por cobrar el mes que viene (impago)", f"${float(due_next_month['amount'].sum()):,.2f}")

# --------- INVERSORES (DETALLE POR CADA UNO) ---------
# Ocultamos la pestaña a los vendedores para no exponer datos globales
if is_admin_user:
    with tab_inversores:
        st.subheader("🤝 Inversores")

        ops = list_operations()
        if not ops:
            st.info("No hay ventas registradas todavía.")
        else:
            ops_df = build_ops_df(ops)
            ins_df = build_installments_df(ops)

            total_pagado_inv = float(ins_df[(ins_df["tipo"]=="COMPRA") & (ins_df["paid"]==True)]["amount"].sum())
            total_compra = float(ops_df["precio_compra"].sum())
            total_por_pagar_inv = total_compra - total_pagado_inv
            ganancia_inversores = float(
                ops_df.apply(lambda r: r["costo_neto"]*0.18 if (r["inversor"] in ("GONZA","MARTIN")) else 0.0, axis=1).sum()
            )

            c1, c2, c3 = st.columns(3)
            c1.metric("Pagado a inversores", f"${total_pagado_inv:,.2f}")
            c2.metric("Por pagar a inversores", f"${total_por_pagar_inv:,.2f}")
            c3.metric("Ganancia de inversores (18%)", f"${ganancia_inversores:,.2f}")

            # --- Ganancia por inversor (desglosada) ---
            def _ganancia_inv_para(inv_nombre: str) -> float:
                inv_ops = ops_df[ops_df["inversor"] == inv_nombre]
                if inv_nombre in ("GONZA", "MARTIN"):
                    return float((inv_ops["costo_neto"] * 0.18).sum())
                else:
                    return 0.0

            gan_gonza  = _ganancia_inv_para("GONZA")
            gan_martin = _ganancia_inv_para("MARTIN")
            gan_tobias = _ganancia_inv_para("TOBIAS (YO)")

            g1, g2, g3 = st.columns(3)
            g1.metric("Ganancia GONZA (18%)", f"${gan_gonza:,.2f}")
            g2.metric("Ganancia MARTIN (18%)", f"${gan_martin:,.2f}")
            g3.metric("Ganancia TOBIAS (YO)", f"${gan_tobias:,.2f}")

            st.divider()
            st.subheader("Cuota mensual a inversores (este mes, impagas)")
            hoy = date.today()
            mes_actual, anio_actual = hoy.month, hoy.year

            cuota_mensual_total = 0.0
            detalle = []
            for _, r in ops_df.iterrows():
                op_id = int(r["id"])
                inv = r["inversor"]
                cuotas_compra = ins_df[(ins_df["operation_id"]==op_id) & (ins_df["tipo"]=="COMPRA")]
                for _, c in cuotas_compra.iterrows():
                    venc = c["due_date"]
                    if (venc.year==anio_actual and venc.month==mes_actual) and (not c["paid"]):
                        cuota_mensual_total += float(c["amount"])
                        detalle.append({
                            "ID venta": op_id, "Inversor": inv, "Cuota #": int(c["idx"]),
                            "Vence": venc.isoformat(), "Monto": float(c["amount"])
                        })
            st.metric("Total a pagar este mes (impago)", f"${cuota_mensual_total:,.2f}")
            if detalle:
                st.dataframe(pd.DataFrame(detalle), use_container_width=True)
            else:
                st.info("No hay cuotas impagas de COMPRA que venzan este mes.")

            st.divider()
            st.subheader("Detalle por inversor")
            for inv in ["GONZA", "MARTIN", "TOBIAS (YO)"]:
                st.markdown(f"### {inv}")
                inv_ops = ops_df[ops_df["inversor"]==inv]
                if inv_ops.empty:
                    st.info("Sin operaciones con este inversor.")
                    continue

                inv_ins = ins_df[ins_df["inversor"]==inv]
                inv_total_compra = float(inv_ops["precio_compra"].sum())
                inv_pagado = float(inv_ins[(inv_ins["tipo"]=="COMPRA") & (inv_ins["paid"]==True)]["amount"].sum())
                inv_pendiente = inv_total_compra - inv_pagado
                inv_ganancia = float(inv_ops.apply(lambda r: r["costo_neto"]*0.18 if inv in ("GONZA","MARTIN") else 0.0, axis=1).sum())

                c1, c2, c3 = st.columns(3)
                c1.metric("Total comprado (con 18% si aplica)", f"${inv_total_compra:,.2f}")
                c2.metric("Pagado a este inversor", f"${inv_pagado:,.2f}")
                c3.metric("Pendiente con este inversor", f"${inv_pendiente:,.2f}")

                st.metric("A pagar este mes (impago)", f"${float(inv_ins[(inv_ins['tipo']=='COMPRA') & (inv_ins['paid']==False) & (inv_ins['due_date'].apply(lambda d: d.year==anio_actual and d.month==mes_actual))]['amount'].sum()):,.2f}")
                st.write(f"**Ganancia acumulada del inversor (18%)**: ${inv_ganancia:,.2f}")

                st.markdown("**Operaciones asociadas**")
                inv_tbl = inv_ops[["id","descripcion","cliente","venta_total","precio_compra","comision","ganancia","sale_date","cuotas","estado"]].copy()
                inv_tbl = inv_tbl.rename(columns={
                    "id":"ID venta","descripcion":"Descripción","cliente":"Cliente","venta_total":"Venta $",
                    "precio_compra":"Precio Compra $","comision":"Comisión $","ganancia":"Ganancia $",
                    "sale_date":"Fecha","cuotas":"Cuotas","estado":"Estado"
                })
                st.dataframe(inv_tbl.sort_values("ID venta", ascending=False), use_container_width=True)
else:
    # Si es seller, mantenemos el tab (pero sólo un mensaje para evitar errores de layout)
    pass
