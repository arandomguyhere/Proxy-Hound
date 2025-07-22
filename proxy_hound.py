# Basic relevance check
        name = repo.get('name', '').lower()
        desc = repo.get('description', '').lower()
        text = f"{name} {desc}"
        
        proxy_keywords = ['proxy', 'socks', 'http', 'list', 'working', 'free']
        if not any(keyword in text for keyword in proxy_keywords):
            return False
        
        return True
    
    async def _score_and_rank_prey(self, repositories):
        """Score and rank repositories for hunting priority"""
        logger.info("🎯 Scoring and ranking hunting targets...")
        
        # Remove duplicates
        unique_repos = {repo['full_name']: repo for repo in repositories}
        
        scored_repos = []
        for repo in unique_repos.values():
            hunt_score = await self._calculate_hunt_score(repo)
            if hunt_score > 0:
                scored_repos.append((hunt_score, repo))
        
        # Sort by hunt score (best targets first)
        scored_repos.sort(reverse=True, key=lambda x: x[0])
        
        logger.info(f"  🎯 Scored {len(scored_repos)} hunting targets")
        if scored_repos:
            best_score = scored_repos[0][0]
            avg_score = sum(score for score, _ in scored_repos) / len(scored_repos)
            logger.info(f"  🏆 Best target score: {best_score:.1f}, Average: {avg_score:.1f}")
        
        return scored_repos
    
    async def _calculate_hunt_score(self, repo):
        """Calculate overall hunting score for repository"""
        
        # Basic scent analysis
        scent_score = self.scent_analyzer.analyze_scent_strength(repo)
        
        # Content hunting score
        content_score = await self._analyze_repository_content(repo)
        
        # Pack behavior analysis  
        pack_score = await self._analyze_pack_behavior(repo)
        
        # Territory size assessment
        size_kb = repo.get('size', 0)
        territory_score = 0
        if 100 <= size_kb <= 20000:  # Ideal hunting territory
            territory_score = 20
        elif 20 <= size_kb <= 50000:  # Acceptable territory
            territory_score = 10
        
        # Combine scores
        total_score = (
            scent_score +           # 0-85 points
            content_score * 0.7 +   # 0-70 points (weighted)
            pack_score * 0.8 +      # 0-48 points (weighted)
            territory_score         # 0-20 points
        )
        
        # Apply pack reputation modifier
        owner = repo['owner']['login']
        pack_reputation = self.hunt_tracker.get_pack_reputation(owner)
        
        if pack_reputation > 0.3:
            total_score *= 1.2  # Proven hunter bonus
        elif pack_reputation > 0 and pack_reputation < 0.05:
            total_score *= 0.6  # Poor hunter penalty
        
        # Normalize to 0-100
        normalized_score = min(100, (total_score / 200) * 100)
        
        return round(normalized_score, 1)
    
    async def _analyze_repository_content(self, repo):
        """Analyze repository content for proxy treasures"""
        content_score = 0
        
        try:
            contents_url = f"https://api.github.com/repos/{repo['full_name']}/contents"
            async with self.session.get(contents_url) as response:
                if response.status == 200:
                    contents = await response.json()
                    
                    proxy_files_found = 0
                    quality_files_found = 0
                    total_treasure_size = 0
                    
                    for item in contents:
                        if item['type'] == 'file':
                            filename = item['name'].lower()
                            size = item.get('size', 0)
                            
                            # Hunt for proxy files
                            if any(marker in filename for marker in ['proxy', 'socks', 'http']):
                                proxy_files_found += 1
                                total_treasure_size += size
                                
                                # Check for quality markers
                                if any(re.match(pattern, filename) 
                                      for pattern in self.scent_analyzer.territory_markers):
                                    quality_files_found += 1
                    
                    # Score the content
                    if proxy_files_found > 0:
                        content_score += min(proxy_files_found * 12, 60)
                    if quality_files_found > 0:
                        content_score += quality_files_found * 20
                    if 1000 < total_treasure_size < 2000000:  # Good treasure size
                        content_score += 25
                        
        except Exception as e:
            logger.debug(f"Content analysis failed for {repo['full_name']}: {e}")
        
        return content_score
    
    async def _analyze_pack_behavior(self, repo):
        """Analyze repository pack behavior (community activity)"""
        pack_score = 0
        
        # Pack size (stars/forks)
        stars = repo.get('stargazers_count', 0)
        forks = repo.get('forks_count', 0)
        
        if stars >= 50:
            pack_score += 25
        elif stars >= 20:
            pack_score += 15
        elif stars >= 10:
            pack_score += 10
        
        if forks >= 10:
            pack_score += 15
        elif forks >= 5:
            pack_score += 10
        
        # Pack leader reputation
        owner = repo['owner']['login']
        pack_reputation = self.hunt_tracker.get_pack_reputation(owner)
        
        if pack_reputation > 0.2:
            pack_score += 20  # Proven pack leader
        elif pack_reputation > 0 and pack_reputation < 0.05:
            pack_score -= 15  # Poor pack leader
        
        return pack_score
    
    async def _hunt_repository_content(self, repository, hunt_score):
        """Hunt through repository files for proxy treasures"""
        repo_name = repository['full_name']
        proxies = []
        
        try:
            contents_url = f"https://api.github.com/repos/{repo_name}/contents"
            
            async with self.session.get(contents_url) as response:
                if response.status != 200:
                    return []
                
                contents = await response.json()
                
                # Find proxy treasure files
                treasure_files = []
                for item in contents:
                    if (item['type'] == 'file' and 
                        self._is_treasure_file(item)):
                        treasure_files.append(item)
                
                logger.info(f"    📁 Found {len(treasure_files)} treasure files")
                
                # Hunt through files (prioritize by size)
                treasure_files.sort(key=lambda x: x.get('size', 0), reverse=True)
                
                for file_item in treasure_files[:5]:  # Limit to top 5 files
                    file_proxies = await self._extract_treasure_from_file(
                        file_item, repo_name, hunt_score
                    )
                    proxies.extend(file_proxies)
                    
                    # Stop if we found enough treasure in this repository
                    if len(proxies) > 5000:
                        break
                    
                    await asyncio.sleep(0.2)
        
        except Exception as e:
            logger.error(f"    ❌ Repository hunt error: {e}")
        
        return proxies
    
    def _is_treasure_file(self, file_item):
        """Determine if a file likely contains proxy treasures"""
        filename = file_item['name'].lower()
        file_size = file_item.get('size', 0)
        
        # Size filters (100 bytes to 5MB)
        if file_size < 100 or file_size > 5_000_000:
            return False
        
        # Pattern matching for treasure files
        treasure_patterns = [
            r'.*proxy.*\.txt#!/usr/bin/env python3
"""
Proxy Hound - Advanced Repository Hunter v2.1
1. Hunt GitHub repositories using scent tracking and pack behavior analysis
2. Deep content analysis for proxy treasure detection
3. Learning system that improves hunting success over time
4. High-performance parallel proxy validation
5. Comprehensive geolocation support
"""

import asyncio
import json
import logging
import sqlite3
import time
import gzip
import re
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Set
from dataclasses import dataclass, asdict
import random
import ssl
import hashlib

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

# Verified hunting grounds (direct sources as backup)
BACKUP_HUNTING_GROUNDS = [
    "https://raw.githubusercontent.com/r00tee/Proxy-List/main/Socks4.txt", 
    "https://raw.githubusercontent.com/r00tee/Proxy-List/main/Socks5.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/http.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/https.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/socks4.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/socks5.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt"
]

@dataclass
class GeolocationInfo:
    """Comprehensive geolocation information."""
    country: Optional[str] = None
    country_code: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    timezone: Optional[str] = None
    isp: Optional[str] = None
    organization: Optional[str] = None
    as_number: Optional[str] = None
    threat_level: Optional[str] = None

@dataclass
class ProxyInfo:
    """Enhanced proxy information with geolocation."""
    ip: str
    port: int
    proxy_type: str
    source: str
    repository: Optional[str] = None
    hunt_score: float = 0.0
    country: Optional[str] = None
    city: Optional[str] = None
    last_checked: Optional[str] = None
    is_working: bool = False
    response_time: Optional[float] = None
    first_seen: Optional[str] = None
    geolocation: Optional[GeolocationInfo] = None
    
    @property
    def location_string(self) -> str:
        """Get human-readable location string."""
        if self.geolocation:
            parts = []
            if self.geolocation.city:
                parts.append(self.geolocation.city)
            if self.geolocation.region:
                parts.append(self.geolocation.region)
            if self.geolocation.country:
                parts.append(self.geolocation.country)
            return ", ".join(parts) if parts else "Unknown"
        elif self.city and self.country:
            return f"{self.city}, {self.country}"
        elif self.country:
            return self.country
        return "Unknown"

class GeolocationService:
    """Geolocation service with multiple providers and caching."""
    
    def __init__(self, cache_size: int = 10000):
        self.cache: Dict[str, GeolocationInfo] = {}
        self.cache_size = cache_size
        self.session_timeout = aiohttp.ClientTimeout(total=10)
        
        # Multiple geolocation providers (free tier)
        self.providers = [
            {
                'name': 'ip-api',
                'url': 'http://ip-api.com/json/{ip}?fields=status,message,country,countryCode,region,regionName,city,lat,lon,timezone,isp,org,as,mobile,proxy,hosting',
                'rate_limit': 45,  # requests per minute
                'last_request': 0
            },
            {
                'name': 'ipapi.co',
                'url': 'https://ipapi.co/{ip}/json/',
                'rate_limit': 30,  # requests per minute for free tier
                'last_request': 0
            },
            {
                'name': 'ipwhois.app',
                'url': 'http://ipwho.is/{ip}',
                'rate_limit': 1000,  # requests per hour
                'last_request': 0
            }
        ]
    
    async def get_geolocation(self, ip: str) -> Optional[GeolocationInfo]:
        """Get geolocation for IP with caching and fallback providers."""
        
        # Check cache first
        if ip in self.cache:
            logger.debug(f"🗺️ Cache hit for {ip}")
            return self.cache[ip]
        
        # Try each provider until we get a result
        for provider in self.providers:
            try:
                result = await self._query_provider(provider, ip)
                if result:
                    # Cache the result
                    if len(self.cache) >= self.cache_size:
                        # Simple cache eviction - remove oldest entry
                        self.cache.pop(next(iter(self.cache)))
                    
                    self.cache[ip] = result
                    logger.debug(f"🌍 Geolocation found for {ip}: {result.city}, {result.country}")
                    return result
                    
            except Exception as e:
                logger.debug(f"❌ Provider {provider['name']} failed for {ip}: {e}")
                continue
        
        logger.debug(f"⚠️ No geolocation found for {ip}")
        return None
    
    async def _query_provider(self, provider: Dict, ip: str) -> Optional[GeolocationInfo]:
        """Query a specific geolocation provider."""
        
        # Rate limiting
        current_time = time.time()
        time_since_last = current_time - provider['last_request']
        min_interval = 60.0 / provider['rate_limit']  # Convert to seconds between requests
        
        if time_since_last < min_interval:
            sleep_time = min_interval - time_since_last
            await asyncio.sleep(sleep_time)
        
        provider['last_request'] = time.time()
        
        url = provider['url'].format(ip=ip)
        
        async with aiohttp.ClientSession(timeout=self.session_timeout) as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return self._parse_response(provider['name'], data)
                else:
                    logger.debug(f"❌ {provider['name']} returned status {response.status} for {ip}")
                    return None
    
    def _parse_response(self, provider_name: str, data: Dict) -> Optional[GeolocationInfo]:
        """Parse geolocation response based on provider format."""
        
        try:
            if provider_name == 'ip-api':
                if data.get('status') == 'success':
                    return GeolocationInfo(
                        country=data.get('country'),
                        country_code=data.get('countryCode'),
                        region=data.get('regionName'),
                        city=data.get('city'),
                        latitude=data.get('lat'),
                        longitude=data.get('lon'),
                        timezone=data.get('timezone'),
                        isp=data.get('isp'),
                        organization=data.get('org'),
                        as_number=data.get('as'),
                        threat_level='proxy' if data.get('proxy') else 'clean'
                    )
            
            elif provider_name == 'ipapi.co':
                if 'error' not in data:
                    return GeolocationInfo(
                        country=data.get('country_name'),
                        country_code=data.get('country_code'),
                        region=data.get('region'),
                        city=data.get('city'),
                        latitude=data.get('latitude'),
                        longitude=data.get('longitude'),
                        timezone=data.get('timezone'),
                        isp=data.get('org'),
                        organization=data.get('org')
                    )
            
            elif provider_name == 'ipwhois.app':
                if data.get('success'):
                    return GeolocationInfo(
                        country=data.get('country'),
                        country_code=data.get('country_code'),
                        region=data.get('region'),
                        city=data.get('city'),
                        latitude=data.get('latitude'),
                        longitude=data.get('longitude'),
                        timezone=data.get('timezone', {}).get('id') if isinstance(data.get('timezone'), dict) else None,
                        isp=data.get('connection', {}).get('isp') if isinstance(data.get('connection'), dict) else None,
                        organization=data.get('connection', {}).get('org') if isinstance(data.get('connection'), dict) else None,
                        as_number=data.get('connection', {}).get('asn') if isinstance(data.get('connection'), dict) else None
                    )
            
        except Exception as e:
            logger.debug(f"❌ Error parsing {provider_name} response: {e}")
        
        return None

class HuntTracker:
    """Track hunting success to improve future hunts"""
    
    def __init__(self):
        self.successful_hunts = {}
        self.failed_hunts = {}
        self.pack_reputation = {}  # Owner success rates
        logger.info("🐕 Hunt tracker initialized")
    
    def record_hunt_result(self, repo_name, hunt_score, working_proxies, total_proxies):
        """Record how successful a repository hunt was"""
        success_rate = (working_proxies / total_proxies) if total_proxies > 0 else 0
        
        hunt_data = {
            'hunt_score': hunt_score,
            'success_rate': success_rate,
            'working_proxies': working_proxies,
            'total_proxies': total_proxies,
            'hunted_at': datetime.now(timezone.utc).isoformat()
        }
        
        if success_rate > 0.1:  # Good hunt (>10% success)
            self.successful_hunts[repo_name] = hunt_data
            logger.info(f"🏆 Successful hunt recorded: {repo_name} ({success_rate:.1%})")
        else:  # Poor hunt
            self.failed_hunts[repo_name] = hunt_data
            logger.info(f"❌ Failed hunt recorded: {repo_name}")
        
        # Track pack (owner) reputation
        owner = repo_name.split('/')[0]
        if owner not in self.pack_reputation:
            self.pack_reputation[owner] = []
        self.pack_reputation[owner].append(success_rate)
    
    def get_pack_reputation(self, owner):
        """Get average success rate for a repository owner"""
        if owner in self.pack_reputation and self.pack_reputation[owner]:
            return sum(self.pack_reputation[owner]) / len(self.pack_reputation[owner])
        return 0.0

class ScentAnalyzer:
    """Analyze repository 'scent' for quality indicators"""
    
    def __init__(self):
        # Strong scent indicators (likely to have good proxies)
        self.strong_scent_keywords = [
            'working', 'live', 'fresh', 'tested', 'verified', 'daily', 'updated',
            'active', 'new', 'current', 'valid', 'checked'
        ]
        
        # Weak scent indicators (likely stale)
        self.weak_scent_keywords = [
            'old', 'archive', 'deprecated', 'backup', 'mirror', 'copy', 'dead',
            'inactive', 'outdated', 'legacy'
        ]
        
        # Territory markers (file patterns that indicate good hunting grounds)
        self.territory_markers = [
            r'.*working.*proxy.*\.txt$',
            r'.*live.*\.txt$', 
            r'.*fresh.*\.txt$',
            r'.*valid.*\.txt$',
            r'.*\d{4}-\d{2}-\d{2}.*\.txt$',  # Date in filename
            r'.*proxy.*list.*\.txt$',
            r'.*socks.*\.txt$',
            r'.*http.*\.txt$'
        ]
        
        logger.info("🐕 Scent analyzer initialized with hunting patterns")
    
    def analyze_scent_strength(self, repo):
        """Analyze how 'fresh' the repository scent is"""
        scent_score = 0
        
        name = repo.get('name', '').lower()
        desc = repo.get('description', '').lower()
        text = f"{name} {desc}"
        
        # Strong scent detection
        strong_matches = sum(1 for keyword in self.strong_scent_keywords 
                           if keyword in text)
        scent_score += strong_matches * 15
        
        # Weak scent penalty
        weak_matches = sum(1 for keyword in self.weak_scent_keywords 
                         if keyword in text)
        scent_score -= weak_matches * 10
        
        # Territory freshness (last updated)
        try:
            updated = datetime.fromisoformat(repo['updated_at'].replace('Z', '+00:00'))
            days_ago = (datetime.now(timezone.utc) - updated).days
            
            if days_ago < 7:
                scent_score += 50    # Very fresh scent
            elif days_ago < 30:
                scent_score += 30    # Fresh scent
            elif days_ago < 90:
                scent_score += 15    # Fading scent
            else:
                scent_score -= 20    # Cold trail
        except:
            scent_score -= 15
        
        return max(0, scent_score)

class ProxyHoundDatabase:
    """Database for tracking Proxy Hound hunting results"""
    
    def __init__(self, db_path="proxy_hound.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Initialize hunting database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL") 
                conn.execute("PRAGMA cache_size=10000")
                conn.execute("PRAGMA temp_store=MEMORY")
                
                # Create proxies table with hunt tracking
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS proxies (
                        id INTEGER PRIMARY KEY,
                        ip TEXT NOT NULL,
                        port INTEGER NOT NULL,
                        proxy_type TEXT,
                        source TEXT NOT NULL,
                        repository TEXT,
                        hunt_score REAL DEFAULT 0,
                        country TEXT,
                        city TEXT,
                        last_checked TEXT,
                        is_working BOOLEAN DEFAULT 0,
                        response_time REAL,
                        first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(ip, port)
                    )
                """)
                
                # Create hunt results table
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS hunt_results (
                        id INTEGER PRIMARY KEY,
                        repository TEXT NOT NULL,
                        hunt_score REAL,
                        total_proxies INTEGER,
                        working_proxies INTEGER,
                        success_rate REAL,
                        hunted_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Create indexes
                indexes = [
                    "CREATE INDEX IF NOT EXISTS idx_ip_port ON proxies(ip, port)",
                    "CREATE INDEX IF NOT EXISTS idx_working ON proxies(is_working)",
                    "CREATE INDEX IF NOT EXISTS idx_hunt_score ON proxies(hunt_score)",
                    "CREATE INDEX IF NOT EXISTS idx_repository ON proxies(repository)",
                    "CREATE INDEX IF NOT EXISTS idx_hunt_results_repo ON hunt_results(repository)"
                ]
                
                for index_sql in indexes:
                    conn.execute(index_sql)
                
            logger.info("🐕 Proxy Hound database initialized")
        except Exception as e:
            logger.error(f"❌ Database initialization failed: {e}")
            raise
    
    def add_hunt_results(self, proxies, batch_size=1000):
        """Add hunting results to database"""
        if not proxies:
            return
            
        logger.info(f"🐕 Recording hunt results: {len(proxies)} proxies")
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("BEGIN TRANSACTION")
                
                for i in range(0, len(proxies), batch_size):
                    batch = proxies[i:i + batch_size]
                    
                    data = [
                        (p.ip, p.port, p.proxy_type, p.source, 
                         p.repository, p.hunt_score, p.country, p.city,
                         p.last_checked, p.is_working, p.response_time)
                        for p in batch
                    ]
                    
                    conn.executemany("""
                        INSERT OR REPLACE INTO proxies 
                        (ip, port, proxy_type, source, repository, hunt_score, country, city, last_checked, is_working, response_time)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, data)
                
                conn.execute("COMMIT")
                logger.info("✅ Hunt results recorded successfully")
        except Exception as e:
            logger.error(f"❌ Failed to record hunt results: {e}")
            raise
    
    def get_working_proxies(self, limit=None):
        """Get working proxies ordered by hunt score and response time"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                query = """
                    SELECT ip, port, proxy_type, source, repository, country, city, last_checked, response_time, hunt_score
                    FROM proxies WHERE is_working = 1 
                    ORDER BY hunt_score DESC, response_time ASC
                """
                
                if limit:
                    query += f" LIMIT {limit}"
                
                results = conn.execute(query).fetchall()
                logger.info(f"🐕 Retrieved {len(results)} working proxies")
                return results
        except Exception as e:
            logger.error(f"❌ Failed to get working proxies: {e}")
            return []
    
    def get_hunt_stats(self):
        """Get hunting statistics"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                total = conn.execute("SELECT COUNT(*) FROM proxies").fetchone()[0]
                working = conn.execute("SELECT COUNT(*) FROM proxies WHERE is_working = 1").fetchone()[0]
                
                # Repository stats with hunt scores
                repo_stats = {}
                for row in conn.execute("""
                    SELECT repository, COUNT(*), AVG(hunt_score), AVG(response_time)
                    FROM proxies WHERE is_working = 1 AND repository IS NOT NULL 
                    GROUP BY repository ORDER BY COUNT(*) DESC LIMIT 10
                """):
                    repo_stats[row[0]] = {
                        "count": row[1], 
                        "avg_hunt_score": round(row[2] or 0, 1),
                        "avg_response_time": round(row[3] or 0, 1)
                    }
                
                # Type stats
                type_stats = {}
                for row in conn.execute("SELECT proxy_type, COUNT(*) FROM proxies WHERE is_working = 1 GROUP BY proxy_type"):
                    type_stats[row[0] or 'unknown'] = row[1]
                
                # Country stats
                country_stats = {}
                for row in conn.execute("SELECT country, COUNT(*) FROM proxies WHERE is_working = 1 AND country IS NOT NULL GROUP BY country ORDER BY COUNT(*) DESC LIMIT 10"):
                    country_stats[row[0]] = row[1]
                
                # City stats
                city_stats = {}
                for row in conn.execute("SELECT city, country, COUNT(*) FROM proxies WHERE is_working = 1 AND city IS NOT NULL GROUP BY city, country ORDER BY COUNT(*) DESC LIMIT 10"):
                    city_key = f"{row[0]}, {row[1]}" if row[1] else row[0]
                    city_stats[city_key] = row[2]
                
                # Hunt success by repository
                hunt_success = {}
                for row in conn.execute("""
                    SELECT repository, AVG(success_rate), COUNT(*)
                    FROM hunt_results GROUP BY repository ORDER BY AVG(success_rate) DESC LIMIT 10
                """):
                    hunt_success[row[0]] = {
                        "avg_success_rate": round(row[1] * 100, 1),
                        "hunts": row[2]
                    }
                
                stats = {
                    "total_proxies": total,
                    "working_proxies": working,
                    "success_rate": round((working / total * 100) if total > 0 else 0, 2),
                    "by_type": type_stats,
                    "by_repository": repo_stats,
                    "by_country": country_stats,
                    "by_city": city_stats,
                    "hunt_success": hunt_success,
                    "geolocated_proxies": conn.execute("SELECT COUNT(*) FROM proxies WHERE is_working = 1 AND country IS NOT NULL").fetchone()[0],
                    "countries_found": len(country_stats),
                    "cities_found": len(city_stats)
                }
                
                logger.info(f"🐕 Hunt stats compiled: {working}/{total} working")
                return stats
        except Exception as e:
            logger.error(f"❌ Failed to get hunt stats: {e}")
            return {"total_proxies": 0, "working_proxies": 0, "success_rate": 0, "by_type": {}, "by_repository": {}, "by_country": {}, "by_city": {}, "hunt_success": {}, "geolocated_proxies": 0, "countries_found": 0, "cities_found": 0}

class ProxyHound:
    """
    Proxy Hound - Advanced Repository Hunter with Geolocation
    
    Multi-factor repository analysis:
    - Scent tracking (recency, activity patterns)
    - Pack behavior analysis (forks, community activity) 
    - Territory mapping (content analysis, file patterns)
    - Hunt success learning (performance feedback)
    - Comprehensive geolocation support
    """
    
    def __init__(self, github_token=None):
        self.github_token = github_token
        self.session = None
        self.hunt_tracker = HuntTracker()
        self.scent_analyzer = ScentAnalyzer()
        self.geolocation_service = GeolocationService()
        self.proxy_pattern = re.compile(r'^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d{1,5})$')
        logger.info("🐕 Proxy Hound with Geolocation initialized - ready to hunt")
    
    async def __aenter__(self):
        headers = {"User-Agent": "ProxyHound/2.1"}
        if self.github_token:
            headers["Authorization"] = f"Bearer {self.github_token}"
            logger.info(f"🔑 GitHub token configured: {self.github_token[:10]}...")
        
        timeout = aiohttp.ClientTimeout(total=20, connect=5)
        connector = aiohttp.TCPConnector(limit=100, ttl_dns_cache=300)
        self.session = aiohttp.ClientSession(headers=headers, timeout=timeout, connector=connector)
        logger.info("🌐 Hunting session established")
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
            logger.info("🔌 Hunting session closed")
    
    async def start_hunt(self, max_pages=3, max_memory_mb=512):
        """Start the proxy hunting expedition"""
        logger.info("🐕 Proxy Hound starting hunting expedition")
        
        all_prey = []  # All found proxies
        
        # Phase 1: Repository hunting
        if self.github_token:
            logger.info("🏞️ Phase 1: Repository territory hunting")
            repo_prey = await self._hunt_repositories(max_pages, max_memory_mb)
            all_prey.extend(repo_prey)
            logger.info(f"  ✅ Repository hunt: {len(repo_prey)} proxies found")
        else:
            logger.warning("⚠️ No GitHub token - skipping repository hunting")
        
        # Phase 2: Backup hunting grounds (only if needed)
        if len(all_prey) < 1000:
            logger.info("🏕️ Phase 2: Backup hunting grounds")
            backup_prey = await self._hunt_backup_grounds()
            all_prey.extend(backup_prey)
            logger.info(f"  ✅ Backup hunt: {len(backup_prey)} proxies found")
        
        # Remove duplicate prey
        logger.info("🔍 Removing duplicate prey...")
        unique_prey = self._remove_duplicate_prey(all_prey)
        
        logger.info(f"🏆 Hunt complete: {len(unique_prey)} unique proxies captured")
        return unique_prey
    
    async def _hunt_repositories(self, max_pages, max_memory_mb):
        """Hunt through GitHub repositories for proxy treasures"""
        logger.info("🐕 Starting repository territory hunt")
        
        # Hunting grounds (search queries)
        hunting_grounds = [
            "free proxies updated language:text pushed:>2024-01-01",
            "working proxy list language:text size:>10",
            "fresh socks proxy language:text",
            "daily proxy update language:text",
            "live proxy collection language:text"
        ]
        
        all_repositories = []
        
        # Search all hunting grounds
        for i, ground in enumerate(hunting_grounds):
            logger.info(f"🌲 Hunting ground {i+1}/{len(hunting_grounds)}: {ground.split()[0]} {ground.split()[1]}")
            
            try:
                repositories = await self._search_hunting_ground(ground, max_pages)
                all_repositories.extend(repositories)
                logger.info(f"  📍 Found {len(repositories)} repositories")
                
                await asyncio.sleep(2)  # Rest between hunts
                
            except Exception as e:
                logger.error(f"  ❌ Hunting ground failed: {e}")
                continue
        
        # Score and rank all found repositories
        scored_repositories = await self._score_and_rank_prey(all_repositories)
        
        # Hunt the best repositories
        all_proxies = []
        hunted_count = 0
        
        for hunt_score, repo in scored_repositories[:25]:  # Hunt top 25
            if hunt_score < 25:  # Skip weak scent trails
                break
                
            logger.info(f"🎯 Hunting: {repo['full_name']} (hunt score: {hunt_score})")
            
            repo_proxies = await self._hunt_repository_content(repo, hunt_score)
            all_proxies.extend(repo_proxies)
            hunted_count += 1
            
            logger.info(f"  🏹 Captured {len(repo_proxies)} proxies")
            
            # Memory management
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            if memory_mb > max_memory_mb and hunted_count >= 10:
                logger.info(f"💾 Memory limit reached ({memory_mb:.1f}MB), ending hunt")
                break
            
            await asyncio.sleep(0.5)
        
        logger.info(f"🏆 Repository hunt complete: {hunted_count} territories, {len(all_proxies)} proxies")
        return all_proxies
    
    async def _search_hunting_ground(self, query, max_pages):
        """Search a specific hunting ground for repositories"""
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
                        logger.warning("    ⚠️ Rate limit hit, resting...")
                        break
                    
                    if response.status != 200:
                        continue
                    
                    data = await response.json()
                    items = data.get("items", [])
                    
                    if not items:
                        break
                    
                    # Pre-filter for quality
                    quality_repos = [repo for repo in items if self._is_quality_territory(repo)]
                    repositories.extend(quality_repos)
                    
                    logger.info(f"    📄 Page {page}: {len(quality_repos)}/{len(items)} quality territories")
                
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"    ❌ Search error: {e}")
                continue
        
        return repositories
    
    def _is_quality_territory(self, repo):
        """Pre-filter repositories for basic quality indicators"""
        # Size check
        size_kb = repo.get('size', 0)
        if size_kb < 10 or size_kb > 50000:
            return False
        
        # Recent activity check
        try:
            updated = datetime.fromisoformat(repo['updated_at'].replace('Z', '+00:00'))
            days_ago = (datetime.now(timezone.utc) - updated).days
            if days_ago > 365:  # No activity in a year
                return False
        except:
            return False
        
        # Basic relevance check
        name = repo.get('name', '').lower, r'.*socks.*\.txt#!/usr/bin/env python3
"""
Proxy Hound - Advanced Repository Hunter v2.1
1. Hunt GitHub repositories using scent tracking and pack behavior analysis
2. Deep content analysis for proxy treasure detection
3. Learning system that improves hunting success over time
4. High-performance parallel proxy validation
5. Comprehensive geolocation support
"""

import asyncio
import json
import logging
import sqlite3
import time
import gzip
import re
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Set
from dataclasses import dataclass, asdict
import random
import ssl
import hashlib

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

# Verified hunting grounds (direct sources as backup)
BACKUP_HUNTING_GROUNDS = [
    "https://raw.githubusercontent.com/r00tee/Proxy-List/main/Socks4.txt", 
    "https://raw.githubusercontent.com/r00tee/Proxy-List/main/Socks5.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/http.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/https.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/socks4.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/socks5.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt"
]

@dataclass
class GeolocationInfo:
    """Comprehensive geolocation information."""
    country: Optional[str] = None
    country_code: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    timezone: Optional[str] = None
    isp: Optional[str] = None
    organization: Optional[str] = None
    as_number: Optional[str] = None
    threat_level: Optional[str] = None

@dataclass
class ProxyInfo:
    """Enhanced proxy information with geolocation."""
    ip: str
    port: int
    proxy_type: str
    source: str
    repository: Optional[str] = None
    hunt_score: float = 0.0
    country: Optional[str] = None
    city: Optional[str] = None
    last_checked: Optional[str] = None
    is_working: bool = False
    response_time: Optional[float] = None
    first_seen: Optional[str] = None
    geolocation: Optional[GeolocationInfo] = None
    
    @property
    def location_string(self) -> str:
        """Get human-readable location string."""
        if self.geolocation:
            parts = []
            if self.geolocation.city:
                parts.append(self.geolocation.city)
            if self.geolocation.region:
                parts.append(self.geolocation.region)
            if self.geolocation.country:
                parts.append(self.geolocation.country)
            return ", ".join(parts) if parts else "Unknown"
        elif self.city and self.country:
            return f"{self.city}, {self.country}"
        elif self.country:
            return self.country
        return "Unknown"

