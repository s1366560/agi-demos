function memstackAuthElement(request) {
  const element = this;
  try {
    const doc = element.ownerDocument;
    const win = doc?.defaultView;
    if (!element.isConnected || !win || win.document !== doc) return { status: 'page_changed' };
    if (win.location.origin !== request.origin) return { status: 'origin_changed' };
    const rect = element.getBoundingClientRect();
    const style = win.getComputedStyle(element);
    if (rect.width <= 0 || rect.height <= 0 || style.display === 'none' || style.visibility !== 'visible') return { status: 'locator_invalid' };
    if (element.disabled || element.getAttribute('aria-disabled') === 'true') {
      if (request.role !== 'submit' || request.action !== 'validate') return { status: 'locator_invalid' };
    }
    if (request.role === 'field') {
      if (!(element instanceof win.HTMLInputElement) || element.type !== request.spec.type || element.readOnly) return { status: 'locator_invalid' };
      if (request.spec.autocomplete != null && element.getAttribute('autocomplete') !== request.spec.autocomplete) return { status: 'locator_invalid' };
    }
    const form = element.form;
    if (request.role !== 'option' && form) {
      if (new URL(form.action, doc.baseURI).origin !== request.origin) return { status: 'origin_changed' };
      if (form.target && form.target !== '_self') return { status: 'locator_invalid' };
    }
    if (request.action === 'validate') return { status: 'ready' };
    if (request.action === 'fill') {
      if (request.role !== 'field' || typeof request.value !== 'string') return { status: 'locator_invalid' };
      element.focus();
      const setter = Object.getOwnPropertyDescriptor(win.HTMLInputElement.prototype, 'value')?.set;
      if (!setter) return { status: 'locator_invalid' };
      setter.call(element, request.value);
      element.dispatchEvent(new win.InputEvent('input', { bubbles: true, inputType: 'insertText', data: null }));
      element.dispatchEvent(new win.Event('change', { bubbles: true }));
      return { status: 'filled' };
    }
    if (request.action === 'focus') { element.focus(); return { status: 'focused' }; }
    if (request.action === 'click') { element.click(); return { status: 'submitted' }; }
    return { status: 'unavailable' };
  } catch { return { status: 'page_changed' }; }
}
