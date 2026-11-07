import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import radar  # noqa: E402

radar.PAUSE = 0
ORIG_GET = radar.http_get

YOUTHALL_HTML = """
<html><body>
<a href="https://www.youthall.com/en/pgcareersturkey/summer-internship-2027-manufacturing-gebze-plant_117/">
 <div>P&amp;G - Summer Internship 2027…</div><div>P&amp;G logo</div>
 <div>Summer Internship 2027: Manufacturing | Gebze Plant Are you passionate about developing people…</div>
 <span>Stajyer</span> <span>16.12.2026</span> <span>Kocaeli</span></a>
<a href="https://www.youthall.com/en/pgcareersturkey/summer-internship-2027-sales_120/">
 <div>P&amp;G - Summer Internship 2027: Sales</div><div>Summer Internship 2027: Sales Are you ready to step into FMCG sales?</div>
 <span>Stajyer</span> <span>16.12.2026</span> <span>İstanbul</span></a>
<a href="https://www.youthall.com/tr/sefine/sky-uzun-donem-staj-programi_5/">
 <div>Sefine Tersanesi - SKY Uzun Dönem Staj Programı</div> <span>Stajyer</span> <span>27.11.2026</span> <span>Yalova</span></a>
<a href="https://www.youthall.com/tr/EskiFirma/eski-ilan_9/"><div>Eski - Production Intern</div> Stajyer 01.01.2020 Bursa</a>
<a href="https://www.youthall.com/tr/is-ilanlari/">Tüm ilanlar</a>
</body></html>
"""

ARBEITNOW = json.dumps({"data": [
    {"slug": "a", "company_name": "Werk GmbH", "title": "Praktikum Produktionsplanung (m/w/d)",
     "description": "<p>Excel und SQL Kenntnisse, Lean Manufacturing</p>", "remote": False,
     "url": "https://www.arbeitnow.com/jobs/a?utm_source=x", "location": "Stuttgart", "created_at": 1790000000},
    {"slug": "b", "company_name": "Soft AG", "title": "Senior Software Engineer",
     "description": "Backend services for our platform.", "remote": True, "url": "https://www.arbeitnow.com/jobs/b",
     "location": "Berlin", "created_at": 1790000001},
]})

