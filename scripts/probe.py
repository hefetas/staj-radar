#!/usr/bin/env python3
"""Tanılama: verilen adresleri GitHub Actions ortamından çekip yapısını özetler (kaynak eklerken kullanılır)."""
import re
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import radar  # noqa: E402


def main():
    urls = [u for u in sys.argv[1].split() if u.strip()]
    pat = re.compile(sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else r"staj|intern|ilan|position|pozisyon", re.I)
    ctx = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] else 0
    for u in urls:
        print("=" * 100)
        print("URL:", u)
        try:
            html = radar.http_get(u, retries=1)
        except Exception as e:  # noqa: BLE001
            print("HATA:", str(e)[:300])
            continue
        print("bayt:", len(html), "| title:", (re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I) or [None, ""])[1].strip()[:120])
        for mark in ("__NUXT__", "__NEXT_DATA__", "application/ld+json", "window.__INITIAL", "cf-challenge", "captcha", "Just a moment"):
            if mark in html:
                print("  işaret:", mark, "@", html.index(mark))
        anchors = re.findall(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.S | re.I)
        print("bağlantı sayısı:", len(anchors))
        if not anchors or u.endswith("robots.txt"):
            print(html[:3500])
        shown = 0
        seen = set()
        for href, inner in anchors:
            text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", inner)).strip()
            if (pat.search(href) or pat.search(text)) and href not in seen:
                seen.add(href)
                print("  -", href[:150], "|", text[:110])
                shown += 1
                if shown >= 45:
                    break
        if ctx:
            m = pat.search(html)
            n = 0
            for m in pat.finditer(html):
                print("  ~~", html[max(0, m.start() - ctx): m.end() + ctx].replace("\n", " ")[: 2 * ctx + 80])
                n += 1
                if n >= 6:
                    break


if __name__ == "__main__":
    main()
