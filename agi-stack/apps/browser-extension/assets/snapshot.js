// MemStack Browser Bridge — accessibility snapshot script.
// Evaluated in the target page via CDP Runtime.evaluate (returnByValue: true).
// Plain ES2019: no imports/exports, no top-level await, no optional chaining.
// Returns a compact YAML-ish snapshot string and stashes ref -> element on
// window.__memstackSnapshotRefs so later action tools can resolve refs.
(function () {
  'use strict';

  var MAX_CHARS = 20000;
  var MAX_NAME = 80;
  var MAX_VALUE = 120;
  var MAX_IFRAME_DEPTH = 1;

  var SKIP_TAGS = { script: 1, style: 1, noscript: 1, template: 1 };
  var INTERACTIVE_ROLES = {
    button: 1,
    link: 1,
    textbox: 1,
    checkbox: 1,
    radio: 1,
    combobox: 1,
    listbox: 1,
    menuitem: 1,
    tab: 1,
    switch: 1,
  };
  var STRUCTURAL_ROLES = { dialog: 1, main: 1, navigation: 1, search: 1 };
  var NAME_FROM_CONTENT_ROLES = { button: 1, link: 1, heading: 1, menuitem: 1, tab: 1 };

  var lines = [];
  var emittedLength = 0;
  var truncated = false;
  var refCount = 0;
  var refs = new Map();

  // ---------------------------------------------------------------- helpers

  function emit(indent, text) {
    if (truncated) return false;
    var line = '';
    for (var i = 0; i < indent; i++) line += '  ';
    line += text;
    if (emittedLength + line.length + 1 > MAX_CHARS) {
      truncated = true;
      return false;
    }
    lines.push(line);
    emittedLength += line.length + 1;
    return true;
  }

  function assignRef(el) {
    refCount += 1;
    var ref = 'e' + refCount;
    refs.set(ref, typeof WeakRef === 'function' ? new WeakRef(el) : el);
    return ref;
  }

  function clean(text) {
    return String(text == null ? '' : text)
      .replace(/\s+/g, ' ')
      .trim();
  }

  function clip(text, max) {
    if (text.length <= max) return text;
    return text.slice(0, max - 1) + '…';
  }

  function quote(text) {
    return '"' + String(text).replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"';
  }

  function isVisible(el) {
    if (el.getAttribute('aria-hidden') === 'true') return false;
    var style;
    try {
      style = window.getComputedStyle(el);
    } catch (e) {
      return false;
    }
    if (!style || style.display === 'none' || style.visibility === 'hidden') return false;
    var rect = el.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) return false;
    return true;
  }

  function directText(el) {
    var text = '';
    for (var i = 0; i < el.childNodes.length; i++) {
      var node = el.childNodes[i];
      if (node.nodeType === 3) text += node.nodeValue;
    }
    return clean(text);
  }

  // ---------------------------------------------------------- element info

  function classify(el) {
    var tag = el.tagName.toLowerCase();
    if (tag === 'iframe') return { kind: 'iframe' };
    if (tag === 'img') return { kind: 'img' };

    var roleAttr = clean(el.getAttribute('role')).toLowerCase().split(' ')[0] || null;
    if (roleAttr && INTERACTIVE_ROLES[roleAttr]) return { kind: 'interactive', role: roleAttr };
    if (roleAttr && STRUCTURAL_ROLES[roleAttr]) return { kind: 'structural', role: roleAttr };

    if (tag === 'a' && el.hasAttribute('href')) return { kind: 'interactive', role: 'link' };
    if (tag === 'button') return { kind: 'interactive', role: 'button' };
    if (tag === 'select') return { kind: 'interactive', role: 'combobox' };
    if (tag === 'textarea') return { kind: 'interactive', role: 'textbox' };
    if (tag === 'summary') return { kind: 'interactive', role: 'button' };
    if (tag === 'input') {
      var type = (el.getAttribute('type') || 'text').toLowerCase();
      if (type === 'hidden') return null;
      if (type === 'checkbox') return { kind: 'interactive', role: 'checkbox' };
      if (type === 'radio') return { kind: 'interactive', role: 'radio' };
      if (type === 'button' || type === 'submit' || type === 'reset') {
        return { kind: 'interactive', role: 'button' };
      }
      if (type === 'range') return { kind: 'interactive', role: 'slider' };
      return { kind: 'interactive', role: 'textbox' };
    }

    var editable = el.getAttribute('contenteditable');
    if (editable !== null && editable !== 'false') return { kind: 'interactive', role: 'textbox' };
    var tabindex = el.getAttribute('tabindex');
    if (tabindex !== null && tabindex !== '-1') {
      return { kind: 'interactive', role: 'generic' };
    }

    if (tag === 'main') return { kind: 'structural', role: 'main' };
    if (tag === 'nav') return { kind: 'structural', role: 'navigation' };
    if (tag === 'header') return { kind: 'structural', role: 'banner' };
    if (tag === 'footer') return { kind: 'structural', role: 'contentinfo' };
    if (tag === 'form') return { kind: 'structural', role: 'form' };
    if (tag === 'dialog') return { kind: 'structural', role: 'dialog' };
    if (tag === 'h1' || tag === 'h2' || tag === 'h3') return { kind: 'structural', role: 'heading' };

    return null;
  }

  function labelledByText(el) {
    var ids = clean(el.getAttribute('aria-labelledby')).split(' ');
    var parts = [];
    for (var i = 0; i < ids.length; i++) {
      if (!ids[i]) continue;
      var target = el.ownerDocument.getElementById(ids[i]);
      if (target) parts.push(clean(target.textContent));
    }
    return clean(parts.join(' '));
  }

  function accessibleName(el, role) {
    var fromLabelledBy = labelledByText(el);
    if (fromLabelledBy) return clip(fromLabelledBy, MAX_NAME);
    var ariaLabel = clean(el.getAttribute('aria-label'));
    if (ariaLabel) return clip(ariaLabel, MAX_NAME);
    if (el.labels && el.labels.length > 0) {
      var fromLabel = clean(el.labels[0].textContent);
      if (fromLabel) return clip(fromLabel, MAX_NAME);
    }
    // Only these roles take their accessible name from the subtree's text;
    // landmarks named by full textContent would drown the snapshot in noise.
    if (NAME_FROM_CONTENT_ROLES[role]) {
      var text = clean(el.textContent);
      if (text) return clip(text, MAX_NAME);
    }
    var placeholder = clean(el.getAttribute('placeholder'));
    if (placeholder) return clip(placeholder, MAX_NAME);
    var value = clean(el.getAttribute('value'));
    if (value) return clip(value, MAX_NAME);
    var alt = clean(el.getAttribute('alt'));
    if (alt) return clip(alt, MAX_NAME);
    return clip(clean(el.getAttribute('title')), MAX_NAME);
  }

  function isChecked(el) {
    return el.checked === true || el.getAttribute('aria-checked') === 'true';
  }

  function isDisabled(el) {
    return (
      el.disabled === true ||
      el.hasAttribute('disabled') ||
      el.getAttribute('aria-disabled') === 'true'
    );
  }

  function controlValue(el) {
    var tag = el.tagName.toLowerCase();
    if (tag !== 'input' && tag !== 'textarea' && tag !== 'select') return '';
    var value = el.value;
    return typeof value === 'string' ? value : '';
  }

  function elementLine(el, info, name) {
    var role = info.role;
    var line = '- ' + role;
    if (name) line += ' ' + quote(name);
    line += ' [ref=' + assignRef(el) + ']';
    if (role === 'link') {
      var href = el.getAttribute('href');
      if (href) line += ' href=' + quote(clip(href, MAX_VALUE));
    }
    if (role === 'textbox' || role === 'combobox' || role === 'slider') {
      var value = controlValue(el);
      if (value) line += ' value=' + quote(clip(clean(value), MAX_VALUE));
    }
    if (role === 'checkbox' || role === 'radio' || role === 'switch') {
      if (isChecked(el)) line += ' checked';
    }
    if (isDisabled(el)) line += ' disabled';
    return line;
  }

  // ----------------------------------------------------------------- walk

  function walkNodes(nodeList, indent, iframeDepth, suppressText) {
    for (var i = 0; i < nodeList.length; i++) {
      if (truncated) return;
      var node = nodeList[i];
      if (node.nodeType === 1) walkElement(node, indent, iframeDepth, suppressText);
    }
  }

  function walkElement(el, indent, iframeDepth, suppressText) {
    var tag = el.tagName.toLowerCase();
    if (SKIP_TAGS[tag]) return;
    if (tag !== 'body' && !isVisible(el)) return;

    var info = classify(el);
    var childIndent = indent;

    if (info && info.kind === 'iframe') {
      var title = clean(el.getAttribute('title') || el.getAttribute('name'));
      var iframeLine = '- iframe' + (title ? ' ' + quote(title) : '');
      iframeLine += ' [ref=' + assignRef(el) + ']';
      if (!emit(indent, iframeLine)) return;
      if (iframeDepth < MAX_IFRAME_DEPTH) {
        try {
          var doc = el.contentDocument;
          if (doc && doc.body) {
            walkNodes([doc.body], indent + 1, iframeDepth + 1, false);
          }
        } catch (e) {
          /* cross-origin frame: skip */
        }
      }
      return;
    }

    if (info && info.kind === 'img') {
      emit(indent, '- img ' + quote(clip(clean(el.getAttribute('alt')), MAX_NAME)));
      return;
    }

    if (info && (info.kind === 'interactive' || info.kind === 'structural')) {
      var name = accessibleName(el, info.role);
      if (!emit(indent, elementLine(el, info, name))) return;
      childIndent = indent + 1;
      // Text that already became the accessible name must not be repeated.
      if (name && name === clean(el.textContent)) suppressText = true;
    }

    if (!suppressText) {
      var text = directText(el);
      if (text) {
        if (!emit(childIndent, '- text ' + quote(clip(text, MAX_VALUE)))) return;
      }
    }

    // An open shadow root replaces the host's light-DOM children.
    if (el.shadowRoot) {
      if (!emit(childIndent, '- #shadow-root')) return;
      walkNodes(el.shadowRoot.childNodes, childIndent + 1, iframeDepth, false);
      return;
    }

    walkNodes(el.childNodes, childIndent, iframeDepth, suppressText);
  }

  // ----------------------------------------------------------------- main

  try {
    if (document.body) walkElement(document.body, 0, 0, false);
  } catch (e) {
    lines.push('- text ' + quote('snapshot error: ' + (e && e.message ? e.message : e)));
  }

  var output = lines.join('\n');
  if (truncated) output += '\n… [truncated]';

  try {
    Object.defineProperty(window, '__memstackSnapshotRefs', {
      value: refs,
      configurable: true,
      writable: true,
    });
  } catch (e) {
    window.__memstackSnapshotRefs = refs;
  }

  return output;
})();
