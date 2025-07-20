#!/usr/bin/env python3
"""
Direct Proxy Sources System
Uses known good proxy list URLs for reliable discovery
"""

import asyncio
import json
import logging
import sqlite3
import time
import gzip
from datetime import datetime, timezone
from pathlib import Path
import os
import sys

# Minimal imports for GitHub Actions
import aiohttp
import aiofiles
import psutil

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Known good proxy sources
PROXY_SOURCES = [
    {
        "name": "r00tee HTTPS Proxies",
        "url": "https://raw.githubusercontent.com/r00tee/Proxy-List/main/Https.txt",
        "type": "https"
    },
    {
        "name": "r00tee SOCKS4 Proxies", 
        "url": "https://raw.githubusercontent.com/r00tee/Proxy-List/main/Socks4.txt",
        "type": "socks4"
    },
    {
        "name": "r00tee SOCKS5 Proxies",
        "url": "https://raw.githubusercontent.com/r00tee/Proxy-List/main/Socks5.txt", 
        "type": "socks5"
    },
    {
        "name": "VMHeaven HTTP Proxies",
        "url": "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/http.txt",
        "type": "http"
    },
    {
        "name": "VMHeaven HTTPS Proxies", 
        "url": "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/https.txt",
        "type": "https"
    },
    {
        "name": "VMHeaven SOCKS4 Proxies",
        "url": "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/socks4.txt",
        "type": "socks4"
    },
    {
        "name": "VMHeaven SOCKS5 Proxies",
        "url": "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/socks5.txt",
        "type": "socks5"
    },
    # GitHub search backup sources
    {
        "name": "GitHub Search Backup",
        "url": "github_search",
        "type": "mixed"
    }
]

