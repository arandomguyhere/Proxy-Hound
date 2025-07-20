#!/usr/bin/env python3
"""
Complete Optimized Proxy Discovery System
Designed for 1M+ proxies on GitHub Actions Free Tier
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

class ProxyDatabase:
    """Optimized database for millions of proxies"""
    
    def __init__(self, db_path="proxies.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Initialize optimized database"""
        with sqlite3.connect(self.db_path) as conn:
            # Performance optimizations
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL") 
            conn.execute("PRAGMA cache_size=10000")
            conn.execute("PRAGMA temp_store=MEMORY")
            
            # Create optimized table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS proxies (
                    id INTEGER PRIMARY KEY,
                    ip TEXT NOT NULL,
                    port INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    country TEXT,
                    last_checked TEXT,
                    is_working BOOLEAN DEFAULT 0,
                    response_time REAL,
                    first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(ip, port)
                )
            """)
            
            # Performance indexes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ip_port ON proxies(ip, port)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_working ON proxies(is_working)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_last_checked ON proxies(last_checked)")
            
    def add_proxies_batch(self, proxies, batch_size=1000):
        """Add proxies in optimized batches"""
        logger.info(f"Adding {len(proxies)} proxies to database")
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("BEGIN TRANSACTION")
            
            for i in range(0, len(proxies), batch_size):
                batch = proxies[i:i + batch_size]
                data = [
                    (p['ip'], p['port'], p['source'], p.get('country'), 
                     p.get('last_checked'), p.get('is_working', False), 
                     p.get('response_time'))
                    for p in batch
                ]
                
                conn.executemany("""
                    INSERT OR REPLACE INTO proxies 
                    (ip, port, source, country, last_checked, is_working, response_time)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, data)
                
                if i % 5000 == 0 and i > 0:
                    logger.info(f"Processed {i} proxies...")
            
            conn.execute("COMMIT")
    
    def get_working_proxies(self, limit=None):
        """Get working proxies sorted by speed"""
        query = """
            SELECT ip, port, source, country, last_checked, response_time
            FROM proxies 
            WHERE is_working = 1 
            ORDER BY response_time ASC
        """
        if limit:
            query += f" LIMIT {limit}"
        
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute(query).fetchall()
    
    def get_stats(self):
        """Get database statistics"""
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM proxies").fetchone()[0]
            working = conn.execute("SELECT COUNT(*) FROM proxies WHERE is_working = 1").fetchone()[0]
            countries = conn.execute("SELECT COUNT(DISTINCT country) FROM proxies WHERE country IS NOT NULL").fetchone()[0]
            
        return {
            "total_proxies": total,
            "working_proxies": working,
            "countries": countries,
            "success_rate": round((working / total * 100) if total > 0 else 0, 2)
        }
    
    def compress_database(self):
        """Compress database to save space"""
        if os.path.exists(self.db_path):
            # Vacuum to optimize
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("VACUUM")
            
            # Compress with gzip
            with open(self.db_path, 'rb') as f_in:
                with gzip.open(f"{self.db_path}.gz", 'wb') as f_out:
                    f_out.writelines(f_in)
            
            # Replace with compressed version
            os.remove(self.db_path)
            os.rename(f"{self.db_path}.gz", self.db_path)
            logger.info(f"Database compressed: {os.path.getsize(self.db_path) / 1024 / 1024:.1f} MB")

