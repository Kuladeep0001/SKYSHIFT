/* Accordion split in two: the header stays in the side column, the body appears in the detail area under the Show row.
   Only one panel is open at a time (the parent owns `open`). Opening a body scrolls it into view.
   Closed bodies stay mounted (hidden) so their state survives, unless keepMounted is false (the sky map needs a real size when opened). */
import { useEffect, useRef } from "react";

export function AccordionHead({ id, title, subtitle, open, onToggle }) {
  return (
    <div className={`accordion ${open ? "open" : ""}`}>
      <button type="button" className="accHead" aria-expanded={open} aria-controls={`accBody-${id}`}
        onClick={() => onToggle(open ? null : id)}>
        <span className="accTitle">{title}</span>
        {subtitle && <small className="accSub">{subtitle}</small>}
        <i className="accChevron" aria-hidden="true">{open ? "−" : "+"}</i>
      </button>
    </div>
  );
}

export function AccordionBody({ id, open, keepMounted = true, children }) {
  const ref = useRef(null);
  const first = useRef(true);

  useEffect(() => {
    if (first.current) { first.current = false; return; }
    if (open && ref.current) ref.current.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [open]);

  if (!keepMounted && !open) return null;
  return (
    <section ref={ref} id={`accBody-${id}`} className="detailBody" hidden={!open}>{children}</section>
  );
}
