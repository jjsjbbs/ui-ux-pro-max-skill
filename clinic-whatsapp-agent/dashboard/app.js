const API = window.location.origin;

// ── State ────────────────────────────────────────────────────────────────────
let currentPage = 'dashboard';
let selectedPhone = null;
let chatLoading = false;
let autoRefreshTimer = null;

// ── Stage config ─────────────────────────────────────────────────────────────
const STAGES = {
  welcome:          { label: 'Nuevo',           col: 'nuevo',       color: '#0891B2', bg: '#E0F7FA' },
  detect_treatment: { label: 'Nuevo',           col: 'nuevo',       color: '#0891B2', bg: '#E0F7FA' },
  qualify_problem:  { label: 'Cualificando',    col: 'cualificando',color: '#D97706', bg: '#FEF3C7' },
  qualify_duration: { label: 'Cualificando',    col: 'cualificando',color: '#D97706', bg: '#FEF3C7' },
  qualify_previous: { label: 'Cualificando',    col: 'cualificando',color: '#D97706', bg: '#FEF3C7' },
  qualify_urgency:  { label: 'Cualificando',    col: 'cualificando',color: '#D97706', bg: '#FEF3C7' },
  request_location: { label: 'Calificado',      col: 'calificado',  color: '#16A34A', bg: '#DCFCE7' },
  clinic_match:     { label: 'Calificado',      col: 'calificado',  color: '#16A34A', bg: '#DCFCE7' },
  show_schedule:    { label: 'Cita en proceso', col: 'cita',        color: '#7C3AED', bg: '#EDE9FE' },
  booking_confirm:  { label: 'Cita en proceso', col: 'cita',        color: '#7C3AED', bg: '#EDE9FE' },
  completed:        { label: 'Completado',      col: 'completado',  color: '#64748B', bg: '#F1F5F9' },
  disqualified:     { label: 'No califica',     col: 'completado',  color: '#DC2626', bg: '#FEE2E2' },
};

const STAGE_COLS = ['nuevo', 'cualificando', 'calificado', 'cita', 'completado'];
const SPECIALTY_COLORS = {
  'Medicina Capilar':       '#0891B2',
  'Medicina Estética':      '#9333EA',
  'Odontología':            '#0D9488',
  'Fisioterapia':           '#EA580C',
  'Dermatología':           '#BE185D',
  'Nutrición y Dietética':  '#16A34A',
  'Psicología':             '#7C3AED',
  'Medicina General':       '#2563EB',
};

function specialtyBadge(specialty) {
  const color = SPECIALTY_COLORS[specialty] || '#0891B2';
  return `<span class="badge" style="background:${color}18;color:${color}">${specialty || '—'}</span>`;
}

function stageBadge(stage) {
  const s = STAGES[stage] || { label: stage, color: '#64748B', bg: '#F1F5F9' };
  return `<span class="badge" style="background:${s.bg};color:${s.color}">${s.label}</span>`;
}

