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

/**
 * Hoe vaak een *opvraging* opnieuw geprobeerd wordt voordat we concluderen dat
 * de achtergronddienst niet draait.
 *
 * Zonder dit vertelt één hapering -- de service die net opstart, een trage
 * eerste aanroep waarin de handelsmotor nog geladen moet worden, een browser
 * die de verbinding afknijpt -- de gebruiker meteen dat JARVIS niet draait.
 * Dat is precies de verkeerde conclusie, en dezelfde fout die de backend aan
 * de Python-kant met retries en backoff vermijdt.
 *
 * Alleen voor GET. Een start-, stop- of herstartverzoek wordt NOOIT herhaald:
 * een tweede poging zou een tweede bot kunnen starten, en dat is het ergste
 * wat hier kan gebeuren.
 */
const GET_RETRIES = 2;
const RETRY_DELAYS_MS = [300, 900];

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

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

  // Alleen opvragingen mogen herhaald worden; zie GET_RETRIES.
  const attempts = method === 'GET' ? GET_RETRIES + 1 : 1;
  let response;
  let lastError;

  for (let attempt = 0; attempt < attempts; attempt += 1) {
    if (attempt > 0) {
      await sleep(RETRY_DELAYS_MS[attempt - 1] ?? RETRY_DELAYS_MS[RETRY_DELAYS_MS.length - 1]);
    }

    const controller = new AbortController();
    const timeout = setTimeout(
      () => controller.abort(),
      slow ? SLOW_REQUEST_TIMEOUT_MS : REQUEST_TIMEOUT_MS,
    );
    try {
      response = await fetch(`${baseUrl}${API_PREFIX}${path}`, {
        method,
        headers: { Authorization: `Bearer ${token}` },
        signal: controller.signal,
      });
      lastError = null;
      break;
    } catch (error) {
      lastError = error;
    } finally {
      clearTimeout(timeout);
    }
  }

  if (lastError) {
    // Pas na alle pogingen concluderen dat er niets luistert. Dat is iets
    // anders dan een verkeerde sleutel, en dat verschil moet de gebruiker
    // te zien krijgen.
    return {
      kind: OFFLINE,
      message: 'JARVIS draait nu niet op deze pc.',
      advice: `De achtergronddienst op ${baseUrl} antwoordt niet. Start JARVIS met START-JARVIS.bat.`,
      cause: lastError && lastError.name === 'AbortError' ? 'timeout' : 'geen verbinding',
      attempts,
    };
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

/**
 * Draait de achtergronddienst überhaupt?
 *
 * /health vraagt geen sleutel. Daardoor kan de extensie "de dienst ligt eruit"
 * onderscheiden van "je sleutel klopt niet" -- óók als er nog helemaal geen
 * sleutel ingesteld is. Zonder dit onderscheid krijgt iemand die de dienst
 * niet gestart heeft te horen dat zijn sleutel verkeerd is, en gaat hij een
 * probleem oplossen dat er niet is.
 */
export const getHealth = async () => {
  const { baseUrl } = await loadSettings();
  let response;
  let lastError;

  for (let attempt = 0; attempt <= GET_RETRIES; attempt += 1) {
    if (attempt > 0) {
      await sleep(RETRY_DELAYS_MS[attempt - 1] ?? RETRY_DELAYS_MS[RETRY_DELAYS_MS.length - 1]);
    }
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      response = await fetch(`${baseUrl}${API_PREFIX}/health`, { signal: controller.signal });
      lastError = null;
      break;
    } catch (error) {
      lastError = error;
    } finally {
      clearTimeout(timeout);
    }
  }

  if (lastError) {
    return {
      kind: OFFLINE,
      message: 'JARVIS draait nu niet op deze pc.',
      advice: `De achtergronddienst op ${baseUrl} antwoordt niet. Start JARVIS met START-JARVIS.bat.`,
    };
  }
  if (!response.ok) {
    return { kind: ERROR, status: response.status, message: 'De service antwoordt, maar niet goed.' };
  }
  return { kind: OK, body: await response.json() };
};

export const getStatus = () => call('/status');
export const start = () => call('/start', { method: 'POST' });
export const stop = () => call('/stop', { method: 'POST', slow: true });
export const restart = () => call('/restart', { method: 'POST', slow: true });
export const getLogs = (name = 'bot', lines = 100) =>
  call(`/logs?name=${encodeURIComponent(name)}&lines=${lines}`);
export const validateCredentials = () => call('/validate-credentials', { method: 'POST', slow: true });
