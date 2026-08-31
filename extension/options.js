/**
 * Instellingenpagina: adres en toegangssleutel van de lokale service.
 *
 * De testknop is het belangrijkste onderdeel. Zonder die knop weet iemand die
 * een sleutel verkeerd plakt pas veel later dat er iets mis is, en dan lijkt
 * het alsof de bot zelf stuk is.
 */

import { DEFAULT_BASE_URL, ERROR, OFFLINE, OK, UNAUTHORIZED, getStatus, loadSettings, saveSettings } from './api.js';

const el = (id) => document.getElementById(id);

function show(text, tone) {
  const node = el('result');
  node.textContent = text;
  node.className = `message tone-${tone}`;
  node.hidden = false;
}

async function restore() {
  const settings = await loadSettings();
  el('base-url').value = settings.baseUrl || DEFAULT_BASE_URL;
  el('token').value = settings.token || '';
}

async function save() {
  const baseUrl = el('base-url').value.trim() || DEFAULT_BASE_URL;
  const token = el('token').value.trim();

  if (!/^https?:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/i.test(baseUrl.replace(/\/+$/, ''))) {
    // Bewust streng: deze extensie hoort nooit met een server op internet te
    // praten. Een adres buiten de eigen pc is vrijwel zeker een vergissing.
    show(
      'Het adres moet naar je eigen pc wijzen, bijvoorbeeld http://127.0.0.1:8770.',
      'bad',
    );
    return;
  }

  await saveSettings({ baseUrl, token });
  show('Opgeslagen.', 'good');
}

async function test() {
  await save();
  if (el('result').classList.contains('tone-bad')) {
    return;
  }

  show('Verbinding testen…', 'busy');
  const result = await getStatus();

  if (result.kind === OK) {
    const state = result.body?.bot?.state || 'onbekend';
    show(`Verbonden. JARVIS meldt de toestand: ${state}.`, 'good');
    return;
  }
  if (result.kind === OFFLINE) {
    show(`${result.message} ${result.advice}`, 'warn');
    return;
  }
  if (result.kind === UNAUTHORIZED) {
    show(`${result.message} ${result.advice}`, 'bad');
    return;
  }
  show(result.message || 'Onbekende fout.', 'bad');
}

el('btn-save').addEventListener('click', save);
el('btn-test').addEventListener('click', test);
el('show-token').addEventListener('change', (event) => {
  el('token').type = event.target.checked ? 'text' : 'password';
});

restore();