class GeolocationService:
    """Geolocation service with multiple providers and caching."""
    
    def __init__(self, cache_size: int = 10000):
        self.cache: Dict[str, GeolocationInfo] = {}
        self.cache_size = cache_size
        self.session_timeout = aiohttp.ClientTimeout(total=10)
        
        # Multiple geolocation providers (free tier)
        self.providers = [
            {
                'name': 'ip-api',
                'url': 'http://ip-api.com/json/{ip}?fields=status,message,country,countryCode,region,regionName,city,lat,lon,timezone,isp,org,as,mobile,proxy,hosting',
                'rate_limit': 45,  # requests per minute
                'last_request': 0
            },
            {
                'name': 'ipapi.co',
                'url': 'https://ipapi.co/{ip}/json/',
                'rate_limit': 30,  # requests per minute for free tier
                'last_request': 0
            },
            {
                'name': 'ipwhois.app',
                'url': 'http://ipwho.is/{ip}',
                'rate_limit': 1000,  # requests per hour
                'last_request': 0
            }
        ]
    
    async def get_geolocation(self, ip: str) -> Optional[GeolocationInfo]:
        """Get geolocation for IP with caching and fallback providers."""
        
        # Check cache first
        if ip in self.cache:
            logger.debug(f"🗺️ Cache hit for {ip}")
            return self.cache[ip]
        
        # Try each provider until we get a result
        for provider in self.providers:
            try:
                result = await self._query_provider(provider, ip)
                if result:
                    # Cache the result
                    if len(self.cache) >= self.cache_size:
                        # Simple cache eviction - remove oldest entry
                        self.cache.pop(next(iter(self.cache)))
                    
                    self.cache[ip] = result
                    logger.debug(f"🌍 Geolocation found for {ip}: {result.city}, {result.country}")
                    return result
                    
            except Exception as e:
                logger.debug(f"❌ Provider {provider['name']} failed for {ip}: {e}")
                continue
        
        logger.debug(f"⚠️ No geolocation found for {ip}")
        return None
    
    async def _query_provider(self, provider: Dict, ip: str) -> Optional[GeolocationInfo]:
        """Query a specific geolocation provider."""
        
        # Rate limiting
        current_time = time.time()
        time_since_last = current_time - provider['last_request']
        min_interval = 60.0 / provider['rate_limit']  # Convert to seconds between requests
        
        if time_since_last < min_interval:
            sleep_time = min_interval - time_since_last
            await asyncio.sleep(sleep_time)
        
        provider['last_request'] = time.time()
        
        url = provider['url'].format(ip=ip)
        
        async with aiohttp.ClientSession(timeout=self.session_timeout) as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return self._parse_response(provider['name'], data)
                else:
                    logger.debug(f"❌ {provider['name']} returned status {response.status} for {ip}")
                    return None
    
    def _parse_response(self, provider_name: str, data: Dict) -> Optional[GeolocationInfo]:
        """Parse geolocation response based on provider format."""
        
        try:
            if provider_name == 'ip-api':
                if data.get('status') == 'success':
                    return GeolocationInfo(
                        country=data.get('country'),
                        country_code=data.get('countryCode'),
                        region=data.get('regionName'),
                        city=data.get('city'),
                        latitude=data.get('lat'),
                        longitude=data.get('lon'),
                        timezone=data.get('timezone'),
                        isp=data.get('isp'),
                        organization=data.get('org'),
                        as_number=data.get('as'),
                        threat_level='proxy' if data.get('proxy') else 'clean'
                    )
            
            elif provider_name == 'ipapi.co':
                if 'error' not in data:
                    return GeolocationInfo(
                        country=data.get('country_name'),
                        country_code=data.get('country_code'),
                        region=data.get('region'),
                        city=data.get('city'),
                        latitude=data.get('latitude'),
                        longitude=data.get('longitude'),
                        timezone=data.get('timezone'),
                        isp=data.get('org'),
                        organization=data.get('org')
                    )
            
            elif provider_name == 'ipwhois.app':
                if data.get('success'):
                    return GeolocationInfo(
                        country=data.get('country'),
                        country_code=data.get('country_code'),
                        region=data.get('region'),
                        city=data.get('city'),
                        latitude=data.get('latitude'),
                        longitude=data.get('longitude'),
                        timezone=data.get('timezone', {}).get('id') if isinstance(data.get('timezone'), dict) else None,
                        isp=data.get('connection', {}).get('isp') if isinstance(data.get('connection'), dict) else None,
                        organization=data.get('connection', {}).get('org') if isinstance(data.get('connection'), dict) else None,
                        as_number=data.get('connection', {}).get('asn') if isinstance(data.get('connection'), dict) else None
                    )
            
        except Exception as e:
            logger.debug(f"❌ Error parsing {provider_name} response: {e}")
        
        return None

class HuntTracker:
    """Track hunting success to improve future hunts"""
    
    def __init__(self):
        self.successful_hunts = {}
        self.failed_hunts = {}
        self.pack_reputation = {}  # Owner success rates
        logger.info("🐕 Hunt tracker initialized")
    
    def record_hunt_result(self, repo_name, hunt_score, working_proxies, total_proxies):
        """Record how successful a repository hunt was"""
        success_rate = (working_proxies / total_proxies) if total_proxies > 0 else 0
        
        hunt_data = {
            'hunt_score': hunt_score,
            'success_rate': success_rate,
            'working_proxies': working_proxies,
            'total_proxies': total_proxies,
            'hunted_at': datetime.now(timezone.utc).isoformat()
        }
        
        if success_rate > 0.1:  # Good hunt (>10% success)
            self.successful_hunts[repo_name] = hunt_data
            logger.info(f"🏆 Successful hunt recorded: {repo_name} ({success_rate:.1%})")
        else:  # Poor hunt
            self.failed_hunts[repo_name] = hunt_data
            logger.info(f"❌ Failed hunt recorded: {repo_name}")
        
        # Track pack (owner) reputation
        owner = repo_name.split('/')[0]
        if owner not in self.pack_reputation:
            self.pack_reputation[owner] = []
        self.pack_reputation[owner].append(success_rate)
    
    def get_pack_reputation(self, owner):
        """Get average success rate for a repository owner"""
        if owner in self.pack_reputation and self.pack_reputation[owner]:
            return sum(self.pack_reputation[owner]) / len(self.pack_reputation[owner])
        return 0.0

class ScentAnalyzer:
    """Analyze repository 'scent' for quality indicators"""
    
    def __init__(self):
        # Strong scent indicators (likely to have good proxies)
        self.strong_scent_keywords = [
            'working', 'live', 'fresh', 'tested', 'verified', 'daily', 'updated',
            'active', 'new', 'current', 'valid', 'checked'
        ]
        
        # Weak scent indicators (likely stale)
        self.weak_scent_keywords = [
            'old', 'archive', 'deprecated', 'backup', 'mirror', 'copy', 'dead',
            'inactive', 'outdated', 'legacy'
        ]
        
        # Territory markers (file patterns that indicate good hunting grounds)
        self.territory_markers = [
            r'.*working.*proxy.*\.txt$',
            r'.*live.*\.txt$', 
            r'.*fresh.*\.txt$',
            r'.*valid.*\.txt$',
            r'.*\d{4}-\d{2}-\d{2}.*\.txt$',  # Date in filename
            r'.*proxy.*list.*\.txt$',
            r'.*socks.*\.txt$',
            r'.*http.*\.txt$'
        ]
        
        logger.info("🐕 Scent analyzer initialized with hunting patterns")
    
    def analyze_scent_strength(self, repo):
        """Analyze how 'fresh' the repository scent is"""
        scent_score = 0
        
        name = repo.get('name', '').lower()
        desc = repo.get('description', '').lower()
        text = f"{name} {desc}"
        
        # Strong scent detection
        strong_matches = sum(1 for keyword in self.strong_scent_keywords 
                           if keyword in text)
        scent_score += strong_matches * 15
        
        # Weak scent penalty
        weak_matches = sum(1 for keyword in self.weak_scent_keywords 
                         if keyword in text)
        scent_score -= weak_matches * 10
        
        # Territory freshness (last updated)
        try:
            updated = datetime.fromisoformat(repo['updated_at'].replace('Z', '+00:00'))
            days_ago = (datetime.now(timezone.utc) - updated).days
            
            if days_ago < 7:
                scent_score += 50    # Very fresh scent
            elif days_ago < 30:
                scent_score += 30    # Fresh scent
            elif days_ago < 90:
                scent_score += 15    # Fading scent
            else:
                scent_score -= 20    # Cold trail
        except:
            scent_score -= 15
        
        return max(0, scent_score)

class ProxyHoundDatabase:
    """Database for tracking Proxy Hound hunting results"""
    
    def __init__(self, db_path="proxy_hound.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Initialize hunting database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL") 
                conn.execute("PRAGMA cache_size=10000")
                conn.execute("PRAGMA temp_store=MEMORY")
                
                # Create proxies table with hunt tracking
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS proxies (
                        id INTEGER PRIMARY KEY,
                        ip TEXT NOT NULL,
                        port INTEGER NOT NULL,
                        proxy_type TEXT,
                        source TEXT NOT NULL,
                        repository TEXT,
                        hunt_score REAL DEFAULT 0,
                        country TEXT,
                        city TEXT,
                        last_checked TEXT,
                        is_working BOOLEAN DEFAULT 0,
                        response_time REAL,
                        first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(ip, port)
                    )
                """)
                
                # Create hunt results table
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS hunt_results (
                        id INTEGER PRIMARY KEY,
                        repository TEXT NOT NULL,
                        hunt_score REAL,
                        total_proxies INTEGER,
                        working_proxies INTEGER,
                        success_rate REAL,
                        hunted_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Create indexes
                indexes = [
                    "CREATE INDEX IF NOT EXISTS idx_ip_port ON proxies(ip, port)",
                    "CREATE INDEX IF NOT EXISTS idx_working ON proxies(is_working)",
                    "CREATE INDEX IF NOT EXISTS idx_hunt_score ON proxies(hunt_score)",
                    "CREATE INDEX IF NOT EXISTS idx_repository ON proxies(repository)",
                    "CREATE INDEX IF NOT EXISTS idx_hunt_results_repo ON hunt_results(repository)"
                ]
                
                for index_sql in indexes:
                    conn.execute(index_sql)
                
            logger.info("🐕 Proxy Hound database initialized")
        except Exception as e:
            logger.error(f"❌ Database initialization failed: {e}")
            raise
    
    def add_hunt_results(self, proxies, batch_size=1000):
        """Add hunting results to database"""
        if not proxies:
            return
            
        logger.info(f"🐕 Recording hunt results: {len(proxies)} proxies")
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("BEGIN TRANSACTION")
                
                for i in range(0, len(proxies), batch_size):
                    batch = proxies[i:i + batch_size]
                    
                    data = [
                        (p.ip, p.port, p.proxy_type, p.source, 
                         p.repository, p.hunt_score, p.country, p.city,
                         p.last_checked, p.is_working, p.response_time)
                        for p in batch
                    ]
                    
                    conn.executemany("""
                        INSERT OR REPLACE INTO proxies 
                        (ip, port, proxy_type, source, repository, hunt_score, country, city, last_checked, is_working, response_time)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, data)
                
                conn.execute("COMMIT")
                logger.info("✅ Hunt results recorded successfully")
        except Exception as e:
            logger.error(f"❌ Failed to record hunt results: {e}")
            raise
    
    def get_working_proxies(self, limit=None):
        """Get working proxies ordered by hunt score and response time"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                query = """
                    SELECT ip, port, proxy_type, source, repository, country, city, last_checked, response_time, hunt_score
                    FROM proxies WHERE is_working = 1 
                    ORDER BY hunt_score DESC, response_time ASC
                """
                
                if limit:
                    query += f" LIMIT {limit}"
                
                results = conn.execute(query).fetchall()
                logger.info(f"🐕 Retrieved {len(results)} working proxies")
                return results
        except Exception as e:
            logger.error(f"❌ Failed to get working proxies: {e}")
            return []
    
    def get_hunt_stats(self):
        """Get hunting statistics"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                total = conn.execute("SELECT COUNT(*) FROM proxies").fetchone()[0]
                working = conn.execute("SELECT COUNT(*) FROM proxies WHERE is_working = 1").fetchone()[0]
                
                # Repository stats with hunt scores
                repo_stats = {}
                for row in conn.execute("""
                    SELECT repository, COUNT(*), AVG(hunt_score), AVG(response_time)
                    FROM proxies WHERE is_working = 1 AND repository IS NOT NULL 
                    GROUP BY repository ORDER BY COUNT(*) DESC LIMIT 10
                """):
                    repo_stats[row[0]] = {
                        "count": row[1], 
                        "avg_hunt_score": round(row[2] or 0, 1),
                        "avg_response_time": round(row[3] or 0, 1)
                    }
                
                # Type stats
                type_stats = {}
                for row in conn.execute("SELECT proxy_type, COUNT(*) FROM proxies WHERE is_working = 1 GROUP BY proxy_type"):
                    type_stats[row[0] or 'unknown'] = row[1]
                
                # Country stats
                country_stats = {}
                for row in conn.execute("SELECT country, COUNT(*) FROM proxies WHERE is_working = 1 AND country IS NOT NULL GROUP BY country ORDER BY COUNT(*) DESC LIMIT 10"):
                    country_stats[row[0]] = row[1]
                
                # City stats
                city_stats = {}
                for row in conn.execute("SELECT city, country, COUNT(*) FROM proxies WHERE is_working = 1 AND city IS NOT NULL GROUP BY city, country ORDER BY COUNT(*) DESC LIMIT 10"):
                    city_key = f"{row[0]}, {row[1]}" if row[1] else row[0]
                    city_stats[city_key] = row[2]
                
                # Hunt success by repository
                hunt_success = {}
                for row in conn.execute("""
                    SELECT repository, AVG(success_rate), COUNT(*)
                    FROM hunt_results GROUP BY repository ORDER BY AVG(success_rate) DESC LIMIT 10
                """):
                    hunt_success[row[0]] = {
                        "avg_success_rate": round(row[1] * 100, 1),
                        "hunts": row[2]
                    }
                
                stats = {
                    "total_proxies": total,
                    "working_proxies": working,
                    "success_rate": round((working / total * 100) if total > 0 else 0, 2),
                    "by_type": type_stats,
                    "by_repository": repo_stats,
                    "by_country": country_stats,
                    "by_city": city_stats,
                    "hunt_success": hunt_success,
                    "geolocated_proxies": conn.execute("SELECT COUNT(*) FROM proxies WHERE is_working = 1 AND country IS NOT NULL").fetchone()[0],
                    "countries_found": len(country_stats),
                    "cities_found": len(city_stats)
                }
                
                logger.info(f"🐕 Hunt stats compiled: {working}/{total} working")
                return stats
        except Exception as e:
            logger.error(f"❌ Failed to get hunt stats: {e}")
            return {"total_proxies": 0, "working_proxies": 0, "success_rate": 0, "by_type": {}, "by_repository": {}, "by_country": {}, "by_city": {}, "hunt_success": {}, "geolocated_proxies": 0, "countries_found": 0, "cities_found": 0}

class ProxyHound:
    """
    Proxy Hound - Advanced Repository Hunter with Geolocation
    
    Multi-factor repository analysis:
    - Scent tracking (recency, activity patterns)
    - Pack behavior analysis (forks, community activity) 
    - Territory mapping (content analysis, file patterns)
    - Hunt success learning (performance feedback)
    - Comprehensive geolocation support
    """
    
    def __init__(self, github_token=None):
        self.github_token = github_token
        self.session = None
        self.hunt_tracker = HuntTracker()
        self.scent_analyzer = ScentAnalyzer()
        self.geolocation_service = GeolocationService()
        self.proxy_pattern = re.compile(r'^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d{1,5})$')
        logger.info("🐕 Proxy Hound with Geolocation initialized - ready to hunt")
    
    async def __aenter__(self):
        headers = {"User-Agent": "ProxyHound/2.1"}
        if self.github_token:
            headers["Authorization"] = f"Bearer {self.github_token}"
            logger.info(f"🔑 GitHub token configured: {self.github_token[:10]}...")
        
        timeout = aiohttp.ClientTimeout(total=20, connect=5)
        connector = aiohttp.TCPConnector(limit=100, ttl_dns_cache=300)
        self.session = aiohttp.ClientSession(headers=headers, timeout=timeout, connector=connector)
        logger.info("🌐 Hunting session established")
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
            logger.info("🔌 Hunting session closed")
    
    async def start_hunt(self, max_pages=3, max_memory_mb=512):
        """Start the proxy hunting expedition"""
        logger.info("🐕 Proxy Hound starting hunting expedition")
        
        all_prey = []  # All found proxies
        
        # Phase 1: Repository hunting
        if self.github_token:
            logger.info("🏞️ Phase 1: Repository territory hunting")
            repo_prey = await self._hunt_repositories(max_pages, max_memory_mb)
            all_prey.extend(repo_prey)
            logger.info(f"  ✅ Repository hunt: {len(repo_prey)} proxies found")
        else:
            logger.warning("⚠️ No GitHub token - skipping repository hunting")
        
        # Phase 2: Backup hunting grounds (only if needed)
        if len(all_prey) < 1000:
            logger.info("🏕️ Phase 2: Backup hunting grounds")
            backup_prey = await self._hunt_backup_grounds()
            all_prey.extend(backup_prey)
            logger.info(f"  ✅ Backup hunt: {len(backup_prey)} proxies found")
        
        # Remove duplicate prey
        logger.info("🔍 Removing duplicate prey...")
        unique_prey = self._remove_duplicate_prey(all_prey)
        
        logger.info(f"🏆 Hunt complete: {len(unique_prey)} unique proxies captured")
        return unique_prey
    
    async def _hunt_repositories(self, max_pages, max_memory_mb):
        """Hunt through GitHub repositories for proxy treasures"""
        logger.info("🐕 Starting repository territory hunt")
        
        # Hunting grounds (search queries)
        hunting_grounds = [
            "free proxies updated language:text pushed:>2024-01-01",
            "working proxy list language:text size:>10",
            "fresh socks proxy language:text",
            "daily proxy update language:text",
            "live proxy collection language:text"
        ]
        
        all_repositories = []
        
        # Search all hunting grounds
        for i, ground in enumerate(hunting_grounds):
            logger.info(f"🌲 Hunting ground {i+1}/{len(hunting_grounds)}: {ground.split()[0]} {ground.split()[1]}")
            
            try:
                repositories = await self._search_hunting_ground(ground, max_pages)
                all_repositories.extend(repositories)
                logger.info(f"  📍 Found {len(repositories)} repositories")
                
                await asyncio.sleep(2)  # Rest between hunts
                
            except Exception as e:
                logger.error(f"  ❌ Hunting ground failed: {e}")
                continue
        
        # Score and rank all found repositories
        scored_repositories = await self._score_and_rank_prey(all_repositories)
        
        # Hunt the best repositories
        all_proxies = []
        hunted_count = 0
        
        for hunt_score, repo in scored_repositories[:25]:  # Hunt top 25
            if hunt_score < 25:  # Skip weak scent trails
                break
                
            logger.info(f"🎯 Hunting: {repo['full_name']} (hunt score: {hunt_score})")
            
            repo_proxies = await self._hunt_repository_content(repo, hunt_score)
            all_proxies.extend(repo_proxies)
            hunted_count += 1
            
            logger.info(f"  🏹 Captured {len(repo_proxies)} proxies")
            
            # Memory management
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            if memory_mb > max_memory_mb and hunted_count >= 10:
                logger.info(f"💾 Memory limit reached ({memory_mb:.1f}MB), ending hunt")
                break
            
            await asyncio.sleep(0.5)
        
        logger.info(f"🏆 Repository hunt complete: {hunted_count} territories, {len(all_proxies)} proxies")
        return all_proxies
    
    async def _search_hunting_ground(self, query, max_pages):
        """Search a specific hunting ground for repositories"""
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
                        logger.warning("    ⚠️ Rate limit hit, resting...")
                        break
                    
                    if response.status != 200:
                        continue
                    
                    data = await response.json()
                    items = data.get("items", [])
                    
                    if not items:
                        break
                    
                    # Pre-filter for quality
                    quality_repos = [repo for repo in items if self._is_quality_territory(repo)]
                    repositories.extend(quality_repos)
                    
                    logger.info(f"    📄 Page {page}: {len(quality_repos)}/{len(items)} quality territories")
                
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"    ❌ Search error: {e}")
                continue
        
        return repositories
    
    def _is_quality_territory(self, repo):
        """Pre-filter repositories for basic quality indicators"""
        # Size check
        size_kb = repo.get('size', 0)
        if size_kb < 10 or size_kb > 50000:
            return False
        
        # Recent activity check
        try:
            updated = datetime.fromisoformat(repo['updated_at'].replace('Z', '+00:00'))
            days_ago = (datetime.now(timezone.utc) - updated).days
            if days_ago > 365:  # No activity in a year
                return False
        except:
            return False
        
        # Basic relevance check
        name = repo.get('name', '').lower, r'.*http.*\.txt#!/usr/bin/env python3
"""
Proxy Hound - Advanced Repository Hunter v2.1
1. Hunt GitHub repositories using scent tracking and pack behavior analysis
2. Deep content analysis for proxy treasure detection
3. Learning system that improves hunting success over time
4. High-performance parallel proxy validation
5. Comprehensive geolocation support
"""

import asyncio
import json
import logging
import sqlite3
import time
import gzip
import re
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Set
from dataclasses import dataclass, asdict
import random
import ssl
import hashlib

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

# Verified hunting grounds (direct sources as backup)
BACKUP_HUNTING_GROUNDS = [
    "https://raw.githubusercontent.com/r00tee/Proxy-List/main/Socks4.txt", 
    "https://raw.githubusercontent.com/r00tee/Proxy-List/main/Socks5.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/http.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/https.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/socks4.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/socks5.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt"
]

@dataclass
class GeolocationInfo:
    """Comprehensive geolocation information."""
    country: Optional[str] = None
    country_code: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    timezone: Optional[str] = None
    isp: Optional[str] = None
    organization: Optional[str] = None
    as_number: Optional[str] = None
    threat_level: Optional[str] = None

@dataclass
class ProxyInfo:
    """Enhanced proxy information with geolocation."""
    ip: str
    port: int
    proxy_type: str
    source: str
    repository: Optional[str] = None
    hunt_score: float = 0.0
    country: Optional[str] = None
    city: Optional[str] = None
    last_checked: Optional[str] = None
    is_working: bool = False
    response_time: Optional[float] = None
    first_seen: Optional[str] = None
    geolocation: Optional[GeolocationInfo] = None
    
    @property
    def location_string(self) -> str:
        """Get human-readable location string."""
        if self.geolocation:
            parts = []
            if self.geolocation.city:
                parts.append(self.geolocation.city)
            if self.geolocation.region:
                parts.append(self.geolocation.region)
            if self.geolocation.country:
                parts.append(self.geolocation.country)
            return ", ".join(parts) if parts else "Unknown"
        elif self.city and self.country:
            return f"{self.city}, {self.country}"
        elif self.country:
            return self.country
        return "Unknown"

class GeolocationService:
    """Geolocation service with multiple providers and caching."""
    
    def __init__(self, cache_size: int = 10000):
        self.cache: Dict[str, GeolocationInfo] = {}
        self.cache_size = cache_size
        self.session_timeout = aiohttp.ClientTimeout(total=10)
        
        # Multiple geolocation providers (free tier)
        self.providers = [
            {
                'name': 'ip-api',
                'url': 'http://ip-api.com/json/{ip}?fields=status,message,country,countryCode,region,regionName,city,lat,lon,timezone,isp,org,as,mobile,proxy,hosting',
                'rate_limit': 45,  # requests per minute
                'last_request': 0
            },
            {
                'name': 'ipapi.co',
                'url': 'https://ipapi.co/{ip}/json/',
                'rate_limit': 30,  # requests per minute for free tier
                'last_request': 0
            },
            {
                'name': 'ipwhois.app',
                'url': 'http://ipwho.is/{ip}',
                'rate_limit': 1000,  # requests per hour
                'last_request': 0
            }
        ]
    
    async def get_geolocation(self, ip: str) -> Optional[GeolocationInfo]:
        """Get geolocation for IP with caching and fallback providers."""
        
        # Check cache first
        if ip in self.cache:
            logger.debug(f"🗺️ Cache hit for {ip}")
            return self.cache[ip]
        
        # Try each provider until we get a result
        for provider in self.providers:
            try:
                result = await self._query_provider(provider, ip)
                if result:
                    # Cache the result
                    if len(self.cache) >= self.cache_size:
                        # Simple cache eviction - remove oldest entry
                        self.cache.pop(next(iter(self.cache)))
                    
                    self.cache[ip] = result
                    logger.debug(f"🌍 Geolocation found for {ip}: {result.city}, {result.country}")
                    return result
                    
            except Exception as e:
                logger.debug(f"❌ Provider {provider['name']} failed for {ip}: {e}")
                continue
        
        logger.debug(f"⚠️ No geolocation found for {ip}")
        return None
    
    async def _query_provider(self, provider: Dict, ip: str) -> Optional[GeolocationInfo]:
        """Query a specific geolocation provider."""
        
        # Rate limiting
        current_time = time.time()
        time_since_last = current_time - provider['last_request']
        min_interval = 60.0 / provider['rate_limit']  # Convert to seconds between requests
        
        if time_since_last < min_interval:
            sleep_time = min_interval - time_since_last
            await asyncio.sleep(sleep_time)
        
        provider['last_request'] = time.time()
        
        url = provider['url'].format(ip=ip)
        
        async with aiohttp.ClientSession(timeout=self.session_timeout) as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return self._parse_response(provider['name'], data)
                else:
                    logger.debug(f"❌ {provider['name']} returned status {response.status} for {ip}")
                    return None
    
    def _parse_response(self, provider_name: str, data: Dict) -> Optional[GeolocationInfo]:
        """Parse geolocation response based on provider format."""
        
        try:
            if provider_name == 'ip-api':
                if data.get('status') == 'success':
                    return GeolocationInfo(
                        country=data.get('country'),
                        country_code=data.get('countryCode'),
                        region=data.get('regionName'),
                        city=data.get('city'),
                        latitude=data.get('lat'),
                        longitude=data.get('lon'),
                        timezone=data.get('timezone'),
                        isp=data.get('isp'),
                        organization=data.get('org'),
                        as_number=data.get('as'),
                        threat_level='proxy' if data.get('proxy') else 'clean'
                    )
            
            elif provider_name == 'ipapi.co':
                if 'error' not in data:
                    return GeolocationInfo(
                        country=data.get('country_name'),
                        country_code=data.get('country_code'),
                        region=data.get('region'),
                        city=data.get('city'),
                        latitude=data.get('latitude'),
                        longitude=data.get('longitude'),
                        timezone=data.get('timezone'),
                        isp=data.get('org'),
                        organization=data.get('org')
                    )
            
            elif provider_name == 'ipwhois.app':
                if data.get('success'):
                    return GeolocationInfo(
                        country=data.get('country'),
                        country_code=data.get('country_code'),
                        region=data.get('region'),
                        city=data.get('city'),
                        latitude=data.get('latitude'),
                        longitude=data.get('longitude'),
                        timezone=data.get('timezone', {}).get('id') if isinstance(data.get('timezone'), dict) else None,
                        isp=data.get('connection', {}).get('isp') if isinstance(data.get('connection'), dict) else None,
                        organization=data.get('connection', {}).get('org') if isinstance(data.get('connection'), dict) else None,
                        as_number=data.get('connection', {}).get('asn') if isinstance(data.get('connection'), dict) else None
                    )
            
        except Exception as e:
            logger.debug(f"❌ Error parsing {provider_name} response: {e}")
        
        return None

class HuntTracker:
    """Track hunting success to improve future hunts"""
    
    def __init__(self):
        self.successful_hunts = {}
        self.failed_hunts = {}
        self.pack_reputation = {}  # Owner success rates
        logger.info("🐕 Hunt tracker initialized")
    
    def record_hunt_result(self, repo_name, hunt_score, working_proxies, total_proxies):
        """Record how successful a repository hunt was"""
        success_rate = (working_proxies / total_proxies) if total_proxies > 0 else 0
        
        hunt_data = {
            'hunt_score': hunt_score,
            'success_rate': success_rate,
            'working_proxies': working_proxies,
            'total_proxies': total_proxies,
            'hunted_at': datetime.now(timezone.utc).isoformat()
        }
        
        if success_rate > 0.1:  # Good hunt (>10% success)
            self.successful_hunts[repo_name] = hunt_data
            logger.info(f"🏆 Successful hunt recorded: {repo_name} ({success_rate:.1%})")
        else:  # Poor hunt
            self.failed_hunts[repo_name] = hunt_data
            logger.info(f"❌ Failed hunt recorded: {repo_name}")
        
        # Track pack (owner) reputation
        owner = repo_name.split('/')[0]
        if owner not in self.pack_reputation:
            self.pack_reputation[owner] = []
        self.pack_reputation[owner].append(success_rate)
    
    def get_pack_reputation(self, owner):
        """Get average success rate for a repository owner"""
        if owner in self.pack_reputation and self.pack_reputation[owner]:
            return sum(self.pack_reputation[owner]) / len(self.pack_reputation[owner])
        return 0.0

class ScentAnalyzer:
    """Analyze repository 'scent' for quality indicators"""
    
    def __init__(self):
        # Strong scent indicators (likely to have good proxies)
        self.strong_scent_keywords = [
            'working', 'live', 'fresh', 'tested', 'verified', 'daily', 'updated',
            'active', 'new', 'current', 'valid', 'checked'
        ]
        
        # Weak scent indicators (likely stale)
        self.weak_scent_keywords = [
            'old', 'archive', 'deprecated', 'backup', 'mirror', 'copy', 'dead',
            'inactive', 'outdated', 'legacy'
        ]
        
        # Territory markers (file patterns that indicate good hunting grounds)
        self.territory_markers = [
            r'.*working.*proxy.*\.txt$',
            r'.*live.*\.txt$', 
            r'.*fresh.*\.txt$',
            r'.*valid.*\.txt$',
            r'.*\d{4}-\d{2}-\d{2}.*\.txt$',  # Date in filename
            r'.*proxy.*list.*\.txt$',
            r'.*socks.*\.txt$',
            r'.*http.*\.txt$'
        ]
        
        logger.info("🐕 Scent analyzer initialized with hunting patterns")
    
    def analyze_scent_strength(self, repo):
        """Analyze how 'fresh' the repository scent is"""
        scent_score = 0
        
        name = repo.get('name', '').lower()
        desc = repo.get('description', '').lower()
        text = f"{name} {desc}"
        
        # Strong scent detection
        strong_matches = sum(1 for keyword in self.strong_scent_keywords 
                           if keyword in text)
        scent_score += strong_matches * 15
        
        # Weak scent penalty
        weak_matches = sum(1 for keyword in self.weak_scent_keywords 
                         if keyword in text)
        scent_score -= weak_matches * 10
        
        # Territory freshness (last updated)
        try:
            updated = datetime.fromisoformat(repo['updated_at'].replace('Z', '+00:00'))
            days_ago = (datetime.now(timezone.utc) - updated).days
            
            if days_ago < 7:
                scent_score += 50    # Very fresh scent
            elif days_ago < 30:
                scent_score += 30    # Fresh scent
            elif days_ago < 90:
                scent_score += 15    # Fading scent
            else:
                scent_score -= 20    # Cold trail
        except:
            scent_score -= 15
        
        return max(0, scent_score)

