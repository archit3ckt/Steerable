"""Decision layer for cheap routine calls: yes/no, classify, route, prioritize.

    from decide import decide
    d = decide("Is this email a sales lead?", ["yes", "no"], context=email_text)
    d = decide("Which team handles this?", {"billing": "Charges and refunds",
                                            "support": "Bugs and how-to questions"}, context=email_text)
    d.choice, d.confidence, d.backend

Options are a list, or a dict of option -> description. Descriptions make answers better:
Jev scores against them, and Haiku sees them in its prompt.

Backends, set with DECIDE_BACKEND in .env:
    jev    Jev by TypeSafe AI, a decision model: about 25x cheaper than Haiku, output free.
           Below JEV_MIN_CONFIDENCE it escalates to Haiku; if Haiku fails, Jev's answer stands.
    haiku  Claude Haiku 4.5.
    rules  No model. Keyword rules passed in by the caller, else the default option.

The default is jev whenever there's a way to reach it: JEV_API_KEY (in .env, or saved from the
dashboard's Connections page, scripts/ai_access.py) calls TypeSafe directly, and connected to
Steerable (STEERABLE_GATEWAY_URL) it goes through the gateway with the gateway token. Otherwise haiku.

Identical questions are cached in .cache/decide.json, so repeats cost nothing.
"""
import hashlib
import json
import sys
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass

from budget import check, cost_of, record, record_usage
from common import CACHE, env, log_run

CACHE_FILE = CACHE / "decide.json"
HAIKU = "claude-haiku-4-5"
JEV_ENDPOINT = "https://api.typesafe.ai/v1/systemone"


@dataclass
class Decision:
    choice: str
    confidence: float
    backend: str
    reason: str = ""


class Uncertain(Exception):
    """Jev answered, but below JEV_MIN_CONFIDENCE. Carries the answer in case nothing better comes."""

    def __init__(self, decision: Decision):
        super().__init__(f"confidence {decision.confidence:.2f} below threshold")
        self.decision = decision


