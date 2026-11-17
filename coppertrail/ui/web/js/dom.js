// Tiny DOM helper. Data strings always go in as textContent, never as HTML.

/**
 * el("button", {class: "btn", text: "Reset", attrs: {title: "…"}, on: {click: fn}}, ...children)
 * Children may be nodes, strings (text nodes), null/false (skipped) or arrays.
 */
export function el(tag, opts = {}, ...children) {
  const node = document.createElement(tag);
  if (opts.class) node.className = opts.class;
  if (opts.text != null) node.textContent = String(opts.text);
  for (const [k, v] of Object.entries(opts.attrs ?? {})) {
    if (v === false || v == null) continue;
    node.setAttribute(k, v === true ? "" : String(v));
  }
  for (const [ev, fn] of Object.entries(opts.on ?? {})) node.addEventListener(ev, fn);
  append(node, children);
  return node;
}

export function append(node, children) {
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

/** Replace all children of `node`. */
export function replace(node, ...children) {
  node.replaceChildren();
  return append(node, children);
}

const SVG_NS = "http://www.w3.org/2000/svg";

/**
 * svg("path", {d: "M0 0 L10 10", class: "x"}, ...children): an SVG element. Colours go in as
 * CSS variables through `style` (for example {style: "stroke: var(--accent)"}), never as hex.
 */
export function svg(tag, attrs = {}, ...children) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v != null && v !== false) node.setAttribute(k, String(v));
  for (const child of children.flat(Infinity)) if (child) node.append(child);
  return node;
}
