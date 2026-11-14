/* A word with a plain-English explanation on hover/tap. */
import { GLOSSARY } from "../lib/targets.js";

export default function Term({ k, children }) {
  return <span className="term" tabIndex={0} title={GLOSSARY[k] || ""} data-tip={GLOSSARY[k] || ""}>{children || k}</span>;
}
