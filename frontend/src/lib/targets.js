/* The challenge's test targets, explained for everyone. */
export const TARGETS = [
  {
    id: "barnard",
    label: "Barnard's Star",
    q: "Barnard's Star",
    emoji: "🏃",
    tagline: "The fastest-moving star in our sky",
    story:
      "Just 6 light-years away, Barnard's Star races across the sky faster than any other star. It covers the width of the full Moon in about 180 years.",
    watch: "Watch the bright dot in the middle creep upward (north) from one visit to the next.",
    band: 0,
  },
  {
    id: "epsindi",
    label: "Epsilon Indi B",
    q: "eps Ind B",
    emoji: "👯",
    tagline: "Two 'failed stars' orbiting each other",
    story:
      "Two brown dwarfs, balls of gas too small to shine like the Sun, circling each other 12 light-years away. They are cool, so they glow mostly in long-wavelength infrared.",
    watch: "The dot in the middle drifts down and to the left. It shows up best in the reddest colours.",
    band: 7,
  },
  {
    id: "wise0855",
    label: "WISE 0855",
    q: "WISE 0855",
    emoji: "🧊",
    tagline: "The coldest brown dwarf known: freezer-cold",
    story:
      "At about −25 °C, WISE 0855 is colder than a home freezer. It gives off almost no visible light, only long-wavelength infrared heat glow, so you need an infrared telescope like SPHEREx to see it.",
    watch: "In the reddest colours there is a faint dot in the middle, creeping to the right (west). It's missing in the bluer colours.",
    band: 7,
  },
  {
    id: "rwaur",
    label: "RW Aurigae",
    q: "RW Aur",
    emoji: "🐣",
    tagline: "A baby star that flickers",
    story:
      "A young star, only a few million years old, still wrapped in the gas and dust it formed from. Its brightness changes as clumps of dust pass in front of it.",
    watch: "Watch how bright the dot in the middle is from one visit to the next.",
    band: 0,
  },
  {
    id: "rdra",
    label: "R Draconis",
    q: "R Dra",
    emoji: "💓",
    tagline: "An old giant star that pulses",
    story:
      "A swollen red giant near the end of its life. It slowly 'breathes', getting brighter and dimmer about every 8 months.",
    watch: "The star in the middle changes brightness between visits.",
    band: 0,
  },
];

export function findTarget(name) {
  if (!name) return null;
  const n = name.toLowerCase();
  return TARGETS.find((t) => n.includes(t.label.toLowerCase()) || t.q.toLowerCase() === n ||
    (t.id === "epsindi" && n.includes("eps") && n.includes("ind")) ||
    (t.id === "wise0855" && n.includes("0855")) || (t.id === "rwaur" && n.includes("rw au")) ||
    (t.id === "rdra" && (n === "r dra" || n.includes("r draconis")))) || null;
}

export const GLOSSARY = {
  "RA / Dec": "The sky's address system, like longitude and latitude but for stars. RA = Right Ascension, Dec = Declination.",
  infrared: "Light with longer wavelengths than red, which our eyes can't see. Warm and cold objects glow in it, so it reveals dusty, cool and hidden things.",
  visit: "SPHEREx scans the whole sky every 6 months, so each spot gets a 'visit' twice a year. Each visit has many snapshots.",
  "brown dwarf": "A 'failed star': too big to be a planet, too small to burn like the Sun. Cool and dim, they glow mostly in infrared.",
  arcsecond: "A tiny angle: 1/3600 of a degree. The full Moon is about 1,800 arcseconds wide.",
  "proper motion": "How fast a star slides across the sky, usually in arcseconds per year. Most stars barely move; nearby ones move more.",
  Gaia: "A European Space Agency telescope that measured the positions and motions of almost 2 billion stars.",
  WISE: "An earlier NASA infrared telescope that mapped the whole sky (2010 onward).",
  detector: "SPHEREx has 6 detector arrays. Each sees a different range of infrared colours, from 0.75 µm (bluest) to 5 µm (reddest).",
  "102 colours": "SPHEREx splits infrared light into 102 narrow colour bands (planes), like a rainbow with 102 stripes.",
};
