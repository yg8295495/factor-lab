"""
数据库连接管理
"""

import sqlite3
import os
from pathlib import Path

# 默认数据库路径（相对于项目根目录）
DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / 'data' / 'quant_engine.db'


def get_connection(db_path=None):
    """获取数据库连接"""
    path = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


class Session:
    """简易 Session 封装，提供上下文管理"""

    def __init__(self, db_path=None):
        self.conn = get_connection(db_path)
        self.cursor = self.conn.cursor()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.conn.commit()
        else:
            self.conn.rollback()
        self.conn.close()

    def execute(self, sql, params=None):
        return self.conn.execute(sql, params or [])

    def executemany(self, sql, params_list):
        return self.conn.executemany(sql, params_list)

    def fetchall(self):
        return self.cursor.fetchall()

    def fetchone(self):
        return self.cursor.fetchone()
