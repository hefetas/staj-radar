// İlana özel İngilizce CV + ön yazı + başvuru e-postası üretir (NVIDIA ücretsiz API).
// Gizli değişken: NVIDIA_API_KEY (Supabase → Edge Functions → Secrets)
import { createClient } from "npm:@supabase/supabase-js@2";

const MODELS = ["deepseek-ai/deepseek-v4.1-flash", "mistralai/mistral-large-4-1t-a52b"];
const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { ...cors, "Content-Type": "application/json" } });

async function pageText(url: string): Promise<string> {
  try {
    const r = await fetch(url, { signal: AbortSignal.timeout(8000), headers: { "User-Agent": "Mozilla/5.0" } });
    if (!r.ok) return "";
    return (await r.text())
      .replace(/<(script|style|noscript)[\s\S]*?<\/\1>/gi, " ")
      .replace(/<[^>]+>/g, " ")
      .replace(/&nbsp;/g, " ").replace(/&amp;/g, "&")
      .replace(/\s+/g, " ").trim().slice(0, 12000);
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

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });

  const sb = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_ANON_KEY")!, {
    global: { headers: { Authorization: req.headers.get("Authorization") ?? "" } },
  });
  const { data: allowed } = await sb.rpc("staj_is_allowed");
  if (!allowed) return json({ error: "Erişim yok" }, 403);

  const { job, who } = await req.json();
  if (!job?.title) return json({ error: "İlan bilgisi eksik" }, 400);

  const { data: prof } = await sb.from("staj_profile").select("cv_en,cv_tr").maybeSingle();
  const raw = (prof?.cv_en || prof?.cv_tr || "").trim();
  if (!raw) return json({ error: "Önce CV sekmesine İngilizce CV metnini kaydet." }, 400);
  const { out: cv, restore } = redact(raw);

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
- cv: reorder and rephrase to fit this job, bring relevant items first, use the job's keywords naturally, max one page. Markdown: "# Full Name", a contact line, "## Section" headings, "- " bullets.
- cover_letter: max 150 words.
- email_subject, email_body: short application email (4-5 sentences, mention the CV is attached, sign with my name).
- changes: 3-6 short bullets on what you changed and why.
Reply with ONLY a JSON object with keys: cv, cover_letter, email_subject, email_body, missing (array of strings), changes (array of strings).`,
  ].filter(Boolean).join("\n\n");

  let lastErr = "";
  for (const model of MODELS) {
    try {
      const r = await fetch("https://integrate.api.nvidia.com/v1/chat/completions", {
        method: "POST",
        headers: { Authorization: `Bearer ${Deno.env.get("NVIDIA_API_KEY")}`, "Content-Type": "application/json" },
        body: JSON.stringify({ model, messages: [{ role: "user", content: prompt }], temperature: 0.4, max_tokens: 4000 }),
        signal: AbortSignal.timeout(110000),
      });
      if (r.status === 401 || r.status === 403) return json({ error: "NVIDIA_API_KEY geçersiz veya eksik." }, 500);
      if (!r.ok) { lastErr = `NVIDIA ${r.status}`; continue; }
      const d = await r.json();
      const res = parseJson(d.choices[0].message.content);
      for (const k of ["cv", "cover_letter", "email_subject", "email_body"]) res[k] = restore(String(res[k] ?? ""));
      res.model = model;
      return json(res);
    } catch (e) {
      lastErr = String(e);
    }
  }
  return json({ error: `Yanıt alınamadı (${lastErr}). Biraz sonra tekrar dene.` }, 502);
});
