// İlana özel CV + ön yazı + başvuru e-postası üretir (Claude API).
// Gizli değişken: ANTHROPIC_API_KEY (Supabase → Edge Functions → Secrets)
import Anthropic from "npm:@anthropic-ai/sdk";
import { createClient } from "npm:@supabase/supabase-js@2";

const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { ...cors, "Content-Type": "application/json" } });

const SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["cv", "cover_letter", "email_subject", "email_body", "missing", "changes"],
  properties: {
    cv: { type: "string", description: "Uyarlanmış CV, Markdown: '# Ad Soyad', iletişim satırı, '## Bölüm', '- madde'" },
    cover_letter: { type: "string" },
    email_subject: { type: "string" },
    email_body: { type: "string" },
    missing: { type: "array", items: { type: "string" } },
    changes: { type: "array", items: { type: "string" } },
  },
};

async function pageText(url: string): Promise<string> {
  try {
    const r = await fetch(url, { signal: AbortSignal.timeout(8000), headers: { "User-Agent": "Mozilla/5.0" } });
    if (!r.ok) return "";
    return (await r.text())
      .replace(/<(script|style|noscript)[\s\S]*?<\/\1>/gi, " ")
      .replace(/<[^>]+>/g, " ")
      .replace(/&nbsp;/g, " ").replace(/&amp;/g, "&")
      .replace(/\s+/g, " ").trim().slice(0, 15000);
  } catch {
    return "";
  }
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });

  const sb = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_ANON_KEY")!, {
    global: { headers: { Authorization: req.headers.get("Authorization") ?? "" } },
  });
  const { data: allowed } = await sb.rpc("staj_is_allowed");
  if (!allowed) return json({ error: "Erişim yok" }, 403);

  const { job, lang, who } = await req.json();
  if (!job?.title) return json({ error: "İlan bilgisi eksik" }, 400);

  const { data: prof } = await sb.from("staj_profile").select("cv_tr,cv_en").maybeSingle();
  const cv = ((lang === "en" ? prof?.cv_en : prof?.cv_tr) || prof?.cv_tr || prof?.cv_en || "").trim();
  if (!cv) return json({ error: "Önce CV sekmesine CV metnini kaydet." }, 400);

  const full = job.url ? await pageText(job.url) : "";
  const prompt = [
    `Staj ilanı için CV'mi uyarla. Çıktı dili: ${lang === "en" ? "İngilizce" : "Türkçe"}.`,
    who || "",
    "İLAN:",
    `Pozisyon: ${job.title}\nFirma: ${job.company || ""}\nKonum: ${job.location || job.country || ""}\nBağlantı: ${job.url || ""}`,
    job.snippet ? `Özet: ${job.snippet}` : "",
    full ? `İlan sayfasının metni (gürültü içerebilir):\n${full}` : "",
    "MEVCUT CV'M:",
    cv,
    "KURALLAR:",
    "- cv: CV'yi bu ilana göre yeniden düzenle; ilgili deneyim, proje ve becerileri öne al, ilandaki anahtar kelimeleri doğal kullan. En fazla 1 sayfa. Markdown: '# Ad Soyad', altında iletişim satırı, '## Bölüm' başlıkları, '- ' maddeler.",
    "- CV'de olmayan deneyim, beceri, sertifika veya tarih UYDURMA. İlanın isteyip CV'de olmayanları 'missing' listesine yaz.",
    "- cover_letter: en fazla 150 kelimelik ön yazı.",
    "- email_subject ve email_body: başvuru e-postası (4-5 cümle, CV'nin ekte olduğunu belirt, imza ad soyad).",
    "- changes: neyi neden değiştirdiğini 3-6 kısa madde.",
  ].filter(Boolean).join("\n\n");

  const client = new Anthropic({ apiKey: Deno.env.get("ANTHROPIC_API_KEY") });
  try {
    const res = await client.beta.messages.create({
      model: "claude-opus-5-5",
      max_tokens: 16000,
      betas: ["server-side-fallback-2026-07-01"],
      fallbacks: "default",
      output_config: { format: { type: "json_schema", schema: SCHEMA } },
      messages: [{ role: "user", content: prompt }],
    } as any);
    if (res.stop_reason === "refusal") return json({ error: "Claude bu isteği yanıtlamadı." }, 422);
    if (res.stop_reason === "max_tokens") return json({ error: "Yanıt yarıda kesildi, tekrar dene." }, 502);
    const text = res.content.find((b: any) => b.type === "text") as any;
    return json(JSON.parse(text.text));
  } catch (e) {
    if (e instanceof Anthropic.AuthenticationError) return json({ error: "ANTHROPIC_API_KEY geçersiz veya eksik." }, 500);
    if (e instanceof Anthropic.RateLimitError) return json({ error: "Çok fazla istek, biraz sonra dene." }, 429);
    if (e instanceof Anthropic.APIError) return json({ error: `Claude API hatası ${e.status}: ${e.message}` }, 502);
    return json({ error: String(e) }, 500);
  }
});
