import {
  ensureInitialized,
  getFolders,
  getSnippets,
  createFolder,
  renameFolder,
  deleteFolder,
  createSnippet,
  updateSnippet,
  deleteSnippet,
  isShortcutTaken,
  validateShortcut,
} from '../shared/storage.js';
import { escapeHTML } from '../shared/utils.js';

let folders = [];
let snippets = [];
let selectedFolderId = null;
let searchQuery = '';
let editingSnippetId = null; // id of a snippet, 'new', or null

const sidebarEl = document.getElementById('folder-list');
const snippetListEl = document.getElementById('snippet-list');
const toolbarTitleEl = document.getElementById('toolbar-title');
const searchInputEl = document.getElementById('search-input');
const newFolderBtn = document.getElementById('new-folder-btn');
const newSnippetBtn = document.getElementById('new-snippet-btn');

async function loadState() {
  await ensureInitialized();
  [folders, snippets] = await Promise.all([getFolders(), getSnippets()]);
  if (!selectedFolderId && folders.length > 0) {
    selectedFolderId = folders[0].id;
  }
}

function snippetCountForFolder(folderId) {
  return snippets.filter((s) => s.folderId === folderId).length;
}

function renderSidebar() {
  sidebarEl.innerHTML = folders
    .map((folder) => {
      const isActive = folder.id === selectedFolderId && !searchQuery;
      return `
        <div class="nav-item ${isActive ? 'active' : ''}">
          <span class="nav-item-name" data-action="select-folder" data-folder-id="${folder.id}">${escapeHTML(folder.name)}</span>
          <span class="nav-badge">${snippetCountForFolder(folder.id)}</span>
          <span class="nav-item-actions">
            <button data-action="rename-folder" data-folder-id="${folder.id}" title="Renombrar">✎</button>
            <button data-action="delete-folder" data-folder-id="${folder.id}" title="Borrar">🗑</button>
          </span>
        </div>
      `;
    })
    .join('');
}

function visibleSnippets() {
  if (searchQuery) {
    const q = searchQuery.toLowerCase();
    return snippets.filter(
      (s) => s.shortcut.toLowerCase().includes(q) || s.body.toLowerCase().includes(q)
    );
  }
  return snippets.filter((s) => s.folderId === selectedFolderId);
}

function renderToolbarTitle() {
  if (searchQuery) {
    toolbarTitleEl.textContent = `Resultados para "${searchQuery}"`;
    return;
  }
  const folder = folders.find((f) => f.id === selectedFolderId);
  toolbarTitleEl.textContent = folder ? folder.name : 'Snippets';
}

function editingCardMarkup(snippet) {
  const isNew = snippet === null;
  const id = isNew ? 'new' : snippet.id;
  const shortcutValue = isNew ? '' : escapeHTML(snippet.shortcut);
  const bodyValue = isNew ? '' : escapeHTML(snippet.body);
  return `
    <div class="snippet-card editing" data-snippet-id="${id}">
      <label class="field-label">Atajo</label>
      <input class="shortcut-input" type="text" placeholder="/miatajo" value="${shortcutValue}" data-field="shortcut">
      <div class="field-error" data-role="error"></div>
      <label class="field-label">Texto</label>
      <textarea class="body-input" rows="4" placeholder="Texto que se va a expandir...">${bodyValue}</textarea>
      <div class="card-actions">
        <button data-action="save-snippet" data-snippet-id="${id}" class="btn-primary">Guardar</button>
        <button data-action="cancel-edit" class="btn-secondary">Cancelar</button>
        ${isNew ? '' : `<button data-action="delete-snippet" data-snippet-id="${id}" class="btn-danger">Borrar</button>`}
      </div>
    </div>
  `;
}

function snippetCardMarkup(snippet) {
  if (editingSnippetId === snippet.id) return editingCardMarkup(snippet);
  const preview = snippet.body.length > 140 ? `${snippet.body.slice(0, 140)}…` : snippet.body;
  return `
    <div class="snippet-card" data-snippet-id="${snippet.id}" data-action="expand-snippet">
      <div class="snippet-shortcut">${escapeHTML(snippet.shortcut)}</div>
      <div class="snippet-preview">${escapeHTML(preview)}</div>
    </div>
  `;
}