class ProxyHoundDatabase:
    """Database for tracking Proxy Hound hunting results"""
    
    def __init__(self, db_path="proxy_hound.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Initialize hunting database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL") 
                conn.execute("PRAGMA cache_size=10000")
                conn.execute("PRAGMA temp_store=MEMORY")
                
                # Create proxies table with hunt tracking
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS proxies (
                        id INTEGER PRIMARY KEY,
                        ip TEXT NOT NULL,
                        port INTEGER NOT NULL,
                        proxy_type TEXT,
                        source TEXT NOT NULL,
                        repository TEXT,
                        hunt_score REAL DEFAULT 0,
                        country TEXT,
                        city TEXT,
                        last_checked TEXT,
                        is_working BOOLEAN DEFAULT 0,
                        response_time REAL,
                        first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(ip, port)
                    )
                """)
                
                # Create hunt results table
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS hunt_results (
                        id INTEGER PRIMARY KEY,
                        repository TEXT NOT NULL,
                        hunt_score REAL,
                        total_proxies INTEGER,
                        working_proxies INTEGER,
                        success_rate REAL,
                        hunted_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Create indexes
                indexes = [
                    "CREATE INDEX IF NOT EXISTS idx_ip_port ON proxies(ip, port)",
                    "CREATE INDEX IF NOT EXISTS idx_working ON proxies(is_working)",
                    "CREATE INDEX IF NOT EXISTS idx_hunt_score ON proxies(hunt_score)",
                    "CREATE INDEX IF NOT EXISTS idx_repository ON proxies(repository)",
                    "CREATE INDEX IF NOT EXISTS idx_hunt_results_repo ON hunt_results(repository)"
                ]
                
                for index_sql in indexes:
                    conn.execute(index_sql)
                
            logger.info("🐕 Proxy Hound database initialized")
        except Exception as e:
            logger.error(f"❌ Database initialization failed: {e}")
            raise
    
    def add_hunt_results(self, proxies, batch_size=1000):
        """Add hunting results to database"""
        if not proxies:
            return
            
        logger.info(f"🐕 Recording hunt results: {len(proxies)} proxies")
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("BEGIN TRANSACTION")
                
                for i in range(0, len(proxies), batch_size):
                    batch = proxies[i:i + batch_size]
                    
                    data = [
                        (p.ip, p.port, p.proxy_type, p.source, 
                         p.repository, p.hunt_score, p.country, p.city,
                         p.last_checked, p.is_working, p.response_time)
                        for p in batch
                    ]
                    
                    conn.executemany("""
                        INSERT OR REPLACE INTO proxies 
                        (ip, port, proxy_type, source, repository, hunt_score, country, city, last_checked, is_working, response_time)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, data)
                
                conn.execute("COMMIT")
                logger.info("✅ Hunt results recorded successfully")
        except Exception as e:
            logger.error(f"❌ Failed to record hunt results: {e}")
            raise
    
    def get_working_proxies(self, limit=None):
        """Get working proxies ordered by hunt score and response time"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                query = """
                    SELECT ip, port, proxy_type, source, repository, country, city, last_checked, response_time, hunt_score
                    FROM proxies WHERE is_working = 1 
                    ORDER BY hunt_score DESC, response_time ASC
                """
                
                if limit:
                    query += f" LIMIT {limit}"
                
                results = conn.execute(query).fetchall()
                logger.info(f"🐕 Retrieved {len(results)} working proxies")
                return results
        except Exception as e:
            logger.error(f"❌ Failed to get working proxies: {e}")
            return []
    
    def get_hunt_stats(self):
        """Get hunting statistics"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                total = conn.execute("SELECT COUNT(*) FROM proxies").fetchone()[0]
                working = conn.execute("SELECT COUNT(*) FROM proxies WHERE is_working = 1").fetchone()[0]
                
                # Repository stats with hunt scores
                repo_stats = {}
                for row in conn.execute("""
                    SELECT repository, COUNT(*), AVG(hunt_score), AVG(response_time)
                    FROM proxies WHERE is_working = 1 AND repository IS NOT NULL 
                    GROUP BY repository ORDER BY COUNT(*) DESC LIMIT 10
                """):
                    repo_stats[row[0]] = {
                        "count": row[1], 
                        "avg_hunt_score": round(row[2] or 0, 1),
                        "avg_response_time": round(row[3] or 0, 1)
                    }
                
                # Type stats
                type_stats = {}
                for row in conn.execute("SELECT proxy_type, COUNT(*) FROM proxies WHERE is_working = 1 GROUP BY proxy_type"):
                    type_stats[row[0] or 'unknown'] = row[1]
                
                # Country stats
                country_stats = {}
                for row in conn.execute("SELECT country, COUNT(*) FROM proxies WHERE is_working = 1 AND country IS NOT NULL GROUP BY country ORDER BY COUNT(*) DESC LIMIT 10"):
                    country_stats[row[0]] = row[1]
                
                # City stats
                city_stats = {}
                for row in conn.execute("SELECT city, country, COUNT(*) FROM proxies WHERE is_working = 1 AND city IS NOT NULL GROUP BY city, country ORDER BY COUNT(*) DESC LIMIT 10"):
                    city_key = f"{row[0]}, {row[1]}" if row[1] else row[0]
                    city_stats[city_key] = row[2]
                
                # Hunt success by repository
                hunt_success = {}
                for row in conn.execute("""
                    SELECT repository, AVG(success_rate), COUNT(*)
                    FROM hunt_results GROUP BY repository ORDER BY AVG(success_rate) DESC LIMIT 10
                """):
                    hunt_success[row[0]] = {
                        "avg_success_rate": round(row[1] * 100, 1),
                        "hunts": row[2]
                    }
                
                stats = {
                    "total_proxies": total,
                    "working_proxies": working,
                    "success_rate": round((working / total * 100) if total > 0 else 0, 2),
                    "by_type": type_stats,
                    "by_repository": repo_stats,
                    "by_country": country_stats,
                    "by_city": city_stats,
                    "hunt_success": hunt_success,
                    "geolocated_proxies": conn.execute("SELECT COUNT(*) FROM proxies WHERE is_working = 1 AND country IS NOT NULL").fetchone()[0],
                    "countries_found": len(country_stats),
                    "cities_found": len(city_stats)
                }
                
                logger.info(f"🐕 Hunt stats compiled: {working}/{total} working")
                return stats
        except Exception as e:
            logger.error(f"❌ Failed to get hunt stats: {e}")
            return {"total_proxies": 0, "working_proxies": 0, "success_rate": 0, "by_type": {}, "by_repository": {}, "by_country": {}, "by_city": {}, "hunt_success": {}, "geolocated_proxies": 0, "countries_found": 0, "cities_found": 0}

class ProxyHound:
    """
    Proxy Hound - Advanced Repository Hunter with Geolocation
    
    Multi-factor repository analysis:
    - Scent tracking (recency, activity patterns)
    - Pack behavior analysis (forks, community activity) 
    - Territory mapping (content analysis, file patterns)
    - Hunt success learning (performance feedback)
    - Comprehensive geolocation support
    """
    
    def __init__(self, github_token=None):
        self.github_token = github_token
        self.session = None
        self.hunt_tracker = HuntTracker()
        self.scent_analyzer = ScentAnalyzer()
        self.geolocation_service = GeolocationService()
        self.proxy_pattern = re.compile(r'^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d{1,5})$')
        logger.info("🐕 Proxy Hound with Geolocation initialized - ready to hunt")
    
    async def __aenter__(self):
        headers = {"User-Agent": "ProxyHound/2.1"}
        if self.github_token:
            headers["Authorization"] = f"Bearer {self.github_token}"
            logger.info(f"🔑 GitHub token configured: {self.github_token[:10]}...")
        
        timeout = aiohttp.ClientTimeout(total=20, connect=5)
        connector = aiohttp.TCPConnector(limit=100, ttl_dns_cache=300)
        self.session = aiohttp.ClientSession(headers=headers, timeout=timeout, connector=connector)
        logger.info("🌐 Hunting session established")
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
            logger.info("🔌 Hunting session closed")
    
    async def start_hunt(self, max_pages=3, max_memory_mb=512):
        """Start the proxy hunting expedition"""
        logger.info("🐕 Proxy Hound starting hunting expedition")
        
        all_prey = []  # All found proxies
        
        # Phase 1: Repository hunting
        if self.github_token:
            logger.info("🏞️ Phase 1: Repository territory hunting")
            repo_prey = await self._hunt_repositories(max_pages, max_memory_mb)
            all_prey.extend(repo_prey)
            logger.info(f"  ✅ Repository hunt: {len(repo_prey)} proxies found")
        else:
            logger.warning("⚠️ No GitHub token - skipping repository hunting")
        
        # Phase 2: Backup hunting grounds (only if needed)
        if len(all_prey) < 1000:
            logger.info("🏕️ Phase 2: Backup hunting grounds")
            backup_prey = await self._hunt_backup_grounds()
            all_prey.extend(backup_prey)
            logger.info(f"  ✅ Backup hunt: {len(backup_prey)} proxies found")
        
        # Remove duplicate prey
        logger.info("🔍 Removing duplicate prey...")
        unique_prey = self._remove_duplicate_prey(all_prey)
        
        logger.info(f"🏆 Hunt complete: {len(unique_prey)} unique proxies captured")
        return unique_prey
    
    async def _hunt_repositories(self, max_pages, max_memory_mb):
        """Hunt through GitHub repositories for proxy treasures"""
        logger.info("🐕 Starting repository territory hunt")
        
        # Hunting grounds (search queries)
        hunting_grounds = [
            "free proxies updated language:text pushed:>2024-01-01",
            "working proxy list language:text size:>10",
            "fresh socks proxy language:text",
            "daily proxy update language:text",
            "live proxy collection language:text"
        ]
        
        all_repositories = []
        
        # Search all hunting grounds
        for i, ground in enumerate(hunting_grounds):
            logger.info(f"🌲 Hunting ground {i+1}/{len(hunting_grounds)}: {ground.split()[0]} {ground.split()[1]}")
            
            try:
                repositories = await self._search_hunting_ground(ground, max_pages)
                all_repositories.extend(repositories)
                logger.info(f"  📍 Found {len(repositories)} repositories")
                
                await asyncio.sleep(2)  # Rest between hunts
                
            except Exception as e:
                logger.error(f"  ❌ Hunting ground failed: {e}")
                continue
        
        # Score and rank all found repositories
        scored_repositories = await self._score_and_rank_prey(all_repositories)
        
        # Hunt the best repositories
        all_proxies = []
        hunted_count = 0
        
        for hunt_score, repo in scored_repositories[:25]:  # Hunt top 25
            if hunt_score < 25:  # Skip weak scent trails
                break
                
            logger.info(f"🎯 Hunting: {repo['full_name']} (hunt score: {hunt_score})")
            
            repo_proxies = await self._hunt_repository_content(repo, hunt_score)
            all_proxies.extend(repo_proxies)
            hunted_count += 1
            
            logger.info(f"  🏹 Captured {len(repo_proxies)} proxies")
            
            # Memory management
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            if memory_mb > max_memory_mb and hunted_count >= 10:
                logger.info(f"💾 Memory limit reached ({memory_mb:.1f}MB), ending hunt")
                break
            
            await asyncio.sleep(0.5)
        
        logger.info(f"🏆 Repository hunt complete: {hunted_count} territories, {len(all_proxies)} proxies")
        return all_proxies
    
    async def _search_hunting_ground(self, query, max_pages):
        """Search a specific hunting ground for repositories"""
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
                        logger.warning("    ⚠️ Rate limit hit, resting...")
                        break
                    
                    if response.status != 200:
                        continue
                    
                    data = await response.json()
                    items = data.get("items", [])
                    
                    if not items:
                        break
                    
                    # Pre-filter for quality
                    quality_repos = [repo for repo in items if self._is_quality_territory(repo)]
                    repositories.extend(quality_repos)
                    
                    logger.info(f"    📄 Page {page}: {len(quality_repos)}/{len(items)} quality territories")
                
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"    ❌ Search error: {e}")
                continue
        
        return repositories
    
    def _is_quality_territory(self, repo):
        """Pre-filter repositories for basic quality indicators"""
        # Size check
        size_kb = repo.get('size', 0)
        if size_kb < 10 or size_kb > 50000:
            return False
        
        # Recent activity check
        try:
            updated = datetime.fromisoformat(repo['updated_at'].replace('Z', '+00:00'))
            days_ago = (datetime.now(timezone.utc) - updated).days
            if days_ago > 365:  # No activity in a year
                return False
        except:
            return False
        
        # Basic relevance check
        name = repo.get('name', '').lower,
            r'^proxies?\.txt#!/usr/bin/env python3
"""
Proxy Hound - Advanced Repository Hunter v2.1
1. Hunt GitHub repositories using scent tracking and pack behavior analysis
2. Deep content analysis for proxy treasure detection
3. Learning system that improves hunting success over time
4. High-performance parallel proxy validation
5. Comprehensive geolocation support
"""

import asyncio
import json
import logging
import sqlite3
import time
import gzip
import re
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Set
from dataclasses import dataclass, asdict
import random
import ssl
import hashlib

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

# Verified hunting grounds (direct sources as backup)
BACKUP_HUNTING_GROUNDS = [
    "https://raw.githubusercontent.com/r00tee/Proxy-List/main/Socks4.txt", 
    "https://raw.githubusercontent.com/r00tee/Proxy-List/main/Socks5.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/http.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/https.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/socks4.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/socks5.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt"
]

@dataclass
class GeolocationInfo:
    """Comprehensive geolocation information."""
    country: Optional[str] = None
    country_code: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    timezone: Optional[str] = None
    isp: Optional[str] = None
    organization: Optional[str] = None
    as_number: Optional[str] = None
    threat_level: Optional[str] = None

@dataclass
class ProxyInfo:
    """Enhanced proxy information with geolocation."""
    ip: str
    port: int
    proxy_type: str
    source: str
    repository: Optional[str] = None
    hunt_score: float = 0.0
    country: Optional[str] = None
    city: Optional[str] = None
    last_checked: Optional[str] = None
    is_working: bool = False
    response_time: Optional[float] = None
    first_seen: Optional[str] = None
    geolocation: Optional[GeolocationInfo] = None
    
    @property
    def location_string(self) -> str:
        """Get human-readable location string."""
        if self.geolocation:
            parts = []
            if self.geolocation.city:
                parts.append(self.geolocation.city)
            if self.geolocation.region:
                parts.append(self.geolocation.region)
            if self.geolocation.country:
                parts.append(self.geolocation.country)
            return ", ".join(parts) if parts else "Unknown"
        elif self.city and self.country:
            return f"{self.city}, {self.country}"
        elif self.country:
            return self.country
        return "Unknown"

class GeolocationService:
    """Geolocation service with multiple providers and caching."""
    
    def __init__(self, cache_size: int = 10000):
        self.cache: Dict[str, GeolocationInfo] = {}
        self.cache_size = cache_size
        self.session_timeout = aiohttp.ClientTimeout(total=10)
        
        # Multiple geolocation providers (free tier)
        self.providers = [
            {
                'name': 'ip-api',
                'url': 'http://ip-api.com/json/{ip}?fields=status,message,country,countryCode,region,regionName,city,lat,lon,timezone,isp,org,as,mobile,proxy,hosting',
                'rate_limit': 45,  # requests per minute
                'last_request': 0
            },
            {
                'name': 'ipapi.co',
                'url': 'https://ipapi.co/{ip}/json/',
                'rate_limit': 30,  # requests per minute for free tier
                'last_request': 0
            },
            {
                'name': 'ipwhois.app',
                'url': 'http://ipwho.is/{ip}',
                'rate_limit': 1000,  # requests per hour
                'last_request': 0
            }
        ]
    
    async def get_geolocation(self, ip: str) -> Optional[GeolocationInfo]:
        """Get geolocation for IP with caching and fallback providers."""
        
        # Check cache first
        if ip in self.cache:
            logger.debug(f"🗺️ Cache hit for {ip}")
            return self.cache[ip]
        
        # Try each provider until we get a result
        for provider in self.providers:
            try:
                result = await self._query_provider(provider, ip)
                if result:
                    # Cache the result
                    if len(self.cache) >= self.cache_size:
                        # Simple cache eviction - remove oldest entry
                        self.cache.pop(next(iter(self.cache)))
                    
                    self.cache[ip] = result
                    logger.debug(f"🌍 Geolocation found for {ip}: {result.city}, {result.country}")
                    return result
                    
            except Exception as e:
                logger.debug(f"❌ Provider {provider['name']} failed for {ip}: {e}")
                continue
        
        logger.debug(f"⚠️ No geolocation found for {ip}")
        return None
    
    async def _query_provider(self, provider: Dict, ip: str) -> Optional[GeolocationInfo]:
        """Query a specific geolocation provider."""
        
        # Rate limiting
        current_time = time.time()
        time_since_last = current_time - provider['last_request']
        min_interval = 60.0 / provider['rate_limit']  # Convert to seconds between requests
        
        if time_since_last < min_interval:
            sleep_time = min_interval - time_since_last
            await asyncio.sleep(sleep_time)
        
        provider['last_request'] = time.time()
        
        url = provider['url'].format(ip=ip)
        
        async with aiohttp.ClientSession(timeout=self.session_timeout) as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return self._parse_response(provider['name'], data)
                else:
                    logger.debug(f"❌ {provider['name']} returned status {response.status} for {ip}")
                    return None
    
    def _parse_response(self, provider_name: str, data: Dict) -> Optional[GeolocationInfo]:
        """Parse geolocation response based on provider format."""
        
        try:
            if provider_name == 'ip-api':
                if data.get('status') == 'success':
                    return GeolocationInfo(
                        country=data.get('country'),
                        country_code=data.get('countryCode'),
                        region=data.get('regionName'),
                        city=data.get('city'),
                        latitude=data.get('lat'),
                        longitude=data.get('lon'),
                        timezone=data.get('timezone'),
                        isp=data.get('isp'),
                        organization=data.get('org'),
                        as_number=data.get('as'),
                        threat_level='proxy' if data.get('proxy') else 'clean'
                    )
            
            elif provider_name == 'ipapi.co':
                if 'error' not in data:
                    return GeolocationInfo(
                        country=data.get('country_name'),
                        country_code=data.get('country_code'),
                        region=data.get('region'),
                        city=data.get('city'),
                        latitude=data.get('latitude'),
                        longitude=data.get('longitude'),
                        timezone=data.get('timezone'),
                        isp=data.get('org'),
                        organization=data.get('org')
                    )
            
            elif provider_name == 'ipwhois.app':
                if data.get('success'):
                    return GeolocationInfo(
                        country=data.get('country'),
                        country_code=data.get('country_code'),
                        region=data.get('region'),
                        city=data.get('city'),
                        latitude=data.get('latitude'),
                        longitude=data.get('longitude'),
                        timezone=data.get('timezone', {}).get('id') if isinstance(data.get('timezone'), dict) else None,
                        isp=data.get('connection', {}).get('isp') if isinstance(data.get('connection'), dict) else None,
                        organization=data.get('connection', {}).get('org') if isinstance(data.get('connection'), dict) else None,
                        as_number=data.get('connection', {}).get('asn') if isinstance(data.get('connection'), dict) else None
                    )
            
        except Exception as e:
            logger.debug(f"❌ Error parsing {provider_name} response: {e}")
        
        return None

class HuntTracker:
    """Track hunting success to improve future hunts"""
    
    def __init__(self):
        self.successful_hunts = {}
        self.failed_hunts = {}
        self.pack_reputation = {}  # Owner success rates
        logger.info("🐕 Hunt tracker initialized")
    
    def record_hunt_result(self, repo_name, hunt_score, working_proxies, total_proxies):
        """Record how successful a repository hunt was"""
        success_rate = (working_proxies / total_proxies) if total_proxies > 0 else 0
        
        hunt_data = {
            'hunt_score': hunt_score,
            'success_rate': success_rate,
            'working_proxies': working_proxies,
            'total_proxies': total_proxies,
            'hunted_at': datetime.now(timezone.utc).isoformat()
        }
        
        if success_rate > 0.1:  # Good hunt (>10% success)
            self.successful_hunts[repo_name] = hunt_data
            logger.info(f"🏆 Successful hunt recorded: {repo_name} ({success_rate:.1%})")
        else:  # Poor hunt
            self.failed_hunts[repo_name] = hunt_data
            logger.info(f"❌ Failed hunt recorded: {repo_name}")
        
        # Track pack (owner) reputation
        owner = repo_name.split('/')[0]
        if owner not in self.pack_reputation:
            self.pack_reputation[owner] = []
        self.pack_reputation[owner].append(success_rate)
    
    def get_pack_reputation(self, owner):
        """Get average success rate for a repository owner"""
        if owner in self.pack_reputation and self.pack_reputation[owner]:
            return sum(self.pack_reputation[owner]) / len(self.pack_reputation[owner])
        return 0.0

class ScentAnalyzer:
    """Analyze repository 'scent' for quality indicators"""
    
    def __init__(self):
        # Strong scent indicators (likely to have good proxies)
        self.strong_scent_keywords = [
            'working', 'live', 'fresh', 'tested', 'verified', 'daily', 'updated',
            'active', 'new', 'current', 'valid', 'checked'
        ]
        
        # Weak scent indicators (likely stale)
        self.weak_scent_keywords = [
            'old', 'archive', 'deprecated', 'backup', 'mirror', 'copy', 'dead',
            'inactive', 'outdated', 'legacy'
        ]
        
        # Territory markers (file patterns that indicate good hunting grounds)
        self.territory_markers = [
            r'.*working.*proxy.*\.txt$',
            r'.*live.*\.txt$', 
            r'.*fresh.*\.txt$',
            r'.*valid.*\.txt$',
            r'.*\d{4}-\d{2}-\d{2}.*\.txt$',  # Date in filename
            r'.*proxy.*list.*\.txt$',
            r'.*socks.*\.txt$',
            r'.*http.*\.txt$'
        ]
        
        logger.info("🐕 Scent analyzer initialized with hunting patterns")
    
    def analyze_scent_strength(self, repo):
        """Analyze how 'fresh' the repository scent is"""
        scent_score = 0
        
        name = repo.get('name', '').lower()
        desc = repo.get('description', '').lower()
        text = f"{name} {desc}"
        
        # Strong scent detection
        strong_matches = sum(1 for keyword in self.strong_scent_keywords 
                           if keyword in text)
        scent_score += strong_matches * 15
        
        # Weak scent penalty
        weak_matches = sum(1 for keyword in self.weak_scent_keywords 
                         if keyword in text)
        scent_score -= weak_matches * 10
        
        # Territory freshness (last updated)
        try:
            updated = datetime.fromisoformat(repo['updated_at'].replace('Z', '+00:00'))
            days_ago = (datetime.now(timezone.utc) - updated).days
            
            if days_ago < 7:
                scent_score += 50    # Very fresh scent
            elif days_ago < 30:
                scent_score += 30    # Fresh scent
            elif days_ago < 90:
                scent_score += 15    # Fading scent
            else:
                scent_score -= 20    # Cold trail
        except:
            scent_score -= 15
        
        return max(0, scent_score)

class ProxyHoundDatabase:
    """Database for tracking Proxy Hound hunting results"""
    
    def __init__(self, db_path="proxy_hound.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Initialize hunting database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL") 
                conn.execute("PRAGMA cache_size=10000")
                conn.execute("PRAGMA temp_store=MEMORY")
                
                # Create proxies table with hunt tracking
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS proxies (
                        id INTEGER PRIMARY KEY,
                        ip TEXT NOT NULL,
                        port INTEGER NOT NULL,
                        proxy_type TEXT,
                        source TEXT NOT NULL,
                        repository TEXT,
                        hunt_score REAL DEFAULT 0,
                        country TEXT,
                        city TEXT,
                        last_checked TEXT,
                        is_working BOOLEAN DEFAULT 0,
                        response_time REAL,
                        first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(ip, port)
                    )
                """)
                
                # Create hunt results table
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS hunt_results (
                        id INTEGER PRIMARY KEY,
                        repository TEXT NOT NULL,
                        hunt_score REAL,
                        total_proxies INTEGER,
                        working_proxies INTEGER,
                        success_rate REAL,
                        hunted_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Create indexes
                indexes = [
                    "CREATE INDEX IF NOT EXISTS idx_ip_port ON proxies(ip, port)",
                    "CREATE INDEX IF NOT EXISTS idx_working ON proxies(is_working)",
                    "CREATE INDEX IF NOT EXISTS idx_hunt_score ON proxies(hunt_score)",
                    "CREATE INDEX IF NOT EXISTS idx_repository ON proxies(repository)",
                    "CREATE INDEX IF NOT EXISTS idx_hunt_results_repo ON hunt_results(repository)"
                ]
                
                for index_sql in indexes:
                    conn.execute(index_sql)
                
            logger.info("🐕 Proxy Hound database initialized")
        except Exception as e:
            logger.error(f"❌ Database initialization failed: {e}")
            raise
    
    def add_hunt_results(self, proxies, batch_size=1000):
        """Add hunting results to database"""
        if not proxies:
            return
            
        logger.info(f"🐕 Recording hunt results: {len(proxies)} proxies")
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("BEGIN TRANSACTION")
                
                for i in range(0, len(proxies), batch_size):
                    batch = proxies[i:i + batch_size]
                    
                    data = [
                        (p.ip, p.port, p.proxy_type, p.source, 
                         p.repository, p.hunt_score, p.country, p.city,
                         p.last_checked, p.is_working, p.response_time)
                        for p in batch
                    ]
                    
                    conn.executemany("""
                        INSERT OR REPLACE INTO proxies 
                        (ip, port, proxy_type, source, repository, hunt_score, country, city, last_checked, is_working, response_time)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, data)
                
                conn.execute("COMMIT")
                logger.info("✅ Hunt results recorded successfully")
        except Exception as e:
            logger.error(f"❌ Failed to record hunt results: {e}")
            raise
    
    def get_working_proxies(self, limit=None):
        """Get working proxies ordered by hunt score and response time"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                query = """
                    SELECT ip, port, proxy_type, source, repository, country, city, last_checked, response_time, hunt_score
                    FROM proxies WHERE is_working = 1 
                    ORDER BY hunt_score DESC, response_time ASC
                """
                
                if limit:
                    query += f" LIMIT {limit}"
                
                results = conn.execute(query).fetchall()
                logger.info(f"🐕 Retrieved {len(results)} working proxies")
                return results
        except Exception as e:
            logger.error(f"❌ Failed to get working proxies: {e}")
            return []
    
    def get_hunt_stats(self):
        """Get hunting statistics"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                total = conn.execute("SELECT COUNT(*) FROM proxies").fetchone()[0]
                working = conn.execute("SELECT COUNT(*) FROM proxies WHERE is_working = 1").fetchone()[0]
                
                # Repository stats with hunt scores
                repo_stats = {}
                for row in conn.execute("""
                    SELECT repository, COUNT(*), AVG(hunt_score), AVG(response_time)
                    FROM proxies WHERE is_working = 1 AND repository IS NOT NULL 
                    GROUP BY repository ORDER BY COUNT(*) DESC LIMIT 10
                """):
                    repo_stats[row[0]] = {
                        "count": row[1], 
                        "avg_hunt_score": round(row[2] or 0, 1),
                        "avg_response_time": round(row[3] or 0, 1)
                    }
                
                # Type stats
                type_stats = {}
                for row in conn.execute("SELECT proxy_type, COUNT(*) FROM proxies WHERE is_working = 1 GROUP BY proxy_type"):
                    type_stats[row[0] or 'unknown'] = row[1]
                
                # Country stats
                country_stats = {}
                for row in conn.execute("SELECT country, COUNT(*) FROM proxies WHERE is_working = 1 AND country IS NOT NULL GROUP BY country ORDER BY COUNT(*) DESC LIMIT 10"):
                    country_stats[row[0]] = row[1]
                
                # City stats
                city_stats = {}
                for row in conn.execute("SELECT city, country, COUNT(*) FROM proxies WHERE is_working = 1 AND city IS NOT NULL GROUP BY city, country ORDER BY COUNT(*) DESC LIMIT 10"):
                    city_key = f"{row[0]}, {row[1]}" if row[1] else row[0]
                    city_stats[city_key] = row[2]
                
                # Hunt success by repository
                hunt_success = {}
                for row in conn.execute("""
                    SELECT repository, AVG(success_rate), COUNT(*)
                    FROM hunt_results GROUP BY repository ORDER BY AVG(success_rate) DESC LIMIT 10
                """):
                    hunt_success[row[0]] = {
                        "avg_success_rate": round(row[1] * 100, 1),
                        "hunts": row[2]
                    }
                
                stats = {
                    "total_proxies": total,
                    "working_proxies": working,
                    "success_rate": round((working / total * 100) if total > 0 else 0, 2),
                    "by_type": type_stats,
                    "by_repository": repo_stats,
                    "by_country": country_stats,
                    "by_city": city_stats,
                    "hunt_success": hunt_success,
                    "geolocated_proxies": conn.execute("SELECT COUNT(*) FROM proxies WHERE is_working = 1 AND country IS NOT NULL").fetchone()[0],
                    "countries_found": len(country_stats),
                    "cities_found": len(city_stats)
                }
                
                logger.info(f"🐕 Hunt stats compiled: {working}/{total} working")
                return stats
        except Exception as e:
            logger.error(f"❌ Failed to get hunt stats: {e}")
            return {"total_proxies": 0, "working_proxies": 0, "success_rate": 0, "by_type": {}, "by_repository": {}, "by_country": {}, "by_city": {}, "hunt_success": {}, "geolocated_proxies": 0, "countries_found": 0, "cities_found": 0}

class ProxyHound:
    """
    Proxy Hound - Advanced Repository Hunter with Geolocation
    
    Multi-factor repository analysis:
    - Scent tracking (recency, activity patterns)
    - Pack behavior analysis (forks, community activity) 
    - Territory mapping (content analysis, file patterns)
    - Hunt success learning (performance feedback)
    - Comprehensive geolocation support
    """
    
    def __init__(self, github_token=None):
        self.github_token = github_token
        self.session = None
        self.hunt_tracker = HuntTracker()
        self.scent_analyzer = ScentAnalyzer()
        self.geolocation_service = GeolocationService()
        self.proxy_pattern = re.compile(r'^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d{1,5})$')
        logger.info("🐕 Proxy Hound with Geolocation initialized - ready to hunt")
    
    async def __aenter__(self):
        headers = {"User-Agent": "ProxyHound/2.1"}
        if self.github_token:
            headers["Authorization"] = f"Bearer {self.github_token}"
            logger.info(f"🔑 GitHub token configured: {self.github_token[:10]}...")
        
        timeout = aiohttp.ClientTimeout(total=20, connect=5)
        connector = aiohttp.TCPConnector(limit=100, ttl_dns_cache=300)
        self.session = aiohttp.ClientSession(headers=headers, timeout=timeout, connector=connector)
        logger.info("🌐 Hunting session established")
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
            logger.info("🔌 Hunting session closed")
    
    async def start_hunt(self, max_pages=3, max_memory_mb=512):
        """Start the proxy hunting expedition"""
        logger.info("🐕 Proxy Hound starting hunting expedition")
        
        all_prey = []  # All found proxies
        
        # Phase 1: Repository hunting
        if self.github_token:
            logger.info("🏞️ Phase 1: Repository territory hunting")
            repo_prey = await self._hunt_repositories(max_pages, max_memory_mb)
            all_prey.extend(repo_prey)
            logger.info(f"  ✅ Repository hunt: {len(repo_prey)} proxies found")
        else:
            logger.warning("⚠️ No GitHub token - skipping repository hunting")
        
        # Phase 2: Backup hunting grounds (only if needed)
        if len(all_prey) < 1000:
            logger.info("🏕️ Phase 2: Backup hunting grounds")
            backup_prey = await self._hunt_backup_grounds()
            all_prey.extend(backup_prey)
            logger.info(f"  ✅ Backup hunt: {len(backup_prey)} proxies found")
        
        # Remove duplicate prey
        logger.info("🔍 Removing duplicate prey...")
        unique_prey = self._remove_duplicate_prey(all_prey)
        
        logger.info(f"🏆 Hunt complete: {len(unique_prey)} unique proxies captured")
        return unique_prey
    
    async def _hunt_repositories(self, max_pages, max_memory_mb):
        """Hunt through GitHub repositories for proxy treasures"""
        logger.info("🐕 Starting repository territory hunt")
        
        # Hunting grounds (search queries)
        hunting_grounds = [
            "free proxies updated language:text pushed:>2024-01-01",
            "working proxy list language:text size:>10",
            "fresh socks proxy language:text",
            "daily proxy update language:text",
            "live proxy collection language:text"
        ]
        
        all_repositories = []
        
        # Search all hunting grounds
        for i, ground in enumerate(hunting_grounds):
            logger.info(f"🌲 Hunting ground {i+1}/{len(hunting_grounds)}: {ground.split()[0]} {ground.split()[1]}")
            
            try:
                repositories = await self._search_hunting_ground(ground, max_pages)
                all_repositories.extend(repositories)
                logger.info(f"  📍 Found {len(repositories)} repositories")
                
                await asyncio.sleep(2)  # Rest between hunts
                
            except Exception as e:
                logger.error(f"  ❌ Hunting ground failed: {e}")
                continue
        
        # Score and rank all found repositories
        scored_repositories = await self._score_and_rank_prey(all_repositories)
        
        # Hunt the best repositories
        all_proxies = []
        hunted_count = 0
        
        for hunt_score, repo in scored_repositories[:25]:  # Hunt top 25
            if hunt_score < 25:  # Skip weak scent trails
                break
                
            logger.info(f"🎯 Hunting: {repo['full_name']} (hunt score: {hunt_score})")
            
            repo_proxies = await self._hunt_repository_content(repo, hunt_score)
            all_proxies.extend(repo_proxies)
            hunted_count += 1
            
            logger.info(f"  🏹 Captured {len(repo_proxies)} proxies")
            
            # Memory management
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            if memory_mb > max_memory_mb and hunted_count >= 10:
                logger.info(f"💾 Memory limit reached ({memory_mb:.1f}MB), ending hunt")
                break
            
            await asyncio.sleep(0.5)
        
        logger.info(f"🏆 Repository hunt complete: {hunted_count} territories, {len(all_proxies)} proxies")
        return all_proxies
    
    async def _search_hunting_ground(self, query, max_pages):
        """Search a specific hunting ground for repositories"""
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
                        logger.warning("    ⚠️ Rate limit hit, resting...")
                        break
                    
                    if response.status != 200:
                        continue
                    
                    data = await response.json()
                    items = data.get("items", [])
                    
                    if not items:
                        break
                    
                    # Pre-filter for quality
                    quality_repos = [repo for repo in items if self._is_quality_territory(repo)]
                    repositories.extend(quality_repos)
                    
                    logger.info(f"    📄 Page {page}: {len(quality_repos)}/{len(items)} quality territories")
                
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"    ❌ Search error: {e}")
                continue
        
        return repositories
    
    def _is_quality_territory(self, repo):
        """Pre-filter repositories for basic quality indicators"""
        # Size check
        size_kb = repo.get('size', 0)
        if size_kb < 10 or size_kb > 50000:
            return False
        
        # Recent activity check
        try:
            updated = datetime.fromisoformat(repo['updated_at'].replace('Z', '+00:00'))
            days_ago = (datetime.now(timezone.utc) - updated).days
            if days_ago > 365:  # No activity in a year
                return False
        except:
            return False
        
        # Basic relevance check
        name = repo.get('name', '').lower, r'^.*list.*\.txt#!/usr/bin/env python3
"""
Proxy Hound - Advanced Repository Hunter v2.1
1. Hunt GitHub repositories using scent tracking and pack behavior analysis
2. Deep content analysis for proxy treasure detection
3. Learning system that improves hunting success over time
4. High-performance parallel proxy validation
5. Comprehensive geolocation support
"""

import asyncio
import json
import logging
import sqlite3
import time
import gzip
import re
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Set
from dataclasses import dataclass, asdict
import random
import ssl
import hashlib

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

