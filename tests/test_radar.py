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

    def test_daily_digest(self):
        import datetime as dt
        now = dt.datetime(2026, 11, 8, 13, 0, tzinfo=dt.timezone.utc)  # 16:00 TR
        today = dt.date(2026, 11, 8)
        jobs = {
            "a": {"id": "a", "title": "Yaz Stajı Üretim", "company": "Acme", "score": 60, "first_seen": "2026-11-08T05:00:00+00:00",
                  "deadline": "2026-11-10"},
            "b": {"id": "b", "title": "Eski ilan", "company": "Eski", "score": 50, "first_seen": "2026-10-01T10:00:00+00:00"},
            "c": {"id": "c", "title": "Alakasız", "company": "Z", "score": 5, "first_seen": "2026-11-08T06:00:00+00:00"},
        }
        progs = [{"name": "Ulusal Staj Programı", "deadline": "2026-12-14"}, {"name": "Eski Program", "deadline": "2026-10-01"}]
        subj, body = radar.build_digest(jobs, {"applied_week": 3, "applied_total": 5, "waiting": 4, "interview": 1, "known": 2}, today, 28, now, progs)
        self.assertIn("günlük", subj.lower())
        self.assertIn("Son 24 saatte 1 yeni uygun ilan", body)
        self.assertIn("Yaz Stajı Üretim — Acme", body)
        self.assertNotIn("Alakasız", body)
        self.assertIn("2 gün: Yaz Stajı Üretim", body)
        self.assertIn("Ulusal Staj Programı: son başvuruya 36 gün kaldı", body)
        self.assertNotIn("Eski Program", body)
        self.assertIn("bu hafta 3, toplam 5", body)
        # yeni ilan yokken de özet çıkar
        _, empty = radar.build_digest({"b": jobs["b"]}, {}, today, 28, now)
        self.assertIn("Son 24 saatte yeni uygun ilan yok", empty)

    def test_digest_sent_once_per_day_on_schedule_only(self):
        import os
        page = {}

        def fake(url, headers=None, timeout=25, retries=2, data=None):
            return ""
        radar.http_get = fake
        old = os.environ.get("SEND_DIGEST")
        try:
            with tempfile.TemporaryDirectory() as d:
                cdir = Path(d) / "cfg"
                cdir.mkdir()
                (cdir / "profile.json").write_text(json.dumps(self.prof))
                off = {"enabled": False}
                (cdir / "sources.json").write_text(json.dumps({"youthall": off, "arbeitnow": off, "adzuna": off, "rss": off, "careers": off, "pages": off}))
                data = Path(d) / "jobs.json"
                data.write_text(json.dumps({"meta": {}, "jobs": {"a": {"id": "a", "title": "Yaz Stajı", "company": "Acme", "url": "https://a.test/1",
                    "source": "x", "score": 60, "first_seen": "2026-01-01T00:00:00+00:00", "last_seen": "2999-01-01T00:00:00+00:00",
                    "location": "Bursa", "country": "TR", "region": "bursa", "km": 0, "reasons": [], "tags": []}}, "announcements": {}, "events": []}))
                args = Namespace(dry_run=True, no_notify=False, force=True, data=str(data), config_dir=str(cdir))
                os.environ.pop("SEND_DIGEST", None)
                radar.run(args)  # elle/schedule dışı: özet yok
                s = json.loads(data.read_text())
                self.assertFalse([e for e in s["events"] if e["title"] == "Günlük özet"])
                os.environ["SEND_DIGEST"] = "1"
                radar.run(args)
                radar.run(args)  # aynı gün ikinci kez: tekrar yok
                s = json.loads(data.read_text())
                self.assertEqual(len([e for e in s["events"] if e["title"] == "Günlük özet"]), 1)
        finally:
            if old is None:
                os.environ.pop("SEND_DIGEST", None)
            else:
                os.environ["SEND_DIGEST"] = old

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

    def test_jooble_needs_key_and_parses(self):
        import os
        old = os.environ.pop("JOOBLE_API_KEY", None)
        got = {}

        def fake(url, headers=None, timeout=25, retries=2, data=None, json_body=None):
            got.update(url=url, body=json_body)
            return json.dumps({"totalCount": 2, "jobs": [
                {"title": "<b>Üretim</b> Stajyeri", "location": "Bursa", "snippet": "Hat verimliliği", "company": "Acme",
                 "link": "https://jooble.org/desc/1?utm_source=x", "updated": "2026-11-01T00:00:00"},
                {"title": "Boş link", "link": ""}]})
        radar.http_get = fake
        try:
            with self.assertRaises(radar.SkipSource):
                radar.fetch_jooble({"queries": [{"keywords": "staj", "location": "Bursa"}]})
            os.environ["JOOBLE_API_KEY"] = "k123"
            out = radar.fetch_jooble({"queries": [{"keywords": "staj üretim", "location": "Bursa"}]})
        finally:
            radar.http_get = ORIG_GET
            os.environ.pop("JOOBLE_API_KEY", None)
            if old:
                os.environ["JOOBLE_API_KEY"] = old
        self.assertEqual(got["url"], "https://jooble.org/api/k123")
        self.assertEqual(got["body"]["keywords"], "staj üretim")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["title"], "Üretim Stajyeri")
        self.assertEqual(out[0]["company"], "Acme")
        self.assertNotIn("utm_", out[0]["url"])

    def test_remote_detection_reads_the_ad(self):
        d = radar.detect_remote
        self.assertEqual(d({"title": "Production Intern (Remote)", "location": "", "snippet": ""}), "uzaktan")
        self.assertEqual(d({"title": "Uzaktan Veri Analizi Stajyeri", "location": "İstanbul", "snippet": ""}), "uzaktan")
        self.assertEqual(d({"title": "Kalite Stajyeri", "location": "Bursa", "snippet": "Haftada 2 gün home office imkanı, hibrit çalışma"}), "hibrit")
        self.assertIsNone(d({"title": "Üretim Stajyeri", "location": "Bursa", "snippet": "Uzaktan çalışma yok, ofiste yüz yüze eğitim"}))
        self.assertIsNone(d({"title": "Intern", "location": "Berlin", "snippet": "Remote work is not possible for this role"}))
        self.assertEqual(d({"title": "Intern", "location": "Berlin", "snippet": "", "remote": True}), "uzaktan")
        self.assertIsNone(d({"title": "Online Marketing Praktikum", "location": "Berlin", "snippet": "Kampagnen"}))
        self.assertEqual(d({"title": "Intern", "location": "", "snippet": "This is a fully remote internship open to students anywhere."}), "uzaktan")

    def test_old_jobs_get_remote_tags_refreshed(self):
        radar.http_get = lambda *a, **k: ""
        try:
            with tempfile.TemporaryDirectory() as d:
                cdir = Path(d) / "cfg"
                cdir.mkdir()
                (cdir / "profile.json").write_text(json.dumps(self.prof))
                off = {"enabled": False}
                (cdir / "sources.json").write_text(json.dumps({k: off for k in ("youthall", "arbeitnow", "adzuna", "rss", "careers", "ats", "jooble", "pages")}))
                data = Path(d) / "jobs.json"
                job = {"id": "r", "title": "Remote Production Intern", "company": "X", "url": "https://r.test/1", "source": "x", "score": 60,
                       "first_seen": "2026-01-01T00:00:00+00:00", "last_seen": "2999-01-01T00:00:00+00:00", "location": "Berlin",
                       "country": "DE", "region": "yurtdisi", "km": None, "reasons": [], "tags": [], "snippet": ""}
                data.write_text(json.dumps({"meta": {"welcomed": True}, "jobs": {"r": job}, "announcements": {}, "events": []}))
                radar.run(Namespace(dry_run=True, no_notify=True, force=True, data=str(data), config_dir=str(cdir)))
                self.assertIn("uzaktan", json.loads(data.read_text())["jobs"]["r"]["tags"])
        finally:
            radar.http_get = ORIG_GET

    def test_remote_ads_ignore_duration_penalties(self):
        base = dict(company="X", snippet="Endüstri mühendisliği öğrencisi, üretim süreçleri. Uzun dönem part time staj.")
        remote = radar.make_job("t", "Uzaktan Üretim Stajyeri (Uzun Dönem)", "https://x.test/1", **base)
        onsite = radar.make_job("t", "Üretim Stajyeri (Uzun Dönem)", "https://x.test/2", **base)
        sr, rr, _, tr = radar.score_job(remote, self.prof)
        so, ro, _, to = radar.score_job(onsite, self.prof)
        self.assertIn("uzaktan", tr)
        self.assertNotIn("uzaktan", to)
        self.assertGreater(sr, so)
        self.assertFalse([r for r in rr if "uzun dönem" in r or "part time" in r])
        self.assertTrue([r for r in ro if "uzun dönem" in r])
        # sınıf şartı (4. sınıf) uzaktan ilanda da cezalı kalır
        r4 = radar.make_job("t", "Remote Production Intern", "https://x.test/3", "X", snippet="Only for 4. sınıf students")
        self.assertTrue([r for r in radar.score_job(r4, self.prof)[1] if "4. sınıf" in r])

    def test_german_ads_kept_and_tagged(self):
        j = radar.make_job("t", "Praktikum Produktionsplanung (m/w/d)", "https://x.test/de", "Werk GmbH", "Stuttgart", "DE",
                           "Sehr gute Deutschkenntnisse, Lean Manufacturing")
        score, reasons, region, tags = radar.score_job(j, self.prof)
        self.assertEqual(region, "yurtdisi")
        self.assertIn("almanca", tags)
        self.assertGreaterEqual(score, self.prof["far_below"])  # Almanca cezası yok; üretim planlama puan getirir

    def test_ats_fetchers_filter_interns(self):
        gh = json.dumps({"jobs": [
            {"title": "Production Intern", "absolute_url": "https://boards.greenhouse.io/x/jobs/1", "location": {"name": "Bursa, TR"}, "updated_at": "2026-11-01"},
            {"title": "Senior Engineer", "absolute_url": "https://boards.greenhouse.io/x/jobs/2", "location": {"name": "Berlin"}}]})
        lv = json.dumps([{"text": "Kalite Stajyeri", "hostedUrl": "https://jobs.lever.co/y/1", "categories": {"location": "Bursa"}, "descriptionPlain": "Kalite süreçleri"},
                         {"text": "Sales Manager", "hostedUrl": "https://jobs.lever.co/y/2", "categories": {}}])
        sr = json.dumps({"content": [{"id": "77", "name": "Praktikum Produktion", "releasedDate": "2026-11-02T10:00:00Z",
                                      "location": {"city": "Bursa", "country": "tr"}},
                                     {"id": "78", "name": "Controller", "location": {"city": "Bursa", "country": "tr"}}]})
        wk = json.dumps({"jobs": [{"title": "Summer Intern", "url": "https://apply.workable.com/z/j/1", "city": "Gebze", "country": "Turkey"},
                                  {"title": "Accountant", "url": "https://apply.workable.com/z/j/2"}]})
        seen = []

        def fake(url, headers=None, timeout=25, retries=2, data=None):
            seen.append(url)
            if "greenhouse" in url:
                return gh
            if "lever.co" in url:
                return lv
            if "smartrecruiters" in url:
                return sr
            if "workable" in url:
                return wk
            raise RuntimeError("beklenmeyen: " + url)
        radar.http_get = fake
        try:
            out = radar.fetch_ats({"sites": [
                {"name": "G", "type": "greenhouse", "id": "x"}, {"name": "L", "type": "lever", "id": "y"},
                {"name": "S", "type": "smartrecruiters", "id": "BoschGroup", "country": "TR"},
                {"name": "W", "type": "workable", "id": "z"}]})
        finally:
            radar.http_get = ORIG_GET
        self.assertEqual(sorted(j["title"] for j in out), ["Kalite Stajyeri", "Praktikum Produktion", "Production Intern", "Summer Intern"])
        self.assertTrue(all(j["trusted_intern"] for j in out))
        sr_job = [j for j in out if j["title"] == "Praktikum Produktion"][0]
        self.assertEqual(sr_job["url"], "https://jobs.smartrecruiters.com/BoschGroup/77")
        self.assertIn("Bursa", sr_job["location"])
        self.assertTrue(any("country=tr" in u for u in seen))

    def test_ats_one_site_failing_keeps_others(self):
        def fake(url, headers=None, timeout=25, retries=2, data=None):
            if "lever" in url:
                raise RuntimeError("404")
            return json.dumps({"jobs": [{"title": "Intern", "absolute_url": "https://g.test/1"}]})
        radar.http_get = fake
        try:
            out = radar.fetch_ats({"sites": [{"name": "L", "type": "lever", "id": "y"}, {"name": "G", "type": "greenhouse", "id": "x"}]})
            self.assertEqual(len(out), 1)
            with self.assertRaises(RuntimeError):
                radar.fetch_ats({"sites": [{"name": "L", "type": "lever", "id": "y"}]})
            with self.assertRaises(radar.SkipSource):
                radar.fetch_ats({"sites": []})
        finally:
            radar.http_get = ORIG_GET

    @staticmethod
    def _kariyer_card(href, title, company, city, model, wtype, sector, sponsored=False, more=""):
        """kariyer.net'in gerçek kart yapısı: öznitelikli div + içinde bağlantı (sponsorlu/ikon metinleriyle)."""
        return (f'<div data-test="ad-card" workModelText="{model}" workTypeText="{wtype}" sectorName="{sector}" '
                f'cityName="{city}" positionName="Stajyer" class="job-list-card-item"><div>'
                f'<a href="{href}" target="_blank" data-test="ad-card-item" class="k-ad-card">'
                + ("<span>Sponsorlu İlan</span>" if sponsored else "")
                + f'<div data-test="company-logo"><img data-test="company-image" alt="{company}"></div>'
                f'<div class="title-wrapper"><span>{title}</span> <i>accessible</i></div>'
                f'<span>{company}</span> <span>{city} {more}</span> <i>update</i> 3 gün</a></div></div>')

    def test_kariyer_parse_pagination_and_failure(self):
        c = self._kariyer_card
        yazaki = c("/is-ilani/yazaki-long-term-internship-4595088", "Long Term Internship (Spring Semester)",
                   "Yazaki Systems Technologies Turkey", "Bursa", "İş Yerinde", "Tam zamanlı", "Mühendislik Hizmetleri")
        tunca = c("/is-ilani/tunca-stajyer-muhendis-4556944", "Stajyer Mühendis", "TUNCA GROUP DANIŞMANLIK LİMİTED",
                  "Bursa", "Uzaktan / Remote", "Dönemsel", "Danışmanlık")
        sponsor = c("/is-ilani/korino-produksiyon-stajyeri-4591634", "Prodüksiyon Stajyeri", "Korino Medya", "İstanbul",
                    "İş Yerinde", "Tam zamanlı", "Medya", sponsored=True)
        faurecia = c("/is-ilani/faurecia-long-term-intern-4585485", "Long Term Intern", "Faurecia Otomotiv Sanayi",
                     "Bursa", "İş Yerinde", "Yarı zamanlı", "Otomotiv", more="+3 il daha")
        pages = {"p1": yazaki + tunca + sponsor, "p2": sponsor + faurecia, "p3": sponsor + faurecia}
        seen = []

        def fake(url, headers=None, timeout=25, retries=2, data=None):
            seen.append(url)
            key = "p3" if "cp=3" in url else "p2" if "cp=2" in url else "p1"
            return f"<html><body><script>var a='<a href=\"/is-ilani/x-1\">x</a>'</script>{pages[key]}</body></html>"
        radar.http_get = fake
        try:
            out = radar.fetch_kariyer({"urls": ["https://www.kariyer.net/is-ilanlari/bursa-stajyer"], "max_pages": 5})
            self.assertEqual(seen, ["https://www.kariyer.net/is-ilanlari/bursa-stajyer",
                                    "https://www.kariyer.net/is-ilanlari/bursa-stajyer?cp=2",
                                    "https://www.kariyer.net/is-ilanlari/bursa-stajyer?cp=3"])  # 3. sayfada yeni yok -> durur
            by = {j["url"].rsplit("-", 1)[-1]: j for j in out}
            self.assertEqual(len(out), 4)  # tekrar eden sponsorlu ilan bir kez sayılır
            y = by["4595088"]
            self.assertEqual((y["company"], y["location"], y["country"]), ("Yazaki Systems Technologies Turkey", "Bursa", "TR"))
            self.assertTrue(y["trusted_intern"])
            self.assertEqual(y["url"], "https://www.kariyer.net/is-ilani/yazaki-long-term-internship-4595088")
            self.assertEqual(by["4591634"]["title"], "Prodüksiyon Stajyeri")  # "Sponsorlu İlan" başlık sanılmaz
            self.assertEqual(by["4585485"]["title"], "Long Term Intern")  # "accessible"/"update" ikon metinleri elenir
            self.assertIn("+3 il daha", by["4585485"]["snippet"])
            t = by["4556944"]
            self.assertTrue(t["remote"])
            self.assertEqual(t["location"], "Uzaktan (Türkiye)")  # uzaktan ilan Bursa ilanı gibi puanlanmaz
            self.assertEqual(radar.detect_remote(t), "uzaktan")
            res = radar.score_job(y, self.prof)
            self.assertIsNotNone(res)
            self.assertEqual(res[2], "bursa")
            self.assertEqual(radar.score_job(t, self.prof)[2], "belirsiz")
            # sayfa yapısı değişirse (kart yok) sessizce 0 ilan dönmek yerine hata verir
            radar.http_get = lambda *a, **k: "<html><body>captcha</body></html>"
            with self.assertRaises(RuntimeError):
                radar.fetch_kariyer({"urls": ["https://www.kariyer.net/is-ilanlari/bursa-stajyer"]})
            with self.assertRaises(radar.SkipSource):
                radar.fetch_kariyer({"urls": []})
        finally:
            radar.http_get = ORIG_GET

    def test_kariyer_enabled_in_config_with_valid_city_urls(self):
        cfg = json.loads((ROOT / "config" / "sources.json").read_text(encoding="utf-8"))["kariyer"]
        self.assertTrue(cfg["enabled"])
        self.assertTrue(cfg["urls"][0].endswith("/bursa-stajyer"))  # Bursa önce
        self.assertTrue(all(u.startswith("https://www.kariyer.net/is-ilanlari/") and u.endswith("-stajyer") for u in cfg["urls"]))

    def test_quiet_digest_and_heartbeat(self):
        import datetime as dt
        now = dt.datetime(2026, 11, 8, 13, 0, tzinfo=dt.timezone.utc)
        today = dt.date(2026, 11, 8)
        old = {"b": {"id": "b", "title": "Eski", "company": "E", "score": 70, "first_seen": "2026-10-01T10:00:00+00:00"}}
        self.assertIsNone(radar.build_digest(old, {"waiting": 3}, today, 28, now, [], 50, True))  # haber yok -> sessiz
        mid = dict(old, c={"id": "c", "title": "Orta", "company": "O", "score": 40, "first_seen": "2026-11-08T05:00:00+00:00"})
        self.assertIsNone(radar.build_digest(mid, {}, today, 28, now, [], 50, True))  # yeni ama sana özel eşiğin altında
        top = dict(old, d={"id": "d", "title": "Üretim Stajı", "company": "Acme", "score": 62, "first_seen": "2026-11-08T05:00:00+00:00"})
        subj, body = radar.build_digest(top, {}, today, 28, now, [], 50, True)
        self.assertIn("Üretim Stajı — Acme", body)
        # program 14 günden uzaksa sessiz modda sayılmaz, yakınsa haber olur
        self.assertIsNone(radar.build_digest(old, {}, today, 28, now, [{"name": "P", "deadline": "2026-12-14"}], 50, True))
        _, pb = radar.build_digest(old, {}, today, 28, now, [{"name": "P", "deadline": "2026-11-20"}], 50, True)
        self.assertIn("P: son başvuruya 12 gün kaldı", pb)
        # eski (sessiz olmayan) davranış korunur
        self.assertIsNotNone(radar.build_digest(old, {}, today, 28, now))

    def test_quiet_run_sends_nothing_then_heartbeat(self):
        import os
        radar.http_get = lambda *a, **k: ""
        old_env = os.environ.get("SEND_DIGEST")
        sent = []
        orig_notify = radar.notify
        radar.notify = lambda subj, body, dry: sent.append(subj) or ["x"]
        try:
            with tempfile.TemporaryDirectory() as d:
                cdir = Path(d) / "cfg"
                cdir.mkdir()
                (cdir / "profile.json").write_text(json.dumps(dict(self.prof, digest_quiet=True, pick_min=50)))
                off = {"enabled": False}
                (cdir / "sources.json").write_text(json.dumps({"youthall": off, "arbeitnow": off, "adzuna": off, "rss": off, "careers": off, "ats": off, "pages": off}))
                data = Path(d) / "jobs.json"
                data.write_text(json.dumps({"meta": {"welcomed": True, "digest_day": radar.utcnow().astimezone(__import__("datetime").timezone(__import__("datetime").timedelta(hours=3))).date().isoformat()},
                    "jobs": {"a": {"id": "a", "title": "Yaz Stajı", "company": "Acme", "url": "https://a.test/1", "source": "x", "score": 60,
                    "first_seen": "2026-01-01T00:00:00+00:00", "last_seen": "2999-01-01T00:00:00+00:00", "location": "Bursa", "country": "TR",
                    "region": "bursa", "km": 0, "reasons": [], "tags": []}}, "announcements": {}, "events": []}))
                args = Namespace(dry_run=False, no_notify=False, force=True, data=str(data), config_dir=str(cdir))
                os.environ["SEND_DIGEST"] = "1"
                radar.run(args)
                self.assertEqual(sent, [])  # bugün zaten gönderilmiş / haber yok -> sessiz
                st = json.loads(data.read_text())
                st["meta"]["digest_day"] = "2026-01-01"  # uzun süredir hiçbir şey gitmedi
                data.write_text(json.dumps(st))
                radar.run(args)
                self.assertEqual(sent, ["Staj Radar çalışıyor"])
        finally:
            radar.notify = orig_notify
            radar.http_get = ORIG_GET
            if old_env is None:
                os.environ.pop("SEND_DIGEST", None)
            else:
                os.environ["SEND_DIGEST"] = old_env


if __name__ == "__main__":
    unittest.main()
