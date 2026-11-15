const background = document.createElement("div");
background.className = "spaceBackground";
background.setAttribute("aria-hidden", "true");
let seed = 2417;
const random = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
for (let layer = 0; layer < 2; layer++) {
  const depth = document.createElement("div");
  depth.className = layer ? "spaceDepth near" : "spaceDepth far";
  const stars = document.createElement("div");
  stars.className = layer ? "spaceStars twinkle" : "spaceStars";
  for (let i = 0; i < 48; i++) {
    const star = document.createElement("i");
    star.style.setProperty("--star-x", `${random() * 100}%`);
    star.style.setProperty("--star-y", `${random() * 100}%`);
    star.style.setProperty("--star-size", `${i % 11 === 0 ? 2 : i % 3 === 0 ? 1.5 : 1}px`);
    star.style.setProperty("--star-opacity", String(.15 + random() * .4));
    stars.appendChild(star);
  }
  depth.appendChild(stars);
  background.appendChild(depth);
}
document.body.prepend(background);
const pause = () => document.documentElement.toggleAttribute("data-space-paused", document.hidden);
document.addEventListener("visibilitychange", pause);
pause();
if (import.meta.hot) import.meta.hot.dispose(() => {
  background.remove();
  document.removeEventListener("visibilitychange", pause);
  document.documentElement.removeAttribute("data-space-paused");
});
