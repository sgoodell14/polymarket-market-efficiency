/* Preview references from either method page without moving the reader. */
(() => {
  const pages = ["Clustering.html", "PCA.html", "NaiveBayes.html", "DecTrees.html"];
  const currentPage = location.pathname.split("/").pop();
  const main = document.querySelector("main");
  if (!pages.includes(currentPage) || !main) return;
  // Word headings may include a visible CSV suffix on their download links.
  function preparationTitle(node) {
    return node?.textContent.replace(/\s+/g, ' ').trim().replace(/\s*\(CSV\)$/i, '');
  }
  // Keep all data in the page; reveal additional prepared features on demand.
  function setSampleExpanded(button, expanded) {
    const table = button.closest('.table-scroll').querySelector('table.table-nb-sample');
    const rows = [...table.tBodies].flatMap(body => [...body.rows]);
    rows.forEach((row, index) => { row.hidden = !expanded && index >= 5; });
    button.setAttribute('aria-expanded', String(expanded));
    button.textContent = expanded ? 'Show first 5 rows' : `Show all ${rows.length} rows`;
    button.nextElementSibling.textContent = `Showing ${expanded ? rows.length : 5} of ${rows.length} rows`;
  }
  for (const table of main.querySelectorAll('table.table-nb-sample')) {
    const container = table.closest('.table-scroll');
    if (preparationTitle(container?.previousElementSibling) !== 'Prepared model inputs') continue;
    const rows = [...table.tBodies].flatMap(body => [...body.rows]);
    if (rows.length <= 5) continue;
    const controls = document.createElement('div');
    controls.className = 'sample-table-controls';
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'sample-table-toggle';
    const status = document.createElement('span');
    status.setAttribute('aria-live', 'polite');
    controls.append(button, status);
    container.append(controls);
    setSampleExpanded(button, false);
  }
  // Delegation also supports tables cloned into the reference preview dialog.
  document.addEventListener('click', event => {
    const button = event.target.closest('.sample-table-toggle');
    if (button) setSampleExpanded(button, button.getAttribute('aria-expanded') !== 'true');
  });
  // Preserve text flow around floated figures, starting below their headings.
  // Measure the rendered heading space so wrapped titles and font changes fit.
  for (const figure of main.querySelectorAll(".method-figure-float")) {
    const paragraph = figure.nextElementSibling;
    const image = figure.querySelector("img");
    if (!image || !paragraph?.matches("p")) continue;
    const alignProse = () => {
      const offset = matchMedia("(min-width: 768px)").matches
        ? Math.max(0, image.getBoundingClientRect().top - paragraph.getBoundingClientRect().top)
        : 0;
      paragraph.style.setProperty("--figure-heading-offset", `${offset}px`);
    };
    new ResizeObserver(alignProse).observe(figure);
    window.addEventListener("resize", alignProse);
    image.addEventListener("load", alignProse);
    document.fonts.ready.then(alignProse);
    alignProse();
  }
  // Keep the overview plots equally tall even when notebook exports change size.
  const overviewPair = main.querySelector('#figure-11')?.closest('.method-figure-pair');
  if (overviewPair) {
    const plots = [...overviewPair.querySelectorAll('.method-figure img')];
    const matchPlotHeights = () => {
      if (plots.length !== 2 || plots.some(image => !image.naturalWidth)) return;
      overviewPair.style.gridTemplateColumns = plots.map(image =>
        `minmax(0, ${image.naturalWidth / image.naturalHeight}fr)`
      ).join(' ');
    };
    plots.forEach(image => image.addEventListener('load', matchPlotHeights));
    matchPlotHeights();
  }
  // Size paired plot thumbnails against the table, including font/width changes.
  for (const pair of main.querySelectorAll(".method-table-figure-pair")) {
    const table = pair.querySelector(".method-table-panel table");
    if (!table) continue;
    const matchTableHeight = () => pair.style.setProperty(
      "--paired-table-height", `${table.getBoundingClientRect().height}px`
    );
    new ResizeObserver(matchTableHeight).observe(table);
    matchTableHeight();
  }
  const captionPattern = /^(Figure|Table)\s+(\d+)\s*:/i;
  const referencePattern = /\b(Figure|Table)\s+(\d+)\b/gi;
  const keyFor = (kind, number) => `${kind.toLowerCase()}-${number}`;
  const items = new Map();

  function collect(root, page) {
    for (const caption of root.querySelectorAll(".method-caption, p")) {
      if (caption.matches("p") && caption.querySelector(".method-caption")) continue;
      const match = caption.textContent.trim().match(captionPattern);
      if (!match) continue;
      const [, kind, number] = match;
      const key = keyFor(kind, number);
      if (items.has(key)) continue;
      caption.dataset.referenceCaption = "true";
      items.set(key, { kind: kind.toLowerCase(), number, caption, page });
      const figure = caption.closest(".method-figure");
      const imageLinks = figure?.querySelectorAll("a.figure-preview") || [];
      imageLinks.forEach((imageLink, panelIndex) => {
        imageLink.dataset.reference = key;
        imageLink.dataset.panel = String(panelIndex);
        const panelTitle = imageLink.closest('.method-figure-panel')?.querySelector('.method-panel-title')?.textContent.trim();
        const hasSource = figure.classList.contains('source-on-preview');
        imageLink.setAttribute("aria-label", `Enlarge Figure ${number}${panelTitle ? ', ' + panelTitle : ''} with its title, caption${hasSource ? ', and source' : ''}`);
      });
    }
  }
  collect(main, currentPage);

  for (const link of main.querySelectorAll("a[href]")) {
    const url = new URL(link.href, location.href);
    if (url.origin === location.origin && url.pathname.endsWith(".csv")) {
      link.download = url.pathname.split("/").pop();
    }
  }

  const dialog = document.createElement("dialog");
  dialog.className = "reference-preview";
  dialog.setAttribute("aria-labelledby", "reference-preview-title");
  dialog.innerHTML = '<header class="reference-preview-header"><h2 id="reference-preview-title"></h2><button type="button" aria-label="Close preview" autofocus>Close ×</button></header><div class="reference-preview-content"></div>';
  document.body.append(dialog);
  const title = dialog.querySelector("h2");
  const content = dialog.querySelector(".reference-preview-content");
  dialog.querySelector("button").addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", event => {
    if (event.target !== dialog) return;
    const box = dialog.getBoundingClientRect();
    if (event.clientX < box.left || event.clientX > box.right ||
        event.clientY < box.top || event.clientY > box.bottom) dialog.close();
  });
  dialog.addEventListener("close", () => document.body.classList.remove("reference-preview-open"));

  function cloneForPreview(node) {
    const clone = node.cloneNode(true);
    clone.removeAttribute("id");
    for (const element of clone.querySelectorAll("[id]")) element.removeAttribute("id");
    return clone;
  }

  function previewTable(item) {
    let start = item.caption.previousElementSibling;
    if (!start?.matches("table, .table-scroll")) {
      content.append(cloneForPreview(item.caption));
      return;
    }
    // Preparation samples contain two panels under one numbered caption.
    const preparedTitle = start.previousElementSibling;
    const originalTable = preparedTitle?.previousElementSibling;
    const originalTitle = originalTable?.previousElementSibling;
    if (preparationTitle(preparedTitle) === "Prepared model inputs" &&
        originalTable?.matches("table, .table-scroll") &&
        preparationTitle(originalTitle) === "Original feature values") start = originalTitle;
    for (let node = start; node; node = node.nextElementSibling) {
      content.append(cloneForPreview(node));
      if (node === item.caption) break;
    }
  }

  function showPreview(key, panelIndex = 0) {
    const item = items.get(key);
    if (!item) return;
    if (item.kind === "figure" && typeof window.GLightbox === "function") {
      showFigureLightbox(item, panelIndex);
      return;
    }
    title.textContent = `${item.kind === "figure" ? "Figure" : "Table"} ${item.number}`;
    content.replaceChildren();
    if (item.kind === "figure") {
      const figure = item.caption.closest(".method-figure");
      const heading = figure?.querySelector(".method-figure-title");
      const subtitle = figure?.querySelector(".method-figure-subtitle");
      if (heading) title.textContent += `: ${heading.textContent.trim()}`;
      if (subtitle) {
        const detail = document.createElement("p");
        detail.className = "reference-preview-subtitle";
        detail.textContent = subtitle.textContent;
        content.append(detail);
      }
      const source = figure?.querySelectorAll("a.figure-preview img")[panelIndex];
      const panelTitle = source?.closest('.method-figure-panel')?.querySelector('.method-panel-title')?.textContent.trim();
      if (panelTitle) title.textContent += ` — ${panelTitle}`;
      if (source) {
        const image = document.createElement("img");
        image.className = "reference-preview-image";
        image.src = new URL(source.getAttribute("src"), new URL(item.page, location.href)).href;
        image.alt = source.alt;
        content.append(image);
      }
      content.append(cloneForPreview(item.caption));
    } else previewTable(item);
    dialog.showModal();
    content.scrollTop = 0;
    document.body.classList.add("reference-preview-open");
  }

  let figureLightbox;
  function fitFigureLightbox() {
    const slide = document.querySelector(".method-lightbox .gslide.current");
    const image = slide?.querySelector(".gslide-image img");
    if (!image?.naturalWidth) return;
    const maxWidth = Math.min(1100, window.innerWidth - 48);
    const maxHeight = Math.max(180, window.innerHeight - 240);
    const width = Math.min(image.naturalWidth, maxWidth, maxHeight * image.naturalWidth / image.naturalHeight);
    slide.querySelector(".ginner-container").style.width = `${width}px`;
  }
  window.addEventListener("resize", fitFigureLightbox);
  function escapeText(text) {
    const span = document.createElement("span");
    span.textContent = text;
    return span.innerHTML;
  }

  function showFigureLightbox(selected, selectedPanel = 0) {
    const figures = [...items.values()]
      .filter(item => item.kind === "figure" && item.page === selected.page)
      .flatMap(item => {
        const figure = item.caption.closest(".method-figure");
        return [...figure.querySelectorAll("a.figure-preview img")]
          .map((source, panelIndex) => ({ item, figure, source, panelIndex }));
      });
    const elements = figures.map(({ item, figure, source }) => {
      const heading = figure.querySelector(".method-figure-title")?.textContent.trim() || "";
      const subtitle = figure.querySelector(".method-figure-subtitle")?.textContent.trim();
      const panelTitle = source.closest('.method-figure-panel')?.querySelector('.method-panel-title')?.textContent.trim();
      return {
        href: new URL(source.getAttribute("src"), new URL(item.page, location.href)).href,
        type: "image",
        alt: source.alt,
        title: escapeText(`Figure ${item.number}: ${heading}${panelTitle ? ' — ' + panelTitle : ''}`) + (subtitle ? `<br><small>${escapeText(subtitle)}</small>` : ""),
        description: item.caption.innerHTML,
        descPosition: "bottom"
      };
    });
    if (figureLightbox) figureLightbox.destroy();
    const opener = document.activeElement;
    figureLightbox = window.GLightbox({
      elements,
      openEffect: "fade", closeEffect: "fade", slideEffect: "slide",
      moreLength: 0,
      slideHTML: '<div class="gslide"><div class="gslide-inner-content"><div class="ginner-container"><h4 class="gslide-title method-lightbox-title"></h4><div class="gslide-media"></div><div class="gslide-description"><div class="gdesc-inner"><div class="gslide-desc"></div></div></div></div></div></div>',
      onOpen: () => {
        document.getElementById("glightbox-body")?.classList.add("method-lightbox");
        requestAnimationFrame(fitFigureLightbox);
      },
      afterSlideLoad: () => requestAnimationFrame(fitFigureLightbox),
      afterSlideChange: () => requestAnimationFrame(fitFigureLightbox),
      onClose: () => opener?.focus({ preventScroll: true })
    });
    figureLightbox.openAt(figures.findIndex(entry => entry.item === selected && entry.panelIndex === selectedPanel));
  }

  main.addEventListener("click", event => {
    const link = event.target.closest("a.document-reference, a.figure-preview");
    if (!link || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    event.stopPropagation();
    showPreview(link.dataset.reference, Number(link.dataset.panel || 0));
  }, true);

  function linkReferences() {
    const walker = document.createTreeWalker(main, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) {
      const node = walker.currentNode;
      if (!node.parentElement.closest("a, script, style, code, pre, table, .method-caption, .method-figure-title, .method-figure-subtitle, [data-reference-caption]")) nodes.push(node);
    }
    for (const node of nodes) {
      const value = node.textContent;
      const matches = [...value.matchAll(referencePattern)].filter(match => items.has(keyFor(match[1], match[2])));
      if (!matches.length) continue;
      const fragment = document.createDocumentFragment();
      let offset = 0;
      for (const match of matches) {
        fragment.append(value.slice(offset, match.index));
        const key = keyFor(match[1], match[2]);
        const item = items.get(key);
        const link = document.createElement("a");
        link.className = "document-reference";
        link.href = item.page;
        link.dataset.reference = key;
        link.setAttribute("aria-haspopup", "dialog");
        link.textContent = match[0];
        link.title = `Preview ${match[0]}`;
        fragment.append(link);
        offset = match.index + match[0].length;
      }
      fragment.append(value.slice(offset));
      node.replaceWith(fragment);
    }
  }
  linkReferences();
  Promise.all(pages.filter(page => page !== currentPage).map(async page => {
    try {
      const response = await fetch(page);
      if (!response.ok) return;
      const other = new DOMParser().parseFromString(await response.text(), "text/html");
      collect(other.querySelector("main") || other, page);
    } catch (error) {
      console.warn("Could not load reference previews", page, error);
    }
  })).then(linkReferences);
})();
