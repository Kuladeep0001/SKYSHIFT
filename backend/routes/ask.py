"""'Ask about this object': answers questions in plain language using ONLY the data SkyShift has loaded.

If an LLM is configured it writes the answer (any OpenAI-compatible API, e.g. Qwen):
    SKYSHIFT_LLM_URL    e.g. https://router.huggingface.co/v1   or   http://localhost:11434/v1 (Ollama)
    SKYSHIFT_LLM_MODEL  default Qwen/Qwen2.5-7B-Instruct          (Ollama: qwen2.5:7b)
    SKYSHIFT_LLM_KEY    API key (or HF_TOKEN); not needed for local Ollama
Without one, a built-in answerer replies from the same facts, so the feature always works.
Owner: Feature developer 2.
"""
from __future__ import annotations

import json
import os
import re

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..services.spherex import SESSION

router = APIRouter(prefix="/api/ask", tags=["assistant"])

LLM_KEY = os.environ.get("SKYSHIFT_LLM_KEY") or os.environ.get("HF_TOKEN") or ""
LLM_URL = os.environ.get("SKYSHIFT_LLM_URL") or ("https://router.huggingface.co/v1" if os.environ.get("HF_TOKEN") else "")
LLM_MODEL = os.environ.get("SKYSHIFT_LLM_MODEL", "Qwen/Qwen2.5-7B-Instruct")

SYSTEM = (
    "You are SkyShift's guide to NASA SPHEREx data. Answer the visitor's question in 2-5 short, friendly sentences "
    "a 12-year-old can follow. Use ONLY the facts in the CONTEXT JSON (measurements, catalogue entries, Wikipedia "
    "summary) plus general astronomy knowledge for explanations. Never invent numbers, names or discoveries. If the "
    "context does not contain the answer, say so and suggest which SkyShift button would show it. Units: arcseconds "
    "per year, light-years, microns."
)


class AskIn(BaseModel):
    question: str = Field(..., min_length=1, max_length=400)
    context: dict = Field(default_factory=dict)


@router.get("/status")
def status():
    return {"llm": bool(LLM_URL), "model": LLM_MODEL if LLM_URL else None,
            "fallback": "built-in answers from SkyShift's own data"}


@router.post("")
def ask(q: AskIn):
    ctx = _trim(q.context)
    if LLM_URL:
        try:
            r = SESSION.post(f"{LLM_URL.rstrip('/')}/chat/completions", timeout=40,
                             headers={"Authorization": f"Bearer {LLM_KEY}"} if LLM_KEY else {},
                             json={"model": LLM_MODEL, "temperature": 0.3, "max_tokens": 350,
                                   "messages": [{"role": "system", "content": SYSTEM},
                                                {"role": "user", "content": f"CONTEXT:\n{json.dumps(ctx)[:7000]}\n\nQUESTION: {q.question}"}]})
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"].strip()
            if text:
                return {"answer": text, "source": "llm", "model": LLM_MODEL}
        except Exception as e:
            fb = built_in(q.question, ctx)
            return {"answer": fb, "source": "built-in", "note": f"AI model unavailable ({str(e)[:80]})"}
    return {"answer": built_in(q.question, ctx), "source": "built-in"}


def _trim(ctx: dict) -> dict:
    """Keep the context small and free of big arrays."""
    out = {}
    for k, v in (ctx or {}).items():
        if isinstance(v, str):
            out[k] = v[:1500]
        elif isinstance(v, list):
            out[k] = v[:12]
        elif isinstance(v, (dict, int, float, bool)) or v is None:
            out[k] = v
    return out


def _has(q: str, *words: str) -> bool:
    return any(re.search(rf"\b{w}", q) for w in words)


