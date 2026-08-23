"""Presentation-only offline replay data used when backend services are absent."""

from __future__ import annotations


TARGET_FEATURE = "checkout/promo"
CRASH_SITE = "packages/checkout/src/checkout.ts:24"
ROOT_CAUSE = "packages/pricing/src/promo.ts:12"
CRASH_PKG = "@acme/checkout"
CAUSE_PKG = "@acme/pricing"
THRESHOLD = 3

COMPLAINTS = [
    {"id":"c01","name":"Avery Kim","handle":"@averyk","avatar":"🟣","time":"20m","likes":8,"reposts":1,"relevant":True,"source":"campaign reply","feature":"checkout/promo","text":"SAVE20 promo code throws an error page at checkout"},
    {"id":"c02","name":"Mina Park","handle":"@minap","avatar":"🟢","time":"19m","likes":3,"reposts":0,"relevant":True,"source":"support ticket","feature":"checkout/promo","text":"Our 40k subscriber send used SAVE20 and the discount code crashed with a 500"},
    {"id":"c03","name":"Noah Jones","handle":"@noahj","avatar":"🔵","time":"18m","likes":31,"reposts":9,"relevant":True,"source":"community","feature":"checkout/promo","text":"free money glitch: SAVE20 promo applied it twice and it doubled"},
    {"id":"c04","name":"Priya Shah","handle":"@priyas","avatar":"🟠","time":"17m","likes":22,"reposts":5,"relevant":True,"source":"social post","feature":"checkout/promo","text":"SAVE20 coupon stacks infinitely, best bug before they patch it"},
    {"id":"c05","name":"Leo Martin","handle":"@leom","avatar":"🟡","time":"16m","likes":12,"reposts":2,"relevant":True,"source":"support chat","feature":"checkout/promo","text":"keep hitting apply on the SAVE20 promo for free money"},
    {"id":"c06","name":"Sofia Reed","handle":"@sofiareed","avatar":"🔴","time":"15m","likes":2,"reposts":0,"relevant":True,"source":"app review","feature":"ai/assistant","text":"chatbot says a 30-day return window but final sale has no refund, those policies contradict"},
    {"id":"c07","name":"Eli Brooks","handle":"@elib","avatar":"🟤","time":"14m","likes":1,"reposts":0,"relevant":True,"source":"session feedback","feature":"ai/assistant","text":"support bot quoted the 30-day return window, then final sale refused a refund"},
    {"id":"c08","name":"Nora Chen","handle":"@norac","avatar":"⚪","time":"13m","likes":4,"reposts":0,"relevant":True,"source":"idea portal","feature":"ai/assistant","text":"assistant claims 30-day returns while the final sale rule says no refund"},
    {"id":"c09","name":"Omar Diaz","handle":"@omard","avatar":"🟧","time":"12m","likes":0,"reposts":0,"relevant":True,"source":"survey","feature":"ai/assistant","text":"ai chat made up a 30-day return window that contradicts final sale no refund"},
    {"id":"c10","name":"Ivy Stone","handle":"@ivys","avatar":"🟪","time":"11m","likes":1,"reposts":0,"relevant":True,"source":"support ticket","feature":"checkout/payment","text":"payment keeps loading and never finishes"},
    {"id":"c11","name":"Theo Bell","handle":"@theob","avatar":"🟦","time":"10m","likes":2,"reposts":0,"relevant":True,"source":"community","feature":"checkout/payment","text":"pay button is spinning during card payment"},
    {"id":"c12","name":"Lina Wong","handle":"@linaw","avatar":"🟩","time":"9m","likes":1,"reposts":0,"relevant":True,"source":"app review","feature":"account","text":"account login loop is broken"},
    {"id":"c13","name":"Kai Patel","handle":"@kaip","avatar":"🟥","time":"8m","likes":0,"reposts":0,"relevant":True,"source":"support chat","feature":"account","text":"sign in keeps loading on my account"},
    {"id":"c14","name":"Zoe Miller","handle":"@zoem","avatar":"🟨","time":"7m","likes":0,"reposts":0,"relevant":True,"source":"session feedback","feature":"shipping","text":"shipping tracking link is broken with a 404"},
    {"id":"c15","name":"Maya Singh","handle":"@mayas","avatar":"🔷","time":"6m","likes":5,"reposts":0,"relevant":False,"source":"social post","feature":"noise","text":"checkout is great"},
    {"id":"c16","name":"Ben Ortiz","handle":"@beno","avatar":"🔶","time":"5m","likes":0,"reposts":0,"relevant":False,"source":"idea portal","feature":"noise","text":"please add dark mode"},
    {"id":"c17","name":"Aya Lewis","handle":"@ayal","avatar":"💠","time":"4m","likes":0,"reposts":0,"relevant":False,"source":"survey","feature":"noise","text":"wish the account had passkeys"},
    {"id":"c18","name":"Max Young","handle":"@maxy","avatar":"🔸","time":"3m","likes":0,"reposts":0,"relevant":False,"source":"community","feature":"noise","text":"@everyone 100x link in bio"},
    {"id":"c19","name":"Rae Davis","handle":"@raed","avatar":"🔹","time":"2m","likes":0,"reposts":0,"relevant":False,"source":"app review","feature":"noise","text":"the price display could be prettier"},
    {"id":"c20","name":"Sam Fox","handle":"@samf","avatar":"◻️","time":"0m","likes":7,"reposts":1,"relevant":False,"source":"campaign reply","feature":"noise","text":"my cart has emotional baggage but checkout is great"},
]


