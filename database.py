from __future__ import annotations

import dataclasses
import datetime as dt
from typing import Any, Iterable, Optional

import aiosqlite


@dataclasses.dataclass(frozen=True)
class User:
    id: int
    tg_id: int
    name: str
    role: str  # admin/observer/member
    internal_rate: float
    external_rate: float


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> aiosqlite.Connection:
        if self._conn is None:
            self._conn = await aiosqlite.connect(self.path)
            self._conn.row_factory = aiosqlite.Row
            await self._conn.execute("PRAGMA foreign_keys = ON;")
        return self._conn

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def init(self) -> None:
        conn = await self.connect()
        await conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tg_id INTEGER NOT NULL UNIQUE,
              name TEXT NOT NULL,
              role TEXT NOT NULL CHECK (role IN ('admin','observer','member')),
              internal_rate REAL NOT NULL DEFAULT 0,
              external_rate REAL NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS clients (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL UNIQUE,
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS projects (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              client_id INTEGER NOT NULL,
              name TEXT NOT NULL,
              status TEXT NOT NULL CHECK (status IN ('active','sleeping','done')),
              last_activity_at TEXT,
              FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE,
              UNIQUE (client_id, name)
            );

            CREATE TABLE IF NOT EXISTS user_projects (
              user_id INTEGER NOT NULL,
              project_id INTEGER NOT NULL,
              PRIMARY KEY (user_id, project_id),
              FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
              FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS timelog (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id INTEGER NOT NULL,
              project_id INTEGER NOT NULL,
              hours REAL NOT NULL,
              date TEXT NOT NULL,
              created_at TEXT NOT NULL,
              FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
              FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS absence (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id INTEGER NOT NULL,
              date TEXT NOT NULL,
              reason TEXT NOT NULL CHECK (reason IN ('vacation','sick','dayoff')),
              created_at TEXT NOT NULL,
              FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
              UNIQUE (user_id, date)
            );

            CREATE TABLE IF NOT EXISTS reminder_ack (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id INTEGER NOT NULL,
              date TEXT NOT NULL,
              kind TEXT NOT NULL,
              created_at TEXT NOT NULL,
              FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
              UNIQUE (user_id, date, kind)
            );

            CREATE TABLE IF NOT EXISTS reminder_flags (
              user_id INTEGER NOT NULL,
              date TEXT NOT NULL,
              key TEXT NOT NULL,
              value TEXT NOT NULL,
              created_at TEXT NOT NULL,
              PRIMARY KEY (user_id, date, key),
              FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_timelog_user_date ON timelog(user_id, date);
            CREATE INDEX IF NOT EXISTS idx_timelog_project_date ON timelog(project_id, date);
            CREATE INDEX IF NOT EXISTS idx_projects_status_activity ON projects(status, last_activity_at);
            CREATE INDEX IF NOT EXISTS idx_absence_user_date ON absence(user_id, date);
            CREATE INDEX IF NOT EXISTS idx_reminder_ack_user_date ON reminder_ack(user_id, date);
            """
        )
        await conn.commit()

    async def execute(self, sql: str, params: Iterable[Any] = ()) -> None:
        conn = await self.connect()
        await conn.execute(sql, tuple(params))
        await conn.commit()

    async def executemany(self, sql: str, seq_of_params: Iterable[Iterable[Any]]) -> None:
        conn = await self.connect()
        await conn.executemany(sql, [tuple(p) for p in seq_of_params])
        await conn.commit()

    async def fetchone(self, sql: str, params: Iterable[Any] = ()) -> Optional[aiosqlite.Row]:
        conn = await self.connect()
        async with conn.execute(sql, tuple(params)) as cur:
            return await cur.fetchone()

    async def fetchall(self, sql: str, params: Iterable[Any] = ()) -> list[aiosqlite.Row]:
        conn = await self.connect()
        async with conn.execute(sql, tuple(params)) as cur:
            rows = await cur.fetchall()
        return list(rows)

    # ---------- users ----------
    async def get_user_by_tg(self, tg_id: int) -> User | None:
        row = await self.fetchone("SELECT * FROM users WHERE tg_id = ?;", (tg_id,))
        if not row:
            return None
        return User(
            id=row["id"],
            tg_id=row["tg_id"],
            name=row["name"],
            role=row["role"],
            internal_rate=float(row["internal_rate"]),
            external_rate=float(row["external_rate"]),
        )

    async def create_user(self, tg_id: int, name: str, role: str = "member") -> User:
        conn = await self.connect()
        await conn.execute(
            "INSERT INTO users (tg_id, name, role, internal_rate, external_rate) VALUES (?,?,?,?,?);",
            (tg_id, name.strip(), role, 0.0, 0.0),
        )
        await conn.commit()
        user = await self.get_user_by_tg(tg_id)
        assert user is not None
        return user

    async def maybe_seed_first_admin(self, admin_tg_id: int | None) -> None:
        if admin_tg_id is None:
            return
        await self.execute(
            "UPDATE users SET role = 'admin' WHERE tg_id = ?;",
            (admin_tg_id,),
        )

    async def list_users(self) -> list[aiosqlite.Row]:
        return await self.fetchall(
            "SELECT id, tg_id, name, role, internal_rate, external_rate FROM users ORDER BY name;"
        )

    async def set_user_role(self, user_id: int, role: str) -> None:
        await self.execute("UPDATE users SET role = ? WHERE id = ?;", (role, user_id))

    async def set_user_rates(self, user_id: int, internal_rate: float, external_rate: float) -> None:
        await self.execute(
            "UPDATE users SET internal_rate = ?, external_rate = ? WHERE id = ?;",
            (float(internal_rate), float(external_rate), user_id),
        )

    # ---------- clients ----------
    async def list_clients(self) -> list[aiosqlite.Row]:
        return await self.fetchall("SELECT id, name FROM clients ORDER BY name;")

    async def create_client(self, name: str) -> int:
        now = dt.datetime.utcnow().isoformat(timespec="seconds")
        conn = await self.connect()
        cur = await conn.execute(
            "INSERT INTO clients (name, created_at) VALUES (?, ?);",
            (name.strip(), now),
        )
        await conn.commit()
        return int(cur.lastrowid)

    async def rename_client(self, client_id: int, name: str) -> None:
        await self.execute("UPDATE clients SET name = ? WHERE id = ?;", (name.strip(), client_id))

    # ---------- projects ----------async def maybe
    async def list_active_projects_for_user(self, user_id: int) -> list[aiosqlite.Row]:
        return await self.fetchall(
            """
            SELECT p.id, p.name, c.name AS client_name
            FROM projects p
            JOIN clients c ON c.id = p.client_id
            JOIN user_projects up ON up.project_id = p.id
            WHERE up.user_id = ? AND p.status = 'active'
            ORDER BY c.name, p.name;
            """,
            (user_id,),
        )

    async def list_sleeping_projects_for_user(self, user_id: int) -> list[aiosqlite.Row]:
        return await self.fetchall(
            """
            SELECT p.id, p.name, c.name AS client_name, p.last_activity_at
            FROM projects p
            JOIN clients c ON c.id = p.client_id
            JOIN user_projects up ON up.project_id = p.id
            WHERE up.user_id = ? AND p.status = 'sleeping'
            ORDER BY p.last_activity_at, c.name, p.name;
            """,
            (user_id,),
        )

    async def list_projects_for_client_active(self, client_id: int) -> list[aiosqlite.Row]:
        return await self.fetchall(
            """
            SELECT id, name
            FROM projects
            WHERE client_id = ? AND status = 'active'
            ORDER BY name;
            """,
            (client_id,),
        )

    async def create_project(self, client_id: int, name: str) -> int:
        conn = await self.connect()
        cur = await conn.execute(
            """
            INSERT INTO projects (client_id, name, status, last_activity_at)
            VALUES (?, ?, 'active', NULL);
            """,
            (client_id, name.strip()),
        )
        await conn.commit()
        return int(cur.lastrowid)

    async def set_project_status(self, project_id: int, status: str) -> None:
        await self.execute("UPDATE projects SET status = ? WHERE id = ?;", (status, project_id))

    async def touch_project_activity(self, project_id: int, activity_date: dt.date) -> None:
        # If project was sleeping, re-activate on activity.
        await self.execute(
            """
            UPDATE projects
            SET last_activity_at = ?, status = CASE WHEN status = 'done' THEN 'done' ELSE 'active' END
            WHERE id = ?;
            """,
            (activity_date.isoformat(), project_id),
        )

    async def attach_user_to_project(self, user_id: int, project_id: int) -> None:
        await self.execute(
            "INSERT OR IGNORE INTO user_projects (user_id, project_id) VALUES (?, ?);",
            (user_id, project_id),
        )

    async def list_all_open_projects(self) -> list[aiosqlite.Row]:
        return await self.fetchall(
            """
            SELECT p.id, p.name, p.status, c.name AS client_name, p.last_activity_at
            FROM projects p
            JOIN clients c ON c.id = p.client_id
            WHERE p.status IN ('active','sleeping')
            ORDER BY p.status, c.name, p.name;
            """
        )

    async def mark_sleeping_projects(self, today: dt.date) -> int:
        # Sets active projects with no activity 14+ days to sleeping.
        conn = await self.connect()
        cur = await conn.execute(
            """
            UPDATE projects
            SET status = 'sleeping'
            WHERE status = 'active'
              AND last_activity_at IS NOT NULL
              AND date(last_activity_at) <= date(?, '-14 day');
            """,
            (today.isoformat(),),
        )
        await conn.commit()
        return int(cur.rowcount or 0)

    # ---------- timelog ----------
    async def add_timelog(self, user_id: int, project_id: int, hours: float, date_: dt.date) -> int:
        conn = await self.connect()
        now = dt.datetime.utcnow().isoformat(timespec="seconds")
        cur = await conn.execute(
            """
            INSERT INTO timelog (user_id, project_id, hours, date, created_at)
            VALUES (?, ?, ?, ?, ?);
            """,
            (user_id, project_id, float(hours), date_.isoformat(), now),
        )
        await conn.commit()
        return int(cur.lastrowid)

    async def user_project_hours(
        self, user_id: int, project_id: int, start: dt.date | None = None, end: dt.date | None = None
    ) -> float:
        if start and end:
            row = await self.fetchone(
                "SELECT COALESCE(SUM(hours),0) AS h FROM timelog WHERE user_id=? AND project_id=? AND date BETWEEN ? AND ?;",
                (user_id, project_id, start.isoformat(), end.isoformat()),
            )
        elif start:
            row = await self.fetchone(
                "SELECT COALESCE(SUM(hours),0) AS h FROM timelog WHERE user_id=? AND project_id=? AND date >= ?;",
                (user_id, project_id, start.isoformat()),
            )
        else:
            row = await self.fetchone(
                "SELECT COALESCE(SUM(hours),0) AS h FROM timelog WHERE user_id=? AND project_id=?;",
                (user_id, project_id),
            )
        return float(row["h"]) if row else 0.0

    async def report_grouped(
        self,
        start: dt.date,
        end: dt.date,
        group_by: str,  # project/user/client
        restrict_user_id: int | None = None,
    ) -> list[aiosqlite.Row]:
        where = "t.date BETWEEN ? AND ?"
        params: list[Any] = [start.isoformat(), end.isoformat()]
        if restrict_user_id is not None:
            where += " AND t.user_id = ?"
            params.append(restrict_user_id)

        if group_by == "project":
            group_sql = "p.id, p.name, c.name AS client_name"
            label_sql = "p.id AS group_id, p.name AS label, c.name AS client_name"
            join_extra = ""
            order = "c.name, p.name"
        elif group_by == "user":
            group_sql = "u.id, u.name"
            label_sql = "u.id AS group_id, u.name AS label, NULL AS client_name"
            join_extra = ""
            order = "u.name"
        elif group_by == "client":
            group_sql = "c.id, c.name"
            label_sql = "c.id AS group_id, c.name AS label, c.name AS client_name"
            join_extra = ""
            order = "c.name"
        else:
            raise ValueError("bad group_by")

        return await self.fetchall(
            f"""
            SELECT
              {label_sql},
              SUM(t.hours) AS hours,
              SUM(t.hours * u.internal_rate) AS internal_cost,
              SUM(t.hours * u.external_rate) AS external_cost
            FROM timelog t
            JOIN users u ON u.id = t.user_id
            JOIN projects p ON p.id = t.project_id
            JOIN clients c ON c.id = p.client_id
            {join_extra}
            WHERE {where}
            GROUP BY {group_sql}
            ORDER BY {order};
            """,
            params,
        )

    # ---------- absence / reminders ----------

    async def add_absence(self, user_id: int, date_: dt.date, reason: str) -> None:
        now = dt.datetime.utcnow().isoformat(timespec="seconds")
        await self.execute(
            """
            INSERT INTO absence (user_id, date, reason, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, date) DO UPDATE SET reason=excluded.reason;
            """,
            (int(user_id), date_.isoformat(), str(reason), now),
        )

    async def absence_counts(self, start: dt.date, end: dt.date) -> list[aiosqlite.Row]:
        return await self.fetchall(
            """
            SELECT user_id, reason, COUNT(*) AS days
            FROM absence
            WHERE date BETWEEN ? AND ?
            GROUP BY user_id, reason;
            """,
            (start.isoformat(), end.isoformat()),
        )

    async def has_timelog(self, user_id: int, date_: dt.date) -> bool:
        row = await self.fetchone(
            "SELECT 1 FROM timelog WHERE user_id = ? AND date = ? LIMIT 1;",
            (int(user_id), date_.isoformat()),
        )
        return row is not None

    async def has_absence(self, user_id: int, date_: dt.date) -> bool:
        row = await self.fetchone(
            "SELECT 1 FROM absence WHERE user_id = ? AND date = ? LIMIT 1;",
            (int(user_id), date_.isoformat()),
        )
        return row is not None

    async def ack_reminder(self, user_id: int, date_: dt.date, kind: str) -> None:
        now = dt.datetime.utcnow().isoformat(timespec="seconds")
        await self.execute(
            """
            INSERT OR IGNORE INTO reminder_ack (user_id, date, kind, created_at)
            VALUES (?, ?, ?, ?);
            """,
            (int(user_id), date_.isoformat(), str(kind), now),
        )

    async def has_ack(self, user_id: int, date_: dt.date, kind: str) -> bool:
        row = await self.fetchone(
            "SELECT 1 FROM reminder_ack WHERE user_id = ? AND date = ? AND kind = ? LIMIT 1;",
            (int(user_id), date_.isoformat(), str(kind)),
        )
        return row is not None

    async def set_flag(self, user_id: int, date_: dt.date, key: str, value: str) -> None:
        now = dt.datetime.utcnow().isoformat(timespec="seconds")
        await self.execute(
            """
            INSERT INTO reminder_flags (user_id, date, key, value, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, date, key) DO UPDATE SET value=excluded.value;
            """,
            (int(user_id), date_.isoformat(), str(key), str(value), now),
        )

    async def get_flag(self, user_id: int, date_: dt.date, key: str) -> str | None:
        row = await self.fetchone(
            "SELECT value FROM reminder_flags WHERE user_id = ? AND date = ? AND key = ?;",
            (int(user_id), date_.isoformat(), str(key)),
        )
        return str(row["value"]) if row else None


