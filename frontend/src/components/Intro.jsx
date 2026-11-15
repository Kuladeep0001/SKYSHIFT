/* Front page: full-screen SPHEREx picture with a welcome pop-up.
   Pressing the button grows the logo to its native 512px size at the centre of the screen, then fades into the Explore page.
   The background is never scaled, so nothing gets blurry. */
import { useEffect, useRef, useState } from "react";
import "../intro.css";

const FLY_MS = 900;   // logo grows
const FADE_MS = 500;  // page fades out to reveal the app

export default function Intro({ onBegin }) {
  const btn = useRef(null);
  const mark = useRef(null);
  const leaving = useRef(false);
  const [fly, setFly] = useState(null); // {left, top, size, dx, dy, scale, fade}

  useEffect(() => { btn.current?.focus(); }, []);

  const begin = () => {
    if (leaving.current) return;
    leaving.current = true;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduce || !mark.current) { onBegin(); return; }
    const r = mark.current.getBoundingClientRect();
    const vw = window.innerWidth, vh = window.innerHeight;
    const finalSize = Math.min(512, vh * 0.8); // never larger than the 512px source
    setFly({
      left: r.left, top: r.top, size: r.width,
      dx: vw / 2 - (r.left + r.width / 2),
      dy: vh / 2 - (r.top + r.height / 2),
      scale: finalSize / r.width,
    });
    setTimeout(onBegin, FLY_MS + FADE_MS);
  };

  useEffect(() => {
    const onKey = (e) => { if (e.key === "Enter") begin(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <div className={`introPage ${fly ? "leaving" : ""}`} style={{ backgroundImage: "url(/intro-bg.png)" }}>
      <div className="introShade" aria-hidden="true" />
      <div className="introDialog" role="dialog" aria-modal="true" aria-labelledby="introTitle">
        <img ref={mark} className="introMark" src="/logo-mark.png" alt="" aria-hidden="true"
          style={fly ? { visibility: "hidden" } : undefined} />
        <h1 id="introTitle">Welcome explorers</h1>
        <p>Look at the same patch of sky across time and see what changes. Real infrared images from NASA's SPHEREx mission.</p>
        <button ref={btn} className="introBtn" onClick={begin}>Press here to begin your journey</button>
      </div>
      {fly && (
        <img className="introFly" src="/logo-mark.png" alt="" aria-hidden="true"
          style={{
            left: fly.left, top: fly.top, width: fly.size, height: fly.size,
            "--dx": `${fly.dx}px`, "--dy": `${fly.dy}px`, "--s": fly.scale,
            animationDuration: `${FLY_MS}ms`,
          }} />
      )}
    </div>
  );
}
