/* ============================================================
   AAguard — Date Range Picker (vanilla)
   ============================================================ */
(function () {
    'use strict';

    const MONTHS = ['January','February','March','April','May','June',
                    'July','August','September','October','November','December'];
    const DOW = ['Su','Mo','Tu','We','Th','Fr','Sa'];

    const SHORTCUTS = [
        { key: 'today',      label: 'Today' },
        { key: 'yesterday',  label: 'Yesterday' },
        { key: 'this_week',  label: 'This week' },
        { key: 'last_week',  label: 'Last week' },
        { key: 'this_month', label: 'This month' },
        { key: 'last_month', label: 'Last month' },
        { key: 'this_year',  label: 'This year' },
        { key: 'last_year',  label: 'Last year' },
        { key: 'all_time',   label: 'All time' },
    ];

    const _pad = n => String(n).padStart(2, '0');
    const _ymd = d => d.getFullYear() + '-' + _pad(d.getMonth()+1) + '-' + _pad(d.getDate());
    const _fmtDisplay = ymd => {
        if (!ymd) return '';
        const [y, m, d] = ymd.split('-');
        return `${MONTHS[parseInt(m,10)-1].slice(0,3)} ${parseInt(d,10)}, ${y}`;
    };
    const _sameDay = (a,b) => a && b && a.getFullYear()===b.getFullYear()
        && a.getMonth()===b.getMonth() && a.getDate()===b.getDate();
    const _startOfDay = d => { const x = new Date(d); x.setHours(0,0,0,0); return x; };
    const _addDays = (d,n) => { const x = new Date(d); x.setDate(x.getDate()+n); return x; };
    const _addMonths = (d,n) => { const x = new Date(d); x.setMonth(x.getMonth()+n); return x; };

    function _applyShortcut(key) {
        const now = _startOfDay(new Date());
        const y = now.getFullYear();
        const m = now.getMonth();
        const dow = now.getDay();
        switch (key) {
            case 'today':      return [now, now];
            case 'yesterday':  return [_addDays(now,-1), _addDays(now,-1)];
            case 'this_week':  return [_addDays(now, -dow), now];
            case 'last_week':  return [_addDays(now, -dow-7), _addDays(now, -dow-1)];
            case 'this_month': return [new Date(y, m, 1), now];
            case 'last_month': return [new Date(y, m-1, 1), new Date(y, m, 0)];
            case 'this_year':  return [new Date(y, 0, 1), now];
            case 'last_year':  return [new Date(y-1, 0, 1), new Date(y-1, 11, 31)];
            case 'all_time':   return [new Date(2000, 0, 1), now];
            default:           return null;
        }
    }

    class DateRangePicker {
        constructor(el, opts = {}) {
            this.el = el;
            this.opts = Object.assign({
                start: null, end: null,
                onChange: null,
                placeholder: 'Pilih periode...',
            }, opts);

            this.startDate = this.opts.start ? this._parseYmd(this.opts.start) : null;
            this.endDate = this.opts.end ? this._parseYmd(this.opts.end) : null;
            this.viewDate = this.startDate ? new Date(this.startDate) : new Date();
            this.viewDate.setDate(1);
            this.hoverDate = null;
            this.pendingStart = this.startDate ? new Date(this.startDate) : null;
            this.pendingEnd = this.endDate ? new Date(this.endDate) : null;
            this.activeShortcut = null;

            this._build();
            this._bind();
            this._updateLabel();
        }

        _parseYmd(s) {
            if (!s) return null;
            const [y, m, d] = s.split('-').map(x => parseInt(x, 10));
            if (!y || !m || !d) return null;
            return new Date(y, m-1, d);
        }

        _build() {
            this.el.classList.add('drp');
            this.el.innerHTML = `
                <button type="button" class="drp-trigger">
                    <i class="fa-regular fa-calendar"></i>
                    <span class="drp-label">${this.opts.placeholder}</span>
                    <span class="drp-clear" role="button" tabindex="0" title="Hapus">
                        <i class="fa-solid fa-xmark"></i>
                    </span>
                </button>
                <div class="drp-panel">
                    <div class="drp-body">
                        <div class="drp-sidebar"></div>
                        <div class="drp-calendars">
                            <div class="drp-month" data-month="0"></div>
                            <div class="drp-month" data-month="1"></div>
                        </div>
                    </div>
                    <div class="drp-footer">
                        <div class="drp-inputs">
                            <input type="text" class="drp-input drp-input-from" placeholder="mm / dd / yyyy">
                            <span class="drp-sep">–</span>
                            <input type="text" class="drp-input drp-input-to" placeholder="mm / dd / yyyy">
                        </div>
                        <div class="drp-actions">
                            <button type="button" class="drp-btn drp-cancel">Cancel</button>
                            <button type="button" class="drp-btn drp-apply">Apply</button>
                        </div>
                    </div>
                </div>`;

            this.trigger = this.el.querySelector('.drp-trigger');
            this.labelEl = this.el.querySelector('.drp-label');
            this.clearBtn = this.el.querySelector('.drp-clear');
            this.sidebarEl = this.el.querySelector('.drp-sidebar');
            this.monthEls = this.el.querySelectorAll('.drp-month');
            this.inputFromEl = this.el.querySelector('.drp-input-from');
            this.inputToEl = this.el.querySelector('.drp-input-to');
            this.applyBtn = this.el.querySelector('.drp-apply');
            this.cancelBtn = this.el.querySelector('.drp-cancel');

            this.sidebarEl.innerHTML = SHORTCUTS.map(s =>
                `<button type="button" class="drp-shortcut" data-key="${s.key}">${s.label}</button>`
            ).join('');

            this._updateInputs();
            this._renderCalendars();
        }

        _bind() {
            this.trigger.addEventListener('click', (e) => {
                e.stopPropagation();
                if (e.target.closest('.drp-clear')) return;
                this.open();
            });

            this.clearBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.pendingStart = this.pendingEnd = null;
                this.startDate = this.endDate = null;
                this.activeShortcut = null;
                this._updateInputs();
                this._renderCalendars();
                this._commit();
            });

            this.sidebarEl.addEventListener('click', (e) => {
                const btn = e.target.closest('.drp-shortcut');
                if (!btn) return;
                e.stopPropagation();
                const range = _applyShortcut(btn.dataset.key);
                if (!range) return;
                this.pendingStart = range[0];
                this.pendingEnd = range[1];
                this.activeShortcut = btn.dataset.key;
                this.viewDate = new Date(range[0]);
                this.viewDate.setDate(1);
                this._updateInputs();
                this._renderCalendars();
                this._updateSidebar();
            });

            this.el.addEventListener('click', (e) => {
                const dayBtn = e.target.closest('.drp-day');
                if (dayBtn && !dayBtn.disabled && !dayBtn.classList.contains('other-month')) {
                    e.stopPropagation();
                    this._handleDayClick(dayBtn.dataset.ymd);
                    return;
                }
                const navBtn = e.target.closest('.drp-nav');
                if (navBtn) {
                    e.stopPropagation();
                    if (navBtn.dataset.nav === 'prev') this.viewDate = _addMonths(this.viewDate, -1);
                    else this.viewDate = _addMonths(this.viewDate, 1);
                    this._renderCalendars();
                }
            });

            this.el.addEventListener('mouseover', (e) => {
                const dayBtn = e.target.closest('.drp-day');
                if (!dayBtn || dayBtn.disabled || dayBtn.classList.contains('other-month')) {
                    if (this.hoverDate) { this.hoverDate = null; this._renderCalendars(); }
                    return;
                }
                if (this.pendingStart && !this.pendingEnd) {
                    this.hoverDate = this._parseYmd(dayBtn.dataset.ymd);
                    this._renderCalendars();
                }
            });

            this.inputFromEl.addEventListener('change', () => {
                const d = this._parseInputDate(this.inputFromEl.value);
                if (!d) return this._updateInputs();
                this.pendingStart = d;
                if (this.pendingEnd && d.getTime() > this.pendingEnd.getTime()) this.pendingEnd = null;
                this.viewDate = new Date(d); this.viewDate.setDate(1);
                this._renderCalendars();
            });
            this.inputToEl.addEventListener('change', () => {
                const d = this._parseInputDate(this.inputToEl.value);
                if (!d) return this._updateInputs();
                this.pendingEnd = d;
                if (this.pendingStart && d.getTime() < this.pendingStart.getTime()) this.pendingStart = null;
                this._renderCalendars();
            });

            this.applyBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this._commit();
                this.close();
            });
            this.cancelBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.close();
            });

            this._docClick = (e) => { if (!this.el.contains(e.target)) this.close(); };
            this._docKey = (e) => { if (e.key === 'Escape' && this.el.classList.contains('open')) this.close(); };
        }

        _handleDayClick(ymd) {
            const d = this._parseYmd(ymd);
            if (!d) return;
            this.activeShortcut = null;
            this.hoverDate = null;
            if (!this.pendingStart || (this.pendingStart && this.pendingEnd)) {
                this.pendingStart = d;
                this.pendingEnd = null;
            } else {
                if (d.getTime() < this.pendingStart.getTime()) {
                    this.pendingEnd = this.pendingStart;
                    this.pendingStart = d;
                } else {
                    this.pendingEnd = d;
                }
            }
            this._updateInputs();
            this._renderCalendars();
            this._updateSidebar();
        }

        _parseInputDate(s) {
            s = String(s || '').replace(/\s+/g, '');
            let m;
            if ((m = s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/)))
                return new Date(+m[3], +m[1]-1, +m[2]);
            if ((m = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/)))
                return new Date(+m[1], +m[2]-1, +m[3]);
            return null;
        }

        _updateInputs() {
            this.inputFromEl.value = this.pendingStart
                ? `${_pad(this.pendingStart.getMonth()+1)} / ${_pad(this.pendingStart.getDate())} / ${this.pendingStart.getFullYear()}`
                : '';
            this.inputToEl.value = this.pendingEnd
                ? `${_pad(this.pendingEnd.getMonth()+1)} / ${_pad(this.pendingEnd.getDate())} / ${this.pendingEnd.getFullYear()}`
                : '';
        }

        _updateSidebar() {
            this.sidebarEl.querySelectorAll('.drp-shortcut').forEach(b =>
                b.classList.toggle('active', b.dataset.key === this.activeShortcut));
        }

        _updateLabel() {
            if (this.startDate && this.endDate) {
                this.el.classList.add('has-value');
                if (_sameDay(this.startDate, this.endDate)) {
                    this.labelEl.textContent = _fmtDisplay(_ymd(this.startDate));
                } else {
                    this.labelEl.textContent = `${_fmtDisplay(_ymd(this.startDate))} – ${_fmtDisplay(_ymd(this.endDate))}`;
                }
            } else if (this.startDate) {
                this.el.classList.add('has-value');
                this.labelEl.textContent = _fmtDisplay(_ymd(this.startDate));
            } else {
                this.el.classList.remove('has-value');
                this.labelEl.textContent = this.opts.placeholder;
            }
        }

        _commit() {
            this.startDate = this.pendingStart ? new Date(this.pendingStart) : null;
            this.endDate = this.pendingEnd ? new Date(this.pendingEnd) : null;
            this._updateLabel();
            if (typeof this.opts.onChange === 'function') {
                this.opts.onChange(
                    this.startDate ? _ymd(this.startDate) : null,
                    this.endDate ? _ymd(this.endDate) : null
                );
            }
        }

        _renderCalendars() {
            const today = _startOfDay(new Date());
            const rs = this.pendingStart;
            const re = this.pendingEnd;
            const previewEnd = (!re && rs && this.hoverDate) ? this.hoverDate : re;

            for (let idx = 0; idx < 2; idx++) {
                const md = _addMonths(this.viewDate, idx);
                const y = md.getFullYear(), m = md.getMonth();
                const el = this.monthEls[idx];
                const startDow = new Date(y, m, 1).getDay();
                const daysInMonth = new Date(y, m+1, 0).getDate();
                const prevMonthDays = new Date(y, m, 0).getDate();

                const cells = [];
                DOW.forEach(d => cells.push(`<div class="drp-dow">${d}</div>`));

                for (let i = startDow - 1; i >= 0; i--) {
                    const dt = new Date(y, m-1, prevMonthDays - i);
                    cells.push(this._dayCell(dt, true, today, rs, previewEnd));
                }
                for (let dnum = 1; dnum <= daysInMonth; dnum++) {
                    cells.push(this._dayCell(new Date(y, m, dnum), false, today, rs, previewEnd));
                }
                const total = startDow + daysInMonth;
                const trailing = (7 - (total % 7)) % 7;
                for (let i = 1; i <= trailing; i++) {
                    cells.push(this._dayCell(new Date(y, m+1, i), true, today, rs, previewEnd));
                }

                const showPrev = idx === 0;
                const showNext = idx === 1;
                el.innerHTML = `
                    <div class="drp-month-header">
                        <button type="button" class="drp-nav ${showPrev ? '' : 'drp-nav-hidden'}" data-nav="prev" aria-label="Bulan sebelumnya">
                            <i class="fa-solid fa-chevron-left"></i>
                        </button>
                        <div class="drp-month-title">${MONTHS[m]} ${y}</div>
                        <button type="button" class="drp-nav ${showNext ? '' : 'drp-nav-hidden'}" data-nav="next" aria-label="Bulan berikutnya">
                            <i class="fa-solid fa-chevron-right"></i>
                        </button>
                    </div>
                    <div class="drp-grid">${cells.join('')}</div>`;
            }
        }

        _dayCell(dt, otherMonth, today, rs, re) {
            const ymd = _ymd(dt);
            const cls = ['drp-day'];
            if (otherMonth) cls.push('other-month');
            if (_sameDay(dt, today)) cls.push('today');

            const t = _startOfDay(dt).getTime();
            const rst = rs ? _startOfDay(rs).getTime() : null;
            const ret = re ? _startOfDay(re).getTime() : null;

            let isStart = false, isEnd = false, inRange = false;
            if (rst !== null && ret !== null) {
                if (t === rst) isStart = true;
                if (t === ret) isEnd = true;
                if (t > rst && t < ret) inRange = true;
            } else if (rst !== null && ret === null && t === rst) {
                isStart = isEnd = true;
            }

            if (inRange) cls.push('in-range');
            if (isStart) cls.push('range-start');
            if (isEnd) cls.push('range-end');

            return `<button type="button" class="${cls.join(' ')}" data-ymd="${ymd}" ${otherMonth ? 'disabled' : ''}>${dt.getDate()}</button>`;
        }

        open() {
            this.pendingStart = this.startDate ? new Date(this.startDate) : null;
            this.pendingEnd = this.endDate ? new Date(this.endDate) : null;
            this.hoverDate = null;
            this.el.classList.add('open');
            this._updateInputs();
            this._renderCalendars();
            this._updateSidebar();
            document.addEventListener('click', this._docClick, true);
            document.addEventListener('keydown', this._docKey, true);
        }

        close() {
            this.el.classList.remove('open');
            document.removeEventListener('click', this._docClick, true);
            document.removeEventListener('keydown', this._docKey, true);
        }

        setValue(startYmd, endYmd) {
            this.startDate = startYmd ? this._parseYmd(startYmd) : null;
            this.endDate = endYmd ? this._parseYmd(endYmd) : null;
            this.pendingStart = this.startDate ? new Date(this.startDate) : null;
            this.pendingEnd = this.endDate ? new Date(this.endDate) : null;
            if (this.startDate) {
                this.viewDate = new Date(this.startDate);
                this.viewDate.setDate(1);
            }
            this._updateLabel();
        }

        getValue() {
            return {
                start: this.startDate ? _ymd(this.startDate) : null,
                end: this.endDate ? _ymd(this.endDate) : null,
            };
        }
    }

    window.AAGuardDateRangePicker = { DateRangePicker };
    console.log('[DateRangePicker] Ready');
})();