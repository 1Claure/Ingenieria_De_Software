import { createRenderedJourney } from "./rendered-scene.js";

function composedParent(element) {
  return element.parentElement || element.getRootNode?.().host || null;
}

function findScrollContainer(root) {
  let element = composedParent(root);
  while (element) {
    if (element.matches?.('[data-testid="stMain"]')) return element;
    const overflow = getComputedStyle(element).overflowY;
    if (/auto|scroll/.test(overflow) && element.scrollHeight > element.clientHeight) return element;
    element = composedParent(element);
  }
  return window;
}

export default function mount({ parentElement, data }) {
  const root = parentElement.querySelector(".journey-root");
  if (!root) return () => {};

  const heroImage = root.querySelector("[data-hero-image]");
  if (typeof data?.hero_image === "string" && data.hero_image.startsWith("data:image/")) {
    heroImage.src = data.hero_image;
  }

  const track = root.querySelector("[data-journey-track]");
  const viewport = root.querySelector("[data-scene-viewport]");
  const canvas = root.querySelector("[data-render-background]");
  const manifestUrl = new URL(data.world_manifest, window.location.href).href;
  const chapters = [...root.querySelectorAll("[data-chapter]")];
  const mobileQuery = window.matchMedia("(max-width: 760px)");
  const motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
  const scrollContainer = findScrollContainer(root);
  const cleanups = [];
  let scene = null;
  let disposed = false;
  let frameId = 0;
  let intersects = true;
  let activeChapter = -1;
  let lastProgress = -1;
  let lastWidth = 0;
  let lastHeight = 0;
  let lastViewportHeight = 0;
  let sceneFailed = false;

  const listen = (target, event, handler, options) => {
    target.addEventListener(event, handler, options);
    cleanups.push(() => target.removeEventListener(event, handler, options));
  };

  const poster = root.querySelector('[data-render-poster]');
  if (poster) {
    listen(poster, 'load', () => {root.dataset.posterState = 'ready';});
    listen(poster, 'error', () => {root.dataset.posterState = 'unavailable';});
    poster.src = data.render_poster ? new URL(data.render_poster, window.location.href).href : new URL('poster.webp', manifestUrl).href;
    poster.decoding = 'async';
  }

  const viewportBounds = () => {
    if (scrollContainer === window) return { top: 0, height: window.innerHeight };
    const bounds = scrollContainer.getBoundingClientRect();
    return { top: bounds.top, height: scrollContainer.clientHeight };
  };

  const update = () => {
    frameId = 0;
    if (disposed || !root.isConnected) return;
    if (sceneFailed && scene) disposeScene();
    const bounds = viewportBounds();
    if (bounds.height !== lastViewportHeight) {
      root.style.setProperty("--journey-viewport-height", `${bounds.height}px`);
      lastViewportHeight = bounds.height;
    }
    const readingLine = bounds.top + viewport.clientHeight * 0.5;
    const centers = chapters.map(chapter => {
      const rect = chapter.getBoundingClientRect();
      return rect.top + rect.height / 2;
    });
    let progress = readingLine >= centers.at(-1) ? 1 : 0;
    for (let index = 0; index < centers.length - 1; index++) {
      if (readingLine >= centers[index] && readingLine < centers[index + 1]) {
        const local = (readingLine - centers[index]) / (centers[index + 1] - centers[index]);
        // Hold the camera while reading, then continue through the same world
        // in either direction. The scene itself is never swapped.
        const travel = Math.max(0, Math.min(1, (local - .18) / .64));
        progress = (index + travel * travel * (3 - 2 * travel)) / (centers.length - 1);
        break;
      }
    }
    root.dataset.journeyProgress = progress.toFixed(4);

    let nextChapter = 0;
    for (let index = 0; index < chapters.length; index += 1) {
      if (chapters[index].getBoundingClientRect().top <= readingLine) nextChapter = index;
    }
    if (activeChapter !== nextChapter) {
      activeChapter = nextChapter;
      chapters.forEach((chapter, index) => chapter.classList.toggle("is-current", index === activeChapter));
    }

    if (scene && intersects) {
      const width = viewport.clientWidth;
      const height = viewport.clientHeight;
      if (width !== lastWidth || height !== lastHeight) {
        scene.resize(width, height);
        lastWidth = width;
        lastHeight = height;
      }
      if (Math.abs(progress - lastProgress) > 0.0001) {
        scene.setProgress(progress);
        lastProgress = progress;
      }
    }
  };

  const scheduleUpdate = () => {
    if (!disposed && !frameId) frameId = requestAnimationFrame(update);
  };

  const disposeScene = () => {
    scene?.dispose();
    scene = null;
    root.dataset.sceneState = "static";
    root.dataset.renderState = "static";
    lastProgress = -1;
    lastWidth = 0;
    lastHeight = 0;
  };

  const syncScene = () => {
    if (disposed) return;
    const useStatic = mobileQuery.matches || motionQuery.matches;
    activeChapter = -1;
    if (useStatic) {
      disposeScene();
    } else if (!scene && !sceneFailed) {
      try {
        root.dataset.sceneState = "loading";
        root.dataset.renderState = "loading";
        scene = createRenderedJourney({
          canvas,
          worldManifestUrl: manifestUrl,
          onReady: () => {
            if (disposed) return;
            root.dataset.sceneState = "ready";
            root.dataset.renderState = "ready";
            scheduleUpdate();
          },
          onError: () => {
            sceneFailed = true;
            activeChapter = -1;
            root.dataset.sceneState = "static";
            root.dataset.renderState = "static";
            scheduleUpdate();
          },
        });
      } catch {
        sceneFailed = true;
        disposeScene();
      }
    }
    scheduleUpdate();
  };

  root.querySelectorAll("[data-open-estimator]").forEach((button) => {
    listen(button, "click", (event) => {
      const estimator = document.getElementById("estimador");
      if (!estimator) return;
      event.preventDefault();
      estimator.scrollIntoView({behavior: motionQuery.matches ? "instant" : "smooth", block: "start"});
      estimator.focus({preventScroll: true});
    });
  });
  listen(scrollContainer, "scroll", scheduleUpdate, { passive: true });
  listen(window, "resize", scheduleUpdate, { passive: true });
  listen(mobileQuery, "change", syncScene);
  listen(motionQuery, "change", syncScene);

  const resizeObserver = new ResizeObserver(scheduleUpdate);
  resizeObserver.observe(root);
  resizeObserver.observe(viewport);
  if (scrollContainer !== window) resizeObserver.observe(scrollContainer);
  cleanups.push(() => resizeObserver.disconnect());

  const intersectionObserver = new IntersectionObserver((entries) => {
    intersects = entries[0]?.isIntersecting ?? true;
    if (intersects) scheduleUpdate();
  }, { root: scrollContainer === window ? null : scrollContainer, rootMargin: "80px" });
  intersectionObserver.observe(track);
  cleanups.push(() => intersectionObserver.disconnect());

  syncScene();

  return () => {
    disposed = true;
    if (frameId) cancelAnimationFrame(frameId);
    cleanups.forEach((cleanup) => cleanup());
    disposeScene();
  };
}
