
# -*- coding: utf-8 -*-
"""
课程管理软件数据库模块

改进内容：
1. SQLite 事务保护
2. 自动数据库快照备份
3. 最多保留最近 20 份备份
4. 安全恢复课程记录
5. 数据库完整性检查
6. 数据库结构版本管理
7. 批量复制课程时使用事务
"""

import sqlite3
from pathlib import Path
from datetime import date, datetime, timedelta
from contextlib import contextmanager


COLUMNS = [
    "日期",
    "开始时间",
    "结束时间",
    "正常课时",
    "三倍课时",
    "总课时",
    "地点",
    "学生人数",
    "课程类型",
    "学生姓名",
    "学科",
    "年级",
    "任课老师",
]

DB_VERSION = 1
DEFAULT_BACKUP_COUNT = 20


def _val(value):
    return "" if value is None else str(value)


class Database:

    def __init__(self, path):
        self.path = Path(path)

        # 创建数据库所在目录
        self.path.parent.mkdir(parents=True, exist_ok=True)

        self._initialize()

    # -------------------------------------------------
    # 数据库连接
    # -------------------------------------------------

    @contextmanager
    def connect(self):
        """
        自动管理数据库连接：
        正常结束时提交，异常时回滚，最后关闭连接。
        """

        conn = sqlite3.connect(
            str(self.path),
            timeout=30
        )

        conn.row_factory = sqlite3.Row

        try:
            conn.execute("PRAGMA busy_timeout = 30000")

            yield conn

            conn.commit()

        except Exception:
            conn.rollback()
            raise

        finally:
            conn.close()

    # -------------------------------------------------
    # 初始化数据库
    # -------------------------------------------------

    def _initialize(self):

        with self.connect() as conn:

            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    日期 TEXT,
                    开始时间 TEXT,
                    结束时间 TEXT,
                    正常课时 REAL,
                    三倍课时 REAL,
                    总课时 REAL,
                    地点 TEXT,
                    学生人数 INTEGER,
                    课程类型 TEXT,
                    学生姓名 TEXT,
                    学科 TEXT,
                    年级 TEXT,
                    任课老师 TEXT
                )
            """)

            # 检查数据库字段，兼容旧版本
            existing = {
                row["name"]
                for row in conn.execute(
                    "PRAGMA table_info(records)"
                ).fetchall()
            }

            column_types = {
                "日期": "TEXT",
                "开始时间": "TEXT",
                "结束时间": "TEXT",
                "正常课时": "REAL",
                "三倍课时": "REAL",
                "总课时": "REAL",
                "地点": "TEXT",
                "学生人数": "INTEGER",
                "课程类型": "TEXT",
                "学生姓名": "TEXT",
                "学科": "TEXT",
                "年级": "TEXT",
                "任课老师": "TEXT",
            }

            for name, data_type in column_types.items():

                if name not in existing:

                    conn.execute(
                        f'ALTER TABLE records ADD COLUMN "{name}" {data_type}'
                    )

            # 常用查询索引
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_records_date
                ON records (日期)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_records_date_start
                ON records (日期, 开始时间)
            """)

            current_version = conn.execute(
                "PRAGMA user_version"
            ).fetchone()[0]

            if current_version > DB_VERSION:
                raise RuntimeError(
                    "数据库版本高于当前软件版本，"
                    "请使用较新版本的软件打开。"
                )

            conn.execute(
                f"PRAGMA user_version = {DB_VERSION}"
            )

    # -------------------------------------------------
    # 数据库完整性检查
    # -------------------------------------------------

    def integrity_check(self):

        with self.connect() as conn:

            result = conn.execute(
                "PRAGMA integrity_check"
            ).fetchone()[0]

        return result

    # -------------------------------------------------
    # 数据库备份
    # -------------------------------------------------

    def create_backup(self, keep=DEFAULT_BACKUP_COUNT):
        """
        使用 SQLite 原生 backup API 备份。

        不直接复制正在使用的数据库文件，
        避免 WAL 模式下备份不完整。
        """

        backup_dir = self.path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime(
            "%Y%m%d_%H%M%S_%f"
        )

        backup_path = (
            backup_dir /
            f"course_manager_{timestamp}.db"
        )

        destination = None

        try:

            with self.connect() as source:

                destination = sqlite3.connect(
                    str(backup_path)
                )

                source.backup(destination)

                destination.commit()

        except Exception:

            if backup_path.exists():
                backup_path.unlink()

            raise

        finally:

            if destination is not None:
                destination.close()

        # 保留最近 keep 份备份
        backups = sorted(
            backup_dir.glob("course_manager_*.db"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )

        for old_backup in backups[max(1, keep):]:

            try:
                old_backup.unlink()
            except OSError:
                pass

        return str(backup_path)

    def list_backups(self):

        backup_dir = self.path.parent / "backups"

        if not backup_dir.exists():
            return []

        backups = sorted(
            backup_dir.glob("course_manager_*.db"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )

        return [str(p) for p in backups]

    # -------------------------------------------------
    # 新增课程
    # -------------------------------------------------

    def add_record(self, row):

        values = [
            row.get(key, "")
            for key in COLUMNS
        ]

        fields = ",".join(
            f'"{key}"' for key in COLUMNS
        )

        placeholders = ",".join(
            "?" for _ in COLUMNS
        )

        with self.connect() as conn:

            conn.execute(
                f"""
                INSERT INTO records ({fields})
                VALUES ({placeholders})
                """,
                values
            )

    # -------------------------------------------------
    # 查询课程
    # -------------------------------------------------

    def get_records(self, keyword=""):

        with self.connect() as conn:

            if keyword:

                like = f"%{keyword}%"

                search_columns = [
                    "学生姓名",
                    "学科",
                    "地点",
                    "年级",
                    "任课老师",
                ]

                conditions = " OR ".join(
                    f'"{column}" LIKE ?'
                    for column in search_columns
                )

                rows = conn.execute(
                    f"""
                    SELECT * FROM records
                    WHERE {conditions}
                    ORDER BY 日期 DESC, 开始时间 DESC
                    """,
                    [like] * len(search_columns)
                ).fetchall()

            else:

                rows = conn.execute("""
                    SELECT * FROM records
                    ORDER BY 日期 DESC, 开始时间 DESC
                """).fetchall()

        return [dict(row) for row in rows]

    def get_records_by_date(self, d):

        with self.connect() as conn:

            rows = conn.execute("""
                SELECT * FROM records
                WHERE 日期 = ?
                ORDER BY 开始时间
            """, (d,)).fetchall()

        return [dict(row) for row in rows]

    def get_month_records(self, year, month):

        prefix = f"{year:04d}-{month:02d}"

        with self.connect() as conn:

            rows = conn.execute("""
                SELECT * FROM records
                WHERE 日期 LIKE ?
                ORDER BY 日期 DESC, 开始时间 DESC
            """, (prefix + "%",)).fetchall()

        return [dict(row) for row in rows]

    # -------------------------------------------------
    # 修改课程
    # -------------------------------------------------

    def update_record(self, rid, row):

        values = [
            row.get(key, "")
            for key in COLUMNS
        ]

        assignments = ", ".join(
            f'"{key}" = ?'
            for key in COLUMNS
        )

        with self.connect() as conn:

            cursor = conn.execute(
                f"""
                UPDATE records
                SET {assignments}
                WHERE id = ?
                """,
                values + [rid]
            )

            return cursor.rowcount > 0

    # -------------------------------------------------
    # 删除课程
    # -------------------------------------------------

    def delete_record(self, rid):

        with self.connect() as conn:

            cursor = conn.execute(
                "DELETE FROM records WHERE id = ?",
                (rid,)
            )

            return cursor.rowcount > 0

    # -------------------------------------------------
    # 复制上一周课程
    # -------------------------------------------------

    def copy_week(self, target_monday):

        if isinstance(target_monday, datetime):
            target_monday = target_monday.date()

        if not isinstance(target_monday, date):
            target_monday = date.fromisoformat(
                str(target_monday)[:10]
            )

        source_monday = target_monday - timedelta(days=7)
        source_sunday = source_monday + timedelta(days=6)

        start = source_monday.isoformat()
        end = source_sunday.isoformat()

        with self.connect() as conn:

            rows = conn.execute("""
                SELECT * FROM records
                WHERE 日期 >= ? AND 日期 <= ?
                ORDER BY 日期, 开始时间
            """, (start, end)).fetchall()

            insert_rows = []

            for source in rows:

                row = dict(source)

                original_date = date.fromisoformat(
                    row["日期"]
                )

                day_offset = (
                    original_date - source_monday
                ).days

                row["日期"] = (
                    target_monday +
                    timedelta(days=day_offset)
                ).isoformat()

                # 复制后生成新的数据库 ID
                values = [
                    row.get(column, "")
                    for column in COLUMNS
                ]

                insert_rows.append(values)

            if insert_rows:

                fields = ",".join(
                    f'"{column}"'
                    for column in COLUMNS
                )

                placeholders = ",".join(
                    "?" for _ in COLUMNS
                )

                conn.executemany(
                    f"""
                    INSERT INTO records ({fields})
                    VALUES ({placeholders})
                    """,
                    insert_rows
                )

        return len(insert_rows)

    # -------------------------------------------------
    # 安全替换全部课程记录
    # -------------------------------------------------

    def replace_records(self, rows, backup=True):
        """
        JSON 恢复时使用。

        先验证数据，再备份旧数据库，
        最后在一个事务中完成替换。

        如果插入过程中发生异常，
        SQLite 会自动回滚，不会留下半份数据。
        """

        if not isinstance(rows, list):
            raise ValueError("课程记录格式错误，必须是列表。")

        prepared = []

        for index, row in enumerate(rows):

            if not isinstance(row, dict):
                raise ValueError(
                    f"第 {index + 1} 条课程记录格式错误。"
                )

            values = [
                row.get(column, "")
                for column in COLUMNS
            ]

            record_id = row.get("id")

            if record_id is not None:

                try:
                    record_id = int(record_id)
                except (TypeError, ValueError):
                    raise ValueError(
                        f"第 {index + 1} 条记录的 ID 无效。"
                    )

                if record_id <= 0:
                    raise ValueError(
                        f"第 {index + 1} 条记录的 ID 无效。"
                    )

            prepared.append((record_id, values))

        # 在破坏旧数据前创建快照
        if backup:
            self.create_backup()

        with self.connect() as conn:

            conn.execute("DELETE FROM records")

            fields = ",".join(
                f'"{column}"'
                for column in COLUMNS
            )

            placeholders = ",".join(
                "?" for _ in COLUMNS
            )

            normal_sql = f"""
                INSERT INTO records ({fields})
                VALUES ({placeholders})
            """

            with_id_sql = f"""
                INSERT INTO records (id, {fields})
                VALUES (?, {placeholders})
            """

            for record_id, values in prepared:

                if record_id is None:

                    conn.execute(
                        normal_sql,
                        values
                    )

                else:

                    conn.execute(
                        with_id_sql,
                        [record_id] + values
                    )

        return len(prepared)
