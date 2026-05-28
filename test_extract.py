import httpx
import re

url = "https://www.billboard.com/charts/artist-100/"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
}
r = httpx.get(url, headers=headers)
html = r.text

pattern = re.compile(r'href="https://www\.billboard\.com/artist/(?P<slug>[^/"]+)/?"[^>]*>\s*(?P<name>[^\n\r\t<>]+)\s*</a>', re.IGNORECASE | re.DOTALL)
matches = pattern.findall(html)
print("Found matches count:", len(matches))
# Deduplicate preserving order
seen = set()
deduped_artists = []
for m in matches:
    name = html.unescape(m[1]).strip()
    if name and name.lower() not in seen:
        seen.add(name.lower())
        deduped_artists.append(name)

print("Deduplicated artists count:", len(deduped_artists))
for i, name in enumerate(deduped_artists[:100]):
    print(f"{i+1}: {name}")
