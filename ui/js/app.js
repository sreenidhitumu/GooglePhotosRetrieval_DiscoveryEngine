/* ==========================================================================
   Google Photos Discovery Engine - Client Application Logic
   Lineage Grounding: Multi-Source Canonical Evidence Corpus (375 records)
   Sources: Reddit, Google Play Store, YouTube, Apple App Store
   ========================================================================== */

const API_BASE = '/api/v1';

let state = {
  currentView: 'dashboard',
  records: [],
  totalRecords: 0,
  limit: 20,
  offset: 0,
  themeFilter: '',
  sourceFilter: '',
  searchQuery: '',
  themesList: [],
};

// Initialize Application
document.addEventListener('DOMContentLoaded', () => {
  setupNavigation();
  setupFilters();
  setupModal();
  loadAllData();
});

// Navigation Setup
function setupNavigation() {
  const tabs = document.querySelectorAll('.tab-btn');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      const targetView = tab.dataset.view;
      if (targetView) {
        switchView(targetView);
      }
    });
  });
}

function switchView(viewName) {
  state.currentView = viewName;
  
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.view === viewName);
  });

  document.querySelectorAll('.view-section').forEach(sec => {
    sec.classList.toggle('active', sec.id === `${viewName}-view`);
  });

  if (viewName === 'explorer') {
    loadRecords();
  } else if (viewName === 'opportunities') {
    loadOpportunities();
  } else if (viewName === 'dashboard') {
    loadStats();
    loadOpportunities();
  }
}

// Global Data Loader
async function loadAllData() {
  await Promise.all([
    loadStats(),
    loadOpportunities(),
    loadRecords()
  ]).catch(err => console.error('Error in loadAllData:', err));
}

// Helper: Source Icons & Styling
function getSourceConfig(sourceType) {
  const st = (sourceType || '').toLowerCase();
  if (st === 'reddit') {
    return { name: 'Reddit Evidence Corpus', icon: 'fab fa-reddit', color: '#ff4500', bg: 'rgba(255, 69, 0, 0.12)' };
  } else if (st === 'google_play') {
    return { name: 'Google Play Store Reviews', icon: 'fab fa-google-play', color: '#00f076', bg: 'rgba(0, 240, 118, 0.12)' };
  } else if (st === 'youtube') {
    return { name: 'YouTube Research Comments', icon: 'fab fa-youtube', color: '#ff3333', bg: 'rgba(255, 51, 51, 0.12)' };
  } else if (st === 'app_store') {
    return { name: 'Apple App Store Reviews', icon: 'fab fa-apple', color: '#3399ff', bg: 'rgba(51, 153, 255, 0.12)' };
  }
  return { name: sourceType || 'Public Data', icon: 'fas fa-globe', color: '#94a3b8', bg: 'rgba(148, 163, 184, 0.12)' };
}

function getSourceBadge(sourceType) {
  const cfg = getSourceConfig(sourceType);
  return `<span class="badge" style="background: ${cfg.bg}; color: ${cfg.color}; border: 1px solid ${cfg.color}44;">
    <i class="${cfg.icon}" style="margin-right: 4px;"></i> ${cfg.name}
  </span>`;
}