def _key(question, options, context):
    raw = json.dumps([question, options, context], sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def _load_cache() -> dict:
    return json.loads(CACHE_FILE.read_text()) if CACHE_FILE.exists() else {}


def _jev_target() -> tuple[str, str] | None:
    """Where to ask Jev, and with which key: TypeSafe directly, or the Steerable gateway."""
    if env("JEV_API_KEY"):
        return env("JEV_ENDPOINT") or JEV_ENDPOINT, env("JEV_API_KEY")
    gateway = env("STEERABLE_GATEWAY_URL")
    if gateway and env("ANTHROPIC_API_KEY"):
        return gateway.rstrip("/") + "/jev", env("ANTHROPIC_API_KEY")
    return None


def _jev(question, options: dict, context, target: tuple[str, str] | None = None) -> Decision:
    target = target or _jev_target()
    if not target:
        raise RuntimeError("JEV_API_KEY not set")
    endpoint, key = target
    check()
    body = {"model": env("JEV_MODEL", "jev-latest"),
            "state": context or "(no further context)",
            "questions": {"decision": {"type": "choice", "instructions": question,
                                       "criteria": {k: v or None for k, v in options.items()}}}}
    req = urllib.request.Request(endpoint, data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {key}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Jev HTTP {e.code}: {e.read()[:200].decode(errors='replace')}") from None

    tokens = (data.get("usage") or {}).get("input_tokens") or len(json.dumps(body)) // 4  # estimate if absent
    record("decide", cost_of("jev", tokens, 0), "jev", tokens, 0)
    answer = data["answers"]["decision"]
    if answer.get("choice") not in options:
        raise RuntimeError(f"Jev returned an unknown option: {answer.get('choice')!r}")
    p = (answer.get("probabilities") or {}).get(answer["choice"], 0)
    decision = Decision(answer["choice"], float(answer.get("confidence", 0)), "jev",
                        f"p={p:.2f} ({data.get('model', 'jev')})")
    if decision.confidence < float(env("JEV_MIN_CONFIDENCE", "0.6")):
        raise Uncertain(decision)
    return decision


def _haiku(question, options: dict, context) -> Decision:
    check()
    schema = {
        "type": "object",
        "properties": {
            "choice": {"type": "string", "enum": list(options)},
            "confidence": {"type": "number"},
            "reason": {"type": "string"},
        },
        "required": ["choice", "confidence", "reason"],
        "additionalProperties": False,
    }
    listed = "\n".join(f"- {k}: {v}" if v else f"- {k}" for k, v in options.items())
    prompt = (f"{question}\n\nOptions:\n{listed}\n"
              "Pick exactly one option. confidence is 0 to 1. reason is at most 15 words.")
    if context:
        prompt += f"\n\n<context>\n{context}\n</context>"
    if not env("ANTHROPIC_API_KEY"):
        return _haiku_by_account(prompt, schema)
    import anthropic

    response = anthropic.Anthropic().messages.create(
        model=HAIKU,
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
        output_config={"format": {"type": "json_schema", "schema": schema}},
    )
    record_usage("decide", HAIKU, response.usage)
    data = json.loads(next(b.text for b in response.content if b.type == "text"))
    return Decision(data["choice"], float(data["confidence"]), "haiku", data["reason"])


def _haiku_by_account(prompt: str, schema: dict) -> Decision:
    """Haiku through Claude Code, for an engine signed in with a Claude account and no API key
    (the SDK can't use the account). Run from a neutral folder, so it doesn't load the
    company's CLAUDE.md for one small question."""
    proc = subprocess.run(["claude", "-p", prompt, "--model", "haiku", "--output-format", "json",
                           "--json-schema", json.dumps(schema), "--max-budget-usd", "0.05"],
                          capture_output=True, text=True, timeout=120, cwd=tempfile.gettempdir())
    try:
        out = json.loads(proc.stdout)
        data = out.get("structured_output") or json.loads(out["result"])
    except (json.JSONDecodeError, KeyError, TypeError):
        raise RuntimeError(f"Haiku (Claude account) gave no answer: {(proc.stderr or proc.stdout)[-200:]}") from None
    record("decide", float(out.get("total_cost_usd") or 0), "haiku", note="claude account")
    return Decision(data["choice"], float(data["confidence"]), "haiku", data.get("reason", ""))


def _rules(question, options: dict, context, rules) -> Decision:
    text = f"{question} {context}".lower()
    for keyword, option in (rules or {}).items():
        if keyword.lower() in text:
            return Decision(option, 0.6, "rules", f"matched '{keyword}'")
    return Decision(list(options)[-1], 0.0, "rules", "no rule matched, default option")


def decide(question: str, options: list[str] | dict[str, str], context: str = "",
           rules: dict[str, str] | None = None, use_cache: bool = True) -> Decision:
    """Pick one of `options`. `rules` maps keyword -> option for the no-model fallback.

    The last option is the safe default when nothing else works, so list it last
    (for example ["send", "hold"]).
    """
    options = dict(options) if isinstance(options, dict) else {o: "" for o in options}
    key = _key(question, options, context)
    cache = _load_cache() if use_cache else {}
    if key in cache:
        return Decision(**{**cache[key], "backend": cache[key]["backend"] + "(cached)"})

    backend = env("DECIDE_BACKEND") or ("jev" if _jev_target() else "haiku")
    chain = {"jev": ["jev", "haiku", "rules"], "haiku": ["haiku", "rules"]}.get(backend, ["rules"])
    decision, uncertain, errors = None, None, []
    for name in chain:
        if name == "rules" and uncertain:
            decision = uncertain  # a low-confidence model answer still beats keyword rules
            break
        try:
            if name == "jev":
                decision = _jev(question, options, context)
            elif name == "haiku":
                decision = _haiku(question, options, context)
            else:
                decision = _rules(question, options, context, rules)
            break
        except Uncertain as e:
            uncertain = e.decision
            errors.append(f"{name}: {e}")
        except Exception as e:  # not configured, over budget, API error: try the next backend
            errors.append(f"{name}: {e}")

    if decision.backend != "rules" and decision is not uncertain:  # retry unsure answers next time
        cache[key] = asdict(decision)
        CACHE_FILE.write_text(json.dumps(cache))
    log_run("decide", "ok", question=question[:80], choice=decision.choice,
            backend=decision.backend, fallbacks=errors)
    return decision


if __name__ == "__main__":
    # python scripts/decide.py "Question?" yes,no ["optional context"]
    q, opts = sys.argv[1], sys.argv[2].split(",")
    ctx = sys.argv[3] if len(sys.argv) > 3 else ""
    print(json.dumps(asdict(decide(q, opts, ctx))))