# Verified hunting grounds (direct sources as backup)
BACKUP_HUNTING_GROUNDS = [
    "https://raw.githubusercontent.com/r00tee/Proxy-List/main/Socks4.txt", 
    "https://raw.githubusercontent.com/r00tee/Proxy-List/main/Socks5.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/http.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/https.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/socks4.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/socks5.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt"
]

@dataclass
class GeolocationInfo:
    """Comprehensive geolocation information."""
    country: Optional[str] = None
    country_code: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    timezone: Optional[str] = None
    isp: Optional[str] = None
    organization: Optional[str] = None
    as_number: Optional[str] = None
    threat_level: Optional[str] = None

@dataclass
class ProxyInfo:
    """Enhanced proxy information with geolocation."""
    ip: str
    port: int
    proxy_type: str
    source: str
    repository: Optional[str] = None
    hunt_score: float = 0.0
    country: Optional[str] = None
    city: Optional[str] = None
    last_checked: Optional[str] = None
    is_working: bool = False
    response_time: Optional[float] = None
    first_seen: Optional[str] = None
    geolocation: Optional[GeolocationInfo] = None
    
    @property
    def location_string(self) -> str:
        """Get human-readable location string."""
        if self.geolocation:
            parts = []
            if self.geolocation.city:
                parts.append(self.geolocation.city)
            if self.geolocation.region:
                parts.append(self.geolocation.region)
            if self.geolocation.country:
                parts.append(self.geolocation.country)
            return ", ".join(parts) if parts else "Unknown"
        elif self.city and self.country:
            return f"{self.city}, {self.country}"
        elif self.country:
            return self.country
        return "Unknown"

class GeolocationService:
    """Geolocation service with multiple providers and caching."""
    
    def __init__(self, cache_size: int = 10000):
        self.cache: Dict[str, GeolocationInfo] = {}
        self.cache_size = cache_size
        self.session_timeout = aiohttp.ClientTimeout(total=10)
        
        # Multiple geolocation providers (free tier)
        self.providers = [
            {
                'name': 'ip-api',
                'url': 'http://ip-api.com/json/{ip}?fields=status,message,country,countryCode,region,regionName,city,lat,lon,timezone,isp,org,as,mobile,proxy,hosting',
                'rate_limit': 45,  # requests per minute
                'last_request': 0
            },
            {
                'name': 'ipapi.co',
                'url': 'https://ipapi.co/{ip}/json/',
                'rate_limit': 30,  # requests per minute for free tier
                'last_request': 0
            },
            {
                'name': 'ipwhois.app',
                'url': 'http://ipwho.is/{ip}',
                'rate_limit': 1000,  # requests per hour
                'last_request': 0
            }
        ]
    
    async def get_geolocation(self, ip: str) -> Optional[GeolocationInfo]:
        """Get geolocation for IP with caching and fallback providers."""
        
        # Check cache first
        if ip in self.cache:
            logger.debug(f"🗺️ Cache hit for {ip}")
            return self.cache[ip]
        
        # Try each provider until we get a result
        for provider in self.providers:
            try:
                result = await self._query_provider(provider, ip)
                if result:
                    # Cache the result
                    if len(self.cache) >= self.cache_size:
                        # Simple cache eviction - remove oldest entry
                        self.cache.pop(next(iter(self.cache)))
                    
                    self.cache[ip] = result
                    logger.debug(f"🌍 Geolocation found for {ip}: {result.city}, {result.country}")
                    return result
                    
            except Exception as e:
                logger.debug(f"❌ Provider {provider['name']} failed for {ip}: {e}")
                continue
        
        logger.debug(f"⚠️ No geolocation found for {ip}")
        return None
    
    async def _query_provider(self, provider: Dict, ip: str) -> Optional[GeolocationInfo]:
        """Query a specific geolocation provider."""
        
        # Rate limiting
        current_time = time.time()
        time_since_last = current_time - provider['last_request']
        min_interval = 60.0 / provider['rate_limit']  # Convert to seconds between requests
        
        if time_since_last < min_interval:
            sleep_time = min_interval - time_since_last
            await asyncio.sleep(sleep_time)
        
        provider['last_request'] = time.time()
        
        url = provider['url'].format(ip=ip)
        
        async with aiohttp.ClientSession(timeout=self.session_timeout) as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return self._parse_response(provider['name'], data)
                else:
                    logger.debug(f"❌ {provider['name']} returned status {response.status} for {ip}")
                    return None
    
    def _parse_response(self, provider_name: str, data: Dict) -> Optional[GeolocationInfo]:
        """Parse geolocation response based on provider format."""
        
        try:
            if provider_name == 'ip-api':
                if data.get('status') == 'success':
                    return GeolocationInfo(
                        country=data.get('country'),
                        country_code=data.get('countryCode'),
                        region=data.get('regionName'),
                        city=data.get('city'),
                        latitude=data.get('lat'),
                        longitude=data.get('lon'),
                        timezone=data.get('timezone'),
                        isp=data.get('isp'),
                        organization=data.get('org'),
                        as_number=data.get('as'),
                        threat_level='proxy' if data.get('proxy') else 'clean'
                    )
            
            elif provider_name == 'ipapi.co':
                if 'error' not in data:
                    return GeolocationInfo(
                        country=data.get('country_name'),
                        country_code=data.get('country_code'),
                        region=data.get('region'),
                        city=data.get('city'),
                        latitude=data.get('latitude'),
                        longitude=data.get('longitude'),
                        timezone=data.get('timezone'),
                        isp=data.get('org'),
                        organization=data.get('org')
                    )
            
            elif provider_name == 'ipwhois.app':
                if data.get('success'):
                    return GeolocationInfo(
                        country=data.get('country'),
                        country_code=data.get('country_code'),
                        region=data.get('region'),
                        city=data.get('city'),
                        latitude=data.get('latitude'),
                        longitude=data.get('longitude'),
                        timezone=data.get('timezone', {}).get('id') if isinstance(data.get('timezone'), dict) else None,
                        isp=data.get('connection', {}).get('isp') if isinstance(data.get('connection'), dict) else None,
                        organization=data.get('connection', {}).get('org') if isinstance(data.get('connection'), dict) else None,
                        as_number=data.get('connection', {}).get('asn') if isinstance(data.get('connection'), dict) else None
                    )
            
        except Exception as e:
            logger.debug(f"❌ Error parsing {provider_name} response: {e}")
        
        return None

class HuntTracker:
    """Track hunting success to improve future hunts"""
    
    def __init__(self):
        self.successful_hunts = {}
        self.failed_hunts = {}
        self.pack_reputation = {}  # Owner success rates
        logger.info("🐕 Hunt tracker initialized")
    
    def record_hunt_result(self, repo_name, hunt_score, working_proxies, total_proxies):
        """Record how successful a repository hunt was"""
        success_rate = (working_proxies / total_proxies) if total_proxies > 0 else 0
        
        hunt_data = {
            'hunt_score': hunt_score,
            'success_rate': success_rate,
            'working_proxies': working_proxies,
            'total_proxies': total_proxies,
            'hunted_at': datetime.now(timezone.utc).isoformat()
        }
        
        if success_rate > 0.1:  # Good hunt (>10% success)
            self.successful_hunts[repo_name] = hunt_data
            logger.info(f"🏆 Successful hunt recorded: {repo_name} ({success_rate:.1%})")
        else:  # Poor hunt
            self.failed_hunts[repo_name] = hunt_data
            logger.info(f"❌ Failed hunt recorded: {repo_name}")
        
        # Track pack (owner) reputation
        owner = repo_name.split('/')[0]
        if owner not in self.pack_reputation:
            self.pack_reputation[owner] = []
        self.pack_reputation[owner].append(success_rate)
    
    def get_pack_reputation(self, owner):
        """Get average success rate for a repository owner"""
        if owner in self.pack_reputation and self.pack_reputation[owner]:
            return sum(self.pack_reputation[owner]) / len(self.pack_reputation[owner])
        return 0.0

class ScentAnalyzer:
    """Analyze repository 'scent' for quality indicators"""
    
    def __init__(self):
        # Strong scent indicators (likely to have good proxies)
        self.strong_scent_keywords = [
            'working', 'live', 'fresh', 'tested', 'verified', 'daily', 'updated',
            'active', 'new', 'current', 'valid', 'checked'
        ]
        
        # Weak scent indicators (likely stale)
        self.weak_scent_keywords = [
            'old', 'archive', 'deprecated', 'backup', 'mirror', 'copy', 'dead',
            'inactive', 'outdated', 'legacy'
        ]
        
        # Territory markers (file patterns that indicate good hunting grounds)
        self.territory_markers = [
            r'.*working.*proxy.*\.txt$',
            r'.*live.*\.txt$', 
            r'.*fresh.*\.txt$',
            r'.*valid.*\.txt$',
            r'.*\d{4}-\d{2}-\d{2}.*\.txt$',  # Date in filename
            r'.*proxy.*list.*\.txt$',
            r'.*socks.*\.txt$',
            r'.*http.*\.txt$'
        ]
        
        logger.info("🐕 Scent analyzer initialized with hunting patterns")
    
    def analyze_scent_strength(self, repo):
        """Analyze how 'fresh' the repository scent is"""
        scent_score = 0
        
        name = repo.get('name', '').lower()
        desc = repo.get('description', '').lower()
        text = f"{name} {desc}"
        
        # Strong scent detection
        strong_matches = sum(1 for keyword in self.strong_scent_keywords 
                           if keyword in text)
        scent_score += strong_matches * 15
        
        # Weak scent penalty
        weak_matches = sum(1 for keyword in self.weak_scent_keywords 
                         if keyword in text)
        scent_score -= weak_matches * 10
        
        # Territory freshness (last updated)
        try:
            updated = datetime.fromisoformat(repo['updated_at'].replace('Z', '+00:00'))
            days_ago = (datetime.now(timezone.utc) - updated).days
            
            if days_ago < 7:
                scent_score += 50    # Very fresh scent
            elif days_ago < 30:
                scent_score += 30    # Fresh scent
            elif days_ago < 90:
                scent_score += 15    # Fading scent
            else:
                scent_score -= 20    # Cold trail
        except:
            scent_score -= 15
        
        return max(0, scent_score)

class ProxyHoundDatabase:
    """Database for tracking Proxy Hound hunting results"""
    
    def __init__(self, db_path="proxy_hound.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Initialize hunting database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL") 
                conn.execute("PRAGMA cache_size=10000")
                conn.execute("PRAGMA temp_store=MEMORY")
                
                # Create proxies table with hunt tracking
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS proxies (
                        id INTEGER PRIMARY KEY,
                        ip TEXT NOT NULL,
                        port INTEGER NOT NULL,
                        proxy_type TEXT,
                        source TEXT NOT NULL,
                        repository TEXT,
                        hunt_score REAL DEFAULT 0,
                        country TEXT,
                        city TEXT,
                        last_checked TEXT,
                        is_working BOOLEAN DEFAULT 0,
                        response_time REAL,
                        first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(ip, port)
                    )
                """)
                
                # Create hunt results table
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS hunt_results (
                        id INTEGER PRIMARY KEY,
                        repository TEXT NOT NULL,
                        hunt_score REAL,
                        total_proxies INTEGER,
                        working_proxies INTEGER,
                        success_rate REAL,
                        hunted_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Create indexes
                indexes = [
                    "CREATE INDEX IF NOT EXISTS idx_ip_port ON proxies(ip, port)",
                    "CREATE INDEX IF NOT EXISTS idx_working ON proxies(is_working)",
                    "CREATE INDEX IF NOT EXISTS idx_hunt_score ON proxies(hunt_score)",
                    "CREATE INDEX IF NOT EXISTS idx_repository ON proxies(repository)",
                    "CREATE INDEX IF NOT EXISTS idx_hunt_results_repo ON hunt_results(repository)"
                ]
                
                for index_sql in indexes:
                    conn.execute(index_sql)
                
            logger.info("🐕 Proxy Hound database initialized")
        except Exception as e:
            logger.error(f"❌ Database initialization failed: {e}")
            raise
    
    def add_hunt_results(self, proxies, batch_size=1000):
        """Add hunting results to database"""
        if not proxies:
            return
            
        logger.info(f"🐕 Recording hunt results: {len(proxies)} proxies")
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("BEGIN TRANSACTION")
                
                for i in range(0, len(proxies), batch_size):
                    batch = proxies[i:i + batch_size]
                    
                    data = [
                        (p.ip, p.port, p.proxy_type, p.source, 
                         p.repository, p.hunt_score, p.country, p.city,
                         p.last_checked, p.is_working, p.response_time)
                        for p in batch
                    ]
                    
                    conn.executemany("""
                        INSERT OR REPLACE INTO proxies 
                        (ip, port, proxy_type, source, repository, hunt_score, country, city, last_checked, is_working, response_time)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, data)
                
                conn.execute("COMMIT")
                logger.info("✅ Hunt results recorded successfully")
        except Exception as e:
            logger.error(f"❌ Failed to record hunt results: {e}")
            raise
    
    def get_working_proxies(self, limit=None):
        """Get working proxies ordered by hunt score and response time"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                query = """
                    SELECT ip, port, proxy_type, source, repository, country, city, last_checked, response_time, hunt_score
                    FROM proxies WHERE is_working = 1 
                    ORDER BY hunt_score DESC, response_time ASC
                """
                
                if limit:
                    query += f" LIMIT {limit}"
                
                results = conn.execute(query).fetchall()
                logger.info(f"🐕 Retrieved {len(results)} working proxies")
                return results
        except Exception as e:
            logger.error(f"❌ Failed to get working proxies: {e}")
            return []
    
    def get_hunt_stats(self):
        """Get hunting statistics"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                total = conn.execute("SELECT COUNT(*) FROM proxies").fetchone()[0]
                working = conn.execute("SELECT COUNT(*) FROM proxies WHERE is_working = 1").fetchone()[0]
                
                # Repository stats with hunt scores
                repo_stats = {}
                for row in conn.execute("""
                    SELECT repository, COUNT(*), AVG(hunt_score), AVG(response_time)
                    FROM proxies WHERE is_working = 1 AND repository IS NOT NULL 
                    GROUP BY repository ORDER BY COUNT(*) DESC LIMIT 10
                """):
                    repo_stats[row[0]] = {
                        "count": row[1], 
                        "avg_hunt_score": round(row[2] or 0, 1),
                        "avg_response_time": round(row[3] or 0, 1)
                    }
                
                # Type stats
                type_stats = {}
                for row in conn.execute("SELECT proxy_type, COUNT(*) FROM proxies WHERE is_working = 1 GROUP BY proxy_type"):
                    type_stats[row[0] or 'unknown'] = row[1]
                
                # Country stats
                country_stats = {}
                for row in conn.execute("SELECT country, COUNT(*) FROM proxies WHERE is_working = 1 AND country IS NOT NULL GROUP BY country ORDER BY COUNT(*) DESC LIMIT 10"):
                    country_stats[row[0]] = row[1]
                
                # City stats
                city_stats = {}
                for row in conn.execute("SELECT city, country, COUNT(*) FROM proxies WHERE is_working = 1 AND city IS NOT NULL GROUP BY city, country ORDER BY COUNT(*) DESC LIMIT 10"):
                    city_key = f"{row[0]}, {row[1]}" if row[1] else row[0]
                    city_stats[city_key] = row[2]
                
                # Hunt success by repository
                hunt_success = {}
                for row in conn.execute("""
                    SELECT repository, AVG(success_rate), COUNT(*)
                    FROM hunt_results GROUP BY repository ORDER BY AVG(success_rate) DESC LIMIT 10
                """):
                    hunt_success[row[0]] = {
                        "avg_success_rate": round(row[1] * 100, 1),
                        "hunts": row[2]
                    }
                
                stats = {
                    "total_proxies": total,
                    "working_proxies": working,
                    "success_rate": round((working / total * 100) if total > 0 else 0, 2),
                    "by_type": type_stats,
                    "by_repository": repo_stats,
                    "by_country": country_stats,
                    "by_city": city_stats,
                    "hunt_success": hunt_success,
                    "geolocated_proxies": conn.execute("SELECT COUNT(*) FROM proxies WHERE is_working = 1 AND country IS NOT NULL").fetchone()[0],
                    "countries_found": len(country_stats),
                    "cities_found": len(city_stats)
                }
                
                logger.info(f"🐕 Hunt stats compiled: {working}/{total} working")
                return stats
        except Exception as e:
            logger.error(f"❌ Failed to get hunt stats: {e}")
            return {"total_proxies": 0, "working_proxies": 0, "success_rate": 0, "by_type": {}, "by_repository": {}, "by_country": {}, "by_city": {}, "hunt_success": {}, "geolocated_proxies": 0, "countries_found": 0, "cities_found": 0}

class ProxyHound:
    """
    Proxy Hound - Advanced Repository Hunter with Geolocation
    
    Multi-factor repository analysis:
    - Scent tracking (recency, activity patterns)
    - Pack behavior analysis (forks, community activity) 
    - Territory mapping (content analysis, file patterns)
    - Hunt success learning (performance feedback)
    - Comprehensive geolocation support
    """
    
    def __init__(self, github_token=None):
        self.github_token = github_token
        self.session = None
        self.hunt_tracker = HuntTracker()
        self.scent_analyzer = ScentAnalyzer()
        self.geolocation_service = GeolocationService()
        self.proxy_pattern = re.compile(r'^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d{1,5})$')
        logger.info("🐕 Proxy Hound with Geolocation initialized - ready to hunt")
    
    async def __aenter__(self):
        headers = {"User-Agent": "ProxyHound/2.1"}
        if self.github_token:
            headers["Authorization"] = f"Bearer {self.github_token}"
            logger.info(f"🔑 GitHub token configured: {self.github_token[:10]}...")
        
        timeout = aiohttp.ClientTimeout(total=20, connect=5)
        connector = aiohttp.TCPConnector(limit=100, ttl_dns_cache=300)
        self.session = aiohttp.ClientSession(headers=headers, timeout=timeout, connector=connector)
        logger.info("🌐 Hunting session established")
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
            logger.info("🔌 Hunting session closed")
    
    async def start_hunt(self, max_pages=3, max_memory_mb=512):
        """Start the proxy hunting expedition"""
        logger.info("🐕 Proxy Hound starting hunting expedition")
        
        all_prey = []  # All found proxies
        
        # Phase 1: Repository hunting
        if self.github_token:
            logger.info("🏞️ Phase 1: Repository territory hunting")
            repo_prey = await self._hunt_repositories(max_pages, max_memory_mb)
            all_prey.extend(repo_prey)
            logger.info(f"  ✅ Repository hunt: {len(repo_prey)} proxies found")
        else:
            logger.warning("⚠️ No GitHub token - skipping repository hunting")
        
        # Phase 2: Backup hunting grounds (only if needed)
        if len(all_prey) < 1000:
            logger.info("🏕️ Phase 2: Backup hunting grounds")
            backup_prey = await self._hunt_backup_grounds()
            all_prey.extend(backup_prey)
            logger.info(f"  ✅ Backup hunt: {len(backup_prey)} proxies found")
        
        # Remove duplicate prey
        logger.info("🔍 Removing duplicate prey...")
        unique_prey = self._remove_duplicate_prey(all_prey)
        
        logger.info(f"🏆 Hunt complete: {len(unique_prey)} unique proxies captured")
        return unique_prey
    
    async def _hunt_repositories(self, max_pages, max_memory_mb):
        """Hunt through GitHub repositories for proxy treasures"""
        logger.info("🐕 Starting repository territory hunt")
        
        # Hunting grounds (search queries)
        hunting_grounds = [
            "free proxies updated language:text pushed:>2024-01-01",
            "working proxy list language:text size:>10",
            "fresh socks proxy language:text",
            "daily proxy update language:text",
            "live proxy collection language:text"
        ]
        
        all_repositories = []
        
        # Search all hunting grounds
        for i, ground in enumerate(hunting_grounds):
            logger.info(f"🌲 Hunting ground {i+1}/{len(hunting_grounds)}: {ground.split()[0]} {ground.split()[1]}")
            
            try:
                repositories = await self._search_hunting_ground(ground, max_pages)
                all_repositories.extend(repositories)
                logger.info(f"  📍 Found {len(repositories)} repositories")
                
                await asyncio.sleep(2)  # Rest between hunts
                
            except Exception as e:
                logger.error(f"  ❌ Hunting ground failed: {e}")
                continue
        
        # Score and rank all found repositories
        scored_repositories = await self._score_and_rank_prey(all_repositories)
        
        # Hunt the best repositories
        all_proxies = []
        hunted_count = 0
        
        for hunt_score, repo in scored_repositories[:25]:  # Hunt top 25
            if hunt_score < 25:  # Skip weak scent trails
                break
                
            logger.info(f"🎯 Hunting: {repo['full_name']} (hunt score: {hunt_score})")
            
            repo_proxies = await self._hunt_repository_content(repo, hunt_score)
            all_proxies.extend(repo_proxies)
            hunted_count += 1
            
            logger.info(f"  🏹 Captured {len(repo_proxies)} proxies")
            
            # Memory management
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            if memory_mb > max_memory_mb and hunted_count >= 10:
                logger.info(f"💾 Memory limit reached ({memory_mb:.1f}MB), ending hunt")
                break
            
            await asyncio.sleep(0.5)
        
        logger.info(f"🏆 Repository hunt complete: {hunted_count} territories, {len(all_proxies)} proxies")
        return all_proxies
    
    async def _search_hunting_ground(self, query, max_pages):
        """Search a specific hunting ground for repositories"""
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
                        logger.warning("    ⚠️ Rate limit hit, resting...")
                        break
                    
                    if response.status != 200:
                        continue
                    
                    data = await response.json()
                    items = data.get("items", [])
                    
                    if not items:
                        break
                    
                    # Pre-filter for quality
                    quality_repos = [repo for repo in items if self._is_quality_territory(repo)]
                    repositories.extend(quality_repos)
                    
                    logger.info(f"    📄 Page {page}: {len(quality_repos)}/{len(items)} quality territories")
                
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"    ❌ Search error: {e}")
                continue
        
        return repositories
    
    def _is_quality_territory(self, repo):
        """Pre-filter repositories for basic quality indicators"""
        # Size check
        size_kb = repo.get('size', 0)
        if size_kb < 10 or size_kb > 50000:
            return False
        
        # Recent activity check
        try:
            updated = datetime.fromisoformat(repo['updated_at'].replace('Z', '+00:00'))
            days_ago = (datetime.now(timezone.utc) - updated).days
            if days_ago > 365:  # No activity in a year
                return False
        except:
            return False
        
        # Basic relevance check
        name = repo.get('name', '').lower, r'.*working.*\.txt#!/usr/bin/env python3
"""
Proxy Hound - Advanced Repository Hunter v2.1
1. Hunt GitHub repositories using scent tracking and pack behavior analysis
2. Deep content analysis for proxy treasure detection
3. Learning system that improves hunting success over time
4. High-performance parallel proxy validation
5. Comprehensive geolocation support
"""

import asyncio
import json
import logging
import sqlite3
import time
import gzip
import re
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Set
from dataclasses import dataclass, asdict
import random
import ssl
import hashlib

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

# Verified hunting grounds (direct sources as backup)
BACKUP_HUNTING_GROUNDS = [
    "https://raw.githubusercontent.com/r00tee/Proxy-List/main/Socks4.txt", 
    "https://raw.githubusercontent.com/r00tee/Proxy-List/main/Socks5.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/http.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/https.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/socks4.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/socks5.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt"
]

@dataclass
class GeolocationInfo:
    """Comprehensive geolocation information."""
    country: Optional[str] = None
    country_code: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    timezone: Optional[str] = None
    isp: Optional[str] = None
    organization: Optional[str] = None
    as_number: Optional[str] = None
    threat_level: Optional[str] = None

@dataclass
class ProxyInfo:
    """Enhanced proxy information with geolocation."""
    ip: str
    port: int
    proxy_type: str
    source: str
    repository: Optional[str] = None
    hunt_score: float = 0.0
    country: Optional[str] = None
    city: Optional[str] = None
    last_checked: Optional[str] = None
    is_working: bool = False
    response_time: Optional[float] = None
    first_seen: Optional[str] = None
    geolocation: Optional[GeolocationInfo] = None
    
    @property
    def location_string(self) -> str:
        """Get human-readable location string."""
        if self.geolocation:
            parts = []
            if self.geolocation.city:
                parts.append(self.geolocation.city)
            if self.geolocation.region:
                parts.append(self.geolocation.region)
            if self.geolocation.country:
                parts.append(self.geolocation.country)
            return ", ".join(parts) if parts else "Unknown"
        elif self.city and self.country:
            return f"{self.city}, {self.country}"
        elif self.country:
            return self.country
        return "Unknown"

class GeolocationService:
    """Geolocation service with multiple providers and caching."""
    
    def __init__(self, cache_size: int = 10000):
        self.cache: Dict[str, GeolocationInfo] = {}
        self.cache_size = cache_size
        self.session_timeout = aiohttp.ClientTimeout(total=10)
        
        # Multiple geolocation providers (free tier)
        self.providers = [
            {
                'name': 'ip-api',
                'url': 'http://ip-api.com/json/{ip}?fields=status,message,country,countryCode,region,regionName,city,lat,lon,timezone,isp,org,as,mobile,proxy,hosting',
                'rate_limit': 45,  # requests per minute
                'last_request': 0
            },
            {
                'name': 'ipapi.co',
                'url': 'https://ipapi.co/{ip}/json/',
                'rate_limit': 30,  # requests per minute for free tier
                'last_request': 0
            },
            {
                'name': 'ipwhois.app',
                'url': 'http://ipwho.is/{ip}',
                'rate_limit': 1000,  # requests per hour
                'last_request': 0
            }
        ]
    
    async def get_geolocation(self, ip: str) -> Optional[GeolocationInfo]:
        """Get geolocation for IP with caching and fallback providers."""
        
        # Check cache first
        if ip in self.cache:
            logger.debug(f"🗺️ Cache hit for {ip}")
            return self.cache[ip]
        
        # Try each provider until we get a result
        for provider in self.providers:
            try:
                result = await self._query_provider(provider, ip)
                if result:
                    # Cache the result
                    if len(self.cache) >= self.cache_size:
                        # Simple cache eviction - remove oldest entry
                        self.cache.pop(next(iter(self.cache)))
                    
                    self.cache[ip] = result
                    logger.debug(f"🌍 Geolocation found for {ip}: {result.city}, {result.country}")
                    return result
                    
            except Exception as e:
                logger.debug(f"❌ Provider {provider['name']} failed for {ip}: {e}")
                continue
        
        logger.debug(f"⚠️ No geolocation found for {ip}")
        return None
    
    async def _query_provider(self, provider: Dict, ip: str) -> Optional[GeolocationInfo]:
        """Query a specific geolocation provider."""
        
        # Rate limiting
        current_time = time.time()
        time_since_last = current_time - provider['last_request']
        min_interval = 60.0 / provider['rate_limit']  # Convert to seconds between requests
        
        if time_since_last < min_interval:
            sleep_time = min_interval - time_since_last
            await asyncio.sleep(sleep_time)
        
        provider['last_request'] = time.time()
        
        url = provider['url'].format(ip=ip)
        
        async with aiohttp.ClientSession(timeout=self.session_timeout) as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return self._parse_response(provider['name'], data)
                else:
                    logger.debug(f"❌ {provider['name']} returned status {response.status} for {ip}")
                    return None
    
    def _parse_response(self, provider_name: str, data: Dict) -> Optional[GeolocationInfo]:
        """Parse geolocation response based on provider format."""
        
        try:
            if provider_name == 'ip-api':
                if data.get('status') == 'success':
                    return GeolocationInfo(
                        country=data.get('country'),
                        country_code=data.get('countryCode'),
                        region=data.get('regionName'),
                        city=data.get('city'),
                        latitude=data.get('lat'),
                        longitude=data.get('lon'),
                        timezone=data.get('timezone'),
                        isp=data.get('isp'),
                        organization=data.get('org'),
                        as_number=data.get('as'),
                        threat_level='proxy' if data.get('proxy') else 'clean'
                    )
            
            elif provider_name == 'ipapi.co':
                if 'error' not in data:
                    return GeolocationInfo(
                        country=data.get('country_name'),
                        country_code=data.get('country_code'),
                        region=data.get('region'),
                        city=data.get('city'),
                        latitude=data.get('latitude'),
                        longitude=data.get('longitude'),
                        timezone=data.get('timezone'),
                        isp=data.get('org'),
                        organization=data.get('org')
                    )
            
            elif provider_name == 'ipwhois.app':
                if data.get('success'):
                    return GeolocationInfo(
                        country=data.get('country'),
                        country_code=data.get('country_code'),
                        region=data.get('region'),
                        city=data.get('city'),
                        latitude=data.get('latitude'),
                        longitude=data.get('longitude'),
                        timezone=data.get('timezone', {}).get('id') if isinstance(data.get('timezone'), dict) else None,
                        isp=data.get('connection', {}).get('isp') if isinstance(data.get('connection'), dict) else None,
                        organization=data.get('connection', {}).get('org') if isinstance(data.get('connection'), dict) else None,
                        as_number=data.get('connection', {}).get('asn') if isinstance(data.get('connection'), dict) else None
                    )
            
        except Exception as e:
            logger.debug(f"❌ Error parsing {provider_name} response: {e}")
        
        return None

class HuntTracker:
    """Track hunting success to improve future hunts"""
    
    def __init__(self):
        self.successful_hunts = {}
        self.failed_hunts = {}
        self.pack_reputation = {}  # Owner success rates
        logger.info("🐕 Hunt tracker initialized")
    
    def record_hunt_result(self, repo_name, hunt_score, working_proxies, total_proxies):
        """Record how successful a repository hunt was"""
        success_rate = (working_proxies / total_proxies) if total_proxies > 0 else 0
        
        hunt_data = {
            'hunt_score': hunt_score,
            'success_rate': success_rate,
            'working_proxies': working_proxies,
            'total_proxies': total_proxies,
            'hunted_at': datetime.now(timezone.utc).isoformat()
        }
        
        if success_rate > 0.1:  # Good hunt (>10% success)
            self.successful_hunts[repo_name] = hunt_data
            logger.info(f"🏆 Successful hunt recorded: {repo_name} ({success_rate:.1%})")
        else:  # Poor hunt
            self.failed_hunts[repo_name] = hunt_data
            logger.info(f"❌ Failed hunt recorded: {repo_name}")
        
        # Track pack (owner) reputation
        owner = repo_name.split('/')[0]
        if owner not in self.pack_reputation:
            self.pack_reputation[owner] = []
        self.pack_reputation[owner].append(success_rate)
    
    def get_pack_reputation(self, owner):
        """Get average success rate for a repository owner"""
        if owner in self.pack_reputation and self.pack_reputation[owner]:
            return sum(self.pack_reputation[owner]) / len(self.pack_reputation[owner])
        return 0.0

class ScentAnalyzer:
    """Analyze repository 'scent' for quality indicators"""
    
    def __init__(self):
        # Strong scent indicators (likely to have good proxies)
        self.strong_scent_keywords = [
            'working', 'live', 'fresh', 'tested', 'verified', 'daily', 'updated',
            'active', 'new', 'current', 'valid', 'checked'
        ]
        
        # Weak scent indicators (likely stale)
        self.weak_scent_keywords = [
            'old', 'archive', 'deprecated', 'backup', 'mirror', 'copy', 'dead',
            'inactive', 'outdated', 'legacy'
        ]
        
        # Territory markers (file patterns that indicate good hunting grounds)
        self.territory_markers = [
            r'.*working.*proxy.*\.txt$',
            r'.*live.*\.txt$', 
            r'.*fresh.*\.txt$',
            r'.*valid.*\.txt$',
            r'.*\d{4}-\d{2}-\d{2}.*\.txt$',  # Date in filename
            r'.*proxy.*list.*\.txt$',
            r'.*socks.*\.txt$',
            r'.*http.*\.txt$'
        ]
        
        logger.info("🐕 Scent analyzer initialized with hunting patterns")
    
    def analyze_scent_strength(self, repo):
        """Analyze how 'fresh' the repository scent is"""
        scent_score = 0
        
        name = repo.get('name', '').lower()
        desc = repo.get('description', '').lower()
        text = f"{name} {desc}"
        
        # Strong scent detection
        strong_matches = sum(1 for keyword in self.strong_scent_keywords 
                           if keyword in text)
        scent_score += strong_matches * 15
        
        # Weak scent penalty
        weak_matches = sum(1 for keyword in self.weak_scent_keywords 
                         if keyword in text)
        scent_score -= weak_matches * 10
        
        # Territory freshness (last updated)
        try:
            updated = datetime.fromisoformat(repo['updated_at'].replace('Z', '+00:00'))
            days_ago = (datetime.now(timezone.utc) - updated).days
            
            if days_ago < 7:
                scent_score += 50    # Very fresh scent
            elif days_ago < 30:
                scent_score += 30    # Fresh scent
            elif days_ago < 90:
                scent_score += 15    # Fading scent
            else:
                scent_score -= 20    # Cold trail
        except:
            scent_score -= 15
        
        return max(0, scent_score)

