/* ══════════════════════════════════════════════════════════════════════════════
   CompanyIntel.ai — Application Logic
   Vanilla JS · No frameworks · Production-grade
   ══════════════════════════════════════════════════════════════════════════════ */

(function () {
    'use strict';

    // ── DOM Refs ──────────────────────────────────────────────────────────────
    const $  = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);

    const enrichForm       = $('#enrich-form');
    const enrichBtn        = $('#enrich-btn');
    const urlInput         = $('#website-url');
    const nameInput        = $('#website-name');
    const loadingContainer = $('#loading-container');
    const loadingUrl       = $('#loading-url');
    const enrichResult     = $('#enrich-result');
    const resultsGrid      = $('#results-grid');
    const resultsBtn       = $('#results-btn');
    const resultsCount     = $('#results-count');
    const countNumber      = $('#count-number');
    const emptyState       = $('#empty-state');
    const toastContainer   = $('#toast-container');

    // ── Helpers ───────────────────────────────────────────────────────────────

    /** Sanitise text to prevent XSS */
    function esc(str) {
        if (str == null) return '';
        const el = document.createElement('span');
        el.textContent = String(str);
        return el.innerHTML;
    }

    /** Returns true when a value is usable (not empty / N/A) */
    function hasValue(val) {
        if (val == null) return false;
        if (Array.isArray(val)) return val.length > 0 && val.some(v => hasValue(v));
        const s = String(val).trim().toLowerCase();
        return s !== '' && s !== 'n/a' && s !== 'na' && s !== 'none' && s !== 'null' && s !== 'undefined' && s !== '-';
    }

    /** Display a field value or a styled dash for N/A */
    function displayValue(val) {
        return hasValue(val) ? esc(val) : '<span class="na">—</span>';
    }

    /** Normalise URL: prepend https:// if missing */
    function normaliseUrl(raw) {
        let url = raw.trim();
        if (!/^https?:\/\//i.test(url)) {
            url = 'https://' + url;
        }
        return url;
    }

    /** Validate URL */
    function isValidUrl(str) {
        try {
            const u = new URL(str);
            return u.protocol === 'http:' || u.protocol === 'https:';
        } catch (_) {
            return false;
        }
    }

    /** Get initials from company name */
    function initials(name) {
        if (!hasValue(name)) return '?';
        return name.split(/\s+/).map(w => w[0]).slice(0, 2).join('').toUpperCase();
    }

    /** Format ISO date string into human-readable form */
    function formatDate(iso) {
        if (!hasValue(iso)) return '—';
        try {
            const d = new Date(iso);
            return d.toLocaleDateString('en-US', {
                month: 'short', day: 'numeric', year: 'numeric',
                hour: '2-digit', minute: '2-digit'
            });
        } catch (_) {
            return esc(iso);
        }
    }

    // ── Toast Notifications ──────────────────────────────────────────────────

    function showToast(message, type = 'success', duration = 4500) {
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        const icon = type === 'success' ? '✓' : '✕';
        toast.innerHTML = `
            <span class="toast-icon">${icon}</span>
            <span class="toast-msg">${esc(message)}</span>
            <button class="toast-close" onclick="this.parentElement.remove()">×</button>
        `;
        toastContainer.appendChild(toast);
        setTimeout(() => {
            toast.style.animation = 'slideOut 0.3s ease forwards';
            setTimeout(() => toast.remove(), 300);
        }, duration);
    }

    function showError(msg) { showToast(msg, 'error', 6000); }
    function showSuccess(msg) { showToast(msg, 'success'); }

    // ── Loading State ────────────────────────────────────────────────────────

    let stepTimer = null;

    function showLoadingState(url) {
        loadingContainer.style.display = 'block';
        loadingUrl.textContent = url;
        enrichResult.style.display = 'none';

        // Reset steps
        for (let i = 1; i <= 4; i++) {
            const step = $(`#step-${i}`);
            step.classList.remove('active', 'completed');
        }

        // Animate through steps
        animateStatusSteps();

        // Scroll into view
        loadingContainer.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    function hideLoadingState() {
        if (stepTimer) {
            clearTimeout(stepTimer);
            stepTimer = null;
        }
        // Complete all remaining steps
        for (let i = 1; i <= 4; i++) {
            const step = $(`#step-${i}`);
            step.classList.remove('active');
            step.classList.add('completed');
        }
        // Fade out after a beat
        setTimeout(() => {
            loadingContainer.style.display = 'none';
        }, 600);
    }

    function animateStatusSteps() {
        const delays = [0, 2200, 4400, 6600]; // staggered timing
        delays.forEach((delay, idx) => {
            stepTimer = setTimeout(() => {
                const stepNum = idx + 1;
                // Mark previous steps as completed
                for (let j = 1; j < stepNum; j++) {
                    const prev = $(`#step-${j}`);
                    prev.classList.remove('active');
                    prev.classList.add('completed');
                }
                // Mark current step active
                const current = $(`#step-${stepNum}`);
                current.classList.add('active');
            }, delay);
        });
    }

    function setBtnLoading(btn, loading) {
        const text   = btn.querySelector('.btn-text');
        const loader = btn.querySelector('.btn-loader');
        if (loading) {
            text.style.display   = 'none';
            loader.style.display = 'inline-flex';
            btn.disabled = true;
        } else {
            text.style.display   = 'inline-flex';
            loader.style.display = 'none';
            btn.disabled = false;
        }
    }

    // ── Copy to Clipboard ────────────────────────────────────────────────────

    function copyToClipboard(text, btnEl) {
        navigator.clipboard.writeText(text).then(() => {
            btnEl.classList.add('copied');
            setTimeout(() => btnEl.classList.remove('copied'), 2000);
            showSuccess('Outreach opener copied to clipboard!');
        }).catch(() => {
            // Fallback
            const ta = document.createElement('textarea');
            ta.value = text;
            ta.style.cssText = 'position:fixed;left:-9999px';
            document.body.appendChild(ta);
            ta.select();
            try {
                document.execCommand('copy');
                btnEl.classList.add('copied');
                setTimeout(() => btnEl.classList.remove('copied'), 2000);
                showSuccess('Copied!');
            } catch (e) {
                showError('Failed to copy.');
            }
            document.body.removeChild(ta);
        });
    }

    // ── Render Company Card ──────────────────────────────────────────────────

    function renderCompanyCard(data) {
        const card = document.createElement('div');
        card.className = 'company-card glass-card';

        // Emails
        let emailsHtml = '<span class="na">—</span>';
        if (hasValue(data.mail)) {
            const mails = Array.isArray(data.mail) ? data.mail : [data.mail];
            const validMails = mails.filter(m => hasValue(m));
            if (validMails.length > 0) {
                emailsHtml = '<div class="email-chips">' +
                    validMails.map(m => `
                        <span class="email-chip">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/>
                                <polyline points="22,6 12,13 2,6"/>
                            </svg>
                            ${esc(m)}
                        </span>
                    `).join('') +
                '</div>';
            }
        }

        // Outreach
        const outreachText = hasValue(data.outreach_opener) ? data.outreach_opener : '';
        const outreachId = 'outreach-' + Math.random().toString(36).slice(2, 10);

        card.innerHTML = `
            <div class="card-header">
                <div class="card-company-name">
                    <span class="company-icon">${initials(data.company_name || data.website_name)}</span>
                    ${esc(data.company_name || data.website_name || 'Unknown')}
                </div>
                ${hasValue(data.website_url)
                    ? `<a class="card-website-url" href="${esc(data.website_url)}" target="_blank" rel="noopener">${esc(data.website_url)}</a>`
                    : ''}
            </div>

            <div class="card-body">
                <div class="card-grid">
                    <div class="card-field">
                        <span class="card-field-label">Address</span>
                        <span class="card-field-value">${displayValue(data.address)}</span>
                    </div>
                    <div class="card-field">
                        <span class="card-field-label">Phone</span>
                        <span class="card-field-value">${displayValue(data.mobile_number)}</span>
                    </div>
                </div>

                <div class="card-field">
                    <span class="card-field-label">Email</span>
                    ${emailsHtml}
                </div>

                <div class="card-field">
                    <span class="card-field-label">Core Service</span>
                    <span class="card-field-value">${displayValue(data.core_service)}</span>
                </div>

                <div class="card-grid">
                    <div class="card-field">
                        <span class="card-field-label">Target Customer</span>
                        <span class="card-field-value">${displayValue(data.target_customer)}</span>
                    </div>
                    <div class="card-field">
                        <span class="card-field-label">Pain Point</span>
                        <span class="card-field-value">${displayValue(data.probable_pain_point)}</span>
                    </div>
                </div>

                ${outreachText ? `
                    <div class="card-field">
                        <span class="card-field-label">Outreach Opener</span>
                        <div class="outreach-box">
                            <span class="card-field-value">"${esc(outreachText)}"</span>
                            <button class="copy-btn" id="${outreachId}" title="Copy to clipboard" aria-label="Copy outreach opener">
                                <span class="copy-tooltip">Copied!</span>
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                                    <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/>
                                </svg>
                            </button>
                        </div>
                    </div>
                ` : `
                    <div class="card-field">
                        <span class="card-field-label">Outreach Opener</span>
                        <span class="card-field-value na">—</span>
                    </div>
                `}
            </div>

            <div class="card-footer">
                <span class="card-footer-badge">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                        <polyline points="20 6 9 17 4 12"/>
                    </svg>
                    AI Enriched
                </span>
                <span>${formatDate(data.enriched_at)}</span>
            </div>
        `;

        // Attach copy handler after render
        if (outreachText) {
            setTimeout(() => {
                const copyBtn = document.getElementById(outreachId);
                if (copyBtn) {
                    copyBtn.addEventListener('click', () => copyToClipboard(outreachText, copyBtn));
                }
            }, 0);
        }

        return card;
    }

    // ── Enrich Company ───────────────────────────────────────────────────────

    async function enrichCompany(url, websiteName) {
        setBtnLoading(enrichBtn, true);
        showLoadingState(url);

        try {
            const response = await fetch('/enrich', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: url, website_name: websiteName }),
            });

            if (!response.ok) {
                let errMsg = `Server error (${response.status})`;
                try {
                    const errData = await response.json();
                    errMsg = errData.error || errData.message || errData.detail || errMsg;
                } catch (_) { /* ignore parse errors */ }
                throw new Error(errMsg);
            }

            const data = await response.json();

            hideLoadingState();

            // Show enriched result
            setTimeout(() => {
                enrichResult.innerHTML = '';
                enrichResult.style.display = 'block';
                const card = renderCompanyCard(data);
                enrichResult.appendChild(card);
                enrichResult.scrollIntoView({ behavior: 'smooth', block: 'center' });
                showSuccess(`Successfully enriched ${data.company_name || websiteName}!`);
            }, 700);

        } catch (err) {
            hideLoadingState();
            setTimeout(() => {
                loadingContainer.style.display = 'none';
            }, 400);
            showError(err.message || 'Failed to enrich company. Please try again.');
        } finally {
            setBtnLoading(enrichBtn, false);
        }
    }

    // ── Show All Results ─────────────────────────────────────────────────────

    async function showAllResults() {
        setBtnLoading(resultsBtn, true);
        emptyState.style.display = 'none';
        resultsGrid.innerHTML = '';
        resultsCount.style.display = 'none';

        try {
            const response = await fetch('/results');

            if (!response.ok) {
                throw new Error(`Server error (${response.status})`);
            }

            const data = await response.json();
            const companies = Array.isArray(data) ? data : [];

            if (companies.length === 0) {
                emptyState.style.display = 'block';
                emptyState.scrollIntoView({ behavior: 'smooth', block: 'center' });
                return;
            }

            // Update count
            countNumber.textContent = companies.length;
            resultsCount.style.display = 'flex';

            // Render cards
            companies.forEach((company) => {
                const card = renderCompanyCard(company);
                resultsGrid.appendChild(card);
            });

            // Smooth scroll
            resultsGrid.scrollIntoView({ behavior: 'smooth', block: 'start' });
            showSuccess(`Loaded ${companies.length} enriched ${companies.length === 1 ? 'company' : 'companies'}`);

        } catch (err) {
            showError(err.message || 'Failed to load results. Please try again.');
        } finally {
            setBtnLoading(resultsBtn, false);
        }
    }

    // Make showAllResults globally accessible for onclick
    window.showAllResults = showAllResults;

    // ── Form Submit Handler ──────────────────────────────────────────────────

    enrichForm.addEventListener('submit', function (e) {
        e.preventDefault();

        let rawUrl  = urlInput.value.trim();
        const name  = nameInput.value.trim();

        if (!rawUrl) {
            showError('Please enter a website URL.');
            urlInput.focus();
            return;
        }
        if (!name) {
            showError('Please enter a company or website name.');
            nameInput.focus();
            return;
        }

        const url = normaliseUrl(rawUrl);
        urlInput.value = url; // update input to show normalised URL

        if (!isValidUrl(url)) {
            showError('Please enter a valid URL (e.g. https://example.com)');
            urlInput.focus();
            return;
        }

        enrichCompany(url, name);
    });

    // ── Auto-prepend protocol hint ───────────────────────────────────────────

    urlInput.addEventListener('blur', function () {
        const val = this.value.trim();
        if (val && !/^https?:\/\//i.test(val)) {
            this.value = 'https://' + val;
        }
    });

    // ── Keyboard shortcuts ───────────────────────────────────────────────────

    document.addEventListener('keydown', function (e) {
        // Ctrl/Cmd + Enter to submit form when focused on inputs
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
            if (document.activeElement === urlInput || document.activeElement === nameInput) {
                enrichForm.dispatchEvent(new Event('submit'));
            }
        }
    });

})();
