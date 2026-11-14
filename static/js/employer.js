// ============================================================
// POST A JOB — multi-step wizard
// ============================================================
(function () {
  const form = document.getElementById('post-job-form');
  if (!form) return;

  const PACKAGE_PRICES = { basic: 19, featured: 39, urgent: 69, premium: 129 };
  let currentStep = 1;
  const totalSteps = 4;

  const backBtn = document.getElementById('wizard-back');
  const nextBtn = document.getElementById('wizard-next');
  const submitBtn = document.getElementById('wizard-submit');

  function updateStepper() {
    document.querySelectorAll('[data-step-indicator]').forEach((el) => {
      const idx = parseInt(el.dataset.stepIndicator, 10);
      const circle = el.querySelector('.step-circle');
      const label = el.querySelector('.step-label');
      if (idx < currentStep) {
        circle.classList.add('bg-mint', 'border-mint', 'text-white');
        circle.classList.remove('border-white/20', 'text-cream/40', 'bg-indigo', 'border-indigo');
        circle.style.background = ''; circle.style.borderColor = '';
        circle.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>';
        label.classList.add('text-cream', 'font-medium');
        label.classList.remove('text-cream/50');
      } else if (idx === currentStep) {
        circle.classList.remove('border-white/20', 'text-cream/40', 'bg-mint', 'border-mint');
        circle.style.background = 'var(--indigo)'; circle.style.borderColor = 'var(--indigo)'; circle.style.color = 'white';
        circle.textContent = idx;
        label.classList.add('text-cream', 'font-medium');
        label.classList.remove('text-cream/50');
      } else {
        circle.classList.remove('bg-mint', 'border-mint', 'text-white');
        circle.style.background = ''; circle.style.borderColor = ''; circle.style.color = '';
        circle.classList.add('border-white/20', 'text-cream/40');
        circle.textContent = idx;
        label.classList.remove('text-cream', 'font-medium');
        label.classList.add('text-cream/50');
      }
    });
  }

  function showStep(step) {
    form.querySelectorAll('[data-step]').forEach((el) => {
      el.classList.toggle('hidden', parseInt(el.dataset.step, 10) !== step);
    });
    backBtn.classList.toggle('invisible', step === 1);
    nextBtn.classList.toggle('hidden', step === totalSteps);
    submitBtn.classList.toggle('hidden', step !== totalSteps);
    if (step === totalSteps) updatePaymentTotal();
    updateStepper();
  }

  function selectedPackage() {
    const checked = form.querySelector('input[name=package]:checked');
    return checked ? checked.value : 'featured';
  }

  function updatePaymentTotal() {
    const pkg = selectedPackage();
    document.getElementById('payment-total').textContent = `$${PACKAGE_PRICES[pkg]}`;
  }

  function highlightPackages() {
    document.querySelectorAll('.package-option').forEach((el) => {
      const radio = el.querySelector('input[type=radio]');
      el.classList.toggle('border-indigo', radio.checked);
      el.classList.toggle('bg-indigo/5', radio.checked);
    });
  }
  document.querySelectorAll('input[name=package]').forEach((r) => r.addEventListener('change', () => { highlightPackages(); updatePaymentTotal(); }));
  highlightPackages();

  function validateStep(step) {
    if (step === 1) {
      const title = form.querySelector('input[name=title]');
      const errorEl = form.querySelector('[data-error=title]');
      if (!title.value.trim()) {
        errorEl.classList.remove('hidden');
        title.classList.add('border-rose');
        title.focus();
        return false;
      }
      errorEl.classList.add('hidden');
      title.classList.remove('border-rose');
    }
    return true;
  }

  nextBtn.addEventListener('click', () => {
    if (!validateStep(currentStep)) return;
    currentStep = Math.min(currentStep + 1, totalSteps);
    showStep(currentStep);
  });
  backBtn.addEventListener('click', () => {
    currentStep = Math.max(currentStep - 1, 1);
    showStep(currentStep);
  });

  submitBtn.addEventListener('click', async () => {
    submitBtn.disabled = true;
    submitBtn.textContent = 'Publishing…';
    const fd = new FormData(form);
    const payload = Object.fromEntries(fd.entries());
    try {
      const res = await fetch('/api/post-job', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
      });
      await res.json();
      await fetch('/api/checkout', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ package: selectedPackage() }),
      });
    } catch (e) { /* demo only */ }
    document.getElementById('publish-success-overlay').classList.add('open');
    document.getElementById('publish-success').classList.add('open');
    if (window.lucide) lucide.createIcons();
  });

  showStep(1);
})();

// ============================================================
// CHECKOUT PAGE (standalone entry from Pricing)
// ============================================================
(function () {
  const publishBtn = document.getElementById('checkout-publish-btn');
  if (!publishBtn) return;
  publishBtn.addEventListener('click', async () => {
    publishBtn.disabled = true;
    publishBtn.textContent = 'Processing Payment…';
    const pkg = publishBtn.dataset.package;
    try {
      const res = await fetch('/api/checkout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ package: pkg }),
      });
      const data = await res.json();
      if (data.checkout_url) {
        window.location.href = data.checkout_url;
        return;
      }
      if (!data.ok) {
        alert(data.error || 'Payment initialization failed. Please try again.');
        publishBtn.disabled = false;
        publishBtn.textContent = 'Publish Job';
        return;
      }
    } catch (e) {
      console.error(e);
    }
    document.getElementById('checkout-form-state').classList.add('hidden');
    document.getElementById('checkout-success-state').classList.remove('hidden');
    if (window.lucide) lucide.createIcons();
  });
})();
