import httpx
import re

url = "https://www.billboard.com/charts/artist-100/"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
}

print("Fetching Billboard page...")
r = httpx.get(url, headers=headers)
print("Status:", r.status_code)
html = r.text

print("Length of HTML:", len(html))

# Let's search for some typical artist names case-insensitively.
# We'll search for common names like "Eminem", "Swift", "Drake", "Weeknd", "Grande", "Cyrus"
artists = ["Eminem", "Swift", "Drake", "Weeknd", "Grande", "Cyrus", "Beyonce", "Billie", "Eilish", "Post", "Malone", "Morgan", "Wallen", "Zach", "Bryan"]
found = False

for artist in artists:
    pattern = re.compile(rf"[^<>]*{artist}[^<>]*", re.IGNORECASE)
    matches = list(pattern.finditer(html))
    if matches:
        found = True
        print(f"\n--- Found artist '{artist}' (matched {len(matches)} times) ---")
        for match in matches[:5]:
            start_idx = max(0, match.start() - 150)
            end_idx = min(len(html), match.end() + 150)
            snippet = html[start_idx:end_idx].strip()
            print(f"Context: ... {snippet} ...")

if not found:
    print("No matches found for any common artist name.")
