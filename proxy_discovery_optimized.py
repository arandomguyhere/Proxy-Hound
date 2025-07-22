#!/usr/bin/env python3
"""
Enterprise Proxy Hunter System v2.1
Security-focused, scalable proxy discovery and management system
Now with comprehensive geolocation support
"""

import asyncio
import aiohttp
import logging
import json
import csv
import time
import random
import ssl
import socket
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Set
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from urllib.parse import urlparse
import concurrent.futures
from contextlib import asynccontextmanager
import hashlib
import base64

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('proxy_hunter.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

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
    threat_level: Optional[str] = None  # For security assessment

@dataclass
class ProxyInfo:
    """Enhanced proxy information with security metadata."""
    host: str
    port: int
    protocol: str
    country: Optional[str] = None
    city: Optional[str] = None
    anonymity: Optional[str] = None
    response_time: Optional[float] = None
    last_tested: Optional[datetime] = None
    success_rate: float = 0.0
    is_working: bool = False
    ssl_support: bool = False
    auth_required: bool = False
    geolocation: Optional[GeolocationInfo] = None
    
    @property
    def url(self) -> str:
        """Generate proxy URL."""
        return f"{self.protocol}://{self.host}:{self.port}"
    
    @property
    def fingerprint(self) -> str:
        """Generate unique proxy fingerprint."""
        data = f"{self.host}:{self.port}:{self.protocol}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]
    
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
                'rate_limit': 10000,  # requests per month
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
                        timezone=data.get('timezone', {}).get('id'),
                        isp=data.get('connection', {}).get('isp'),
                        organization=data.get('connection', {}).get('org'),
                        as_number=data.get('connection', {}).get('asn')
                    )
            
        except Exception as e:
            logger.debug(f"❌ Error parsing {provider_name} response: {e}")
        
        return None

@dataclass
class HuntStatistics:
    """Comprehensive hunting statistics with geolocation metrics."""
    total_sources: int = 0
    total_discovered: int = 0
    total_tested: int = 0
    working_proxies: int = 0
    failed_proxies: int = 0
    timeout_proxies: int = 0
    success_percentage: float = 0.0
    average_response_time: float = 0.0
    hunt_duration: float = 0.0
    timestamp: str = ""
    geolocated_proxies: int = 0
    countries_found: int = 0
    cities_found: int = 0
    
    def calculate_metrics(self) -> None:
        """Calculate derived metrics with proper error handling."""
        try:
            if self.total_tested > 0:
                self.success_percentage = (self.working_proxies / self.total_tested) * 100
            else:
                self.success_percentage = 0.0
                
            self.timestamp = datetime.now(timezone.utc).isoformat()
            logger.info(f"📊 Metrics calculated: {self.working_proxies}/{self.total_tested} success rate: {self.success_percentage:.2f}%")
        except Exception as e:
            logger.error(f"💥 Error calculating metrics: {e}")
            self.success_percentage = 0.0

class ProxyValidator:
    """Advanced proxy validation with anti-detection capabilities."""
    
    def __init__(self, timeout: int = 10, max_concurrent: int = 100):
        self.timeout = timeout
        self.max_concurrent = max_concurrent
        self.test_urls = [
            "https://httpbin.org/ip",
            "https://api.ipify.org?format=json",
            "https://icanhazip.com"
        ]
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ]
    
    async def validate_proxy(self, proxy: ProxyInfo, session: aiohttp.ClientSession) -> ProxyInfo:
        """Validate individual proxy with comprehensive testing."""
        try:
            start_time = time.time()
            
            # Create proxy connector with SSL verification
            connector = aiohttp.TCPConnector(
                ssl=ssl.create_default_context(),
                limit=10,
                ttl_dns_cache=300,
                use_dns_cache=True
            )
            
            # Configure proxy settings
            proxy_url = proxy.url
            headers = {
                'User-Agent': random.choice(self.user_agents),
                'Accept': 'application/json,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            }
            
            # Test proxy connectivity
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            test_url = random.choice(self.test_urls)
            
            async with aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers=headers
            ) as test_session:
                async with test_session.get(
                    test_url,
                    proxy=proxy_url,
                    ssl=False  # Allow SSL flexibility for testing
                ) as response:
                    if response.status == 200:
                        response_time = time.time() - start_time
                        proxy.response_time = response_time
                        proxy.is_working = True
                        proxy.last_tested = datetime.now(timezone.utc)
                        proxy.success_rate = 100.0
                        
                        # Test SSL support
                        try:
                            ssl_test_url = test_url.replace('http://', 'https://')
                            async with test_session.get(ssl_test_url, proxy=proxy_url) as ssl_response:
                                proxy.ssl_support = ssl_response.status == 200
                        except:
                            proxy.ssl_support = False
                        
                        logger.info(f"✅ Proxy validated: {proxy.host}:{proxy.port} ({response_time:.2f}s)")
                    else:
                        proxy.is_working = False
                        logger.debug(f"❌ Proxy failed: {proxy.host}:{proxy.port} (HTTP {response.status})")
                        
        except asyncio.TimeoutError:
            proxy.is_working = False
            logger.debug(f"⏰ Proxy timeout: {proxy.host}:{proxy.port}")
        except Exception as e:
            proxy.is_working = False
            logger.debug(f"💥 Proxy error: {proxy.host}:{proxy.port} - {e}")
        
        return proxy

