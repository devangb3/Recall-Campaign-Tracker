"""Small transactional migrations for tables with expanded CHECK enums."""

import sqlite3


def expand_check(con: sqlite3.Connection, table: str, marker: str,
                 create_sql: str, *, current_view: bool = False) -> None:
    """Rebuild a known internal table only when its CHECK is outdated.

    The caller owns the transaction. Row identifiers, indexes, and all
    historical rows survive; no source records or saved JSON are changed.
    """
    row = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (table,)).fetchone()
    if row is None or marker in row[0]:
        return
    indexes = [r[0] for r in con.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? "
        "AND sql IS NOT NULL", (table,))]
    if current_view:
        con.execute(f"DROP VIEW IF EXISTS cur_{table}")
    con.execute(create_sql.replace(
        f"IF NOT EXISTS {table}", f"{table}_expanded", 1))
    con.execute(f"INSERT INTO {table}_expanded SELECT * FROM {table}")
    con.execute(f"DROP TABLE {table}")
    con.execute(f"ALTER TABLE {table}_expanded RENAME TO {table}")
    for sql in indexes:
        con.execute(sql)
