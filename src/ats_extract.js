// ats_extract.js — evaluated in the page by ats_apply.py.
// Returns one descriptor per question: {idx, tag, type, label, required, prefilled,
// options:[{text, idx}], name, id, combobox}. Every control/option gets a
// data-hermes-idx attribute so Python can target it with a stable selector.
() => {
  let counter = 0;
  const tag = (el) => { const i = counter++; el.setAttribute("data-hermes-idx", String(i)); return i; };
  const clean = (t) => (t || "").replace(/\s+/g, " ").trim();
  const visible = (el) => !!(el.offsetParent || el.getClientRects().length);

  // Some ATS vendors (confirmed live: SmartRecruiters' "oneclick-ui" apply form) render
  // every field inside a custom-element shadow root. Playwright's own locators pierce
  // shadow DOM automatically, but plain document.querySelectorAll does not, so this
  // extractor previously found 1 of 13 real fields on such a page (only the one control
  // that happened to sit in the light DOM). deepQueryAll walks into every shadow root;
  // getRootNode() makes id-based label lookup resolve within the SAME root as the input
  // (a shadow-DOM component's own <label for=...> lives in its own shadow tree, not in
  // the top-level document).
  const deepQueryAll = (selector) => {
    const out = [];
    const walk = (root) => {
      out.push(...root.querySelectorAll(selector));
      root.querySelectorAll("*").forEach((el) => { if (el.shadowRoot) walk(el.shadowRoot); });
    };
    walk(document);
    return out;
  };

  const ownLabel = (el) => {
    if (el.id) {
      const root = el.getRootNode ? el.getRootNode() : document;
      const l = root.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (l) return l;
    }
    return el.closest("label");
  };

  // Question text: walk up until an ancestor has a label/legend that is not the option's own label.
  const questionLabel = (el, skipOwn) => {
    const own = skipOwn ? ownLabel(el) : null;
    let n = el.parentElement;
    for (let depth = 0; n && depth < 8; depth++, n = n.parentElement) {
      if (n.matches("li.application-question, .application-question")) {
        const l = n.querySelector(".application-label, .text");
        if (l) return l;
      }
      const cands = n.querySelectorAll(":scope > label, :scope > legend, :scope > fieldset > legend, :scope > div > label, :scope > .application-label");
      for (const c of cands) {
        if (c !== own && !c.contains(el) && clean(c.innerText)) return c;
      }
    }
    return null;
  };

  // Helper text ("How do you pronounce your name?") often carries the real question.
  const described = (el) => clean((el.getAttribute("aria-describedby") || "").split(/\s+/)
    .map((id) => document.getElementById(id)).filter((d) => d && !/error/i.test(d.id + d.className))
    .map((d) => d.innerText).join(" "));

  const labelInfo = (labelEl, fallback, el) => {
    const help = el ? described(el) : "";
    const text = clean((labelEl ? labelEl.innerText : fallback) + (help ? " — " + help : ""));
    const req = !!labelEl && (/[*✱]/.test(labelEl.innerText) || /required/i.test(labelEl.className || "")
      || !!labelEl.querySelector("[class*=required], .required"));
    return { text, req };
  };

  const isCombobox = (el) => el.getAttribute("role") === "combobox" || !!el.getAttribute("aria-autocomplete")
    || el.getAttribute("aria-haspopup") === "listbox" || /location-input|candidate-location/.test(el.id || "");

  const out = [];
  const groups = new Map();
  const controls = deepQueryAll("input, textarea, select");
  for (const el of controls) {
    const type = (el.type || "").toLowerCase();
    if (["hidden", "submit", "button", "search", "image", "reset"].includes(type)) continue;
    if (type !== "file" && !visible(el)) continue;
    if (!el.id && !el.name && el.tabIndex === -1) continue;  // react-select's hidden validator input
    if (/recaptcha|captcha/i.test(el.name || el.id || "")) continue;

    if (type === "radio" || (type === "checkbox" && el.name && document.querySelectorAll(`input[type=checkbox][name="${CSS.escape(el.name)}"]`).length > 1)) {
      const key = type + ":" + el.name;
      if (!groups.has(key)) {
        const info = labelInfo(questionLabel(el, true), el.name);
        const g = { idx: null, tag: "INPUT", type, label: info.text, required: info.req || el.required,
                    prefilled: false, options: [], name: el.name, id: el.id, combobox: false, choice: true };
        groups.set(key, g); out.push(g);
      }
      const g = groups.get(key);
      const ol = ownLabel(el);
      g.options.push({ text: clean(ol ? ol.innerText : el.value), idx: tag(el) });
      if (el.checked) g.prefilled = true;
      continue;
    }

    const idx = tag(el);
    const lbl = type === "checkbox" ? (ownLabel(el) || questionLabel(el, false)) : (ownLabel(el) || questionLabel(el, false));
    const info = labelInfo(lbl, el.getAttribute("aria-label") || el.placeholder || el.name, el);
    const required = info.req || el.required || el.getAttribute("aria-required") === "true";
    let options = [];
    let prefilled = false;
    if (el.tagName === "SELECT") {
      options = Array.from(el.options).filter((o) => o.value && clean(o.text) && !/^select/i.test(clean(o.text)))
        .map((o) => ({ text: clean(o.text), idx: null }));
      prefilled = el.selectedIndex > 0 && !!el.value;
    } else if (type === "file") {
      prefilled = el.files && el.files.length > 0;
    } else if (type === "checkbox") {
      prefilled = el.checked;
    } else {
      prefilled = !!clean(el.value);
    }
    out.push({ idx, tag: el.tagName, type, label: info.text, required, prefilled, options,
               name: el.name || "", id: el.id || "", combobox: isCombobox(el) });
  }

  // Ashby renders boolean questions as a pair of "Yes"/"No" buttons.
  const seen = new Set();
  for (const b of document.querySelectorAll("button[type=button]")) {
    const parent = b.parentElement;
    if (!parent || seen.has(parent)) continue;
    const btns = Array.from(parent.querySelectorAll(":scope > button"));
    const texts = btns.map((x) => clean(x.innerText));
    if (btns.length !== 2 || !texts.includes("Yes") || !texts.includes("No")) continue;
    seen.add(parent);
    const info = labelInfo(questionLabel(parent, false), "");
    const pressed = btns.some((x) => x.getAttribute("aria-pressed") === "true" || /selected|active/i.test(x.className));
    out.push({ idx: null, tag: "BUTTONS", type: "buttons", label: info.text, required: info.req,
               prefilled: pressed, options: btns.map((x) => ({ text: clean(x.innerText), idx: tag(x) })),
               name: "", id: "", combobox: false, choice: true });
  }
  return out;
}
