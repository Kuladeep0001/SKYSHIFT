/* Guided tour: "Show me something amazing". Each step loads a target and a view, with a short story. */
import { useEffect } from "react";

export const TOUR = [
  { q: "Barnard's Star", view: "blink", det: 0, math: "none", title: "The fastest star in the sky",
    text: "Barnard's Star is just 6 light-years away. Watch the bright dot in the middle: between visits, six months apart, it creeps upward (north)." },
  { view: "timecolours", title: "Colour by date",
    text: "Each date gets its own colour. Stars that stayed put add up to white; Barnard's Star leaves a coloured trail because it moved." },
  { view: "timemachine", title: "76 years in a few seconds",
    text: "The same patch of sky on a 1950 glass photo, then 1991, 2000, 2010 and SPHEREx today. Follow Barnard's Star along the dashed line: it has travelled almost half the width of the full Moon." },
  { view: "blink", action: "detect", title: "SkyShift measures it",
    text: "SkyShift compares the visits by itself, measures the motion (about 10.4 arcseconds a year), and checks Gaia and SIMBAD: confirmed!" },
  { q: "eps Ind B", view: "blink", det: 7, title: "Two failed stars",
    text: "Epsilon Indi B is a pair of brown dwarfs: too small to shine like the Sun. They glow in the reddest infrared, drifting down and to the left." },
  { view: "planes", title: "What are they made of?",
    text: "The spectral cube stacks 102 infrared colours. The deep dips are water vapour in the brown dwarfs' atmospheres, plus carbon monoxide." },
  { q: "R Dra", view: "compare", det: 0, title: "A breathing giant",
    text: "R Draconis is an old red giant that swells and shrinks about every 8 months. Drag the slider and see its brightness change." },
  { q: "WISE 0855", view: "blink", det: 7, title: "Colder than a freezer",
    text: "WISE 0855 is the coldest brown dwarf known, about −25 °C. It's invisible in visible light, but SPHEREx catches its faint heat glow in the reddest colours." },
  { view: "blink", end: true, title: "Your turn!",
    text: "Pick any spot on the sky map, or type a star's name. Find something that moves and isn't in any catalogue? Report it on the Discovery board!" },
];

export default function Tour({ step, setStep, ready, auto, setAuto, speak }) {
  const s = TOUR[step];
  useEffect(() => {
    if (!s || !speak || !ready || !("speechSynthesis" in window)) return;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(new SpeechSynthesisUtterance(`${s.title}. ${s.text}`));
  }, [step, ready]);
  useEffect(() => {
    if (!auto || !ready || !s || s.end) return;
    const h = setTimeout(() => setStep(step + 1), 14000);
    return () => clearTimeout(h);
  }, [auto, ready, step]);
  if (!s) return null;
  return (
    <div className="tourCard" role="dialog" aria-label="Guided tour">
      <div className="tourTop"><span className="muted small">Tour · {step + 1} of {TOUR.length}</span>
        <button className="linkBtn" onClick={() => { window.speechSynthesis && window.speechSynthesis.cancel(); setStep(null); }} aria-label="End tour">✕</button></div>
      <h3>{s.title}</h3>
      <p>{ready ? s.text : "Loading…"}</p>
      <div className="row">
        <button onClick={() => setStep(Math.max(0, step - 1))} disabled={step === 0}>Back</button>
        {s.end ? <button className="primary" onClick={() => setStep(null)}>Start exploring</button>
          : <button className="primary" onClick={() => setStep(step + 1)}>Next</button>}
        <label className="tog small"><input type="checkbox" checked={auto} onChange={() => setAuto(!auto)} /> auto-play</label>
      </div>
    </div>
  );
}
