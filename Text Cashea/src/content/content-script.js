(() => {
  const STORAGE_KEY = 'tc_snippets';
  let snippetIndex = new Map();

  function rebuildIndex(snippets) {
    snippetIndex = new Map((snippets || []).map((s) => [s.shortcut, s.body]));
  }

  chrome.storage.local.get(STORAGE_KEY, (data) => rebuildIndex(data[STORAGE_KEY]));

  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === 'local' && changes[STORAGE_KEY]) {
      rebuildIndex(changes[STORAGE_KEY].newValue);
    }
  });

  function findMatchingShortcut(textBeforeCaret) {
    for (const [shortcut, body] of snippetIndex) {
      if (!shortcut || !textBeforeCaret.endsWith(shortcut)) continue;
      const charBeforeIndex = textBeforeCaret.length - shortcut.length - 1;
      const charBefore = charBeforeIndex >= 0 ? textBeforeCaret[charBeforeIndex] : undefined;
      if (charBefore !== undefined && /\w/.test(charBefore)) continue;
      return { shortcut, body };
    }
    return null;
  }

  function replaceInStandardField(el, shortcut, body, caretPos) {
    const value = el.value;
    const newValue = value.slice(0, caretPos - shortcut.length) + body + value.slice(caretPos);
    const proto = el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
    setter.call(el, newValue);
    el.dispatchEvent(new InputEvent('input', { bubbles: true, cancelable: true, inputType: 'insertText', data: body }));
    const newCaretPos = caretPos - shortcut.length + body.length;
    el.setSelectionRange(newCaretPos, newCaretPos);
  }

  function handleStandardField(el) {
    if (el.type === 'password') return;
    if (typeof el.selectionStart !== 'number') return;
    const caretPos = el.selectionStart;
    const textBeforeCaret = el.value.slice(0, caretPos);
    const match = findMatchingShortcut(textBeforeCaret);
    if (!match) return;
    replaceInStandardField(el, match.shortcut, match.body, caretPos);
  }

  function pasteText(el, text) {
    const dataTransfer = new DataTransfer();
    dataTransfer.setData('text/plain', text);
    const pasteEvent = new ClipboardEvent('paste', {
      clipboardData: dataTransfer,
      bubbles: true,
      cancelable: true,
    });
    return el.dispatchEvent(pasteEvent);
  }

  function nextTick() {
    return new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  }

  let isProcessingReplacement = false;

  async function handleContentEditable(el) {
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0 || !selection.isCollapsed) return;
    const range = selection.getRangeAt(0);
    if (range.startContainer.nodeType !== Node.TEXT_NODE) return;
    const textBeforeCaret = range.startContainer.textContent.slice(0, range.startOffset);
    const match = findMatchingShortcut(textBeforeCaret);
    if (!match) return;

    isProcessingReplacement = true;
    try {
      // We're reacting to the 'input' event for the shortcut's own last
      // keystroke. Rich-text editors (Lexical, Draft.js, etc.) reconcile
      // their internal model from that keystroke asynchronously — acting
      // immediately races ahead of it and whatever we do next gets
      // overridden once that reconciliation lands. Let it settle first.
      await nextTick();

      // Grow the selection backward over the shortcut, one character at a
      // time, the same way Shift+ArrowLeft does — this only moves the
      // selection boundary, it never mutates content, so editors stay
      // correctly in sync with it the way they don't with a sequence of
      // separate delete commands.
      for (let i = 0; i < match.shortcut.length; i++) {
        selection.modify('extend', 'backward', 'character');
      }

      // Pasting over a non-collapsed selection replaces it in one atomic
      // operation instead of a delete-then-insert sequence. Rich-text
      // editors implement their own paste handling and call
      // preventDefault(); a false return means one of them took over and
      // inserted the text through its own model.
      const notHandledByPageEditor = pasteText(el, match.body);
      if (!notHandledByPageEditor) return;

      if (document.queryCommandSupported && document.queryCommandSupported('insertText')) {
        document.execCommand('insertText', false, match.body);
      }
    } finally {
      isProcessingReplacement = false;
    }
  }

  document.addEventListener('input', (event) => {
    if (!event.isTrusted) return;
    if (isProcessingReplacement) return;
    if (snippetIndex.size === 0) return;

    const el = event.target;
    if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) {
      handleStandardField(el);
    } else if (el && el.isContentEditable) {
      handleContentEditable(el);
    }
  }, true);
})();
