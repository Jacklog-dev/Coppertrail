// One popover at a time, 4 px under its anchor, kept inside the window.
// Closes on Escape and on a click outside both the popover and its anchor.

let current = null;

function place(node, anchor) {
  const a = anchor.getBoundingClientRect();
  const w = node.offsetWidth;
  const h = node.offsetHeight;
  let left = Math.min(a.left, window.innerWidth - w - 8);
  let top = a.bottom + 4;
  if (top + h > window.innerHeight - 8) top = Math.max(8, a.top - 4 - h); // flip above
  node.style.left = Math.max(8, left) + "px";
  node.style.top = top + "px";
}

/** Close the open popover. `notify=false` skips its onClose (used when re-rendering). */
export function closePopover(notify = true) {
  if (!current) return;
  const { node, onClose, cleanup } = current;
  current = null;
  cleanup();
  node.remove();
  if (notify) onClose?.();
}

/** openPopover(anchor, content, {className, onClose}) -> {close(), node} */
export function openPopover(anchor, content, { className = "popover", onClose } = {}) {
  closePopover(false);
  const node = document.createElement("div");
  node.className = className;
  node.setAttribute("role", "dialog");
  node.append(content);
  document.body.append(node);
  place(node, anchor);

  const onDown = (e) => {
    if (!node.contains(e.target) && !anchor.contains(e.target)) closePopover();
  };
  const onKey = (e) => {
    if (e.key === "Escape") closePopover();
  };
  const onResize = () => closePopover();
  document.addEventListener("mousedown", onDown, true);
  document.addEventListener("keydown", onKey);
  window.addEventListener("resize", onResize);
  const cleanup = () => {
    document.removeEventListener("mousedown", onDown, true);
    document.removeEventListener("keydown", onKey);
    window.removeEventListener("resize", onResize);
  };
  current = { node, onClose, cleanup };
  return { node, close: () => closePopover() };
}
