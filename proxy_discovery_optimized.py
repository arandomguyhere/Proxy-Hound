#!/usr/bin/env python3
"""
Enhanced Proxy Discovery System
Combines GitHub search with direct sources + database migration
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

# Direct proxy sources (as backup)
DIRECT_SOURCES = [
    "https://raw.githubusercontent.com/r00tee/Proxy-List/main/Https.txt",
    "https://raw.githubusercontent.com/r00tee/Proxy-List/main/Socks4.txt", 
    "https://raw.githubusercontent.com/r00tee/Proxy-List/main/Socks5.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/http.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/https.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/socks4.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/socks5.txt"
]

class ProxyDatabase:
    """Database with automatic migration support"""
    
    def __init__(self, db_path="proxies.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Initialize database with migration support"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL") 
                conn.execute("PRAGMA cache_size=10000")
                conn.execute("PRAGMA temp_store=MEMORY")
                
                # Check if table exists and get current schema
                cursor = conn.execute("PRAGMA table_info(proxies)")
                columns = [row[1] for row in cursor.fetchall()]
                
                if not columns:
                    # Create new table
                    logger.info("📝 Creating new proxy table...")
                    self._create_new_table(conn)
                else:
                    # Check if we need to migrate
                    if 'proxy_type' not in columns:
                        logger.info("🔄 Migrating database schema...")
                        self._migrate_database(conn)
                    else:
                        logger.info("✅ Database schema is current")
                
                # Create/update indexes
                self._create_indexes(conn)
                
            logger.info("✅ Database initialized successfully")
        except Exception as e:
            logger.error(f"❌ Database initialization failed: {e}")
            raise
    
    def _create_new_table(self, conn):
        """Create new table with current schema"""
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
    
    def _migrate_database(self, conn):
        """Migrate old database to new schema"""
        # Add proxy_type column if it doesn't exist
        try:
            conn.execute("ALTER TABLE proxies ADD COLUMN proxy_type TEXT")
            logger.info("  ✅ Added proxy_type column")
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e):
                raise
    
    def _create_indexes(self, conn):
        """Create performance indexes"""
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_ip_port ON proxies(ip, port)",
            "CREATE INDEX IF NOT EXISTS idx_working ON proxies(is_working)",
            "CREATE INDEX IF NOT EXISTS idx_last_checked ON proxies(last_checked)"
        ]
        
        # Only create proxy_type index if column exists
        cursor = conn.execute("PRAGMA table_info(proxies)")
        columns = [row[1] for row in cursor.fetchall()]
        if 'proxy_type' in columns:
            indexes.append("CREATE INDEX IF NOT EXISTS idx_proxy_type ON proxies(proxy_type)")
        
        for index_sql in indexes:
            try:
                conn.execute(index_sql)
            except sqlite3.OperationalError:
                pass  # Index might already exist
    
    def add_proxies_batch(self, proxies, batch_size=1000):
        """Add proxies with backward compatibility"""
        if not proxies:
            return
            
        logger.info(f"📝 Adding {len(proxies)} proxies to database")
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                # Check if proxy_type column exists
                cursor = conn.execute("PRAGMA table_info(proxies)")
                columns = [row[1] for row in cursor.fetchall()]
                has_proxy_type = 'proxy_type' in columns
                
                conn.execute("BEGIN TRANSACTION")
                
                for i in range(0, len(proxies), batch_size):
                    batch = proxies[i:i + batch_size]
                    
                    if has_proxy_type:
                        # New schema with proxy_type
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
                    else:
                        # Old schema without proxy_type
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
                
                conn.execute("COMMIT")
                logger.info("✅ Database batch insert completed")
        except Exception as e:
            logger.error(f"❌ Database insert failed: {e}")
            raise
    
    def get_working_proxies(self, limit=None):
        """Get working proxies with backward compatibility"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                # Check available columns
                cursor = conn.execute("PRAGMA table_info(proxies)")
                columns = [row[1] for row in cursor.fetchall()]
                
                if 'proxy_type' in columns:
                    query = """
                        SELECT ip, port, proxy_type, source, country, last_checked, response_time
                        FROM proxies WHERE is_working = 1 ORDER BY response_time ASC
                    """
                else:
                    query = """
                        SELECT ip, port, source, country, last_checked, response_time
                        FROM proxies WHERE is_working = 1 ORDER BY response_time ASC
                    """
                
                if limit:
                    query += f" LIMIT {limit}"
                
                results = conn.execute(query).fetchall()
                logger.info(f"📊 Retrieved {len(results)} working proxies")
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
                
                # Try to get countries
                try:
                    countries = conn.execute("SELECT COUNT(DISTINCT country) FROM proxies WHERE country IS NOT NULL").fetchone()[0]
                except:
                    countries = 0
                
                # Try to get type stats if column exists
                type_stats = {}
                try:
                    cursor = conn.execute("PRAGMA table_info(proxies)")
                    columns = [row[1] for row in cursor.fetchall()]
                    if 'proxy_type' in columns:
                        for row in conn.execute("SELECT proxy_type, COUNT(*) FROM proxies WHERE is_working = 1 GROUP BY proxy_type"):
                            type_stats[row[0] or 'unknown'] = row[1]
                except:
                    pass
                
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

