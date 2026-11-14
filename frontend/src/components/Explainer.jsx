/* "What am I looking at?" in plain words. Changes with the target and the current view. */
import Term from "./Term.jsx";

export default function Explainer({ story, target, mode, math, det, channel, chWave, view, simple }) {
  let howBuilt;
  if (view === "compare") howBuilt = <>Left side: the <b>first</b> visit. Right side: the <b>last</b> visit. Drag the handle to compare. Anything that shifts or changes brightness is interesting.</>;
  else if (math === "first" || math === "prev") howBuilt = <>You're seeing each picture <b>minus the {math === "first" ? "first" : "previous"} one</b>. <b className="orange">Orange</b> = there now, <b className="blue">blue</b> = was there before. A <b>blue and orange pair</b> side by side means it <b>moved</b>. A lone blob means it changed brightness.</>;
  else if (math === "sum") howBuilt = <>All pictures are <b>added together</b>, so faint things show up better. Moving things get smeared, though.</>;
  else if (mode === "exposure") howBuilt = <>Each picture is <b>one single snapshot</b>, taken minutes to days apart. Good for catching fast things like asteroids.</>;
  else if (mode === "channel") howBuilt = <>Every picture uses the <b>same infrared colour</b> (plane {channel} of 102{chWave ? `, ${chWave}` : ""}), so brightness changes are a fair comparison.</>;
  else howBuilt = <>Each picture combines all snapshots from one <Term k="visit">visit</Term>. SPHEREx comes back to every spot about <b>every 6 months</b>{det === 7 ? ", here using only the reddest light (3.8–5 µm)" : det ? `, here using detector D${det}` : ""}.</>;

  return (
    <section className="card explainer">
      <h2>What you're looking at</h2>
      {story ? (
        <>
          <p className="storyHead"><span className="emoji">{story.emoji}</span> <b>{story.label}</b>: {story.tagline}</p>
          <p>{story.story}</p>
          <p className="watch">👀 <b>Look for:</b> {story.watch}</p>
        </>
      ) : target ? (
        <p>A patch of sky around <b>{target.name || "your coordinates"}</b>. Bright dots are stars and galaxies; dark is empty space.</p>
      ) : null}
      <p>{howBuilt}</p>
      {simple && (
        <ul className="keys">
          <li><i className="k cross" /> the spot you searched for</li>
          <li><i className="k gaia" /> known fast-moving stars (from the <Term k="Gaia">Gaia</Term> telescope)</li>
          <li><i className="k cand" /> things SkyShift found moving or changing</li>
        </ul>
      )}
      <p className="small muted">These are real pictures from NASA's SPHEREx space telescope, taken in <Term k="infrared">infrared</Term> light our eyes can't see. North is up.</p>
    </section>
  );
}
