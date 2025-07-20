import requests
import json
from bs4 import BeautifulSoup

def github_code_search(keyword="proxies.txt", ext="txt", pages=3):
    headers = {
        "Accept": "application/vnd.github.v3.text-match+json",
        "User-Agent": "proxy-intel-tracker"
    }
    proxies_found = set()

    for page in range(1, pages + 1):
        url = f"https://api.github.com/search/code?q={keyword}+in:file+extension:{ext}&page={page}"
        resp = requests.get(url, headers=headers)
        if resp.status_code != 200:
            print(f"GitHub search failed: {resp.status_code}")
            break

        results = resp.json().get("items", [])
        for item in results:
            raw_url = item["html_url"].replace("github.com", "raw.githubusercontent.com").replace("/blob", "")
            print(f"Fetching: {raw_url}")
            try:
                data = requests.get(raw_url, timeout=10).text
                for line in data.splitlines():
                    if ":" in line and "." in line:
                        proxies_found.add(line.strip())
            except Exception as e:
                print(f"Error fetching {raw_url}: {e}")

    with open("proxies_github.txt", "w") as f:
        for proxy in sorted(proxies_found):
            f.write(f"{proxy}\n")
