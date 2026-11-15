"""Built-in assistant used when no Gemini key is configured or Gemini is unavailable.

It understands a small set of everyday questions in English and Arabic and uses the
exact same user-bound tools as the Gemini path, so the security properties are identical.
"""
import re

from .tools import Toolbox

_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٫", "0123456789.")
_SEND = re.compile(
    r"(?:send|transfer|pay|give|حو[ّ]?ل|ارسل|أرسل|ادفع)\s+(?:(?:bhd|bd|د\.?ب)\s*)?(?P<amount>\d+(?:\.\d{1,3})?)"
    r"\s*(?:bhd|bd|dinars?|دينار|د\.?ب)?\s*(?:to|for|إلى|الى|ل)\s*@?(?P<to>[\w.]+)", re.I)
_SEND_REVERSED = re.compile(
    r"(?:send|transfer|pay|give)\s+@?(?P<to>[A-Za-z][\w.]*)\s+(?:(?:bhd|bd)\s*)?(?P<amount>\d+(?:\.\d{1,3})?)", re.I)


def _is_arabic(text: str) -> bool:
    return bool(re.search(r"[؀-ۿ]", text))


def reply(message: str, tools: Toolbox) -> str:
    text = message.translate(_AR_DIGITS).strip()
    low = text.lower()
    ar = _is_arabic(text)

    m = _SEND.search(text) or _SEND_REVERSED.search(text)
    if m:
        result = tools.call("propose_transfer", {"to": m["to"], "amount": m["amount"]})
        if "error" in result:
            return ("تعذّر تجهيز التحويل: " if ar else "I couldn't set that up: ") + result["error"]
        if ar:
            return f"جهّزت تحويل {result['amount_bhd']} د.ب إلى {result['to']} — راجع التفاصيل واضغط «تأكيد» للإرسال."
        return f"Ready to send {result['amount_bhd']} BHD to {result['to']} — check the details below and press Confirm."

    if re.search(r"balance|how much.*(have|left)|رصيد|كم.*(عندي|لدي)", low):
        accounts = tools.call("get_accounts", {})["accounts"]
        lines = [f"{a['name']}: {a['balance_bhd']} " + ("د.ب" if ar else "BHD") for a in accounts]
        return ("أرصدتك الآن:\n" if ar else "Here's what you have right now:\n") + "\n".join(lines)

    if re.search(r"spen[dt]|spending|where.*money|صرف|مصروف|انفق|أنفق", low):
        s = tools.call("get_spending_summary", {"days": 30})
        if not s["by_category"]:
            return "لم تصرف شيئاً خلال آخر 30 يوماً." if ar else "You haven't spent anything in the last 30 days."
        top = "\n".join(f"• {k}: {v}" for k, v in list(s["by_category"].items())[:5])
        head = (f"صرفت {s['spent_bhd']} د.ب خلال آخر 30 يوماً:\n" if ar
                else f"You spent {s['spent_bhd']} BHD in the last 30 days:\n")
        return head + top

    if re.search(r"transaction|recent|last|history|activity|معاملات|آخر|اخر|حركات", low):
        rows = tools.call("get_recent_transactions", {"limit": 5})["transactions"]
        if not rows:
            return "لا توجد معاملات بعد." if ar else "No transactions yet."
        lines = "\n".join(f"• {r['date']}  {r['title']}  {r['amount_bhd']}" for r in rows)
        return ("آخر معاملاتك:\n" if ar else "Your latest transactions:\n") + lines

    if ar:
        return ("أستطيع مساعدتك في: معرفة رصيدك، ملخّص مصروفاتك، آخر معاملاتك، "
                "أو تجهيز تحويل مثل «حوّل 5 إلى layla». لن يُرسل أي مبلغ قبل أن تضغط «تأكيد».")
    return ("I can tell you your balance, summarise your spending, show recent transactions, "
            "or prepare a transfer, for example \"send 5 to layla\". Nothing is sent until you press Confirm.")