def built_in(question: str, c: dict) -> str:
    """Rule-based answers from the loaded data (used when no AI model is configured)."""
    q = question.lower()
    name = c.get("name") or "this spot"
    det = c.get("details") or {}
    feats = c.get("features") or []
    finds = c.get("finds") or []
    visits = c.get("visits") or []
    movers = [f for f in finds if f.get("kind") == "mover"]

    if _has(q, "far", "distance", "light.year", "how close"):
        d = det.get("distance_ly")
        return (f"{name} is about {d:,.1f} light-years away (from {det.get('distance_source', 'Gaia/SIMBAD')}). Light from it "
                f"left about {d:,.0f} years ago." if d else
                f"I don't have a distance for {name}. Open the Object details card: if Gaia measured a parallax, the distance is there.")
    if _has(q, "move", "moving", "fast", "speed", "motion", "shift", "proper"):
        if movers:
            m = movers[0]
            return (f"{m.get('plain_english', '')} {m.get('verification', '')} Stars this close to us appear to drift across "
                    "the sky because they orbit the centre of our galaxy at a different speed than the Sun does.").strip()
        pm = c.get("pm_arcsec_yr")
        if pm:
            return (f"Catalogues say {name} moves {pm:.2f} arcseconds per year. Press 'Find moving or changing things' "
                    "to measure it from SPHEREx alone, or open the Time machine to see it move since 1950.")
        return "Press 'Find moving or changing things' and SkyShift will compare the visits and measure any motion."
    if _has(q, "water", "molecule", "spectrum", "dip", "gas", "co2", "methane", "ice", "rock", "mineral", "made of", "chemical"):
        seen = [f for f in feats if f.get("status") in ("likely", "possible")]
        if seen:
            parts = "; ".join(f"{f['name']}: {f['plain_english']}" for f in seen[:4])
            return (f"In its spectrum SkyShift sees: {parts} SPHEREx splits light into 102 colours; molecules absorb "
                    "specific colours, leaving dips. These are hints to follow up, not proof.")
        return ("No strong molecule signatures stand out in this spectrum yet. Click the star itself (not empty sky), "
                "and try the Spectral cube tab: dips below the smooth curve mean molecules like water or CO.")
    if _has(q, "bright", "dim", "variab", "flicker", "pulse", "change"):
        var = [f for f in finds if f.get("kind") == "variable"]
        if var:
            return f"{var[0].get('plain_english', '')} {var[0].get('verification', '')}".strip()
        return "Press 'Find moving or changing things' to check whether its brightness changed between visits, or look at the light curve."
    if _has(q, "new", "discover", "unknown", "found"):
        unk = [f for f in finds if "unknown" in (f.get("verification") or "").lower() or "not in gaia" in (f.get("verification") or "").lower()]
        if unk:
            return (f"{len(unk)} of the things SkyShift found here aren't in Gaia or WISE. Most such cases are glitches, "
                    "but some could be new. Report them on the Discovery board so others can take a look!")
        return "Everything SkyShift found here matches known objects. Try other spots: new brown dwarfs are often faint, red and moving."
    if _has(q, "spherex", "telescope", "satellite"):
        return ("SPHEREx is a NASA space telescope launched in 2025. Every six months it photographs the whole sky in "
                "102 infrared colours, so we can see how things change over time and what they're made of.")
    if _has(q, "when", "date", "how many", "picture", "photo", "visit"):
        if visits:
            v = ", ".join(f"{x.get('start')} ({x.get('n')} snapshots)" for x in visits[:6])
            return f"SPHEREx visited this spot {len(visits)} times: {v}. Each visit's snapshots are stacked into one clear picture."
    if _has(q, "what is", "what's", "tell me", "who", "type", "kind of"):
        if det.get("summary"):
            w = det.get("wikipedia")
            return det["summary"] + (f" {w.split('. ')[0]}." if w else "")
        if c.get("story"):
            return c["story"]
    base = det.get("summary") or c.get("story") or f"I know about {name}'s position, the SPHEREx visits and anything SkyShift measured."
    return base + " You can ask: how far away is it, how fast does it move, what is it made of, or did it change brightness?"
