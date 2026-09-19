from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from .models import Caption, DownloadStatus, Project, ProjectStatus
from .settings import APP_DIR


class LibraryDatabase:
    def __init__(self, database_path: Path | None = None) -> None:
        self.path = database_path or APP_DIR / "library.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._create_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _create_schema(self) -> None:
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    author TEXT NOT NULL DEFAULT '',
                    provider TEXT NOT NULL DEFAULT '本地导入',
                    source_url TEXT NOT NULL DEFAULT '',
                    media_path TEXT NOT NULL DEFAULT '',
                    reference_path TEXT NOT NULL DEFAULT '',
                    subtitle_source TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    source_language TEXT NOT NULL DEFAULT 'auto',
                    target_language TEXT NOT NULL DEFAULT 'zh',
                    subtitle_order TEXT NOT NULL DEFAULT 'source_first',
                    recognition_engine TEXT NOT NULL DEFAULT 'faster-whisper',
                    translation_engine TEXT NOT NULL DEFAULT 'pyvideotrans-local',
                    alignment_enabled INTEGER NOT NULL DEFAULT 0,
                    download_status TEXT NOT NULL DEFAULT '待下载',
                    download_format TEXT NOT NULL DEFAULT 'audio'
                );
                CREATE TABLE IF NOT EXISTS captions (
                    id INTEGER PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL,
                    start_seconds REAL NOT NULL,
                    end_seconds REAL NOT NULL,
                    english TEXT NOT NULL,
                    chinese TEXT NOT NULL DEFAULT '',
                    source_text TEXT NOT NULL DEFAULT '',
                    translated_text TEXT NOT NULL DEFAULT '',
                    UNIQUE(project_id, position)
                );
                """
            )
            self._ensure_columns(connection, "projects", {
                "source_language": "TEXT NOT NULL DEFAULT 'auto'",
                "target_language": "TEXT NOT NULL DEFAULT 'zh'",
                "subtitle_order": "TEXT NOT NULL DEFAULT 'source_first'",
                "recognition_engine": "TEXT NOT NULL DEFAULT 'faster-whisper'",
                "translation_engine": "TEXT NOT NULL DEFAULT 'pyvideotrans-local'",
                "alignment_enabled": "INTEGER NOT NULL DEFAULT 0",
                "download_status": "TEXT NOT NULL DEFAULT '待下载'",
                "download_format": "TEXT NOT NULL DEFAULT 'audio'",
            })
            self._ensure_columns(connection, "captions", {
                "source_text": "TEXT NOT NULL DEFAULT ''",
                "translated_text": "TEXT NOT NULL DEFAULT ''",
            })
            connection.execute("UPDATE captions SET source_text=english WHERE source_text='' AND english<>''")
            connection.execute("UPDATE captions SET translated_text=chinese WHERE translated_text='' AND chinese<>''")
            connection.commit()

    @staticmethod
    def _ensure_columns(connection: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
        existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        for name, definition in columns.items():
            if name not in existing:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def save_project(self, project: Project) -> Project:
        values = (
            project.title, project.author, project.provider, project.source_url,
            project.media_path, project.reference_path, project.subtitle_source,
            project.status.value, project.error,
            project.source_language, project.target_language, project.subtitle_order,
            project.recognition_engine, project.translation_engine, int(project.alignment_enabled),
            project.download_status.value, project.download_format,
        )
        with closing(self._connect()) as connection:
            if project.id is None:
                cursor = connection.execute(
                    """INSERT INTO projects
                    (title, author, provider, source_url, media_path, reference_path, subtitle_source, status, error,
                    source_language, target_language, subtitle_order, recognition_engine, translation_engine, alignment_enabled,
                    download_status, download_format)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", values
                )
                project.id = cursor.lastrowid
            else:
                connection.execute(
                    """UPDATE projects SET title=?, author=?, provider=?, source_url=?, media_path=?,
                    reference_path=?, subtitle_source=?, status=?, error=?, source_language=?, target_language=?,
                    subtitle_order=?, recognition_engine=?, translation_engine=?, alignment_enabled=?,
                    download_status=?, download_format=?,
                    updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                    values[0:9] + values[9:] + (project.id,),
                )
                connection.execute("DELETE FROM captions WHERE project_id=?", (project.id,))
            connection.executemany(
                """INSERT INTO captions (project_id, position, start_seconds, end_seconds, english, chinese, source_text, translated_text)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [(project.id, index, caption.start, caption.end, caption.source_text, caption.translated_text,
                  caption.source_text, caption.translated_text)
                 for index, caption in enumerate(project.captions)],
            )
            connection.commit()
        return self.get_project(project.id)

    def get_project(self, project_id: int) -> Project:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
            if row is None:
                raise KeyError(project_id)
            captions = connection.execute(
                "SELECT start_seconds, end_seconds, english, chinese, source_text, translated_text FROM captions WHERE project_id=? ORDER BY position",
                (project_id,),
            ).fetchall()
        return Project(
            id=row["id"], title=row["title"], author=row["author"], provider=row["provider"],
            source_url=row["source_url"], media_path=row["media_path"], reference_path=row["reference_path"],
            subtitle_source=row["subtitle_source"], status=ProjectStatus(row["status"]), error=row["error"],
            created_at=row["created_at"], updated_at=row["updated_at"],
            captions=[Caption(c["start_seconds"], c["end_seconds"], c["source_text"] or c["english"], c["translated_text"] or c["chinese"]) for c in captions],
            source_language=row["source_language"], target_language=row["target_language"],
            subtitle_order=row["subtitle_order"], recognition_engine=row["recognition_engine"],
            translation_engine=row["translation_engine"], alignment_enabled=bool(row["alignment_enabled"]),
            download_status=DownloadStatus(row["download_status"]), download_format=row["download_format"],
        )

    def list_projects(self) -> list[Project]:
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT id FROM projects ORDER BY updated_at DESC, id DESC").fetchall()
        return [self.get_project(row["id"]) for row in rows]

    def recover_interrupted_projects(self) -> int:
        """Mark unfinished work from a previous app session as retryable."""
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """UPDATE projects
                SET status=?, error=?, updated_at=CURRENT_TIMESTAMP
                WHERE status=?""",
                (
                    ProjectStatus.FAILED.value,
                    "上次运行期间任务被中断，可以重新加入处理队列。",
                    ProjectStatus.PROCESSING.value,
                ),
            )
            connection.commit()
            return cursor.rowcount
