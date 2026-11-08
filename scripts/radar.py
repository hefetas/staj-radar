#!/usr/bin/env python3
"""Staj Radar: ilanları çeker, profile göre puanlar, yenileri bildirir.

Yalnızca standart kütüphane kullanır (pip install gerekmez).
Çıktı: docs/data/jobs.json  (site bu dosyayı okur)
"""
from __future__ import annotations

import argparse
import datetime as dt
import functools
import hashlib
import html as htmllib
import json
import os
import re
import smtplib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.message import EmailMessage
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UA = "InternshipRadar/1.0 (personal job alert tool)"
PAUSE = 0.5  # istekler arası bekleme (sn); testlerde 0 yapılır
FAIL_ALERT_STREAK = 6  # üst üste bu kadar hata olursa bir kez uyar (~18 saat)

TR_MAP = str.maketrans({"ş": "s", "ğ": "g", "ü": "u", "ö": "o", "ç": "c", "ı": "i",
                        "â": "a", "î": "i", "û": "u"})


# ----------------------------------------------------------------- yardımcılar
def fold(s: str | None) -> str:
    """Küçük harfe çevirir ve Türkçe karakterleri ASCII'ye indirger."""
    s = (s or "").replace("İ", "i").replace("I", "ı").lower()
    return s.translate(TR_MAP)


def ws(s: str | None) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(s or "")).strip()


def strip_tags(s: str | None) -> str:
    return ws(re.sub(r"<[^>]+>", " ", s or ""))


def safe_url(url: str) -> str:
    """Hata mesajlarında sorgu parametrelerini (API anahtarı!) saklar."""
    p = urllib.parse.urlparse(url)
    return f"{p.scheme}://{p.netloc}{p.path}"


def http_get(url: str, headers: dict | None = None, timeout: int = 25, retries: int = 2, data: dict | None = None,
             json_body: dict | None = None) -> str:
    h = {"User-Agent": UA, "Accept": "*/*"}
    h.update(headers or {})
    body = None
    if data is not None:  # form POST (bazı duyuru listeleri sayfaya sonradan yükleniyor)
        body = urllib.parse.urlencode(data).encode("utf-8")
        h["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        h["X-Requested-With"] = "XMLHttpRequest"
    if json_body is not None:  # JSON POST (ör. Jooble API)
        body = json.dumps(json_body).encode("utf-8")
        h["Content-Type"] = "application/json"
    last = None
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=body, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                charset = r.headers.get_content_charset() or "utf-8"
                return raw.decode(charset, errors="replace")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"{safe_url(url)}: {type(last).__name__}: {last}")


def canon_url(url: str) -> str:
    p = urllib.parse.urlparse(url.strip())
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query)
         if not k.lower().startswith("utm_") and k.lower() not in ("ref", "source")]
    return urllib.parse.urlunparse((p.scheme, p.netloc, p.path, "", urllib.parse.urlencode(q), ""))


def make_job(source, title, url, company="", location="", country="TR", snippet="",
             posted=None, deadline=None, trusted_intern=False, remote=False) -> dict:
    url = canon_url(url)
    return {
        "id": hashlib.sha1(url.encode()).hexdigest()[:12],
        "source": source,
        "title": ws(title)[:200],
        "company": ws(company)[:120],
        "location": ws(location)[:120],
        "country": country,
        "url": url,
        "snippet": ws(snippet)[:600],
        "posted": posted,
        "deadline": deadline,
        "trusted_intern": trusted_intern,
        "remote": remote,
    }


class SkipSource(Exception):
    """Kaynak bilerek atlandı (anahtar yok, süre dolmadı vb.)."""


class AnchorParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href = None
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href") or ""
            self._buf = []

    def handle_data(self, data):
        if self._href is not None:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, ws(" ".join(self._buf))))
            self._href = None


# -------------------------------------------------------------------- kaynaklar
def fetch_arbeitnow(cfg: dict) -> list[dict]:
    """Almanya/Avrupa (ve UK) için ücretsiz, anahtarsız genel API."""
    out, errors = [], []
    for base in cfg.get("bases", ["https://www.arbeitnow.com/api/job-board-api"]):
        country = "UK" if ".co.uk" in base else "DE"
        try:
            for page in range(1, int(cfg.get("max_pages", 5)) + 1):
                data = json.loads(http_get(f"{base}?page={page}"))
                rows = data.get("data") or []
                if not rows:
                    break
                for r in rows:
                    posted = None
                    try:
                        posted = dt.datetime.fromtimestamp(int(r["created_at"]), dt.timezone.utc).isoformat()
                    except (KeyError, TypeError, ValueError):
                        pass
                    out.append(make_job("Arbeitnow", r.get("title", ""), r.get("url", ""),
                                        r.get("company_name", ""), r.get("location", ""), country,
                                        strip_tags(r.get("description", "")), posted,
                                        remote=bool(r.get("remote"))))
                time.sleep(PAUSE)
        except Exception as e:  # noqa: BLE001
            errors.append(str(e))
    if not out and errors:
        raise RuntimeError("; ".join(errors)[:300])
    return out


YOUTHALL_JOB = re.compile(r"/(?:tr|en)/([^/]+)/([^/]+)_(\d+)/?$")
DATE_TAIL = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})\s+(.+?)\s*$")
TYPE_TAIL = re.compile(r"\s+(Stajyer|MT Programı|Tam Zamanlı|Yarı Zamanlı|Gönüllü|Sözleşmeli|Dönemsel|"
                       r"Proje Bazlı|Serbest Zamanlı|Yeni Mezun|Genç Profesyonel|Profesyonel|Burs)\s*$")


NON_ALNUM = re.compile(r"[^a-z0-9]")


def split_company_title(body: str, slug: str):
    """Kart metni "Şirket Başlık Açıklama…" biçiminde; URL slug'ı başlığın harfleriyle
    eşleşir. Slug'ı metinde bulup şirketi (öncesi) ve başlığı (kendisi) ayırır."""
    slug_s = NON_ALNUM.sub("", fold(slug))
    if not slug_s:
        return None
    tokens = body.split()
    for i in range(0, min(len(tokens), 5)):
        acc = ""
        for j in range(i, len(tokens)):
            acc += NON_ALNUM.sub("", fold(tokens[j]))
            if acc.startswith(slug_s):
                company = " ".join(tokens[:i]).strip(" -–—:|")
                title = " ".join(tokens[i:j + 1]).strip(" -–—:|…")
                return company, title
            if not slug_s.startswith(acc):
                break
    return None


