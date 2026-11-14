"""Discovery board: anyone can report an interesting find; others vote on it (citizen science).

Stored in a small SQLite file (data/finds.db). No accounts: a random browser id prevents double votes.
Owner: Integration lead.
"""
from __future__ import annotations

import math
import re
import sqlite3
import threading
import time
from collections import defaultdict, deque

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ..services.spherex import CACHE

router = APIRouter(prefix="/api/finds", tags=["discovery board"])
DB = CACHE.parent / "finds.db"
_lock = threading.Lock()
_recent: dict[str, deque] = defaultdict(deque)  # ip -> report times (rate limit)
MAX_REPORTS_PER_HOUR = 15


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(DB, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS finds (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created REAL, ra REAL, dec REAL, fov REAL, query_id TEXT,
        x REAL, y REAL, frame INTEGER, kind TEXT, verification TEXT, summary TEXT, note TEXT, nickname TEXT,
        target TEXT, score INTEGER DEFAULT 0)""")
    con.execute("CREATE TABLE IF NOT EXISTS votes (find_id INTEGER, voter TEXT, value INTEGER, PRIMARY KEY (find_id, voter))")
    return con


def _clean(s: str | None, n: int) -> str:
    s = re.sub(r"[\x00-\x1f\x7f]", " ", s or "").strip()
    return s[:n]


class FindIn(BaseModel):
    ra: float = Field(..., ge=0, lt=360)
    dec: float = Field(..., ge=-90, le=90)
    fov: float = Field(6, ge=2, le=30)
    query_id: str | None = Field(None, max_length=32)
    x: float | None = None
    y: float | None = None
    frame: int | None = None
    kind: str = Field("other", max_length=20)
    verification: str | None = Field(None, max_length=30)
    summary: str = Field("", max_length=600)
    note: str = Field("", max_length=280)
    nickname: str = Field("", max_length=40)
    target: str = Field("", max_length=80)
    voter: str = Field("", max_length=64)


class VoteIn(BaseModel):
    voter: str = Field(..., min_length=8, max_length=64)
    value: int = Field(..., ge=-1, le=1)


def _row(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["link"] = f"/?ra={d['ra']:.5f}&dec={d['dec']:.5f}&fov={d['fov']:g}"
    return d


@router.post("")
def report(f: FindIn, request: Request):
    """Report a find. Reports of the same spot (within 6″, same kind) are merged and count as a vote."""
    ip = request.client.host if request.client else "?"
    now = time.time()
    q = _recent[ip]
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= MAX_REPORTS_PER_HOUR:
        raise HTTPException(429, {"status": "error", "error": "too_many", "message": "Thanks! That's a lot of reports; please wait a while."})
    q.append(now)
    with _lock, _db() as con:
        cosd = max(0.01, abs(math.cos(math.radians(f.dec))))
        tol = 6 / 3600
        dup = con.execute("SELECT * FROM finds WHERE kind = ? AND ABS(dec - ?) < ? AND ABS(ra - ?) * ? < ?",
                          (f.kind, f.dec, tol, f.ra, cosd, tol)).fetchone()
        if dup:
            fid = dup["id"]
            merged = True
        else:
            cur = con.execute(
                "INSERT INTO finds (created, ra, dec, fov, query_id, x, y, frame, kind, verification, summary, note, nickname, target) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (now, f.ra, f.dec, f.fov, _clean(f.query_id, 32), f.x, f.y, f.frame, _clean(f.kind, 20),
                 _clean(f.verification, 30), _clean(f.summary, 600), _clean(f.note, 280), _clean(f.nickname, 40) or "anonymous",
                 _clean(f.target, 80)))
            fid = cur.lastrowid
            merged = False
        if f.voter:
            con.execute("INSERT OR REPLACE INTO votes VALUES (?,?,1)", (fid, _clean(f.voter, 64)))
            con.execute("UPDATE finds SET score = (SELECT COALESCE(SUM(value),0) FROM votes WHERE find_id = ?) WHERE id = ?", (fid, fid))
        row = con.execute("SELECT * FROM finds WHERE id = ?", (fid,)).fetchone()
    return {"status": "success", "merged_with_existing": merged, "find": _row(row)}


@router.get("")
def list_finds(sort: str = Query("top", pattern="^(top|new)$"), limit: int = Query(50, ge=1, le=200), voter: str = ""):
    order = "score DESC, created DESC" if sort == "top" else "created DESC"
    with _db() as con:
        rows = [_row(r) for r in con.execute(f"SELECT * FROM finds ORDER BY {order} LIMIT ?", (limit,))]
        if voter:
            mine = {r["find_id"]: r["value"] for r in con.execute("SELECT find_id, value FROM votes WHERE voter = ?", (voter,))}
            for r in rows:
                r["my_vote"] = mine.get(r["id"], 0)
        total = con.execute("SELECT COUNT(*) FROM finds").fetchone()[0]
    return {"total": total, "finds": rows}


@router.post("/{find_id}/vote")
def vote(find_id: int, v: VoteIn):
    """+1 = "worth a look", -1 = "probably nothing", 0 = remove my vote. One vote per browser."""
    with _lock, _db() as con:
        if not con.execute("SELECT 1 FROM finds WHERE id = ?", (find_id,)).fetchone():
            raise HTTPException(404, {"status": "error", "error": "not_found", "message": "No such find"})
        if v.value == 0:
            con.execute("DELETE FROM votes WHERE find_id = ? AND voter = ?", (find_id, v.voter))
        else:
            con.execute("INSERT OR REPLACE INTO votes VALUES (?,?,?)", (find_id, v.voter, v.value))
        con.execute("UPDATE finds SET score = (SELECT COALESCE(SUM(value),0) FROM votes WHERE find_id = ?) WHERE id = ?", (find_id, find_id))
        score = con.execute("SELECT score FROM finds WHERE id = ?", (find_id,)).fetchone()[0]
    return {"id": find_id, "score": score, "my_vote": v.value}
