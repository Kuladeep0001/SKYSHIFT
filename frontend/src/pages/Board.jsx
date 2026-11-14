/* Discovery board: finds reported by visitors, voted on by everyone (citizen science). Owner: UI 1. */
import { useEffect, useState } from "react";
import { api, voterId } from "../lib/api.js";

const KIND = { mover: "🏃 moved", variable: "💡 changed brightness", appeared: "✨ appeared", vanished: "🌑 vanished", transient: "☄️ one-off spot", asteroid: "☄️ possible asteroid", other: "❓ other" };

export default function Board() {
  const [sort, setSort] = useState("top");
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const load = () => api.finds(sort).then(setData).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, [sort]);

  async function vote(f, v) {
    const value = f.my_vote === v ? 0 : v;
    const r = await api.vote(f.id, value);
    setData((d) => ({ ...d, finds: d.finds.map((x) => (x.id === f.id ? { ...x, score: r.score, my_vote: value } : x)) }));
  }

  return (
    <div className="about board">
      <section className="card">
        <h1>🔭 Discovery board</h1>
        <p>Things visitors spotted in SPHEREx data: stars that moved, sources that changed brightness, spots no catalogue lists.
          Vote <b>▲ worth a look</b> or <b>▼ probably nothing</b>. The most interesting finds rise to the top, ready for astronomers to follow up.
          Report your own from <b>Find things that moved</b> on any spot.</p>
        <div className="seg" role="group" aria-label="Sort">
          <button className={sort === "top" ? "on" : ""} onClick={() => setSort("top")}>Top</button>
          <button className={sort === "new" ? "on" : ""} onClick={() => setSort("new")}>Newest</button>
        </div>
        <span className="muted small"> {data ? `${data.total} finds so far` : ""}</span>
      </section>
      {err && <p className="err">{err}</p>}
      {data && !data.finds.length && <p className="hint center">No finds yet. Be the first: open a spot, press "Find moving or changing things", and report what you see.</p>}
      <div className="finds">
        {(data?.finds || []).map((f) => (
          <article key={f.id} className="card find">
            <div className="votes">
              <button className={f.my_vote === 1 ? "on" : ""} onClick={() => vote(f, 1)} aria-label="Worth a look">▲</button>
              <b>{f.score}</b>
              <button className={f.my_vote === -1 ? "on" : ""} onClick={() => vote(f, -1)} aria-label="Probably nothing">▼</button>
            </div>
            <div className="findBody">
              <div className="candHead"><b>{KIND[f.kind] || f.kind}</b>{f.target && <span className="muted"> near {f.target}</span>}
                {f.verification && <span className={`badge ${f.verification === "unmatched" ? "new" : "ok"}`}>{f.verification.replace("_", " ")}</span>}</div>
              <p>{f.summary}</p>
              {f.note && <p className="note">“{f.note}” — {f.nickname}</p>}
              <p className="mono small muted">RA {f.ra.toFixed(5)} Dec {f.dec.toFixed(5)} · {new Date(f.created * 1000).toLocaleDateString()} · reported by {f.nickname}</p>
              <a href={f.link}>Open in SkyShift ↗</a>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

export { voterId };