def humanize_slug(slug: str) -> str:
    return " ".join(w.capitalize() if w.islower() else w for w in slug.replace("-", " ").split())


def parse_youthall(html_text: str, base: str) -> list[dict]:
    p = AnchorParser()
    p.feed(html_text)
    out = []
    for href, text in p.links:
        full = urllib.parse.urljoin(base, href)
        pu = urllib.parse.urlparse(full)
        if "youthall.com" not in pu.netloc:
            continue
        m = YOUTHALL_JOB.search(pu.path)
        if not m:
            continue
        company_slug, slug, _ = m.groups()
        deadline, city, body = None, "", text
        dm = DATE_TAIL.search(text)
        if dm:
            d, mo, y, city = dm.groups()
            deadline = f"{y}-{mo}-{d}"
            body = text[:dm.start()].strip()
        body = TYPE_TAIL.sub("", body)
        slug_core = slug.rsplit("_", 1)[0]
        sp = split_company_title(body, slug_core)
        if sp and sp[1]:
            out.append(make_job("Youthall", sp[1], full, sp[0] or humanize_slug(company_slug),
                                city, "TR", body, deadline=deadline, trusted_intern=True,
                                remote=bool(re.search(r"uzaktan|remote|online", fold(city + " " + slug)))))
            continue
        # Yedek: "Şirket - Başlık…" biçimindeki etiketten; kesilmişse/çok uzunsa slug'dan.
        head = re.split(r"…|\.\.\.", body)[0].strip()
        truncated = len(head) < len(body) and body[len(head):len(head) + 1] in ("…", ".")
        company = ""
        if " - " in head[:60]:
            company, head = [x.strip() for x in head.split(" - ", 1)]
        title = head
        if truncated or not title or len(title) > 90:
            title = humanize_slug(slug.rsplit("_", 1)[0])
        out.append(make_job("Youthall", title, full, company or humanize_slug(company_slug),
                            city, "TR", body, deadline=deadline, trusted_intern=True,
                            remote=bool(re.search(r"uzaktan|remote|online", fold(city + " " + slug)))))
    return out


def fetch_youthall(cfg: dict) -> list[dict]:
    """Youthall'ın herkese açık staj listesi (giriş gerektirmez). En iyi çaba."""
    out, errors = {}, []
    for base in cfg.get("urls", ["https://www.youthall.com/tr/is-ilanlari/stajyer/"]):
        try:
            for page in range(1, int(cfg.get("max_pages", 3)) + 1):
                url = base if page == 1 else f"{base}?page={page}"
                rows = parse_youthall(http_get(url), url)
                new = [r for r in rows if r["id"] not in out or len(r["snippet"]) > len(out[r["id"]]["snippet"])]
                if not rows or not new:
                    break
                for r in rows:
                    if r["id"] not in out or len(r["snippet"]) > len(out[r["id"]]["snippet"]):
                        out[r["id"]] = r
                time.sleep(PAUSE)
        except Exception as e:  # noqa: BLE001
            errors.append(str(e))
    if not out and errors:
        raise RuntimeError("; ".join(errors)[:300])
    return list(out.values())


def unwrap_google(link: str) -> str:
    p = urllib.parse.urlparse(link)
    if p.netloc.endswith("google.com") and p.path == "/url":
        q = urllib.parse.parse_qs(p.query)
        for key in ("url", "q"):
            if key in q:
                return q[key][0]
    return link