function timeAgo(isoStr) {
  if (!isoStr) return '—';
  const diff = Date.now() - new Date(isoStr).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return 'ahora';
  if (m < 60) return `hace ${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `hace ${h}h`;
  return `hace ${Math.floor(h/24)}d`;
}

// ── Navigation ────────────────────────────────────────────────────────────────
function navigate(page) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  const pageEl = document.getElementById('page-' + page);
  const navEl = document.querySelector(`[data-page="${page}"]`);
  if (pageEl) pageEl.classList.add('active');
  if (navEl) navEl.classList.add('active');
  currentPage = page;

  const titles = {
    dashboard: 'Panel General',
    leads: 'Gestión de Leads',
    pacientes: 'Pacientes',
    centros: 'Centros',
    simulador: 'Simulador WhatsApp',
  };
  document.getElementById('topbar-title').textContent = titles[page] || page;
  loadPage(page);
}

function loadPage(page) {
  if (page === 'dashboard') loadDashboard();
  else if (page === 'leads') loadLeads();
  else if (page === 'pacientes') loadPacientes();
  else if (page === 'centros') loadCentros();
}

// ── Dashboard page ────────────────────────────────────────────────────────────
async function loadDashboard() {
  try {
    const [statsRes, sessRes] = await Promise.all([
      fetch(`${API}/api/stats`), fetch(`${API}/api/sessions`)
    ]);
    const stats = await statsRes.json();
    const { sessions } = await sessRes.json();

    animateNumber('stat-total', stats.total_conversations || 0);
    animateNumber('stat-qualified', stats.qualified || 0);
    animateNumber('stat-booked', stats.booked || 0);
    document.getElementById('stat-conversion').textContent = (stats.conversion_rate || 0) + '%';

    renderFunnel(stats);
    renderActivity(sessions.slice(0, 8));
    renderMiniKanban(sessions);
  } catch(e) {
    console.warn('Dashboard load error', e);
  }
}

function animateNumber(id, target) {
  const el = document.getElementById(id);
  if (!el) return;
  let current = 0;
  const step = Math.max(1, Math.ceil(target / 30));
  const timer = setInterval(() => {
    current = Math.min(current + step, target);
    el.textContent = current;
    if (current >= target) clearInterval(timer);
  }, 40);
}

function renderFunnel(stats) {
  const el = document.getElementById('funnel-chart');
  if (!el) return;
  const total = stats.total_conversations || 1;
  const stages = [
    { label: 'Conversaciones',   val: stats.total_conversations || 0, color: '#0891B2' },
    { label: 'Cualificando',     val: (stats.by_stage?.qualify_problem || 0) + (stats.by_stage?.qualify_duration || 0), color: '#D97706' },
    { label: 'Calificados',      val: stats.qualified || 0, color: '#16A34A' },
    { label: 'Cita agendada',    val: stats.booked || 0, color: '#7C3AED' },
  ];
  el.innerHTML = stages.map(s => {
    const pct = Math.max(8, Math.round((s.val / total) * 100));
    return `<div class="funnel-row">
      <span class="funnel-label">${s.label}</span>
      <div class="funnel-bar-wrap">
        <div class="funnel-bar" style="width:${pct}%;background:${s.color}">
          <span>${s.val}</span>
        </div>
      </div>
    </div>`;
  }).join('');
}

function renderActivity(sessions) {
  const el = document.getElementById('activity-feed');
  if (!el) return;
  if (!sessions.length) { el.innerHTML = '<p style="color:var(--text-secondary);font-size:13px;padding:10px 0">Sin actividad reciente</p>'; return; }
  el.innerHTML = sessions.map(s => {
    const p = s.patient || {};
    const stage = STAGES[s.stage] || {};
    return `<div class="activity-item">
      <div class="activity-icon">
        <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/></svg>
      </div>
      <div>
        <div class="activity-text"><strong>${p.name || s.phone}</strong> — ${p.problem || 'Nueva consulta'}</div>
        <div class="activity-time">${stageBadge(s.stage)} · ${timeAgo(s.updated_at)}</div>
      </div>
    </div>`;
  }).join('');
}

function renderMiniKanban(sessions) {
  const el = document.getElementById('mini-kanban');
  if (!el) return;
  const byCols = {};
  STAGE_COLS.forEach(c => byCols[c] = []);
  sessions.forEach(s => {
    const col = (STAGES[s.stage] || {}).col || 'nuevo';
    byCols[col].push(s);
  });
  const colLabels = { nuevo: 'Nuevo', cualificando: 'Cualificando', calificado: 'Calificado', cita: 'Cita', completado: 'Cerrado' };
  el.innerHTML = STAGE_COLS.map(col => `
    <div class="kanban-col col-${col}">
      <div class="kanban-col-header">
        <span class="kanban-col-title">${colLabels[col]}</span>
        <span class="kanban-count">${byCols[col].length}</span>
      </div>
      <div class="kanban-cards">
        ${byCols[col].slice(0,4).map(s => miniLeadCard(s)).join('')}
        ${byCols[col].length > 4 ? `<div style="font-size:11px;color:var(--text-secondary);text-align:center;padding:4px">+${byCols[col].length-4} más</div>` : ''}
      </div>
    </div>`).join('');
}

function miniLeadCard(s) {
  const p = s.patient || {};
  const urg = p.urgency || 'low';
  return `<div class="lead-card" onclick="openLeadModal('${s.phone}')">
    <div class="lead-name">${p.name || s.phone}</div>
    <div class="lead-problem">${p.problem || 'Sin descripción'}</div>
    <div class="lead-meta">
      ${p.specialty ? `<span class="lead-specialty">${p.specialty}</span>` : '<span></span>'}
      <div style="display:flex;align-items:center;gap:5px">
        <div class="lead-urgency urgency-${urg}"></div>
        <span class="lead-time">${timeAgo(s.updated_at)}</span>
      </div>
    </div>
  </div>`;
}

// ── Leads page ────────────────────────────────────────────────────────────────
async function loadLeads() {
  try {
    const { sessions } = await (await fetch(`${API}/api/sessions`)).json();
    const byCols = {};
    STAGE_COLS.forEach(c => byCols[c] = []);
    sessions.forEach(s => {
      const col = (STAGES[s.stage] || {}).col || 'nuevo';
      byCols[col].push(s);
    });
    const colLabels = { nuevo: 'Nuevo', cualificando: 'Cualificando', calificado: 'Calificado', cita: 'Cita confirmada', completado: 'Cerrado' };
    const board = document.getElementById('kanban-board');
    if (!board) return;
    board.innerHTML = STAGE_COLS.map(col => `
      <div class="kanban-col col-${col}">
        <div class="kanban-col-header">
          <span class="kanban-col-title">${colLabels[col]}</span>
          <span class="kanban-count">${byCols[col].length}</span>
        </div>
        <div class="kanban-cards" id="col-${col}">
          ${byCols[col].length === 0 ? '<div style="font-size:12px;color:var(--text-secondary);text-align:center;padding:20px 0">Sin leads</div>' : ''}
          ${byCols[col].map(s => fullLeadCard(s)).join('')}
        </div>
      </div>`).join('');
  } catch(e) { console.warn('Leads error', e); }
}

function fullLeadCard(s) {
  const p = s.patient || {};
  const urg = p.urgency || 'low';
  return `<div class="lead-card" onclick="openLeadModal('${s.phone}')">
    <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:4px">
      <div class="lead-name">${p.name || s.phone}</div>
      <div class="lead-urgency urgency-${urg}" style="margin-top:3px"></div>
    </div>
    <div class="lead-problem">${p.problem || 'Sin descripción'}</div>
    ${p.specialty ? `<div style="margin:5px 0">${specialtyBadge(p.specialty)}</div>` : ''}
    <div class="lead-meta">
      <span class="lead-time">${s.phone}</span>
      <span class="lead-time">${timeAgo(s.updated_at)}</span>
    </div>
    ${p.city ? `<div style="font-size:11px;color:var(--text-secondary);margin-top:4px">📍 ${p.city}</div>` : ''}
  </div>`;
}

// ── Pacientes page ────────────────────────────────────────────────────────────
async function loadPacientes() {
  try {
    const { sessions } = await (await fetch(`${API}/api/sessions`)).json();
    const tbody = document.getElementById('pacientes-tbody');
    if (!tbody) return;
    if (!sessions.length) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:30px;color:var(--text-secondary)">Sin pacientes registrados</td></tr>';
      return;
    }
    tbody.innerHTML = sessions.map(s => {
      const p = s.patient || {};
      return `<tr onclick="openLeadModal('${s.phone}')">
        <td><strong>${p.name || '—'}</strong></td>
        <td>${s.phone}</td>
        <td>${p.specialty ? specialtyBadge(p.specialty) : '—'}</td>
        <td>${p.problem ? `<span title="${p.problem}" style="max-width:180px;display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${p.problem}</span>` : '—'}</td>
        <td>${stageBadge(s.stage)}</td>
        <td>${p.city || '—'}</td>
        <td>${timeAgo(s.updated_at)}</td>
      </tr>`;
    }).join('');
  } catch(e) { console.warn('Pacientes error', e); }
}

// ── Centros page ──────────────────────────────────────────────────────────────
async function loadCentros() {
  try {
    const data = await (await fetch(`${API}/api/clinic`)).json();
    document.getElementById('clinic-name-display').textContent = data.name;
    document.getElementById('clinic-type-display').textContent = data.type;
    const grid = document.getElementById('centros-grid');
    if (!grid) return;
    grid.innerHTML = data.locations.map(loc => `
      <div class="card">
        <div class="card-header">
          <div>
            <div class="card-title">${loc.name}</div>
            <div style="font-size:12px;color:var(--text-secondary);margin-top:2px">${loc.city}</div>
          </div>
          <a href="https://maps.google.com/?q=${loc.address}" target="_blank" class="btn btn-ghost" style="font-size:12px">
            <svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z"/><path stroke-linecap="round" stroke-linejoin="round" d="M15 11a3 3 0 11-6 0 3 3 0 016 0z"/></svg>
            Ver en mapa
          </a>
        </div>
        <div class="card-body">
          <div class="info-row"><span class="info-key">Dirección</span><span class="info-val">${loc.address}</span></div>
          <div class="info-row"><span class="info-key">Teléfono</span><span class="info-val">${loc.phone}</span></div>
          <div style="margin-top:12px">
            <div style="font-size:12px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px">Especialidades</div>
            <div style="display:flex;flex-wrap:wrap;gap:6px">
              ${loc.specialties.map(sp => `<span class="badge" style="background:var(--primary-light);color:var(--primary)">${sp}</span>`).join('')}
            </div>
          </div>
          <div style="margin-top:14px">
            <div style="font-size:12px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px">Equipo médico</div>
            ${loc.doctors.map(d => `
              <div style="display:flex;align-items:center;gap:10px;padding:7px 0;border-bottom:1px solid var(--border)">
                <div style="width:30px;height:30px;border-radius:50%;background:var(--primary-light);display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;color:var(--primary)">
                  ${d.name.split(' ').map(w=>w[0]).slice(0,2).join('')}
                </div>
                <div>
                  <div style="font-size:13px;font-weight:600">${d.name}</div>
                  <div style="font-size:11px;color:var(--text-secondary)">${d.specialty}</div>
                </div>
              </div>`).join('')}
          </div>
        </div>
      </div>`).join('');
  } catch(e) { console.warn('Centros error', e); }
}

// ── Lead Modal ────────────────────────────────────────────────────────────────
async function openLeadModal(phone) {
  try {
    const data = await (await fetch(`${API}/api/sessions/${encodeURIComponent(phone)}`)).json();
    const s = data.session;
    const p = s.patient || {};
    const modal = document.getElementById('lead-modal');
    document.getElementById('modal-name').textContent = p.name || phone;
    document.getElementById('modal-stage').innerHTML = stageBadge(s.stage);
    document.getElementById('modal-info').innerHTML = [
      ['Teléfono', phone],
      ['Problema', p.problem || '—'],
      ['Especialidad', p.specialty || '—'],
      ['Duración', p.duration || '—'],
      ['Tratamientos previos', p.previous_treatments || '—'],
      ['Califica', p.qualifies === true ? '✓ Sí' : p.qualifies === false ? '✗ No' : '—'],
      ['Ciudad', p.city || '—'],
      ['Urgencia', p.urgency || '—'],
    ].map(([k,v]) => `<div class="info-row"><span class="info-key">${k}</span><span class="info-val">${v}</span></div>`).join('');

    const msgs = data.messages || [];
    document.getElementById('modal-messages').innerHTML = msgs.length
      ? msgs.map(m => `<div class="msg ${m.role === 'user' ? 'user' : 'bot'}"><div class="msg-bubble">${m.content}</div></div>`).join('')
      : '<p style="color:var(--text-secondary);font-size:13px">Sin mensajes</p>';
    setTimeout(() => {
      const mc = document.getElementById('modal-messages');
      if (mc) mc.scrollTop = mc.scrollHeight;
    }, 50);
    modal.classList.add('open');
  } catch(e) { console.warn('Modal error', e); }
}

function closeModal() { document.getElementById('lead-modal').classList.remove('open'); }
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

// ── Simulador ─────────────────────────────────────────────────────────────────
async function sendChat() {
  if (chatLoading) return;
  const input = document.getElementById('chat-input-sim');
  const phone = document.getElementById('test-phone').value.trim() || '+34test0001';
  const msg = input.value.trim();
  if (!msg) return;
  appendMsg(msg, 'user');
  input.value = '';
  chatLoading = true;
  const typingId = 'typing-' + Date.now();
  document.getElementById('sim-messages').insertAdjacentHTML('beforeend',
    `<div id="${typingId}" class="msg bot"><div class="msg-bubble" style="opacity:.5">Escribiendo...</div></div>`);
  scrollChat();
  try {
    const r = await fetch(`${API}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phone, message: msg }),
    });
    document.getElementById(typingId)?.remove();
    if (r.ok) {
      const d = await r.json();
      appendMsg(d.reply, 'bot');
      renderSimState(d.stage, d.patient);
      loadPage(currentPage);
    } else {
      appendMsg('Error al conectar. Verifica que el servidor está activo.', 'bot');
    }
  } catch(e) {
    document.getElementById(typingId)?.remove();
    appendMsg('No se puede conectar al servidor. Asegúrate de que está corriendo.', 'bot');
  }
  chatLoading = false;
}

