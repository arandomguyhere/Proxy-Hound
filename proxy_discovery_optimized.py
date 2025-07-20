#!/usr/bin/env python3
"""
Repository-First Proxy Discovery System
1. Search GitHub repositories for proxy projects (like your URL)
2. Then scrape all proxy files from those repositories
3. Add direct sources as backup
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

# Direct proxy sources as backup
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
                
                # Check current schema
                cursor = conn.execute("PRAGMA table_info(proxies)")
                columns = [row[1] for row in cursor.fetchall()]
                
                if not columns:
                    # Create new table
                    logger.info("📝 Creating new proxy table...")
                    self._create_new_table(conn)
                else:
                    # Migrate if needed
                    if 'proxy_type' not in columns:
                        logger.info("🔄 Migrating database schema...")
                        self._migrate_database(conn)
                    else:
                        logger.info("✅ Database schema is current")
                
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
                repository TEXT,
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
        try:
            conn.execute("ALTER TABLE proxies ADD COLUMN proxy_type TEXT")
            logger.info("  ✅ Added proxy_type column")
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e):
                pass
        
        try:
            conn.execute("ALTER TABLE proxies ADD COLUMN repository TEXT")
            logger.info("  ✅ Added repository column")
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e):
                pass
    
    def _create_indexes(self, conn):
        """Create performance indexes"""
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_ip_port ON proxies(ip, port)",
            "CREATE INDEX IF NOT EXISTS idx_working ON proxies(is_working)",
            "CREATE INDEX IF NOT EXISTS idx_last_checked ON proxies(last_checked)"
        ]
        
        # Check which columns exist
        cursor = conn.execute("PRAGMA table_info(proxies)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'proxy_type' in columns:
            indexes.append("CREATE INDEX IF NOT EXISTS idx_proxy_type ON proxies(proxy_type)")
        if 'repository' in columns:
            indexes.append("CREATE INDEX IF NOT EXISTS idx_repository ON proxies(repository)")
        
        for index_sql in indexes:
            try:
                conn.execute(index_sql)
            except sqlite3.OperationalError:
                pass
    
    def add_proxies_batch(self, proxies, batch_size=1000):
        """Add proxies with backward compatibility"""
        if not proxies:
            return
            
        logger.info(f"📝 Adding {len(proxies)} proxies to database")
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                # Check available columns
                cursor = conn.execute("PRAGMA table_info(proxies)")
                columns = [row[1] for row in cursor.fetchall()]
                
                has_proxy_type = 'proxy_type' in columns
                has_repository = 'repository' in columns
                
                conn.execute("BEGIN TRANSACTION")
                
                for i in range(0, len(proxies), batch_size):
                    batch = proxies[i:i + batch_size]
                    
                    if has_proxy_type and has_repository:
                        # Full new schema
                        data = [
                            (p['ip'], p['port'], p.get('proxy_type'), p['source'], 
                             p.get('repository'), p.get('country'), p.get('last_checked'), 
                             p.get('is_working', False), p.get('response_time'))
                            for p in batch
                        ]
                        conn.executemany("""
                            INSERT OR REPLACE INTO proxies 
                            (ip, port, proxy_type, source, repository, country, last_checked, is_working, response_time)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, data)
                    elif has_proxy_type:
                        # Partial new schema
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
                        # Old schema
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
        """Get working proxies"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("PRAGMA table_info(proxies)")
                columns = [row[1] for row in cursor.fetchall()]
                
                if 'repository' in columns:
                    query = """
                        SELECT ip, port, proxy_type, source, repository, country, last_checked, response_time
                        FROM proxies WHERE is_working = 1 ORDER BY response_time ASC
                    """
                elif 'proxy_type' in columns:
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
                
                try:
                    countries = conn.execute("SELECT COUNT(DISTINCT country) FROM proxies WHERE country IS NOT NULL").fetchone()[0]
                except:
                    countries = 0
                
                # Repository stats
                repo_stats = {}
                try:
                    cursor = conn.execute("PRAGMA table_info(proxies)")
                    columns = [row[1] for row in cursor.fetchall()]
                    if 'repository' in columns:
                        for row in conn.execute("SELECT repository, COUNT(*) FROM proxies WHERE is_working = 1 AND repository IS NOT NULL GROUP BY repository ORDER BY COUNT(*) DESC LIMIT 10"):
                            repo_stats[row[0]] = row[1]
                except:
                    pass
                
                # Type stats
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
                    "by_type": type_stats,
                    "by_repository": repo_stats
                }
                logger.info(f"📊 Database stats: {stats}")
                return stats
        except Exception as e:
            logger.error(f"❌ Failed to get database stats: {e}")
            return {"total_proxies": 0, "working_proxies": 0, "countries": 0, "success_rate": 0, "by_type": {}, "by_repository": {}}
    
    def compress_database(self):
        """Compress database"""
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

class RepositoryFirstDiscovery:
    """Repository-first discovery strategy"""
    
    def __init__(self, github_token=None):
        self.github_token = github_token
        self.session = None
        self.discovered_count = 0
        logger.info(f"🔧 Repository-first discovery initialized")
    
    async def __aenter__(self):
        headers = {"User-Agent": "ProxyIntelligence/3.0"}
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
        """Repository-first discovery strategy"""
        logger.info(f"🔍 Starting repository-first discovery")
        
        all_proxies = []
        
        # Phase 1: Search repositories first (like your URL)
        if self.github_token:
            logger.info("🏢 Phase 1: Repository discovery")
            repo_proxies = await self._discover_proxy_repositories(max_pages)
            all_proxies.extend(repo_proxies)
            logger.info(f"  ✅ Repository search: {len(repo_proxies)} proxies")
        else:
            logger.warning("⚠️ No GitHub token - skipping repository search")
        
        # Phase 2: Direct sources backup
        logger.info("📡 Phase 2: Direct sources backup")
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
    
    async def _discover_proxy_repositories(self, max_pages):
        """Step 1: Find proxy repositories (like https://github.com/search?q=free+proxies&type=repositories)"""
        logger.info("🔍 Step 1: Searching for proxy repositories")
        
        # Repository search queries (what you want)
        repo_queries = [
            "free proxies",
            "proxy list", 
            "socks proxy",
            "http proxy",
            "working proxies",
            "proxy server",
            "free proxy list",
            "proxy collection"
        ]
        
        discovered_repositories = set()
        all_proxies = []
        
        for i, query in enumerate(repo_queries):
            logger.info(f"🔎 Repository query {i+1}/{len(repo_queries)}: '{query}'")
            
            try:
                repositories = await self._search_repositories(query, max_pages)
                logger.info(f"  📋 Found {len(repositories)} repositories")
                
                # Step 2: Scrape all proxy files from each repository
                for repo in repositories:
                    if repo['full_name'] not in discovered_repositories:
                        discovered_repositories.add(repo['full_name'])
                        logger.info(f"  📁 Scraping repository: {repo['full_name']}")
                        
                        repo_proxies = await self._scrape_repository_files(repo)
                        all_proxies.extend(repo_proxies)
                        logger.info(f"    ✅ Extracted {len(repo_proxies)} proxies from {repo['full_name']}")
                        
                        # Small delay between repositories
                        await asyncio.sleep(1)
                
                # Rate limiting between queries
                await asyncio.sleep(3)
                
            except Exception as e:
                logger.error(f"  ❌ Repository query failed: {e}")
                continue
        
        logger.info(f"✅ Repository discovery complete: {len(discovered_repositories)} repos, {len(all_proxies)} proxies")
        return all_proxies
    
    async def _search_repositories(self, query, max_pages):
        """Search GitHub repositories (not code files)"""
        repositories = []
        
        for page in range(1, max_pages + 1):
            try:
                url = "https://api.github.com/search/repositories"
                params = {
                    "q": query,
                    "sort": "updated",  # Most recently updated first
                    "order": "desc",
                    "page": page,
                    "per_page": 30
                }
                
                logger.info(f"    📡 Repository search: page {page}")
                
                async with self.session.get(url, params=params) as response:
                    logger.info(f"      📊 Response: {response.status}")
                    
                    if response.status == 403:
                        logger.warning("      ⚠️ Rate limit hit")
                        break
                    
                    if response.status != 200:
                        logger.warning(f"      ⚠️ Unexpected status: {response.status}")
                        continue
                    
                    data = await response.json()
                    items = data.get("items", [])
                    total_count = data.get("total_count", 0)
                    
                    logger.info(f"      📋 Found {len(items)} repositories (total: {total_count})")
                    
                    if not items:
                        break
                    
                    repositories.extend(items)
                
                # Rate limiting
                await asyncio.sleep(2)
                
            except Exception as e:
                logger.error(f"    ❌ Repository search error: {e}")
                continue
        
        return repositories
    
    async def _scrape_repository_files(self, repository):
        """Step 2: Scrape all proxy files from a repository"""
        repo_name = repository['full_name']
        proxies = []
        
        try:
            # Get repository contents
            contents_url = f"https://api.github.com/repos/{repo_name}/contents"
            
            async with self.session.get(contents_url) as response:
                if response.status != 200:
                    logger.warning(f"      ⚠️ Failed to get contents: {response.status}")
                    return []
                
                contents = await response.json()
                
                # Look for proxy files
                proxy_files = []
                for item in contents:
                    if item['type'] == 'file':
                        filename = item['name'].lower()
                        # Check if it's likely a proxy file
                        if any(keyword in filename for keyword in ['proxy', 'socks', 'http', '.txt', '.json']):
                            proxy_files.append(item)
                
                logger.info(f"      📄 Found {len(proxy_files)} potential proxy files")
                
                # Extract proxies from each file
                for file_item in proxy_files[:10]:  # Limit files per repo
                    logger.info(f"        📝 Processing: {file_item['name']}")
                    file_proxies = await self._extract_from_repository_file(file_item, repo_name)
                    proxies.extend(file_proxies)
                    logger.info(f"          ✅ Extracted {len(file_proxies)} proxies")
                    
                    # Small delay between files
                    await asyncio.sleep(0.5)
        
        except Exception as e:
            logger.error(f"      ❌ Repository scraping error: {e}")
        
        return proxies
    
    async def _extract_from_repository_file(self, file_item, repo_name):
        """Extract proxies from a repository file"""
        try:
            download_url = file_item.get('download_url')
            if not download_url:
                return []
            
            async with self.session.get(download_url) as response:
                if response.status != 200:
                    return []
                
                content = await response.text()
                
                # Skip very large files
                if len(content) > 1000000:  # 1MB limit
                    logger.warning(f"          ⚠️ File too large: {len(content)} bytes")
                    return []
                
                # Determine proxy type
                proxy_type = self._guess_proxy_type(download_url, file_item['name'])
                
                proxies = self._parse_proxy_content(content, repo_name, proxy_type)
                return proxies
        
        except Exception as e:
            logger.warning(f"          ❌ File extraction error: {e}")
            return []
    
    async def _fetch_direct_sources(self):
        """Fetch from direct sources as backup"""
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
                    repo_name = url.split('/')[-2]
                    
                    proxies = self._parse_proxy_content(content, repo_name, proxy_type)
                    all_proxies.extend(proxies)
                    logger.info(f"    ✅ Fetched {len(proxies)} proxies")
                
                await asyncio.sleep(1)
                
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
    
    def _parse_proxy_content(self, content, repository, proxy_type):
        """Parse proxy content"""
        proxies = []
        lines = content.splitlines()
        
        for line in lines:
            line = line.strip()
            
            # Skip comments and empty lines
            if not line or line.startswith(('#', '//', ';', '!')):
                continue
            
            if ':' in line and '.' in line:
                try:
                    # Handle different formats
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
                                'source': f"repository:{repository}",
                                'repository': repository
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
        
        # Process in chunks
        chunk_size = 1000
        all_results = []
        
        for i in range(0, len(proxies), chunk_size):
            chunk = proxies[i:i + chunk_size]
            logger.info(f"  🔄 Chunk {i//chunk_size + 1}: {len(chunk)} proxies")
            
            tasks = [self._validate_single(proxy) for proxy in chunk]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            all_results.extend(results)
        
        validated = [r for r in all_results if isinstance(r, dict) and r.get('is_working')]
        logger.info(f"✅ Validation complete: {len(validated)}/{len(proxies)} working")
        
        return all_results
    
    async def _validate_single(self, proxy):
        """Validate single proxy"""
        async with self.semaphore:
            start_time = time.time()
            
            try:
                proxy_url = f"http://{proxy['ip']}:{proxy['port']}"
                timeout = aiohttp.ClientTimeout(total=self.timeout)
                
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    test_urls = ["http://httpbin.org/ip", "http://icanhazip.com"]
                    
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
            await f.write("# Discovered using repository-first strategy\n")
            await f.write("# Format: IP:PORT\n\n")
            
            for proxy in working_proxies:
                await f.write(f"{proxy[0]}:{proxy[1]}\n")
        
        # Export JSON with repository info
        json_data = {
            "metadata": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total_working": len(working_proxies),
                "database_stats": stats,
                "discovery_method": "repository-first"
            },
            "proxies": []
        }
        
        # Build JSON with available fields
        for p in working_proxies:
            proxy_data = {
                "ip": p[0],
                "port": p[1]
            }
            
            # Add fields based on available columns
            if len(p) > 2:
                proxy_data["type"] = p[2]
            if len(p) > 3:
                proxy_data["source"] = p[3]
            if len(p) > 4:
                proxy_data["repository"] = p[4]
            if len(p) > 7:
                proxy_data["response_time_ms"] = p[7]
            
            json_data["proxies"].append(proxy_data)
        
        json_path = Path(output_dir) / "proxies.json"
        async with aiofiles.open(json_path, 'w') as f:
            await f.write(json.dumps(json_data, indent=2))
        
        # Export stats
        stats_path = Path(output_dir) / "stats.json"
        async with aiofiles.open(stats_path, 'w') as f:
            await f.write(json.dumps(stats, indent=2))
        
        # Create enhanced dashboard
        await create_dashboard(stats, output_dir)
        
        logger.info(f"✅ Export complete: {len(working_proxies)} proxies")
        return len(working_proxies)
        
    except Exception as e:
        logger.error(f"❌ Export failed: {e}")
        raise

