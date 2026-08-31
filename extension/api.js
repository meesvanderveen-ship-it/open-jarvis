/**
 * Enige plek waar de extensie met de lokale control-service praat.
 *
 * Belangrijk voor de veiligheid: hier staan geen API-sleutels van Coinbase of
 * OpenAI, en die komen hier ook nooit langs. De extensie kent alleen het adres
 * van de lokale service en een toegangssleutel die uitsluitend geldig is voor
 * die service op deze pc. Alle handelslogica en alle echte secrets blijven in
 * het Python-proces.
 *
 * Elke fout wordt vertaald naar een van drie toestanden, want die betekenen
 * iets heel verschillends voor de gebruiker:
 *   OFFLINE       de backend draait niet (JARVIS is niet gestart)
 *   UNAUTHORIZED  de backend draait, maar de sleutel klopt niet
 *   ERROR         de backend antwoordde met een echte fout
 */

export const DEFAULT_BASE_URL = 'http://127.0.0.1:8770';
export const API_PREFIX = '/api/control';

export const OFFLINE = 'OFFLINE';
export const UNAUTHORIZED = 'UNAUTHORIZED';
export const ERROR = 'ERROR';
export const OK = 'OK';

/** Hoe lang we op de lokale service wachten. Lokaal mag dit kort zijn. */
const REQUEST_TIMEOUT_MS = 8000;
/** Stoppen kan een lopende handelscyclus moeten afwachten. */
const SLOW_REQUEST_TIMEOUT_MS = 60000;

export async function loadSettings() {
  const stored = await chrome.storage.local.get(['baseUrl', 'token']);
  return {
    baseUrl: (stored.baseUrl || DEFAULT_BASE_URL).replace(/\/+$/, ''),
    token: stored.token || '',
  };
}

export async function saveSettings({ baseUrl, token }) {
  await chrome.storage.local.set({
    baseUrl: (baseUrl || DEFAULT_BASE_URL).replace(/\/+$/, ''),
    token: token || '',
  });
}

/**
 * Voer één aanroep uit en geef altijd een object met een `kind` terug.
 * Deze functie gooit nooit: de popup moet elke uitkomst kunnen tonen.
 */
export async function call(path, { method = 'GET', slow = false } = {}) {
  const { baseUrl, token } = await loadSettings();

  if (!token) {
    return {
      kind: UNAUTHORIZED,
      message: 'Er is nog geen toegangssleutel ingesteld.',
      advice: 'Open de instellingen en plak de sleutel uit state/control_token.txt.',
    };
  }

  const controller = new AbortController();
  const timeout = setTimeout(
    () => controller.abort(),
    slow ? SLOW_REQUEST_TIMEOUT_MS : REQUEST_TIMEOUT_MS,
  );

  let response;
  try {
    response = await fetch(`${baseUrl}${API_PREFIX}${path}`, {
      method,
      headers: { Authorization: `Bearer ${token}` },
      signal: controller.signal,
    });
  } catch (error) {
    // Een mislukte fetch naar 127.0.0.1 betekent vrijwel altijd: er luistert
    // niets. Dat is iets anders dan een verkeerde sleutel, en dat verschil
    // moet de gebruiker te zien krijgen.
    return {
      kind: OFFLINE,
      message: 'JARVIS draait nu niet op deze pc.',
      advice: `De achtergronddienst op ${baseUrl} antwoordt niet. Start JARVIS met START-JARVIS.bat.`,
      cause: error && error.name === 'AbortError' ? 'timeout' : 'geen verbinding',
    };
  } finally {
    clearTimeout(timeout);
  }

  let body = null;
  try {
    body = await response.json();
  } catch (error) {
    body = null;
  }

  if (response.status === 401 || response.status === 503) {
    const detail = (body && body.detail) || {};
    return {
      kind: UNAUTHORIZED,
      message: detail.message || 'De toegangssleutel werd niet geaccepteerd.',
      advice: detail.advice || 'Open de instellingen en plak de sleutel uit state/control_token.txt.',
    };
  }

  if (!response.ok) {
    const detail = (body && body.detail) || body || {};
    return {
      kind: ERROR,
      status: response.status,
      message: detail.message || body?.message || `De service antwoordde met foutcode ${response.status}.`,
      advice: detail.advice || body?.detail || '',
      body,
    };
  }

  return { kind: OK, body };
}

export const getHealth = async () => {
  // /health heeft geen sleutel nodig; zo kan de extensie 'draait de service'
  // onderscheiden van 'sleutel klopt niet', ook als er nog niets ingesteld is.
  const { baseUrl } = await loadSettings();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(`${baseUrl}${API_PREFIX}/health`, { signal: controller.signal });
    if (!response.ok) {
      return { kind: ERROR, status: response.status, message: 'De service antwoordt, maar niet goed.' };
    }
    return { kind: OK, body: await response.json() };
  } catch (error) {
    return {
      kind: OFFLINE,
      message: 'JARVIS draait nu niet op deze pc.',
      advice: `De achtergronddienst op ${baseUrl} antwoordt niet. Start JARVIS met START-JARVIS.bat.`,
    };
  } finally {
    clearTimeout(timeout);
  }
};

export const getStatus = () => call('/status');
export const start = () => call('/start', { method: 'POST' });
export const stop = () => call('/stop', { method: 'POST', slow: true });
export const restart = () => call('/restart', { method: 'POST', slow: true });
export const getLogs = (name = 'bot', lines = 100) =>
  call(`/logs?name=${encodeURIComponent(name)}&lines=${lines}`);
export const validateCredentials = () => call('/validate-credentials', { method: 'POST', slow: true });