class ProxyDatabase:
    """Optimized database for millions of proxies"""
    
    def __init__(self, db_path="proxies.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Initialize optimized database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL") 
                conn.execute("PRAGMA cache_size=10000")
                conn.execute("PRAGMA temp_store=MEMORY")
                
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS proxies (
                        id INTEGER PRIMARY KEY,
                        ip TEXT NOT NULL,
                        port INTEGER NOT NULL,
                        proxy_type TEXT,
                        source TEXT NOT NULL,
                        country TEXT,
                        last_checked TEXT,
                        is_working BOOLEAN DEFAULT 0,
                        response_time REAL,
                        first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(ip, port)
                    )
                """)
                
                conn.execute("CREATE INDEX IF NOT EXISTS idx_ip_port ON proxies(ip, port)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_working ON proxies(is_working)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_type ON proxies(proxy_type)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_source ON proxies(source)")
            logger.info("✅ Database initialized successfully")
        except Exception as e:
            logger.error(f"❌ Database initialization failed: {e}")
            raise
    
    def add_proxies_batch(self, proxies, batch_size=1000):
        """Add proxies in optimized batches"""
        if not proxies:
            logger.warning("⚠️ No proxies to add to database")
            return
            
        logger.info(f"📝 Adding {len(proxies)} proxies to database")
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("BEGIN TRANSACTION")
                
                for i in range(0, len(proxies), batch_size):
                    batch = proxies[i:i + batch_size]
                    data = [
                        (p['ip'], p['port'], p.get('proxy_type'), p['source'], 
                         p.get('country'), p.get('last_checked'), 
                         p.get('is_working', False), p.get('response_time'))
                        for p in batch
                    ]
                    
                    conn.executemany("""
                        INSERT OR REPLACE INTO proxies 
                        (ip, port, proxy_type, source, country, last_checked, is_working, response_time)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, data)
                    
                    if i % 5000 == 0 and i > 0:
                        logger.info(f"  📊 Processed {i} proxies...")
                
                conn.execute("COMMIT")
                logger.info("✅ Database batch insert completed")
        except Exception as e:
            logger.error(f"❌ Database insert failed: {e}")
            raise
    
    def get_working_proxies(self, limit=None, proxy_type=None):
        """Get working proxies sorted by speed"""
        try:
            query = """
                SELECT ip, port, proxy_type, source, country, last_checked, response_time
                FROM proxies 
                WHERE is_working = 1
            """
            params = []
            
            if proxy_type:
                query += " AND proxy_type = ?"
                params.append(proxy_type)
            
            query += " ORDER BY response_time ASC"
            
            if limit:
                query += " LIMIT ?"
                params.append(limit)
            
            with sqlite3.connect(self.db_path) as conn:
                results = conn.execute(query, params).fetchall()
                logger.info(f"📊 Retrieved {len(results)} working proxies from database")
                return results
        except Exception as e:
            logger.error(f"❌ Failed to get working proxies: {e}")
            return []
    
    def get_stats(self):
        """Get database statistics"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                total = conn.execute("SELECT COUNT(*) FROM proxies").fetchone()[0]
                working = conn.execute("SELECT COUNT(*) FROM proxies WHERE is_working = 1").fetchone()[0]
                countries = conn.execute("SELECT COUNT(DISTINCT country) FROM proxies WHERE country IS NOT NULL").fetchone()[0]
                
                # Get stats by type
                type_stats = {}
                for row in conn.execute("SELECT proxy_type, COUNT(*) FROM proxies WHERE is_working = 1 GROUP BY proxy_type"):
                    type_stats[row[0] or 'unknown'] = row[1]
                
            stats = {
                "total_proxies": total,
                "working_proxies": working,
                "countries": countries,
                "success_rate": round((working / total * 100) if total > 0 else 0, 2),
                "by_type": type_stats
            }
            logger.info(f"📊 Database stats: {stats}")
            return stats
        except Exception as e:
            logger.error(f"❌ Failed to get database stats: {e}")
            return {"total_proxies": 0, "working_proxies": 0, "countries": 0, "success_rate": 0, "by_type": {}}
    
    def compress_database(self):
        """Compress database to save space"""
        try:
            if os.path.exists(self.db_path):
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute("VACUUM")
                
                with open(self.db_path, 'rb') as f_in:
                    with gzip.open(f"{self.db_path}.gz", 'wb') as f_out:
                        f_out.writelines(f_in)
                
                os.remove(self.db_path)
                os.rename(f"{self.db_path}.gz", self.db_path)
                size_mb = os.path.getsize(self.db_path) / 1024 / 1024
                logger.info(f"🗜️ Database compressed: {size_mb:.1f} MB")
        except Exception as e:
            logger.error(f"❌ Database compression failed: {e}")

class DirectProxyDiscovery:
    """Direct proxy discovery from known sources"""
    
    def __init__(self, github_token=None):
        self.github_token = github_token
        self.session = None
        self.discovered_count = 0
        logger.info(f"🔧 DirectProxyDiscovery initialized")
    
    async def __aenter__(self):
        headers = {"User-Agent": "ProxyIntelligence/2.0"}
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        self.session = aiohttp.ClientSession(headers=headers, timeout=timeout)
        logger.info("🌐 HTTP session created")
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
            logger.info("🔌 HTTP session closed")
    
    async def discover_all_proxies(self):
        """Discover proxies from all known sources"""
        logger.info(f"🔍 Starting discovery from {len(PROXY_SOURCES)} sources")
        
        all_proxies = []
        
        for i, source in enumerate(PROXY_SOURCES):
            logger.info(f"📡 Source {i+1}/{len(PROXY_SOURCES)}: {source['name']}")
            
            try:
                if source['url'] == 'github_search':
                    # Use GitHub search as backup
                    if self.github_token:
                        proxies = await self._github_search_backup()
                    else:
                        logger.warning("⚠️ Skipping GitHub search - no token provided")
                        continue
                else:
                    # Direct URL fetch
                    proxies = await self._fetch_direct_source(source)
                
                all_proxies.extend(proxies)
                logger.info(f"  ✅ {source['name']}: {len(proxies)} proxies")
                
                # Small delay between sources
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"  ❌ {source['name']} failed: {e}")
                continue
        
        # Remove duplicates
        logger.info("🔄 Removing duplicates...")
        unique_proxies = {}
        for proxy in all_proxies:
            key = f"{proxy['ip']}:{proxy['port']}"
            if key not in unique_proxies:
                unique_proxies[key] = proxy
        
        result = list(unique_proxies.values())
        logger.info(f"✅ Discovery complete: {len(result)} unique proxies found (from {len(all_proxies)} total)")
        return result
    
    async def _fetch_direct_source(self, source):
        """Fetch proxies from a direct URL source"""
        try:
            logger.info(f"  🌐 Fetching: {source['url']}")
            
            async with self.session.get(source['url']) as response:
                if response.status != 200:
                    logger.warning(f"  ⚠️ HTTP {response.status} for {source['name']}")
                    return []
                
                content = await response.text()
                logger.info(f"  📄 Downloaded {len(content)} bytes")
                
                proxies = self._parse_proxy_content(content, source)
                logger.info(f"  ✅ Parsed {len(proxies)} proxies")
                
                return proxies
                
        except Exception as e:
            logger.error(f"  ❌ Error fetching {source['name']}: {e}")
            return []
    
    async def _github_search_backup(self):
        """Backup GitHub search method"""
        logger.info("  🔍 Running GitHub search backup")
        
        headers = {"Authorization": f"Bearer {self.github_token}"}
        search_url = "https://api.github.com/search/code"
        
        queries = ["proxy list filetype:txt", "free proxies"]
        all_proxies = []
        
        for query in queries:
            try:
                params = {"q": query, "per_page": 10}
                
                async with self.session.get(search_url, params=params, headers=headers) as response:
                    if response.status == 403:
                        logger.warning("  ⚠️ GitHub rate limit hit")
                        break
                    
                    if response.status != 200:
                        continue
                    
                    data = await response.json()
                    items = data.get("items", [])
                    
                    for item in items[:5]:  # Limit items
                        file_proxies = await self._extract_from_github_file(item)
                        all_proxies.extend(file_proxies)
                
                await asyncio.sleep(2)  # Rate limiting
                
            except Exception as e:
                logger.error(f"  ❌ GitHub search error: {e}")
                continue
        
        return all_proxies
    
    async def _extract_from_github_file(self, item):
        """Extract proxies from GitHub file"""
        try:
            html_url = item.get("html_url", "")
            raw_url = html_url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
            
            async with self.session.get(raw_url) as response:
                if response.status != 200:
                    return []
                
                content = await response.text()
                if len(content) > 500000:  # Skip large files
                    return []
                
                source_info = {
                    "name": f"GitHub: {item.get('repository', {}).get('full_name', 'unknown')}",
                    "url": raw_url,
                    "type": "mixed"
                }
                
                return self._parse_proxy_content(content, source_info)
        
        except Exception as e:
            return []
    
    def _parse_proxy_content(self, content, source):
        """Parse proxy content from any source"""
        proxies = []
        lines = content.splitlines()
        
        logger.info(f"    📝 Parsing {len(lines)} lines from {source['name']}")
        
        for line in lines:
            line = line.strip()
            
            # Skip comments and empty lines
            if not line or line.startswith(('#', '//', ';', '!')):
                continue
            
            # Look for IP:port pattern
            if ':' in line and '.' in line:
                try:
                    # Handle different formats
                    if '|' in line:
                        # Format: IP:PORT|country|etc
                        parts = line.split('|')
                        ip_port = parts[0].strip()
                    elif '\t' in line:
                        # Tab separated
                        ip_port = line.split('\t')[0].strip()
                    elif ' ' in line:
                        # Space separated
                        ip_port = line.split(' ')[0].strip()
                    else:
                        # Just IP:PORT
                        ip_port = line
                    
                    if ':' in ip_port:
                        ip, port_str = ip_port.split(':', 1)
                        port = int(port_str)
                        
                        if self._is_valid_ip(ip) and 1 <= port <= 65535:
                            proxies.append({
                                'ip': ip,
                                'port': port,
                                'proxy_type': source['type'],
                                'source': source['name']
                            })
                            
                except (ValueError, IndexError):
                    continue
        
        logger.info(f"    ✅ Found {len(proxies)} valid proxies")
        return proxies
    
    def _is_valid_ip(self, ip):
        """Validate IP address"""
        try:
            parts = ip.split('.')
            return len(parts) == 4 and all(0 <= int(part) <= 255 for part in parts)
        except:
            return False

class ProxyValidator:
    """High-speed proxy validation"""
    
    def __init__(self, max_concurrent=50, timeout=5.0):
        self.max_concurrent = max_concurrent
        self.timeout = timeout
        self.semaphore = asyncio.Semaphore(max_concurrent)
        logger.info(f"⚡ ProxyValidator initialized: {max_concurrent} concurrent, {timeout}s timeout")
    
    async def validate_batch(self, proxies):
        """Validate proxies in batches"""
        if not proxies:
            logger.warning("⚠️ No proxies to validate")
            return []
            
        logger.info(f"🔍 Validating {len(proxies)} proxies")
        
        # Create tasks for validation
        tasks = [self._validate_single(proxy) for proxy in proxies]
        
        # Process in chunks to avoid overwhelming the system
        chunk_size = 500
        all_results = []
        
        for i in range(0, len(tasks), chunk_size):
            chunk = tasks[i:i + chunk_size]
            logger.info(f"  🔄 Processing validation chunk {i//chunk_size + 1}")
            
            results = await asyncio.gather(*chunk, return_exceptions=True)
            all_results.extend(results)
        
        # Filter successful validations
        validated = []
        errors = 0
        
        for result in all_results:
            if isinstance(result, dict):
                if result.get('is_working'):
                    validated.append(result)
            else:
                errors += 1
        
        logger.info(f"✅ Validation complete: {len(validated)}/{len(proxies)} working ({errors} errors)")
        return validated
    
    async def _validate_single(self, proxy):
        """Validate single proxy"""
        async with self.semaphore:
            start_time = time.time()
            
            try:
                # Try HTTP validation first (works for most proxy types)
                proxy_url = f"http://{proxy['ip']}:{proxy['port']}"
                timeout = aiohttp.ClientTimeout(total=self.timeout)
                
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    test_urls = [
                        "http://httpbin.org/ip",
                        "http://icanhazip.com",
                        "http://ipecho.net/plain"
                    ]
                    
                    for test_url in test_urls:
                        try:
                            async with session.get(test_url, proxy=proxy_url) as response:
                                if response.status == 200:
                                    response_time = (time.time() - start_time) * 1000
                                    proxy.update({
                                        'is_working': True,
                                        'response_time': round(response_time, 2),
                                        'last_checked': datetime.now(timezone.utc).isoformat(),
                                        'country': 'Unknown'
                                    })
                                    return proxy
                        except:
                            continue
                            
            except Exception:
                pass
            
            # Mark as non-working
            proxy.update({
                'is_working': False,
                'last_checked': datetime.now(timezone.utc).isoformat()
            })
            return proxy

async def export_files(db, output_dir="docs"):
    """Export proxy files for GitHub Pages"""
    logger.info(f"📤 Starting export to {output_dir}")
    
    try:
        os.makedirs(output_dir, exist_ok=True)
        
        # Get working proxies by type
        all_working = db.get_working_proxies(limit=10000)
        stats = db.get_stats()
        
        logger.info(f"📊 Exporting {len(all_working)} working proxies")
        
        # Export main proxy list (all types)
        txt_path = Path(output_dir) / "proxies.txt"
        async with aiofiles.open(txt_path, 'w') as f:
            await f.write(f"# Proxy List - {datetime.now(timezone.utc).isoformat()}\n")
            await f.write(f"# Working proxies: {stats['working_proxies']}\n")
            await f.write(f"# Success rate: {stats['success_rate']}%\n")
            await f.write("# Format: IP:PORT\n\n")
            
            for proxy in all_working:
                await f.write(f"{proxy[0]}:{proxy[1]}\n")
        
        # Export by proxy type
        for proxy_type in ['http', 'https', 'socks4', 'socks5']:
            type_proxies = db.get_working_proxies(proxy_type=proxy_type)
            if type_proxies:
                type_path = Path(output_dir) / f"proxies_{proxy_type}.txt"
                async with aiofiles.open(type_path, 'w') as f:
                    await f.write(f"# {proxy_type.upper()} Proxy List\n")
                    await f.write(f"# Generated: {datetime.now(timezone.utc).isoformat()}\n")
                    await f.write(f"# Count: {len(type_proxies)}\n\n")
                    
                    for proxy in type_proxies:
                        await f.write(f"{proxy[0]}:{proxy[1]}\n")
        
        logger.info(f"✅ TXT exports complete")
        
        # Export JSON with detailed info
        json_data = {
            "metadata": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total_working": len(all_working),
                "database_stats": stats,
                "version": "2.0"
            },
            "proxies": [
                {
                    "ip": p[0],
                    "port": p[1],
                    "type": p[2],
                    "source": p[3],
                    "country": p[4],
                    "response_time_ms": p[6],
                    "last_checked": p[5]
                }
                for p in all_working
            ]
        }
        
        json_path = Path(output_dir) / "proxies.json"
        async with aiofiles.open(json_path, 'w') as f:
            await f.write(json.dumps(json_data, indent=2))
        
        # Export stats
        stats_path = Path(output_dir) / "stats.json"
        async with aiofiles.open(stats_path, 'w') as f:
            await f.write(json.dumps(stats, indent=2))
        
        # Create dashboard
        await create_dashboard(stats, output_dir)
        
        logger.info(f"🎉 Export completed: {len(all_working)} proxies exported")
        return len(all_working)
        
    except Exception as e:
        logger.error(f"❌ Export failed: {e}")
        raise

async def create_dashboard(stats, output_dir):
    """Create enhanced HTML dashboard"""
    logger.info("🎨 Creating enhanced dashboard")
    
    try:
        # Create download links for different types
        type_links = ""
        for proxy_type, count in stats.get('by_type', {}).items():
            if count > 0:
                type_links += f'<a href="proxies_{proxy_type}.txt" class="btn type-btn">{proxy_type.upper()} ({count:,})</a>\n        '
        
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Proxy Intelligence Dashboard</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 2rem;
            border-radius: 10px;
            text-align: center;
            margin-bottom: 2rem;
        }}
        .stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }}
        .stat {{
            background: white;
            padding: 1.5rem;
            border-radius: 8px;
            text-align: center;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        .stat-number {{
            font-size: 2rem;
            font-weight: bold;
            color: #667eea;
        }}
        .downloads {{
            background: white;
            padding: 2rem;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            margin-bottom: 2rem;
        }}
        .btn {{
            display: inline-block;
            background: #28a745;
            color: white;
            padding: 12px 24px;
            text-decoration: none;
            border-radius: 6px;
            margin: 5px;
            font-weight: 500;
        }}
        .btn:hover {{
            background: #218838;
        }}
        .type-btn {{
            background: #007bff;
        }}
        .type-btn:hover {{
            background: #0056b3;
        }}
        .type-stats {{
            background: white;
            padding: 2rem;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            margin-bottom: 2rem;
        }}
        .type-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 1rem;
        }}
        .type-card {{
            background: #f8f9fa;
            padding: 1rem;
            border-radius: 6px;
            text-align: center;
        }}
        .footer {{
            text-align: center;
            margin-top: 2rem;
            color: #666;
            font-size: 0.9rem;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Proxy Intelligence Dashboard</h1>
        <p>Direct source proxy discovery and validation</p>
    </div>
    
    <div class="stats">
        <div class="stat">
            <div class="stat-number">{stats['working_proxies']:,}</div>
            <div>Working Proxies</div>
        </div>
        <div class="stat">
            <div class="stat-number">{stats['total_proxies']:,}</div>
            <div>Total Discovered</div>
        </div>
        <div class="stat">
            <div class="stat-number">{stats['success_rate']}%</div>
            <div>Success Rate</div>
        </div>
        <div class="stat">
            <div class="stat-number">{stats['countries']}</div>
            <div>Countries</div>
        </div>
    </div>
    
    <div class="type-stats">
        <h2>Proxies by Type</h2>
        <div class="type-grid">"""
        
        for proxy_type, count in stats.get('by_type', {}).items():
            html += f"""
            <div class="type-card">
                <div class="stat-number">{count:,}</div>
                <div>{proxy_type.upper()}</div>
            </div>"""
        
        html += f"""
        </div>
    </div>
    
    <div class="downloads">
        <h2>Download Proxy Lists</h2>
        <p><strong>All Proxies:</strong></p>
        <a href="proxies.txt" class="btn">All Proxies (TXT)</a>
        <a href="proxies.json" class="btn">JSON Format</a>
        <a href="stats.json" class="btn">Statistics</a>
        
        <p><strong>By Type:</strong></p>
        {type_links}
        
        <p><em>Updated automatically every 8 hours from reliable sources.</em></p>
    </div>
    
    <div class="footer">
        <p>Last updated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}</p>
        <p>Sources: r00tee, VMHeaven, GitHub repositories</p>
        <p>Optimized for GitHub Actions free tier</p>
    </div>
</body>
</html>"""
        
        html_path = Path(output_dir) / "index.html"
        async with aiofiles.open(html_path, 'w') as f:
            await f.write(html)
        
        logger.info("✅ Enhanced dashboard created successfully")
        
    except Exception as e:
        logger.error(f"❌ Dashboard creation failed: {e}")
        raise

