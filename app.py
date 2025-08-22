# ---- Auto-restore simple al arrancar ----
try:
    with get_conn() as con:
        cnt = con.execute("SELECT COUNT(*) FROM operations").fetchone()[0]
    if cnt == 0:
        restore_db_from_github_snapshot()
        st.toast("Base restaurada desde GitHub ✅", icon="✅")
except Exception as e:
    st.warning(f"No se pudo restaurar automáticamente: {e}")
