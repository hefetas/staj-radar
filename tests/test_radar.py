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
              '<a href="/endustri/">Ana</a>']


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
                sales = [j for j in s1["jobs"].values() if "Sales" in j["title"]]
                self.assertTrue(sales and all(j["score"] < s1["meta"]["far_below"] for j in sales))  # silinmez, "uzak" sekmesine düşer
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

    def test_city_distance_and_regions(self):
        self.assertEqual(radar.locate("Nilüfer / Bursa"), ("nilufer", 0))
        self.assertEqual(radar.locate("Gebze, Kocaeli"), ("gebze", 180))
        self.assertEqual(radar.locate("Ankara")[1], 390)
        self.assertEqual(radar.locate("Türkiye"), (None, None))
        self.assertEqual([radar.region_for_km(k) for k in (0, 80, 250, 700, None)],
                         ["bursa", "yakin", "orta", "uzak", "belirsiz"])

    def test_summer_internship_scoring_and_eligibility(self):
        def job(title, loc, snippet=""):
            return radar.make_job("t", title, "https://x.test/" + title.replace(" ", "-"), "Firma", loc, "TR", snippet)
        good = job("Yaz Stajı - Üretim Planlama Stajyeri", "Bursa", "Excel, lean, fabrika")
        bad = job("Uzun Dönem Stajyer (Yüksek Lisans)", "Bursa", "master öğrencisi, tez")
        g, b = radar.score_job(good, self.prof), radar.score_job(bad, self.prof)
        self.assertEqual(g[2], "bursa")
        self.assertGreater(g[0], b[0] + 25)
        self.assertEqual(good["km"], 0)

    def test_supabase_state_roundtrip(self):
        import os
        calls = []
        store = {"data": {}}

        def fake_rpc(name, payload):
            calls.append(name)
            if name == "staj_get_state":
                return store["data"]
            store["data"] = payload["p_data"]

        orig = radar.supa_rpc
        radar.supa_rpc = fake_rpc
        env = {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_ANON_KEY": "anon", "STAJ_INGEST_TOKEN": "tok"}
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            with tempfile.TemporaryDirectory() as d:
                cdir = Path(d) / "cfg"
                cdir.mkdir()
                (cdir / "profile.json").write_text(json.dumps(self.prof))
                off = {"enabled": False}
                (cdir / "sources.json").write_text(json.dumps({
                    "youthall": {"enabled": True, "urls": ["https://www.youthall.com/tr/is-ilanlari/stajyer/"], "max_pages": 1},
                    "arbeitnow": off, "adzuna": off, "rss": off, "careers": off, "pages": off}))
                args = Namespace(dry_run=True, no_notify=True, force=True, data=str(Path(d) / "x.json"), config_dir=str(cdir))
                self.assertEqual(radar.run(args), 0)
                self.assertEqual(calls, ["staj_get_state", "staj_put_state"])
                self.assertTrue(store["data"]["jobs"])
                self.assertFalse((Path(d) / "x.json").exists())  # yerel dosyaya yazılmaz
                self.assertNotIn("tok", json.dumps(store["data"]))
        finally:
            radar.supa_rpc = orig
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_deadline_reminder_event_once(self):
        import datetime as dt
        d3 = (dt.datetime.now(dt.timezone(dt.timedelta(hours=3))).date() + dt.timedelta(days=3)).strftime("%d.%m.%Y")
        html = ('<a href="https://www.youthall.com/tr/acme/yaz-staji-uretim-planlama_77/"><div>Acme - Yaz Stajı Üretim Planlama</div>'
                f'<span>Stajyer</span> <span>{d3}</span> <span>Bursa</span></a>')
        radar.http_get = lambda url, headers=None, timeout=25, retries=2, data=None: html if "page=" not in url else "<html></html>"
        with tempfile.TemporaryDirectory() as d:
            cdir = Path(d) / "cfg"
            cdir.mkdir()
            (cdir / "profile.json").write_text(json.dumps(self.prof))
            off = {"enabled": False}
            (cdir / "sources.json").write_text(json.dumps({
                "youthall": {"enabled": True, "urls": ["https://www.youthall.com/tr/is-ilanlari/stajyer/"], "max_pages": 1},
                "arbeitnow": off, "adzuna": off, "rss": off, "careers": off, "pages": off, "companies": [{"name": "X"}]}))
            data = Path(d) / "jobs.json"
            args = Namespace(dry_run=True, no_notify=False, force=True, data=str(data), config_dir=str(cdir))
            radar.run(args)
            radar.run(args)
            s = json.loads(data.read_text())
            rem = [e for e in s["events"] if e["type"] == "hatirlatma"]
            self.assertEqual(len(rem), 1)
            self.assertIn("Son başvuru 3 gün", rem[0]["title"])
            self.assertEqual(s["meta"]["companies"][0]["name"], "X")

    def test_deadline_reminders_7_3_1(self):
        import datetime as dt
        tr_today = dt.datetime.now(dt.timezone(dt.timedelta(hours=3))).date()
        page = {"d": 7}

        def fake(url, headers=None, timeout=25, retries=2, data=None):
            if "page=" in url:
                return "<html></html>"
            dd = (tr_today + dt.timedelta(days=page["d"])).strftime("%d.%m.%Y")
            return ('<a href="https://www.youthall.com/tr/acme/yaz-staji-uretim-planlama_77/"><div>Acme - Yaz Stajı Üretim Planlama</div>'
                    f'<span>Stajyer</span> <span>{dd}</span> <span>Bursa</span></a>')
        radar.http_get = fake
        with tempfile.TemporaryDirectory() as d:
            cdir = Path(d) / "cfg"
            cdir.mkdir()
            (cdir / "profile.json").write_text(json.dumps(self.prof))
            off = {"enabled": False}
            (cdir / "sources.json").write_text(json.dumps({
                "youthall": {"enabled": True, "urls": ["https://www.youthall.com/tr/is-ilanlari/stajyer/"], "max_pages": 1},
                "arbeitnow": off, "adzuna": off, "rss": off, "careers": off, "pages": off}))
            data = Path(d) / "jobs.json"
            args = Namespace(dry_run=True, no_notify=False, force=True, data=str(data), config_dir=str(cdir))
            for days in (9, 7, 7, 4, 3, 3, 1, 1, 0):
                page["d"] = days
                radar.run(args)
            s = json.loads(data.read_text())
            titles = [e["title"] for e in s["events"] if e["type"] == "hatirlatma"]
            self.assertEqual(len(titles), 3, titles)  # 7, 3 ve 1 gün eşikleri birer kez

    def test_program_deadline_reminders_and_must_filter(self):
        import datetime as dt
        tr_today = dt.datetime.now(dt.timezone(dt.timedelta(hours=3))).date()
        page = {"d": 40}

        def fake(url, headers=None, timeout=25, retries=2, data=None):
            return ('<a href="https://x.gov.tr/duyurular/ulusal-staj-programi-2099-basvurulari/">Ulusal Staj Programı 2099 başvuruları başladı</a>'
                    '<a href="https://x.gov.tr/duyurular/personel-alimi-ilani-2099/">Karayolları personel alımı duyurusu</a>')
        radar.http_get = fake
        with tempfile.TemporaryDirectory() as d:
            cdir = Path(d) / "cfg"
            cdir.mkdir()
            (cdir / "profile.json").write_text(json.dumps(self.prof))
            off = {"enabled": False}
            wl = [{"name": "Test Programı", "url": "https://p.test/", "kind": "kamu", "pin": "yurtici",
                   "deadline": None}]
            data = Path(d) / "jobs.json"
            args = Namespace(dry_run=True, no_notify=False, force=True, data=str(data), config_dir=str(cdir))
            deadline = tr_today + dt.timedelta(days=30)
            wl[0]["deadline"] = deadline.isoformat()
            (cdir / "sources.json").write_text(json.dumps({
                "youthall": off, "arbeitnow": off, "adzuna": off, "rss": off, "careers": off,
                "pages": {"enabled": True, "sites": [{"name": "Kurum", "url": "https://x.gov.tr/duyurular/", "notify": "important", "must": ["staj"]}]},
                "watchlist": wl}))
            real = radar.utcnow
            try:
                for ahead in (0, 16, 17, 20, 23, 25, 27, 27, 28, 29, 30):  # saat ilerliyor, tarih sabit
                    radar.utcnow = lambda a=ahead: real() + dt.timedelta(days=a)
                    page["d"] = 30 - ahead
                    radar.run(args)
            finally:
                radar.utcnow = real
            s = json.loads(data.read_text())
            titles = [e["title"] for e in s["events"] if e["type"] == "hatirlatma"]
            self.assertEqual(len(titles), 4, titles)  # 14, 7, 3, 1 gün eşikleri birer kez
            anns = [a["title"] for a in s["announcements"].values()]
            self.assertTrue(all("staj" in a.lower() for a in anns), anns)  # 'must' süzgeci
            self.assertEqual(len(anns), 1, anns)

    def test_firm_slug_and_names(self):
        self.assertEqual(radar.firm_slug("Oyak Renault"), "oyak-renault")
        names = radar.company_names({}, {"companies": [{"name": "Bosch Bursa"}]})
        self.assertEqual(names["firma:bosch-bursa"], "Bosch Bursa (ilansız başvuru)")

    def test_followups_guarded_and_parsed(self):
        import os
        keys = ("SUPABASE_URL", "SUPABASE_ANON_KEY", "STAJ_INGEST_TOKEN")
        old = {k: os.environ.get(k) for k in keys}
        orig = radar.supa_rpc
        try:
            for k in keys:
                os.environ.pop(k, None)
            self.assertEqual(radar.followups(), [])
            os.environ.update({"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_ANON_KEY": "anon", "STAJ_INGEST_TOKEN": "tok"})
            radar.supa_rpc = lambda name, payload: [{"job_id": "firma:x", "days": 8, "kind": 7, "contact": "ik@x.com"}, "bozuk", {"yok": 1}]
            got = radar.followups()
            self.assertEqual(len(got), 1)
            self.assertEqual(got[0]["contact"], "ik@x.com")
        finally:
            radar.supa_rpc = orig
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_weekly_digest(self):
        import datetime as dt
        now = dt.datetime(2026, 11, 8, 16, 0, tzinfo=dt.timezone.utc)  # Pazar 19:00 TR
        today = dt.date(2026, 11, 8)
        jobs = {
            "a": {"id": "a", "title": "Yaz Stajı Üretim", "company": "Acme", "score": 60, "first_seen": "2026-11-05T10:00:00+00:00",
                  "deadline": "2026-11-10"},
            "b": {"id": "b", "title": "Eski ilan", "company": "Eski", "score": 50, "first_seen": "2026-10-01T10:00:00+00:00"},
            "c": {"id": "c", "title": "Alakasız", "company": "Z", "score": 5, "first_seen": "2026-11-06T10:00:00+00:00"},
        }
        subj, body = radar.build_digest(jobs, {"applied_week": 3, "applied_total": 5, "waiting": 4, "interview": 1, "known": 2}, today, 28, now)
        self.assertIn("haftalık", subj.lower())
        self.assertIn("Bu hafta 1 yeni uygun ilan", body)
        self.assertIn("2 gün: Yaz Stajı Üretim", body)
        self.assertIn("bu hafta 3, toplam 5", body)
        self.assertIn("Tanıdığın olan 2", body)

    def test_new_access_requests(self):
        import os
        keys = ("SUPABASE_URL", "SUPABASE_ANON_KEY", "STAJ_INGEST_TOKEN")
        old = {k: os.environ.get(k) for k in keys}
        orig = radar.supa_rpc
        try:
            for k in keys:
                os.environ.pop(k, None)
            self.assertEqual(radar.new_access_requests(), [])  # Supabase yoksa boş
            os.environ.update({"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_ANON_KEY": "anon", "STAJ_INGEST_TOKEN": "tok"})
            seen = []

            def fake_rpc(name, payload):
                seen.append((name, payload))
                return ["a@b.com", "c@d.com"]

            radar.supa_rpc = fake_rpc
            self.assertEqual(radar.new_access_requests(), ["a@b.com", "c@d.com"])
            self.assertEqual(seen[0], ("staj_take_new_requests", {"p_token": "tok"}))
        finally:
            radar.supa_rpc = orig
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_missing_token_fails_loudly(self):
        import os
        old = {k: os.environ.get(k) for k in ("SUPABASE_URL", "STAJ_INGEST_TOKEN")}
        os.environ["SUPABASE_URL"] = "https://x.supabase.co"
        os.environ.pop("STAJ_INGEST_TOKEN", None)
        try:
            with self.assertRaises(RuntimeError):
                radar.use_supabase()
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_german_ads_kept_and_tagged(self):
        j = radar.make_job("t", "Praktikum Produktionsplanung (m/w/d)", "https://x.test/de", "Werk GmbH", "Stuttgart", "DE",
                           "Sehr gute Deutschkenntnisse, Lean Manufacturing")
        score, reasons, region, tags = radar.score_job(j, self.prof)
        self.assertEqual(region, "yurtdisi")
        self.assertIn("almanca", tags)
        self.assertGreaterEqual(score, self.prof["far_below"])  # Almanca cezası yok; üretim planlama puan getirir


if __name__ == "__main__":
    unittest.main()