def build_trace(complaint_ids: list[str]) -> list[tuple[float, str, str, str]]:
    ids = ", ".join(complaint_ids[:5]) or "replay cluster"
    return [
        (0.0, "INGEST", f"qualifying complaints {ids}", "info"),
        (0.2, "TEMPORAL", "error rate stepped after deploy 94b112c · PR #1", "warn"),
        (0.2, "TELEMETRY", "promo.code=SAVE20 and status=500 join one TypeError cluster", "crash"),
        (0.2, "CALLGRAPH", "checkout.ts:24 → resolvePromo → promo.ts:12", "code"),
        (0.2, "GREPTILE CACHE", "captured P1 review fixture flagged the crash before users reported it", "warn"),
        (0.2, "CODE INTEL", "semantic/cache · review fixture supplies code context", "code"),
        (0.2, "FUSION", "evidence confidence: crash 0.95 · root cause 0.75", "cause"),
        (0.2, "PATCH", ROOT_CAUSE, "cause"),
        (0.2, "CITE", f"{CRASH_SITE} (higher confidence, wrong file)", "crash"),
    ]


REPLAY_DIAGNOSES = [
    {
        "id":"diag-sig-0001","signal_id":"sig-0001","feature":"checkout/promo","mode":"crash","confidence":0.75,
        "root_cause":f"{ROOT_CAUSE}: expired catalog entries collapse into a nullable result",
        "code_evidence":[
            {"file":"packages/pricing/src/promo.ts","line_start":12,"line_end":12,"source":"callgraph","role":"root-cause","confidence":0.75,"rationale":"resolvePromo returns null for an expired known code"},
            {"file":"packages/checkout/src/checkout.ts","line_start":24,"line_end":24,"source":"both","role":"crash-site","confidence":0.95,"rationale":"runtime frame and prior review agree here"}
        ],
        "log_evidence":[],"temporal":{},"degraded":[],
        "prior_review":{"pr":1,"severity":"P1","title":"Expired promos dereference null","location":CRASH_SITE,"addressed":False,"summary":"Review identified the nullable dereference before the incident."},
        "contradictions":["Agreement measures certainty, not causality; the highest-confidence location is the crash site."],
        "social_context":{"summary":"Users report two distinct promo failures: expired SAVE20 crashes while repeated application compounds discounts.","complaint_count":5,"distinct_authors":5,"families":["availability","abuse"],"artifacts":{"promoCodes":["SAVE20"],"httpStatus":["500"]},"exemplars":["SAVE20 throws an error page","Our 40k subscriber send crashed","Applied it twice and it doubled"]}
    },
    {
        "id":"diag-sig-0002","signal_id":"sig-0002","feature":"ai/assistant","mode":"degradation","confidence":0.78,
        "root_cause":"packages/support/prompts/support_agent.md:6-7: grounding fallback is disabled",
        "code_evidence":[{"file":"packages/support/prompts/support_agent.md","line_start":6,"line_end":7,"source":"review","role":"root-cause","confidence":0.78,"rationale":"prior review identified the missing grounding constraint"}],
        "log_evidence":[],"temporal":{"metric_anomalies":[]},"degraded":["No matching exception or metric drift."],
        "prior_review":{"pr":3,"severity":"P1","title":"Grounding fallback is disabled","location":"packages/support/prompts/support_agent.md:6-7","addressed":False,"summary":"Review saw the unsafe prompt before users did."},
        "contradictions":["The offline eval stayed at 0.94 because the customer question was absent from its curated set."],
        "social_context":{"summary":"The assistant's 30-day return answer contradicts the merchant's final-sale, no-refund rule.","complaint_count":4,"distinct_authors":4,"families":["correctness"],"artifacts":{"policyClaims":["30-day","final sale","no refund"]},"exemplars":["Chatbot says 30 days but final sale has no refund","Support bot contradicted final-sale policy","AI chat made up a return window"]}
    }
]
