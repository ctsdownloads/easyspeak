// Click a rendered diagram or a screenshot to view it in an overlay window,
// scaled to fit the screen; the close button, a click anywhere or Escape
// restores it. Material renders Mermaid into a closed shadow root, so the
// diagram cannot be copied: the element itself is moved into the window and
// moved back after.

// Mermaid caps the SVG at its natural width, and in a narrow page it is shrunk
// to the column, keeping its aspect ratio. The SVG is out of reach, but a very
// wide host shows it at natural width, and the host's height is then the
// natural height; the in-page ratio gives the natural width.
function diagramSize(diagram, inPage) {
  diagram.style.width = "100000px";
  const height = diagram.getBoundingClientRect().height;
  return { width: (height * inPage.width) / inPage.height, height };
}

// A diagram is shrunk to fit only while it stays readable; below that, it is
// shown at natural size and the stage scrolls, which is a pan on a touch
// screen. A screenshot always fits, but is never blown up past its pixels.
function diagramZoom(both) {
  return both >= 0.75 ? both : 1;
}

function screenshotZoom(both) {
  return Math.min(both, 1);
}

function openFigure(figure, label, naturalSize, zoomFor) {
  const overlay = document.createElement("div");
  overlay.className = "figure-overlay";
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-label", label);
  overlay.innerHTML =
    '<div class="figure-overlay__bar">' +
    "<span>Click anywhere or press Esc to close</span>" +
    '<button type="button" aria-label="Close">×</button>' +
    "</div>" +
    '<div class="figure-overlay__stage"></div>';
  const stage = overlay.lastElementChild;

  const inPage = figure.getBoundingClientRect();
  const placeholder = document.createComment("figure");
  figure.replaceWith(placeholder);
  stage.appendChild(figure);
  document.body.appendChild(overlay);
  // The page underneath is inert while the window is open: no scrolling it.
  const pageOverflow = document.documentElement.style.overflow;
  document.documentElement.style.overflow = "hidden";
  const natural = naturalSize(figure, inPage);
  figure.style.width = `${natural.width}px`;
  figure.style.height = `${natural.height}px`;

  const fit = () => {
    const padding = 2 * parseFloat(getComputedStyle(stage).padding);
    const room = {
      width: stage.clientWidth - padding,
      height: stage.clientHeight - padding,
    };
    const both = Math.min(room.width / natural.width, room.height / natural.height);
    figure.style.zoom = zoomFor(both);
  };
  fit();

  const close = () => {
    figure.style.cssText = "";
    placeholder.replaceWith(figure);
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
    // figure already back in the page, opens it again.
    event.stopPropagation();
    close();
  });
  document.addEventListener("keydown", onKey);
  window.addEventListener("resize", fit);
}

// Images inside a link, such as the video thumbnail, keep opening the link.
document.addEventListener("click", (event) => {
  if (event.target.closest(".figure-overlay")) return;
  const diagram = event.target.closest(".mermaid");
  if (diagram) {
    openFigure(diagram, "Enlarged diagram", diagramSize, diagramZoom);
    return;
  }
  const screenshot = event.target.closest(".md-content img:not(a img)");
  if (screenshot) {
    const size = (img) => ({ width: img.naturalWidth, height: img.naturalHeight });
    openFigure(screenshot, "Enlarged screenshot", size, screenshotZoom);
  }
});
