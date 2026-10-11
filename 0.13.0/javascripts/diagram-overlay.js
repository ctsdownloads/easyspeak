// Click a rendered diagram to view it in an overlay window, scaled to fit the
// screen; the close button, a click anywhere or Escape restores it. Material
// renders Mermaid into a closed shadow root, so the diagram cannot be copied:
// the rendered element itself is moved into the window and moved back after.

function openDiagram(diagram) {
  const overlay = document.createElement("div");
  overlay.className = "diagram-overlay";
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-label", "Enlarged diagram");
  overlay.innerHTML =
    '<div class="diagram-overlay__bar">' +
    "<span>Click anywhere or press Esc to close</span>" +
    '<button type="button" aria-label="Close">×</button>' +
    "</div>" +
    '<div class="diagram-overlay__stage"></div>';
  const stage = overlay.lastElementChild;

  // Mermaid caps the SVG at its natural width, and in a narrow page it is
  // shrunk to the column, keeping its aspect ratio. The SVG is out of reach,
  // but a very wide host shows it at natural width, and the host's height is
  // then the natural height; the in-page ratio gives the natural width.
  const inPage = diagram.getBoundingClientRect();
  const placeholder = document.createComment("diagram");
  diagram.replaceWith(placeholder);
  stage.appendChild(diagram);
  document.body.appendChild(overlay);
  // The page underneath is inert while the window is open: no scrolling it.
  const pageOverflow = document.documentElement.style.overflow;
  document.documentElement.style.overflow = "hidden";
  diagram.style.width = "100000px";
  const height = diagram.getBoundingClientRect().height;
  const natural = { width: (height * inPage.width) / inPage.height, height };
  diagram.style.width = `${natural.width}px`;
  diagram.style.height = `${natural.height}px`;

  // Shrink to fit while the result stays readable; below that, show it at
  // natural size and let the stage scroll, which is a pan on a touch screen.
  const fit = () => {
    const padding = 2 * parseFloat(getComputedStyle(stage).padding);
    const room = {
      width: stage.clientWidth - padding,
      height: stage.clientHeight - padding,
    };
    const both = Math.min(room.width / natural.width, room.height / natural.height);
    diagram.style.zoom = both >= 0.75 ? both : 1;
  };
  fit();

  const close = () => {
    diagram.style.cssText = "";
    placeholder.replaceWith(diagram);
    overlay.remove();
    document.documentElement.style.overflow = pageOverflow;
    document.removeEventListener("keydown", onKey);
    window.removeEventListener("resize", fit);
  };
  const onKey = (event) => {
    if (event.key === "Escape") close();
  };
  overlay.addEventListener("click", (event) => {
    // Stop here, or the same click reaches the opener below and, with the
    // diagram already back in the page, opens it again.
    event.stopPropagation();
    close();
  });
  document.addEventListener("keydown", onKey);
  window.addEventListener("resize", fit);
}

document.addEventListener("click", (event) => {
  const diagram = event.target.closest(".mermaid");
  if (diagram && !diagram.closest(".diagram-overlay")) openDiagram(diagram);
});