class ProxyHoundDatabase:
    """Database for tracking Proxy Hound hunting results"""
    
    def __init__(self, db_path="proxy_hound.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Initialize hunting database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL") 
                conn.execute("PRAGMA cache_size=10000")
                conn.execute("PRAGMA temp_store=MEMORY")
                
                # Create proxies table with hunt tracking
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS proxies (
                        id INTEGER PRIMARY KEY,
                        ip TEXT NOT NULL,
                        port INTEGER NOT NULL,
                        proxy_type TEXT,
                        source TEXT NOT NULL,
                        repository TEXT,
                        hunt_score REAL DEFAULT 0,
                        country TEXT,
                        city TEXT,
                        last_checked TEXT,
                        is_working BOOLEAN DEFAULT 0,
                        response_time REAL,
                        first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(ip, port)
                    )
                """)
                
                # Create hunt results table
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS hunt_results (
                        id INTEGER PRIMARY KEY,
                        repository TEXT NOT NULL,
                        hunt_score REAL,
                        total_proxies INTEGER,
                        working_proxies INTEGER,
                        success_rate REAL,
                        hunted_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Create indexes
                indexes = [
                    "CREATE INDEX IF NOT EXISTS idx_ip_port ON proxies(ip, port)",
                    "CREATE INDEX IF NOT EXISTS idx_working ON proxies(is_working)",
                    "CREATE INDEX IF NOT EXISTS idx_hunt_score ON proxies(hunt_score)",
                    "CREATE INDEX IF NOT EXISTS idx_repository ON proxies(repository)",
                    "CREATE INDEX IF NOT EXISTS idx_hunt_results_repo ON hunt_results(repository)"
                ]
                
                for index_sql in indexes:
                    conn.execute(index_sql)
                
            logger.info("🐕 Proxy Hound database initialized")
        except Exception as e:
            logger.error(f"❌ Database initialization failed: {e}")
            raise
    
    def add_hunt_results(self, proxies, batch_size=1000):
        """Add hunting results to database"""
        if not proxies:
            return
            
        logger.info(f"🐕 Recording hunt results: {len(proxies)} proxies")
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("BEGIN TRANSACTION")
                
                for i in range(0, len(proxies), batch_size):
                    batch = proxies[i:i + batch_size]
                    
                    data = [
                        (p.ip, p.port, p.proxy_type, p.source, 
                         p.repository, p.hunt_score, p.country, p.city,
                         p.last_checked, p.is_working, p.response_time)
                        for p in batch
                    ]
                    
                    conn.executemany("""
                        INSERT OR REPLACE INTO proxies 
                        (ip, port, proxy_type, source, repository, hunt_score, country, city, last_checked, is_working, response_time)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, data)
                
                conn.execute("COMMIT")
                logger.info("✅ Hunt results recorded successfully")
        except Exception as e:
            logger.error(f"❌ Failed to record hunt results: {e}")
            raise
    
    def get_working_proxies(self, limit=None):
        """Get working proxies ordered by hunt score and response time"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                query = """
                    SELECT ip, port, proxy_type, source, repository, country, city, last_checked, response_time, hunt_score
                    FROM proxies WHERE is_working = 1 
                    ORDER BY hunt_score DESC, response_time ASC
                """
                
                if limit:
                    query += f" LIMIT {limit}"
                
                results = conn.execute(query).fetchall()
                logger.info(f"🐕 Retrieved {len(results)} working proxies")
                return results
        except Exception as e:
            logger.error(f"❌ Failed to get working proxies: {e}")
            return []
    
    def get_hunt_stats(self):
        """Get hunting statistics"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                total = conn.execute("SELECT COUNT(*) FROM proxies").fetchone()[0]
                working = conn.execute("SELECT COUNT(*) FROM proxies WHERE is_working = 1").fetchone()[0]
                
                # Repository stats with hunt scores
                repo_stats = {}
                for row in conn.execute("""
                    SELECT repository, COUNT(*), AVG(hunt_score), AVG(response_time)
                    FROM proxies WHERE is_working = 1 AND repository IS NOT NULL 
                    GROUP BY repository ORDER BY COUNT(*) DESC LIMIT 10
                """):
                    repo_stats[row[0]] = {
                        "count": row[1], 
                        "avg_hunt_score": round(row[2] or 0, 1),
                        "avg_response_time": round(row[3] or 0, 1)
                    }
                
                # Type stats
                type_stats = {}
                for row in conn.execute("SELECT proxy_type, COUNT(*) FROM proxies WHERE is_working = 1 GROUP BY proxy_type"):
                    type_stats[row[0] or 'unknown'] = row[1]
                
                # Country stats
                country_stats = {}
                for row in conn.execute("SELECT country, COUNT(*) FROM proxies WHERE is_working = 1 AND country IS NOT NULL GROUP BY country ORDER BY COUNT(*) DESC LIMIT 10"):
                    country_stats[row[0]] = row[1]
                
                # City stats
                city_stats = {}
                for row in conn.execute("SELECT city, country, COUNT(*) FROM proxies WHERE is_working = 1 AND city IS NOT NULL GROUP BY city, country ORDER BY COUNT(*) DESC LIMIT 10"):
                    city_key = f"{row[0]}, {row[1]}" if row[1] else row[0]
                    city_stats[city_key] = row[2]
                
                # Hunt success by repository
                hunt_success = {}
                for row in conn.execute("""
                    SELECT repository, AVG(success_rate), COUNT(*)
                    FROM hunt_results GROUP BY repository ORDER BY AVG(success_rate) DESC LIMIT 10
                """):
                    hunt_success[row[0]] = {
                        "avg_success_rate": round(row[1] * 100, 1),
                        "hunts": row[2]
                    }
                
                stats = {
                    "total_proxies": total,
                    "working_proxies": working,
                    "success_rate": round((working / total * 100) if total > 0 else 0, 2),
                    "by_type": type_stats,
                    "by_repository": repo_stats,
                    "by_country": country_stats,
                    "by_city": city_stats,
                    "hunt_success": hunt_success,
                    "geolocated_proxies": conn.execute("SELECT COUNT(*) FROM proxies WHERE is_working = 1 AND country IS NOT NULL").fetchone()[0],
                    "countries_found": len(country_stats),
                    "cities_found": len(city_stats)
                }
                
                logger.info(f"🐕 Hunt stats compiled: {working}/{total} working")
                return stats
        except Exception as e:
            logger.error(f"❌ Failed to get hunt stats: {e}")
            return {"total_proxies": 0, "working_proxies": 0, "success_rate": 0, "by_type": {}, "by_repository": {}, "by_country": {}, "by_city": {}, "hunt_success": {}, "geolocated_proxies": 0, "countries_found": 0, "cities_found": 0}

class ProxyHound:
    """
    Proxy Hound - Advanced Repository Hunter with Geolocation
    
    Multi-factor repository analysis:
    - Scent tracking (recency, activity patterns)
    - Pack behavior analysis (forks, community activity) 
    - Territory mapping (content analysis, file patterns)
    - Hunt success learning (performance feedback)
    - Comprehensive geolocation support
    """
    
    def __init__(self, github_token=None):
        self.github_token = github_token
        self.session = None
        self.hunt_tracker = HuntTracker()
        self.scent_analyzer = ScentAnalyzer()
        self.geolocation_service = GeolocationService()
        self.proxy_pattern = re.compile(r'^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d{1,5})$')
        logger.info("🐕 Proxy Hound with Geolocation initialized - ready to hunt")
    
    async def __aenter__(self):
        headers = {"User-Agent": "ProxyHound/2.1"}
        if self.github_token:
            headers["Authorization"] = f"Bearer {self.github_token}"
            logger.info(f"🔑 GitHub token configured: {self.github_token[:10]}...")
        
        timeout = aiohttp.ClientTimeout(total=20, connect=5)
        connector = aiohttp.TCPConnector(limit=100, ttl_dns_cache=300)
        self.session = aiohttp.ClientSession(headers=headers, timeout=timeout, connector=connector)
        logger.info("🌐 Hunting session established")
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
            logger.info("🔌 Hunting session closed")
    
    async def start_hunt(self, max_pages=3, max_memory_mb=512):
        """Start the proxy hunting expedition"""
        logger.info("🐕 Proxy Hound starting hunting expedition")
        
        all_prey = []  # All found proxies
        
        # Phase 1: Repository hunting
        if self.github_token:
            logger.info("🏞️ Phase 1: Repository territory hunting")
            repo_prey = await self._hunt_repositories(max_pages, max_memory_mb)
            all_prey.extend(repo_prey)
            logger.info(f"  ✅ Repository hunt: {len(repo_prey)} proxies found")
        else:
            logger.warning("⚠️ No GitHub token - skipping repository hunting")
        
        # Phase 2: Backup hunting grounds (only if needed)
        if len(all_prey) < 1000:
            logger.info("🏕️ Phase 2: Backup hunting grounds")
            backup_prey = await self._hunt_backup_grounds()
            all_prey.extend(backup_prey)
            logger.info(f"  ✅ Backup hunt: {len(backup_prey)} proxies found")
        
        # Remove duplicate prey
        logger.info("🔍 Removing duplicate prey...")
        unique_prey = self._remove_duplicate_prey(all_prey)
        
        logger.info(f"🏆 Hunt complete: {len(unique_prey)} unique proxies captured")
        return unique_prey
    
    async def _hunt_repositories(self, max_pages, max_memory_mb):
        """Hunt through GitHub repositories for proxy treasures"""
        logger.info("🐕 Starting repository territory hunt")
        
        # Hunting grounds (search queries)
        hunting_grounds = [
            "free proxies updated language:text pushed:>2024-01-01",
            "working proxy list language:text size:>10",
            "fresh socks proxy language:text",
            "daily proxy update language:text",
            "live proxy collection language:text"
        ]
        
        all_repositories = []
        
        # Search all hunting grounds
        for i, ground in enumerate(hunting_grounds):
            logger.info(f"🌲 Hunting ground {i+1}/{len(hunting_grounds)}: {ground.split()[0]} {ground.split()[1]}")
            
            try:
                repositories = await self._search_hunting_ground(ground, max_pages)
                all_repositories.extend(repositories)
                logger.info(f"  📍 Found {len(repositories)} repositories")
                
                await asyncio.sleep(2)  # Rest between hunts
                
            except Exception as e:
                logger.error(f"  ❌ Hunting ground failed: {e}")
                continue
        
        # Score and rank all found repositories
        scored_repositories = await self._score_and_rank_prey(all_repositories)
        
        # Hunt the best repositories
        all_proxies = []
        hunted_count = 0
        
        for hunt_score, repo in scored_repositories[:25]:  # Hunt top 25
            if hunt_score < 25:  # Skip weak scent trails
                break
                
            logger.info(f"🎯 Hunting: {repo['full_name']} (hunt score: {hunt_score})")
            
            repo_proxies = await self._hunt_repository_content(repo, hunt_score)
            all_proxies.extend(repo_proxies)
            hunted_count += 1
            
            logger.info(f"  🏹 Captured {len(repo_proxies)} proxies")
            
            # Memory management
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            if memory_mb > max_memory_mb and hunted_count >= 10:
                logger.info(f"💾 Memory limit reached ({memory_mb:.1f}MB), ending hunt")
                break
            
            await asyncio.sleep(0.5)
        
        logger.info(f"🏆 Repository hunt complete: {hunted_count} territories, {len(all_proxies)} proxies")
        return all_proxies
    
    async def _search_hunting_ground(self, query, max_pages):
        """Search a specific hunting ground for repositories"""
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
                        logger.warning("    ⚠️ Rate limit hit, resting...")
                        break
                    
                    if response.status != 200:
                        continue
                    
                    data = await response.json()
                    items = data.get("items", [])
                    
                    if not items:
                        break
                    
                    # Pre-filter for quality
                    quality_repos = [repo for repo in items if self._is_quality_territory(repo)]
                    repositories.extend(quality_repos)
                    
                    logger.info(f"    📄 Page {page}: {len(quality_repos)}/{len(items)} quality territories")
                
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"    ❌ Search error: {e}")
                continue
        
        return repositories
    
    def _is_quality_territory(self, repo):
        """Pre-filter repositories for basic quality indicators"""
        # Size check
        size_kb = repo.get('size', 0)
        if size_kb < 10 or size_kb > 50000:
            return False
        
        # Recent activity check
        try:
            updated = datetime.fromisoformat(repo['updated_at'].replace('Z', '+00:00'))
            days_ago = (datetime.now(timezone.utc) - updated).days
            if days_ago > 365:  # No activity in a year
                return False
        except:
            return False
        
        # Basic relevance check
        name = repo.get('name', '').lower,
            r'.*fresh.*\.txt#!/usr/bin/env python3
"""
Proxy Hound - Advanced Repository Hunter v2.1
1. Hunt GitHub repositories using scent tracking and pack behavior analysis
2. Deep content analysis for proxy treasure detection
3. Learning system that improves hunting success over time
4. High-performance parallel proxy validation
5. Comprehensive geolocation support
"""

import asyncio
import json
import logging
import sqlite3
import time
import gzip
import re
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Set
from dataclasses import dataclass, asdict
import random
import ssl
import hashlib

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

# Verified hunting grounds (direct sources as backup)
BACKUP_HUNTING_GROUNDS = [
    "https://raw.githubusercontent.com/r00tee/Proxy-List/main/Socks4.txt", 
    "https://raw.githubusercontent.com/r00tee/Proxy-List/main/Socks5.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/http.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/https.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/socks4.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/socks5.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt"
]

@dataclass
class GeolocationInfo:
    """Comprehensive geolocation information."""
    country: Optional[str] = None
    country_code: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    timezone: Optional[str] = None
    isp: Optional[str] = None
    organization: Optional[str] = None
    as_number: Optional[str] = None
    threat_level: Optional[str] = None

@dataclass
class ProxyInfo:
    """Enhanced proxy information with geolocation."""
    ip: str
    port: int
    proxy_type: str
    source: str
    repository: Optional[str] = None
    hunt_score: float = 0.0
    country: Optional[str] = None
    city: Optional[str] = None
    last_checked: Optional[str] = None
    is_working: bool = False
    response_time: Optional[float] = None
    first_seen: Optional[str] = None
    geolocation: Optional[GeolocationInfo] = None
    
    @property
    def location_string(self) -> str:
        """Get human-readable location string."""
        if self.geolocation:
            parts = []
            if self.geolocation.city:
                parts.append(self.geolocation.city)
            if self.geolocation.region:
                parts.append(self.geolocation.region)
            if self.geolocation.country:
                parts.append(self.geolocation.country)
            return ", ".join(parts) if parts else "Unknown"
        elif self.city and self.country:
            return f"{self.city}, {self.country}"
        elif self.country:
            return self.country
        return "Unknown"

class GeolocationService:
    """Geolocation service with multiple providers and caching."""
    
    def __init__(self, cache_size: int = 10000):
        self.cache: Dict[str, GeolocationInfo] = {}
        self.cache_size = cache_size
        self.session_timeout = aiohttp.ClientTimeout(total=10)
        
        # Multiple geolocation providers (free tier)
        self.providers = [
            {
                'name': 'ip-api',
                'url': 'http://ip-api.com/json/{ip}?fields=status,message,country,countryCode,region,regionName,city,lat,lon,timezone,isp,org,as,mobile,proxy,hosting',
                'rate_limit': 45,  # requests per minute
                'last_request': 0
            },
            {
                'name': 'ipapi.co',
                'url': 'https://ipapi.co/{ip}/json/',
                'rate_limit': 30,  # requests per minute for free tier
                'last_request': 0
            },
            {
                'name': 'ipwhois.app',
                'url': 'http://ipwho.is/{ip}',
                'rate_limit': 1000,  # requests per hour
                'last_request': 0
            }
        ]
    
    async def get_geolocation(self, ip: str) -> Optional[GeolocationInfo]:
        """Get geolocation for IP with caching and fallback providers."""
        
        # Check cache first
        if ip in self.cache:
            logger.debug(f"🗺️ Cache hit for {ip}")
            return self.cache[ip]
        
        # Try each provider until we get a result
        for provider in self.providers:
            try:
                result = await self._query_provider(provider, ip)
                if result:
                    # Cache the result
                    if len(self.cache) >= self.cache_size:
                        # Simple cache eviction - remove oldest entry
                        self.cache.pop(next(iter(self.cache)))
                    
                    self.cache[ip] = result
                    logger.debug(f"🌍 Geolocation found for {ip}: {result.city}, {result.country}")
                    return result
                    
            except Exception as e:
                logger.debug(f"❌ Provider {provider['name']} failed for {ip}: {e}")
                continue
        
        logger.debug(f"⚠️ No geolocation found for {ip}")
        return None
    
    async def _query_provider(self, provider: Dict, ip: str) -> Optional[GeolocationInfo]:
        """Query a specific geolocation provider."""
        
        # Rate limiting
        current_time = time.time()
        time_since_last = current_time - provider['last_request']
        min_interval = 60.0 / provider['rate_limit']  # Convert to seconds between requests
        
        if time_since_last < min_interval:
            sleep_time = min_interval - time_since_last
            await asyncio.sleep(sleep_time)
        
        provider['last_request'] = time.time()
        
        url = provider['url'].format(ip=ip)
        
        async with aiohttp.ClientSession(timeout=self.session_timeout) as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return self._parse_response(provider['name'], data)
                else:
                    logger.debug(f"❌ {provider['name']} returned status {response.status} for {ip}")
                    return None
    
    def _parse_response(self, provider_name: str, data: Dict) -> Optional[GeolocationInfo]:
        """Parse geolocation response based on provider format."""
        
        try:
            if provider_name == 'ip-api':
                if data.get('status') == 'success':
                    return GeolocationInfo(
                        country=data.get('country'),
                        country_code=data.get('countryCode'),
                        region=data.get('regionName'),
                        city=data.get('city'),
                        latitude=data.get('lat'),
                        longitude=data.get('lon'),
                        timezone=data.get('timezone'),
                        isp=data.get('isp'),
                        organization=data.get('org'),
                        as_number=data.get('as'),
                        threat_level='proxy' if data.get('proxy') else 'clean'
                    )
            
            elif provider_name == 'ipapi.co':
                if 'error' not in data:
                    return GeolocationInfo(
                        country=data.get('country_name'),
                        country_code=data.get('country_code'),
                        region=data.get('region'),
                        city=data.get('city'),
                        latitude=data.get('latitude'),
                        longitude=data.get('longitude'),
                        timezone=data.get('timezone'),
                        isp=data.get('org'),
                        organization=data.get('org')
                    )
            
            elif provider_name == 'ipwhois.app':
                if data.get('success'):
                    return GeolocationInfo(
                        country=data.get('country'),
                        country_code=data.get('country_code'),
                        region=data.get('region'),
                        city=data.get('city'),
                        latitude=data.get('latitude'),
                        longitude=data.get('longitude'),
                        timezone=data.get('timezone', {}).get('id') if isinstance(data.get('timezone'), dict) else None,
                        isp=data.get('connection', {}).get('isp') if isinstance(data.get('connection'), dict) else None,
                        organization=data.get('connection', {}).get('org') if isinstance(data.get('connection'), dict) else None,
                        as_number=data.get('connection', {}).get('asn') if isinstance(data.get('connection'), dict) else None
                    )
            
        except Exception as e:
            logger.debug(f"❌ Error parsing {provider_name} response: {e}")
        
        return None

class HuntTracker:
    """Track hunting success to improve future hunts"""
    
    def __init__(self):
        self.successful_hunts = {}
        self.failed_hunts = {}
        self.pack_reputation = {}  # Owner success rates
        logger.info("🐕 Hunt tracker initialized")
    
    def record_hunt_result(self, repo_name, hunt_score, working_proxies, total_proxies):
        """Record how successful a repository hunt was"""
        success_rate = (working_proxies / total_proxies) if total_proxies > 0 else 0
        
        hunt_data = {
            'hunt_score': hunt_score,
            'success_rate': success_rate,
            'working_proxies': working_proxies,
            'total_proxies': total_proxies,
            'hunted_at': datetime.now(timezone.utc).isoformat()
        }
        
        if success_rate > 0.1:  # Good hunt (>10% success)
            self.successful_hunts[repo_name] = hunt_data
            logger.info(f"🏆 Successful hunt recorded: {repo_name} ({success_rate:.1%})")
        else:  # Poor hunt
            self.failed_hunts[repo_name] = hunt_data
            logger.info(f"❌ Failed hunt recorded: {repo_name}")
        
        # Track pack (owner) reputation
        owner = repo_name.split('/')[0]
        if owner not in self.pack_reputation:
            self.pack_reputation[owner] = []
        self.pack_reputation[owner].append(success_rate)
    
    def get_pack_reputation(self, owner):
        """Get average success rate for a repository owner"""
        if owner in self.pack_reputation and self.pack_reputation[owner]:
            return sum(self.pack_reputation[owner]) / len(self.pack_reputation[owner])
        return 0.0

class ScentAnalyzer:
    """Analyze repository 'scent' for quality indicators"""
    
    def __init__(self):
        # Strong scent indicators (likely to have good proxies)
        self.strong_scent_keywords = [
            'working', 'live', 'fresh', 'tested', 'verified', 'daily', 'updated',
            'active', 'new', 'current', 'valid', 'checked'
        ]
        
        # Weak scent indicators (likely stale)
        self.weak_scent_keywords = [
            'old', 'archive', 'deprecated', 'backup', 'mirror', 'copy', 'dead',
            'inactive', 'outdated', 'legacy'
        ]
        
        # Territory markers (file patterns that indicate good hunting grounds)
        self.territory_markers = [
            r'.*working.*proxy.*\.txt$',
            r'.*live.*\.txt$', 
            r'.*fresh.*\.txt$',
            r'.*valid.*\.txt$',
            r'.*\d{4}-\d{2}-\d{2}.*\.txt$',  # Date in filename
            r'.*proxy.*list.*\.txt$',
            r'.*socks.*\.txt$',
            r'.*http.*\.txt$'
        ]
        
        logger.info("🐕 Scent analyzer initialized with hunting patterns")
    
    def analyze_scent_strength(self, repo):
        """Analyze how 'fresh' the repository scent is"""
        scent_score = 0
        
        name = repo.get('name', '').lower()
        desc = repo.get('description', '').lower()
        text = f"{name} {desc}"
        
        # Strong scent detection
        strong_matches = sum(1 for keyword in self.strong_scent_keywords 
                           if keyword in text)
        scent_score += strong_matches * 15
        
        # Weak scent penalty
        weak_matches = sum(1 for keyword in self.weak_scent_keywords 
                         if keyword in text)
        scent_score -= weak_matches * 10
        
        # Territory freshness (last updated)
        try:
            updated = datetime.fromisoformat(repo['updated_at'].replace('Z', '+00:00'))
            days_ago = (datetime.now(timezone.utc) - updated).days
            
            if days_ago < 7:
                scent_score += 50    # Very fresh scent
            elif days_ago < 30:
                scent_score += 30    # Fresh scent
            elif days_ago < 90:
                scent_score += 15    # Fading scent
            else:
                scent_score -= 20    # Cold trail
        except:
            scent_score -= 15
        
        return max(0, scent_score)

class ProxyHoundDatabase:
    """Database for tracking Proxy Hound hunting results"""
    
    def __init__(self, db_path="proxy_hound.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Initialize hunting database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL") 
                conn.execute("PRAGMA cache_size=10000")
                conn.execute("PRAGMA temp_store=MEMORY")
                
                # Create proxies table with hunt tracking
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS proxies (
                        id INTEGER PRIMARY KEY,
                        ip TEXT NOT NULL,
                        port INTEGER NOT NULL,
                        proxy_type TEXT,
                        source TEXT NOT NULL,
                        repository TEXT,
                        hunt_score REAL DEFAULT 0,
                        country TEXT,
                        city TEXT,
                        last_checked TEXT,
                        is_working BOOLEAN DEFAULT 0,
                        response_time REAL,
                        first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(ip, port)
                    )
                """)
                
                # Create hunt results table
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS hunt_results (
                        id INTEGER PRIMARY KEY,
                        repository TEXT NOT NULL,
                        hunt_score REAL,
                        total_proxies INTEGER,
                        working_proxies INTEGER,
                        success_rate REAL,
                        hunted_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Create indexes
                indexes = [
                    "CREATE INDEX IF NOT EXISTS idx_ip_port ON proxies(ip, port)",
                    "CREATE INDEX IF NOT EXISTS idx_working ON proxies(is_working)",
                    "CREATE INDEX IF NOT EXISTS idx_hunt_score ON proxies(hunt_score)",
                    "CREATE INDEX IF NOT EXISTS idx_repository ON proxies(repository)",
                    "CREATE INDEX IF NOT EXISTS idx_hunt_results_repo ON hunt_results(repository)"
                ]
                
                for index_sql in indexes:
                    conn.execute(index_sql)
                
            logger.info("🐕 Proxy Hound database initialized")
        except Exception as e:
            logger.error(f"❌ Database initialization failed: {e}")
            raise
    
    def add_hunt_results(self, proxies, batch_size=1000):
        """Add hunting results to database"""
        if not proxies:
            return
            
        logger.info(f"🐕 Recording hunt results: {len(proxies)} proxies")
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("BEGIN TRANSACTION")
                
                for i in range(0, len(proxies), batch_size):
                    batch = proxies[i:i + batch_size]
                    
                    data = [
                        (p.ip, p.port, p.proxy_type, p.source, 
                         p.repository, p.hunt_score, p.country, p.city,
                         p.last_checked, p.is_working, p.response_time)
                        for p in batch
                    ]
                    
                    conn.executemany("""
                        INSERT OR REPLACE INTO proxies 
                        (ip, port, proxy_type, source, repository, hunt_score, country, city, last_checked, is_working, response_time)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, data)
                
                conn.execute("COMMIT")
                logger.info("✅ Hunt results recorded successfully")
        except Exception as e:
            logger.error(f"❌ Failed to record hunt results: {e}")
            raise
    
    def get_working_proxies(self, limit=None):
        """Get working proxies ordered by hunt score and response time"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                query = """
                    SELECT ip, port, proxy_type, source, repository, country, city, last_checked, response_time, hunt_score
                    FROM proxies WHERE is_working = 1 
                    ORDER BY hunt_score DESC, response_time ASC
                """
                
                if limit:
                    query += f" LIMIT {limit}"
                
                results = conn.execute(query).fetchall()
                logger.info(f"🐕 Retrieved {len(results)} working proxies")
                return results
        except Exception as e:
            logger.error(f"❌ Failed to get working proxies: {e}")
            return []
    
    def get_hunt_stats(self):
        """Get hunting statistics"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                total = conn.execute("SELECT COUNT(*) FROM proxies").fetchone()[0]
                working = conn.execute("SELECT COUNT(*) FROM proxies WHERE is_working = 1").fetchone()[0]
                
                # Repository stats with hunt scores
                repo_stats = {}
                for row in conn.execute("""
                    SELECT repository, COUNT(*), AVG(hunt_score), AVG(response_time)
                    FROM proxies WHERE is_working = 1 AND repository IS NOT NULL 
                    GROUP BY repository ORDER BY COUNT(*) DESC LIMIT 10
                """):
                    repo_stats[row[0]] = {
                        "count": row[1], 
                        "avg_hunt_score": round(row[2] or 0, 1),
                        "avg_response_time": round(row[3] or 0, 1)
                    }
                
                # Type stats
                type_stats = {}
                for row in conn.execute("SELECT proxy_type, COUNT(*) FROM proxies WHERE is_working = 1 GROUP BY proxy_type"):
                    type_stats[row[0] or 'unknown'] = row[1]
                
                # Country stats
                country_stats = {}
                for row in conn.execute("SELECT country, COUNT(*) FROM proxies WHERE is_working = 1 AND country IS NOT NULL GROUP BY country ORDER BY COUNT(*) DESC LIMIT 10"):
                    country_stats[row[0]] = row[1]
                
                # City stats
                city_stats = {}
                for row in conn.execute("SELECT city, country, COUNT(*) FROM proxies WHERE is_working = 1 AND city IS NOT NULL GROUP BY city, country ORDER BY COUNT(*) DESC LIMIT 10"):
                    city_key = f"{row[0]}, {row[1]}" if row[1] else row[0]
                    city_stats[city_key] = row[2]
                
                # Hunt success by repository
                hunt_success = {}
                for row in conn.execute("""
                    SELECT repository, AVG(success_rate), COUNT(*)
                    FROM hunt_results GROUP BY repository ORDER BY AVG(success_rate) DESC LIMIT 10
                """):
                    hunt_success[row[0]] = {
                        "avg_success_rate": round(row[1] * 100, 1),
                        "hunts": row[2]
                    }
                
                stats = {
                    "total_proxies": total,
                    "working_proxies": working,
                    "success_rate": round((working / total * 100) if total > 0 else 0, 2),
                    "by_type": type_stats,
                    "by_repository": repo_stats,
                    "by_country": country_stats,
                    "by_city": city_stats,
                    "hunt_success": hunt_success,
                    "geolocated_proxies": conn.execute("SELECT COUNT(*) FROM proxies WHERE is_working = 1 AND country IS NOT NULL").fetchone()[0],
                    "countries_found": len(country_stats),
                    "cities_found": len(city_stats)
                }
                
                logger.info(f"🐕 Hunt stats compiled: {working}/{total} working")
                return stats
        except Exception as e:
            logger.error(f"❌ Failed to get hunt stats: {e}")
            return {"total_proxies": 0, "working_proxies": 0, "success_rate": 0, "by_type": {}, "by_repository": {}, "by_country": {}, "by_city": {}, "hunt_success": {}, "geolocated_proxies": 0, "countries_found": 0, "cities_found": 0}

class ProxyHound:
    """
    Proxy Hound - Advanced Repository Hunter with Geolocation
    
    Multi-factor repository analysis:
    - Scent tracking (recency, activity patterns)
    - Pack behavior analysis (forks, community activity) 
    - Territory mapping (content analysis, file patterns)
    - Hunt success learning (performance feedback)
    - Comprehensive geolocation support
    """
    
    def __init__(self, github_token=None):
        self.github_token = github_token
        self.session = None
        self.hunt_tracker = HuntTracker()
        self.scent_analyzer = ScentAnalyzer()
        self.geolocation_service = GeolocationService()
        self.proxy_pattern = re.compile(r'^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d{1,5})$')
        logger.info("🐕 Proxy Hound with Geolocation initialized - ready to hunt")
    
    async def __aenter__(self):
        headers = {"User-Agent": "ProxyHound/2.1"}
        if self.github_token:
            headers["Authorization"] = f"Bearer {self.github_token}"
            logger.info(f"🔑 GitHub token configured: {self.github_token[:10]}...")
        
        timeout = aiohttp.ClientTimeout(total=20, connect=5)
        connector = aiohttp.TCPConnector(limit=100, ttl_dns_cache=300)
        self.session = aiohttp.ClientSession(headers=headers, timeout=timeout, connector=connector)
        logger.info("🌐 Hunting session established")
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
            logger.info("🔌 Hunting session closed")
    
    async def start_hunt(self, max_pages=3, max_memory_mb=512):
        """Start the proxy hunting expedition"""
        logger.info("🐕 Proxy Hound starting hunting expedition")
        
        all_prey = []  # All found proxies
        
        # Phase 1: Repository hunting
        if self.github_token:
            logger.info("🏞️ Phase 1: Repository territory hunting")
            repo_prey = await self._hunt_repositories(max_pages, max_memory_mb)
            all_prey.extend(repo_prey)
            logger.info(f"  ✅ Repository hunt: {len(repo_prey)} proxies found")
        else:
            logger.warning("⚠️ No GitHub token - skipping repository hunting")
        
        # Phase 2: Backup hunting grounds (only if needed)
        if len(all_prey) < 1000:
            logger.info("🏕️ Phase 2: Backup hunting grounds")
            backup_prey = await self._hunt_backup_grounds()
            all_prey.extend(backup_prey)
            logger.info(f"  ✅ Backup hunt: {len(backup_prey)} proxies found")
        
        # Remove duplicate prey
        logger.info("🔍 Removing duplicate prey...")
        unique_prey = self._remove_duplicate_prey(all_prey)
        
        logger.info(f"🏆 Hunt complete: {len(unique_prey)} unique proxies captured")
        return unique_prey
    
    async def _hunt_repositories(self, max_pages, max_memory_mb):
        """Hunt through GitHub repositories for proxy treasures"""
        logger.info("🐕 Starting repository territory hunt")
        
        # Hunting grounds (search queries)
        hunting_grounds = [
            "free proxies updated language:text pushed:>2024-01-01",
            "working proxy list language:text size:>10",
            "fresh socks proxy language:text",
            "daily proxy update language:text",
            "live proxy collection language:text"
        ]
        
        all_repositories = []
        
        # Search all hunting grounds
        for i, ground in enumerate(hunting_grounds):
            logger.info(f"🌲 Hunting ground {i+1}/{len(hunting_grounds)}: {ground.split()[0]} {ground.split()[1]}")
            
            try:
                repositories = await self._search_hunting_ground(ground, max_pages)
                all_repositories.extend(repositories)
                logger.info(f"  📍 Found {len(repositories)} repositories")
                
                await asyncio.sleep(2)  # Rest between hunts
                
            except Exception as e:
                logger.error(f"  ❌ Hunting ground failed: {e}")
                continue
        
        # Score and rank all found repositories
        scored_repositories = await self._score_and_rank_prey(all_repositories)
        
        # Hunt the best repositories
        all_proxies = []
        hunted_count = 0
        
        for hunt_score, repo in scored_repositories[:25]:  # Hunt top 25
            if hunt_score < 25:  # Skip weak scent trails
                break
                
            logger.info(f"🎯 Hunting: {repo['full_name']} (hunt score: {hunt_score})")
            
            repo_proxies = await self._hunt_repository_content(repo, hunt_score)
            all_proxies.extend(repo_proxies)
            hunted_count += 1
            
            logger.info(f"  🏹 Captured {len(repo_proxies)} proxies")
            
            # Memory management
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            if memory_mb > max_memory_mb and hunted_count >= 10:
                logger.info(f"💾 Memory limit reached ({memory_mb:.1f}MB), ending hunt")
                break
            
            await asyncio.sleep(0.5)
        
        logger.info(f"🏆 Repository hunt complete: {hunted_count} territories, {len(all_proxies)} proxies")
        return all_proxies
    
    async def _search_hunting_ground(self, query, max_pages):
        """Search a specific hunting ground for repositories"""
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
                        logger.warning("    ⚠️ Rate limit hit, resting...")
                        break
                    
                    if response.status != 200:
                        continue
                    
                    data = await response.json()
                    items = data.get("items", [])
                    
                    if not items:
                        break
                    
                    # Pre-filter for quality
                    quality_repos = [repo for repo in items if self._is_quality_territory(repo)]
                    repositories.extend(quality_repos)
                    
                    logger.info(f"    📄 Page {page}: {len(quality_repos)}/{len(items)} quality territories")
                
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"    ❌ Search error: {e}")
                continue
        
        return repositories
    
    def _is_quality_territory(self, repo):
        """Pre-filter repositories for basic quality indicators"""
        # Size check
        size_kb = repo.get('size', 0)
        if size_kb < 10 or size_kb > 50000:
            return False
        
        # Recent activity check
        try:
            updated = datetime.fromisoformat(repo['updated_at'].replace('Z', '+00:00'))
            days_ago = (datetime.now(timezone.utc) - updated).days
            if days_ago > 365:  # No activity in a year
                return False
        except:
            return False
        
        # Basic relevance check
        name = repo.get('name', '').lower, r'.*live.*\.txt#!/usr/bin/env python3