class ProxySource:
    """Abstract base for proxy sources."""
    
    async def fetch_proxies(self) -> List[ProxyInfo]:
        """Fetch proxies from source."""
        raise NotImplementedError

class FreeProxySource(ProxySource):
    """Free proxy list source with rate limiting."""
    
    def __init__(self):
        self.sources = [
            "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
            "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
            "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt"
        ]
        self.session_timeout = aiohttp.ClientTimeout(total=30)
    
    async def fetch_proxies(self) -> List[ProxyInfo]:
        """Fetch proxies from free sources with proper error handling."""
        all_proxies = []
        
        async with aiohttp.ClientSession(timeout=self.session_timeout) as session:
            for source_url in self.sources:
                try:
                    logger.info(f"🔍 Fetching from source: {source_url}")
                    
                    async with session.get(source_url) as response:
                        if response.status == 200:
                            content = await response.text()
                            proxies = self._parse_proxy_list(content)
                            all_proxies.extend(proxies)
                            logger.info(f"📥 Fetched {len(proxies)} proxies from {source_url}")
                        else:
                            logger.warning(f"⚠️ Failed to fetch from {source_url}: HTTP {response.status}")
                            
                except Exception as e:
                    logger.error(f"💥 Error fetching from {source_url}: {e}")
                
                # Rate limiting between requests
                await asyncio.sleep(random.uniform(1, 3))
        
        # Remove duplicates
        unique_proxies = self._deduplicate_proxies(all_proxies)
        logger.info(f"🧹 Deduplicated: {len(unique_proxies)} unique proxies from {len(all_proxies)} total")
        
        return unique_proxies
    
    def _parse_proxy_list(self, content: str) -> List[ProxyInfo]:
        """Parse proxy list content."""
        proxies = []
        
        for line in content.strip().split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
                
            try:
                if ':' in line:
                    host, port = line.split(':', 1)
                    port = int(port)
                    
                    proxy = ProxyInfo(
                        host=host.strip(),
                        port=port,
                        protocol='http'  # Assume HTTP for free sources
                    )
                    proxies.append(proxy)
                    
            except (ValueError, IndexError) as e:
                logger.debug(f"🚫 Invalid proxy format: {line} - {e}")
                continue
        
        return proxies
    
    def _deduplicate_proxies(self, proxies: List[ProxyInfo]) -> List[ProxyInfo]:
        """Remove duplicate proxies based on host:port."""
        seen = set()
        unique_proxies = []
        
        for proxy in proxies:
            key = f"{proxy.host}:{proxy.port}"
            if key not in seen:
                seen.add(key)
                unique_proxies.append(proxy)
        
        return unique_proxies