// Fetch Stats (Dashboard)
async function loadStats() {
  try {
    const res = await fetch(`${API_BASE}/stats/sources`);
    if (!res.ok) return;

    const sourcesData = await res.json();

    // Render Scoped Stats Cards safely
    const canonicalElem = document.getElementById('stat-canonical-count');
    if (canonicalElem) canonicalElem.innerText = (sourcesData.total_canonical || 4139).toLocaleString();

    const relevantElem = document.getElementById('stat-relevant-count');
    if (relevantElem) relevantElem.innerText = (sourcesData.total_relevant || 375).toLocaleString();

    const clustersElem = document.getElementById('stat-clusters-count');
    if (clustersElem) clustersElem.innerText = '5';

    // Render Source Distribution Chips (All Sources)
    const sourcesContainer = document.getElementById('sources-distribution');
    if (sourcesContainer && sourcesData.sources) {
      sourcesContainer.innerHTML = sourcesData.sources.map(s => {
        const cfg = getSourceConfig(s.source_type);
        return `
          <div style="background: rgba(30, 41, 59, 0.6); padding: 0.85rem 1.2rem; border-radius: 8px; border: 1px solid rgba(255,255,255,0.06); display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.5rem;">
            <div style="display: flex; align-items: center;">
              <i class="${cfg.icon}" style="color: ${cfg.color}; margin-right: 10px; font-size: 1.1rem;"></i>
              <span style="font-weight: 600; font-size: 0.95rem; color: #fff;">${cfg.name}</span>
            </div>
            <div style="display: flex; gap: 0.5rem; align-items: center;">
              <span class="badge badge-source" style="font-size: 0.8rem; font-weight: 500;">
                <strong>${(s.canonical_count || 0).toLocaleString()}</strong> canonical 
                <span style="color: var(--text-muted); margin: 0 4px;">|</span> 
                <strong style="color: var(--accent-success);">${(s.relevant_count || 0).toLocaleString()}</strong> relevant
              </span>
            </div>
          </div>
        `;
      }).join('');
    }
  } catch (err) {
    console.error('Error loading stats:', err);
  }
}

// Fetch Opportunities (Validated Research Themes)
async function loadOpportunities() {
  try {
    const res = await fetch(`${API_BASE}/opportunities`);
    if (!res.ok) return;
    const data = await res.json();
    
    state.themesList = data.themes || [];
    const oppList = data.opportunities || [];

    const grid = document.getElementById('opportunities-container');
    const dashGrid = document.getElementById('dashboard-opportunities-container');

    if (oppList.length === 0) {
      if (grid) grid.innerHTML = '<div style="color: var(--text-muted); padding: 2rem;">No opportunity themes found.</div>';
      if (dashGrid) dashGrid.innerHTML = '<div style="color: var(--text-muted); padding: 1rem;">No opportunities found.</div>';
      return;
    }

    const renderCard = (opp) => {
      const isCore = opp.is_core_opportunity;
      const fitLabel = opp.mvp_fit_label || 'RESEARCH THEME';
      const badgeStyle = isCore
        ? 'background: linear-gradient(135deg, #10b981 0%, #059669 100%); color: #fff; box-shadow: 0 4px 12px rgba(16, 185, 129, 0.4);'
        : 'background: rgba(99, 102, 241, 0.2); color: #a5b4fc; border: 1px solid rgba(99, 102, 241, 0.4);';

      const recCount = opp.member_count || opp.record_count || 0;

      return `
        <div class="opportunity-card" style="${isCore ? 'border: 2px solid #10b981; background: rgba(16, 185, 129, 0.05);' : ''}">
          <div class="rank-badge" style="${badgeStyle}">
            ${isCore ? '⭐ ' : ''}${fitLabel}
          </div>

          <h3 class="opp-title" style="margin-top: 0.75rem;">
            ${escapeHtml(opp.cluster_label || 'Research Theme')}
          </h3>
          <p class="opp-summary" style="font-size: 0.88rem; min-height: 48px;">
            ${escapeHtml(opp.cluster_summary || '')}
          </p>
          
          <div class="metrics-bar-group" style="margin-top: 0.5rem; margin-bottom: 1rem;">
            <div class="metric-bar-item" style="margin-bottom: 0.3rem;">
              <span class="metric-label" style="font-weight: 700; color: #f8fafc;">Primary Hits:</span>
              <span style="font-weight: 700; color: var(--accent-secondary);">${recCount} records</span>
            </div>
            ${isCore ? `
              <div style="font-size: 0.78rem; color: #10b981; background: rgba(16, 185, 129, 0.12); padding: 0.4rem 0.6rem; border-radius: 6px; margin-top: 0.3rem;">
                <i class="fas fa-bullseye"></i> <strong>Core Differentiator:</strong> Fragmentary visual memory search (unlike generic Ask Photos / AI search).
              </div>
            ` : ''}
          </div>

          <div class="opp-footer">
            <span style="font-size: 0.8rem; color: var(--text-muted);"><i class="fas fa-layer-group"></i> ${recCount} Evidence Records</span>
            <button class="btn-primary" style="${isCore ? 'background: #10b981;' : ''}" onclick="filterByTheme('${opp.cluster_id}')">
              <i class="fas fa-search"></i> Inspect Evidence
            </button>
          </div>
        </div>
      `;
    };

    if (grid) {
      grid.innerHTML = oppList.map((opp) => renderCard(opp)).join('');
    }

    if (dashGrid) {
      dashGrid.innerHTML = oppList.slice(0, 3).map((opp) => renderCard(opp)).join('');
    }
  } catch (err) {
    console.error('Error loading opportunities:', err);
  }
}