"""
Proxy Hound - Advanced Repository Hunter v2.1
1. Hunt GitHub repositories using scent tracking and pack behavior analysis
2. Deep content analysis for proxy treasure detection
3. Learning system that improves hunting success over time
4. High-performance parallel proxy validation
5. Comprehensive geolocation support
"""

import asyncio
import json
import logging
import sqlite3
import time
import gzip
import re
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Set
from dataclasses import dataclass, asdict
import random
import ssl
import hashlib

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

# Verified hunting grounds (direct sources as backup)
BACKUP_HUNTING_GROUNDS = [
    "https://raw.githubusercontent.com/r00tee/Proxy-List/main/Socks4.txt", 
    "https://raw.githubusercontent.com/r00tee/Proxy-List/main/Socks5.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/http.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/https.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/socks4.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/socks5.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt"
]

@dataclass
class GeolocationInfo:
    """Comprehensive geolocation information."""
    country: Optional[str] = None
    country_code: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    timezone: Optional[str] = None
    isp: Optional[str] = None
    organization: Optional[str] = None
    as_number: Optional[str] = None
    threat_level: Optional[str] = None

@dataclass
class ProxyInfo:
    """Enhanced proxy information with geolocation."""
    ip: str
    port: int
    proxy_type: str
    source: str
    repository: Optional[str] = None
    hunt_score: float = 0.0
    country: Optional[str] = None
    city: Optional[str] = None
    last_checked: Optional[str] = None
    is_working: bool = False
    response_time: Optional[float] = None
    first_seen: Optional[str] = None
    geolocation: Optional[GeolocationInfo] = None
    
    @property
    def location_string(self) -> str:
        """Get human-readable location string."""
        if self.geolocation:
            parts = []
            if self.geolocation.city:
                parts.append(self.geolocation.city)
            if self.geolocation.region:
                parts.append(self.geolocation.region)
            if self.geolocation.country:
                parts.append(self.geolocation.country)
            return ", ".join(parts) if parts else "Unknown"
        elif self.city and self.country:
            return f"{self.city}, {self.country}"
        elif self.country:
            return self.country
        return "Unknown"

class GeolocationService:
    """Geolocation service with multiple providers and caching."""
    
    def __init__(self, cache_size: int = 10000):
        self.cache: Dict[str, GeolocationInfo] = {}
        self.cache_size = cache_size
        self.session_timeout = aiohttp.ClientTimeout(total=10)
        
        # Multiple geolocation providers (free tier)
        self.providers = [
            {
                'name': 'ip-api',
                'url': 'http://ip-api.com/json/{ip}?fields=status,message,country,countryCode,region,regionName,city,lat,lon,timezone,isp,org,as,mobile,proxy,hosting',
                'rate_limit': 45,  # requests per minute
                'last_request': 0
            },
            {
                'name': 'ipapi.co',
                'url': 'https://ipapi.co/{ip}/json/',
                'rate_limit': 30,  # requests per minute for free tier
                'last_request': 0
            },
            {
                'name': 'ipwhois.app',
                'url': 'http://ipwho.is/{ip}',
                'rate_limit': 1000,  # requests per hour
                'last_request': 0
            }
        ]
    
    async def get_geolocation(self, ip: str) -> Optional[GeolocationInfo]:
        """Get geolocation for IP with caching and fallback providers."""
        
        # Check cache first
        if ip in self.cache:
            logger.debug(f"🗺️ Cache hit for {ip}")
            return self.cache[ip]
        
        # Try each provider until we get a result
        for provider in self.providers:
            try:
                result = await self._query_provider(provider, ip)
                if result:
                    # Cache the result
                    if len(self.cache) >= self.cache_size:
                        # Simple cache eviction - remove oldest entry
                        self.cache.pop(next(iter(self.cache)))
                    
                    self.cache[ip] = result
                    logger.debug(f"🌍 Geolocation found for {ip}: {result.city}, {result.country}")
                    return result
                    
            except Exception as e:
                logger.debug(f"❌ Provider {provider['name']} failed for {ip}: {e}")
                continue
        
        logger.debug(f"⚠️ No geolocation found for {ip}")
        return None
    
    async def _query_provider(self, provider: Dict, ip: str) -> Optional[GeolocationInfo]:
        """Query a specific geolocation provider."""
        
        # Rate limiting
        current_time = time.time()
        time_since_last = current_time - provider['last_request']
        min_interval = 60.0 / provider['rate_limit']  # Convert to seconds between requests
        
        if time_since_last < min_interval:
            sleep_time = min_interval - time_since_last
            await asyncio.sleep(sleep_time)
        
        provider['last_request'] = time.time()
        
        url = provider['url'].format(ip=ip)
        
        async with aiohttp.ClientSession(timeout=self.session_timeout) as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return self._parse_response(provider['name'], data)
                else:
                    logger.debug(f"❌ {provider['name']} returned status {response.status} for {ip}")
                    return None
    
    def _parse_response(self, provider_name: str, data: Dict) -> Optional[GeolocationInfo]:
        """Parse geolocation response based on provider format."""
        
        try:
            if provider_name == 'ip-api':
                if data.get('status') == 'success':
                    return GeolocationInfo(
                        country=data.get('country'),
                        country_code=data.get('countryCode'),
                        region=data.get('regionName'),
                        city=data.get('city'),
                        latitude=data.get('lat'),
                        longitude=data.get('lon'),
                        timezone=data.get('timezone'),
                        isp=data.get('isp'),
                        organization=data.get('org'),
                        as_number=data.get('as'),
                        threat_level='proxy' if data.get('proxy') else 'clean'
                    )
            
            elif provider_name == 'ipapi.co':
                if 'error' not in data:
                    return GeolocationInfo(
                        country=data.get('country_name'),
                        country_code=data.get('country_code'),
                        region=data.get('region'),
                        city=data.get('city'),
                        latitude=data.get('latitude'),
                        longitude=data.get('longitude'),
                        timezone=data.get('timezone'),
                        isp=data.get('org'),
                        organization=data.get('org')
                    )
            
            elif provider_name == 'ipwhois.app':
                if data.get('success'):
                    return GeolocationInfo(
                        country=data.get('country'),
                        country_code=data.get('country_code'),
                        region=data.get('region'),
                        city=data.get('city'),
                        latitude=data.get('latitude'),
                        longitude=data.get('longitude'),
                        timezone=data.get('timezone', {}).get('id') if isinstance(data.get('timezone'), dict) else None,
                        isp=data.get('connection', {}).get('isp') if isinstance(data.get('connection'), dict) else None,
                        organization=data.get('connection', {}).get('org') if isinstance(data.get('connection'), dict) else None,
                        as_number=data.get('connection', {}).get('asn') if isinstance(data.get('connection'), dict) else None
                    )
            
        except Exception as e:
            logger.debug(f"❌ Error parsing {provider_name} response: {e}")
        
        return None

class HuntTracker:
    """Track hunting success to improve future hunts"""
    
    def __init__(self):
        self.successful_hunts = {}
        self.failed_hunts = {}
        self.pack_reputation = {}  # Owner success rates
        logger.info("🐕 Hunt tracker initialized")
    
    def record_hunt_result(self, repo_name, hunt_score, working_proxies, total_proxies):
        """Record how successful a repository hunt was"""
        success_rate = (working_proxies / total_proxies) if total_proxies > 0 else 0
        
        hunt_data = {
            'hunt_score': hunt_score,
            'success_rate': success_rate,
            'working_proxies': working_proxies,
            'total_proxies': total_proxies,
            'hunted_at': datetime.now(timezone.utc).isoformat()
        }
        
        if success_rate > 0.1:  # Good hunt (>10% success)
            self.successful_hunts[repo_name] = hunt_data
            logger.info(f"🏆 Successful hunt recorded: {repo_name} ({success_rate:.1%})")
        else:  # Poor hunt
            self.failed_hunts[repo_name] = hunt_data
            logger.info(f"❌ Failed hunt recorded: {repo_name}")
        
        # Track pack (owner) reputation
        owner = repo_name.split('/')[0]
        if owner not in self.pack_reputation:
            self.pack_reputation[owner] = []
        self.pack_reputation[owner].append(success_rate)
    
    def get_pack_reputation(self, owner):
        """Get average success rate for a repository owner"""
        if owner in self.pack_reputation and self.pack_reputation[owner]:
            return sum(self.pack_reputation[owner]) / len(self.pack_reputation[owner])
        return 0.0

class ScentAnalyzer:
    """Analyze repository 'scent' for quality indicators"""
    
    def __init__(self):
        # Strong scent indicators (likely to have good proxies)
        self.strong_scent_keywords = [
            'working', 'live', 'fresh', 'tested', 'verified', 'daily', 'updated',
            'active', 'new', 'current', 'valid', 'checked'
        ]
        
        # Weak scent indicators (likely stale)
        self.weak_scent_keywords = [
            'old', 'archive', 'deprecated', 'backup', 'mirror', 'copy', 'dead',
            'inactive', 'outdated', 'legacy'
        ]
        
        # Territory markers (file patterns that indicate good hunting grounds)
        self.territory_markers = [
            r'.*working.*proxy.*\.txt$',
            r'.*live.*\.txt$', 
            r'.*fresh.*\.txt$',
            r'.*valid.*\.txt$',
            r'.*\d{4}-\d{2}-\d{2}.*\.txt$',  # Date in filename
            r'.*proxy.*list.*\.txt$',
            r'.*socks.*\.txt$',
            r'.*http.*\.txt$'
        ]
        
        logger.info("🐕 Scent analyzer initialized with hunting patterns")
    
    def analyze_scent_strength(self, repo):
        """Analyze how 'fresh' the repository scent is"""
        scent_score = 0
        
        name = repo.get('name', '').lower()
        desc = repo.get('description', '').lower()
        text = f"{name} {desc}"
        
        # Strong scent detection
        strong_matches = sum(1 for keyword in self.strong_scent_keywords 
                           if keyword in text)
        scent_score += strong_matches * 15
        
        # Weak scent penalty
        weak_matches = sum(1 for keyword in self.weak_scent_keywords 
                         if keyword in text)
        scent_score -= weak_matches * 10
        
        # Territory freshness (last updated)
        try:
            updated = datetime.fromisoformat(repo['updated_at'].replace('Z', '+00:00'))
            days_ago = (datetime.now(timezone.utc) - updated).days
            
            if days_ago < 7:
                scent_score += 50    # Very fresh scent
            elif days_ago < 30:
                scent_score += 30    # Fresh scent
            elif days_ago < 90:
                scent_score += 15    # Fading scent
            else:
                scent_score -= 20    # Cold trail
        except:
            scent_score -= 15
        
        return max(0, scent_score)

class ProxyHoundDatabase:
    """Database for tracking Proxy Hound hunting results"""
    
    def __init__(self, db_path="proxy_hound.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Initialize hunting database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL") 
                conn.execute("PRAGMA cache_size=10000")
                conn.execute("PRAGMA temp_store=MEMORY")
                
                # Create proxies table with hunt tracking
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS proxies (
                        id INTEGER PRIMARY KEY,
                        ip TEXT NOT NULL,
                        port INTEGER NOT NULL,
                        proxy_type TEXT,
                        source TEXT NOT NULL,
                        repository TEXT,
                        hunt_score REAL DEFAULT 0,
                        country TEXT,
                        city TEXT,
                        last_checked TEXT,
                        is_working BOOLEAN DEFAULT 0,
                        response_time REAL,
                        first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(ip, port)
                    )
                """)
                
                # Create hunt results table
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS hunt_results (
                        id INTEGER PRIMARY KEY,
                        repository TEXT NOT NULL,
                        hunt_score REAL,
                        total_proxies INTEGER,
                        working_proxies INTEGER,
                        success_rate REAL,
                        hunted_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Create indexes
                indexes = [
                    "CREATE INDEX IF NOT EXISTS idx_ip_port ON proxies(ip, port)",
                    "CREATE INDEX IF NOT EXISTS idx_working ON proxies(is_working)",
                    "CREATE INDEX IF NOT EXISTS idx_hunt_score ON proxies(hunt_score)",
                    "CREATE INDEX IF NOT EXISTS idx_repository ON proxies(repository)",
                    "CREATE INDEX IF NOT EXISTS idx_hunt_results_repo ON hunt_results(repository)"
                ]
                
                for index_sql in indexes:
                    conn.execute(index_sql)
                
            logger.info("🐕 Proxy Hound database initialized")
        except Exception as e:
            logger.error(f"❌ Database initialization failed: {e}")
            raise
    
    def add_hunt_results(self, proxies, batch_size=1000):
        """Add hunting results to database"""
        if not proxies:
            return
            
        logger.info(f"🐕 Recording hunt results: {len(proxies)} proxies")
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("BEGIN TRANSACTION")
                
                for i in range(0, len(proxies), batch_size):
                    batch = proxies[i:i + batch_size]
                    
                    data = [
                        (p.ip, p.port, p.proxy_type, p.source, 
                         p.repository, p.hunt_score, p.country, p.city,
                         p.last_checked, p.is_working, p.response_time)
                        for p in batch
                    ]
                    
                    conn.executemany("""
                        INSERT OR REPLACE INTO proxies 
                        (ip, port, proxy_type, source, repository, hunt_score, country, city, last_checked, is_working, response_time)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, data)
                
                conn.execute("COMMIT")
                logger.info("✅ Hunt results recorded successfully")
        except Exception as e:
            logger.error(f"❌ Failed to record hunt results: {e}")
            raise
    
    def get_working_proxies(self, limit=None):
        """Get working proxies ordered by hunt score and response time"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                query = """
                    SELECT ip, port, proxy_type, source, repository, country, city, last_checked, response_time, hunt_score
                    FROM proxies WHERE is_working = 1 
                    ORDER BY hunt_score DESC, response_time ASC
                """
                
                if limit:
                    query += f" LIMIT {limit}"
                
                results = conn.execute(query).fetchall()
                logger.info(f"🐕 Retrieved {len(results)} working proxies")
                return results
        except Exception as e:
            logger.error(f"❌ Failed to get working proxies: {e}")
            return []
    
    def get_hunt_stats(self):
        """Get hunting statistics"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                total = conn.execute("SELECT COUNT(*) FROM proxies").fetchone()[0]
                working = conn.execute("SELECT COUNT(*) FROM proxies WHERE is_working = 1").fetchone()[0]
                
                # Repository stats with hunt scores
                repo_stats = {}
                for row in conn.execute("""
                    SELECT repository, COUNT(*), AVG(hunt_score), AVG(response_time)
                    FROM proxies WHERE is_working = 1 AND repository IS NOT NULL 
                    GROUP BY repository ORDER BY COUNT(*) DESC LIMIT 10
                """):
                    repo_stats[row[0]] = {
                        "count": row[1], 
                        "avg_hunt_score": round(row[2] or 0, 1),
                        "avg_response_time": round(row[3] or 0, 1)
                    }
                
                # Type stats
                type_stats = {}
                for row in conn.execute("SELECT proxy_type, COUNT(*) FROM proxies WHERE is_working = 1 GROUP BY proxy_type"):
                    type_stats[row[0] or 'unknown'] = row[1]
                
                # Country stats
                country_stats = {}
                for row in conn.execute("SELECT country, COUNT(*) FROM proxies WHERE is_working = 1 AND country IS NOT NULL GROUP BY country ORDER BY COUNT(*) DESC LIMIT 10"):
                    country_stats[row[0]] = row[1]
                
                # City stats
                city_stats = {}
                for row in conn.execute("SELECT city, country, COUNT(*) FROM proxies WHERE is_working = 1 AND city IS NOT NULL GROUP BY city, country ORDER BY COUNT(*) DESC LIMIT 10"):
                    city_key = f"{row[0]}, {row[1]}" if row[1] else row[0]
                    city_stats[city_key] = row[2]
                
                # Hunt success by repository
                hunt_success = {}
                for row in conn.execute("""
                    SELECT repository, AVG(success_rate), COUNT(*)
                    FROM hunt_results GROUP BY repository ORDER BY AVG(success_rate) DESC LIMIT 10
                """):
                    hunt_success[row[0]] = {
                        "avg_success_rate": round(row[1] * 100, 1),
                        "hunts": row[2]
                    }
                
                stats = {
                    "total_proxies": total,
                    "working_proxies": working,
                    "success_rate": round((working / total * 100) if total > 0 else 0, 2),
                    "by_type": type_stats,
                    "by_repository": repo_stats,
                    "by_country": country_stats,
                    "by_city": city_stats,
                    "hunt_success": hunt_success,
                    "geolocated_proxies": conn.execute("SELECT COUNT(*) FROM proxies WHERE is_working = 1 AND country IS NOT NULL").fetchone()[0],
                    "countries_found": len(country_stats),
                    "cities_found": len(city_stats)
                }
                
                logger.info(f"🐕 Hunt stats compiled: {working}/{total} working")
                return stats
        except Exception as e:
            logger.error(f"❌ Failed to get hunt stats: {e}")
            return {"total_proxies": 0, "working_proxies": 0, "success_rate": 0, "by_type": {}, "by_repository": {}, "by_country": {}, "by_city": {}, "hunt_success": {}, "geolocated_proxies": 0, "countries_found": 0, "cities_found": 0}

class ProxyHound:
    """
    Proxy Hound - Advanced Repository Hunter with Geolocation
    
    Multi-factor repository analysis:
    - Scent tracking (recency, activity patterns)
    - Pack behavior analysis (forks, community activity) 
    - Territory mapping (content analysis, file patterns)
    - Hunt success learning (performance feedback)
    - Comprehensive geolocation support
    """
    
    def __init__(self, github_token=None):
        self.github_token = github_token
        self.session = None
        self.hunt_tracker = HuntTracker()
        self.scent_analyzer = ScentAnalyzer()
        self.geolocation_service = GeolocationService()
        self.proxy_pattern = re.compile(r'^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d{1,5})$')
        logger.info("🐕 Proxy Hound with Geolocation initialized - ready to hunt")
    
    async def __aenter__(self):
        headers = {"User-Agent": "ProxyHound/2.1"}
        if self.github_token:
            headers["Authorization"] = f"Bearer {self.github_token}"
            logger.info(f"🔑 GitHub token configured: {self.github_token[:10]}...")
        
        timeout = aiohttp.ClientTimeout(total=20, connect=5)
        connector = aiohttp.TCPConnector(limit=100, ttl_dns_cache=300)
        self.session = aiohttp.ClientSession(headers=headers, timeout=timeout, connector=connector)
        logger.info("🌐 Hunting session established")
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
            logger.info("🔌 Hunting session closed")
    
    async def start_hunt(self, max_pages=3, max_memory_mb=512):
        """Start the proxy hunting expedition"""
        logger.info("🐕 Proxy Hound starting hunting expedition")
        
        all_prey = []  # All found proxies
        
        # Phase 1: Repository hunting
        if self.github_token:
            logger.info("🏞️ Phase 1: Repository territory hunting")
            repo_prey = await self._hunt_repositories(max_pages, max_memory_mb)
            all_prey.extend(repo_prey)
            logger.info(f"  ✅ Repository hunt: {len(repo_prey)} proxies found")
        else:
            logger.warning("⚠️ No GitHub token - skipping repository hunting")
        
        # Phase 2: Backup hunting grounds (only if needed)
        if len(all_prey) < 1000:
            logger.info("🏕️ Phase 2: Backup hunting grounds")
            backup_prey = await self._hunt_backup_grounds()
            all_prey.extend(backup_prey)
            logger.info(f"  ✅ Backup hunt: {len(backup_prey)} proxies found")
        
        # Remove duplicate prey
        logger.info("🔍 Removing duplicate prey...")
        unique_prey = self._remove_duplicate_prey(all_prey)
        
        logger.info(f"🏆 Hunt complete: {len(unique_prey)} unique proxies captured")
        return unique_prey
    
    async def _hunt_repositories(self, max_pages, max_memory_mb):
        """Hunt through GitHub repositories for proxy treasures"""
        logger.info("🐕 Starting repository territory hunt")
        
        # Hunting grounds (search queries)
        hunting_grounds = [
            "free proxies updated language:text pushed:>2024-01-01",
            "working proxy list language:text size:>10",
            "fresh socks proxy language:text",
            "daily proxy update language:text",
            "live proxy collection language:text"
        ]
        
        all_repositories = []
        
        # Search all hunting grounds
        for i, ground in enumerate(hunting_grounds):
            logger.info(f"🌲 Hunting ground {i+1}/{len(hunting_grounds)}: {ground.split()[0]} {ground.split()[1]}")
            
            try:
                repositories = await self._search_hunting_ground(ground, max_pages)
                all_repositories.extend(repositories)
                logger.info(f"  📍 Found {len(repositories)} repositories")
                
                await asyncio.sleep(2)  # Rest between hunts
                
            except Exception as e:
                logger.error(f"  ❌ Hunting ground failed: {e}")
                continue
        
        # Score and rank all found repositories
        scored_repositories = await self._score_and_rank_prey(all_repositories)
        
        # Hunt the best repositories
        all_proxies = []
        hunted_count = 0
        
        for hunt_score, repo in scored_repositories[:25]:  # Hunt top 25
            if hunt_score < 25:  # Skip weak scent trails
                break
                
            logger.info(f"🎯 Hunting: {repo['full_name']} (hunt score: {hunt_score})")
            
            repo_proxies = await self._hunt_repository_content(repo, hunt_score)
            all_proxies.extend(repo_proxies)
            hunted_count += 1
            
            logger.info(f"  🏹 Captured {len(repo_proxies)} proxies")
            
            # Memory management
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            if memory_mb > max_memory_mb and hunted_count >= 10:
                logger.info(f"💾 Memory limit reached ({memory_mb:.1f}MB), ending hunt")
                break
            
            await asyncio.sleep(0.5)
        
        logger.info(f"🏆 Repository hunt complete: {hunted_count} territories, {len(all_proxies)} proxies")
        return all_proxies
    
    async def _search_hunting_ground(self, query, max_pages):
        """Search a specific hunting ground for repositories"""
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
                        logger.warning("    ⚠️ Rate limit hit, resting...")
                        break
                    
                    if response.status != 200:
                        continue
                    
                    data = await response.json()
                    items = data.get("items", [])
                    
                    if not items:
                        break
                    
                    # Pre-filter for quality
                    quality_repos = [repo for repo in items if self._is_quality_territory(repo)]
                    repositories.extend(quality_repos)
                    
                    logger.info(f"    📄 Page {page}: {len(quality_repos)}/{len(items)} quality territories")
                
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"    ❌ Search error: {e}")
                continue
        
        return repositories
    
    def _is_quality_territory(self, repo):
        """Pre-filter repositories for basic quality indicators"""
        # Size check
        size_kb = repo.get('size', 0)
        if size_kb < 10 or size_kb > 50000:
            return False
        
        # Recent activity check
        try:
            updated = datetime.fromisoformat(repo['updated_at'].replace('Z', '+00:00'))
            days_ago = (datetime.now(timezone.utc) - updated).days
            if days_ago > 365:  # No activity in a year
                return False
        except:
            return False
        
        # Basic relevance check
        name = repo.get('name', '').lower, r'.*valid.*\.txt#!/usr/bin/env python3
"""
Proxy Hound - Advanced Repository Hunter v2.1
1. Hunt GitHub repositories using scent tracking and pack behavior analysis
2. Deep content analysis for proxy treasure detection
3. Learning system that improves hunting success over time
4. High-performance parallel proxy validation
5. Comprehensive geolocation support
"""

import asyncio
import json
import logging
import sqlite3
import time
import gzip
import re
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Set
from dataclasses import dataclass, asdict
import random
import ssl
import hashlib

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

# Verified hunting grounds (direct sources as backup)
BACKUP_HUNTING_GROUNDS = [
    "https://raw.githubusercontent.com/r00tee/Proxy-List/main/Socks4.txt", 
    "https://raw.githubusercontent.com/r00tee/Proxy-List/main/Socks5.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/http.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/https.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/socks4.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/socks5.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt"
]

@dataclass
class GeolocationInfo:
    """Comprehensive geolocation information."""
    country: Optional[str] = None
    country_code: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    timezone: Optional[str] = None
    isp: Optional[str] = None
    organization: Optional[str] = None
    as_number: Optional[str] = None
    threat_level: Optional[str] = None

@dataclass
class ProxyInfo:
    """Enhanced proxy information with geolocation."""
    ip: str
    port: int
    proxy_type: str
    source: str
    repository: Optional[str] = None
    hunt_score: float = 0.0
    country: Optional[str] = None
    city: Optional[str] = None
    last_checked: Optional[str] = None
    is_working: bool = False
    response_time: Optional[float] = None
    first_seen: Optional[str] = None
    geolocation: Optional[GeolocationInfo] = None
    
    @property
    def location_string(self) -> str:
        """Get human-readable location string."""
        if self.geolocation:
            parts = []
            if self.geolocation.city:
                parts.append(self.geolocation.city)
            if self.geolocation.region:
                parts.append(self.geolocation.region)
            if self.geolocation.country:
                parts.append(self.geolocation.country)
            return ", ".join(parts) if parts else "Unknown"
        elif self.city and self.country:
            return f"{self.city}, {self.country}"
        elif self.country:
            return self.country
        return "Unknown"

class GeolocationService:
    """Geolocation service with multiple providers and caching."""
    
    def __init__(self, cache_size: int = 10000):
        self.cache: Dict[str, GeolocationInfo] = {}
        self.cache_size = cache_size
        self.session_timeout = aiohttp.ClientTimeout(total=10)
        
        # Multiple geolocation providers (free tier)
        self.providers = [
            {
                'name': 'ip-api',
                'url': 'http://ip-api.com/json/{ip}?fields=status,message,country,countryCode,region,regionName,city,lat,lon,timezone,isp,org,as,mobile,proxy,hosting',
                'rate_limit': 45,  # requests per minute
                'last_request': 0
            },
            {
                'name': 'ipapi.co',
                'url': 'https://ipapi.co/{ip}/json/',
                'rate_limit': 30,  # requests per minute for free tier
                'last_request': 0
            },
            {
                'name': 'ipwhois.app',
                'url': 'http://ipwho.is/{ip}',
                'rate_limit': 1000,  # requests per hour
                'last_request': 0
            }
        ]
    
    async def get_geolocation(self, ip: str) -> Optional[GeolocationInfo]:
        """Get geolocation for IP with caching and fallback providers."""
        
        # Check cache first
        if ip in self.cache:
            logger.debug(f"🗺️ Cache hit for {ip}")
            return self.cache[ip]
        
        # Try each provider until we get a result
        for provider in self.providers:
            try:
                result = await self._query_provider(provider, ip)
                if result:
                    # Cache the result
                    if len(self.cache) >= self.cache_size:
                        # Simple cache eviction - remove oldest entry
                        self.cache.pop(next(iter(self.cache)))
                    
                    self.cache[ip] = result
                    logger.debug(f"🌍 Geolocation found for {ip}: {result.city}, {result.country}")
                    return result
                    
            except Exception as e:
                logger.debug(f"❌ Provider {provider['name']} failed for {ip}: {e}")
                continue
        
        logger.debug(f"⚠️ No geolocation found for {ip}")
        return None
    
    async def _query_provider(self, provider: Dict, ip: str) -> Optional[GeolocationInfo]:
        """Query a specific geolocation provider."""
        
        # Rate limiting
        current_time = time.time()
        time_since_last = current_time - provider['last_request']
        min_interval = 60.0 / provider['rate_limit']  # Convert to seconds between requests
        
        if time_since_last < min_interval:
            sleep_time = min_interval - time_since_last
            await asyncio.sleep(sleep_time)
        
        provider['last_request'] = time.time()
        
        url = provider['url'].format(ip=ip)
        
        async with aiohttp.ClientSession(timeout=self.session_timeout) as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return self._parse_response(provider['name'], data)
                else:
                    logger.debug(f"❌ {provider['name']} returned status {response.status} for {ip}")
                    return None
    
    def _parse_response(self, provider_name: str, data: Dict) -> Optional[GeolocationInfo]:
        """Parse geolocation response based on provider format."""
        
        try:
            if provider_name == 'ip-api':
                if data.get('status') == 'success':
                    return GeolocationInfo(
                        country=data.get('country'),
                        country_code=data.get('countryCode'),
                        region=data.get('regionName'),
                        city=data.get('city'),
                        latitude=data.get('lat'),
                        longitude=data.get('lon'),
                        timezone=data.get('timezone'),
                        isp=data.get('isp'),
                        organization=data.get('org'),
                        as_number=data.get('as'),
                        threat_level='proxy' if data.get('proxy') else 'clean'
                    )
            
            elif provider_name == 'ipapi.co':
                if 'error' not in data:
                    return GeolocationInfo(
                        country=data.get('country_name'),
                        country_code=data.get('country_code'),
                        region=data.get('region'),
                        city=data.get('city'),
                        latitude=data.get('latitude'),
                        longitude=data.get('longitude'),
                        timezone=data.get('timezone'),
                        isp=data.get('org'),
                        organization=data.get('org')
                    )
            
            elif provider_name == 'ipwhois.app':
                if data.get('success'):
                    return GeolocationInfo(
                        country=data.get('country'),
                        country_code=data.get('country_code'),
                        region=data.get('region'),
                        city=data.get('city'),
                        latitude=data.get('latitude'),
                        longitude=data.get('longitude'),
                        timezone=data.get('timezone', {}).get('id') if isinstance(data.get('timezone'), dict) else None,
                        isp=data.get('connection', {}).get('isp') if isinstance(data.get('connection'), dict) else None,
                        organization=data.get('connection', {}).get('org') if isinstance(data.get('connection'), dict) else None,
                        as_number=data.get('connection', {}).get('asn') if isinstance(data.get('connection'), dict) else None
                    )
            
        except Exception as e:
            logger.debug(f"❌ Error parsing {provider_name} response: {e}")
        
        return None

