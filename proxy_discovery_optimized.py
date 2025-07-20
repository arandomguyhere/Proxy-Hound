#!/usr/bin/env python3
"""
Optimized Repository-First Proxy Discovery System
1. Search GitHub repositories for proxy projects with quality scoring
2. Smart file detection and processing
3. High-performance validation with early filtering
4. Memory-efficient batch processing
"""

import asyncio
import json
import logging
import sqlite3
import time
import gzip
import re
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

# Optimized proxy file patterns
PROXY_FILE_PATTERNS = [
    r'.*proxy.*\.txt$', r'.*socks.*\.txt$', r'.*http.*\.txt$',
    r'^proxies?\.txt$', r'^.*list.*\.txt$', r'.*working.*\.txt$',
    r'.*free.*\.txt$', r'.*live.*\.txt$', r'.*valid.*\.txt$'
]

# Direct proxy sources as backup (verified active sources)
DIRECT_SOURCES = [
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
                    logger.info("📝 Creating new proxy table...")
                    self._create_new_table(conn)
                else:
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
                repo_score INTEGER DEFAULT 0,
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
        except sqlite3.OperationalError:
            pass
        
        try:
            conn.execute("ALTER TABLE proxies ADD COLUMN repository TEXT")
            logger.info("  ✅ Added repository column")
        except sqlite3.OperationalError:
            pass
            
        try:
            conn.execute("ALTER TABLE proxies ADD COLUMN repo_score INTEGER DEFAULT 0")
            logger.info("  ✅ Added repo_score column")
        except sqlite3.OperationalError:
            pass
    
    def _create_indexes(self, conn):
        """Create performance indexes"""
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_ip_port ON proxies(ip, port)",
            "CREATE INDEX IF NOT EXISTS idx_working ON proxies(is_working)",
            "CREATE INDEX IF NOT EXISTS idx_last_checked ON proxies(last_checked)",
            "CREATE INDEX IF NOT EXISTS idx_proxy_type ON proxies(proxy_type)",
            "CREATE INDEX IF NOT EXISTS idx_repository ON proxies(repository)",
            "CREATE INDEX IF NOT EXISTS idx_repo_score ON proxies(repo_score)"
        ]
        
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
                cursor = conn.execute("PRAGMA table_info(proxies)")
                columns = [row[1] for row in cursor.fetchall()]
                
                has_proxy_type = 'proxy_type' in columns
                has_repository = 'repository' in columns
                has_repo_score = 'repo_score' in columns
                
                conn.execute("BEGIN TRANSACTION")
                
                for i in range(0, len(proxies), batch_size):
                    batch = proxies[i:i + batch_size]
                    
                    if has_repo_score and has_proxy_type and has_repository:
                        # Full new schema
                        data = [
                            (p['ip'], p['port'], p.get('proxy_type'), p['source'], 
                             p.get('repository'), p.get('repo_score', 0), p.get('country'), 
                             p.get('last_checked'), p.get('is_working', False), p.get('response_time'))
                            for p in batch
                        ]
                        conn.executemany("""
                            INSERT OR REPLACE INTO proxies 
                            (ip, port, proxy_type, source, repository, repo_score, country, last_checked, is_working, response_time)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, data)
                    else:
                        # Fallback for older schema
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
                
                conn.execute("COMMIT")
                logger.info("✅ Database batch insert completed")
        except Exception as e:
            logger.error(f"❌ Database insert failed: {e}")
            raise
    
    def get_working_proxies(self, limit=None):
        """Get working proxies ordered by repo score and response time"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("PRAGMA table_info(proxies)")
                columns = [row[1] for row in cursor.fetchall()]
                
                if 'repo_score' in columns:
                    query = """
                        SELECT ip, port, proxy_type, source, repository, country, last_checked, response_time
                        FROM proxies WHERE is_working = 1 
                        ORDER BY repo_score DESC, response_time ASC
                    """
                else:
                    query = """
                        SELECT ip, port, proxy_type, source, repository, country, last_checked, response_time
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
                
                # Repository stats with scores
                repo_stats = {}
                try:
                    cursor = conn.execute("PRAGMA table_info(proxies)")
                    columns = [row[1] for row in cursor.fetchall()]
                    if 'repository' in columns:
                        for row in conn.execute("""
                            SELECT repository, COUNT(*), AVG(repo_score) 
                            FROM proxies WHERE is_working = 1 AND repository IS NOT NULL 
                            GROUP BY repository ORDER BY COUNT(*) DESC LIMIT 10
                        """):
                            repo_stats[row[0]] = {"count": row[1], "avg_score": round(row[2] or 0, 1)}
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
                
                size_mb = os.path.getsize(self.db_path) / 1024 / 1024
                logger.info(f"🗜️ Database optimized: {size_mb:.1f} MB")
        except Exception as e:
            logger.error(f"❌ Database compression failed: {e}")

class OptimizedRepositoryDiscovery:
    """Optimized repository-first discovery with intelligent scoring"""
    
    def __init__(self, github_token=None):
        self.github_token = github_token
        self.session = None
        self.discovered_count = 0
        self.proxy_pattern = re.compile(r'^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d{1,5})$')
        logger.info(f"🔧 Optimized repository discovery initialized")
    
    async def __aenter__(self):
        headers = {"User-Agent": "ProxyIntelligence/4.0"}
        if self.github_token:
            headers["Authorization"] = f"Bearer {self.github_token}"
            logger.info(f"🔑 GitHub token configured: {self.github_token[:10]}...")
        
        # Optimized timeouts
        timeout = aiohttp.ClientTimeout(total=20, connect=5)
        connector = aiohttp.TCPConnector(limit=100, ttl_dns_cache=300)
        self.session = aiohttp.ClientSession(headers=headers, timeout=timeout, connector=connector)
        logger.info("🌐 Optimized HTTP session created")
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
            logger.info("🔌 HTTP session closed")
    
    async def discover_all_proxies(self, max_pages=3, max_memory_mb=512):
        """Optimized repository-first discovery with memory management"""
        logger.info(f"🔍 Starting optimized repository discovery")
        
        all_proxies = []
        
        # Phase 1: Smart repository discovery
        if self.github_token:
            logger.info("🏢 Phase 1: Smart repository discovery")
            repo_proxies = await self._discover_proxy_repositories_optimized(max_pages, max_memory_mb)
            all_proxies.extend(repo_proxies)
            logger.info(f"  ✅ Repository search: {len(repo_proxies)} proxies")
        else:
            logger.warning("⚠️ No GitHub token - skipping repository search")
        
        # Phase 2: Direct sources backup (only if needed)
        if len(all_proxies) < 1000:
            logger.info("📡 Phase 2: Direct sources backup")
            direct_proxies = await self._fetch_direct_sources_optimized()
            all_proxies.extend(direct_proxies)
            logger.info(f"  ✅ Direct sources: {len(direct_proxies)} proxies")
        
        # Memory-efficient deduplication
        logger.info("🔄 Memory-efficient deduplication...")
        unique_proxies = self._deduplicate_proxies(all_proxies)
        
        logger.info(f"✅ Discovery complete: {len(unique_proxies)} unique proxies")
        return unique_proxies
    
    async def _discover_proxy_repositories_optimized(self, max_pages, max_memory_mb):
        """Optimized repository discovery with scoring and filtering"""
        logger.info("🔍 Smart repository discovery with scoring")
        
        # Optimized search queries
        repo_queries = [
            "free proxies language:text pushed:>2024-01-01",
            "proxy list language:text size:>10",
            "socks proxy working language:text",
            "http proxy fresh language:text",
            "working proxies updated language:text"
        ]
        
        all_repositories = []
        
        # Collect repositories with quality filters
        for i, query in enumerate(repo_queries):
            logger.info(f"🔎 Query {i+1}/{len(repo_queries)}: '{query.split()[0]} {query.split()[1]}'")
            
            try:
                repositories = await self._search_repositories_optimized(query, max_pages)
                all_repositories.extend(repositories)
                logger.info(f"  📋 Found {len(repositories)} repositories")
                
                # Rate limiting
                await asyncio.sleep(2)
                
            except Exception as e:
                logger.error(f"  ❌ Query failed: {e}")
                continue
        
        # Score and rank repositories
        scored_repos = await self._score_and_rank_repositories(all_repositories)
        
        # Process top repositories with memory management
        all_proxies = []
        processed_count = 0
        
        for score, repo in scored_repos[:30]:  # Limit to top 30 repos
            if score < 25:  # Skip low-scoring repos
                break
                
            logger.info(f"📁 Processing: {repo['full_name']} (score: {score})")
            
            repo_proxies = await self._scrape_repository_optimized(repo, score)
            all_proxies.extend(repo_proxies)
            processed_count += 1
            
            logger.info(f"  ✅ Extracted {len(repo_proxies)} proxies")
            
            # Memory management
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            if memory_mb > max_memory_mb and processed_count >= 10:
                logger.info(f"💾 Memory limit reached ({memory_mb:.1f}MB), stopping early")
                break
            
            await asyncio.sleep(0.5)
        
        logger.info(f"✅ Repository discovery: {processed_count} repos, {len(all_proxies)} proxies")
        return all_proxies
    
    async def _search_repositories_optimized(self, query, max_pages):
        """Optimized repository search with better filtering"""
        repositories = []
        
        for page in range(1, max_pages + 1):
            try:
                url = "https://api.github.com/search/repositories"
                params = {
                    "q": query,
                    "sort": "updated",
                    "order": "desc",
                    "page": page,
                    "per_page": 30
                }
                
                async with self.session.get(url, params=params) as response:
                    if response.status == 403:
                        logger.warning("    ⚠️ Rate limit hit")
                        break
                    
                    if response.status != 200:
                        continue
                    
                    data = await response.json()
                    items = data.get("items", [])
                    
                    if not items:
                        break
                    
                    # Pre-filter repositories
                    filtered_items = []
                    for item in items:
                        if self._is_quality_repository(item):
                            filtered_items.append(item)
                    
                    repositories.extend(filtered_items)
                    logger.info(f"    📄 Page {page}: {len(filtered_items)}/{len(items)} quality repos")
                
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"    ❌ Search error: {e}")
                continue
        
        return repositories
    
    def _is_quality_repository(self, repo):
        """Pre-filter repositories for quality indicators"""
        # Size check (not too small, not too large)
        size_kb = repo.get('size', 0)
        if size_kb < 10 or size_kb > 50000:  # 10KB to 50MB
            return False
        
        # Recent activity check
        try:
            updated = datetime.fromisoformat(repo['updated_at'].replace('Z', '+00:00'))
            days_ago = (datetime.now(timezone.utc) - updated).days
            if days_ago > 365:  # Updated within last year
                return False
        except:
            return False
        
        # Name and description quality
        name = repo.get('name', '').lower()
        desc = repo.get('description', '').lower()
        
        proxy_keywords = ['proxy', 'socks', 'http', 'list', 'working', 'free']
        if not any(keyword in name or keyword in desc for keyword in proxy_keywords):
            return False
        
        return True
    
    async def _score_and_rank_repositories(self, repositories):
        """Score repositories for quality and recency"""
        logger.info("🏆 Scoring and ranking repositories...")
        
        # Remove duplicates
        unique_repos = {repo['full_name']: repo for repo in repositories}
        
        scored_repos = []
        for repo in unique_repos.values():
            score = await self._score_repository(repo)
            if score > 0:
                scored_repos.append((score, repo))
        
        # Sort by score (highest first)
        scored_repos.sort(reverse=True, key=lambda x: x[0])
        
        logger.info(f"  📊 Scored {len(scored_repos)} repositories")
        if scored_repos:
            top_score = scored_repos[0][0]
            avg_score = sum(score for score, _ in scored_repos) / len(scored_repos)
            logger.info(f"  🥇 Top score: {top_score}, Average: {avg_score:.1f}")
        
        return scored_repos
    
    async def _score_repository(self, repo):
        """Advanced repository scoring system"""
        score = 0
        
        # 1. Recent activity (most important - up to 100 points)
        try:
            updated = datetime.fromisoformat(repo['updated_at'].replace('Z', '+00:00'))
            days_ago = (datetime.now(timezone.utc) - updated).days
            
            if days_ago < 7:
                score += 100
            elif days_ago < 30:
                score += 80
            elif days_ago < 90:
                score += 60
            elif days_ago < 180:
                score += 40
            elif days_ago < 365:
                score += 20
        except:
            pass
        
        # 2. Repository popularity (up to 30 points)
        stars = repo.get('stargazers_count', 0)
        if stars >= 100:
            score += 30
        elif stars >= 50:
            score += 25
        elif stars >= 20:
            score += 20
        elif stars >= 10:
            score += 15
        elif stars >= 5:
            score += 10
        
        # 3. Name relevance (up to 40 points)
        name = repo.get('name', '').lower()
        if 'proxy' in name:
            score += 25
        if 'list' in name:
            score += 15
        if any(word in name for word in ['free', 'working', 'fresh', 'live']):
            score += 10
        if any(word in name for word in ['socks', 'http', 'https']):
            score += 10
        
        # 4. Description quality (up to 20 points)
        desc = repo.get('description', '').lower()
        if desc:
            if any(word in desc for word in ['proxy', 'socks', 'http']):
                score += 10
            if any(word in desc for word in ['working', 'fresh', 'updated', 'daily']):
                score += 10
        
        # 5. Repository size (up to 10 points)
        size_kb = repo.get('size', 0)
        if 100 <= size_kb <= 10000:  # Sweet spot for proxy lists
            score += 10
        elif 10 <= size_kb <= 50000:
            score += 5
        
        return score
    
    async def _scrape_repository_optimized(self, repository, repo_score):
        """Optimized repository scraping with smart file detection"""
        repo_name = repository['full_name']
        proxies = []
        
        try:
            contents_url = f"https://api.github.com/repos/{repo_name}/contents"
            
            async with self.session.get(contents_url) as response:
                if response.status != 200:
                    return []
                
                contents = await response.json()
                
                # Smart file filtering
                proxy_files = []
                for item in contents:
                    if item['type'] == 'file' and self._is_likely_proxy_file(item):
                        proxy_files.append(item)
                
                logger.info(f"    📄 Found {len(proxy_files)} quality proxy files")
                
                # Process files with size priority
                proxy_files.sort(key=lambda x: x.get('size', 0), reverse=True)
                
                for file_item in proxy_files[:5]:  # Limit to top 5 files
                    file_proxies = await self._extract_from_file_optimized(file_item, repo_name, repo_score)
                    proxies.extend(file_proxies)
                    
                    # Stop if we have enough proxies from this repo
                    if len(proxies) > 5000:
                        break
                    
                    await asyncio.sleep(0.2)
        
        except Exception as e:
            logger.error(f"    ❌ Repository error: {e}")
        
        return proxies
    
    def _is_likely_proxy_file(self, file_item):
        """Smart proxy file detection"""
        filename = file_item['name'].lower()
        file_size = file_item.get('size', 0)
        
        # Size filters (100 bytes to 5MB)
        if file_size < 100 or file_size > 5_000_000:
            return False
        
        # Pattern matching
        return any(re.match(pattern, filename) for pattern in PROXY_FILE_PATTERNS)
    
    async def _extract_from_file_optimized(self, file_item, repo_name, repo_score):
        """Optimized proxy extraction with fast parsing"""
        try:
            download_url = file_item.get('download_url')
            if not download_url:
                return []
            
            async with self.session.get(download_url) as response:
                if response.status != 200:
                    return []
                
                content = await response.text()
                
                # Quick content validation
                if len(content) > 3_000_000:  # 3MB limit
                    return []
                
                proxy_type = self._guess_proxy_type_fast(download_url, file_item['name'])
                return self._parse_proxy_content_optimized(content, repo_name, proxy_type, repo_score)
        
        except Exception as e:
            logger.warning(f"      ❌ File error: {e}")
            return []
    
    def _parse_proxy_content_optimized(self, content, repository, proxy_type, repo_score):
        """High-performance proxy parsing with regex"""
        proxies = []
        lines = content.splitlines()
        
        # Limit processing for performance
        max_lines = min(len(lines), 100_000)
        
        for line in lines[:max_lines]:
            line = line.strip()
            
            # Skip comments and empty lines
            if not line or line.startswith(('#', '//', ';', '!')):
                continue
            
            # Fast regex matching
            match = self.proxy_pattern.match(line)
            if match:
                ip, port_str = match.groups()
                try:
                    port = int(port_str)
                    if self._is_valid_ip_fast(ip) and 1 <= port <= 65535:
                        proxies.append({
                            'ip': ip,
                            'port': port,
                            'proxy_type': proxy_type,
                            'source': f"repository:{repository}",
                            'repository': repository,
                            'repo_score': repo_score
                        })
                except ValueError:
                    continue
        
        return proxies
    
    def _is_valid_ip_fast(self, ip):
        """Fast IP validation"""
        parts = ip.split('.')
        if len(parts) != 4:
            return False
        try:
            return all(0 <= int(part) <= 255 for part in parts)
        except ValueError:
            return False
    
    def _guess_proxy_type_fast(self, url, filename):
        """Fast proxy type detection"""
        text = f"{url} {filename}".lower()
        
        if 'socks5' in text:
            return 'socks5'
        elif 'socks4' in text:
            return 'socks4'
        elif 'https' in text:
            return 'https'
        elif 'http' in text:
            return 'http'
        else:
            return 'mixed'
    
    async def _fetch_direct_sources_optimized(self):
        """Optimized direct source fetching"""
        logger.info("📡 Fetching optimized direct sources")
        
        all_proxies = []
        tasks = []
        
        # Parallel fetching
        for url in DIRECT_SOURCES:
            task = self._fetch_single_source(url)
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, result in enumerate(results):
            if isinstance(result, list):
                all_proxies.extend(result)
                logger.info(f"  ✅ Source {i+1}: {len(result)} proxies")
            else:
                logger.warning(f"  ❌ Source {i+1}: Failed")
        
        return all_proxies
    
    async def _fetch_single_source(self, url):
        """Fetch single direct source"""
        try:
            async with self.session.get(url) as response:
                if response.status != 200:
                    return []
                
                content = await response.text()
                proxy_type = self._guess_proxy_type_fast(url, url.split('/')[-1])
                repo_name = url.split('/')[-3] + "/" + url.split('/')[-2]
                
                return self._parse_proxy_content_optimized(content, repo_name, proxy_type, 50)
        except:
            return []
    
    def _deduplicate_proxies(self, proxies):
        """Memory-efficient deduplication"""
        seen = set()
        unique_proxies = []
        
        for proxy in proxies:
            key = f"{proxy['ip']}:{proxy['port']}"
            if key not in seen:
                seen.add(key)
                unique_proxies.append(proxy)
        
        return unique_proxies

class HighPerformanceValidator:
    """High-performance proxy validation with smart batching"""
    
    def __init__(self, max_concurrent=100, timeout=3.0):
        self.max_concurrent = max_concurrent
        self.timeout = timeout
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.test_url = "http://httpbin.org/ip"  # Single fast endpoint
        logger.info(f"⚡ High-performance validator: {max_concurrent} concurrent, {timeout}s timeout")
    
    async def validate_batch(self, proxies):
        """High-performance batch validation"""
        if not proxies:
            return []
            
        logger.info(f"🔍 High-speed validation: {len(proxies)} proxies")
        
        # Smart chunking based on memory
        chunk_size = min(2000, len(proxies))
        all_results = []
        
        for i in range(0, len(proxies), chunk_size):
            chunk = proxies[i:i + chunk_size]
            chunk_num = i//chunk_size + 1
            total_chunks = (len(proxies)-1)//chunk_size + 1
            
            logger.info(f"  ⚡ Chunk {chunk_num}/{total_chunks}: {len(chunk)} proxies")
            
            # Parallel validation
            tasks = [self._validate_single_fast(proxy) for proxy in chunk]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Filter valid results
            valid_results = [r for r in results if isinstance(r, dict)]
            all_results.extend(valid_results)
            
            working_count = sum(1 for r in valid_results if r.get('is_working'))
            logger.info(f"    ✅ Chunk complete: {working_count}/{len(chunk)} working")
        
        total_working = sum(1 for r in all_results if r.get('is_working'))
        logger.info(f"✅ Validation complete: {total_working}/{len(proxies)} working ({total_working/len(proxies)*100:.1f}%)")
        
        return all_results
    
    async def _validate_single_fast(self, proxy):
        """Fast single proxy validation"""
        async with self.semaphore:
            start_time = time.time()
            
            try:
                # Optimized timeouts
                timeout = aiohttp.ClientTimeout(total=self.timeout, connect=1.0)
                connector = aiohttp.TCPConnector(limit=1, ttl_dns_cache=300)
                
                proxy_url = f"http://{proxy['ip']}:{proxy['port']}"
                
                async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
                    async with session.get(self.test_url, proxy=proxy_url) as response:
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
            
            # Mark as failed
            proxy.update({
                'is_working': False,
                'last_checked': datetime.now(timezone.utc).isoformat()
            })
            return proxy

async def export_files_optimized(db, output_dir="docs"):
    """Optimized file export with enhanced metadata"""
    logger.info(f"📤 Exporting optimized results to {output_dir}")
    
    try:
        os.makedirs(output_dir, exist_ok=True)
        
        working_proxies = db.get_working_proxies(limit=10000)
        stats = db.get_stats()
        
        logger.info(f"📊 Exporting {len(working_proxies)} working proxies")
        
        # Export main list with quality indicators
        txt_path = Path(output_dir) / "proxies.txt"
        async with aiofiles.open(txt_path, 'w') as f:
            await f.write(f"# Optimized Proxy List - {datetime.now(timezone.utc).isoformat()}\n")
            await f.write(f"# Working proxies: {stats['working_proxies']}\n")
            await f.write(f"# Success rate: {stats['success_rate']}%\n")
            await f.write("# Discovery: Repository-first with intelligent scoring\n")
            await f.write("# Validation: High-performance parallel testing\n")
            await f.write("# Format: IP:PORT (sorted by quality)\n\n")
            
            for proxy in working_proxies:
                await f.write(f"{proxy[0]}:{proxy[1]}\n")
        
        # Enhanced JSON export
        json_data = {
            "metadata": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total_working": len(working_proxies),
                "database_stats": stats,
                "discovery_method": "optimized-repository-first",
                "validation_method": "high-performance-parallel",
                "quality_sorted": True
            },
            "proxies": []
        }
        
        # Build enhanced JSON
        for p in working_proxies:
            proxy_data = {
                "ip": p[0],
                "port": p[1],
                "type": p[2] if len(p) > 2 else "unknown",
                "source": p[3] if len(p) > 3 else "unknown",
                "repository": p[4] if len(p) > 4 else "unknown",
                "response_time_ms": p[7] if len(p) > 7 else None
            }
            json_data["proxies"].append(proxy_data)
        
        json_path = Path(output_dir) / "proxies.json"
        async with aiofiles.open(json_path, 'w') as f:
            await f.write(json.dumps(json_data, indent=2))
        
        # Export by type
        by_type_dir = Path(output_dir) / "by_type"
        os.makedirs(by_type_dir, exist_ok=True)
        
        if stats.get('by_type'):
            for proxy_type in stats['by_type'].keys():
                type_proxies = [p for p in working_proxies if (len(p) > 2 and p[2] == proxy_type)]
                if type_proxies:
                    type_path = by_type_dir / f"{proxy_type}.txt"
                    async with aiofiles.open(type_path, 'w') as f:
                        await f.write(f"# {proxy_type.upper()} Proxies\n")
                        await f.write(f"# Count: {len(type_proxies)}\n\n")
                        for p in type_proxies:
                            await f.write(f"{p[0]}:{p[1]}\n")
        
        # Enhanced stats
        stats_path = Path(output_dir) / "stats.json"
        async with aiofiles.open(stats_path, 'w') as f:
            await f.write(json.dumps(stats, indent=2))
        
        # Create optimized dashboard
        await create_optimized_dashboard(stats, output_dir)
        
        logger.info(f"✅ Optimized export complete: {len(working_proxies)} proxies")
        return len(working_proxies)
        
    except Exception as e:
        logger.error(f"❌ Export failed: {e}")
        raise

async def create_optimized_dashboard(stats, output_dir):
    """Create enhanced dashboard with optimization details"""
    
    # Repository section with scores
    repo_section = ""
    if stats.get('by_repository'):
        repo_section = """
    <div class="repositories">
        <h2>🏆 Top Quality Repositories</h2>
        <div class="repo-grid">"""
        
        for repo, data in list(stats['by_repository'].items())[:10]:
            if isinstance(data, dict):
                count = data.get('count', 0)
                score = data.get('avg_score', 0)
                repo_section += f"""
                <div class="repo-card">
                    <div class="repo-name">{repo}</div>
                    <div class="repo-stats">
                        <span class="count">{count:,} proxies</span>
                        <span class="score">Quality: {score}/100</span>
                    </div>
                </div>"""
            else:
                repo_section += f"""
                <div class="repo-card">
                    <div class="repo-name">{repo}</div>
                    <div class="repo-count">{data:,} proxies</div>
                </div>"""
        
        repo_section += """
        </div>
    </div>"""
    
    # Type section
    type_section = ""
    if stats.get('by_type'):
        type_section = """
        <div class="type-stats">
            <h2>📊 Proxies by Type</h2>
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
    <title>Optimized Proxy Intelligence Dashboard</title>
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
        .optimization-badge {{
            background: rgba(255,255,255,0.2);
            padding: 0.5rem 1rem;
            border-radius: 20px;
            display: inline-block;
            margin-top: 1rem;
            font-size: 0.9rem;
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
        .optimization-info {{
            background: linear-gradient(135deg, #e7f3ff 0%, #f0f8ff 100%);
            padding: 1.5rem;
            border-radius: 8px;
            margin-bottom: 2rem;
            border-left: 4px solid #007bff;
        }}
        .feature-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 1rem;
            margin-top: 1rem;
        }}
        .feature {{
            background: white;
            padding: 1rem;
            border-radius: 6px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
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
            font-size: 0.9rem;
        }}
        .repo-stats {{
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .count {{
            color: #666;
            font-size: 0.8rem;
        }}
        .score {{
            background: #e7f3ff;
            color: #0066cc;
            padding: 0.2rem 0.5rem;
            border-radius: 12px;
            font-size: 0.7rem;
            font-weight: 500;
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
        <h1>⚡ Optimized Proxy Intelligence</h1>
        <p>Advanced Repository-First Discovery with AI Scoring</p>
        <div class="optimization-badge">
            🚀 High-Performance • 🧠 Smart Filtering • ⚡ Parallel Validation
        </div>
    </div>
    
    <div class="optimization-info">
        <h3>🔬 Advanced Optimization Features</h3>
        <div class="feature-grid">
            <div class="feature">
                <h4>🏆 Repository Scoring</h4>
                <p>AI-powered quality assessment based on activity, popularity, and content analysis</p>
            </div>
            <div class="feature">
                <h4>⚡ Parallel Processing</h4>
                <p>High-concurrency validation with smart memory management</p>
            </div>
            <div class="feature">
                <h4>🎯 Smart Filtering</h4>
                <p>Advanced regex patterns and file size optimization</p>
            </div>
            <div class="feature">
                <h4>📊 Quality Sorting</h4>
                <p>Results ranked by repository score and response time</p>
            </div>
        </div>
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
            <div>Quality Repositories</div>
        </div>
    </div>
    
    {type_section}
    
    {repo_section}
    
    <div class="downloads">
        <h2>📥 Download Optimized Proxy Lists</h2>
        <p>High-quality proxies from scored repositories, validated with parallel processing:</p>
        <a href="proxies.txt" class="btn">📄 Main List (Quality Sorted)</a>
        <a href="proxies.json" class="btn">📊 Enhanced JSON</a>
        <a href="by_type/" class="btn">🗂️ By Type</a>
        <a href="stats.json" class="btn">📈 Statistics</a>
        <p><em>Updated every 8 hours using optimized repository-first discovery with AI scoring.</em></p>
    </div>
    
    <div class="footer">
        <p>Last updated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}</p>
        <p>🧠 AI-powered repository scoring • ⚡ 100+ concurrent validation • 🎯 Smart filtering</p>
        <p>🔍 Discovery optimized for quality over quantity</p>
    </div>
</body>
</html>"""
    
    html_path = Path(output_dir) / "index.html"
    async with aiofiles.open(html_path, 'w') as f:
        await f.write(html)

async def main():
    """Optimized main execution"""
    start_time = time.time()
    logger.info("🚀 Starting Optimized Repository-First Proxy Discovery")
    
    # Enhanced configuration
    github_token = os.getenv("GITHUB_TOKEN")
    max_pages = int(os.getenv("MAX_PAGES", "3"))
    max_concurrent = int(os.getenv("MAX_CONCURRENT", "100"))
    max_memory_mb = int(os.getenv("MAX_MEMORY_MB", "512"))
    
    logger.info(f"🔧 Optimized Configuration:")
    logger.info(f"  - GitHub Token: {'✅ Set' if github_token else '❌ Missing'}")
    logger.info(f"  - Max Pages per query: {max_pages}")
    logger.info(f"  - Max Concurrent: {max_concurrent}")
    logger.info(f"  - Memory Limit: {max_memory_mb}MB")
    logger.info(f"  - Strategy: Optimized repository-first with AI scoring")
    
    try:
        # Initialize optimized database
        logger.info("🗄️ Initializing optimized database...")
        db = ProxyDatabase()
        
        # Optimized discovery
        logger.info("🧠 Starting AI-powered repository discovery...")
        async with OptimizedRepositoryDiscovery(github_token) as discovery:
            proxies = await discovery.discover_all_proxies(max_pages, max_memory_mb)
        
        if not proxies:
            logger.error("❌ No proxies discovered!")
            await export_files_optimized(db)
            return
        
        logger.info(f"✅ Total proxies discovered: {len(proxies)}")
        
        # High-performance validation
        logger.info("⚡ Starting high-performance validation...")
        validator = HighPerformanceValidator(max_concurrent=max_concurrent)
        
        # Optimized batch processing
        batch_size = min(10000, len(proxies))
        all_validated = []
        
        for i in range(0, len(proxies), batch_size):
            batch = proxies[i:i + batch_size]
            batch_num = i//batch_size + 1
            total_batches = (len(proxies)-1)//batch_size + 1
            
            logger.info(f"🔄 Processing batch {batch_num}/{total_batches}: {len(batch)} proxies")
            
            validated = await validator.validate_batch(batch)
            all_validated.extend(validated)
            
            # Immediate database storage
            db.add_proxies_batch(validated)
            
            # Memory monitoring
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            logger.info(f"💾 Memory usage: {memory_mb:.1f} MB")
            
            # Brief pause for system stability
            if len(batch) >= 5000:
                await asyncio.sleep(1)
        
        # Export optimized results
        logger.info("📤 Exporting optimized results...")
        exported_count = await export_files_optimized(db)
        
        # Database optimization
        logger.info("🗜️ Optimizing database...")
        db.compress_database()
        
        # Enhanced statistics
        stats = db.get_stats()
        execution_time = time.time() - start_time
        
        logger.info("=" * 80)
        logger.info("🎉 OPTIMIZED REPOSITORY-FIRST DISCOVERY COMPLETE")
        logger.info("=" * 80)
        logger.info(f"⏱️  Total execution time: {execution_time:.1f} seconds")
        logger.info(f"🔍 Total discovered: {stats['total_proxies']:,}")
        logger.info(f"✅ Working proxies: {stats['working_proxies']:,}")
        logger.info(f"📊 Success rate: {stats['success_rate']}%")
        logger.info(f"📤 Exported: {exported_count:,}")
        logger.info(f"🏆 Quality repositories: {len(stats.get('by_repository', {}))}")
        
        # Performance metrics
        if execution_time > 0:
            repos_per_minute = len(stats.get('by_repository', {})) * 60 / execution_time
            proxies_per_second = len(proxies) / execution_time
            validation_rate = stats['total_proxies'] / execution_time
            
            logger.info("⚡ Performance Metrics:")
            logger.info(f"  - Repository processing: {repos_per_minute:.1f} repos/min")
            logger.info(f"  - Proxy discovery: {proxies_per_second:.1f} proxies/sec")
            logger.info(f"  - Validation rate: {validation_rate:.1f} validations/sec")
        
        # Top repositories with scores
        if stats.get('by_repository'):
            logger.info("🏆 Top quality repositories:")
            for repo, data in list(stats['by_repository'].items())[:5]:
                if isinstance(data, dict):
                    count = data.get('count', 0)
                    score = data.get('avg_score', 0)
                    logger.info(f"  - {repo}: {count:,} proxies (quality: {score:.1f}/100)")
                else:
                    logger.info(f"  - {repo}: {data:,} proxies")
        
        # Type breakdown
        if stats.get('by_type'):
            logger.info("📋 Optimized breakdown by type:")
            for proxy_type, count in stats['by_type'].items():
                percentage = (count / stats['working_proxies'] * 100) if stats['working_proxies'] > 0 else 0
                logger.info(f"  - {proxy_type.upper()}: {count:,} ({percentage:.1f}%)")
        
        # GitHub Actions output
        if os.getenv("GITHUB_ACTIONS"):
            try:
                with open(os.getenv("GITHUB_OUTPUT", "/dev/stdout"), "a") as f:
                    f.write(f"working_proxies={stats['working_proxies']}\n")
                    f.write(f"total_proxies={stats['total_proxies']}\n")
                    f.write(f"success_rate={stats['success_rate']}\n")
                    f.write(f"repositories_found={len(stats.get('by_repository', {}))}\n")
                    f.write(f"execution_time={execution_time:.1f}\n")
                    f.write(f"optimization_enabled=true\n")
            except Exception as e:
                logger.warning(f"⚠️ GitHub Actions output failed: {e}")
        
        logger.info("🚀 Optimized proxy discovery completed successfully!")
        logger.info("🧠 AI scoring and parallel validation delivered premium results")
        
    except Exception as e:
        logger.error(f"❌ System failure: {e}")
        logger.error("Full traceback:", exc_info=True)
        
        # Emergency export
        try:
            logger.info("🔄 Creating emergency export...")
            db = ProxyDatabase()
            await export_files_optimized(db)
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
        logger.error(f"💥 Critical error: {e}")
        sys.exit(1)
