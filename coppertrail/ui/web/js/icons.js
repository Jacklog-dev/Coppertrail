// Stroke icons from web/icons/*.svg, inlined so they take the text colour (currentColor).
// The files are ours, shipped with the app; nothing here comes from data.

const cache = new Map();

function load(name) {
  if (!cache.has(name)) {
    cache.set(
      name,
      fetch(`icons/${name}.svg`)
        .then((r) => r.text())
        .then((text) => new DOMParser().parseFromString(text, "image/svg+xml").documentElement),
    );
  }
  return cache.get(name);
}

/** An inline SVG icon, `size` px square, coloured by the surrounding text colour. */
export function icon(name, size = 18) {
  const holder = document.createElement("span");
  holder.className = "icon";
  holder.style.display = "inline-flex";
  holder.style.width = holder.style.height = size + "px";
  holder.setAttribute("aria-hidden", "true");
  load(name).then((svg) => {
    const copy = document.importNode(svg, true);
    copy.setAttribute("width", size);
    copy.setAttribute("height", size);
    holder.replaceChildren(copy);
  });
  return holder;
}

/** Preload icons so they appear with the first render. */
export function preload(...names) {
  return Promise.all(names.map(load));
}
