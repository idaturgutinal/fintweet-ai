#!/usr/bin/env python3
"""FinTweet Tweet Validator - Gramer, yabanci kelime ekleri ve icerik dogrulugu kontrolu."""
import os
import json


VALIDATION_SYSTEM_PROMPT = """Sen bir Turkce dil ve icerik dogrulama asistanisin. Verilen tweet metnini 3 boyutta kontrol et:

## 1. GRAMER VE DIL KONTROLU
- Turkce yazim ve dilbilgisi hatalari
- Noktalama, buyuk/kucuk harf, Turkce karakter kullanimi (s, c, g, u, o, i, I)
- Tweet'in akici ve dogal Turkce olup olmadigi

## 2. YABANCI KELIME + TURKCE EK KURALLARI (COK ONEMLI)
Turkce'de yabanci kelimelerden sonra gelen ekler, kelimenin OKUNUSUNA gore eklenir, yazilisina gore DEGIL. Kesme isareti (') kullanilir.

KURALLAR VE ORNEKLER:
- Bitcoin -> "bitkoin" okunur -> Bitcoin'in, Bitcoin'e, Bitcoin'den (ince unlu)
- Ethereum -> "itiryum" okunur -> Ethereum'un, Ethereum'a, Ethereum'dan (kalin unlu)
- Blockchain -> "blokcheyn" okunur -> Blockchain'in, Blockchain'e, Blockchain'den (ince)
- ETF -> "i-ti-ef" okunur -> ETF'in, ETF'e, ETF'den (son harf okunusu "ef" = ince)
- SEC -> "sek" okunur -> SEC'in, SEC'e, SEC'den (ince)
- FOMC -> "ef-ou-em-si" okunur -> FOMC'nin, FOMC'ye (son ses "si" = ince)
- Fed -> "fed" okunur -> Fed'in, Fed'e, Fed'den (ince)
- Trump -> "tramp" okunur -> Trump'in, Trump'a, Trump'tan (kalin)
- Tether -> "tetir" okunur -> Tether'in, Tether'a, Tether'dan (kalin)
- DeFi -> "difay" okunur -> DeFi'nin, DeFi'ye (son ses "ay" = kalin)
- Solana -> "solana" okunur -> Solana'nin, Solana'ya, Solana'dan (kalin)
- Coinbase -> "koynbeys" okunur -> Coinbase'in, Coinbase'e (ince)
- Binance -> "bayninS" okunur -> Binance'in, Binance'e (ince)
- Stablecoin -> "steybilkoyn" okunur -> Stablecoin'in, Stablecoin'e (ince)
- WhatsApp -> "votsep" okunur -> WhatsApp'in, WhatsApp'a (kalin)
- YouTube -> "yutub" okunur -> YouTube'un, YouTube'a (kalin)
- Tweet -> "tivit" okunur -> Tweet'in, Tweet'e (ince)
- Halving -> "helving" okunur -> Halving'in, Halving'e (ince)
- Rally -> "reli" okunur -> Rally'nin, Rally'ye (ince)
- Bull -> "bul" okunur -> Bull'un (kalin)
- Bear -> "ber" okunur -> Bear'in (ince)

ONEMLI: p/c/t/k ile biten YABANCI kelimelerde yumusama OLMAZ: "Trump'a" (Trum'ba degil), "ETF'e" (ETV'e degil).

## 3. ICERIK DOGRULUGU
Kaynak icerik verilmisse:
- Tweet'teki bilgiler kaynakla tutarli mi?
- Yanlis rakam, yanlis yorum, uydurma bilgi var mi?
- Kaynakta olmayan bir iddia tweet'te geciyor mu?
- accuracy_score (0-100) ver

CIKTI FORMATI (sadece JSON, baska bir sey yazma):
{
    "grammar_ok": true/false,
    "accuracy_score": 0-100,
    "corrected_text": "duzeltilmis metin (degisiklik yoksa orijinal metin)",
    "issues": ["sorun 1", "sorun 2"]
}

Eger hic sorun yoksa: grammar_ok=true, accuracy_score=100, corrected_text=orijinal metin, issues=[]
Kaynak icerik verilmemisse accuracy_score=80 (varsayilan) ver."""


def validate_tweet(tweet_text, source_content=None):
    """Tweet metnini gramer, ek kurallari ve icerik dogrulugu acisindan kontrol et.

    Returns: {"grammar_ok": bool, "accuracy_score": int, "corrected_text": str, "issues": list}
    """
    try:
        import anthropic
    except ImportError:
        print("[VALIDATOR] anthropic modulu yok, atlaniyor")
        return {"grammar_ok": True, "accuracy_score": 80, "corrected_text": tweet_text, "issues": []}

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("[VALIDATOR] ANTHROPIC_API_KEY yok, atlaniyor")
        return {"grammar_ok": True, "accuracy_score": 80, "corrected_text": tweet_text, "issues": []}

    user_msg = "Tweet metni:\n%s" % tweet_text
    if source_content:
        user_msg += "\n\nKaynak icerik:\n%s" % str(source_content)[:1500]

    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            system=VALIDATION_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = msg.content[0].text.strip()

        # JSON parse
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            result = json.loads(raw[start:end])
            return {
                "grammar_ok": result.get("grammar_ok", True),
                "accuracy_score": result.get("accuracy_score", 80),
                "corrected_text": result.get("corrected_text", tweet_text),
                "issues": result.get("issues", []),
            }
    except Exception as e:
        print("[VALIDATOR] Hata: %s" % e)

    return {"grammar_ok": True, "accuracy_score": 80, "corrected_text": tweet_text, "issues": []}
