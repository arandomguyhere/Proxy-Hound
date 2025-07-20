import sqlite3
from datetime import datetime

class ProxyDatabase:
    def __init__(self, path="proxies.db"):
        self.conn = sqlite3.connect(path)
        self.cursor = self.conn.cursor()
        self._create_tables()

    def _create_tables(self):
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS proxies (
                id INTEGER PRIMARY KEY,
                ip TEXT NOT NULL,
                port INTEGER NOT NULL,
                source TEXT,
                asn TEXT,
                org TEXT,
                country TEXT,
                region TEXT,
                inferred_type TEXT,
                first_seen TIMESTAMP,
                last_seen TIMESTAMP,
                UNIQUE(ip, port)
            )
        ''')
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS health_check (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                proxy_id INTEGER,
                checked_at TIMESTAMP,
                is_alive BOOLEAN,
                is_https BOOLEAN,
                latency_ms REAL,
                FOREIGN KEY(proxy_id) REFERENCES proxies(id)
            )
        ''')
        self.conn.commit()

    def upsert_proxy(self, ip, port, source, metadata):
        now = datetime.utcnow().isoformat()
        self.cursor.execute('''
            INSERT INTO proxies (ip, port, source, asn, org, country, region, inferred_type, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ip, port) DO UPDATE SET
                source=excluded.source,
                asn=excluded.asn,
                org=excluded.org,
                country=excluded.country,
                region=excluded.region,
                inferred_type=excluded.inferred_type,
                last_seen=excluded.last_seen
        ''', (ip, port, source,
              metadata.get('asn'), metadata.get('org'),
              metadata.get('country'), metadata.get('region'),
              metadata.get('inferred_type'), now, now))
        self.conn.commit()

    def log_health(self, ip, port, is_alive, is_https, latency_ms):
        self.cursor.execute('SELECT id FROM proxies WHERE ip=? AND port=?', (ip, port))
        row = self.cursor.fetchone()
        if not row:
            return
        proxy_id = row[0]
        self.cursor.execute('''
            INSERT INTO health_check (proxy_id, checked_at, is_alive, is_https, latency_ms)
            VALUES (?, ?, ?, ?, ?)
        ''', (proxy_id, datetime.utcnow().isoformat(), is_alive, is_https, latency_ms))
        self.conn.commit()

    def close(self):
        self.conn.close()
