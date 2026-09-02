/**
 * De popup: één scherm dat altijd eerlijk vertelt wat er aan de hand is.
 *
 * Uitgangspunt is dat een niet-programmeur hier alles uit moet kunnen
 * opmaken. Daarom nooit een kale foutcode, altijd een zin plus een concrete
 * volgende stap -- en nooit doen alsof alles goed staat wanneer de
 * achtergronddienst niet eens antwoordt.
 */

import {
  ERROR,
  OFFLINE,
  OK,
  UNAUTHORIZED,
  getLogs,
  getStatus,
  restart,
  start,
  stop,
  validateCredentials,
} from './api.js';

const el = (id) => document.getElementById(id);

const STATE_LABELS = {
  running: { label: 'Draait', tone: 'good' },
  starting: { label: 'Start op', tone: 'busy' },
  cooldown: { label: 'Herstelt', tone: 'warn' },
  stopped: { label: 'Uit', tone: 'neutral' },
  failed: { label: 'Gestopt door fout', tone: 'bad' },
  unknown: { label: 'Onbekend', tone: 'neutral' },
};

const HEALTH_TONES = {
  READY: 'good',
  WARNING: 'warn',
  OFFLINE: 'warn',
  ERROR: 'bad',
};

function setPill(text, tone) {
  const pill = el('state-pill');
  pill.textContent = text;
  pill.className = `pill pill-${tone}`;
}

function setMessage(message, advice) {
  el('state-message').textContent = message;
  const adviceNode = el('state-advice');
  if (advice) {
    adviceNode.textContent = advice;
    adviceNode.hidden = false;
  } else {
    adviceNode.hidden = true;
  }
}

function setButtonsEnabled(enabled) {
  for (const id of ['btn-start', 'btn-stop', 'btn-restart']) {
    el(id).disabled = !enabled;
  }
}

function showActionResult(text, tone) {
  const node = el('action-result');
  node.textContent = text;
  node.className = `action-result tone-${tone}`;
  node.hidden = false;
}

function renderHealth(report) {
  const list = el('health-list');
  list.textContent = '';

  if (!report || !Array.isArray(report.checks)) {
    const item = document.createElement('li');
    item.className = 'muted';
    item.textContent = 'Geen systeemcontrole beschikbaar.';
    list.append(item);
    return;
  }

  for (const check of report.checks) {
    const item = document.createElement('li');
    item.className = `health-item tone-${HEALTH_TONES[check.status] || 'neutral'}`;

    const name = document.createElement('strong');
    name.textContent = check.component;
    const summary = document.createElement('span');
    summary.textContent = check.summary;
    item.append(name, summary);

    if (check.advice && check.status !== 'READY') {
      const advice = document.createElement('em');
      advice.textContent = check.advice;
      item.append(advice);
    }
    list.append(item);
  }
}

/** Vertaal elke uitkomst van de API naar het scherm. Geeft true bij OK. */
function applyConnectionProblem(result) {
  if (result.kind === OK) {
    return false;
  }
  if (result.kind === OFFLINE) {
    setPill('Niet bereikbaar', 'neutral');
    setMessage(result.message, result.advice);
    setButtonsEnabled(false);
    renderHealth(null);
    return true;
  }
  if (result.kind === UNAUTHORIZED) {
    setPill('Geen toegang', 'warn');
    setMessage(result.message, result.advice);
    setButtonsEnabled(false);
    renderHealth(null);
    return true;
  }
  setPill('Fout', 'bad');
  setMessage(result.message, result.advice);
  setButtonsEnabled(true);
  return true;
}

async function refresh() {
  const result = await getStatus();
  if (applyConnectionProblem(result)) {
    return;
  }

  const bot = result.body.bot || {};
  const descriptor = STATE_LABELS[bot.state] || STATE_LABELS.unknown;
  setPill(descriptor.label, descriptor.tone);

  const supervisor = bot.supervisor || {};
  const health = result.body.health || {};

  let message = supervisor.message || '';
  if (!message) {
    message = bot.running ? 'JARVIS draait en bewaakt de markt.' : 'JARVIS staat uit.';
  }
  let advice = supervisor.advice || '';
  if (!advice && health.overall === 'ERROR') {
    advice = `Dit blokkeert het starten: ${(health.blocking || []).join(', ')}.`;
  }
  setMessage(message, advice);

  setButtonsEnabled(true);
  el('btn-start').disabled = bot.running;
  el('btn-stop').disabled = !bot.running;

  renderHealth(health);
  chrome.runtime.sendMessage({ type: 'refresh-badge' }).catch(() => {});
}

async function runAction(action, busyText) {
  setButtonsEnabled(false);
  showActionResult(busyText, 'busy');
  const result = await action();

  if (result.kind === OK) {
    const body = result.body || {};
    showActionResult(body.message || 'Klaar.', body.ok === false ? 'warn' : 'good');
  } else if (result.kind === OFFLINE || result.kind === UNAUTHORIZED) {
    showActionResult(`${result.message} ${result.advice || ''}`.trim(), 'bad');
  } else {
    showActionResult(`${result.message} ${result.advice || ''}`.trim(), 'bad');
  }

  await refresh();
}

async function showLogs() {
  const name = el('log-name').value;
  const output = el('log-output');
  output.hidden = false;
  output.textContent = 'Ophalen…';

  const result = await getLogs(name, 100);
  if (result.kind !== OK) {
    output.textContent = `${result.message}\n${result.advice || ''}`.trim();
    return;
  }
  const body = result.body || {};
  if (!body.exists) {
    output.textContent = body.message || 'Dit logbestand bestaat nog niet.';
    return;
  }
  output.textContent = (body.lines || []).join('\n') || 'Het logbestand is leeg.';
  output.scrollTop = output.scrollHeight;
}

async function checkCredentials() {
  const node = el('validate-result');
  node.hidden = false;
  node.textContent = 'Controleren bij OpenAI en Coinbase…';

  const result = await validateCredentials();
  if (result.kind !== OK) {
    node.textContent = `${result.message} ${result.advice || ''}`.trim();
    return;
  }
  node.textContent = result.body.message || 'Controle uitgevoerd.';
}

el('btn-start').addEventListener('click', () => runAction(start, 'Starten…'));
el('btn-stop').addEventListener('click', () => runAction(stop, 'Stoppen… dit kan even duren.'));
el('btn-restart').addEventListener('click', () => runAction(restart, 'Herstarten…'));
el('btn-refresh').addEventListener('click', refresh);
el('btn-logs').addEventListener('click', showLogs);
el('btn-validate').addEventListener('click', checkCredentials);
el('btn-options').addEventListener('click', () => chrome.runtime.openOptionsPage());

refresh();
