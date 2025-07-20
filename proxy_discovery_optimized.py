#!/usr/bin/env python3
"""
Optimized Proxy Discovery System for GitHub Free Tier
Designed to handle 1M+ proxies with minimal resource usage
"""

import asyncio
import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Set, Optional, AsyncGenerator
import os
import sys

# Minimal dependencies for GitHub Actions
import aiohttp
import aiofiles

# Configure minimal logging for GitHub Actions
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

@dataclass
class ProxyInfo:
    """Lightweight proxy information"""
    ip: str
    port: int
    source: str
    country: Optional[str] = None
    last_checked: Optional[str] = None
    is_working: bool = False
    response_time: Optional[float] = None

class OptimizedProxyDatabase:
    """Memory-efficient SQLite database for large-scale proxy storage"""
    
    def __init__(self, db_path: str = "proxies.db"):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """Initialize database with optimized schema for millions of records"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")  # Better for concurrent access
            conn.execute("PRAGMA synchronous=NORMAL")  # Faster writes
            conn.execute("PRAGMA cache_size=10000")  # 10MB cache
            conn.execute("PRAGMA temp_store=MEMORY")  # Use memory for temp tables
            
            # Optimized schema with indexes
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
            
            # Indexes for performance with millions of records
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ip_port ON proxies(ip, port)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_working ON proxies(is_working)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_last_checked ON proxies(last_checked)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_country ON proxies(country)")
            
            conn.commit()
    
    def bulk_insert_proxies(self, proxies: List[ProxyInfo], batch_size: int = 1000):
        """Efficiently insert millions of proxies in batches"""
        logger.info(f"Inserting {len(proxies)} proxies in batches of {batch_size}")
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("BEGIN TRANSACTION")
            
            for i in range(0, len(proxies), batch_size):
                batch = proxies[i:i + batch_size]
                proxy_data = [
                    (p.ip, p.port, p.source, p.country, p.last_checked, p.is_working, p.response_time)
                    for p in batch
                ]
                
                conn.executemany("""
                    INSERT OR REPLACE INTO proxies 
                    (ip, port, source, country, last_checked, is_working, response_time)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, proxy_data)
                
                if i % (batch_size * 10) == 0:  # Log progress every 10k records
                    logger.info(f"Processed {i + len(batch)} proxies...")
            
            conn.execute("COMMIT")
            logger.info("Bulk insert completed")
    
    def get_working_proxies(self, limit: Optional[int] = None) -> List[ProxyInfo]:
        """Get working proxies efficiently"""
        query = """
            SELECT ip, port, source, country, last_checked, response_time
            FROM proxies 
            WHERE is_working = 1 
            ORDER BY response_time ASC
        """
        if limit:
            query += f" LIMIT {limit}"
        
        with sqlite3.connect(self.db_path) as conn:
            results = conn.execute(query).fetchall()
            
        return [
            ProxyInfo(
                ip=row[0], port=row[1], source=row[2], country=row[3],
                last_checked=row[4], is_working=True, response_time=row[5]
            )
            for row in results
        ]
    
    def get_stats(self) -> dict:
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