// Fetch Record Explorer Table Data
async function loadRecords() {
  try {
    let url = `${API_BASE}/records?limit=${state.limit}&offset=${state.offset}&is_relevant=true`;
    if (state.themeFilter) url += `&theme_id=${encodeURIComponent(state.themeFilter)}`;
    if (state.sourceFilter) url += `&source_type=${encodeURIComponent(state.sourceFilter)}`;
    if (state.searchQuery) url += `&q=${encodeURIComponent(state.searchQuery)}`;

    const res = await fetch(url);
    if (!res.ok) return;
    const data = await res.json();

    state.records = data.records || [];
    state.totalRecords = data.total || 0;

    renderRecordsTable();
    renderPagination();
  } catch (err) {
    console.error('Error loading records:', err);
  }
}

function renderRecordsTable() {
  const tbody = document.getElementById('records-tbody');
  if (!tbody) return;

  if (state.records.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding: 2rem; color: var(--text-muted);">No records found matching filters.</td></tr>`;
    return;
  }

  tbody.innerHTML = state.records.map(r => {
    let themeBadge = '<span class="badge" style="background: rgba(148,163,184,0.1); color: #94a3b8;">Unassigned</span>';
    if (r.theme_ids && r.theme_ids.length > 0) {
      const isCore = r.theme_ids.some(t => t.startsWith('T2'));
      themeBadge = `<span class="badge" style="${isCore ? 'background: rgba(16, 185, 129, 0.2); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.4);' : 'background: rgba(99, 102, 241, 0.15); color: #a5b4fc; border: 1px solid rgba(99, 102, 241, 0.3);'}">
        ${isCore ? '⭐ ' : ''}${r.theme_ids[0].substring(0, 2)}
      </span>`;
    }

    const postDate = r.posted_at ? new Date(r.posted_at).toLocaleDateString() : 'N/A';

    return `
      <tr>
        <td>${getSourceBadge(r.source_type)}</td>
        <td style="max-width: 350px;">
          <div style="font-weight: 600; color: #fff; text-overflow: ellipsis; overflow: hidden; white-space: nowrap;">${escapeHtml(r.title || 'Untitled Record')}</div>
          <div style="font-size: 0.8rem; color: var(--text-muted); text-overflow: ellipsis; overflow: hidden; white-space: nowrap;">${escapeHtml((r.body || '').substring(0, 90))}...</div>
        </td>
        <td>${themeBadge}</td>
        <td style="font-size: 0.8rem; color: var(--text-muted);">${postDate}</td>
        <td>
          <button class="btn-secondary" style="font-size: 0.75rem; padding: 0.3rem 0.6rem;" onclick="showRecordDetail('${r.id}')">
            <i class="fas fa-eye"></i> Detail
          </button>
        </td>
      </tr>
    `;
  }).join('');
}

function renderPagination() {
  const info = document.getElementById('pagination-info');
  const prevBtn = document.getElementById('prev-page-btn');
  const nextBtn = document.getElementById('next-page-btn');

  const start = state.totalRecords === 0 ? 0 : state.offset + 1;
  const end = Math.min(state.offset + state.limit, state.totalRecords);

  if (info) info.innerText = `Showing ${start} - ${end} of ${state.totalRecords} records`;
  if (prevBtn) prevBtn.disabled = state.offset === 0;
  if (nextBtn) nextBtn.disabled = state.offset + state.limit >= state.totalRecords;
}

