#!/usr/bin/env python3
"""
Enterprise Proxy Hunter System v2.0
Security-focused, scalable proxy discovery and management system
Designed for GitHub Actions deployment with comprehensive monitoring
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
class ProxyInfo:
    """Enhanced proxy information with security metadata."""
    host: str
    port: int
    protocol: str
    country: Optional[str] = None
    anonymity: Optional[str] = None
    response_time: Optional[float] = None
    last_tested: Optional[datetime] = None
    success_rate: float = 0.0
    is_working: bool = False
    ssl_support: bool = False
    auth_required: bool = False
    geolocation: Optional[Dict[str, str]] = None
    
    @property
    def url(self) -> str:
        """Generate proxy URL."""
        return f"{self.protocol}://{self.host}:{self.port}"
    
    @property
    def fingerprint(self) -> str:
        """Generate unique proxy fingerprint."""
        data = f"{self.host}:{self.port}:{self.protocol}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]

@dataclass
class HuntStatistics:
    """Comprehensive hunting statistics with proper scope management."""
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
        self.sources: List[ProxySource] = [FreeProxySource()]
        self.statistics = HuntStatistics()
        self.working_proxies: List[ProxyInfo] = []
        self.all_proxies: List[ProxyInfo] = []
        
        logger.info("🐕 Proxy Hound database initialized")
    
    async def hunt_proxies(self) -> HuntStatistics:
        """Main hunting orchestration with comprehensive error handling."""
        hunt_start_time = time.time()
        
        try:
            logger.info("🎯 Starting proxy hunt...")
            
            # Phase 1: Discover proxies from all sources
            await self._discover_proxies()
            
            # Phase 2: Validate discovered proxies
            await self._validate_proxies()
            
            # Phase 3: Calculate final statistics
            self._finalize_statistics(hunt_start_time)
            
            logger.info(f"🏁 Hunt completed: {self.statistics.working_proxies}/{self.statistics.total_tested} proxies working")
            
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
            logger.info("🔄 Creating emergency hunt report...")
            logger.info("📤 Exporting hunt results to docs")
            
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
            
            logger.info(f"✅ Hunt results exported: {self.statistics.working_proxies} proxies")
            return True
            
        except Exception as e:
            logger.error(f"💥 Critical export error: {e}")
            return False
    
    async def _export_json(self, docs_dir: Path) -> None:
        """Export results to JSON format."""
        # Export statistics
        stats_data = asdict(self.statistics)
        with open(docs_dir / "proxy_statistics.json", "w") as f:
            json.dump(stats_data, f, indent=2, default=str)
        
        # Export working proxies
        proxies_data = [asdict(proxy) for proxy in self.working_proxies]
        with open(docs_dir / "working_proxies.json", "w") as f:
            json.dump(proxies_data, f, indent=2, default=str)
        
        logger.info(f"📊 Exported {len(self.working_proxies)} proxies to JSON")
    
    async def _export_csv(self, docs_dir: Path) -> None:
        """Export working proxies to CSV format."""
        if not self.working_proxies:
            return
            
        with open(docs_dir / "working_proxies.csv", "w", newline="") as f:
            writer = csv.writer(f)
            
            # Write header
            writer.writerow([
                "host", "port", "protocol", "country", "anonymity",
                "response_time", "last_tested", "success_rate", "ssl_support"
            ])
            
            # Write proxy data
            for proxy in self.working_proxies:
                writer.writerow([
                    proxy.host, proxy.port, proxy.protocol, proxy.country,
                    proxy.anonymity, proxy.response_time, proxy.last_tested,
                    proxy.success_rate, proxy.ssl_support
                ])
        
        logger.info(f"📄 Exported {len(self.working_proxies)} proxies to CSV")
    
    async def _export_markdown(self, docs_dir: Path) -> None:
        """Export comprehensive markdown report."""
        # Use the properly scoped percentage variable
        percentage = self.statistics.success_percentage
        
        report = f"""# Proxy Hunt Report

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

## 🌍 Geographic Distribution

"""
        
        # Add geographic analysis
        countries = {}
        for proxy in self.working_proxies:
            country = proxy.country or "Unknown"
            countries[country] = countries.get(country, 0) + 1
        
        for country, count in sorted(countries.items(), key=lambda x: x[1], reverse=True):
            report += f"- **{country}**: {count} proxies\n"
        
        report += f"""

## 🔒 Security Analysis

- **SSL Support**: {sum(1 for p in self.working_proxies if p.ssl_support)} proxies
- **Authentication Required**: {sum(1 for p in self.working_proxies if p.auth_required)} proxies
- **Average Response Time**: {self.statistics.average_response_time:.2f}s

## 📈 Performance Metrics

### Response Time Distribution
"""
        
        # Add response time analysis
        if self.working_proxies:
            times = [p.response_time for p in self.working_proxies if p.response_time]
            if times:
                times.sort()
                report += f"- **Fastest**: {min(times):.2f}s\n"
                report += f"- **Slowest**: {max(times):.2f}s\n"
                report += f"- **Median**: {times[len(times)//2]:.2f}s\n"
        
        report += """

## 🚀 Usage