class ProxyDiscovery:
    """Memory-efficient proxy discovery"""
    
    def __init__(self, github_token=None):
        self.github_token = github_token
        self.session = None
        self.discovered_count = 0
    
    async def __aenter__(self):
        headers = {"User-Agent": "ProxyIntelligence/1.0"}
        if self.github_token:
            headers["Authorization"] = f"Bearer {self.github_token}"
        
        timeout = aiohttp.ClientTimeout(total=30)
        self.session = aiohttp.ClientSession(headers=headers, timeout=timeout)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def discover_github_proxies(self, max_pages=3):
        """Discover proxies from GitHub repositories"""
        logger.info(f"Starting GitHub discovery (max {max_pages} pages)")
        
        queries = [
            "proxy list filetype:txt",
            "socks proxy filetype:txt",
            "http proxy servers", 
            "proxy.txt",
            "proxies.txt"
        ]
        
        all_proxies = []
        
        for query in queries:
            proxies = await self._search_query(query, max_pages)
            all_proxies.extend(proxies)
            logger.info(f"Query '{query}': found {len(proxies)} proxies")
            
            if len(all_proxies) > 50000:  # Limit for memory
                logger.info(f"Reached proxy limit, stopping discovery")
                break
        
        # Remove duplicates
        unique_proxies = {}
        for proxy in all_proxies:
            key = f"{proxy['ip']}:{proxy['port']}"
            if key not in unique_proxies:
                unique_proxies[key] = proxy
        
        result = list(unique_proxies.values())
        logger.info(f"Discovery complete: {len(result)} unique proxies found")
        return result
    
    async def _search_query(self, query, max_pages):
        """Search GitHub with specific query"""
        proxies = []
        
        for page in range(1, max_pages + 1):
            try:
                url = "https://api.github.com/search/code"
                params = {"q": query, "page": page, "per_page": 20}
                
                async with self.session.get(url, params=params) as response:
                    if response.status == 403:
                        logger.warning("GitHub rate limit hit")
                        break
                    
                    if response.status != 200:
                        continue
                    
                    data = await response.json()
                    items = data.get("items", [])
                    
                    if not items:
                        break
                    
                    # Process files
                    for item in items[:10]:  # Limit files per page
                        file_proxies = await self._extract_from_file(item)
                        proxies.extend(file_proxies)
                
                await asyncio.sleep(2)  # Rate limiting
                
            except Exception as e:
                logger.error(f"Search error: {e}")
                continue
        
        return proxies
    
    async def _extract_from_file(self, item):
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
                
                return self._parse_content(content, item.get('repository', {}).get('full_name', 'unknown'))
        
        except Exception as e:
            logger.debug(f"File extraction error: {e}")
            return []
    
    def _parse_content(self, content, source):
        """Parse proxy content efficiently"""
        proxies = []
        
        for line in content.splitlines()[:5000]:  # Limit lines
            line = line.strip()
            
            if not line or line.startswith(('#', '//', ';')):
                continue
            
            if ':' in line and '.' in line:
                try:
                    parts = line.split(':')
                    if len(parts) >= 2:
                        ip = parts[0].strip()
                        port = int(parts[1].strip())
                        
                        if self._is_valid_ip(ip) and 1 <= port <= 65535:
                            proxies.append({
                                'ip': ip,
                                'port': port,
                                'source': f"github:{source}"
                            })
                except (ValueError, IndexError):
                    continue
        
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
    
    async def validate_batch(self, proxies):
        """Validate proxies in batches"""
        logger.info(f"Validating {len(proxies)} proxies")
        
        tasks = [self._validate_single(proxy) for proxy in proxies]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        validated = [r for r in results if isinstance(r, dict) and r.get('is_working')]
        logger.info(f"Validation complete: {len(validated)}/{len(proxies)} working")
        
        return validated
    
    async def _validate_single(self, proxy):
        """Validate single proxy"""
        async with self.semaphore:
            start_time = time.time()
            
            try:
                proxy_url = f"http://{proxy['ip']}:{proxy['port']}"
                timeout = aiohttp.ClientTimeout(total=self.timeout)
                
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get("http://httpbin.org/ip", proxy=proxy_url) as response:
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
                pass
            
            proxy.update({
                'is_working': False,
                'last_checked': datetime.now(timezone.utc).isoformat()
            })
            return proxy

