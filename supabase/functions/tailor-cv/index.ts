// İlana özel İngilizce CV + ön yazı üretir (NVIDIA ücretsiz API) ve staj_cvs tablosuna yazar.
// Hemen döner; üretim arka planda sürer, site tabloyu okuyarak sonucu bekler.
// Gizli değişken: NVIDIA_API_KEY (Supabase → Edge Functions → Secrets)
import { createClient } from "npm:@supabase/supabase-js@2";

// [model, ek parametreler] — hızlı model önce, düşünme kapalı
const MODELS: [string, Record<string, unknown>][] = [
  ["nvidia/nemotron-3.5-lightning-30b-a3b", { chat_template_kwargs: { enable_thinking: false } }],
  ["openai/gpt-oss-20b", { reasoning_effort: "low" }],
];
const BUDGET_MS = 135000; // Supabase 150 sn'de işi keser
const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { ...cors, "Content-Type": "application/json" } });

async function pageText(url: string): Promise<string> {
  try {
    const r = await fetch(url, { signal: AbortSignal.timeout(6000), headers: { "User-Agent": "Mozilla/5.0" } });
    if (!r.ok) return "";
    return (await r.text())
      .replace(/<(script|style|noscript)[\s\S]*?<\/\1>/gi, " ")
      .replace(/<[^>]+>/g, " ")
      .replace(/&nbsp;/g, " ").replace(/&amp;/g, "&")
      .replace(/\s+/g, " ").trim().slice(0, 5000);
  } catch {
    return "";
  }
}

// E-posta ve telefonu NVIDIA'ya göndermeden gizle, sonra geri koy.
function redact(cv: string) {
  const found: string[] = [];
  const out = cv
    .replace(/[\w.+-]+@[\w-]+\.[\w.]+/g, (m) => (found.push(m), `[C${found.length - 1}]`))
    .replace(/\+?\d[\d\s()-]{8,}\d/g, (m) => {
      if (m.replace(/\D/g, "").length < 10) return m; // tarih aralıklarını telefon sanma
      found.push(m);
      return `[C${found.length - 1}]`;
    });
  return { out, restore: (s: string) => s.replace(/\[C(\d+)\]/g, (m, i) => found[+i] ?? m) };
}

function parseJson(text: string) {
  const t = text.replace(/<think>[\s\S]*?<\/think>/g, "");
  return JSON.parse(t.slice(t.indexOf("{"), t.lastIndexOf("}") + 1));
}

async function generate(prompt: string, started: number) {
  let lastErr = "";
  for (const [model, extra] of MODELS) {
    const left = BUDGET_MS - (Date.now() - started);
    if (left < 10000) break;
    try {
      const r = await fetch("https://integrate.api.nvidia.com/v1/chat/completions", {
        method: "POST",
        headers: { Authorization: `Bearer ${Deno.env.get("NVIDIA_API_KEY")}`, "Content-Type": "application/json" },
        body: JSON.stringify({ model, messages: [{ role: "user", content: prompt }], temperature: 0.4, max_tokens: 4000, ...extra }),
        signal: AbortSignal.timeout(Math.min(left, 80000)),
      });
      if (r.status === 401 || r.status === 403) throw new Error("NVIDIA_API_KEY geçersiz veya eksik.");
      if (!r.ok) { lastErr = `NVIDIA ${r.status}`; console.error(model, lastErr, (await r.text()).slice(0, 300)); continue; }
      const d = await r.json();
      const msg = d.choices?.[0]?.message || {};
      const res = parseJson(msg.content || "");
      console.log(model, "ok", Date.now() - started, "ms");
      return { ...res, model };
    } catch (e) {
      if (String(e).includes("NVIDIA_API_KEY")) throw e;
      lastErr = String(e);
      console.error(model, lastErr, Date.now() - started, "ms");
    }
  }
  throw new Error(`NVIDIA'dan yanıt alınamadı (${lastErr}). Biraz sonra tekrar dene.`);
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  const started = Date.now();

  const sb = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_ANON_KEY")!, {
    global: { headers: { Authorization: req.headers.get("Authorization") ?? "" } },
  });
  const { data: allowed } = await sb.rpc("staj_is_allowed");
  if (!allowed) return json({ error: "Erişim yok" }, 403);
  const { data: u } = await sb.auth.getUser();
  const email = u.user?.email;
  if (!email) return json({ error: "Giriş gerekli" }, 401);

  const { job, who } = await req.json();
  if (!job?.id || !job?.title) return json({ error: "İlan bilgisi eksik" }, 400);

  const { data: prof } = await sb.from("staj_profile").select("cv_en,cv_tr").maybeSingle();
  const raw = (prof?.cv_en || prof?.cv_tr || "").trim();
  if (!raw) return json({ error: "Önce Profil'den CV'ni (PDF) yükle." }, 400);
  const { out: cv, restore } = redact(raw);

  const row = { email, job_id: String(job.id), title: job.title, company: job.company || "", url: job.url || "" };
  const save = (f: Record<string, unknown>) =>
    sb.from("staj_cvs").upsert({ ...row, ...f, updated_at: new Date().toISOString() }, { onConflict: "email,job_id" });
  await save({ status: "pending", data: null, error: null });

  const work = (async () => {
    try {
      const full = job.url ? await pageText(job.url) : "";
      const prompt = [
        "Tailor my CV for this internship posting. Write everything in English.",
        who ? `About me (Turkish): ${who}` : "",
        `JOB:\nTitle: ${job.title}\nCompany: ${job.company || ""}\nLocation: ${job.location || job.country || ""}`,
        job.snippet ? `Summary: ${job.snippet}` : "",
        full ? `Posting page text (may be noisy):\n${full}` : "",
        `MY CV (placeholders like [C0] are contact details, keep them exactly as they are):\n${cv}`,
        `RULES:
- Never invent experience, skills, certificates or dates that are not in my CV. Put what the job asks for but my CV lacks into "missing".
- cv: reorder and rephrase to fit this job, relevant items first, use the job's keywords naturally, max one page. Markdown: "# Full Name", a contact line, "## Section" headings, "- " bullets.
- cover_letter: max 120 words.
- email_subject, email_body: short application email (3-4 sentences, CV attached, sign with my name).
- changes: 3 short bullets on what you changed.
Reply with ONLY a JSON object with keys: cv, cover_letter, email_subject, email_body, missing (array of strings), changes (array of strings).`,
      ].filter(Boolean).join("\n\n");
      const res = await generate(prompt, started);
      for (const k of ["cv", "cover_letter", "email_subject", "email_body"]) res[k] = restore(String(res[k] ?? ""));
      await save({ status: "done", data: res, error: null });
    } catch (e) {
      await save({ status: "error", error: String((e as Error).message || e) });
    }
  })();
  // @ts-ignore EdgeRuntime Supabase ortamında tanımlı
  EdgeRuntime.waitUntil(work);
  return json({ status: "pending" });
});