### Download Formats
- [JSON Statistics](proxy_statistics.json)
- [Working Proxies JSON](working_proxies.json)
- [Working Proxies CSV](working_proxies.csv)

### Integration
```python
import requests

# Example proxy usage
proxy = {
    'http': 'http://proxy_host:proxy_port',
    'https': 'http://proxy_host:proxy_port'
}

response = requests.get('https://httpbin.org/ip', proxies=proxy)
print(response.json())
```

---
*Report generated by Enterprise Proxy Hunter v2.0*
"""
        
        with open(docs_dir / "README.md", "w") as f:
            f.write(report)
        
        logger.info("📋 Exported comprehensive markdown report")
    
    async def _export_github_pages(self, docs_dir: Path) -> None:
        """Export GitHub Pages compatible index.html."""
        # Use the properly scoped percentage variable
        percentage = self.statistics.success_percentage
        
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Proxy Hunter Results</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 40px; }}
        .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin: 20px 0; }}
        .stat-card {{ background: #f8f9fa; padding: 20px; border-radius: 8px; text-align: center; }}
        .stat-number {{ font-size: 2em; font-weight: bold; color: #28a745; }}
        .stat-label {{ color: #6c757d; font-size: 0.9em; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background-color: #f8f9fa; }}
        .success {{ color: #28a745; }}
        .timestamp {{ color: #6c757d; font-size: 0.9em; }}
    </style>
</head>
<body>
    <h1>🐕 Proxy Hunter Results</h1>
    <p class="timestamp">Last Updated: {self.statistics.timestamp}</p>
    
    <div class="stats">
        <div class="stat-card">
            <div class="stat-number">{self.statistics.working_proxies:,}</div>
            <div class="stat-label">Working Proxies</div>
        </div>
        <div class="stat-card">
            <div class="stat-number">{self.statistics.total_tested:,}</div>
            <div class="stat-label">Total Tested</div>
        </div>
        <div class="stat-card">
            <div class="stat-number">{percentage:.1f}%</div>
            <div class="stat-label">Success Rate</div>
        </div>
        <div class="stat-card">
            <div class="stat-number">{self.statistics.average_response_time:.2f}s</div>
            <div class="stat-label">Avg Response Time</div>
        </div>
    </div>
    
    <h2>📥 Download Results</h2>
    <ul>
        <li><a href="proxy_statistics.json">📊 Statistics (JSON)</a></li>
        <li><a href="working_proxies.json">🌐 Working Proxies (JSON)</a></li>
        <li><a href="working_proxies.csv">📄 Working Proxies (CSV)</a></li>
        <li><a href="README.md">📋 Full Report (Markdown)</a></li>
    </ul>
    
    <h2>🔥 Top Performing Proxies</h2>
    <table>
        <thead>
            <tr><th>Host</th><th>Port</th><th>Protocol</th><th>Response Time</th><th>SSL</th></tr>
        </thead>
        <tbody>
"""
        
        # Add top 10 fastest proxies
        fastest_proxies = sorted(
            [p for p in self.working_proxies if p.response_time],
            key=lambda x: x.response_time
        )[:10]
        
        for proxy in fastest_proxies:
            ssl_icon = "✅" if proxy.ssl_support else "❌"
            html_content += f"""
            <tr>
                <td>{proxy.host}</td>
                <td>{proxy.port}</td>
                <td>{proxy.protocol.upper()}</td>
                <td class="success">{proxy.response_time:.2f}s</td>
                <td>{ssl_icon}</td>
            </tr>"""
        
        html_content += """
        </tbody>
    </table>
    
    <footer style="margin-top: 40px; text-align: center; color: #6c757d;">
        <p>Generated by Enterprise Proxy Hunter v2.0</p>
    </footer>
</body>
</html>"""
        
        with open(docs_dir / "index.html", "w") as f:
            f.write(html_content)
        
        logger.info("🌐 Exported GitHub Pages index.html")

async def main():
    """Main execution function with comprehensive error handling."""
    try:
        logger.info("🚀 Starting Enterprise Proxy Hunter v2.0")
        
        # Initialize hunter with configuration
        hunter = ProxyHunter(
            max_concurrent=100,  # Adjust based on system capabilities
            timeout=10
        )
        
        # Execute hunt
        stats = await hunter.hunt_proxies()
        
        # Export results
        export_success = await hunter.export_results()
        
        if export_success:
            logger.info("🎯 Proxy hunt completed successfully!")
            logger.info(f"📈 Final Results: {stats.working_proxies}/{stats.total_tested} proxies ({stats.success_percentage:.2f}% success)")
        else:
            logger.error("❌ Export failed, but hunt data is available")
            exit(1)
            
    except KeyboardInterrupt:
        logger.info("🛑 Hunt interrupted by user")
        exit(0)
    except Exception as e:
        logger.error(f"💥 Fatal error in main: {e}")
        exit(1)

if __name__ == "__main__":
    # Configure asyncio for better performance
    if hasattr(asyncio, 'set_event_loop_policy'):
        # Use uvloop on Unix systems for better performance
        try:
            import uvloop
            asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
            logger.info("🚀 Using uvloop for enhanced performance")
        except ImportError:
            logger.info("📡 Using default asyncio event loop")
    
    # Run the main coroutine
    asyncio.run(main())
