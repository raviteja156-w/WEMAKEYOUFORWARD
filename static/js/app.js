// ---------------------------------------------------------------- Global CSRF Interceptor
(function () {
  const origFetch = window.fetch;
  window.fetch = function (url, options = {}) {
    const metaCsrf = document.querySelector('meta[name="csrf-token"]');
    const token = metaCsrf ? metaCsrf.getAttribute('content') : '';
    const method = (options.method || 'GET').toUpperCase();
    if (token && !['GET', 'HEAD', 'OPTIONS'].includes(method)) {
      options.headers = options.headers || {};
      if (options.headers instanceof Headers) {
        if (!options.headers.has('X-CSRF-Token')) options.headers.set('X-CSRF-Token', token);
      } else if (Array.isArray(options.headers)) {
        options.headers.push(['X-CSRF-Token', token]);
      } else {
        if (!options.headers['X-CSRF-Token']) options.headers['X-CSRF-Token'] = token;
      }
    }
    return origFetch(url, options);
  };
})();

// ---------------------------------------------------------------- Toasts
function showToast(message, opts = {}) {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const icon = opts.icon || 'check-circle-2';
  const el = document.createElement('div');
  el.className = 'toast';
  const iconEl = document.createElement('i');
  iconEl.setAttribute('data-lucide', icon);
  iconEl.className = 'w-4 h-4 text-mint shrink-0';
  const text = document.createElement('span');
  text.textContent = message;          // textContent: messages are never parsed as HTML
  el.append(iconEl, text);
  container.appendChild(el);
  if (window.lucide) lucide.createIcons({ nodes: [el] });
  setTimeout(() => {
    el.classList.add('leaving');
    setTimeout(() => el.remove(), 250);
  }, 3200);
}

// ---------------------------------------------------------------- Demo role
async function setDemoRole(role) {
  try {
    await fetch('/api/demo-role', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role }),
    });
  } catch (e) { /* demo only */ }
  const destinations = {
    guest: '/',
    seeker: '/dashboard/seeker',
    employer: '/dashboard/employer',
    admin: '/admin',
  };
  window.location.href = destinations[role] || '/';
}

function toggleDemoMenu() {
  document.getElementById('demo-menu').classList.toggle('hidden');
}
document.addEventListener('click', (e) => {
  const menu = document.getElementById('demo-menu');
  const btn = document.getElementById('demo-switcher-btn');
  if (menu && !menu.classList.contains('hidden') && !menu.contains(e.target) && e.target !== btn && !btn.contains(e.target)) {
    menu.classList.add('hidden');
  }
});

// ---------------------------------------------------------------- Employer user menu
function toggleUserMenu(force) {
  const panel = document.getElementById('user-menu-panel');
  const btn = document.getElementById('user-menu-btn');
  if (!panel || !btn) return;
  const open = typeof force === 'boolean' ? force : panel.classList.contains('hidden');
  panel.classList.toggle('hidden', !open);
  btn.setAttribute('aria-expanded', String(open));
}
document.addEventListener('click', (e) => {
  const menu = document.getElementById('user-menu');
  if (menu && !menu.contains(e.target)) toggleUserMenu(false);
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    toggleUserMenu(false);
    document.getElementById('user-menu-btn')?.focus();
  }
});

// Menu entries for pages that aren't built yet
function comingSoon(label) {
  toggleUserMenu(false);
  showToast(`${label} is coming soon.`, { icon: 'clock' });
}

// ---------------------------------------------------------------- Mobile nav
function openMobileNav() {
  document.getElementById('mobile-nav-overlay').classList.add('open');
  document.getElementById('mobile-nav-drawer').classList.add('open');
}
function closeMobileNav() {
  document.getElementById('mobile-nav-overlay').classList.remove('open');
  document.getElementById('mobile-nav-drawer').classList.remove('open');
}
document.getElementById('mobile-nav-btn')?.addEventListener('click', openMobileNav);

// ---------------------------------------------------------------- Modal / Drawer helpers
function openModal(id) {
  document.getElementById(id + '-overlay')?.classList.add('open');
  document.getElementById(id)?.classList.add('open');
}
function closeModal(id) {
  document.getElementById(id + '-overlay')?.classList.remove('open');
  document.getElementById(id)?.classList.remove('open');
}
function openDrawer(id) {
  document.getElementById(id + '-overlay')?.classList.add('open');
  document.getElementById(id)?.classList.add('open');
}
function closeDrawer(id) {
  document.getElementById(id + '-overlay')?.classList.remove('open');
  document.getElementById(id)?.classList.remove('open');
}

// ---------------------------------------------------------------- Save / Apply (job seekers)
// Visitors are sent to the job-seeker login and brought back here afterwards.
function goToSeekerLogin() {
  window.location.href = '/seeker/login?next=' + encodeURIComponent(window.location.pathname + window.location.search);
}
async function seekerPost(url, body) {
  const res = await fetch(url, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}),
  });
  if (res.status === 401) { goToSeekerLogin(); return null; }
  const data = await res.json().catch(() => ({}));
  if (res.status === 403) { showToast(data.error || 'Use a job seeker account for this.', { icon: 'alert-circle' }); return null; }
  if (!res.ok) { showToast(data.error || 'Something went wrong. Please try again.', { icon: 'alert-circle' }); return null; }
  return data;
}

async function toggleSaveJob(jobId) {
  const data = await seekerPost(`/api/jobs/${jobId}/save`);
  if (!data) return;
  document.querySelectorAll(`[data-save-btn="${jobId}"]`).forEach((el) => {
    el.classList.toggle('is-saved', data.saved);
    const icon = el.querySelector('i, svg');
    if (icon) icon.setAttribute('fill', data.saved ? 'currentColor' : 'none');
    const label = el.querySelector('[data-save-label]');
    if (label) label.textContent = data.saved ? 'Saved' : 'Save';
  });
  document.querySelectorAll('[data-saved-count]').forEach((el) => { el.textContent = data.saved_count; });
  showToast(data.saved ? 'Job saved to your list.' : 'Removed from saved jobs.', { icon: data.saved ? 'bookmark-check' : 'bookmark-minus' });
  if (window.lucide) lucide.createIcons();
}

// One-click apply from lists (Find Jobs, Job Matches)
async function quickApply(jobId, btn) {
  const data = await seekerPost(`/api/jobs/${jobId}/apply`);
  if (!data) return;
  if (btn) { btn.disabled = true; btn.textContent = 'Applied'; }
  document.querySelectorAll(`[data-apply="${jobId}"]`).forEach((el) => { el.disabled = true; el.textContent = 'Applied'; });
  showToast(data.already_applied ? 'You already applied to this job.' : 'Application submitted. Track it in My Applications.', { icon: 'check-circle-2' });
}

// Animated counters for dashboard metrics
function animateCounter(el, target, opts = {}) {
  const duration = opts.duration || 900;
  const prefix = opts.prefix || '';
  const suffix = opts.suffix || '';
  const start = 0;
  const startTime = performance.now();
  function tick(now) {
    const progress = Math.min((now - startTime) / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3);
    const value = Math.round(start + (target - start) * eased);
    el.textContent = prefix + value.toLocaleString() + suffix;
    if (progress < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-counter]').forEach((el) => {
    const target = parseInt(el.dataset.counter, 10) || 0;
    animateCounter(el, target, { prefix: el.dataset.prefix || '', suffix: el.dataset.suffix || '' });
  });
});
