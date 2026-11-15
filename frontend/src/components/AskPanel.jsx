/* "Ask about this object": plain-language answers built only from the data SkyShift has loaded. */
import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api.js";
import { speak as speakAloud } from "../lib/voice.js";

const SUGGESTIONS = ["What is this?", "How far away is it?", "Why does it move?", "What is it made of?", "Did it change brightness?", "Could it be something new?"];

export default function AskPanel({ context, speak }) {
  const [log, setLog] = useState([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState(null);
  const end = useRef(null);
  useEffect(() => { api.askStatus().then(setStatus).catch(() => {}); }, []);
  useEffect(() => { end.current && end.current.scrollIntoView({ block: "nearest" }); }, [log]);
  useEffect(() => { setLog([]); }, [context?.name, context?.ra]);

  async function ask(q) {
    q = q.trim();
    if (!q || busy) return;
    setText("");
    setLog((l) => [...l, { who: "you", text: q }]);
    setBusy(true);
    try {
      const r = await api.ask(q, context);
      setLog((l) => [...l, { who: "sky", text: r.answer, source: r.source }]);
      if (speak) speakAloud(r.answer);
    } catch (e) {
      setLog((l) => [...l, { who: "sky", text: `Sorry, I couldn't answer that (${e.message}).` }]);
    } finally { setBusy(false); }
  }

  return (
    <section className="card askPanel" aria-label="Ask about this object">
      <h2>Ask about this object <small>{status ? (status.llm ? `AI: ${status.model}` : "answers from SkyShift's data") : ""}</small></h2>
      <div className="askLog" aria-live="polite">
        {!log.length && <p className="small muted">Ask anything about {context?.name || "this spot"}. Answers use only what SkyShift measured and what catalogues say, so they won't make things up.</p>}
        {log.map((m, i) => <p key={i} className={`msg ${m.who}`}>{m.text}{m.source === "built-in" && m.who === "sky" ? "" : ""}</p>)}
        {busy && <p className="msg sky muted">Thinking…</p>}
        <span ref={end} />
      </div>
      <div className="chips askChips">{SUGGESTIONS.map((s) => <button key={s} onClick={() => ask(s)} disabled={busy}>{s}</button>)}</div>
      <form className="search" onSubmit={(e) => { e.preventDefault(); ask(text); }}>
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Type a question…" aria-label="Your question" maxLength={400} />
        <button className="primary" disabled={busy || !text.trim()}>Ask</button>
      </form>
    </section>
  );
}