def parse_feed(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    items = []
    for el in root.iter():
        if el.tag.split("}")[-1] not in ("item", "entry"):
            continue
        d = {c.tag.split("}")[-1]: c for c in el}
        title = strip_tags(d["title"].text) if "title" in d else ""
        link = ""
        if "link" in d:
            link = d["link"].get("href") or (d["link"].text or "")
        summ = ""
        for k in ("description", "summary", "content"):
            if k in d and d[k].text:
                summ = strip_tags(d[k].text)
                break
        items.append({"title": title, "link": unwrap_google(link.strip()), "summary": summ})
    return items


def fetch_rss(cfg: dict) -> list[dict]:
    """Google Alerts (RSS) veya herhangi bir RSS/Atom akışı."""
    feeds = cfg.get("feeds", [])
    if not feeds:
        raise SkipSource("akış listesi boş")
    out, errors = [], []
    for f in feeds:
        try:
            for it in parse_feed(http_get(f["url"])):
                if it["link"]:
                    out.append(make_job(f.get("name", "RSS"), it["title"], it["link"], "",
                                        f.get("location", ""), f.get("country", "TR"), it["summary"]))
            time.sleep(PAUSE)
        except Exception as e:  # noqa: BLE001
            errors.append(str(e))
    if not out and errors:
        raise RuntimeError("; ".join(errors)[:300])
    return out


CAREER_RE = re.compile(r"(?<![a-z0-9])(staj|stajyer|intern|internship|praktikum|genc yetenek|early career|kariyer baslangic)")


def fetch_careers(cfg: dict) -> list[dict]:
    """Verdiğiniz firma kariyer sayfalarında 'staj/intern' içeren bağlantıları arar."""
    sites = cfg.get("sites", [])
    if not sites:
        raise SkipSource("firma listesi boş")
    out, errors = [], []
    for s in sites:
        try:
            p = AnchorParser()
            p.feed(http_get(s["url"]))
            for href, text in p.links:
                if not href or href.startswith(("#", "javascript:", "mailto:")):
                    continue
                if CAREER_RE.search(fold(text + " " + href)):
                    out.append(make_job(f"Kariyer: {s['name']}", text or "Staj bağlantısı",
                                        urllib.parse.urljoin(s["url"], href), s["name"],
                                        s.get("city", ""), s.get("country", "TR"), text,
                                        trusted_intern=True))
            time.sleep(PAUSE)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{s.get('name')}: {e}")
    if not out and errors:
        raise RuntimeError("; ".join(errors)[:300])
    return out


def fetch_adzuna(cfg: dict) -> list[dict]:
    """Adzuna ücretsiz API (ADZUNA_APP_ID / ADZUNA_APP_KEY gerekir). Türkiye kapsamı yok."""
    app_id, app_key = os.environ.get("ADZUNA_APP_ID"), os.environ.get("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        raise SkipSource("ADZUNA_APP_ID/ADZUNA_APP_KEY tanımlı değil")
    out, errors = [], []
    for c in cfg.get("countries", ["de", "gb"]):
        for q in cfg.get("queries", ["intern production"]):
            params = urllib.parse.urlencode({
                "app_id": app_id, "app_key": app_key, "results_per_page": 50, "what": q,
                "sort_by": "date", "max_days_old": cfg.get("max_days_old", 30)})
            try:
                data = json.loads(http_get(f"https://api.adzuna.com/v1/api/jobs/{c}/search/1?{params}"))
                for r in data.get("results", []):
                    out.append(make_job("Adzuna", r.get("title", ""), r.get("redirect_url", ""),
                                        (r.get("company") or {}).get("display_name", ""),
                                        (r.get("location") or {}).get("display_name", ""),
                                        c.upper(), strip_tags(r.get("description", "")),
                                        r.get("created")))
                time.sleep(PAUSE)
            except Exception as e:  # noqa: BLE001
                errors.append(str(e))
    if not out and errors:
        raise RuntimeError("; ".join(errors)[:300])
    return out


ATS_INTERN_RE = re.compile(r"(?<![a-z0-9])(staj|stajyer|intern|internship|praktikum|praktikant|werkstudent|trainee|co-?op|working student)")


def _ats_postings(site: dict) -> list[dict]:
    """Bir firmanın ATS (işe alım sistemi) herkese açık ilan listesini ortak biçime çevirir."""
    kind, key = site["type"], site["id"]
    out = []
    if kind == "greenhouse":
        data = json.loads(http_get(f"https://boards-api.greenhouse.io/v1/boards/{key}/jobs"))
        for r in data.get("jobs", []):
            out.append({"title": r.get("title", ""), "url": r.get("absolute_url", ""),
                        "location": (r.get("location") or {}).get("name", ""), "posted": r.get("updated_at")})
    elif kind == "lever":
        data = json.loads(http_get(f"https://api.lever.co/v0/postings/{key}?mode=json"))
        for r in data:
            out.append({"title": r.get("text", ""), "url": r.get("hostedUrl", ""),
                        "location": (r.get("categories") or {}).get("location", ""),
                        "snippet": r.get("descriptionPlain", ""), "posted": None})
    elif kind == "smartrecruiters":
        q = urllib.parse.urlencode({"q": site.get("q", "intern"), "limit": 100,
                                    **({"country": site["country"].lower()} if site.get("country") else {})})
        data = json.loads(http_get(f"https://api.smartrecruiters.com/v1/companies/{key}/postings?{q}"))
        for r in data.get("content", []):
            loc = r.get("location") or {}
            out.append({"title": r.get("name", ""), "url": f"https://jobs.smartrecruiters.com/{key}/{r.get('id', '')}",
                        "location": ", ".join(x for x in (loc.get("city"), (loc.get("country") or "").upper()) if x),
                        "posted": r.get("releasedDate")})
    elif kind == "workable":
        data = json.loads(http_get(f"https://apply.workable.com/api/v1/widget/accounts/{key}"))
        for r in data.get("jobs", []):
            out.append({"title": r.get("title", ""), "url": r.get("url", ""),
                        "location": ", ".join(x for x in (r.get("city"), r.get("country")) if x),
                        "posted": r.get("published_on")})
    else:
        raise ValueError(f"bilinmeyen ATS türü: {kind}")
    return out


def fetch_ats(cfg: dict) -> list[dict]:
    """Firma ATS panolarından (Greenhouse/Lever/SmartRecruiters/Workable) yalnızca staj benzeri ilanları alır."""
    sites = cfg.get("sites", [])
    if not sites:
        raise SkipSource("firma listesi boş")
    out, errors, ok = [], [], 0
    for s in sites:
        try:
            posts = _ats_postings(s)
            print(f"[ats] {s['name']}: {len(posts)} ilan okundu", file=sys.stderr)
            for r in posts:
                if not r.get("url") or not ATS_INTERN_RE.search(fold(r["title"])):
                    continue
                out.append(make_job(f"ATS: {s['name']}", r["title"], r["url"], s["name"],
                                    r.get("location") or s.get("city", ""), s.get("country", "TR"),
                                    r.get("snippet", ""), r.get("posted"), trusted_intern=True))
            ok += 1
            time.sleep(PAUSE)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{s.get('name')}: {e}")
    if not ok and errors:
        raise RuntimeError("; ".join(errors)[:300])
    return out


def fetch_jooble(cfg: dict) -> list[dict]:
    """Jooble ücretsiz API (JOOBLE_API_KEY gerekir). Türkiye dahil çok ülkeyi kapsar."""
    key = os.environ.get("JOOBLE_API_KEY")
    if not key:
        raise SkipSource("JOOBLE_API_KEY tanımlı değil")
    out, errors = [], []
    for q in cfg.get("queries", []):
        try:
            data = json.loads(http_get(f"https://{q.get('domain', cfg.get('domain', 'jooble.org'))}/api/{key}", json_body={
                "keywords": q["keywords"], "location": q.get("location", ""), "page": 1}))
            print(f"[jooble] {q['keywords']} / {q.get('location', '')}: toplam={data.get('totalCount')} gelen={len(data.get('jobs', []))}",
                  file=sys.stderr)
            for r in data.get("jobs", [])[:4]:
                print(f"   - {strip_tags(r.get('title', ''))[:70]} | {r.get('company', '')[:30]} | {r.get('location', '')[:30]}", file=sys.stderr)
            for r in data.get("jobs", []):
                if not r.get("link"):
                    continue
                out.append(make_job("Jooble", strip_tags(r.get("title", "")), r["link"], r.get("company", ""),
                                    r.get("location", "") or q.get("location", ""), q.get("country", "TR"),
                                    strip_tags(r.get("snippet", "")), r.get("updated")))
            time.sleep(PAUSE)
        except Exception as e:  # noqa: BLE001
            errors.append(str(e))
    if not out and errors:
        raise RuntimeError("; ".join(errors)[:300])
    return out


def fetch_pages(cfg: dict) -> dict:
    """Duyuru sayfalarındaki bağlantıları toplar. Yeni görünen bağlantı = yeni duyuru.
    Dönüş: {"items": [...], "ok_sites": [başarıyla okunan site adları]}"""
    sites = cfg.get("sites", [])
    if not sites:
        raise SkipSource("sayfa listesi boş")
    items, ok_sites, errors = [], [], []
    for s in sites:
        try:
            base = s["url"]
            p = AnchorParser()
            if s.get("ajax"):  # liste, sayfaya POST ile sonradan yükleniyor
                aj = s["ajax"]
                p.feed(http_get(urllib.parse.urljoin(base, aj["url"]), data=aj["data"],
                                headers={"Referer": base}))
            else:
                p.feed(http_get(base))
            seen = set()
            for href, text in p.links:
                if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                    continue
                full = canon_url(urllib.parse.urljoin(base, href))
                if urllib.parse.urlparse(full).scheme not in ("http", "https"):
                    continue
                if len(text) < (8 if s.get("ajax") else 15) or full in seen or full.rstrip("/") == base.rstrip("/"):
                    continue
                if s.get("must") and not any(fold(m) in fold(text + " " + full) for m in s["must"]):
                    continue  # genel kurum sayfalarında yalnızca ilgili duyurular (ör. "staj")
                seen.add(full)
                items.append({"id": hashlib.sha1(full.encode()).hexdigest()[:12], "site": s["name"],
                              "title": text[:200], "url": full, "notify": s.get("notify", "important")})
            ok_sites.append(s["name"])
            time.sleep(PAUSE)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{s.get('name')}: {e}")
    if not ok_sites and errors:
        raise RuntimeError("; ".join(errors)[:300])
    return {"items": items, "ok_sites": ok_sites}


FETCHERS = {
    "youthall": fetch_youthall,
    "arbeitnow": fetch_arbeitnow,
    "adzuna": fetch_adzuna,
    "rss": fetch_rss,
    "careers": fetch_careers,
    "ats": fetch_ats,
    "jooble": fetch_jooble,
    "pages": fetch_pages,
}


# ------------------------------------------------------------------- puanlama
INTERN_RE = re.compile(
    r"(?<![a-z0-9])(staj\w*|intern(?:s|ship|ships)?(?![a-z0-9])|praktik\w*|werkstudent\w*|apprentice\w*|co-op(?![a-z0-9]))")


@functools.lru_cache(maxsize=None)
def kw_re(kw: str, strict: bool = False) -> re.Pattern:
    k = re.escape(fold(kw))
    tail = r"(?![a-z0-9])" if (strict or len(kw) <= 4) else ""
    return re.compile(r"(?<![a-z0-9])" + k + tail)


@functools.lru_cache(maxsize=1)
def _city_table():
    data = json.loads((ROOT / "config" / "cities.json").read_text(encoding="utf-8"))
    items = sorted(((fold(k), v) for k, v in data.items()), key=lambda kv: -len(kv[0]))
    return [(re.compile(r"(?<![a-z])" + re.escape(k) + r"(?![a-z])"), k, v) for k, v in items]


def locate(text: str):
    """Metindeki ilk bilinen şehri bulur; (şehir, Bursa'dan km) ya da (None, None)."""
    t = fold(text)
    best = None  # metinde en önce geçen yer kazanır ("Gebze, Kocaeli" -> Gebze); eşitlikte uzun ad
    for rx, name, km in _city_table():
        m = rx.search(t)
        if m and (best is None or (m.start(), -len(name)) < best[0]):
            best = ((m.start(), -len(name)), name, km)
    return (best[1], best[2]) if best else (None, None)


def region_for_km(km):
    if km is None:
        return "belirsiz"
    if km == 0:
        return "bursa"
    if km <= 200:
        return "yakin"
    if km <= 450:
        return "orta"
    return "uzak"


REMOTE_RE = re.compile(r"uzaktan|remote|home ?office|evden calis|work from home|\bwfh\b|telecommut|"
                       r"online (?:staj|intern)|sanal staj|virtual intern|fully distributed")
HYBRID_RE = re.compile(r"hybrid|hibrit|karma calisma")
NOT_REMOTE_RE = re.compile(r"no remote|not remote|remote work is not|remote.{0,20}not (?:possible|available|offered)|"
                           r"uzaktan.{0,25}(?:yok|degil|mumkun degil|olmayacak)|on-?site only|yuz yuze|office-based|ofiste calis")


def detect_remote(job: dict):
    """İlanı inceler: tam uzaktan ise 'uzaktan', karma ise 'hibrit', değilse None döndürür.
    Başlık, konum ve açıklamanın başı okunur; 'uzaktan çalışma yok' gibi olumsuzlar sayılmaz."""
    text = fold(" ".join([job.get("location", ""), job.get("title", ""), (job.get("snippet") or "")[:500]]))
    if HYBRID_RE.search(text) and not re.search(r"fully remote|tamamen uzaktan|%100 uzaktan", text):
        return "hibrit"
    if NOT_REMOTE_RE.search(text):
        return None
    if job.get("remote") or REMOTE_RE.search(text):
        return "uzaktan"
    return None


# Uzaktan stajlarda yaz/kısa dönem şartı aranmaz: süre ile ilgili cezalar uygulanmaz
REMOTE_IGNORE_NEG = {"uzun dönem", "long term", "long-term", "part time", "yarı zamanlı"}


def classify(job: dict, prof: dict) -> tuple[str, list[str]]:
    loc = fold(job["location"] + " " + job["title"])
    if job["country"] != "TR":
        region, job["city"], job["km"] = "yurtdisi", None, None
    else:
        city, km = locate(job["location"])
        if city is None:
            city, km = locate(job["title"])
        job["city"], job["km"] = city, km
        region = region_for_km(km)
    tags = []
    remote_tag = detect_remote(job)
    if remote_tag:
        tags.append(remote_tag)
    full = fold(" ".join([job["title"], job["snippet"]]))
    if re.search(r"\(m/w/d\)|\(w/m/d\)|\(m/f/d\)|deutsch|almanca|fliessend|german", full):
        tags.append("almanca")  # ilan Almanca ya da Almanca bilgisi isteniyor olabilir
    return region, tags


def score_job(job: dict, prof: dict):
    """(puan, nedenler, bölge, etiketler) döndürür; staj değilse None."""
    text = fold(" ".join([job["title"], job["company"], job["snippet"]]))
    title = fold(job["title"])
    # Staj ifadesi başlıkta ya da açıklamanın başında geçmeli (açıklamanın ortasındaki
    # "stajyerlere mentorluk yaparsın" gibi cümleler ilanı staj yapmaz).
    if not (job.get("trusted_intern") or INTERN_RE.search(title + " " + fold(job["snippet"][:200]))):
        return None
    reasons, s = ["staj ilanı"], 20.0

    role = 0.0
    for kw, w in prof.get("role_keywords", {}).items():
        rx = kw_re(kw)
        if rx.search(title):
            role += w * 1.5
            reasons.append(f"başlıkta: {kw}")
        elif rx.search(text):
            role += w
            reasons.append(kw)
    s += min(role, 60)

    skills = [k for k in prof.get("skills", []) if kw_re(k, True).search(text)]
    if skills:
        s += min(15, 5 * len(skills))
        reasons.append("beceri: " + ", ".join(skills))

    region, tags = classify(job, prof)
    for kw, w in prof.get("negative", {}).items():
        if "uzaktan" in tags and kw in REMOTE_IGNORE_NEG:
            continue  # uzaktan stajlarda süre (uzun dönem, yarı zamanlı) puan düşürmez
        if kw_re(kw).search(text):
            s -= w
            reasons.append(f"-{w}: {kw}")

    weights = prof.get("location", {}).get("weights", {})
    s += weights.get({"bursa": "home", "yakin": "near", "orta": "turkey", "uzak": "turkey",
                      "belirsiz": "turkey", "yurtdisi": "abroad"}[region], 0)
    if "uzaktan" in tags:
        s += weights.get("remote", 0)
    return max(0, min(100, round(s))), reasons, region, tags


# --------------------------------------------------------------------- bildirim
def post_json(url: str, payload: dict) -> None:
    data = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        r.read()


def notify(subject: str, body: str, dry: bool) -> list[str]:
    if dry:
        print(f"--- BİLDİRİM (dry-run) ---\n{subject}\n{body}\n--------------------------")
        return ["dry-run"]
    sent = []
    site = os.environ.get("SITE_URL", "").rstrip("/")
    if site:
        body = f"{body}\n\nTüm bildirimler: {site}/#bildirimler"
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if token and chat:
        try:
            post_json(f"https://api.telegram.org/bot{token}/sendMessage",
                      {"chat_id": chat, "text": f"{subject}\n\n{body}"[:4000],
                       "disable_web_page_preview": "true"})
            sent.append("telegram")
        except Exception as e:  # noqa: BLE001  (token URL'de; ayrıntı yazdırma)
            print(f"Telegram gönderilemedi: {type(e).__name__}", file=sys.stderr)
    topic = os.environ.get("NTFY_TOPIC")
    if topic:
        try:
            msg = {"topic": topic, "title": subject[:200], "message": body[:3500]}
            if site:
                msg["click"] = f"{site}/#bildirimler"
            payload = json.dumps(msg).encode("utf-8")
            req = urllib.request.Request("https://ntfy.sh/", data=payload,
                                         headers={"User-Agent": UA, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                r.read()
            sent.append("ntfy")
        except Exception as e:  # noqa: BLE001  (kanal adı gizli; ayrıntı yazdırma)
            print(f"ntfy gönderilemedi: {type(e).__name__}", file=sys.stderr)
    user, pw, to = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASS"), os.environ.get("NOTIFY_EMAIL")
    if user and pw and to:
        try:
            msg = EmailMessage()
            msg["Subject"], msg["From"], msg["To"] = subject, user, to
            msg.set_content(body)
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
                s.login(user, pw)
                s.send_message(msg)
            sent.append("email")
        except Exception as e:  # noqa: BLE001
            print(f"E-posta gönderilemedi: {type(e).__name__}", file=sys.stderr)
    if not sent:
        print("Bildirim kanalı tanımlı değil (ntfy/Telegram/e-posta secret'ları yok); atlandı.")
    return sent


def fmt_jobs(jobs: list[dict], limit: int = 10) -> str:
    lines = []
    for j in jobs[:limit]:
        place = j["location"] or j["country"]
        who = f" — {j['company']}" if j["company"] else ""
        dl = f" (son başvuru {j['deadline']})" if j.get("deadline") else ""
        lines.append(f"• [{j['score']}] {j['title']}{who} · {place}{dl}\n  {j['url']}")
    if len(jobs) > limit:
        lines.append(f"… ve {len(jobs) - limit} ilan daha (siteye bak).")
    return "\n".join(lines)


# ------------------------------------------------------------------------ ana akış
def load_json(path: Path, default=None):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def parse_dt(s: str) -> dt.datetime:
    d = dt.datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def expired(job: dict, today: dt.date) -> bool:
    try:
        return bool(job.get("deadline")) and dt.date.fromisoformat(job["deadline"]) < today
    except ValueError:
        return False


# ------------------------------------------------------------ depolama (Supabase)
def supa_rpc(name: str, payload: dict):
    """Supabase RPC çağrısı. Yalnızca herkese açık anon anahtarı + özel yazma belirteci kullanılır."""
    base = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_ANON_KEY"]
    req = urllib.request.Request(
        f"{base}/rest/v1/rpc/{name}", data=json.dumps(payload).encode("utf-8"),
        headers={"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Supabase {name}: HTTP {e.code}") from None
    return json.loads(raw) if raw.strip() else None


def use_supabase() -> bool:
    if os.environ.get("SUPABASE_URL") and not os.environ.get("STAJ_INGEST_TOKEN"):
        # Sessizce yerel dosyaya yazıp veriyi kaybetmek yerine açıkça hata ver
        raise RuntimeError("STAJ_INGEST_TOKEN gizli anahtarı eksik: GitHub depo ayarlarında Secrets bölümüne ekle")
    return all(os.environ.get(k) for k in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "STAJ_INGEST_TOKEN"))


def load_state(data_path: Path):
    default = {"meta": {}, "jobs": {}}
    if use_supabase():
        st = supa_rpc("staj_get_state", {"p_token": os.environ["STAJ_INGEST_TOKEN"]})
        return st if st else default
    return load_json(data_path, default)


def save_state(data_path: Path, state: dict) -> None:
    if use_supabase():
        supa_rpc("staj_put_state", {"p_token": os.environ["STAJ_INGEST_TOKEN"], "p_data": state})
        return
    data_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


DEADLINE_STEPS = (7, 3, 1)
PROGRAM_STEPS = (14, 7, 3, 1)
DIGEST_HEARTBEAT_DAYS = 7  # sessiz modda bu kadar gün hiç bildirim gitmediyse "çalışıyorum" haberi


def firm_slug(name: str) -> str:
    """Sitedeki slug() ile aynı kural (firma:<slug> anahtarları için)."""
    return re.sub(r"[^a-z0-9ğüşöçı]+", "-", name.lower()).strip("-")


def company_names(jobs: dict, sources: dict) -> dict:
    out = {j["id"]: j.get("title", j["id"]) for j in jobs.values() if "id" in j}
    for c in sources.get("companies", []):
        out[f"firma:{firm_slug(c['name'])}"] = f"{c['name']} (ilansız başvuru)"
    for w in sources.get("watchlist", []):
        if w.get("pin"):
            out[f"prog:{firm_slug(w['name'])}"] = w["name"]
    return out


def followups() -> list[dict]:
    """7. ve 14. günü gelen, hâlâ 'Başvurdum' durumundaki başvurular (Supabase yoksa boş)."""
    if not use_supabase():
        return []
    got = supa_rpc("staj_followups", {"p_token": os.environ["STAJ_INGEST_TOKEN"]})
    return [x for x in (got or []) if isinstance(x, dict) and x.get("job_id")]


def digest_stats() -> dict:
    if not use_supabase():
        return {}
    return supa_rpc("staj_digest_stats", {"p_token": os.environ["STAJ_INGEST_TOKEN"]}) or {}


def build_digest(jobs: dict, stats: dict, today: dt.date, far_below: int, now: dt.datetime,
                 programs: list | None = None, pick_min: int | None = None, quiet: bool = False):
    """Günlük özet: sana özel yeni ilanlar (puan >= pick_min), yaklaşan son tarihler, program tarihleri, başvuru sayıları.
    quiet=True iken anlatılacak yeni bir şey yoksa None döner (bildirim gönderilmez)."""
    since = now - dt.timedelta(days=1)
    fit = [j for j in jobs.values() if j.get("score", 0) >= far_below]
    picks = [j for j in fit if j.get("score", 0) >= (pick_min or 0)]
    new_fit = sorted((j for j in picks if parse_dt(j["first_seen"]) >= since), key=lambda j: -j.get("score", 0))
    soon = []
    for j in fit:
        try:
            left = (dt.date.fromisoformat(j["deadline"]) - today).days if j.get("deadline") else None
        except ValueError:
            left = None
        if left is not None and 0 <= left <= 7:
            soon.append((left, j))
    soon.sort(key=lambda x: x[0])
    if new_fit:
        lines = [f"• Son 24 saatte {len(new_fit)} yeni uygun ilan (toplam {len(fit)} uygun ilan):"]
        lines += [f"   {j['title']} — {j.get('company', '')}" for j in new_fit[:3]]
        if len(new_fit) > 3:
            lines.append(f"   … ve {len(new_fit) - 3} ilan daha")
    else:
        lines = [f"• Son 24 saatte yeni uygun ilan yok (toplam {len(fit)} uygun ilan)."]
    if soon:
        lines.append("• Son başvurusu bu hafta olanlar:")
        lines += [f"   {l} gün: {j['title']} — {j.get('company', '')}" for l, j in soon[:5]]
    prog_lines = []
    for w in programs or []:
        try:
            left = (dt.date.fromisoformat(w["deadline"]) - today).days if w.get("deadline") else None
        except ValueError:
            left = None
        if left is not None and 0 <= left <= (14 if quiet else 45):
            prog_lines.append(f"• {w['name']}: son başvuruya {left} gün kaldı.")
    lines += prog_lines
    if quiet and not (new_fit or soon or prog_lines):
        return None
    if stats:
        lines.append(f"• Başvuru: bu hafta {stats.get('applied_week', 0)}, toplam {stats.get('applied_total', 0)}; "
                     f"cevap bekleyen {stats.get('waiting', 0)}, mülakat {stats.get('interview', 0)}.")
        if stats.get("known"):
            lines.append(f"• Tanıdığın olan {stats['known']} yer var; referans istemeyi unutma.")
    return "Staj Radar günlük özet", "\n".join(lines)


def new_access_requests() -> list[str]:
    """Henüz bildirilmemiş erişim isteklerini alır (Supabase yoksa boş)."""
    if not use_supabase():
        return []
    got = supa_rpc("staj_take_new_requests", {"p_token": os.environ["STAJ_INGEST_TOKEN"]})
    return [str(x) for x in (got or [])]


def run(args) -> int:
    cfg_dir = Path(args.config_dir) if getattr(args, "config_dir", None) else ROOT / "config"
    prof = load_json(cfg_dir / "profile.json")
    sources = load_json(cfg_dir / "sources.json")
    data_path = Path(args.data) if args.data else ROOT / "docs/data/jobs.json"
    state = load_state(data_path)
    meta = state.setdefault("meta", {})
    meta.setdefault("sources", {})
    meta.setdefault("last_run", {})
    jobs = state.setdefault("jobs", {})
    anns = state.setdefault("announcements", {})
    had_events = "events" in state
    events = state.setdefault("events", [])
    welcomed = bool(meta.get("welcomed"))
    now = utcnow()
    now_iso = now.isoformat(timespec="seconds")
    today = now.astimezone(dt.timezone(dt.timedelta(hours=3))).date()  # Türkiye saati (UTC+3, yaz saati yok)
    min_score = int(prof.get("notify_min_score", 35))
    alerts, fresh, fresh_ann, ok_sites = [], [], [], []

    ev_ids = {e["id"] for e in events}

    def add_event(typ, title, text="", url="", source="", score=None, important=False, ts=None, key=None):
        eid = hashlib.sha1(f"{typ}|{key or url or title}".encode()).hexdigest()[:12]
        if eid in ev_ids:
            return
        ev_ids.add(eid)
        events.append({"id": eid, "ts": ts or now_iso, "type": typ, "title": title[:200], "text": text[:200],
                       "url": url, "source": source, "score": score, "important": important})

    if not had_events:  # eski veriden başlangıç akışı oluştur
        for j in jobs.values():
            if j.get("score", 0) >= min_score:
                add_event("ilan", j["title"], " · ".join(x for x in (j["company"], j["location"]) if x),
                          j["url"], j["source"], j["score"], j["score"] >= 50, ts=j["first_seen"])

    for name, fn in FETCHERS.items():
        cfg = sources.get(name, {})
        st = meta["sources"].setdefault(name, {"fail_streak": 0})
        if not cfg.get("enabled"):
            st.update(status="kapalı", error=None)
            continue
        gate = cfg.get("min_interval_hours")
        last = meta["last_run"].get(name)
        if gate and last and (now - parse_dt(last)).total_seconds() < gate * 3600 and not args.force:
            st.update(status="bekliyor", error=None)
            continue
        try:
            res = fn(cfg)
            if name == "pages":
                fresh_ann += res["items"]
                ok_sites += res["ok_sites"]
                count = len(res["items"])
            else:
                fresh += res
                count = len(res)
            st.update(status="ok", count=count, error=None, at=now_iso, fail_streak=0)
            meta["last_run"][name] = now_iso
        except SkipSource as e:
            st.update(status="atlandı", error=str(e), count=0)
        except Exception as e:  # noqa: BLE001
            st["fail_streak"] = st.get("fail_streak", 0) + 1
            st.update(status="hata", error=str(e)[:300], at=now_iso)
            print(f"[{name}] HATA: {e}", file=sys.stderr)
            if st["fail_streak"] == FAIL_ALERT_STREAK:
                alerts.append(f"{name} kaynağı {FAIL_ALERT_STREAK} taramadır hata veriyor: {st['error']}")

    # --- ilanlar
    seen, new_jobs = set(), []
    for j in fresh:
        if j["id"] in seen or expired(j, today):
            continue
        seen.add(j["id"])
        res = score_job(j, prof)
        if res is None:
            continue
        if res[0] < int(prof.get("min_score_keep", 10)):
            continue
        j["score"], j["reasons"], j["region"], j["tags"] = res
        j.pop("trusted_intern", None)
        old = jobs.get(j["id"])
        if old:
            keep = {k: old[k] for k in ("first_seen", "notified") if k in old}
            old.update(j)
            old.update(keep)
            old["last_seen"] = now_iso
        else:
            j.update(first_seen=now_iso, last_seen=now_iso, notified=False)
            jobs[j["id"]] = j
            new_jobs.append(j)

    for old_job in jobs.values():  # eski ilanların uzaktan/hibrit etiketlerini güncel kurala göre yenile
        try:
            tg = classify(dict(old_job), prof)[1]
            if sorted(tg) != sorted(old_job.get("tags", [])):
                old_job["tags"] = tg
        except Exception:  # noqa: BLE001
            pass

    cutoff = now - dt.timedelta(days=int(prof.get("max_age_days", 21)))
    keep_min = int(prof.get("min_score_keep", 10))
    for jid in [i for i, j in jobs.items()
                if parse_dt(j["last_seen"]) < cutoff or expired(j, today) or j.get("score", 0) < keep_min]:
        del jobs[jid]

    # --- duyurular (okul/kurum sayfaları): ilk görülen site sessizce "tohumlanır"
    seeded = meta.setdefault("pages_seeded", {})
    kws = prof.get("announcement_keywords", [])
    new_anns, seen_a = [], set()
    for a in fresh_ann:
        if a["id"] in seen_a:
            continue
        seen_a.add(a["id"])
        if a["id"] in anns:
            anns[a["id"]]["last_seen"] = now_iso
            continue
        imp = any(kw_re(k).search(fold(a["title"])) for k in kws)
        anns[a["id"]] = {"title": a["title"], "url": a["url"], "site": a["site"],
                         "first_seen": now_iso, "last_seen": now_iso, "important": imp}
        if seeded.get(a["site"]):
            new_anns.append(dict(a, important=imp))
    for site in ok_sites:
        seeded[site] = True
    for aid in [i for i, a in anns.items() if parse_dt(a["last_seen"]) < now - dt.timedelta(days=60)]:
        del anns[aid]
    for a in new_anns:
        add_event("duyuru", a["title"], a["site"], a["url"], a["site"], None, a["important"])

    # --- bildirimler
    def near_first(j):  # Bursa'ya yakınlık önce, aynı mesafede yüksek puan; yurt dışı en sonda
        km = 99999 if j.get("country", "TR") != "TR" else (j.get("km") if j.get("km") is not None else 9999)
        return (km, -j["score"])
    to_notify = sorted((j for j in new_jobs if j["score"] >= min_score), key=near_first)
    for j in to_notify:
        add_event("ilan", j["title"], " · ".join(x for x in (j["company"], j["location"]) if x),
                  j["url"], j["source"], j["score"], j["score"] >= 50)
    to_push = [a for a in new_anns if a["notify"] == "all" or a["important"]]

    # Son başvuru tarihi yaklaşan ilanlar için 7, 3 ve 1 gün kala hatırlatma (her eşik bir kez)
    due = []
    for j in jobs.values():
        if j.get("deadline") and j.get("score", 0) >= min_score:
            try:
                left = (dt.date.fromisoformat(j["deadline"]) - today).days
            except ValueError:
                continue
            sent_th = j.setdefault("dl_sent", [])
            if j.get("dl_notified") and not sent_th:  # eski tek seferlik hatırlatma yapılmışsa 7 ve 3'ü say
                sent_th.extend([7, 3])
            pending = [t for t in DEADLINE_STEPS if 0 <= left <= t and t not in sent_th]
            if pending:
                sent_th.extend(pending)
                due.append((left, j))
    for left, j in sorted(due, key=lambda x: x[0]):
        add_event("hatirlatma", f"Son başvuru {left} gün: {j['title']}",
                  " · ".join(x for x in (j["company"], j["location"]) if x), j["url"], j["source"], j["score"], True,
                  key=f"dl{min(t for t in DEADLINE_STEPS if left <= t)}|{j['url'] or j['id']}")

    # Programların (Ulusal Staj Programı vb.) son başvuru tarihi: 14, 7, 3 ve 1 gün kala
    prog_sent = meta.setdefault("prog_sent", {})
    for w in sources.get("watchlist", []):
        if not w.get("deadline"):
            continue
        try:
            left = (dt.date.fromisoformat(w["deadline"]) - today).days
        except ValueError:
            continue
        sent_th = prog_sent.setdefault(f"{w['name']}|{w['deadline']}", [])
        pending = [t for t in PROGRAM_STEPS if 0 <= left <= t and t not in sent_th]
        if pending:
            sent_th.extend(pending)
            step = min(t for t in PROGRAM_STEPS if left <= t)
            add_event("hatirlatma", f"Son başvuru {left} gün: {w['name']}", w.get("window", ""), w.get("url", ""),
                      "program", None, True, key=f"prog{step}|{w['name']}|{w['deadline']}")

    # Başvuru takibi: 7. ve 14. günde "cevap yok, takip et" hatırlatması (Supabase'teki başvurulardan)
    if not args.no_notify and not args.dry_run:  # RPC kaydı 'bildirildi' işaretler; kuru çalıştırmada dokunma
        try:
            fups = [f for f in followups() if not str(f["job_id"]).startswith("prog:")]  # programlarda 'cevap yok' takibi anlamsız
        except Exception as e:  # noqa: BLE001
            print(f"Takip hatırlatmaları okunamadı: {type(e).__name__}", file=sys.stderr)
            fups = []
        if fups:
            names = company_names(jobs, sources)
            lines = []
            for f in fups:
                nm = names.get(f["job_id"], f["job_id"])
                add_event("hatirlatma", f"Takip zamanı ({f['kind']}. gün): {nm}",
                          f"{f['days']} gün önce başvurdun, cevap yok" + (f" · {f['contact']}" if f.get("contact") else ""),
                          "", "başvuru", None, True, key=f"fu{f['kind']}|{f['job_id']}")
                lines.append(f"• {nm}: {f['days']} gün önce başvurdun, cevap yok."
                             + (f"\n  İletişim: {f['contact']}" if f.get("contact") else ""))
            notify(f"Takip zamanı: {len(fups)} başvuru",
                   "Cevap gelmediyse nazik bir takip e-postası at.\n" + "\n".join(lines), args.dry_run)

    if not welcomed and jobs:
        # İlk özet: bir bildirim kanalı gerçekten çalışana kadar bekler (secret'lar sonradan eklenebilir).
        top = sorted(jobs.values(), key=lambda j: -j["score"])
        sent = notify(f"Staj Radar çalışıyor: {len(jobs)} ilan bulundu",
                      "En iyi eşleşmeler:\n" + fmt_jobs(top), args.dry_run)
        if sent:
            meta["welcomed"] = True
            add_event("sistem", "Staj Radar çalışıyor", f"{len(jobs)} ilan bulundu", important=False)
            for j in jobs.values():
                j["notified"] = True
    elif not args.no_notify:
        if to_notify:
            notify(f"Yeni staj ilanı: {len(to_notify)} eşleşme", fmt_jobs(to_notify), args.dry_run)
            for j in to_notify:
                jobs[j["id"]]["notified"] = True
    if to_push and not args.no_notify:
        lines = [f"• [{a['site']}] {a['title']}\n  {a['url']}" for a in to_push[:10]]
        notify(f"Yeni duyuru: {len(to_push)}", "\n".join(lines), args.dry_run)
    if due and not args.no_notify:
        notify(f"Son başvuru yaklaşıyor: {len(due)} ilan",
               "\n".join(f"• {l} gün kaldı: {j['title']} — {j['company']}\n  {j['url']}" for l, j in sorted(due, key=lambda x: x[0])[:10]),
               args.dry_run)
    for a in alerts:
        add_event("sistem", a, important=True)
        if not args.no_notify:
            notify("Staj Radar uyarı", a, args.dry_run)

    # Günlük özet: zamanlanmış çalıştırmada (SEND_DIGEST=1) günde bir kez; yeni ilan olmasa da gönderilir
    tr_now = now.astimezone(dt.timezone(dt.timedelta(hours=3)))
    day_key = tr_now.date().isoformat()
    if not args.no_notify and os.environ.get("SEND_DIGEST") == "1" and meta.get("digest_day") != day_key and jobs:
        try:
            stats = digest_stats()
        except Exception as e:  # noqa: BLE001
            print(f"Özet istatistikleri okunamadı: {type(e).__name__}", file=sys.stderr)
            stats = {}
        quiet = bool(prof.get("digest_quiet", True))
        got = build_digest(jobs, stats, today, int(prof.get("far_below", 28)), now, sources.get("watchlist", []),
                           int(prof.get("pick_min", 50)), quiet)
        if got is None:  # sessiz mod: yeni bir şey yok. 7 gündür hiçbir şey gitmediyse "çalışıyorum" haberi ver
            last_sent = meta.get("digest_day")
            try:
                idle = (today - dt.date.fromisoformat(last_sent)).days if last_sent else 99
            except ValueError:
                idle = 99
            if idle >= DIGEST_HEARTBEAT_DAYS:
                got = ("Staj Radar çalışıyor",
                       f"Son {DIGEST_HEARTBEAT_DAYS} gündür sana özel yeni ilan çıkmadı. Tarama her gün çalışıyor; toplam {len(jobs)} ilan listede.")
        if got and notify(got[0], got[1], args.dry_run):
            meta["digest_day"] = day_key
            add_event("sistem", "Günlük özet", got[1].replace("\n", " ")[:200], key=f"digest|{day_key}")

    # Siteye erişim isteyenler (anında bildirim gitmediyse burada yakalanır)
    if not args.no_notify and not args.dry_run:
        try:
            reqs = new_access_requests()
        except Exception as e:  # noqa: BLE001
            print(f"Erişim istekleri okunamadı: {type(e).__name__}", file=sys.stderr)
            reqs = []
        if reqs:
            add_event("sistem", f"Erişim isteği: {', '.join(reqs)}", important=True)
            notify("Staj Radar: erişim isteği",
                   "\n".join(f"• {m}" for m in reqs) + "\nOnaylamak için siteyi aç → Erişim sekmesi.", args.dry_run)

    events.sort(key=lambda e: e["ts"], reverse=True)
    del events[300:]
    meta["updated"] = now_iso
    meta["total"] = len(jobs)
    meta["watchlist"] = sources.get("watchlist", [])
    meta["companies"] = sources.get("companies", [])
    meta["companies_source"] = sources.get("companies_source", "")
    meta["page_sites"] = [{"name": x["name"], "url": x["url"]} for x in sources.get("pages", {}).get("sites", [])]
    meta["criteria"] = prof.get("criteria", {})
    meta["far_below"] = int(prof.get("far_below", 28))
    save_state(data_path, state)
    print(f"Toplam {len(jobs)} ilan, {len(new_jobs)} yeni ilan, {len(to_notify)} ilan bildirimi, "
          f"{len(new_anns)} yeni duyuru.")
    return 0

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="bildirimleri göndermek yerine yazdır")
    ap.add_argument("--no-notify", action="store_true")
    ap.add_argument("--force", action="store_true", help="min_interval_hours kapısını yok say")
    ap.add_argument("--data", help="jobs.json yolu (test için)")
    ap.add_argument("--config-dir", help="profile.json ve sources.json klasörü (test için)")
    sys.exit(run(ap.parse_args()))
