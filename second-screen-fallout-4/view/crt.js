"use strict";
// Native foreground scan: .6 * SourceGraphic * scan * (1 + verticalScan),
// plus .4 times a blur of the original UI. A Gaussian with matching variance
// approximates the native 5x5 box; its +1.5 pixel offset matches registration.
// One generated alpha profile reduces the SVG pass to five primitives.
(() => {
  const display = document.getElementById("display");
  const PROFILE_WIDTH = 8;
  const NS = "http://www.w3.org/2000/svg";
  const XLINK = "http://www.w3.org/1999/xlink";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("aria-hidden", "true");
  svg.style.cssText =
    "position:absolute;width:0;height:0;overflow:hidden;pointer-events:none";
  function node(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    for (const [key, value] of Object.entries(attrs))
      e.setAttribute(key, String(value));
    parent.append(e);
    return e;
  }
  const defs = node("defs", {}, svg);
  const filter = node(
    "filter",
    {
      id: "pipboy-native-crt",
      x: "-4%",
      y: "-4%",
      width: "108%",
      height: "108%",
      filterUnits: "objectBoundingBox",
      primitiveUnits: "userSpaceOnUse",
      "color-interpolation-filters": "sRGB",
    },
    defs,
  );
  const scan = node(
    "feImage",
    {
      x: 0,
      y: 0,
      preserveAspectRatio: "none",
      result: "scanProfile",
    },
    filter,
  );
  node(
    "feComposite",
    {
      in: "SourceGraphic",
      in2: "scanProfile",
      operator: "in",
      result: "main",
    },
    filter,
  );
  node(
    "feGaussianBlur",
    {
      in: "SourceGraphic",
      stdDeviation: Math.sqrt(18),
      result: "blur",
    },
    filter,
  );
  node(
    "feOffset",
    { in: "blur", dx: 1.5, dy: 1.5, result: "offsetBlur" },
    filter,
  );
  node(
    "feComposite",
    {
      in: "main",
      in2: "offsetBlur",
      operator: "arithmetic",
      k1: 0,
      k2: 1,
      k3: 0.4,
      k4: 0,
    },
    filter,
  );
  document.body.append(svg);
  const scratch = document.createElement("canvas");
  scratch.width = PROFILE_WIDTH;
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  let ready = false,
    enabled = true,
    frozen = null,
    phase = -0.5;
  let height = 0,
    profiles = null,
    sourceKey = "",
    revision = 0,
    stamp = "";
  let sweepStart = performance.now() / 1000;
  let nextStart = sweepStart + 4 + 3 + Math.random() * 7;

  function source(descriptor) {
    const embedded = descriptor?.dataURI;
    if (/^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(embedded || ""))
      return embedded;
    const path = descriptor?.path;
    if (!path || /(^|\/)\.\.(\/|$)/.test(path)) return null;
    if (path.startsWith("file://")) return path;
    if (/^[a-z]+:/i.test(path)) return null;
    return (
      (window.armada?.data || "").replace(/\/$/, "") +
      "/" +
      path.replace(/^\//, "")
    );
  }
  function profile(href) {
    return new Promise((resolve, reject) => {
      const image = new Image();
      image.onload = () => {
        try {
          const canvas = document.createElement("canvas");
          canvas.width = image.naturalWidth;
          canvas.height = image.naturalHeight;
          const context = canvas.getContext("2d");
          context.drawImage(image, 0, 0);
          const rgba = context.getImageData(
            0,
            0,
            canvas.width,
            canvas.height,
          ).data;
          const rows = Array.from(
            { length: canvas.height },
            (_, y) => rgba[y * canvas.width * 4] / 255,
          );
          resolve(rows);
        } catch (error) {
          reject(error);
        }
      };
      image.onerror = reject;
      image.src = href;
    });
  }
  function sample(rows, position, repeat) {
    const n = rows.length;
    const p = position * n - 0.5;
    const index = Math.floor(p),
      fraction = p - index;
    const at = (i) =>
      rows[repeat ? ((i % n) + n) % n : Math.max(0, Math.min(n - 1, i))];
    return at(index) * (1 - fraction) + at(index + 1) * fraction;
  }
  function draw() {
    if (!ready || !enabled || !height) return;
    const key = `${height}:${phase}:${revision}`;
    if (stamp === key) return;
    stamp = key;
    const pixels = new ImageData(PROFILE_WIDTH, height);
    for (let y = 0; y < height; y++) {
      const uv = (y + 0.5) / height;
      const gain =
        0.6 *
        sample(profiles[0], uv * 200, true) *
        (1 + sample(profiles[1], (uv - phase) * 3, false));
      const alpha = Math.round(gain * 255);
      for (let x = 0; x < PROFILE_WIDTH; x++) {
        const p = (y * PROFILE_WIDTH + x) * 4;
        pixels.data[p] = pixels.data[p + 1] = pixels.data[p + 2] = 255;
        pixels.data[p + 3] = alpha;
      }
    }
    scratch.getContext("2d").putImageData(pixels, 0, 0);
    const href = scratch.toDataURL();
    scan.setAttribute("href", href);
    scan.setAttributeNS(XLINK, "xlink:href", href);
  }
  function attribute(element, key, value) {
    const text = String(value);
    if (element.getAttribute(key) !== text) element.setAttribute(key, text);
  }
  function size() {
    const rect = display.getBoundingClientRect();
    attribute(scan, "width", rect.width);
    attribute(scan, "height", rect.height);
    const next = Math.max(1, Math.round(rect.height * (devicePixelRatio || 1)));
    if (height !== next) {
      height = next;
      scratch.height = height;
      stamp = "";
    }
    draw();
  }
  function apply() {
    const active = ready && enabled;
    document.body.dataset.crt = active ? "native" : "off";
    display.style.filter = active ? "url(#pipboy-native-crt)" : "";
    display.style.isolation = active ? "isolate" : "";
    display.style.backgroundColor = active ? "#000" : "";
    if (active) draw();
  }
  function update(state) {
    const effects = state?.assets?.effects;
    const urls = [source(effects?.scan), source(effects?.verticalScan)];
    const key = JSON.stringify(urls);
    if (key !== sourceKey) {
      sourceKey = key;
      ready = false;
      const request = ++revision;
      if (urls.every(Boolean))
        Promise.all(urls.map(profile))
          .then((loaded) => {
            if (request !== revision) return;
            profiles = loaded;
            ready = true;
            stamp = "";
            size();
            apply();
          })
          .catch(() => {
            if (request === revision) {
              ready = false;
              apply();
            }
          });
    }
    size();
    apply();
  }
  function step(seconds) {
    if (frozen !== null) phase = frozen;
    else if (reduced.matches) phase = 1.5;
    else {
      if (seconds >= nextStart) {
        sweepStart = seconds;
        nextStart = seconds + 4 + 3 + Math.random() * 7;
      }
      phase = Math.min(1.5, -0.5 + (seconds - sweepStart) * 0.5);
    }
    draw();
  }
  let last = 0;
  function animate(now) {
    requestAnimationFrame(animate);
    if (!ready || !enabled || now - last < 1000 / 30) return;
    last = now;
    step(now / 1000);
  }
  new ResizeObserver(size).observe(display);
  window.addEventListener("resize", size);
  window.PipboyCRT = {
    update,
    step,
    freeze(value) {
      frozen = value;
      step(performance.now() / 1000);
    },
    resume() {
      frozen = null;
      sweepStart = performance.now() / 1000;
      nextStart = sweepStart + 4 + 3 + Math.random() * 7;
    },
    enable(value) {
      enabled = !!value;
      stamp = "";
      apply();
    },
    get ready() {
      return ready;
    },
    get phase() {
      return phase;
    },
  };
  apply();
  requestAnimationFrame(animate);
})();
