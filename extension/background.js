/**
 * Service worker: houdt het icoontje in de werkbalk actueel.
 *
 * Doet bewust weinig. Een MV3 service worker wordt door Chrome regelmatig
 * afgesloten, dus hier hoort geen toestand te leven die de gebruiker nodig
 * heeft. De waarheid staat altijd in de lokale control-service; dit bestand
 * vraagt die alleen periodiek op en vertaalt hem naar een kleur.
 */

import { getStatus, OFFLINE, OK, UNAUTHORIZED } from './api.js';

const ALARM_NAME = 'jarvis-status-poll';
const POLL_MINUTES = 1;

const BADGES = {
  running: { text: 'AAN', color: '#1a7f37', title: 'JARVIS draait' },
  cooldown: { text: 'WACHT', color: '#bf8700', title: 'JARVIS herstelt van een storing' },
  starting: { text: '...', color: '#0969da', title: 'JARVIS start op' },
  stopped: { text: 'UIT', color: '#6e7781', title: 'JARVIS draait niet' },
  failed: { text: '!', color: '#cf222e', title: 'JARVIS is gestopt door een fout' },
  offline: { text: '?', color: '#6e7781', title: 'De achtergronddienst is niet bereikbaar' },
  unauthorized: { text: '!', color: '#bf8700', title: 'Toegangssleutel ontbreekt of klopt niet' },
};

async function applyBadge(key) {
  const badge = BADGES[key] || BADGES.offline;
  try {
    await chrome.action.setBadgeText({ text: badge.text });
    await chrome.action.setBadgeBackgroundColor({ color: badge.color });
    await chrome.action.setTitle({ title: `JARVIS Trading Bot — ${badge.title}` });
  } catch (error) {
    // Chrome kan de service worker midden in deze aanroep afsluiten. Dat is
    // geen fout die iemand hoeft te zien; de volgende poll herstelt het.
  }
}

async function refresh() {
  const result = await getStatus();

  if (result.kind === OFFLINE) {
    await applyBadge('offline');
    return;
  }
  if (result.kind === UNAUTHORIZED) {
    await applyBadge('unauthorized');
    return;
  }
  if (result.kind !== OK) {
    await applyBadge('failed');
    return;
  }

  const state = result.body?.bot?.state || 'stopped';
  await applyBadge(state in BADGES ? state : 'stopped');
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create(ALARM_NAME, { periodInMinutes: POLL_MINUTES });
  refresh();
});

chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create(ALARM_NAME, { periodInMinutes: POLL_MINUTES });
  refresh();
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === ALARM_NAME) {
    refresh();
  }
});

// De popup meldt zich zodra hij iets veranderd heeft, zodat het icoontje niet
// tot de volgende minuut achterloopt.
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === 'refresh-badge') {
    refresh().then(() => sendResponse({ ok: true }));
    return true;
  }
  return false;
});
