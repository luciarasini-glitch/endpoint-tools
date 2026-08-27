import { STORAGE_KEYS, SCHEMA_VERSION, DEFAULT_FOLDER_NAME } from './constants.js';
import { generateId } from './utils.js';

const DEV_PREFIX = 'tc_dev_';

function hasExtensionStorage() {
  return typeof chrome !== 'undefined' && !!(chrome.storage && chrome.storage.local);
}

function get(keys) {
  if (hasExtensionStorage()) {
    return new Promise((resolve) => chrome.storage.local.get(keys, resolve));
  }
  const keyList = Array.isArray(keys) ? keys : [keys];
  const result = {};
  keyList.forEach((key) => {
    const raw = window.localStorage.getItem(DEV_PREFIX + key);
    if (raw !== null) result[key] = JSON.parse(raw);
  });
  return Promise.resolve(result);
}

function set(items) {
  if (hasExtensionStorage()) {
    return new Promise((resolve) => chrome.storage.local.set(items, resolve));
  }
  Object.entries(items).forEach(([key, value]) => {
    window.localStorage.setItem(DEV_PREFIX + key, JSON.stringify(value));
  });
  return Promise.resolve();
}

export async function ensureInitialized() {
  const data = await get([STORAGE_KEYS.SCHEMA_VERSION]);
  if (data[STORAGE_KEYS.SCHEMA_VERSION]) return;

  const defaultFolder = {
    id: generateId(),
    name: DEFAULT_FOLDER_NAME,
    createdAt: Date.now(),
    updatedAt: Date.now(),
  };

  await set({
    [STORAGE_KEYS.SCHEMA_VERSION]: SCHEMA_VERSION,
    [STORAGE_KEYS.FOLDERS]: [defaultFolder],
    [STORAGE_KEYS.SNIPPETS]: [],
  });
}

export async function getFolders() {
  const data = await get([STORAGE_KEYS.FOLDERS]);
  return data[STORAGE_KEYS.FOLDERS] || [];
}

export async function getSnippets() {
  const data = await get([STORAGE_KEYS.SNIPPETS]);
  return data[STORAGE_KEYS.SNIPPETS] || [];
}

async function saveFolders(folders) {
  await set({ [STORAGE_KEYS.FOLDERS]: folders });
}

async function saveSnippets(snippets) {
  await set({ [STORAGE_KEYS.SNIPPETS]: snippets });
}

export async function createFolder(name) {
  const folders = await getFolders();
  const folder = {
    id: generateId(),
    name: name.trim(),
    createdAt: Date.now(),
    updatedAt: Date.now(),
  };
  folders.push(folder);
  await saveFolders(folders);
  return folder;
}

export async function renameFolder(id, name) {
  const folders = await getFolders();
  const folder = folders.find((f) => f.id === id);
  if (!folder) return;
  folder.name = name.trim();
  folder.updatedAt = Date.now();
  await saveFolders(folders);
}

export async function deleteFolder(id) {
  const [folders, snippets] = await Promise.all([getFolders(), getSnippets()]);
  const remainingFolders = folders.filter((f) => f.id !== id);
  const remainingSnippets = snippets.filter((s) => s.folderId !== id);
  await Promise.all([saveFolders(remainingFolders), saveSnippets(remainingSnippets)]);
}

function normalizeShortcut(shortcut) {
  return shortcut.trim();
}

export async function isShortcutTaken(shortcut, excludeSnippetId) {
  const normalized = normalizeShortcut(shortcut);
  const snippets = await getSnippets();
  return snippets.some((s) => s.id !== excludeSnippetId && s.shortcut === normalized);
}

export function validateShortcut(shortcut) {
  const normalized = normalizeShortcut(shortcut);
  if (!normalized) return 'El atajo no puede estar vacío.';
  if (/\s/.test(normalized)) return 'El atajo no puede contener espacios.';
  return null;
}

export async function createSnippet({ shortcut, body, folderId }) {
  const snippets = await getSnippets();
  const snippet = {
    id: generateId(),
    shortcut: normalizeShortcut(shortcut),
    body,
    folderId,
    createdAt: Date.now(),
    updatedAt: Date.now(),
  };
  snippets.push(snippet);
  await saveSnippets(snippets);
  return snippet;
}

export async function updateSnippet(id, { shortcut, body, folderId }) {
  const snippets = await getSnippets();
  const snippet = snippets.find((s) => s.id === id);
  if (!snippet) return;
  snippet.shortcut = normalizeShortcut(shortcut);
  snippet.body = body;
  snippet.folderId = folderId;
  snippet.updatedAt = Date.now();
  await saveSnippets(snippets);
}

export async function deleteSnippet(id) {
  const snippets = await getSnippets();
  await saveSnippets(snippets.filter((s) => s.id !== id));
}