async def main():
    """Main execution function"""
    start_time = time.time()
    logger.info("🚀 Starting Direct Proxy Intelligence System")
    
    # Configuration
    github_token = os.getenv("GITHUB_TOKEN")
    max_concurrent = int(os.getenv("MAX_CONCURRENT", "50"))
    
    logger.info(f"🔧 Configuration:")
    logger.info(f"  - GitHub Token: {'✅ Set' if github_token else '❌ Missing'}")
    logger.info(f"  - Max Concurrent: {max_concurrent}")
    logger.info(f"  - Direct Sources: {len([s for s in PROXY_SOURCES if s['url'] != 'github_search'])}")
    
    try:
        # Initialize database
        logger.info("🗄️ Initializing database...")
        db = ProxyDatabase()
        
        # Discover proxies from direct sources
        logger.info("🔍 Starting direct proxy discovery...")
        async with DirectProxyDiscovery(github_token) as discovery:
            proxies = await discovery.discover_all_proxies()
        
        if not proxies:
            logger.error("❌ No proxies discovered from any source!")
            logger.error("This could be due to:")
            logger.error("  - Network connectivity issues")
            logger.error("  - Source websites being down")
            logger.error("  - Content format changes")
            
            # Create minimal fallback
            logger.info("🔄 Creating fallback export...")
            await export_files(db)
            return
        
        logger.info(f"✅ Total proxies discovered: {len(proxies)}")
        
        # Validate proxies in batches
        logger.info("🔍 Starting proxy validation...")
        validator = ProxyValidator(max_concurrent=max_concurrent)
        
        batch_size = 2000
        all_validated = []
        
        for i in range(0, len(proxies), batch_size):
            batch = proxies[i:i + batch_size]
            batch_num = i//batch_size + 1
            total_batches = (len(proxies)-1)//batch_size + 1
            
            logger.info(f"🔄 Validating batch {batch_num}/{total_batches} ({len(batch)} proxies)")
            
            validated = await validator.validate_batch(batch)
            all_validated.extend(validated)
            
            # Add to database (both working and non-working for statistics)
            db.add_proxies_batch(batch)
            
            # Memory monitoring
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            logger.info(f"💾 Memory usage: {memory_mb:.1f} MB")
            
            # Give system a breather between large batches
            if len(batch) >= 1000:
                await asyncio.sleep(2)
        
        # Export results
        logger.info("📤 Exporting results...")
        exported_count = await export_files(db)
        
        # Compress database
        logger.info("🗜️ Compressing database...")
        db.compress_database()
        
        # Final statistics
        stats = db.get_stats()
        execution_time = time.time() - start_time
        
        logger.info("=" * 70)
        logger.info("🎉 EXECUTION SUMMARY")
        logger.info("=" * 70)
        logger.info(f"⏱️  Execution time: {execution_time:.1f} seconds")
        logger.info(f"🔍 Total discovered: {stats['total_proxies']:,}")
        logger.info(f"✅ Working proxies: {stats['working_proxies']:,}")
        logger.info(f"📊 Success rate: {stats['success_rate']}%")
        logger.info(f"📤 Exported: {exported_count:,}")
        logger.info(f"🌍 Countries: {stats['countries']}")
        
        # Show breakdown by type
        logger.info("📋 Breakdown by type:")
        for proxy_type, count in stats.get('by_type', {}).items():
            logger.info(f"  - {proxy_type.upper()}: {count:,}")
        
        # GitHub Actions output
        if os.getenv("GITHUB_ACTIONS"):
            try:
                with open(os.getenv("GITHUB_OUTPUT", "/dev/stdout"), "a") as f:
                    f.write(f"working_proxies={stats['working_proxies']}\n")
                    f.write(f"total_proxies={stats['total_proxies']}\n")
                    f.write(f"success_rate={stats['success_rate']}\n")
                    f.write(f"execution_time={execution_time:.1f}\n")
            except Exception as e:
                logger.warning(f"⚠️ Failed to write GitHub Actions output: {e}")
        
        logger.info("🚀 Direct proxy discovery completed successfully!")
        
        # Performance summary
        proxies_per_second = len(proxies) / execution_time if execution_time > 0 else 0
        logger.info(f"⚡ Performance: {proxies_per_second:.1f} proxies discovered per second")
        
    except Exception as e:
        logger.error(f"❌ System failed with error: {e}")
        logger.error("Full traceback:", exc_info=True)
        
        # Try to create minimal export even on failure
        try:
            logger.info("🔄 Creating minimal emergency export...")
            db = ProxyDatabase()
            await export_files(db)
        except:
            pass
        
        raise

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⏹️  Process interrupted by user")
    except Exception as e:
        logger.error(f"💥 Unexpected error: {e}")
        sys.exit(1)