async function resetSim() {
  const phone = document.getElementById('test-phone').value.trim() || '+34test0001';
  await fetch(`${API}/api/chat/${encodeURIComponent(phone)}`, { method: 'DELETE' });
  document.getElementById('sim-messages').innerHTML = '<div class="msg bot"><div class="msg-bubble">Conversación reiniciada. Escribe un mensaje para empezar.</div></div>';
  document.getElementById('sim-state').innerHTML = '<p style="color:var(--text-secondary);font-size:13px">Inicia la conversación.</p>';
}

function appendMsg(text, role) {
  const el = document.createElement('div');
  el.className = `msg ${role === 'user' ? 'user' : 'bot'}`;
  el.innerHTML = `<div class="msg-bubble">${text}</div>`;
  document.getElementById('sim-messages').appendChild(el);
  scrollChat();
}

function scrollChat() {
  const el = document.getElementById('sim-messages');
  if (el) el.scrollTop = el.scrollHeight;
}

function renderSimState(stage, patient) {
  const s = STAGES[stage] || {};
  const rows = patient ? [
    patient.name && `<div class="info-row"><span class="info-key">Nombre</span><span class="info-val">${patient.name}</span></div>`,
    patient.problem && `<div class="info-row"><span class="info-key">Problema</span><span class="info-val">${patient.problem}</span></div>`,
    patient.specialty && `<div class="info-row"><span class="info-key">Especialidad</span><span class="info-val">${patient.specialty}</span></div>`,
    patient.duration && `<div class="info-row"><span class="info-key">Duración</span><span class="info-val">${patient.duration}</span></div>`,
    patient.city && `<div class="info-row"><span class="info-key">Ciudad</span><span class="info-val">${patient.city}</span></div>`,
    patient.qualifies != null && `<div class="info-row"><span class="info-key">Califica</span><span class="info-val" style="color:${patient.qualifies ? 'var(--accent)' : 'var(--destructive)'}">${patient.qualifies ? '✓ Sí' : '✗ No'}</span></div>`,
  ].filter(Boolean).join('') : '';
  document.getElementById('sim-state').innerHTML = `
    <div style="margin-bottom:10px">${stageBadge(stage)}</div>
    ${rows || '<p style="color:var(--text-secondary);font-size:12px">Sin datos aún</p>'}`;
}

// ── Refresh ───────────────────────────────────────────────────────────────────
function refreshAll() {
  loadPage(currentPage);
  updateNavBadge();
}

async function updateNavBadge() {
  try {
    const { total } = await (await fetch(`${API}/api/sessions`)).json();
    const badge = document.getElementById('nav-leads-badge');
    if (badge) badge.textContent = total;
  } catch(e) {}
}

// ── Init ──────────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
  navigate('dashboard');
  autoRefreshTimer = setInterval(refreshAll, 20000);
  document.getElementById('chat-input-sim')?.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
  });
});