class HuntTracker:
    """Track hunting success to improve future hunts"""
    
    def __init__(self):
        self.successful_hunts = {}
        self.failed_hunts = {}
        self.pack_reputation = {}  # Owner success rates
        logger.info("🐕 Hunt tracker initialized")
    
    def record_hunt_result(self, repo_name, hunt_score, working_proxies, total_proxies):
        """Record how successful a repository hunt was"""
        success_rate = (working_proxies / total_proxies) if total_proxies > 0 else 0
        
        hunt_data = {
            'hunt_score': hunt_score,
            'success_rate': success_rate,
            'working_proxies': working_proxies,
            'total_proxies': total_proxies,
            'hunted_at': datetime.now(timezone.utc).isoformat()
        }
        
        if success_rate > 0.1:  # Good hunt (>10% success)
            self.successful_hunts[repo_name] = hunt_data
            logger.info(f"🏆 Successful hunt recorded: {repo_name} ({success_rate:.1%})")
        else:  # Poor hunt
            self.failed_hunts[repo_name] = hunt_data
            logger.info(f"❌ Failed hunt recorded: {repo_name}")
        
        # Track pack (owner) reputation
        owner = repo_name.split('/')[0]
        if owner not in self.pack_reputation:
            self.pack_reputation[owner] = []
        self.pack_reputation[owner].append(success_rate)
    
    def get_pack_reputation(self, owner):
        """Get average success rate for a repository owner"""
        if owner in self.pack_reputation and self.pack_reputation[owner]:
            return sum(self.pack_reputation[owner]) / len(self.pack_reputation[owner])
        return 0.0

class ScentAnalyzer:
    """Analyze repository 'scent' for quality indicators"""
    
    def __init__(self):
        # Strong scent indicators (likely to have good proxies)
        self.strong_scent_keywords = [
            'working', 'live', 'fresh', 'tested', 'verified', 'daily', 'updated',
            'active', 'new', 'current', 'valid', 'checked'
        ]
        
        # Weak scent indicators (likely stale)
        self.weak_scent_keywords = [
            'old', 'archive', 'deprecated', 'backup', 'mirror', 'copy', 'dead',
            'inactive', 'outdated', 'legacy'
        ]
        
        # Territory markers (file patterns that indicate good hunting grounds)
        self.territory_markers = [
            r'.*working.*proxy.*\.txt$',
            r'.*live.*\.txt$', 
            r'.*fresh.*\.txt$',
            r'.*valid.*\.txt$',
            r'.*\d{4}-\d{2}-\d{2}.*\.txt$',  # Date in filename
            r'.*proxy.*list.*\.txt$',
            r'.*socks.*\.txt$',
            r'.*http.*\.txt$'
        ]
        
        logger.info("🐕 Scent analyzer initialized with hunting patterns")
    
    def analyze_scent_strength(self, repo):
        """Analyze how 'fresh' the repository scent is"""
        scent_score = 0
        
        name = repo.get('name', '').lower()
        desc = repo.get('description', '').lower()
        text = f"{name} {desc}"
        
        # Strong scent detection
        strong_matches = sum(1 for keyword in self.strong_scent_keywords 
                           if keyword in text)
        scent_score += strong_matches * 15
        
        # Weak scent penalty
        weak_matches = sum(1 for keyword in self.weak_scent_keywords 
                         if keyword in text)
        scent_score -= weak_matches * 10
        
        # Territory freshness (last updated)
        try:
            updated = datetime.fromisoformat(repo['updated_at'].replace('Z', '+00:00'))
            days_ago = (datetime.now(timezone.utc) - updated).days
            
            if days_ago < 7:
                scent_score += 50    # Very fresh scent
            elif days_ago < 30:
                scent_score += 30    # Fresh scent
            elif days_ago < 90:
                scent_score += 15    # Fading scent
            else:
                scent_score -= 20    # Cold trail
        except:
            scent_score -= 15
        
        return max(0, scent_score)

class ProxyHoundDatabase:
    """Database for tracking Proxy Hound hunting results"""
    
    def __init__(self, db_path="proxy_hound.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Initialize hunting database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL") 
                conn.execute("PRAGMA cache_size=10000")
                conn.execute("PRAGMA temp_store=MEMORY")
                
                # Create proxies table with hunt tracking
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS proxies (
                        id INTEGER PRIMARY KEY,
                        ip TEXT NOT NULL,
                        port INTEGER NOT NULL,
                        proxy_type TEXT,
                        source TEXT NOT NULL,
                        repository TEXT,
                        hunt_score REAL DEFAULT 0,
                        country TEXT,
                        city TEXT,
                        last_checked TEXT,
                        is_working BOOLEAN DEFAULT 0,
                        response_time REAL,
                        first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(ip, port)
                    )
                """)
                
                # Create hunt results table
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS hunt_results (
                        id INTEGER PRIMARY KEY,
                        repository TEXT NOT NULL,
                        hunt_score REAL,
                        total_proxies INTEGER,
                        working_proxies INTEGER,
                        success_rate REAL,
                        hunted_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Create indexes
                indexes = [
                    "CREATE INDEX IF NOT EXISTS idx_ip_port ON proxies(ip, port)",
                    "CREATE INDEX IF NOT EXISTS idx_working ON proxies(is_working)",
                    "CREATE INDEX IF NOT EXISTS idx_hunt_score ON proxies(hunt_score)",
                    "CREATE INDEX IF NOT EXISTS idx_repository ON proxies(repository)",
                    "CREATE INDEX IF NOT EXISTS idx_hunt_results_repo ON hunt_results(repository)"
                ]
                
                for index_sql in indexes:
                    conn.execute(index_sql)
                
            logger.info("🐕 Proxy Hound database initialized")
        except Exception as e:
            logger.error(f"❌ Database initialization failed: {e}")
            raise
    
    def add_hunt_results(self, proxies, batch_size=1000):
        """Add hunting results to database"""
        if not proxies:
            return
            
        logger.info(f"🐕 Recording hunt results: {len(proxies)} proxies")
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("BEGIN TRANSACTION")
                
                for i in range(0, len(proxies), batch_size):
                    batch = proxies[i:i + batch_size]
                    
                    data = [
                        (p.ip, p.port, p.proxy_type, p.source, 
                         p.repository, p.hunt_score, p.country, p.city,
                         p.last_checked, p.is_working, p.response_time)
                        for p in batch
                    ]
                    
                    conn.executemany("""
                        INSERT OR REPLACE INTO proxies 
                        (ip, port, proxy_type, source, repository, hunt_score, country, city, last_checked, is_working, response_time)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, data)
                
                conn.execute("COMMIT")
                logger.info("✅ Hunt results recorded successfully")
        except Exception as e:
            logger.error(f"❌ Failed to record hunt results: {e}")
            raise
    
    def get_working_proxies(self, limit=None):
        """Get working proxies ordered by hunt score and response time"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                query = """
                    SELECT ip, port, proxy_type, source, repository, country, city, last_checked, response_time, hunt_score
                    FROM proxies WHERE is_working = 1 
                    ORDER BY hunt_score DESC, response_time ASC
                """
                
                if limit:
                    query += f" LIMIT {limit}"
                
                results = conn.execute(query).fetchall()
                logger.info(f"🐕 Retrieved {len(results)} working proxies")
                return results
        except Exception as e:
            logger.error(f"❌ Failed to get working proxies: {e}")
            return []
    
    def get_hunt_stats(self):
        """Get hunting statistics"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                total = conn.execute("SELECT COUNT(*) FROM proxies").fetchone()[0]
                working = conn.execute("SELECT COUNT(*) FROM proxies WHERE is_working = 1").fetchone()[0]
                
                # Repository stats with hunt scores
                repo_stats = {}
                for row in conn.execute("""
                    SELECT repository, COUNT(*), AVG(hunt_score), AVG(response_time)
                    FROM proxies WHERE is_working = 1 AND repository IS NOT NULL 
                    GROUP BY repository ORDER BY COUNT(*) DESC LIMIT 10
                """):
                    repo_stats[row[0]] = {
                        "count": row[1], 
                        "avg_hunt_score": round(row[2] or 0, 1),
                        "avg_response_time": round(row[3] or 0, 1)
                    }
                
                # Type stats
                type_stats = {}
                for row in conn.execute("SELECT proxy_type, COUNT(*) FROM proxies WHERE is_working = 1 GROUP BY proxy_type"):
                    type_stats[row[0] or 'unknown'] = row[1]
                
                # Country stats
                country_stats = {}
                for row in conn.execute("SELECT country, COUNT(*) FROM proxies WHERE is_working = 1 AND country IS NOT NULL GROUP BY country ORDER BY COUNT(*) DESC LIMIT 10"):
                    country_stats[row[0]] = row[1]
                
                # City stats
                city_stats = {}
                for row in conn.execute("SELECT city, country, COUNT(*) FROM proxies WHERE is_working = 1 AND city IS NOT NULL GROUP BY city, country ORDER BY COUNT(*) DESC LIMIT 10"):
                    city_key = f"{row[0]}, {row[1]}" if row[1] else row[0]
                    city_stats[city_key] = row[2]
                
                # Hunt success by repository
                hunt_success = {}
                for row in conn.execute("""
                    SELECT repository, AVG(success_rate), COUNT(*)
                    FROM hunt_results GROUP BY repository ORDER BY AVG(success_rate) DESC LIMIT 10
                """):
                    hunt_success[row[0]] = {
                        "avg_success_rate": round(row[1] * 100, 1),
                        "hunts": row[2]
                    }
                
                stats = {
                    "total_proxies": total,
                    "working_proxies": working,
                    "success_rate": round((working / total * 100) if total > 0 else 0, 2),
                    "by_type": type_stats,
                    "by_repository": repo_stats,
                    "by_country": country_stats,
                    "by_city": city_stats,
                    "hunt_success": hunt_success,
                    "geolocated_proxies": conn.execute("SELECT COUNT(*) FROM proxies WHERE is_working = 1 AND country IS NOT NULL").fetchone()[0],
                    "countries_found": len(country_stats),
                    "cities_found": len(city_stats)
                }
                
                logger.info(f"🐕 Hunt stats compiled: {working}/{total} working")
                return stats
        except Exception as e:
            logger.error(f"❌ Failed to get hunt stats: {e}")
            return {"total_proxies": 0, "working_proxies": 0, "success_rate": 0, "by_type": {}, "by_repository": {}, "by_country": {}, "by_city": {}, "hunt_success": {}, "geolocated_proxies": 0, "countries_found": 0, "cities_found": 0}

class ProxyHound:
    """
    Proxy Hound - Advanced Repository Hunter with Geolocation
    
    Multi-factor repository analysis:
    - Scent tracking (recency, activity patterns)
    - Pack behavior analysis (forks, community activity) 
    - Territory mapping (content analysis, file patterns)
    - Hunt success learning (performance feedback)
    - Comprehensive geolocation support
    """
    
    def __init__(self, github_token=None):
        self.github_token = github_token
        self.session = None
        self.hunt_tracker = HuntTracker()
        self.scent_analyzer = ScentAnalyzer()
        self.geolocation_service = GeolocationService()
        self.proxy_pattern = re.compile(r'^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d{1,5})$')
        logger.info("🐕 Proxy Hound with Geolocation initialized - ready to hunt")
    
    async def __aenter__(self):
        headers = {"User-Agent": "ProxyHound/2.1"}
        if self.github_token:
            headers["Authorization"] = f"Bearer {self.github_token}"
            logger.info(f"🔑 GitHub token configured: {self.github_token[:10]}...")
        
        timeout = aiohttp.ClientTimeout(total=20, connect=5)
        connector = aiohttp.TCPConnector(limit=100, ttl_dns_cache=300)
        self.session = aiohttp.ClientSession(headers=headers, timeout=timeout, connector=connector)
        logger.info("🌐 Hunting session established")
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
            logger.info("🔌 Hunting session closed")
    
    async def start_hunt(self, max_pages=3, max_memory_mb=512):
        """Start the proxy hunting expedition"""
        logger.info("🐕 Proxy Hound starting hunting expedition")
        
        all_prey = []  # All found proxies
        
        # Phase 1: Repository hunting
        if self.github_token:
            logger.info("🏞️ Phase 1: Repository territory hunting")
            repo_prey = await self._hunt_repositories(max_pages, max_memory_mb)
            all_prey.extend(repo_prey)
            logger.info(f"  ✅ Repository hunt: {len(repo_prey)} proxies found")
        else:
            logger.warning("⚠️ No GitHub token - skipping repository hunting")
        
        # Phase 2: Backup hunting grounds (only if needed)
        if len(all_prey) < 1000:
            logger.info("🏕️ Phase 2: Backup hunting grounds")
            backup_prey = await self._hunt_backup_grounds()
            all_prey.extend(backup_prey)
            logger.info(f"  ✅ Backup hunt: {len(backup_prey)} proxies found")
        
        # Remove duplicate prey
        logger.info("🔍 Removing duplicate prey...")
        unique_prey = self._remove_duplicate_prey(all_prey)
        
        logger.info(f"🏆 Hunt complete: {len(unique_prey)} unique proxies captured")
        return unique_prey
    
    async def _hunt_repositories(self, max_pages, max_memory_mb):
        """Hunt through GitHub repositories for proxy treasures"""
        logger.info("🐕 Starting repository territory hunt")
        
        # Hunting grounds (search queries)
        hunting_grounds = [
            "free proxies updated language:text pushed:>2024-01-01",
            "working proxy list language:text size:>10",
            "fresh socks proxy language:text",
            "daily proxy update language:text",
            "live proxy collection language:text"
        ]
        
        all_repositories = []
        
        # Search all hunting grounds
        for i, ground in enumerate(hunting_grounds):
            logger.info(f"🌲 Hunting ground {i+1}/{len(hunting_grounds)}: {ground.split()[0]} {ground.split()[1]}")
            
            try:
                repositories = await self._search_hunting_ground(ground, max_pages)
                all_repositories.extend(repositories)
                logger.info(f"  📍 Found {len(repositories)} repositories")
                
                await asyncio.sleep(2)  # Rest between hunts
                
            except Exception as e:
                logger.error(f"  ❌ Hunting ground failed: {e}")
                continue
        
        # Score and rank all found repositories
        scored_repositories = await self._score_and_rank_prey(all_repositories)
        
        # Hunt the best repositories
        all_proxies = []
        hunted_count = 0
        
        for hunt_score, repo in scored_repositories[:25]:  # Hunt top 25
            if hunt_score < 25:  # Skip weak scent trails
                break
                
            logger.info(f"🎯 Hunting: {repo['full_name']} (hunt score: {hunt_score})")
            
            repo_proxies = await self._hunt_repository_content(repo, hunt_score)
            all_proxies.extend(repo_proxies)
            hunted_count += 1
            
            logger.info(f"  🏹 Captured {len(repo_proxies)} proxies")
            
            # Memory management
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            if memory_mb > max_memory_mb and hunted_count >= 10:
                logger.info(f"💾 Memory limit reached ({memory_mb:.1f}MB), ending hunt")
                break
            
            await asyncio.sleep(0.5)
        
        logger.info(f"🏆 Repository hunt complete: {hunted_count} territories, {len(all_proxies)} proxies")
        return all_proxies
    
    async def _search_hunting_ground(self, query, max_pages):
        """Search a specific hunting ground for repositories"""
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
                        logger.warning("    ⚠️ Rate limit hit, resting...")
                        break
                    
                    if response.status != 200:
                        continue
                    
                    data = await response.json()
                    items = data.get("items", [])
                    
                    if not items:
                        break
                    
                    # Pre-filter for quality
                    quality_repos = [repo for repo in items if self._is_quality_territory(repo)]
                    repositories.extend(quality_repos)
                    
                    logger.info(f"    📄 Page {page}: {len(quality_repos)}/{len(items)} quality territories")
                
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"    ❌ Search error: {e}")
                continue
        
        return repositories
    
    def _is_quality_territory(self, repo):
        """Pre-filter repositories for basic quality indicators"""
        # Size check
        size_kb = repo.get('size', 0)
        if size_kb < 10 or size_kb > 50000:
            return False
        
        # Recent activity check
        try:
            updated = datetime.fromisoformat(repo['updated_at'].replace('Z', '+00:00'))
            days_ago = (datetime.now(timezone.utc) - updated).days
            if days_ago > 365:  # No activity in a year
                return False
        except:
            return False
        
        # Basic relevance check
        name = repo.get('name', '').lower
        ]
        
        return any(re.match(pattern, filename) for pattern in treasure_patterns)
    
    async def _extract_treasure_from_file(self, file_item, repo_name, hunt_score):
        """Extract proxy treasures from a file"""
        try:
            download_url = file_item.get('download_url')
            if not download_url:
                return []
            
            async with self.session.get(download_url) as response:
                if response.status != 200:
                    return []
                
                content = await response.text()
                
                # Skip oversized files
                if len(content) > 3_000_000:  # 3MB limit
                    return []
                
                proxy_type = self._detect_treasure_type(download_url, file_item['name'])
                return self._parse_treasure_content(content, repo_name, proxy_type, hunt_score)
        
        except Exception as e:
            logger.warning(f"      ❌ File treasure extraction error: {e}")
            return []
    
    def _detect_treasure_type(self, url, filename):
        """Detect what type of proxy treasure this is"""
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
    
    def _parse_treasure_content(self, content, repository, proxy_type, hunt_score):
        """Parse content for proxy treasures using high-performance regex"""
        treasures = []
        lines = content.splitlines()
        
        # Limit processing for performance
        max_lines = min(len(lines), 100_000)
        
        for line in lines[:max_lines]:
            line = line.strip()
            
            # Skip comments and empty lines
            if not line or line.startswith(('#', '//', ';', '!')):
                continue
            
            # Fast regex matching for IP:PORT
            match = self.proxy_pattern.match(line)
            if match:
                ip, port_str = match.groups()
                try:
                    port = int(port_str)
                    if self._is_valid_treasure(ip) and 1 <= port <= 65535:
                        treasures.append(ProxyInfo(
                            ip=ip,
                            port=port,
                            proxy_type=proxy_type,
                            source=f"repository:{repository}",
                            repository=repository,
                            hunt_score=hunt_score
                        ))
                except ValueError:
                    continue
        
        return treasures
    
    def _is_valid_treasure(self, ip):
        """Fast IP validation for treasure"""
        parts = ip.split('.')
        if len(parts) != 4:
            return False
        try:
            return all(0 <= int(part) <= 255 for part in parts)
        except ValueError:
            return False
    
    async def _hunt_backup_grounds(self):
        """Hunt backup territories when primary hunt yields insufficient results"""
        logger.info("🏕️ Hunting backup territories")
        
        all_treasures = []
        tasks = []
        
        # Parallel hunting of backup grounds
        for ground_url in BACKUP_HUNTING_GROUNDS:
            task = self._hunt_single_backup_ground(ground_url)
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, result in enumerate(results):
            if isinstance(result, list):
                all_treasures.extend(result)
                logger.info(f"  ✅ Backup ground {i+1}: {len(result)} treasures")
            else:
                logger.warning(f"  ❌ Backup ground {i+1}: Failed")
        
        return all_treasures
    
    async def _hunt_single_backup_ground(self, ground_url):
        """Hunt a single backup territory"""
        try:
            async with self.session.get(ground_url) as response:
                if response.status != 200:
                    return []
                
                content = await response.text()
                proxy_type = self._detect_treasure_type(ground_url, ground_url.split('/')[-1])
                repo_name = f"{ground_url.split('/')[-3]}/{ground_url.split('/')[-2]}"
                
                return self._parse_treasure_content(content, repo_name, proxy_type, 50.0)
        except:
            return []
    
    def _remove_duplicate_prey(self, proxies):
        """Remove duplicate prey efficiently"""
        seen = set()
        unique_treasures = []
        
        for treasure in proxies:
            key = f"{treasure.ip}:{treasure.port}"
            if key not in seen:
                seen.add(key)
                unique_treasures.append(treasure)
        
        return unique_treasures

class ProxyPackValidator:
    """High-performance proxy pack validation with geolocation"""
    
    def __init__(self, max_concurrent=100, timeout=3.0, geolocation_service=None):
        self.max_concurrent = max_concurrent
        self.timeout = timeout
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.geolocation_service = geolocation_service
        self.test_url = "http://httpbin.org/ip"  # Fast test endpoint
        logger.info(f"🐕 Pack validator with geolocation ready: {max_concurrent} concurrent hunters")
    
    async def validate_pack(self, proxies):
        """Validate proxy pack with high-performance testing and geolocation"""
        if not proxies:
            return []
            
        logger.info(f"🎯 Pack validation: {len(proxies)} proxies")
        
        # Smart chunking for memory efficiency
        chunk_size = min(2000, len(proxies))
        all_results = []
        
        for i in range(0, len(proxies), chunk_size):
            chunk = proxies[i:i + chunk_size]
            chunk_num = i//chunk_size + 1
            total_chunks = (len(proxies)-1)//chunk_size + 1
            
            logger.info(f"  🏹 Pack {chunk_num}/{total_chunks}: {len(chunk)} proxies")
            
            # Parallel validation
            tasks = [self._test_single_proxy(proxy) for proxy in chunk]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Filter valid results
            valid_results = [r for r in results if isinstance(r, ProxyInfo)]
            all_results.extend(valid_results)
            
            working_count = sum(1 for r in valid_results if r.is_working)
            logger.info(f"    ✅ Pack result: {working_count}/{len(chunk)} working ({working_count/len(chunk)*100:.1f}%)")
        
        # Add geolocation to working proxies
        if self.geolocation_service:
            await self._add_geolocation(all_results)
        
        total_working = sum(1 for r in all_results if r.is_working)
        success_rate = total_working/len(proxies)*100 if proxies else 0
        logger.info(f"🏆 Pack validation complete: {total_working}/{len(proxies)} working ({success_rate:.1f}%)")
        
        return all_results
    
    async def _test_single_proxy(self, proxy):
        """Test individual proxy with optimized performance"""
        async with self.semaphore:
            start_time = time.time()
            
            try:
                # Optimized connection settings
                timeout = aiohttp.ClientTimeout(total=self.timeout, connect=1.0)
                connector = aiohttp.TCPConnector(limit=1, ttl_dns_cache=300)
                
                proxy_url = f"http://{proxy.ip}:{proxy.port}"
                
                async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
                    async with session.get(self.test_url, proxy=proxy_url) as response:
                        if response.status == 200:
                            response_time = (time.time() - start_time) * 1000
                            proxy.is_working = True
                            proxy.response_time = round(response_time, 2)
                            proxy.last_checked = datetime.now(timezone.utc).isoformat()
                            return proxy
                            
            except:
                pass
            
            # Mark as failed
            proxy.is_working = False
            proxy.last_checked = datetime.now(timezone.utc).isoformat()
            return proxy
    
    async def _add_geolocation(self, proxies):
        """Add geolocation data to working proxies"""
        working_proxies = [p for p in proxies if p.is_working]
        if not working_proxies:
            return
        
        logger.info(f"🌍 Adding geolocation to {len(working_proxies)} working proxies...")
        
        # Create semaphore for rate limiting geolocation requests
        geo_semaphore = asyncio.Semaphore(5)  # Conservative rate limiting
        
        async def geolocate_proxy(proxy: ProxyInfo) -> ProxyInfo:
            async with geo_semaphore:
                geolocation = await self.geolocation_service.get_geolocation(proxy.ip)
                if geolocation:
                    proxy.geolocation = geolocation
                    proxy.country = geolocation.country
                    proxy.city = geolocation.city
                return proxy
        
        # Create geolocation tasks
        geo_tasks = [
            asyncio.create_task(geolocate_proxy(proxy))
            for proxy in working_proxies
        ]
        
        # Process geolocation results in batches
        batch_size = 50
        for i in range(0, len(geo_tasks), batch_size):
            batch = geo_tasks[i:i + batch_size]
            await asyncio.gather(*batch, return_exceptions=True)
            
            # Log progress
            progress = min(i + batch_size, len(geo_tasks))
            logger.info(f"🗺️ Geolocation progress: {progress}/{len(geo_tasks)}")

async def export_hunt_results(db, output_dir="docs"):
    """Export Proxy Hound hunting results with geolocation"""
    logger.info(f"📤 Exporting hunt results to {output_dir}")
    
    try:
        os.makedirs(output_dir, exist_ok=True)
        
        working_proxies = db.get_working_proxies(limit=10000)
        hunt_stats = db.get_hunt_stats()
        
        logger.info(f"📊 Exporting {len(working_proxies)} working proxies")
        
        # Export main hunting results
        txt_path = Path(output_dir) / "proxy_hound_results.txt"
        async with aiofiles.open(txt_path, 'w') as f:
            await f.write(f"# Proxy Hound Hunt Results - {datetime.now(timezone.utc).isoformat()}\n")
            await f.write(f"# Working proxies: {hunt_stats['working_proxies']}\n")
            await f.write(f"# Hunt success rate: {hunt_stats['success_rate']}%\n")
            await f.write(f"# Geolocated proxies: {hunt_stats['geolocated_proxies']}\n")
            await f.write(f"# Countries found: {hunt_stats['countries_found']}\n")
            await f.write(f"# Cities found: {hunt_stats['cities_found']}\n")
            await f.write("# Hunting method: Advanced repository analysis with pack behavior tracking\n")
            await f.write("# Validation: High-performance parallel testing with geolocation\n")
            await f.write("# Format: IP:PORT (sorted by hunt score and response time)\n\n")
            
            for proxy in working_proxies:
                await f.write(f"{proxy[0]}:{proxy[1]}\n")
        
        # Enhanced JSON export with hunt data and geolocation
        json_data = {
            "metadata": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total_working": len(working_proxies),
                "hunt_stats": hunt_stats,
                "hunting_method": "proxy-hound-advanced-repository-analysis-v2.1",
                "validation_method": "high-performance-parallel-pack-testing-with-geolocation",
                "sorted_by": "hunt_score_and_response_time"
            },
            "proxies": []
        }
        
        # Build enhanced JSON with hunt scores and geolocation
        for p in working_proxies:
            proxy_data = {
                "ip": p[0],
                "port": p[1],
                "type": p[2] if len(p) > 2 else "unknown",
                "source": p[3] if len(p) > 3 else "unknown",
                "repository": p[4] if len(p) > 4 else "unknown",
                "country": p[5] if len(p) > 5 else "unknown",
                "city": p[6] if len(p) > 6 else "unknown",
                "response_time_ms": p[8] if len(p) > 8 else None,
                "hunt_score": p[9] if len(p) > 9 else 0
            }
            json_data["proxies"].append(proxy_data)
        
        json_path = Path(output_dir) / "proxy_hound_results.json"
        async with aiofiles.open(json_path, 'w') as f:
            await f.write(json.dumps(json_data, indent=2))
        
        # Export by type with hunt scores
        by_type_dir = Path(output_dir) / "by_type"
        os.makedirs(by_type_dir, exist_ok=True)
        
        if hunt_stats.get('by_type'):
            for proxy_type in hunt_stats['by_type'].keys():
                type_proxies = [p for p in working_proxies if (len(p) > 2 and p[2] == proxy_type)]
                if type_proxies:
                    type_path = by_type_dir / f"{proxy_type}_hunted.txt"
                    async with aiofiles.open(type_path, 'w') as f:
                        await f.write(f"# {proxy_type.upper()} Proxies - Hunted by Proxy Hound\n")
                        await f.write(f"# Count: {len(type_proxies)}\n")
                        await f.write("# Sorted by hunt score\n\n")
                        for p in type_proxies:
                            await f.write(f"{p[0]}:{p[1]}\n")
        
        # Hunt statistics
        stats_path = Path(output_dir) / "hunt_stats.json"
        async with aiofiles.open(stats_path, 'w') as f:
            await f.write(json.dumps(hunt_stats, indent=2))
        
        # Create Proxy Hound dashboard
        await create_proxy_hound_dashboard(hunt_stats, output_dir)
        
        logger.info(f"✅ Hunt results exported: {len(working_proxies)} proxies")
        return len(working_proxies)
        
    except Exception as e:
        logger.error(f"❌ Export failed: {e}")
        raise

