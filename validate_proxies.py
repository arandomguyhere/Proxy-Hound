import asyncio
import aiohttp
import time
import json
from proxy_db import ProxyDatabase
from ipwhois import IPWhois

async def validate_proxy(db, session, proxy, source):
    ip, port = proxy.split(":")
    proxy_url = f"http://{proxy}"
    start = time.time()
    try:
        async with session.get("http://httpbin.org/ip", proxy=proxy_url, timeout=10) as resp:
            latency = (time.time() - start) * 1000
            if resp.status == 200:
                data = await resp.json()
                origin_ip = data.get("origin")
                whois = IPWhois(ip)
                details = whois.lookup_rdap(depth=1)
                db.upsert_proxy(ip, int(port), source, {
                    'asn': details.get('asn'),
                    'org': details.get('network', {}).get('name'),
                    'country': details.get('asn_country_code'),
                    'region': details.get('network', {}).get('remarks', [{}])[0].get('description', ''),
                    'inferred_type': 'residential' if 'broadband' in str(details).lower() else 'datacenter'
                })
                db.log_health(ip, int(port), True, True, latency)
                print(f"[+] {proxy} is alive ({latency:.2f}ms)")
            else:
                db.log_health(ip, int(port), False, False, None)
    except Exception as e:
        db.log_health(ip, int(port), False, False, None)
        print(f"[-] {proxy} failed: {str(e)}")

async def validate_proxies(proxy_list, source):
    db = ProxyDatabase()
    async with aiohttp.ClientSession() as session:
        tasks = [validate_proxy(db, session, proxy.strip(), source) for proxy in proxy_list if proxy.strip()]
        await asyncio.gather(*tasks)
    db.close()

if __name__ == "__main__":
    with open("proxies_github.txt") as f:
        proxies = f.readlines()
    asyncio.run(validate_proxies(proxies, source="GitHub Crawler"))