class EnhancedProxyDiscovery:
    """Enhanced discovery with GitHub search + direct sources"""
    
    def __init__(self, github_token=None):
        self.github_token = github_token
        self.session = None
        self.discovered_count = 0
        logger.info(f"🔧 Enhanced discovery initialized with token: {bool(github_token)}")
    
    async def __aenter__(self):
        headers = {"User-Agent": "ProxyIntelligence/2.0"}
        if self.github_token:
            headers["Authorization"] = f"Bearer {self.github_token}"
            logger.info(f"🔑 GitHub token configured: {self.github_token[:10]}...")
        
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        self.session = aiohttp.ClientSession(headers=headers, timeout=timeout)
        logger.info("🌐 HTTP session created")
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
            logger.info("🔌 HTTP session closed")
    
    async def discover_all_proxies(self, max_pages=3):
        """Enhanced discovery: GitHub search + direct sources"""
        logger.info(f"🔍 Starting enhanced discovery (GitHub + Direct sources)")
        
        all_proxies = []
        
        # Primary: GitHub search for fresh results
        if self.github_token:
            logger.info("🔎 Phase 1: GitHub repository search")
            github_proxies = await self._github_comprehensive_search(max_pages)
            all_proxies.extend(github_proxies)
            logger.info(f"  ✅ GitHub search: {len(github_proxies)} proxies")
        else:
            logger.warning("⚠️ No GitHub token - skipping GitHub search")
        
        # Backup: Direct sources
        logger.info("📡 Phase 2: Direct source backup")
        direct_proxies = await self._fetch_direct_sources()
        all_proxies.extend(direct_proxies)
        logger.info(f"  ✅ Direct sources: {len(direct_proxies)} proxies")
        
        # Remove duplicates
        logger.info("🔄 Removing duplicates...")
        unique_proxies = {}
        for proxy in all_proxies:
            key = f"{proxy['ip']}:{proxy['port']}"
            if key not in unique_proxies:
                unique_proxies[key] = proxy
        
        result = list(unique_proxies.values())
        logger.info(f"✅ Discovery complete: {len(result)} unique proxies (from {len(all_proxies)} total)")
        return result
    
    async def _github_comprehensive_search(self, max_pages):
        """Comprehensive GitHub search for proxy repositories"""
        logger.info("🔍 Starting comprehensive GitHub search")
        
        # Enhanced search queries
        search_queries = [
            "proxy list filetype:txt",
            "free proxies filetype:txt",
            "socks proxy filetype:txt", 
            "http proxy filetype:txt",
            "proxy.txt",
            "proxies.txt",
            "proxy servers",
            "working proxies",
            "proxy list updated",
            "free proxy list"
        ]
        
        all_proxies = []
        
        for i, query in enumerate(search_queries):
            logger.info(f"🔎 Query {i+1}/{len(search_queries)}: '{query}'")
            
            try:
                proxies = await self._search_github_repositories(query, max_pages)
                all_proxies.extend(proxies)
                logger.info(f"  ✅ Found {len(proxies)} proxies")
                
                # Rate limiting
                await asyncio.sleep(3)
                
                # Stop if we have enough proxies
                if len(all_proxies) > 100000:
                    logger.info("⚠️ Reached 100k proxy limit")
                    break
                    
            except Exception as e:
                logger.error(f"  ❌ Query failed: {e}")
                continue
        
        logger.info(f"✅ GitHub search complete: {len(all_proxies)} total proxies")
        return all_proxies
    
    async def _search_github_repositories(self, query, max_pages):
        """Search GitHub repositories for proxy files"""
        proxies = []
        
        for page in range(1, max_pages + 1):
            try:
                url = "https://api.github.com/search/code"
                params = {
                    "q": query,
                    "page": page,
                    "per_page": 30,  # Increased for more results
                    "sort": "indexed"  # Get recently indexed content
                }
                
                logger.info(f"    📡 GitHub API request: page {page}")
                
                async with self.session.get(url, params=params) as response:
                    logger.info(f"      📊 Response: {response.status}")
                    
                    if response.status == 403:
                        logger.warning("      ⚠️ Rate limit hit")
                        break
                    
                    if response.status == 422:
                        logger.warning(f"      ⚠️ Invalid query: {query}")
                        break
                    
                    if response.status != 200:
                        logger.warning(f"      ⚠️ Unexpected status: {response.status}")
                        continue
                    
                    data = await response.json()
                    items = data.get("items", [])
                    total_count = data.get("total_count", 0)
                    
                    logger.info(f"      📋 Found {len(items)} files (total: {total_count})")
                    
                    if not items:
                        break
                    
                    # Process each file
                    for j, item in enumerate(items):
                        logger.info(f"        📄 File {j+1}: {item.get('name', 'unknown')}")
                        file_proxies = await self._extract_from_github_file(item)
                        proxies.extend(file_proxies)
                        logger.info(f"          ✅ Extracted {len(file_proxies)} proxies")
                        
                        # Small delay between files
                        await asyncio.sleep(0.5)
                
                # Rate limiting between pages
                await asyncio.sleep(2)
                
            except Exception as e:
                logger.error(f"    ❌ Page {page} error: {e}")
                continue
        
        return proxies
    
    async def _extract_from_github_file(self, item):
        """Extract proxies from GitHub file"""
        try:
            html_url = item.get("html_url", "")
            if not html_url:
                return []
            
            # Convert to raw URL
            raw_url = html_url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
            
            async with self.session.get(raw_url) as response:
                if response.status != 200:
                    logger.warning(f"          ⚠️ Failed to fetch: {response.status}")
                    return []
                
                content = await response.text()
                
                # Skip very large files
                if len(content) > 1000000:  # 1MB limit
                    logger.warning(f"          ⚠️ File too large: {len(content)} bytes")
                    return []
                
                # Determine proxy type from URL/filename
                proxy_type = self._guess_proxy_type(raw_url, item.get('name', ''))
                
                source_name = f"github:{item.get('repository', {}).get('full_name', 'unknown')}"
                
                proxies = self._parse_proxy_content(content, source_name, proxy_type)
                return proxies
        
        except Exception as e:
            logger.warning(f"          ❌ Extraction error: {e}")
            return []
    
    async def _fetch_direct_sources(self):
        """Fetch from direct proxy sources as backup"""
        logger.info("📡 Fetching from direct sources")
        
        all_proxies = []
        
        for i, url in enumerate(DIRECT_SOURCES):
            logger.info(f"  📄 Source {i+1}/{len(DIRECT_SOURCES)}: {url.split('/')[-1]}")
            
            try:
                async with self.session.get(url) as response:
                    if response.status != 200:
                        logger.warning(f"    ⚠️ Failed: {response.status}")
                        continue
                    
                    content = await response.text()
                    proxy_type = self._guess_proxy_type(url, url.split('/')[-1])
                    source_name = f"direct:{url.split('/')[-2]}"
                    
                    proxies = self._parse_proxy_content(content, source_name, proxy_type)
                    all_proxies.extend(proxies)
                    logger.info(f"    ✅ Fetched {len(proxies)} proxies")
                
                await asyncio.sleep(1)  # Rate limiting
                
            except Exception as e:
                logger.error(f"    ❌ Error: {e}")
                continue
        
        return all_proxies
    
    def _guess_proxy_type(self, url, filename):
        """Guess proxy type from URL or filename"""
        url_lower = url.lower()
        filename_lower = filename.lower()
        
        if 'socks5' in url_lower or 'socks5' in filename_lower:
            return 'socks5'
        elif 'socks4' in url_lower or 'socks4' in filename_lower:
            return 'socks4'
        elif 'https' in url_lower or 'https' in filename_lower:
            return 'https'
        elif 'http' in url_lower or 'http' in filename_lower:
            return 'http'
        else:
            return 'mixed'
    
    def _parse_proxy_content(self, content, source, proxy_type):
        """Parse proxy content from any source"""
        proxies = []
        lines = content.splitlines()
        
        for line in lines:
            line = line.strip()
            
            # Skip comments and empty lines
            if not line or line.startswith(('#', '//', ';', '!')):
                continue
            
            # Various formats handling
            if ':' in line and '.' in line:
                try:
                    # Handle different separators
                    for separator in ['|', '\t', ' ', ',']:
                        if separator in line:
                            line = line.split(separator)[0].strip()
                            break
                    
                    if ':' in line:
                        ip, port_str = line.split(':', 1)
                        port = int(port_str)
                        
                        if self._is_valid_ip(ip) and 1 <= port <= 65535:
                            proxies.append({
                                'ip': ip,
                                'port': port,
                                'proxy_type': proxy_type,
                                'source': source
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
        logger.info(f"⚡ Validator: {max_concurrent} concurrent, {timeout}s timeout")
    
    async def validate_batch(self, proxies):
        """Validate proxies efficiently"""
        if not proxies:
            return []
            
        logger.info(f"🔍 Validating {len(proxies)} proxies")
        
        # Process in chunks to manage memory
        chunk_size = 1000
        all_results = []
        
        for i in range(0, len(proxies), chunk_size):
            chunk = proxies[i:i + chunk_size]
            logger.info(f"  🔄 Chunk {i//chunk_size + 1}: {len(chunk)} proxies")
            
            tasks = [self._validate_single(proxy) for proxy in chunk]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            all_results.extend(results)
        
        # Count results
        validated = [r for r in all_results if isinstance(r, dict) and r.get('is_working')]
        logger.info(f"✅ Validation complete: {len(validated)}/{len(proxies)} working")
        
        return all_results  # Return all for database storage
    
    async def _validate_single(self, proxy):
        """Validate single proxy"""
        async with self.semaphore:
            start_time = time.time()
            
            try:
                proxy_url = f"http://{proxy['ip']}:{proxy['port']}"
                timeout = aiohttp.ClientTimeout(total=self.timeout)
                
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    # Try multiple test endpoints
                    test_urls = [
                        "http://httpbin.org/ip",
                        "http://icanhazip.com"
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
            
            proxy.update({
                'is_working': False,
                'last_checked': datetime.now(timezone.utc).isoformat()
            })
            return proxy

async def export_files(db, output_dir="docs"):
    """Export proxy files"""
    logger.info(f"📤 Exporting to {output_dir}")
    
    try:
        os.makedirs(output_dir, exist_ok=True)
        
        working_proxies = db.get_working_proxies(limit=10000)
        stats = db.get_stats()
        
        logger.info(f"📊 Exporting {len(working_proxies)} working proxies")
        
        # Export main list
        txt_path = Path(output_dir) / "proxies.txt"
        async with aiofiles.open(txt_path, 'w') as f:
            await f.write(f"# Proxy List - {datetime.now(timezone.utc).isoformat()}\n")
            await f.write(f"# Working proxies: {stats['working_proxies']}\n")
            await f.write(f"# Success rate: {stats['success_rate']}%\n")
            await f.write("# Format: IP:PORT\n\n")
            
            for proxy in working_proxies:
                await f.write(f"{proxy[0]}:{proxy[1]}\n")
        
        # Export JSON
        json_data = {
            "metadata": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total_working": len(working_proxies),
                "database_stats": stats
            },
            "proxies": [
                {
                    "ip": p[0],
                    "port": p[1],
                    "source": p[3] if len(p) > 3 else "unknown",
                    "response_time_ms": p[-1] if len(p) > 6 else None
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
        
        logger.info(f"✅ Export complete: {len(working_proxies)} proxies")
        return len(working_proxies)
        
    except Exception as e:
        logger.error(f"❌ Export failed: {e}")
        raise

async def create_dashboard(stats, output_dir):
    """Create dashboard"""
    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Proxy Intelligence Dashboard</title>
    <style>
        body {{ font-family: Arial, sans-serif; max-width: 1000px; margin: 0 auto; padding: 20px; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 2rem; border-radius: 10px; text-align: center; margin-bottom: 2rem; }}
        .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 2rem; }}
        .stat {{ background: white; padding: 1.5rem; border-radius: 8px; text-align: center; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        .stat-number {{ font-size: 2rem; font-weight: bold; color: #667eea; }}
        .downloads {{ background: white; padding: 2rem; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        .btn {{ display: inline-block; background: #28a745; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; margin: 5px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Proxy Intelligence Dashboard</h1>
        <p>Enhanced GitHub + Direct Source Discovery</p>
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
        <h2>Download Proxy Lists</h2>
        <a href="proxies.txt" class="btn">Text Format</a>
        <a href="proxies.json" class="btn">JSON Format</a>
        <a href="stats.json" class="btn">Statistics</a>
    </div>
</body>
</html>"""
    
    html_path = Path(output_dir) / "index.html"
    async with aiofiles.open(html_path, 'w') as f:
        await f.write(html)

async def main():
    """Main execution function"""
    start_time = time.time()
    logger.info("🚀 Starting Enhanced Proxy Intelligence System")
    
    # Configuration
    github_token = os.getenv("GITHUB_TOKEN")
    max_pages = int(os.getenv("MAX_PAGES", "3"))
    max_concurrent = int(os.getenv("MAX_CONCURRENT", "50"))
    
    logger.info(f"🔧 Configuration:")
    logger.info(f"  - GitHub Token: {'✅ Set' if github_token else '❌ Missing'}")
    logger.info(f"  - Max Pages: {max_pages}")
    logger.info(f"  - Max Concurrent: {max_concurrent}")
    
    try:
        # Initialize database with migration
        logger.info("🗄️ Initializing database...")
        db = ProxyDatabase()
        
        # Enhanced discovery
        logger.info("🔍 Starting enhanced discovery...")
        async with EnhancedProxyDiscovery(github_token) as discovery:
            proxies = await discovery.discover_all_proxies(max_pages)
        
        if not proxies:
            logger.error("❌ No proxies discovered!")
            await export_files(db)
            return
        
        logger.info(f"✅ Total proxies discovered: {len(proxies)}")
        
        # Validate proxies
        logger.info("🔍 Starting validation...")
        validator = ProxyValidator(max_concurrent=max_concurrent)
        
        # Process in batches
        batch_size = 3000
        all_validated = []
        
        for i in range(0, len(proxies), batch_size):
            batch = proxies[i:i + batch_size]
            batch_num = i//batch_size + 1
            total_batches = (len(proxies)-1)//batch_size + 1
            
            logger.info(f"🔄 Batch {batch_num}/{total_batches}: {len(batch)} proxies")
            
            validated = await validator.validate_batch(batch)
            all_validated.extend(validated)
            
            # Add to database
            db.add_proxies_batch(validated)
            
            # Memory check
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            logger.info(f"💾 Memory: {memory_mb:.1f} MB")
        
        # Export results
        logger.info("📤 Exporting results...")
        exported_count = await export_files(db)
        
        # Compress database
        logger.info("🗜️ Compressing database...")
        db.compress_database()
        
        # Final statistics
        stats = db.get_stats()
        execution_time = time.time() - start_time
        
        logger.info("=" * 60)
        logger.info("🎉 EXECUTION SUMMARY")
        logger.info("=" * 60)
        logger.info(f"⏱️  Execution time: {execution_time:.1f} seconds")
        logger.info(f"🔍 Total discovered: {stats['total_proxies']:,}")
        logger.info(f"✅ Working proxies: {stats['working_proxies']:,}")
        logger.info(f"📊 Success rate: {stats['success_rate']}%")
        logger.info(f"📤 Exported: {exported_count:,}")
        logger.info(f"🌍 Countries: {stats['countries']}")
        
        # GitHub Actions output
        if os.getenv("GITHUB_ACTIONS"):
            try:
                with open(os.getenv("GITHUB_OUTPUT", "/dev/stdout"), "a") as f:
                    f.write(f"working_proxies={stats['working_proxies']}\n")
                    f.write(f"total_proxies={stats['total_proxies']}\n")
                    f.write(f"success_rate={stats['success_rate']}\n")
            except Exception as e:
                logger.warning(f"⚠️ GitHub Actions output failed: {e}")
        
        logger.info("🚀 Enhanced discovery completed successfully!")
        
    except Exception as e:
        logger.error(f"❌ System failed: {e}")
        logger.error("Full traceback:", exc_info=True)
        
        # Emergency export
        try:
            logger.info("🔄 Creating emergency export...")
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
        logger.info("⏹️  Process interrupted")
    except Exception as e:
        logger.error(f"💥 Unexpected error: {e}")
        sys.exit(1)