async def create_dashboard(stats, output_dir):
    """Create enhanced dashboard with repository info"""
    
    # Build repository section
    repo_section = ""
    if stats.get('by_repository'):
        repo_section = """
    <div class="repositories">
        <h2>Top Proxy Repositories</h2>
        <div class="repo-grid">"""
        
        for repo, count in list(stats['by_repository'].items())[:10]:
            repo_section += f"""
            <div class="repo-card">
                <div class="repo-name">{repo}</div>
                <div class="repo-count">{count:,} proxies</div>
            </div>"""
        
        repo_section += """
        </div>
    </div>"""
    
    # Build type section
    type_section = ""
    if stats.get('by_type'):
        type_section = """
        <div class="type-stats">
            <h2>Proxies by Type</h2>
            <div class="type-grid">"""
        
        for proxy_type, count in stats['by_type'].items():
            type_section += f"""
            <div class="type-card">
                <div class="stat-number">{count:,}</div>
                <div>{proxy_type.upper()}</div>
            </div>"""
        
        type_section += """
            </div>
        </div>"""
    
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
        .repositories, .type-stats {{
            background: white;
            padding: 2rem;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            margin-bottom: 2rem;
        }}
        .repo-grid, .type-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 1rem;
        }}
        .repo-card {{
            background: #f8f9fa;
            padding: 1rem;
            border-radius: 6px;
            border-left: 4px solid #667eea;
        }}
        .repo-name {{
            font-weight: bold;
            color: #333;
            margin-bottom: 0.5rem;
        }}
        .repo-count {{
            color: #666;
            font-size: 0.9rem;
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
        .strategy-info {{
            background: #e7f3ff;
            padding: 1rem;
            border-radius: 6px;
            margin-bottom: 2rem;
            border-left: 4px solid #007bff;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Proxy Intelligence Dashboard</h1>
        <p>Repository-First Discovery Strategy</p>
    </div>
    
    <div class="strategy-info">
        <h3>🔍 Discovery Method: Repository-First</h3>
        <p>This system searches GitHub repositories first (like github.com/search?q=free+proxies&type=repositories), 
        then scrapes all proxy files from those repositories. This approach discovers fresher, 
        more comprehensive proxy lists compared to random file searching.</p>
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
            <div class="stat-number">{len(stats.get('by_repository', {}))}</div>
            <div>Repositories</div>
        </div>
    </div>
    
    {type_section}
    
    {repo_section}
    
    <div class="downloads">
        <h2>📥 Download Proxy Lists</h2>
        <p>Fresh proxies discovered from active GitHub repositories:</p>
        <a href="proxies.txt" class="btn">📄 Text Format</a>
        <a href="proxies.json" class="btn">📊 JSON Format</a>
        <a href="stats.json" class="btn">📈 Statistics</a>
        <p><em>Updated automatically every 8 hours using repository-first discovery.</em></p>
    </div>
    
    <div class="footer">
        <p>Last updated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}</p>
        <p>🏢 Repository-first discovery finds fresher proxy sources</p>
        <p>📡 Backup sources: r00tee, VMHeaven repositories</p>
    </div>
</body>
</html>"""
    
    html_path = Path(output_dir) / "index.html"
    async with aiofiles.open(html_path, 'w') as f:
        await f.write(html)

async def main():
    """Main execution with repository-first strategy"""
    start_time = time.time()
    logger.info("🚀 Starting Repository-First Proxy Discovery")
    
    # Configuration
    github_token = os.getenv("GITHUB_TOKEN")
    max_pages = int(os.getenv("MAX_PAGES", "3"))
    max_concurrent = int(os.getenv("MAX_CONCURRENT", "50"))
    
    logger.info(f"🔧 Configuration:")
    logger.info(f"  - GitHub Token: {'✅ Set' if github_token else '❌ Missing'}")
    logger.info(f"  - Max Pages per query: {max_pages}")
    logger.info(f"  - Max Concurrent: {max_concurrent}")
    logger.info(f"  - Strategy: Repository-first discovery")
    
    try:
        # Initialize database with migration
        logger.info("🗄️ Initializing database...")
        db = ProxyDatabase()
        
        # Repository-first discovery
        logger.info("🔍 Starting repository-first discovery...")
        async with RepositoryFirstDiscovery(github_token) as discovery:
            proxies = await discovery.discover_all_proxies(max_pages)
        
        if not proxies:
            logger.error("❌ No proxies discovered!")
            await export_files(db)
            return
        
        logger.info(f"✅ Total proxies discovered: {len(proxies)}")
        
        # Validate proxies
        logger.info("🔍 Starting validation...")
        validator = ProxyValidator(max_concurrent=max_concurrent)
        
        # Process in large batches for efficiency
        batch_size = 5000
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
            
            # Memory monitoring
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            logger.info(f"💾 Memory: {memory_mb:.1f} MB")
            
            # Brief pause between large batches
            if len(batch) >= 2000:
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
        logger.info("🎉 REPOSITORY-FIRST DISCOVERY SUMMARY")
        logger.info("=" * 70)
        logger.info(f"⏱️  Execution time: {execution_time:.1f} seconds")
        logger.info(f"🔍 Total discovered: {stats['total_proxies']:,}")
        logger.info(f"✅ Working proxies: {stats['working_proxies']:,}")
        logger.info(f"📊 Success rate: {stats['success_rate']}%")
        logger.info(f"📤 Exported: {exported_count:,}")
        logger.info(f"🏢 Repositories found: {len(stats.get('by_repository', {}))}")
        
        # Show top repositories
        if stats.get('by_repository'):
            logger.info("🏆 Top proxy repositories:")
            for repo, count in list(stats['by_repository'].items())[:5]:
                logger.info(f"  - {repo}: {count:,} working proxies")
        
        # Show breakdown by type
        if stats.get('by_type'):
            logger.info("📋 Breakdown by type:")
            for proxy_type, count in stats['by_type'].items():
                logger.info(f"  - {proxy_type.upper()}: {count:,}")
        
        # GitHub Actions output
        if os.getenv("GITHUB_ACTIONS"):
            try:
                with open(os.getenv("GITHUB_OUTPUT", "/dev/stdout"), "a") as f:
                    f.write(f"working_proxies={stats['working_proxies']}\n")
                    f.write(f"total_proxies={stats['total_proxies']}\n")
                    f.write(f"success_rate={stats['success_rate']}\n")
                    f.write(f"repositories_found={len(stats.get('by_repository', {}))}\n")
            except Exception as e:
                logger.warning(f"⚠️ GitHub Actions output failed: {e}")
        
        logger.info("🚀 Repository-first discovery completed successfully!")
        
        # Performance summary
        repos_per_minute = len(stats.get('by_repository', {})) * 60 / execution_time if execution_time > 0 else 0
        proxies_per_second = len(proxies) / execution_time if execution_time > 0 else 0
        logger.info(f"⚡ Performance: {repos_per_minute:.1f} repos/min, {proxies_per_second:.1f} proxies/sec")
        
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