RSS = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry>
<title>&lt;b&gt;Tofaş&lt;/b&gt; yaz stajı üretim mühendisliği</title>
<link href="https://www.google.com/url?rct=j&amp;url=https://example.com/staj1&amp;ct=ga"/>
<content type="html">Bursa fabrikası endüstri mühendisliği stajyer</content></entry></feed>"""

CAREER_HTML = """<a href="/kariyer/staj-programi">Yaz Stajı Programı</a><a href="/hakkimizda">Hakkımızda</a>
<a href="https://x.com/jobs/1">Senior Manager</a>"""


PAGE_LINKS = ['<a href="/endustri/duyuru/1">Staj Defterlerinin Teslimi Hakkında Duyuru</a>',
              '<a href="/endustri/duyuru/2">Yaz Dönemi Zorunlu Staj Başvuruları</a>',
              '<a href="/endustri/">Ana sayfa</a>']


def fake_get(url, headers=None, timeout=25, retries=2, data=None):
    if "pages.test" in url:
        return "<html>" + "".join(PAGE_LINKS) + "</html>"
    if "youthall.com" in url:
        return YOUTHALL_HTML if "page=" not in url else "<html></html>"
    if "arbeitnow.co.uk" in url:
        raise RuntimeError("uk down")
    if "arbeitnow.com" in url:
        return ARBEITNOW if "page=1" in url else json.dumps({"data": []})
    if "alerts.test" in url:
        return RSS
    if "career.test" in url:
        return CAREER_HTML
    raise RuntimeError("beklenmeyen url " + url)


class RadarTests(unittest.TestCase):
    def setUp(self):
        self.prof = json.loads((ROOT / "config/profile.json").read_text())
        radar.http_get = fake_get

    def test_fold(self):
        self.assertEqual(radar.fold("İSTANBUL Üretim ŞEF ığ"), "istanbul uretim sef ig")

    def test_youthall_parse(self):
        jobs = radar.parse_youthall(YOUTHALL_HTML, "https://www.youthall.com/tr/is-ilanlari/stajyer/")
        self.assertEqual(len(jobs), 4)
        by_url = {j["url"].split("/")[-2]: j for j in jobs}
        gebze = by_url["summer-internship-2027-manufacturing-gebze-plant_117"]
        self.assertEqual(gebze["deadline"], "2026-12-16")
        self.assertEqual(gebze["location"], "Kocaeli")
        self.assertIn("Manufacturing", gebze["title"])  # kesik etiket yerine slug'dan
        sef = by_url["sky-uzun-donem-staj-programi_5"]
        self.assertEqual(sef["company"], "Sefine Tersanesi")
        self.assertEqual(sef["title"], "SKY Uzun Dönem Staj Programı")

    def test_youthall_real_format(self):
        html = (
            '<a href="/en/pgcareersturkey/summer-internship-2027-manufacturing-gebze-plant_117/">'
            "P&amp;G Summer Internship 2027: Manufacturing | Gebze Plant Are you passionate about… Stajyer 16.12.2026 Kocaeli</a>"
            '<a href="/tr/Akcansa/ready-mix-concrete-long-term-intern-thrace_58/">'
            "Akçansa Ready-Mix Concrete Long-Term Intern - Thrace About Us As a leader… Stajyer 17.11.2026 Tekirdağ</a>"
            '<a href="/en/Commencis/commencis-cloud-camp-2027_50/">'
            "Commencis Commencis Cloud Camp 2027 Join us as we pave… Stajyer 25.11.2026 Hibrit</a>"
        )
        jobs = {j["url"].split("/")[-2]: j for j in radar.parse_youthall(html, "https://www.youthall.com/tr/")}
        g = jobs["summer-internship-2027-manufacturing-gebze-plant_117"]
        self.assertEqual(g["company"], "P&G")
        self.assertEqual(g["title"], "Summer Internship 2027: Manufacturing | Gebze Plant")
        a = jobs["ready-mix-concrete-long-term-intern-thrace_58"]
        self.assertEqual((a["company"], a["title"]), ("Akçansa", "Ready-Mix Concrete Long-Term Intern - Thrace"))
        c = jobs["commencis-cloud-camp-2027_50"]
        self.assertEqual((c["company"], c["title"]), ("Commencis", "Commencis Cloud Camp 2027"))

    def test_ntfy_payload_utf8(self):
        import os
        seen = {}

        class R:
            def read(self): return b""
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake_open(req, timeout=0):
            seen["url"], seen["body"] = req.full_url, json.loads(req.data.decode("utf-8"))
            return R()

        orig = radar.urllib.request.urlopen
        radar.urllib.request.urlopen = fake_open
        os.environ["NTFY_TOPIC"] = "test-konu-123"
        try:
            sent = radar.notify("Yeni staj ilanı: 1 eşleşme", "• [48] Üretim Stajyeri — Şirket", dry=False)
        finally:
            radar.urllib.request.urlopen = orig
            del os.environ["NTFY_TOPIC"]
        self.assertEqual(sent, ["ntfy"])
        self.assertEqual(seen["url"], "https://ntfy.sh/")
        self.assertEqual(seen["body"]["topic"], "test-konu-123")
        self.assertIn("Üretim", seen["body"]["message"])

    def test_scoring_order(self):
        jobs = {j["url"].split("/")[-2]: j for j in radar.parse_youthall(YOUTHALL_HTML, "https://www.youthall.com/")}
        gebze = radar.score_job(jobs["summer-internship-2027-manufacturing-gebze-plant_117"], self.prof)
        sales = radar.score_job(jobs["summer-internship-2027-sales_120"], self.prof)
        self.assertGreaterEqual(gebze[0], 35)
        self.assertLess(sales[0], 35)
        self.assertEqual(gebze[2], "yakin")

    def test_non_intern_dropped_and_internal_not_matched(self):
        j = radar.make_job("t", "Internal Audit Specialist", "https://a.b/1", snippet="internal controls")
        self.assertIsNone(radar.score_job(j, self.prof))
        j2 = radar.make_job("t", "Werkstudent Produktion", "https://a.b/2", country="DE")
        self.assertIsNotNone(radar.score_job(j2, self.prof))

    def test_url_canonical_strips_utm(self):
        self.assertEqual(radar.canon_url("https://a.b/x?utm_source=1&id=2#f"), "https://a.b/x?id=2")

    def test_rss_google_unwrap_and_careers(self):
        items = radar.fetch_rss({"feeds": [{"name": "Alert", "url": "https://alerts.test/f"}]})
        self.assertEqual(items[0]["url"], "https://example.com/staj1")
        self.assertNotIn("<b>", items[0]["title"])
        car = radar.fetch_careers({"sites": [{"name": "Firma", "url": "https://career.test/", "city": "Bursa"}]})
        self.assertEqual(len(car), 1)
        self.assertEqual(car[0]["url"], "https://career.test/kariyer/staj-programi")
        self.assertEqual(radar.classify(car[0], self.prof)[0], "bursa")

    def test_error_redacts_query(self):
        def boom(*a, **k):
            raise OSError("x")
        orig_open, orig_sleep = radar.urllib.request.urlopen, radar.time.sleep
        radar.urllib.request.urlopen, radar.time.sleep = boom, lambda s: None
        try:
            with self.assertRaises(RuntimeError) as cm:
                ORIG_GET("https://api.adzuna.com/v1/x?app_key=SECRET&app_id=ID", retries=0)
            self.assertNotIn("SECRET", str(cm.exception))
        finally:
            radar.urllib.request.urlopen, radar.time.sleep = orig_open, orig_sleep

    def test_full_run_and_second_run_no_duplicates(self):
        with tempfile.TemporaryDirectory() as d:
            data = Path(d) / "jobs.json"
            args = Namespace(dry_run=True, no_notify=False, force=True, data=str(data))
            src = ROOT / "config/sources.json"
            cfg = json.loads(src.read_text())
            cfg["rss"] = {"enabled": True, "feeds": [{"name": "Alert", "url": "https://alerts.test/f"}]}
            cfg["careers"] = {"enabled": True, "sites": [{"name": "Firma", "url": "https://career.test/", "city": "Bursa"}]}
            backup = src.read_text()
            src.write_text(json.dumps(cfg))
            try:
                self.assertEqual(radar.run(args), 0)
                s1 = json.loads(data.read_text())
                ids1 = set(s1["jobs"])
                self.assertTrue(ids1)
                self.assertEqual(s1["meta"]["sources"]["adzuna"]["status"], "atlandı")
                self.assertEqual(s1["meta"]["sources"]["arbeitnow"]["status"], "ok")
                self.assertNotIn("SECRET", json.dumps(s1))
                # eski (süresi geçmiş) ilan alınmamış olmalı
                self.assertFalse(any("eski-ilan" in j["url"] for j in s1["jobs"].values()))
                # Senior Software Engineer (staj değil) alınmamış olmalı
                self.assertFalse(any("Senior" in j["title"] for j in s1["jobs"].values()))
                # satış stajı düşük puanlı: saklanmamalı
                self.assertFalse(any("Sales" in j["title"] for j in s1["jobs"].values()))
                self.assertEqual(radar.run(args), 0)
                s2 = json.loads(data.read_text())
                self.assertEqual(set(s2["jobs"]), ids1)
                first = next(iter(s1["jobs"]))
                self.assertEqual(s2["jobs"][first]["first_seen"], s1["jobs"][first]["first_seen"])
            finally:
                src.write_text(backup)

    def test_pages_seed_silently_then_report_new(self):
        with tempfile.TemporaryDirectory() as d:
            cdir = Path(d) / "cfg"
            cdir.mkdir()
            (cdir / "profile.json").write_text(json.dumps(self.prof))
            off = {"enabled": False}
            (cdir / "sources.json").write_text(json.dumps({
                "youthall": off, "arbeitnow": off, "adzuna": off, "rss": off, "careers": off,
                "pages": {"enabled": True, "sites": [{"name": "Bölüm", "url": "https://pages.test/endustri/duyuru", "notify": "all",
                                                    "ajax": {"url": "/Home/_TestData", "data": {"insId": "1"}}}]},
                "watchlist": [{"name": "X", "url": "https://example.com"}]}))
            data = Path(d) / "jobs.json"
            args = Namespace(dry_run=True, no_notify=False, force=True, data=str(data), config_dir=str(cdir))
            self.assertEqual(radar.run(args), 0)
            s1 = json.loads(data.read_text())
            self.assertEqual(len(s1["announcements"]), 2)  # kısa/ana sayfa bağlantıları elendi
            self.assertFalse([e for e in s1["events"] if e["type"] == "duyuru"])  # ilk tarama sessiz
            PAGE_LINKS.append('<a href="/endustri/duyuru/3">Kariyer Günleri Etkinliği Hakkında</a>')
            try:
                self.assertEqual(radar.run(args), 0)
            finally:
                PAGE_LINKS.pop()
            s2 = json.loads(data.read_text())
            ev = [e for e in s2["events"] if e["type"] == "duyuru"]
            self.assertEqual(len(ev), 1)
            self.assertIn("Kariyer Günleri", ev[0]["title"])
            self.assertTrue(ev[0]["important"])
            self.assertEqual(s2["meta"]["watchlist"][0]["name"], "X")
            self.assertEqual(radar.run(args), 0)  # üçüncü tarama: tekrar olay üretmez
            self.assertEqual(len([e for e in json.loads(data.read_text())["events"] if e["type"] == "duyuru"]), 1)


if __name__ == "__main__":
    unittest.main()