// Modal Detail View
async function showRecordDetail(recordId) {
  const modal = document.getElementById('detail-modal');
  const modalTitle = document.getElementById('modal-title');
  const modalBody = document.getElementById('modal-body');

  if (!modal || !modalBody) return;

  modalBody.innerHTML = '<div style="color: var(--text-muted); padding: 2rem; text-align: center;">Loading evidence record detail...</div>';
  modal.classList.add('active');

  try {
    const res = await fetch(`${API_BASE}/records/${recordId}`);
    if (!res.ok) throw new Error('Record fetch failed');
    const r = await res.json();

    if (modalTitle) modalTitle.innerText = `Evidence Record ${r.id.substring(0, 8)}`;

    let themesHtml = '';
    if (r.theme_ids && r.theme_ids.length > 0) {
      themesHtml = `
        <div class="detail-section">
          <div class="detail-label">Assigned Research Themes</div>
          <div style="display: flex; gap: 0.5rem; flex-wrap: wrap;">
            ${r.theme_ids.map(tId => `<span class="badge" style="background: rgba(16, 185, 129, 0.2); color: #10b981;">Theme: ${tId}</span>`).join('')}
          </div>
        </div>
      `;
    }

    modalBody.innerHTML = `
      <div class="detail-section">
        <div class="detail-label">Source & Lineage</div>
        <div style="display: flex; gap: 0.5rem; margin-bottom: 0.75rem; align-items: center; flex-wrap: wrap;">
          ${getSourceBadge(r.source_type)}
          ${r.permalink ? `<a href="${r.permalink}" target="_blank" class="btn-secondary" style="font-size:0.75rem; padding: 0.2rem 0.6rem;"><i class="fas fa-external-link-alt"></i> Original Permalink</a>` : ''}
          <span style="font-size: 0.8rem; color: var(--text-muted); margin-left: auto;">ID: ${r.id}</span>
        </div>
      </div>

      <div class="detail-section">
        <div class="detail-label">Title</div>
        <div style="font-weight: 600; color: #fff; font-size: 1.05rem;">${escapeHtml(r.title || 'Untitled Record')}</div>
      </div>

      <div class="detail-section">
        <div class="detail-label">Canonical Content Text</div>
        <div class="code-block" style="white-space: pre-wrap; word-break: break-word;">${escapeHtml(r.body || '')}</div>
      </div>

      ${themesHtml}
    `;
  } catch (err) {
    modalBody.innerHTML = `<div style="color: var(--accent-danger); padding: 1.5rem;">Failed to load detail for record ${recordId}.</div>`;
  }
}

function setupModal() {
  const modal = document.getElementById('detail-modal');
  const closeBtn = document.getElementById('modal-close-btn');

  if (closeBtn && modal) {
    closeBtn.addEventListener('click', () => modal.classList.remove('active'));
    modal.addEventListener('click', (e) => {
      if (e.target === modal) modal.classList.remove('active');
    });
  }
}

// Filters & Explorer Helpers
function setupFilters() {
  document.getElementById('filter-theme')?.addEventListener('change', (e) => {
    state.themeFilter = e.target.value;
    state.offset = 0;
    loadRecords();
  });

  document.getElementById('filter-source')?.addEventListener('change', (e) => {
    state.sourceFilter = e.target.value;
    state.offset = 0;
    loadRecords();
  });

  let searchTimeout;
  document.getElementById('search-input')?.addEventListener('input', (e) => {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
      state.searchQuery = e.target.value;
      state.offset = 0;
      loadRecords();
    }, 300);
  });

  document.getElementById('prev-page-btn')?.addEventListener('click', () => {
    if (state.offset >= state.limit) {
      state.offset -= state.limit;
      loadRecords();
    }
  });

  document.getElementById('next-page-btn')?.addEventListener('click', () => {
    if (state.offset + state.limit < state.totalRecords) {
      state.offset += state.limit;
      loadRecords();
    }
  });
}

function filterByTheme(themeId) {
  state.themeFilter = themeId;
  const themeSelect = document.getElementById('filter-theme');
  if (themeSelect) themeSelect.value = themeId;
  switchView('explorer');
}

// Helper: Escape HTML
function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
