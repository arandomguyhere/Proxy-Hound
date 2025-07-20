import sqlite3
import json
from datetime import datetime

def export_proxies(db_path="proxies.db"):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
        SELECT p.ip, p.port
        FROM proxies p
        JOIN (
            SELECT proxy_id, MAX(checked_at) as max_time FROM health_check WHERE is_alive=1 GROUP BY proxy_id
        ) h ON p.id = h.proxy_id
    """)
    alive = cur.fetchall()

    with open("proxies.txt", "w") as f:
        f.write(f"# Proxy List - {datetime.utcnow().isoformat()}\n")
        for ip, port in alive:
            f.write(f"{ip}:{port}\n")

    cur.execute("""
        SELECT p.ip, p.port, p.country, p.org, p.asn, h.latency_ms, h.checked_at
        FROM proxies p
        LEFT JOIN health_check h ON p.id = h.proxy_id
        WHERE h.is_alive = 1
    """)
    enriched = [
        {
            "ip": ip,
            "port": port,
            "country": country,
            "org": org,
            "asn": asn,
            "latency_ms": latency,
            "last_checked": checked
        }
        for ip, port, country, org, asn, latency, checked in cur.fetchall()
    ]

    with open("proxies.json", "w") as f:
        json.dump(enriched, f, indent=2)

    conn.close()

if __name__ == "__main__":
    export_proxies()