function renderSnippetList() {
  const list = visibleSnippets();
  let html = '';
  if (editingSnippetId === 'new') {
    html += editingCardMarkup(null);
  }
  if (list.length === 0 && editingSnippetId !== 'new') {
    html += `<div class="empty">No hay snippets ${searchQuery ? 'que coincidan con la búsqueda' : 'en esta carpeta'} todavía.</div>`;
  } else {
    html += list.map(snippetCardMarkup).join('');
  }
  snippetListEl.innerHTML = html;
}

function render() {
  renderSidebar();
  renderToolbarTitle();
  renderSnippetList();
}

function selectFolder(folderId) {
  selectedFolderId = folderId;
  searchQuery = '';
  searchInputEl.value = '';
  editingSnippetId = null;
  render();
}

async function handleNewFolder() {
  const name = prompt('Nombre de la nueva carpeta:');
  if (!name || !name.trim()) return;
  const folder = await createFolder(name);
  folders = await getFolders();
  selectFolder(folder.id);
}

async function handleRenameFolder(folderId) {
  const folder = folders.find((f) => f.id === folderId);
  if (!folder) return;
  const name = prompt('Nuevo nombre:', folder.name);
  if (!name || !name.trim()) return;
  await renameFolder(folderId, name);
  folders = await getFolders();
  render();
}

async function handleDeleteFolder(folderId) {
  const folder = folders.find((f) => f.id === folderId);
  if (!folder) return;
  const count = snippetCountForFolder(folderId);
  const confirmed = confirm(
    `¿Borrar la carpeta "${folder.name}" y sus ${count} snippet(s)? Esta acción no se puede deshacer.`
  );
  if (!confirmed) return;
  await deleteFolder(folderId);
  [folders, snippets] = await Promise.all([getFolders(), getSnippets()]);
  if (selectedFolderId === folderId) {
    selectedFolderId = folders.length > 0 ? folders[0].id : null;
  }
  render();
}

function showFieldError(cardEl, message) {
  const errorEl = cardEl.querySelector('[data-role="error"]');
  if (errorEl) errorEl.textContent = message || '';
}

async function handleSaveSnippet(snippetId, cardEl) {
  const shortcutInput = cardEl.querySelector('[data-field="shortcut"]');
  const bodyInput = cardEl.querySelector('textarea');
  const shortcut = shortcutInput.value;
  const body = bodyInput.value;

  const validationError = validateShortcut(shortcut);
  if (validationError) {
    showFieldError(cardEl, validationError);
    return;
  }
  const excludeId = snippetId === 'new' ? undefined : snippetId;
  if (await isShortcutTaken(shortcut, excludeId)) {
    showFieldError(cardEl, 'Ya existe un snippet con ese atajo.');
    return;
  }

  if (snippetId === 'new') {
    await createSnippet({ shortcut, body, folderId: selectedFolderId });
  } else {
    await updateSnippet(snippetId, { shortcut, body, folderId: selectedFolderId });
  }
  snippets = await getSnippets();
  editingSnippetId = null;
  render();
}

async function handleDeleteSnippet(snippetId) {
  const confirmed = confirm('¿Borrar este snippet?');
  if (!confirmed) return;
  await deleteSnippet(snippetId);
  snippets = await getSnippets();
  editingSnippetId = null;
  render();
}

sidebarEl.addEventListener('click', (event) => {
  const target = event.target.closest('[data-action]');
  if (!target) return;
  const action = target.dataset.action;
  const folderId = target.dataset.folderId;
  if (action === 'select-folder') selectFolder(folderId);
  if (action === 'rename-folder') handleRenameFolder(folderId);
  if (action === 'delete-folder') handleDeleteFolder(folderId);
});

snippetListEl.addEventListener('click', (event) => {
  const target = event.target.closest('[data-action]');
  if (!target) return;
  const action = target.dataset.action;
  const snippetId = target.dataset.snippetId;
  const cardEl = target.closest('.snippet-card');

  if (action === 'expand-snippet') {
    editingSnippetId = snippetId;
    render();
  } else if (action === 'save-snippet') {
    handleSaveSnippet(snippetId, cardEl);
  } else if (action === 'cancel-edit') {
    editingSnippetId = null;
    render();
  } else if (action === 'delete-snippet') {
    handleDeleteSnippet(snippetId);
  }
});

newFolderBtn.addEventListener('click', handleNewFolder);
newSnippetBtn.addEventListener('click', () => {
  searchQuery = '';
  searchInputEl.value = '';
  editingSnippetId = 'new';
  render();
});

searchInputEl.addEventListener('input', (event) => {
  searchQuery = event.target.value.trim();
  editingSnippetId = null;
  render();
});

(async () => {
  await loadState();
  render();
})();