async def export_files(db, output_dir="docs"):
    """Export proxy files for GitHub Pages"""
    os.makedirs(output_dir, exist_ok=True)
    
    working_proxies = db.get_working_proxies(limit=10000)  # Limit for GitHub Pages
    stats = db.get_stats()
    
    logger.info(f"Exporting {len(working_proxies)} working proxies")
    
    # Export TXT format
    txt_path = Path(output_dir) / "proxies.txt"
    async with aiofiles.open(txt_path, 'w') as f:
        await f.write(f"# Proxy List - {datetime.now(timezone.utc).isoformat()}\n")
        await f.write(f"# Working proxies: {stats['working_proxies']}\n")
        await f.write(f"# Success rate: {stats['success_rate']}%\n")
        await f.write("# Format: IP:PORT\n\n")
        
        for proxy in working_proxies:
            await f.write(f"{proxy[0]}:{proxy[1]}\n")
    
    # Export JSON format
    json_data = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_proxies": len(working_proxies),
            "database_stats": stats,
            "version": "1.0"
        },
        "proxies": [
            {
                "ip": p[0],
                "port": p[1],
                "country": p[3],
                "response_time_ms": p[5],
                "source": p[2],
                "last_checked": p[4]
            }
            for p in working_proxies
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
    
    return len(working_proxies)

async def create_dashboard(stats, output_dir):
    """Create HTML dashboard"""
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Proxy Intelligence Dashboard</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            max-width: 1000px;
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
        }}
        .btn:hover {{
            background: #218838;
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
        <h1>🔍 Proxy Intelligence Dashboard</h1>
        <p>Automated proxy discovery and validation system</p>
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
    
    <div class="downloads">
        <h2>📥 Download Proxy Lists</h2>
        <p>Choose your preferred format:</p>
        <a href="proxies.txt" class="btn">📄 Text Format</a>
        <a href="proxies.json" class="btn">📊 JSON Format</a>
        <a href="stats.json" class="btn">📈 Statistics</a>
        <p><strong>Note:</strong> Limited to top 10,000 fastest proxies for optimal performance.</p>
    </div>
    
    <div class="footer">
        <p>Last updated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}</p>
        <p>🤖 Automatically updated every 8 hours via GitHub Actions</p>
        <p>⚡ Optimized for GitHub Actions free tier</p>
    </div>
</body>
</html>"""
    
    html_path = Path(output_dir) / "index.html"
    async with aiofiles.open(html_path, 'w') as f:
        await f.write(html)

async def main():
    """Main execution function"""
    start_time = time.time()
    logger.info("🚀 Starting Proxy Intelligence System")
    
    # Configuration
    github_token = os.getenv("PROXY_GITHUB_TOKEN")
    max_pages = int(os.getenv("MAX_PAGES", "3"))
    max_concurrent = int(os.getenv("MAX_CONCURRENT", "50"))
    
    if not github_token:
        logger.warning("⚠️  GITHUB_TOKEN not found - limited API access")
    
    try:
        # Initialize database
        db = ProxyDatabase()
        
        # Discover proxies
        logger.info("🔍 Starting proxy discovery...")
        async with ProxyDiscovery(github_token) as discovery:
            proxies = await discovery.discover_github_proxies(max_pages)
        
        if not proxies:
            logger.error("❌ No proxies discovered")
            return
        
        # Validate proxies in batches
        logger.info("✅ Starting proxy validation...")
        validator = ProxyValidator(max_concurrent=max_concurrent)
        
        batch_size = 2000
        all_validated = []
        
        for i in range(0, len(proxies), batch_size):
            batch = proxies[i:i + batch_size]
            logger.info(f"Validating batch {i//batch_size + 1}/{(len(proxies)-1)//batch_size + 1}")
            
            validated = await validator.validate_batch(batch)
            all_validated.extend(validated)
            
            # Add to database
            db.add_proxies_batch(batch)
            
            # Memory cleanup
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            logger.info(f"Memory usage: {memory_mb:.1f} MB")
        
        # Export results
        logger.info("📤 Exporting results...")
        exported_count = await export_files(db)
        
        # Compress database
        db.compress_database()
        
        # Final statistics
        stats = db.get_stats()
        execution_time = time.time() - start_time
        
        logger.info("=" * 50)
        logger.info("🎉 EXECUTION SUMMARY")
        logger.info("=" * 50)
        logger.info(f"⏱️  Execution time: {execution_time:.1f} seconds")
        logger.info(f"🔍 Total discovered: {stats['total_proxies']:,}")
        logger.info(f"✅ Working proxies: {stats['working_proxies']:,}")
        logger.info(f"📊 Success rate: {stats['success_rate']}%")
        logger.info(f"📤 Exported: {exported_count:,}")
        logger.info(f"🌍 Countries: {stats['countries']}")
        
        # GitHub Actions output
        if os.getenv("GITHUB_ACTIONS"):
            with open(os.getenv("GITHUB_OUTPUT", "/dev/stdout"), "a") as f:
                f.write(f"working_proxies={stats['working_proxies']}\n")
                f.write(f"total_proxies={stats['total_proxies']}\n")
                f.write(f"success_rate={stats['success_rate']}\n")
        
        logger.info("🚀 System completed successfully!")
        
    except Exception as e:
        logger.error(f"❌ System failed: {e}")
        raise

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⏹️  Process interrupted")
    except Exception as e:
        logger.error(f"💥 Unexpected error: {e}")
        sys.exit(1)