async def create_proxy_hound_dashboard(hunt_stats, output_dir):
    """Create Proxy Hound hunting dashboard with geolocation"""
    
    # Repository section with hunt scores
    repo_section = ""
    if hunt_stats.get('by_repository'):
        repo_section = """
    <div class="hunting-grounds">
        <h2>🏆 Best Hunting Grounds</h2>
        <div class="repo-grid">"""
        
        for repo, data in list(hunt_stats['by_repository'].items())[:10]:
            count = data.get('count', 0)
            hunt_score = data.get('avg_hunt_score', 0)
            response_time = data.get('avg_response_time', 0)
            
            repo_section += f"""
            <div class="repo-card">
                <div class="repo-name">🎯 {repo}</div>
                <div class="repo-stats">
                    <span class="count">{count:,} proxies</span>
                    <span class="hunt-score">Hunt Score: {hunt_score}/100</span>
                    <span class="response-time">{response_time}ms avg</span>
                </div>
            </div>"""
        
        repo_section += """
        </div>
    </div>"""
    
    # Geographic section
    geo_section = ""
    if hunt_stats.get('by_country'):
        geo_section = """
        <div class="geographic-distribution">
            <h2>🌍 Geographic Distribution</h2>
            <div class="geo-stats">
                <div class="geo-stat">
                    <div class="stat-number">""" + str(hunt_stats['geolocated_proxies']) + """</div>
                    <div class="stat-label">Geolocated</div>
                </div>
                <div class="geo-stat">
                    <div class="stat-number">""" + str(hunt_stats['countries_found']) + """</div>
                    <div class="stat-label">Countries</div>
                </div>
                <div class="geo-stat">
                    <div class="stat-number">""" + str(hunt_stats['cities_found']) + """</div>
                    <div class="stat-label">Cities</div>
                </div>
            </div>
            <div class="country-grid">"""
        
        for country, count in list(hunt_stats['by_country'].items())[:8]:
            geo_section += f"""
            <div class="country-card">
                <div class="country-name">{country}</div>
                <div class="country-count">{count} proxies</div>
            </div>"""
        
        geo_section += """
            </div>
        </div>"""
    
    # Type section
    type_section = ""
    if hunt_stats.get('by_type'):
        type_section = """
        <div class="prey-types">
            <h2>🎪 Prey Types Captured</h2>
            <div class="type-grid">"""
        
        # Calculate percentage correctly
        total_proxies = sum(hunt_stats['by_type'].values())
        for proxy_type, count in hunt_stats['by_type'].items():
            percentage = (count / total_proxies * 100) if total_proxies > 0 else 0
            type_section += f"""
            <div class="type-card">
                <div class="stat-number">{count:,}</div>
                <div>{proxy_type.upper()} ({percentage:.1f}%)</div>
            </div>"""
        
        type_section += """
            </div>
        </div>"""
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Proxy Hound Dashboard</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        .header {{
            background: linear-gradient(135deg, #8B4513 0%, #D2B48C 100%);
            color: white;
            padding: 2rem;
            border-radius: 10px;
            text-align: center;
            margin-bottom: 2rem;
            position: relative;
            overflow: hidden;
        }}
        .logo {{
            width: 80px;
            height: 80px;
            margin: 0 auto 1rem;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .logo svg {{
            width: 100%;
            height: 100%;
            fill: white;
        }}
        .hunting-badge {{
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
            border-left: 4px solid #8B4513;
        }}
        .stat-number {{
            font-size: 2rem;
            font-weight: bold;
            color: #8B4513;
        }}
        .hunting-grounds, .prey-types, .geographic-distribution {{
            background: white;
            padding: 2rem;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            margin-bottom: 2rem;
        }}
        .repo-grid, .type-grid, .country-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 1rem;
        }}
        .geo-stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 1rem;
            margin-bottom: 1.5rem;
        }}
        .geo-stat {{
            background: #f8f9fa;
            padding: 1rem;
            border-radius: 8px;
            text-align: center;
            border-left: 4px solid #007bff;
        }}
        .repo-card, .country-card {{
            background: #f8f9fa;
            padding: 1rem;
            border-radius: 6px;
            border-left: 4px solid #8B4513;
        }}
        .repo-name, .country-name {{
            font-weight: bold;
            color: #333;
            margin-bottom: 0.5rem;
            font-size: 0.9rem;
        }}
            display: flex;
            flex-direction: column;
            gap: 0.3rem;
        }}
        .count, .country-count {{
            color: #666;
            font-size: 0.8rem;
        }}
        .hunt-score {{
            background: #e7f3ff;
            color: #0066cc;
            padding: 0.2rem 0.5rem;
            border-radius: 12px;
            font-size: 0.7rem;
            font-weight: 500;
            display: inline-block;
            width: fit-content;
        }}
        .response-time {{
            color: #28a745;
            font-size: 0.7rem;
            font-weight: 500;
        }}
        .type-card {{
            background: #f8f9fa;
            padding: 1rem;
            border-radius: 6px;
            text-align: center;
            border-left: 4px solid #dc3545;
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
            background: #8B4513;
            color: white;
            padding: 12px 24px;
            text-decoration: none;
            border-radius: 6px;
            margin: 5px;
            font-weight: 500;
        }}
        .btn:hover {{
            background: #A0522D;
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
        <div class="logo">
            <svg viewBox="0 0 400 400" xmlns="http://www.w3.org/2000/svg">
                <!-- Proxy Hound Logo -->
                <path d="M80 60 C80 60, 70 40, 85 35 C100 30, 120 45, 115 65 C110 85, 95 95, 80 85 Z" fill="white"/>
                <path d="M180 35 C195 40, 185 60, 185 60 L185 85 C190 95, 175 85, 170 65 C165 45, 175 30, 180 35 Z" fill="white"/>
                <path d="M60 80 C60 60, 80 50, 100 55 C120 50, 140 55, 160 65 C180 75, 190 90, 185 110 C180 130, 170 150, 155 165 C140 180, 125 185, 110 185 C95 185, 80 180, 65 165 C50 150, 45 130, 50 110 C55 90, 60 80, 60 80 Z" fill="white"/>
                <ellipse cx="105" cy="100" rx="8" ry="6" fill="black"/>
                <ellipse cx="107" cy="98" rx="2" ry="2" fill="white"/>
                <ellipse cx="118" cy="155" rx="6" ry="4" fill="black"/>
                <path d="M118 162 C115 170, 110 175, 105 173 M118 162 C121 170, 126 175, 131 173" stroke="black" stroke-width="2" fill="none"/>
            </svg>
        </div>
        <h1>Proxy Hound Dashboard</h1>
        <p>Advanced Repository Hunter - Tracking Quality Proxy Sources</p>
        <div class="hunting-badge">
            🎯 Scent Tracking • 🏹 Pack Validation • 🏆 Learning Algorithm • 🌍 Geolocation
        </div>
    </div>
    
    <div class="stats">
        <div class="stat">
            <div class="stat-number">{hunt_stats['working_proxies']:,}</div>
            <div>Working Proxies</div>
        </div>
        <div class="stat">
            <div class="stat-number">{hunt_stats['total_proxies']:,}</div>
            <div>Total Hunted</div>
        </div>
        <div class="stat">
            <div class="stat-number">{hunt_stats['success_rate']}%</div>
            <div>Hunt Success Rate</div>
        </div>
        <div class="stat">
            <div class="stat-number">{len(hunt_stats.get('by_repository', {}))}</div>
            <div>Territories Hunted</div>
        </div>
    </div>
    
    {geo_section}
    
    {type_section}
    
    {repo_section}
    
    <div class="downloads">
        <h2>📥 Download Hunt Results</h2>
        <p>High-quality proxies hunted using advanced repository analysis with geolocation:</p>
        <a href="proxy_hound_results.txt" class="btn">📄 Main Results</a>
        <a href="proxy_hound_results.json" class="btn">📊 Enhanced JSON</a>
        <a href="by_type/" class="btn">🗂️ By Type</a>
        <a href="hunt_stats.json" class="btn">📈 Hunt Statistics</a>
        <p><em>Updated every 8 hours using Proxy Hound's advanced hunting algorithms with geolocation.</em></p>
    </div>
    
    <div class="footer">
        <p>Last hunt: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}</p>
        <p>🐕 Proxy Hound v2.1 - Advanced repository analysis with pack behavior tracking and geolocation</p>
        <p>🎯 Hunt success improves over time through learning algorithms</p>
    </div>
</body>
</html>"""
    
    html_path = Path(output_dir) / "index.html"
    async with aiofiles.open(html_path, 'w') as f:
        await f.write(html)

async def main():
    """Proxy Hound main hunting expedition"""
    start_time = time.time()
    logger.info("🐕 Proxy Hound v2.1 - Starting hunting expedition")
    
    # Hunting configuration
    github_token = os.getenv("GITHUB_TOKEN")
    max_pages = int(os.getenv("MAX_PAGES", "3"))
    max_concurrent = int(os.getenv("MAX_CONCURRENT", "100"))
    max_memory_mb = int(os.getenv("MAX_MEMORY_MB", "512"))
    
    logger.info(f"🎯 Hunt Configuration:")
    logger.info(f"  - GitHub Token: {'✅ Set' if github_token else '❌ Missing'}")
    logger.info(f"  - Max Pages per territory: {max_pages}")
    logger.info(f"  - Pack Size (concurrent): {max_concurrent}")
    logger.info(f"  - Memory Limit: {max_memory_mb}MB")
    logger.info(f"  - Strategy: Advanced repository hunting with pack behavior analysis and geolocation")
    
    try:
        # Initialize hunting database
        logger.info("🗄️ Initializing hunt tracking database...")
        db = ProxyHoundDatabase()
        
        # Start the hunt
        logger.info("🐕 Starting hunting expedition...")
        async with ProxyHound(github_token) as hound:
            caught_proxies = await hound.start_hunt(max_pages, max_memory_mb)
        
        if not caught_proxies:
            logger.error("❌ No proxies caught during hunt!")
            await export_hunt_results(db)
            return
        
        logger.info(f"✅ Hunt phase complete: {len(caught_proxies)} proxies caught")
        
        # Validate the pack with geolocation
        logger.info("🎯 Starting pack validation with geolocation...")
        validator = ProxyPackValidator(max_concurrent=max_concurrent, geolocation_service=hound.geolocation_service)
        
        # Process in hunting packs
        pack_size = min(10000, len(caught_proxies))
        all_validated = []
        
        for i in range(0, len(caught_proxies), pack_size):
            pack = caught_proxies[i:i + pack_size]
            pack_num = i//pack_size + 1
            total_packs = (len(caught_proxies)-1)//pack_size + 1
            
            logger.info(f"🏹 Validating pack {pack_num}/{total_packs}: {len(pack)} proxies")
            
            validated = await validator.validate_pack(pack)
            all_validated.extend(validated)
            
            # Record hunt results immediately
            db.add_hunt_results(validated)
            
            # Memory monitoring
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            logger.info(f"💾 Memory usage: {memory_mb:.1f} MB")
            
            # Rest between large pack validations
            if len(pack) >= 5000:
                await asyncio.sleep(1)
        
        # Export hunt results
        logger.info("📤 Exporting hunt results...")
        exported_count = await export_hunt_results(db)
        
        # Final hunt statistics
        hunt_stats = db.get_hunt_stats()
        expedition_time = time.time() - start_time
        
        logger.info("=" * 80)
        logger.info("🏆 PROXY HOUND HUNTING EXPEDITION COMPLETE")
        logger.info("=" * 80)
        logger.info(f"⏱️  Expedition time: {expedition_time:.1f} seconds")
        logger.info(f"🎯 Total hunted: {hunt_stats['total_proxies']:,}")
        logger.info(f"✅ Working proxies: {hunt_stats['working_proxies']:,}")
        logger.info(f"🏹 Hunt success rate: {hunt_stats['success_rate']}%")
        logger.info(f"📤 Exported: {exported_count:,}")
        logger.info(f"🏞️ Territories hunted: {len(hunt_stats.get('by_repository', {}))}")
        logger.info(f"🌍 Geolocated proxies: {hunt_stats['geolocated_proxies']:,}")
        logger.info(f"🗺️ Countries found: {hunt_stats['countries_found']}")
        logger.info(f"🏙️ Cities found: {hunt_stats['cities_found']}")
        
        # Performance metrics
        if expedition_time > 0:
            territories_per_minute = len(hunt_stats.get('by_repository', {})) * 60 / expedition_time
            proxies_per_second = len(caught_proxies) / expedition_time
            validation_rate = hunt_stats['total_proxies'] / expedition_time
            
            logger.info("⚡ Hunt Performance:")
            logger.info(f"  - Territory hunting: {territories_per_minute:.1f} repos/min")
            logger.info(f"  - Proxy capture: {proxies_per_second:.1f} proxies/sec")
            logger.info(f"  - Pack validation: {validation_rate:.1f} validations/sec")
        
        # Best hunting grounds
        if hunt_stats.get('by_repository'):
            logger.info("🏆 Best hunting grounds:")
            for repo, data in list(hunt_stats['by_repository'].items())[:5]:
                if isinstance(data, dict):
                    count = data.get('count', 0)
                    hunt_score = data.get('avg_hunt_score', 0)
                    logger.info(f"  - {repo}: {count:,} proxies (hunt score: {hunt_score:.1f})")
                else:
                    logger.info(f"  - {repo}: {data:,} proxies")
        
        # Geographic distribution
        if hunt_stats.get('by_country'):
            logger.info("🌍 Geographic distribution:")
            for country, count in list(hunt_stats['by_country'].items())[:5]:
                logger.info(f"  - {country}: {count:,} proxies")
        
        # Prey type breakdown
        if hunt_stats.get('by_type'):
            logger.info("🎪 Prey types captured:")
            total_proxies = sum(hunt_stats['by_type'].values())
            for proxy_type, count in hunt_stats['by_type'].items():
                percentage = (count / total_proxies * 100) if total_proxies > 0 else 0
                logger.info(f"  - {proxy_type.upper()}: {count:,} ({percentage:.1f}%)")
        
        # GitHub Actions output
        if os.getenv("GITHUB_ACTIONS"):
            try:
                with open(os.getenv("GITHUB_OUTPUT", "/dev/stdout"), "a") as f:
                    f.write(f"working_proxies={hunt_stats['working_proxies']}\n")
                    f.write(f"total_proxies={hunt_stats['total_proxies']}\n")
                    f.write(f"success_rate={hunt_stats['success_rate']}\n")
                    f.write(f"territories_hunted={len(hunt_stats.get('by_repository', {}))}\n")
                    f.write(f"geolocated_proxies={hunt_stats['geolocated_proxies']}\n")
                    f.write(f"countries_found={hunt_stats['countries_found']}\n")
                    f.write(f"cities_found={hunt_stats['cities_found']}\n")
                    f.write(f"expedition_time={expedition_time:.1f}\n")
                    f.write(f"hunting_method=proxy_hound_v2.1\n")
            except Exception as e:
                logger.warning(f"⚠️ GitHub Actions output failed: {e}")
        
        logger.info("🐕 Proxy Hound hunting expedition completed successfully!")
        logger.info("🏆 Advanced repository analysis with pack behavior tracking and geolocation delivered premium results")
        
    except Exception as e:
        logger.error(f"❌ Hunting expedition failed: {e}")
        logger.error("Full traceback:", exc_info=True)
        
        # Emergency export
        try:
            logger.info("🔄 Creating emergency hunt report...")
            db = ProxyHoundDatabase()
            await export_hunt_results(db)
        except:
            pass
        
        raise

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⏹️  Hunt interrupted by user")
    except Exception as e:
        logger.error(f"💥 Critical hunting error: {e}")
        sys.exit(1)
            #!/usr/bin/env python3
"""
Proxy Hound - Advanced Repository Hunter v2.1
1. Hunt GitHub repositories using scent tracking and pack behavior analysis
2. Deep content analysis for proxy treasure detection
3. Learning system that improves hunting success over time
4. High-performance parallel proxy validation
5. Comprehensive geolocation support
"""

import asyncio
import json
import logging
import sqlite3
import time
import gzip
import re
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Set
from dataclasses import dataclass, asdict
import random
import ssl
import hashlib

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

# Verified hunting grounds (direct sources as backup)
BACKUP_HUNTING_GROUNDS = [
    "https://raw.githubusercontent.com/r00tee/Proxy-List/main/Socks4.txt", 
    "https://raw.githubusercontent.com/r00tee/Proxy-List/main/Socks5.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/http.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/https.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/socks4.txt",
    "https://raw.githubusercontent.com/vmheaven/VMHeaven-Free-Proxy-Updated/refs/heads/main/socks5.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt"
]

@dataclass
class GeolocationInfo:
    """Comprehensive geolocation information."""
    country: Optional[str] = None
    country_code: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    timezone: Optional[str] = None
    isp: Optional[str] = None
    organization: Optional[str] = None
    as_number: Optional[str] = None
    threat_level: Optional[str] = None

@dataclass
class ProxyInfo:
    """Enhanced proxy information with geolocation."""
    ip: str
    port: int
    proxy_type: str
    source: str
    repository: Optional[str] = None
    hunt_score: float = 0.0
    country: Optional[str] = None
    city: Optional[str] = None
    last_checked: Optional[str] = None
    is_working: bool = False
    response_time: Optional[float] = None
    first_seen: Optional[str] = None
    geolocation: Optional[GeolocationInfo] = None
    
    @property
    def location_string(self) -> str:
        """Get human-readable location string."""
        if self.geolocation:
            parts = []
            if self.geolocation.city:
                parts.append(self.geolocation.city)
            if self.geolocation.region:
                parts.append(self.geolocation.region)
            if self.geolocation.country:
                parts.append(self.geolocation.country)
            return ", ".join(parts) if parts else "Unknown"
        elif self.city and self.country:
            return f"{self.city}, {self.country}"
        elif self.country:
            return self.country
        return "Unknown"

class GeolocationService:
    """Geolocation service with multiple providers and caching."""
    
    def __init__(self, cache_size: int = 10000):
        self.cache: Dict[str, GeolocationInfo] = {}
        self.cache_size = cache_size
        self.session_timeout = aiohttp.ClientTimeout(total=10)
        
        # Multiple geolocation providers (free tier)
        self.providers = [
            {
                'name': 'ip-api',
                'url': 'http://ip-api.com/json/{ip}?fields=status,message,country,countryCode,region,regionName,city,lat,lon,timezone,isp,org,as,mobile,proxy,hosting',
                'rate_limit': 45,  # requests per minute
                'last_request': 0
            },
            {
                'name': 'ipapi.co',
                'url': 'https://ipapi.co/{ip}/json/',
                'rate_limit': 30,  # requests per minute for free tier
                'last_request': 0
            },
            {
                'name': 'ipwhois.app',
                'url': 'http://ipwho.is/{ip}',
                'rate_limit': 1000,  # requests per hour
                'last_request': 0
            }
        ]
    
    async def get_geolocation(self, ip: str) -> Optional[GeolocationInfo]:
        """Get geolocation for IP with caching and fallback providers."""
        
        # Check cache first
        if ip in self.cache:
            logger.debug(f"🗺️ Cache hit for {ip}")
            return self.cache[ip]
        
        # Try each provider until we get a result
        for provider in self.providers:
            try:
                result = await self._query_provider(provider, ip)
                if result:
                    # Cache the result
                    if len(self.cache) >= self.cache_size:
                        # Simple cache eviction - remove oldest entry
                        self.cache.pop(next(iter(self.cache)))
                    
                    self.cache[ip] = result
                    logger.debug(f"🌍 Geolocation found for {ip}: {result.city}, {result.country}")
                    return result
                    
            except Exception as e:
                logger.debug(f"❌ Provider {provider['name']} failed for {ip}: {e}")
                continue
        
        logger.debug(f"⚠️ No geolocation found for {ip}")
        return None
    
    async def _query_provider(self, provider: Dict, ip: str) -> Optional[GeolocationInfo]:
        """Query a specific geolocation provider."""
        
        # Rate limiting
        current_time = time.time()
        time_since_last = current_time - provider['last_request']
        min_interval = 60.0 / provider['rate_limit']  # Convert to seconds between requests
        
        if time_since_last < min_interval:
            sleep_time = min_interval - time_since_last
            await asyncio.sleep(sleep_time)
        
        provider['last_request'] = time.time()
        
        url = provider['url'].format(ip=ip)
        
        async with aiohttp.ClientSession(timeout=self.session_timeout) as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return self._parse_response(provider['name'], data)
                else:
                    logger.debug(f"❌ {provider['name']} returned status {response.status} for {ip}")
                    return None
    
    def _parse_response(self, provider_name: str, data: Dict) -> Optional[GeolocationInfo]:
        """Parse geolocation response based on provider format."""
        
        try:
            if provider_name == 'ip-api':
                if data.get('status') == 'success':
                    return GeolocationInfo(
                        country=data.get('country'),
                        country_code=data.get('countryCode'),
                        region=data.get('regionName'),
                        city=data.get('city'),
                        latitude=data.get('lat'),
                        longitude=data.get('lon'),
                        timezone=data.get('timezone'),
                        isp=data.get('isp'),
                        organization=data.get('org'),
                        as_number=data.get('as'),
                        threat_level='proxy' if data.get('proxy') else 'clean'
                    )
            
            elif provider_name == 'ipapi.co':
                if 'error' not in data:
                    return GeolocationInfo(
                        country=data.get('country_name'),
                        country_code=data.get('country_code'),
                        region=data.get('region'),
                        city=data.get('city'),
                        latitude=data.get('latitude'),
                        longitude=data.get('longitude'),
                        timezone=data.get('timezone'),
                        isp=data.get('org'),
                        organization=data.get('org')
                    )
            
            elif provider_name == 'ipwhois.app':
                if data.get('success'):
                    return GeolocationInfo(
                        country=data.get('country'),
                        country_code=data.get('country_code'),
                        region=data.get('region'),
                        city=data.get('city'),
                        latitude=data.get('latitude'),
                        longitude=data.get('longitude'),
                        timezone=data.get('timezone', {}).get('id') if isinstance(data.get('timezone'), dict) else None,
                        isp=data.get('connection', {}).get('isp') if isinstance(data.get('connection'), dict) else None,
                        organization=data.get('connection', {}).get('org') if isinstance(data.get('connection'), dict) else None,
                        as_number=data.get('connection', {}).get('asn') if isinstance(data.get('connection'), dict) else None
                    )
            
        except Exception as e:
            logger.debug(f"❌ Error parsing {provider_name} response: {e}")
        
        return None

class HuntTracker:
    """Track hunting success to improve future hunts"""
    
    def __init__(self):
        self.successful_hunts = {}
        self.failed_hunts = {}
        self.pack_reputation = {}  # Owner success rates
        logger.info("🐕 Hunt tracker initialized")
    
    def record_hunt_result(self, repo_name, hunt_score, working_proxies, total_proxies):
        """Record how successful a repository hunt was"""
        success_rate = (working_proxies / total_proxies) if total_proxies > 0 else 0
        
        hunt_data = {
            'hunt_score': hunt_score,
            'success_rate': success_rate,
            'working_proxies': working_proxies,
            'total_proxies': total_proxies,
            'hunted_at': datetime.now(timezone.utc).isoformat()
        }
        
        if success_rate > 0.1:  # Good hunt (>10% success)
            self.successful_hunts[repo_name] = hunt_data
            logger.info(f"🏆 Successful hunt recorded: {repo_name} ({success_rate:.1%})")
        else:  # Poor hunt
            self.failed_hunts[repo_name] = hunt_data
            logger.info(f"❌ Failed hunt recorded: {repo_name}")
        
        # Track pack (owner) reputation
        owner = repo_name.split('/')[0]
        if owner not in self.pack_reputation:
            self.pack_reputation[owner] = []
        self.pack_reputation[owner].append(success_rate)
    
    def get_pack_reputation(self, owner):
        """Get average success rate for a repository owner"""
        if owner in self.pack_reputation and self.pack_reputation[owner]:
            return sum(self.pack_reputation[owner]) / len(self.pack_reputation[owner])
        return 0.0

class ScentAnalyzer:
    """Analyze repository 'scent' for quality indicators"""
    
    def __init__(self):
        # Strong scent indicators (likely to have good proxies)
        self.strong_scent_keywords = [
            'working', 'live', 'fresh', 'tested', 'verified', 'daily', 'updated',
            'active', 'new', 'current', 'valid', 'checked'
        ]
        
        # Weak scent indicators (likely stale)
        self.weak_scent_keywords = [
            'old', 'archive', 'deprecated', 'backup', 'mirror', 'copy', 'dead',
            'inactive', 'outdated', 'legacy'
        ]
        
        # Territory markers (file patterns that indicate good hunting grounds)
        self.territory_markers = [
            r'.*working.*proxy.*\.txt$',
            r'.*live.*\.txt$', 
            r'.*fresh.*\.txt$',
            r'.*valid.*\.txt$',
            r'.*\d{4}-\d{2}-\d{2}.*\.txt$',  # Date in filename
            r'.*proxy.*list.*\.txt$',
            r'.*socks.*\.txt$',
            r'.*http.*\.txt$'
        ]
        
        logger.info("🐕 Scent analyzer initialized with hunting patterns")
    
    def analyze_scent_strength(self, repo):
        """Analyze how 'fresh' the repository scent is"""
        scent_score = 0
        
        name = repo.get('name', '').lower()
        desc = repo.get('description', '').lower()
        text = f"{name} {desc}"
        
        # Strong scent detection
        strong_matches = sum(1 for keyword in self.strong_scent_keywords 
                           if keyword in text)
        scent_score += strong_matches * 15
        
        # Weak scent penalty
        weak_matches = sum(1 for keyword in self.weak_scent_keywords 
                         if keyword in text)
        scent_score -= weak_matches * 10
        
        # Territory freshness (last updated)
        try:
            updated = datetime.fromisoformat(repo['updated_at'].replace('Z', '+00:00'))
            days_ago = (datetime.now(timezone.utc) - updated).days
            
            if days_ago < 7:
                scent_score += 50    # Very fresh scent
            elif days_ago < 30:
                scent_score += 30    # Fresh scent
            elif days_ago < 90:
                scent_score += 15    # Fading scent
            else:
                scent_score -= 20    # Cold trail
        except:
            scent_score -= 15
        
        return max(0, scent_score)

class ProxyHoundDatabase:
    """Database for tracking Proxy Hound hunting results"""
    
    def __init__(self, db_path="proxy_hound.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Initialize hunting database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL") 
                conn.execute("PRAGMA cache_size=10000")
                conn.execute("PRAGMA temp_store=MEMORY")
                
                # Create proxies table with hunt tracking
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS proxies (
                        id INTEGER PRIMARY KEY,
                        ip TEXT NOT NULL,
                        port INTEGER NOT NULL,
                        proxy_type TEXT,
                        source TEXT NOT NULL,
                        repository TEXT,
                        hunt_score REAL DEFAULT 0,
                        country TEXT,
                        city TEXT,
                        last_checked TEXT,
                        is_working BOOLEAN DEFAULT 0,
                        response_time REAL,
                        first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(ip, port)
                    )
                """)
                
                # Create hunt results table
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS hunt_results (
                        id INTEGER PRIMARY KEY,
                        repository TEXT NOT NULL,
                        hunt_score REAL,
                        total_proxies INTEGER,
                        working_proxies INTEGER,
                        success_rate REAL,
                        hunted_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Create indexes
                indexes = [
                    "CREATE INDEX IF NOT EXISTS idx_ip_port ON proxies(ip, port)",
                    "CREATE INDEX IF NOT EXISTS idx_working ON proxies(is_working)",
                    "CREATE INDEX IF NOT EXISTS idx_hunt_score ON proxies(hunt_score)",
                    "CREATE INDEX IF NOT EXISTS idx_repository ON proxies(repository)",
                    "CREATE INDEX IF NOT EXISTS idx_hunt_results_repo ON hunt_results(repository)"
                ]
                
                for index_sql in indexes:
                    conn.execute(index_sql)
                
            logger.info("🐕 Proxy Hound database initialized")
        except Exception as e:
            logger.error(f"❌ Database initialization failed: {e}")
            raise
    
    def add_hunt_results(self, proxies, batch_size=1000):
        """Add hunting results to database"""
        if not proxies:
            return
            
        logger.info(f"🐕 Recording hunt results: {len(proxies)} proxies")
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("BEGIN TRANSACTION")
                
                for i in range(0, len(proxies), batch_size):
                    batch = proxies[i:i + batch_size]
                    
                    data = [
                        (p.ip, p.port, p.proxy_type, p.source, 
                         p.repository, p.hunt_score, p.country, p.city,
                         p.last_checked, p.is_working, p.response_time)
                        for p in batch
                    ]
                    
                    conn.executemany("""
                        INSERT OR REPLACE INTO proxies 
                        (ip, port, proxy_type, source, repository, hunt_score, country, city, last_checked, is_working, response_time)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, data)
                
                conn.execute("COMMIT")
                logger.info("✅ Hunt results recorded successfully")
        except Exception as e:
            logger.error(f"❌ Failed to record hunt results: {e}")
            raise
    
    def get_working_proxies(self, limit=None):
        """Get working proxies ordered by hunt score and response time"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                query = """
                    SELECT ip, port, proxy_type, source, repository, country, city, last_checked, response_time, hunt_score
                    FROM proxies WHERE is_working = 1 
                    ORDER BY hunt_score DESC, response_time ASC
                """
                
                if limit:
                    query += f" LIMIT {limit}"
                
                results = conn.execute(query).fetchall()
                logger.info(f"🐕 Retrieved {len(results)} working proxies")
                return results
        except Exception as e:
            logger.error(f"❌ Failed to get working proxies: {e}")
            return []
    
    def get_hunt_stats(self):
        """Get hunting statistics"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                total = conn.execute("SELECT COUNT(*) FROM proxies").fetchone()[0]
                working = conn.execute("SELECT COUNT(*) FROM proxies WHERE is_working = 1").fetchone()[0]
                
                # Repository stats with hunt scores
                repo_stats = {}
                for row in conn.execute("""
                    SELECT repository, COUNT(*), AVG(hunt_score), AVG(response_time)
                    FROM proxies WHERE is_working = 1 AND repository IS NOT NULL 
                    GROUP BY repository ORDER BY COUNT(*) DESC LIMIT 10
                """):
                    repo_stats[row[0]] = {
                        "count": row[1], 
                        "avg_hunt_score": round(row[2] or 0, 1),
                        "avg_response_time": round(row[3] or 0, 1)
                    }
                
                # Type stats
                type_stats = {}
                for row in conn.execute("SELECT proxy_type, COUNT(*) FROM proxies WHERE is_working = 1 GROUP BY proxy_type"):
                    type_stats[row[0] or 'unknown'] = row[1]
                
                # Country stats
                country_stats = {}
                for row in conn.execute("SELECT country, COUNT(*) FROM proxies WHERE is_working = 1 AND country IS NOT NULL GROUP BY country ORDER BY COUNT(*) DESC LIMIT 10"):
                    country_stats[row[0]] = row[1]
                
                # City stats
                city_stats = {}
                for row in conn.execute("SELECT city, country, COUNT(*) FROM proxies WHERE is_working = 1 AND city IS NOT NULL GROUP BY city, country ORDER BY COUNT(*) DESC LIMIT 10"):
                    city_key = f"{row[0]}, {row[1]}" if row[1] else row[0]
                    city_stats[city_key] = row[2]
                
                # Hunt success by repository
                hunt_success = {}
                for row in conn.execute("""
                    SELECT repository, AVG(success_rate), COUNT(*)
                    FROM hunt_results GROUP BY repository ORDER BY AVG(success_rate) DESC LIMIT 10
                """):
                    hunt_success[row[0]] = {
                        "avg_success_rate": round(row[1] * 100, 1),
                        "hunts": row[2]
                    }
                
                stats = {
                    "total_proxies": total,
                    "working_proxies": working,
                    "success_rate": round((working / total * 100) if total > 0 else 0, 2),
                    "by_type": type_stats,
                    "by_repository": repo_stats,
                    "by_country": country_stats,
                    "by_city": city_stats,
                    "hunt_success": hunt_success,
                    "geolocated_proxies": conn.execute("SELECT COUNT(*) FROM proxies WHERE is_working = 1 AND country IS NOT NULL").fetchone()[0],
                    "countries_found": len(country_stats),
                    "cities_found": len(city_stats)
                }
                
                logger.info(f"🐕 Hunt stats compiled: {working}/{total} working")
                return stats
        except Exception as e:
            logger.error(f"❌ Failed to get hunt stats: {e}")
            return {"total_proxies": 0, "working_proxies": 0, "success_rate": 0, "by_type": {}, "by_repository": {}, "by_country": {}, "by_city": {}, "hunt_success": {}, "geolocated_proxies": 0, "countries_found": 0, "cities_found": 0}

class ProxyHound:
    """
    Proxy Hound - Advanced Repository Hunter with Geolocation
    
    Multi-factor repository analysis:
    - Scent tracking (recency, activity patterns)
    - Pack behavior analysis (forks, community activity) 
    - Territory mapping (content analysis, file patterns)
    - Hunt success learning (performance feedback)
    - Comprehensive geolocation support
    """
    
    def __init__(self, github_token=None):
        self.github_token = github_token
        self.session = None
        self.hunt_tracker = HuntTracker()
        self.scent_analyzer = ScentAnalyzer()
        self.geolocation_service = GeolocationService()
        self.proxy_pattern = re.compile(r'^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d{1,5})$')
        logger.info("🐕 Proxy Hound with Geolocation initialized - ready to hunt")
    
    async def __aenter__(self):
        headers = {"User-Agent": "ProxyHound/2.1"}
        if self.github_token:
            headers["Authorization"] = f"Bearer {self.github_token}"
            logger.info(f"🔑 GitHub token configured: {self.github_token[:10]}...")
        
        timeout = aiohttp.ClientTimeout(total=20, connect=5)
        connector = aiohttp.TCPConnector(limit=100, ttl_dns_cache=300)
        self.session = aiohttp.ClientSession(headers=headers, timeout=timeout, connector=connector)
        logger.info("🌐 Hunting session established")
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
            logger.info("🔌 Hunting session closed")
    
    async def start_hunt(self, max_pages=3, max_memory_mb=512):
        """Start the proxy hunting expedition"""
        logger.info("🐕 Proxy Hound starting hunting expedition")
        
        all_prey = []  # All found proxies
        
        # Phase 1: Repository hunting
        if self.github_token:
            logger.info("🏞️ Phase 1: Repository territory hunting")
            repo_prey = await self._hunt_repositories(max_pages, max_memory_mb)
            all_prey.extend(repo_prey)
            logger.info(f"  ✅ Repository hunt: {len(repo_prey)} proxies found")
        else:
            logger.warning("⚠️ No GitHub token - skipping repository hunting")
        
        # Phase 2: Backup hunting grounds (only if needed)
        if len(all_prey) < 1000:
            logger.info("🏕️ Phase 2: Backup hunting grounds")
            backup_prey = await self._hunt_backup_grounds()
            all_prey.extend(backup_prey)
            logger.info(f"  ✅ Backup hunt: {len(backup_prey)} proxies found")
        
        # Remove duplicate prey
        logger.info("🔍 Removing duplicate prey...")
        unique_prey = self._remove_duplicate_prey(all_prey)
        
        logger.info(f"🏆 Hunt complete: {len(unique_prey)} unique proxies captured")
        return unique_prey
    
    async def _hunt_repositories(self, max_pages, max_memory_mb):
        """Hunt through GitHub repositories for proxy treasures"""
        logger.info("🐕 Starting repository territory hunt")
        
        # Hunting grounds (search queries)
        hunting_grounds = [
            "free proxies updated language:text pushed:>2024-01-01",
            "working proxy list language:text size:>10",
            "fresh socks proxy language:text",
            "daily proxy update language:text",
            "live proxy collection language:text"
        ]
        
        all_repositories = []
        
        # Search all hunting grounds
        for i, ground in enumerate(hunting_grounds):
            logger.info(f"🌲 Hunting ground {i+1}/{len(hunting_grounds)}: {ground.split()[0]} {ground.split()[1]}")
            
            try:
                repositories = await self._search_hunting_ground(ground, max_pages)
                all_repositories.extend(repositories)
                logger.info(f"  📍 Found {len(repositories)} repositories")
                
                await asyncio.sleep(2)  # Rest between hunts
                
            except Exception as e:
                logger.error(f"  ❌ Hunting ground failed: {e}")
                continue
        
        # Score and rank all found repositories
        scored_repositories = await self._score_and_rank_prey(all_repositories)
        
        # Hunt the best repositories
        all_proxies = []
        hunted_count = 0
        
        for hunt_score, repo in scored_repositories[:25]:  # Hunt top 25
            if hunt_score < 25:  # Skip weak scent trails
                break
                
            logger.info(f"🎯 Hunting: {repo['full_name']} (hunt score: {hunt_score})")
            
            repo_proxies = await self._hunt_repository_content(repo, hunt_score)
            all_proxies.extend(repo_proxies)
            hunted_count += 1
            
            logger.info(f"  🏹 Captured {len(repo_proxies)} proxies")
            
            # Memory management
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            if memory_mb > max_memory_mb and hunted_count >= 10:
                logger.info(f"💾 Memory limit reached ({memory_mb:.1f}MB), ending hunt")
                break
            
            await asyncio.sleep(0.5)
        
        logger.info(f"🏆 Repository hunt complete: {hunted_count} territories, {len(all_proxies)} proxies")
        return all_proxies
    
    async def _search_hunting_ground(self, query, max_pages):
        """Search a specific hunting ground for repositories"""
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
                        logger.warning("    ⚠️ Rate limit hit, resting...")
                        break
                    
                    if response.status != 200:
                        continue
                    
                    data = await response.json()
                    items = data.get("items", [])
                    
                    if not items:
                        break
                    
                    # Pre-filter for quality
                    quality_repos = [repo for repo in items if self._is_quality_territory(repo)]
                    repositories.extend(quality_repos)
                    
                    logger.info(f"    📄 Page {page}: {len(quality_repos)}/{len(items)} quality territories")
                
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"    ❌ Search error: {e}")
                continue
        
        return repositories
    
    def _is_quality_territory(self, repo):
        """Pre-filter repositories for basic quality indicators"""
        # Size check
        size_kb = repo.get('size', 0)
        if size_kb < 10 or size_kb > 50000:
            return False
        
        # Recent activity check
        try:
            updated = datetime.fromisoformat(repo['updated_at'].replace('Z', '+00:00'))
            days_ago = (datetime.now(timezone.utc) - updated).days
            if days_ago > 365:  # No activity in a year
                return False
        except:
            return False
        
        # Basic relevance check
        name = repo.get('name', '').lower
