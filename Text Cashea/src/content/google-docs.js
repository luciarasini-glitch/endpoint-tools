(() => {
  // Google Docs doesn't render the document as a normal contenteditable —
  // it captures real keystrokes through a hidden, offscreen iframe
  // (docs-texteventtarget-iframe) containing a tiny contenteditable div that
  // Docs keeps nearly empty (just zero-width space placeholders) at all
  // times, applying each keystroke to its own internal document model and
  // clearing the div right after. Because of that we can't read "the text
  // before the caret" the way the rest of the extension does — we track our
  // own rolling buffer of recently typed characters from the input events
  // themselves instead. Docs also replaces this div at some point after
  // load, so we delegate from the iframe's document rather than binding to
  // one captured element reference.
  const STORAGE_KEY = 'tc_snippets';
  let snippetIndex = new Map();
  let maxShortcutLength = 0;

  function rebuildIndex(snippets) {
    snippetIndex = new Map((snippets || []).map((s) => [s.shortcut, s.body]));
    maxShortcutLength = 0;
    for (const shortcut of snippetIndex.keys()) {
      if (shortcut.length > maxShortcutLength) maxShortcutLength = shortcut.length;
    }
  }

  chrome.storage.local.get(STORAGE_KEY, (data) => rebuildIndex(data[STORAGE_KEY]));
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === 'local' && changes[STORAGE_KEY]) rebuildIndex(changes[STORAGE_KEY].newValue);
  });

  function isDocsTextTarget(el) {
    return !!el
      && el.nodeType === 1
      && el.getAttribute('contenteditable') === 'true'
      && el.getAttribute('role') === 'textbox';
  }

  function findMatchingShortcut(buffer) {
    for (const [shortcut, body] of snippetIndex) {
      if (!shortcut || !buffer.endsWith(shortcut)) continue;
      // If the shortcut fills the whole buffer we don't know what real
      // character (if any) precedes it in the document, since the buffer
      // only covers what we've personally observed being typed — accept it
      // rather than reject on unknown context.
      const charBeforeIndex = buffer.length - shortcut.length - 1;
      const charBefore = charBeforeIndex >= 0 ? buffer[charBeforeIndex] : undefined;
      if (charBefore !== undefined && /\w/.test(charBefore)) continue;
      return { shortcut, body };
    }
    return null;
  }

  function pasteText(el, text) {
    const dataTransfer = new DataTransfer();
    dataTransfer.setData('text/plain', text);
    el.dispatchEvent(new ClipboardEvent('paste', {
      clipboardData: dataTransfer,
      bubbles: true,
      cancelable: true,
    }));
  }

  function backspace(el, times) {
    for (let i = 0; i < times; i++) {
      el.dispatchEvent(new KeyboardEvent('keydown', {
        key: 'Backspace',
        code: 'Backspace',
        keyCode: 8,
        which: 8,
        bubbles: true,
        cancelable: true,
      }));
    }
  }

  function nextTick() {
    return new Promise((resolve) => setTimeout(resolve, 0));
  }

  let buffer = '';
  let isProcessingReplacement = false;

  // Docs never fires a native 'input' event on this element for real typing
  // — it reads keydown directly and updates its own document model itself,
  // without going through the browser's native contenteditable insertion
  // path. So we build our buffer from raw keydown, the same signal Docs
  // itself is reading.
  document.addEventListener('keydown', (event) => {
    const el = event.target;
    if (!isDocsTextTarget(el)) return;
    if (!event.isTrusted) return;
    if (isProcessingReplacement) return;
    if (snippetIndex.size === 0) return;

    if (event.key === 'Backspace') {
      buffer = buffer.slice(0, -1);
      return;
    }

    const isPrintableKey = event.key && event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey;
    if (!isPrintableKey) {
      // Arrows, Enter, shortcuts, etc. can move the caret or otherwise
      // change context — our buffer can no longer be trusted to reflect
      // what precedes the caret after one of those.
      buffer = '';
      return;
    }

    buffer += event.key;
    if (buffer.length > maxShortcutLength) {
      buffer = buffer.slice(buffer.length - maxShortcutLength);
    }

    const match = findMatchingShortcut(buffer);
    if (!match) return;

    isProcessingReplacement = true;
    buffer = '';
    // Let Docs finish applying this very keystroke to its own document
    // model before we start reversing it — acting synchronously races
    // ahead of that and corrupts the result.
    nextTick().then(() => {
      try {
        backspace(el, match.shortcut.length);
        pasteText(el, match.body);
      } finally {
        isProcessingReplacement = false;
      }
    });
  }, true);
})();
