async function memstackDomOperation(request) {
  const { operation, args = [] } = request;
  const visible = element => {
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
  };
  const textOf = element => element.innerText ?? element.textContent ?? '';
  const normalize = text => String(text ?? '').replace(/\s+/g, ' ').trim();
  const matchesText = (actual, expected, exact = false) => expected?.regex !== undefined
    ? new RegExp(expected.regex, expected.flags).test(actual)
    : exact ? normalize(actual) === normalize(expected) : normalize(actual).includes(normalize(expected));
  const descendants = (root, selector = '*') => {
    const result = [...root.querySelectorAll(selector)];
    for (const element of root.querySelectorAll('*')) if (element.shadowRoot) result.push(...descendants(element.shadowRoot, selector));
    return result;
  };
  const roleOf = element => {
    if (element.hasAttribute('role')) return element.getAttribute('role').split(' ')[0];
    const tag = element.tagName.toLowerCase();
    if (tag === 'input') return ({ checkbox: 'checkbox', radio: 'radio', range: 'slider', button: 'button', submit: 'button', reset: 'button', search: 'searchbox', hidden: 'none' })[element.type] ?? 'textbox';
    return ({ button: 'button', a: element.hasAttribute('href') ? 'link' : '', textarea: 'textbox', select: element.multiple ? 'listbox' : 'combobox', option: 'option', img: 'img', h1: 'heading', h2: 'heading', h3: 'heading', h4: 'heading', h5: 'heading', h6: 'heading', table: 'table', tr: 'row', td: 'cell', th: 'columnheader', ul: 'list', ol: 'list', li: 'listitem', nav: 'navigation', main: 'main', progress: 'progressbar' })[tag] ?? '';
  };
  const nameOf = element => {
    const labelledBy = element.getAttribute('aria-labelledby');
    if (labelledBy) return normalize(labelledBy.split(/\s+/).map(id => element.ownerDocument.getElementById(id)?.textContent ?? '').join(' '));
    return element.getAttribute('aria-label') ?? (element.labels?.length ? [...element.labels].map(label => textOf(label)).join(' ') : undefined)
      ?? element.getAttribute('alt') ?? element.getAttribute('title') ?? textOf(element);
  };
  function select(steps, initial = [document]) {
    let roots = initial;
    for (const { kind, args: values = [] } of steps) {
      const [value, options = {}] = values;
      if (kind === 'first') { roots = roots.slice(0, 1); continue; }
      if (kind === 'last') { roots = roots.slice(-1); continue; }
      if (kind === 'nth') { roots = roots[value] ? [roots[value]] : []; continue; }
      if (kind === 'and' || kind === 'or') {
        const other = select(value);
        roots = kind === 'and' ? roots.filter(item => other.includes(item)) : [...new Set([...roots, ...other])];
        continue;
      }
      if (kind === 'filter') {
        roots = roots.filter(element => (value.hasText === undefined || matchesText(textOf(element), value.hasText))
          && (value.hasNotText === undefined || !matchesText(textOf(element), value.hasNotText))
          && (!value.has || select(value.has, [element]).length > 0) && (!value.hasNot || select(value.hasNot, [element]).length === 0)
          && (value.visible === undefined || visible(element) === value.visible));
        continue;
      }
      let elements;
      if (kind === 'locator' || kind === 'frameLocator') elements = roots.flatMap(root => descendants(root, value));
      else elements = roots.flatMap(root => descendants(root)).filter(element => {
        if (kind === 'getByRole') return roleOf(element) === value && (options.name === undefined || matchesText(nameOf(element), options.name, options.exact)) && (options.includeHidden || visible(element));
        if (kind === 'getByText') return matchesText(textOf(element), value, options.exact) && ![...element.children].some(child => matchesText(textOf(child), value, options.exact));
        if (kind === 'getByLabel') return matchesText(nameOf(element), value, options.exact) && element.matches('input,textarea,select,[contenteditable],[role]');
        if (kind === 'getByPlaceholder') return matchesText(element.getAttribute('placeholder') ?? '', value, options.exact);
        if (kind === 'getByTestId') return matchesText(element.getAttribute('data-testid') ?? '', value, true);
        throw new Error(`unsupported locator selector: ${kind}`);
      });
      roots = [...new Set(elements)];
      if (kind === 'frameLocator') roots = roots.map(frame => {
        if (!frame.contentDocument) throw new Error('cross-origin frame requires its own scoped browser target');
        return frame.contentDocument;
      });
    }
    return roots;
  }
  const unique = steps => {
    const elements = select(steps);
    if (elements.length !== 1) throw new Error(`strict locator matched ${elements.length} elements`);
    return elements[0];
  };
  const waitUnique = async (steps, options = {}, actionable = false) => {
    const deadline = performance.now() + Math.min(options.timeoutMs ?? options.timeout ?? 5000, 30000);
    do {
      const elements = select(steps);
      if (elements.length > 1) throw new Error(`strict locator matched ${elements.length} elements`);
      if (elements.length === 1 && (!actionable || (visible(elements[0]) && !elements[0].disabled))) return elements[0];
      await new Promise(resolve => setTimeout(resolve, 25));
    } while (performance.now() < deadline);
    throw new Error('locator did not become available before timeout');
  };
  const evaluate = (spec, value, argument) => {
    const source = spec?.function ?? spec;
    if (typeof source !== 'string') throw new Error('evaluate requires a function or expression');
    const fn = (0, eval)(`(${source})`);
    return typeof fn === 'function' ? fn(value, argument) : fn;
  };
  const fill = (element, value) => {
    if (!visible(element) || element.disabled || element.readOnly) throw new Error('element is not editable');
    element.focus();
    if (element.isContentEditable) element.textContent = value;
    else {
      const prototype = element.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
      if (!setter) throw new Error('element does not accept text');
      setter.call(element, value);
    }
    element.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: value }));
    element.dispatchEvent(new Event('change', { bubbles: true }));
  };
  const snapshot = () => {
    const refs = [];
    const lines = [];
    let length = 0;
    let truncated = false;
    const emit = line => {
      if (length + line.length + 1 > 20000) { truncated = true; return; }
      lines.push(line);
      length += line.length + 1;
    };
    const excluded = element => element.matches('script,style,noscript,template,[aria-hidden="true"],[inert]')
      || getComputedStyle(element).display === 'none';
    const childrenOf = element => element.localName === 'slot' && element.assignedNodes().length
      ? element.assignedNodes() : (element.shadowRoot ?? element).childNodes;
    const visibleText = node => {
      const style = getComputedStyle(node.parentElement ?? node.parentNode.host);
      if (style.visibility === 'hidden' || style.visibility === 'collapse') return '';
      const range = document.createRange();
      range.selectNodeContents(node);
      return [...range.getClientRects()].some(rect => rect.width > 0 && rect.height > 0)
        ? normalize(node.nodeValue) : '';
    };
    const contentText = node => {
      if (node.nodeType === Node.TEXT_NODE) return visibleText(node);
      if (node.nodeType !== Node.ELEMENT_NODE || excluded(node)) return '';
      return normalize([...childrenOf(node)].map(contentText).join(' '));
    };
    const walk = (node, suppressText = false) => {
      if (truncated) return;
      if (node.nodeType === Node.TEXT_NODE) {
        if (suppressText) return;
        const text = visibleText(node);
        if (text) emit(`text ${JSON.stringify(text.slice(0, 1000))}`);
        return;
      }
      if (node.nodeType !== Node.ELEMENT_NODE) return;
      const element = node;
      if (excluded(element)) return;
      const role = roleOf(element);
      if (visible(element) && (role || element.matches('input,textarea,[contenteditable],[tabindex]'))) {
        refs.push(element);
        const fromContent = ['button', 'link', 'heading', 'option'].includes(role)
          ? contentText(element) : '';
        const explicitName = element.matches('[aria-label],[aria-labelledby],[alt],[title]') || element.labels?.length;
        const name = normalize(explicitName ? nameOf(element) : fromContent).slice(0, 300);
        const value = element.type !== 'password' && element.matches('input,textarea,select')
          ? ` value=${JSON.stringify(String(element.value ?? '').slice(0, 300))}` : '';
        emit(`[${refs.length - 1}] ${role || element.tagName.toLowerCase()} ${JSON.stringify(name)}${value}`);
        // The name already presents this text. Nested controls still keep refs.
        suppressText ||= name !== '' && name === fromContent;
      }
      for (const child of childrenOf(element)) walk(child, suppressText);
    };
    if (document.body) walk(document.body);
    if (truncated) lines.push('[snapshot truncated]');
    globalThis.__memstackFacadeRefs = refs;
    return lines.join('\n');
  };
  if (operation === 'playwright.domSnapshot' || operation === 'dom_cua.get_visible_dom' || operation === 'ax.get') return snapshot();
  if (operation === 'playwright.evaluate') return evaluate(args[0], args[1]);
  if (operation === 'playwright.resolveElement') return await waitUnique(args[0]);
  if (operation === 'playwright.focusLocator') { (await waitUnique(args[0], {}, true)).focus(); return; }
  const mediaSource = element => {
    if (!element?.isConnected) throw new Error('media target is unavailable');
    const media = element.closest('img,video,audio,source,a[href]') ?? element.querySelector('img,video,audio,source,a[href]');
    const url = media?.currentSrc || media?.src || media?.href;
    if (!url) throw new Error('target does not expose a downloadable media source');
    return { url, filename: media.getAttribute('download') || null };
  };
  if (operation === 'cua.downloadMedia') {
    const { x, y } = args[0] ?? {};
    if (!Number.isFinite(x) || !Number.isFinite(y) || x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) throw new Error('media point is outside the viewport');
    let element = document.elementFromPoint(x, y);
    while (element?.shadowRoot?.elementFromPoint(x, y)) element = element.shadowRoot.elementFromPoint(x, y);
    return mediaSource(element);
  }
  if (operation === 'playwright.elementInfo') {
    const options = args[0];
    return document.elementsFromPoint(options.x, options.y).filter(element => options.includeNonInteractable || roleOf(element)).map(element => {
      const rect = element.getBoundingClientRect();
      const candidates = [element.id ? `#${CSS.escape(element.id)}` : null, element.hasAttribute('data-testid') ? `[data-testid=${JSON.stringify(element.getAttribute('data-testid'))}]` : null,
        element.hasAttribute('name') ? `${element.tagName.toLowerCase()}[name=${JSON.stringify(element.getAttribute('name'))}]` : null].filter(Boolean);
      return { tagName: element.tagName.toLowerCase(), role: roleOf(element) || null, ariaName: nameOf(element) || null,
        visibleText: element.type === 'password' ? null : textOf(element), preview: element.outerHTML.slice(0, 240),
        testId: element.getAttribute('data-testid'), boundingBox: { x: rect.x, y: rect.y, width: rect.width, height: rect.height }, selector: { primary: candidates[0] ?? null, candidates } };
    });
  }
  if (['ax.setValue', 'ax.selectText', 'ax.performSecondaryAction'].includes(operation)) {
    const element = globalThis.__memstackFacadeRefs?.[args[0]];
    if (!element?.isConnected) throw new Error('stale accessibility index');
    if (operation === 'ax.setValue') { fill(element, String(args[1])); return; }
    if (operation === 'ax.performSecondaryAction') {
      if (args[1] === 'press') return element.click();
      if (args[1] === 'focus') return element.focus();
      throw new Error('secondary action is not exposed by this element');
    }
    const text = String(element.value ?? element.textContent ?? '');
    const [wanted, options = {}] = args.slice(1);
    const matches = []; let cursor = 0;
    while (cursor <= text.length) {
      const found = text.indexOf(wanted, cursor); if (found < 0) break;
      if ((options.prefix === undefined || text.slice(0, found).endsWith(options.prefix)) && (options.suffix === undefined || text.slice(found + wanted.length).startsWith(options.suffix))) matches.push(found);
      cursor = found + Math.max(1, wanted.length);
    }
    if (matches.length !== 1) throw new Error('text selection is missing or ambiguous');
    element.focus();
    const begin = matches[0]; const end = begin + wanted.length;
    element.setSelectionRange(options.selectionType === 'after' ? end : begin, options.selectionType === 'before' ? begin : end);
    return;
  }
  if (operation.startsWith('dom_cua.')) {
    const options = args[0] ?? {};
    const element = options.node_id === undefined ? document.activeElement : globalThis.__memstackFacadeRefs?.[Number(options.node_id)];
    if (!element?.isConnected) throw new Error('stale DOM node id');
    if (operation === 'dom_cua.downloadMedia') return mediaSource(element);
    if (operation === 'dom_cua.click' || operation === 'dom_cua.double_click') { element.click(); if (operation.endsWith('double_click')) { element.click(); element.dispatchEvent(new MouseEvent('dblclick', { bubbles: true })); } return; }
    if (operation === 'dom_cua.type') { fill(element, String(element.value ?? '') + options.text); return; }
    if (operation === 'dom_cua.scroll') { (options.node_id === undefined ? window : element).scrollBy(options.x, options.y); return; }
    if (operation === 'dom_cua.keypress') { const key = options.keys?.at(-1); element.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true })); element.dispatchEvent(new KeyboardEvent('keyup', { key, bubbles: true })); return; }
  }
  if (operation === 'playwright.locator') {
    const [steps, method, values = []] = args;
    const [value, options = {}] = values;
    if (method === 'count') return select(steps).length;
    if (method === 'allTextContents') return select(steps).map(element => element.textContent);
    if (method === 'evaluateAll') return evaluate(value, select(steps), options);
    if (method === 'waitFor') {
      const deadline = performance.now() + Math.min(value?.timeoutMs ?? value?.timeout ?? 5000, 30000);
      do {
        const elements = select(steps); const state = value?.state ?? 'visible';
        if (state === 'detached' ? !elements.length : state === 'hidden' ? elements.every(element => !visible(element)) : state === 'attached' ? elements.length > 0 : elements.some(visible)) return;
        await new Promise(resolve => setTimeout(resolve, 50));
      } while (performance.now() < deadline);
      throw new Error('locator wait timed out');
    }
    if (method === 'isVisible' && select(steps).length === 0) return false;
    const action = ['fill', 'type', 'pressSequentially', 'click', 'dblclick', 'check', 'uncheck', 'setChecked', 'selectOption'].includes(method);
    const element = await waitUnique(steps, ['click', 'dblclick', 'check', 'uncheck'].includes(method) ? value ?? {} : options, action);
    if (method === 'getAttribute') return element.getAttribute(value);
    if (method === 'innerText') return element.innerText;
    if (method === 'textContent') return element.textContent;
    if (method === 'isVisible') return visible(element);
    if (method === 'isEnabled') return !element.disabled && element.getAttribute('aria-disabled') !== 'true';
    if (method === 'evaluate') return evaluate(value, element, options);
    if (method === 'downloadMedia') return mediaSource(element);
    if (method === 'clickPoint') {
      element.scrollIntoView({ block: 'center', inline: 'center' });
      const rect = element.getBoundingClientRect();
      if (!rect.width || !rect.height) throw new Error('element has no clickable bounds');
      const x = rect.x + rect.width / 2;
      const y = rect.y + rect.height / 2;
      const root = element.getRootNode();
      const hit = root.elementFromPoint?.(x, y) ?? document.elementFromPoint(x, y);
      if (!value?.force && (element.disabled || !visible(element) || (hit !== element && !element.contains(hit)))) throw new Error('element is disabled or obscured');
      return { x, y };
    }
    if (method === 'fill') { fill(element, String(value)); return; }
    if (method === 'type' || method === 'pressSequentially') { fill(element, String(element.value ?? element.textContent ?? '') + value); return; }
    if (['click', 'dblclick', 'check', 'uncheck', 'setChecked'].includes(method)) {
      if (!visible(element) || element.disabled) throw new Error('element is not actionable');
      element.scrollIntoView({ block: 'center', inline: 'center' });
      if (['check', 'uncheck', 'setChecked'].includes(method)) {
        const desired = method === 'check' || (method === 'setChecked' && value);
        if (element.checked !== desired) element.click();
        if (element.checked !== desired) throw new Error('element did not reach requested checked state');
      } else { element.click(); if (method === 'dblclick') { element.click(); element.dispatchEvent(new MouseEvent('dblclick', { bubbles: true })); } }
      return;
    }
    if (method === 'selectOption') {
      const desired = Array.isArray(value) ? value : [value];
      for (const option of element.options ?? []) {
        option.selected = desired.some(item => typeof item === 'string' ? option.value === item : item.value !== undefined ? option.value === item.value : item.label !== undefined ? option.label === item.label : option.index === item.index);
      }
      element.dispatchEvent(new Event('input', { bubbles: true })); element.dispatchEvent(new Event('change', { bubbles: true }));
      return [...element.selectedOptions].map(option => option.value);
    }
    if (method === 'press') {
      element.focus();
      element.dispatchEvent(new KeyboardEvent('keydown', { key: value, bubbles: true }));
      element.dispatchEvent(new KeyboardEvent('keyup', { key: value, bubbles: true }));
      return;
    }
    throw new Error(`unsupported locator action: ${method}`);
  }
  if (operation === 'content.export') return { url: location.href, title: document.title, text: document.body.innerText, html: document.documentElement.outerHTML };
  if (operation === 'clipboard.readText') return navigator.clipboard.readText();
  if (operation === 'clipboard.writeText') return navigator.clipboard.writeText(args[0]);
  if (operation === 'clipboard.read') {
    const items = await navigator.clipboard.read();
    return Promise.all(items.map(async item => ({ presentationStyle: item.presentationStyle, entries: await Promise.all(item.types.map(async mimeType => {
      const blob = await item.getType(mimeType);
      if (blob.size > 16 * 1024 * 1024) throw new Error('clipboard item exceeds size limit');
      if (mimeType.startsWith('text/')) return { mimeType, text: await blob.text() };
      let binary = ''; for (const byte of new Uint8Array(await blob.arrayBuffer())) binary += String.fromCharCode(byte);
      return { mimeType, base64: btoa(binary) };
    })) })));
  }
  if (operation === 'clipboard.write') return navigator.clipboard.write(args[0].map(item => new ClipboardItem(Object.fromEntries(item.entries.map(entry => {
    const bytes = entry.base64 === undefined ? entry.text ?? '' : Uint8Array.from(atob(entry.base64), char => char.charCodeAt(0));
    return [entry.mimeType, new Blob([bytes], { type: entry.mimeType })];
  })), { presentationStyle: item.presentationStyle })));
  if (operation === 'capability.webmcp.listTools') {
    if (!navigator.modelContext?.listTools) throw new Error('WebMCP is unavailable on this page');
    return navigator.modelContext.listTools();
  }
  if (operation === 'capability.webmcp.callTool') {
    if (!navigator.modelContext?.callTool) throw new Error('WebMCP is unavailable on this page');
    return navigator.modelContext.callTool(...args);
  }
  if (operation === 'capability.pageAssets.list') {
    const discovered = new Map();
    const add = (raw, kind, source) => {
      let url; try { url = new URL(raw, document.baseURI); } catch { return; }
      if (!['http:', 'https:'].includes(url.protocol)) return;
      const existing = discovered.get(url.href);
      if (existing) { existing.sources.push(source); if (existing.kind === 'other') existing.kind = kind; return; }
      discovered.set(url.href, { id: url.href, url: url.href, kind, name: url.pathname.split('/').pop() || 'asset', sources: [source] });
    };
    for (const element of descendants(document)) {
      if (element.tagName === 'IMG') add(element.currentSrc || element.src, 'image', { kind: 'attribute', property: 'src' });
      if (element.tagName === 'VIDEO') { add(element.currentSrc || element.src, 'video', { kind: 'attribute', property: 'src' }); if (element.poster) add(element.poster, 'image', { kind: 'attribute', property: 'poster' }); }
      if (element.tagName === 'LINK' && element.rel === 'stylesheet') add(element.href, 'stylesheet', { kind: 'attribute', property: 'href' });
      if (element.tagName === 'SCRIPT' && element.src) add(element.src, 'script', { kind: 'attribute', property: 'src' });
      const style = getComputedStyle(element);
      for (const property of ['backgroundImage', 'maskImage', 'listStyleImage']) for (const match of style[property].matchAll(/url\(["']?([^"')]+)["']?\)/gu)) add(match[1], 'image', { kind: 'computedStyle', property });
    }
    for (const resource of performance.getEntriesByType('resource')) {
      const kind = ({ img: 'image', css: 'stylesheet', script: 'script', video: 'video', font: 'font' })[resource.initiatorType] ?? (/\.(woff2?|ttf|otf)(?:\?|$)/iu.test(resource.name) ? 'font' : 'other');
      add(resource.name, kind, { kind: 'resource' });
    }
    const assets = [...discovered.values()]; const byKind = {};
    for (const asset of assets) byKind[asset.kind] = (byKind[asset.kind] ?? 0) + 1;
    const inlineSvgs = descendants(document, 'svg').map((svg, i) => ({ id: String(i), markup: svg.outerHTML, name: svg.id || `svg-${i}` }));
    const inventory = { id: crypto.randomUUID(), pageUrl: location.href, assets, inlineSvgs, summary: { byKind, totalCount: assets.length, inlineSvgCount: inlineSvgs.length } };
    globalThis.__memstackAssetInventory = inventory;
    return inventory;
  }
  throw new Error(`unsupported DOM operation: ${operation}`);
}