class MemoryEfficientDiscovery:
    """Discover proxies using minimal memory for large-scale operations"""
    
    def __init__(self, github_token: Optional[str] = None):
        self.github_token = github_token
        self.session: Optional[aiohttp.ClientSession] = None
        self.discovered_count = 0
    
    async def __aenter__(self):
        """Async context manager setup"""
        headers = {"User-Agent": "ProxyDiscovery/1.0"}
        if self.github_token:
            headers["Authorization"] = f"Bearer {self.github_token}"
        
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        self.session = aiohttp.ClientSession(
            headers=headers,
            timeout=timeout,
            connector=aiohttp.TCPConnector(limit=100, limit_per_host=10)
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Cleanup session"""
        if self.session:
            await self.session.close()
    
    async def discover_from_github(self, max_pages: int = 5) -> AsyncGenerator[ProxyInfo, None]:
        """Memory-efficient GitHub discovery using generators"""
        logger.info(f"Starting GitHub discovery (max {max_pages} pages)")
        
        queries = [
            "proxy list filetype:txt",
            "socks proxy filetype:txt", 
            "http proxy servers",
            "proxy.txt",
            "proxies.txt"
        ]
        
        for query in queries:
            async for proxy in self._search_github_query(query, max_pages):
                yield proxy
                self.discovered_count += 1
                
                # Log progress every 1000 proxies
                if self.discovered_count % 1000 == 0:
                    logger.info(f"Discovered {self.discovered_count} proxies so far...")
    
    async def _search_github_query(self, query: str, max_pages: int) -> AsyncGenerator[ProxyInfo, None]:
        """Search GitHub with a specific query"""
        for page in range(1, max_pages + 1):
            try:
                url = f"https://api.github.com/search/code"
                params = {
                    "q": query,
                    "page": page,
                    "per_page": 30  # Reduced for rate limiting
                }
                
                async with self.session.get(url, params=params) as response:
                    if response.status == 403:  # Rate limited
                        logger.warning("GitHub rate limit hit, stopping search")
                        break
                    
                    if response.status != 200:
                        logger.warning(f"GitHub API error: {response.status}")
                        continue
                    
                    data = await response.json()
                    items = data.get("items", [])
                    
                    if not items:
                        break
                    
                    # Process items concurrently but limit memory usage
                    tasks = [self._extract_proxies_from_file(item) for item in items[:10]]  # Limit concurrent files
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    for result in results:
                        if isinstance(result, list):
                            for proxy in result:
                                yield proxy
                
                # Rate limiting delay
                await asyncio.sleep(2)
                
            except Exception as e:
                logger.error(f"Error searching GitHub: {e}")
                continue
    
    async def _extract_proxies_from_file(self, item: dict) -> List[ProxyInfo]:
        """Extract proxies from a GitHub file efficiently"""
        try:
            # Convert to raw URL
            html_url = item.get("html_url", "")
            raw_url = html_url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
            
            async with self.session.get(raw_url) as response:
                if response.status != 200:
                    return []
                
                # Read content with size limit to prevent memory issues
                content = await response.text()
                if len(content) > 1_000_000:  # Skip files larger than 1MB
                    logger.warning(f"Skipping large file: {raw_url}")
                    return []
                
                return self._parse_proxy_content(content, source=f"github:{item.get('repository', {}).get('full_name', 'unknown')}")
        
        except Exception as e:
            logger.debug(f"Error extracting from file: {e}")
            return []
    
    def _parse_proxy_content(self, content: str, source: str) -> List[ProxyInfo]:
        """Parse proxy content efficiently"""
        proxies = []
        lines = content.splitlines()
        
        for line in lines[:10000]:  # Limit lines processed per file
            line = line.strip()
            
            # Skip comments and empty lines
            if not line or line.startswith(('#', '//', ';')):
                continue
            
            # Look for IP:port pattern
            if ':' in line and '.' in line:
                parts = line.split(':')
                if len(parts) >= 2:
                    try:
                        ip = parts[0].strip()
                        port = int(parts[1].strip())
                        
                        # Basic IP validation
                        if self._is_valid_ip(ip) and 1 <= port <= 65535:
                            proxies.append(ProxyInfo(ip=ip, port=port, source=source))
                            
                    except (ValueError, IndexError):
                        continue
        
        return proxies
    
    def _is_valid_ip(self, ip: str) -> bool:
        """Quick IP validation"""
        try:
            parts = ip.split('.')
            return len(parts) == 4 and all(0 <= int(part) <= 255 for part in parts)
        except (ValueError, AttributeError):
            return False

class FastProxyValidator:
    """High-speed proxy validation optimized for GitHub Actions"""
    
    def __init__(self, max_concurrent: int = 100, timeout: float = 5.0):
        self.max_concurrent = max_concurrent
        self.timeout = timeout
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.validated_count = 0
    
    async def validate_proxies_batch(self, proxies: List[ProxyInfo]) -> List[ProxyInfo]:
        """Validate proxies in efficient batches"""
        logger.info(f"Validating {len(proxies)} proxies with {self.max_concurrent} concurrent connections")
        
        # Create validation tasks
        tasks = [self._validate_single_proxy(proxy) for proxy in proxies]
        
        # Process in batches to manage memory
        batch_size = 1000
        validated_proxies = []
        
        for i in range(0, len(tasks), batch_size):
            batch_tasks = tasks[i:i + batch_size]
            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
            
            for result in batch_results:
                if isinstance(result, ProxyInfo) and result.is_working:
                    validated_proxies.append(result)
                    self.validated_count += 1
            
            # Log progress
            logger.info(f"Validated {min(i + batch_size, len(tasks))}/{len(tasks)} proxies, {self.validated_count} working")
            
            # Small delay to prevent overwhelming the system
            if i + batch_size < len(tasks):
                await asyncio.sleep(0.1)
        
        logger.info(f"Validation complete: {self.validated_count}/{len(proxies)} proxies working")
        return validated_proxies
    
    async def _validate_single_proxy(self, proxy: ProxyInfo) -> ProxyInfo:
        """Validate a single proxy with timeout and error handling"""
        async with self.semaphore:
            start_time = time.time()
            
            try:
                proxy_url = f"http://{proxy.ip}:{proxy.port}"
                timeout = aiohttp.ClientTimeout(total=self.timeout)
                
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(
                        "http://httpbin.org/ip",
                        proxy=proxy_url,
                        timeout=timeout
                    ) as response:
                        if response.status == 200:
                            response_time = time.time() - start_time
                            proxy.is_working = True
                            proxy.response_time = round(response_time * 1000, 2)  # ms
                            proxy.last_checked = datetime.now(timezone.utc).isoformat()
                            
                            # Try to get country info from response
                            try:
                                data = await response.json()
                                # This is a basic example - in production you'd use a proper geolocation service
                                proxy.country = "Unknown"
                            except:
                                proxy.country = "Unknown"
                        
                        return proxy
            
            except Exception:
                # Proxy failed validation
                proxy.is_working = False
                proxy.last_checked = datetime.now(timezone.utc).isoformat()
                return proxy

async def export_proxy_files(db: OptimizedProxyDatabase, output_dir: str = "output"):
    """Export proxy files efficiently for GitHub Pages"""
    os.makedirs(output_dir, exist_ok=True)
    
    # Get working proxies
    working_proxies = db.get_working_proxies(limit=50000)  # Limit for GitHub Pages size
    stats = db.get_stats()
    
    logger.info(f"Exporting {len(working_proxies)} working proxies")
    
    # Export simple text format
    txt_path = Path(output_dir) / "proxies.txt"
    async with aiofiles.open(txt_path, 'w') as f:
        await f.write(f"# Proxy List - {datetime.now(timezone.utc).isoformat()}\n")
        await f.write(f"# Total working proxies: {stats['working_proxies']}\n")
        await f.write(f"# Success rate: {stats['success_rate']}%\n")
        await f.write("# Format: IP:PORT\n\n")
        
        for proxy in working_proxies:
            await f.write(f"{proxy.ip}:{proxy.port}\n")
    
    # Export JSON format with metadata
    json_data = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_proxies": len(working_proxies),
            "database_stats": stats,
            "format_version": "1.0"
        },
        "proxies": [
            {
                "ip": p.ip,
                "port": p.port,
                "country": p.country,
                "response_time_ms": p.response_time,
                "source": p.source,
                "last_checked": p.last_checked
            }
            for p in working_proxies
        ]
    }
    
    json_path = Path(output_dir) / "proxies.json"
    async with aiofiles.open(json_path, 'w') as f:
        await f.write(json.dumps(json_data, indent=2))
    
    # Export statistics
    stats_path = Path(output_dir) / "stats.json"
    async with aiofiles.open(stats_path, 'w') as f:
        await f.write(json.dumps(stats, indent=2))
    
    logger.info(f"Export completed: {len(working_proxies)} proxies exported to {output_dir}")
    return len(working_proxies)

async def main():
    """Main execution function optimized for GitHub Actions"""
    start_time = time.time()
    logger.info("Starting optimized proxy discovery system")
    
    # Configuration from environment
    github_token = os.getenv("GITHUB_TOKEN")
    max_pages = int(os.getenv("MAX_PAGES", "3"))
    max_concurrent = int(os.getenv("MAX_CONCURRENT", "50"))  # Reduced for free tier
    
    if not github_token:
        logger.warning("GITHUB_TOKEN not provided - API rate limits will be very restrictive")
    
    # Initialize database
    db = OptimizedProxyDatabase()
    
    # Discover proxies
    discovered_proxies = []
    async with MemoryEfficientDiscovery(github_token) as discovery:
        async for proxy in discovery.discover_from_github(max_pages):
            discovered_proxies.append(proxy)
            
            # Process in batches to manage memory
            if len(discovered_proxies) >= 5000:
                logger.info(f"Processing batch of {len(discovered_proxies)} proxies")
                
                # Validate batch
                validator = FastProxyValidator(max_concurrent=max_concurrent)
                validated = await validator.validate_proxies_batch(discovered_proxies)
                
                # Store in database
                db.bulk_insert_proxies(validated)
                
                # Clear memory
                discovered_proxies.clear()
                
                # Log memory usage (approximate)
                import psutil
                process = psutil.Process()
                memory_mb = process.memory_info().rss / 1024 / 1024
                logger.info(f"Memory usage: {memory_mb:.1f} MB")
    
    # Process remaining proxies
    if discovered_proxies:
        logger.info(f"Processing final batch of {len(discovered_proxies)} proxies")
        validator = FastProxyValidator(max_concurrent=max_concurrent)
        validated = await validator.validate_proxies_batch(discovered_proxies)
        db.bulk_insert_proxies(validated)
    
    # Export results
    exported_count = await export_proxy_files(db)
    
    # Final statistics
    stats = db.get_stats()
    execution_time = time.time() - start_time
    
    logger.info("="*50)
    logger.info("EXECUTION SUMMARY")
    logger.info("="*50)
    logger.info(f"Total execution time: {execution_time:.1f} seconds")
    logger.info(f"Total proxies discovered: {stats['total_proxies']}")
    logger.info(f"Working proxies: {stats['working_proxies']}")
    logger.info(f"Success rate: {stats['success_rate']}%")
    logger.info(f"Proxies exported: {exported_count}")
    logger.info(f"Countries detected: {stats['countries']}")
    
    # Set GitHub Actions output
    if os.getenv("GITHUB_ACTIONS"):
        with open(os.getenv("GITHUB_OUTPUT", "/dev/stdout"), "a") as f:
            f.write(f"working_proxies={stats['working_proxies']}\n")
            f.write(f"success_rate={stats['success_rate']}\n")
            f.write(f"total_discovered={stats['total_proxies']}\n")

if __name__ == "__main__":
    # Ensure proper event loop for Windows compatibility
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Process interrupted by user")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)