class ProxyHunter:
    """Main proxy hunting orchestrator with enterprise features."""
    
    def __init__(self, max_concurrent: int = 100, timeout: int = 10):
        self.max_concurrent = max_concurrent
        self.timeout = timeout
        self.validator = ProxyValidator(timeout=timeout, max_concurrent=max_concurrent)
        self.geolocation_service = GeolocationService()
        self.sources: List[ProxySource] = [FreeProxySource()]
        self.statistics = HuntStatistics()
        self.working_proxies: List[ProxyInfo] = []
        self.all_proxies: List[ProxyInfo] = []
        
        logger.info("🐕 Proxy Hunter with Geolocation initialized")
    
    async def hunt_proxies(self) -> HuntStatistics:
        """Main hunting orchestration with comprehensive error handling."""
        hunt_start_time = time.time()
        
        try:
            logger.info("🎯 Starting proxy hunt...")
            
            # Phase 1: Discover proxies from all sources
            await self._discover_proxies()
            
            # Phase 2: Validate discovered proxies
            await self._validate_proxies()
            
            # Phase 3: Geolocate working proxies
            await self._geolocate_proxies()
            
            # Phase 4: Calculate final statistics
            self._finalize_statistics(hunt_start_time)
            
            logger.info(f"🏁 Hunt completed: {self.statistics.working_proxies}/{self.statistics.total_tested} proxies working")
            logger.info(f"🌍 Geolocation: {self.statistics.geolocated_proxies} proxies, {self.statistics.countries_found} countries, {self.statistics.cities_found} cities")
            
        except Exception as e:
            logger.error(f"💥 Critical hunting error: {e}")
            # Ensure statistics are calculated even on error
            self.statistics.calculate_metrics()
        
        return self.statistics
    
    async def _discover_proxies(self) -> None:
        """Discover proxies from all configured sources."""
        logger.info("🔍 Phase 1: Discovering proxies...")
        
        discovery_tasks = []
        for source in self.sources:
            task = asyncio.create_task(source.fetch_proxies())
            discovery_tasks.append(task)
        
        # Wait for all discovery tasks
        results = await asyncio.gather(*discovery_tasks, return_exceptions=True)
        
        # Process results
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"💥 Source {i} failed: {result}")
            else:
                self.all_proxies.extend(result)
        
        self.statistics.total_sources = len(self.sources)
        self.statistics.total_discovered = len(self.all_proxies)
        
        logger.info(f"📊 Discovery complete: {self.statistics.total_discovered} proxies from {self.statistics.total_sources} sources")
    
    async def _validate_proxies(self) -> None:
        """Validate all discovered proxies with concurrency control."""
        logger.info("✅ Phase 2: Validating proxies...")
        
        if not self.all_proxies:
            logger.warning("⚠️ No proxies to validate")
            return
        
        # Create semaphore for concurrency control
        semaphore = asyncio.Semaphore(self.max_concurrent)
        
        async def validate_with_semaphore(proxy: ProxyInfo) -> ProxyInfo:
            async with semaphore:
                async with aiohttp.ClientSession() as session:
                    return await self.validator.validate_proxy(proxy, session)
        
        # Create validation tasks
        validation_tasks = [
            asyncio.create_task(validate_with_semaphore(proxy))
            for proxy in self.all_proxies
        ]
        
        # Process validation results with progress tracking
        self.statistics.total_tested = len(validation_tasks)
        
        logger.info(f"🧪 Testing {self.statistics.total_tested} proxies with max {self.max_concurrent} concurrent")
        
        # Process results in batches for memory efficiency
        batch_size = 1000
        for i in range(0, len(validation_tasks), batch_size):
            batch = validation_tasks[i:i + batch_size]
            results = await asyncio.gather(*batch, return_exceptions=True)
            
            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"💥 Validation error: {result}")
                    self.statistics.failed_proxies += 1
                elif result.is_working:
                    self.working_proxies.append(result)
                    self.statistics.working_proxies += 1
                else:
                    self.statistics.failed_proxies += 1
            
            # Log progress
            progress = min(i + batch_size, len(validation_tasks))
            logger.info(f"📈 Progress: {progress}/{self.statistics.total_tested} tested")
    
    async def _geolocate_proxies(self) -> None:
        """Add geolocation information to working proxies."""
        logger.info("🌍 Phase 3: Geolocating working proxies...")
        
        if not self.working_proxies:
            logger.warning("⚠️ No working proxies to geolocate")
            return
        
        # Create semaphore for rate limiting geolocation requests
        geo_semaphore = asyncio.Semaphore(10)  # Conservative rate limiting
        
        async def geolocate_proxy(proxy: ProxyInfo) -> ProxyInfo:
            async with geo_semaphore:
                geolocation = await self.geolocation_service.get_geolocation(proxy.host)
                if geolocation:
                    proxy.geolocation = geolocation
                    proxy.country = geolocation.country
                    proxy.city = geolocation.city
                return proxy
        
        # Create geolocation tasks
        geo_tasks = [
            asyncio.create_task(geolocate_proxy(proxy))
            for proxy in self.working_proxies
        ]
        
        logger.info(f"🗺️ Geolocating {len(geo_tasks)} working proxies...")
        
        # Process geolocation results
        results = await asyncio.gather(*geo_tasks, return_exceptions=True)
        
        # Update working proxies with geolocation data
        geolocated_count = 0
        countries = set()
        cities = set()
        
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"💥 Geolocation error: {result}")
            elif result.geolocation:
                geolocated_count += 1
                if result.geolocation.country:
                    countries.add(result.geolocation.country)
                if result.geolocation.city:
                    cities.add(result.geolocation.city)
        
        self.statistics.geolocated_proxies = geolocated_count
        self.statistics.countries_found = len(countries)
        self.statistics.cities_found = len(cities)
        
        logger.info(f"🌍 Geolocation complete: {geolocated_count}/{len(self.working_proxies)} proxies geolocated")
        logger.info(f"📍 Found proxies in {len(countries)} countries and {len(cities)} cities")
    
    def _finalize_statistics(self, hunt_start_time: float) -> None:
        """Calculate final hunting statistics."""
        self.statistics.hunt_duration = time.time() - hunt_start_time
        
        # Calculate average response time
        working_times = [p.response_time for p in self.working_proxies if p.response_time]
        if working_times:
            self.statistics.average_response_time = sum(working_times) / len(working_times)
        
        # Calculate final metrics
        self.statistics.calculate_metrics()
        
        logger.info(f"🐕 Hunt stats compiled: {self.statistics.working_proxies}/{self.statistics.total_tested} working")
    
    async def export_results(self) -> bool:
        """Export hunt results to multiple formats."""
        try:
            logger.info("📤 Exporting hunt results with geolocation data...")
            
            # Ensure docs directory exists
            docs_dir = Path("docs")
            docs_dir.mkdir(exist_ok=True)
            
            # Export to JSON
            await self._export_json(docs_dir)
            
            # Export to CSV
            await self._export_csv(docs_dir)
            
            # Export to Markdown
            await self._export_markdown(docs_dir)
            
            # Export GitHub Pages index
            await self._export_github_pages(docs_dir)
            
            logger.info(f"✅ Hunt results exported: {self.statistics.working_proxies} proxies with geolocation")
            return True
            
        except Exception as e:
            logger.error(f"💥 Critical export error: {e}")
            return False
    
    async def _export_json(self, docs_dir: Path) -> None:
        """Export results to JSON format."""
        # Custom serializer for datetime and dataclass objects
        def json_serializer(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            elif hasattr(obj, '__dict__'):
                return obj.__dict__
            return str(obj)
        
        # Export statistics
        stats_data = asdict(self.statistics)
        with open(docs_dir / "proxy_statistics.json", "w") as f:
            json.dump(stats_data, f, indent=2, default=json_serializer)
        
        # Export working proxies with geolocation
        proxies_data = []
        for proxy in self.working_proxies:
            proxy_dict = asdict(proxy)
            if proxy.geolocation:
                proxy_dict['geolocation'] = asdict(proxy.geolocation)
            proxies_data.append(proxy_dict)
        
        with open(docs_dir / "working_proxies.json", "w") as f:
            json.dump(proxies_data, f, indent=2, default=json_serializer)
        
        logger.info(f"📊 Exported {len(self.working_proxies)} proxies to JSON with geolocation")
    
    async def _export_csv(self, docs_dir: Path) -> None:
        """Export working proxies to CSV format with geolocation."""
        if not self.working_proxies:
            return
            
        with open(docs_dir / "working_proxies.csv", "w", newline="") as f:
            writer = csv.writer(f)
            
            # Write header with geolocation fields
            writer.writerow([
                "host", "port", "protocol", "country", "city", "region",
                "anonymity", "response_time", "last_tested", "success_rate", 
                "ssl_support", "isp", "organization", "latitude", "longitude"
            ])
            
            # Write proxy data
            for proxy in self.working_proxies:
                geo = proxy.geolocation
                writer.writerow([
                    proxy.host, proxy.port, proxy.protocol, 
                    proxy.country or (geo.country if geo else ""),
                    proxy.city or (geo.city if geo else ""),
                    geo.region if geo else "",
                    proxy.anonymity, proxy.response_time, proxy.last_tested,
                    proxy.success_rate, proxy.ssl_support,
                    geo.isp if geo else "",
                    geo.organization if geo else "",
                    geo.latitude if geo else "",
                    geo.longitude if geo else ""
                ])
        
        logger.info(f"📄 Exported {len(self.working_proxies)} proxies to CSV with geolocation")
    
    async def _export_markdown(self, docs_dir: Path) -> None:
        """Export comprehensive markdown report with geolocation analysis."""
        percentage = self.statistics.success_percentage
        
        report = f"""# Proxy Hunt Report with Geolocation

Generated: {self.statistics.timestamp}

## 📊 Hunt Statistics

| Metric | Value |
|--------|-------|
| **Total Sources** | {self.statistics.total_sources:,} |
| **Total Discovered** | {self.statistics.total_discovered:,} |
| **Total Tested** | {self.statistics.total_tested:,} |
| **Working Proxies** | {self.statistics.working_proxies:,} |
| **Failed Proxies** | {self.statistics.failed_proxies:,} |
| **Success Rate** | {percentage:.2f}% |
| **Average Response Time** | {self.statistics.average_response_time:.2f}s |
| **Hunt Duration** | {self.statistics.hunt_duration:.2f}s |
| **Geolocated Proxies** | {self.statistics.geolocated_proxies:,} |
| **Countries Found** | {self.statistics.countries_found:,} |
| **Cities Found** | {self.statistics.cities_found:,} |

## 🌍 Geographic Distribution

### By Country
"""
        
        # Add country analysis
        countries = {}
        for proxy in self.working_proxies:
            country = proxy.country or "Unknown"
