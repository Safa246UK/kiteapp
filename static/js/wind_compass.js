/**
 * WindCompass — interactive 16-point compass picker for WindChaser
 * Usage (editable):  new WindCompass('container-id')
 * Usage (read-only): new WindCompass('container-id', { readOnly: true, size: 200 })
 */

const COMPASS_POINTS = [
    'N','NNE','NE','ENE','E','ESE','SE','SSE',
    'S','SSW','SW','WSW','W','WNW','NW','NNW'
];

const RATING_COLORS = {
    dangerous: '#9E9E9E',   // dark grey
    poor:      '#D4849A',   // muted rose pink
    good:      '#FF9800',   // orange
    perfect:   '#4CAF50'    // green
};

class WindCompass {
    constructor(containerId, options = {}) {
        this.container      = document.getElementById(containerId);
        this.size           = options.size     || 280;
        this.readOnly       = options.readOnly || false;
        this.cx             = this.size / 2;
        this.cy             = this.size / 2;
        this.outerR         = this.size * 0.40;
        this.innerR         = this.size * 0.13;
        this.labelR         = this.size * 0.47;
        this.selectedRating = 'perfect';
        this.sliceRatings   = {};
        this.sliceEls       = {};

        COMPASS_POINTS.forEach(p => (this.sliceRatings[p] = 'dangerous'));
        this._build();
        if (!this.readOnly) this._sync(); // initialise hidden inputs
    }

    /* ---------- geometry helpers ---------- */

    _xy(deg, r) {
        const rad = (deg - 90) * Math.PI / 180;
        return { x: this.cx + r * Math.cos(rad),
                 y: this.cy + r * Math.sin(rad) };
    }

    _path(i) {
        const step   = 360 / 16;
        const offset = -step / 2;           // centre N on 12 o'clock
        const a0 = i * step + offset,  a1 = a0 + step;
        const os  = this._xy(a0, this.outerR), oe  = this._xy(a1, this.outerR);
        const is_ = this._xy(a0, this.innerR), ie  = this._xy(a1, this.innerR);
        return [
            `M${is_.x},${is_.y}`,
            `L${os.x},${os.y}`,
            `A${this.outerR},${this.outerR} 0 0,1 ${oe.x},${oe.y}`,
            `L${ie.x},${ie.y}`,
            `A${this.innerR},${this.innerR} 0 0,0 ${is_.x},${is_.y}Z`
        ].join(' ');
    }

    /* ---------- build the SVG ---------- */

    _build() {
        const ns  = 'http://www.w3.org/2000/svg';
        const svg = document.createElementNS(ns, 'svg');
        svg.setAttribute('width',   this.size);
        svg.setAttribute('height',  this.size);
        svg.setAttribute('viewBox', `0 0 ${this.size} ${this.size}`);
        svg.style.cssText = 'display:block;margin:auto;';

        COMPASS_POINTS.forEach((pt, i) => {
            /* slice */
            const path = document.createElementNS(ns, 'path');
            path.setAttribute('d',            this._path(i));
            path.setAttribute('fill',         RATING_COLORS[this.sliceRatings[pt]]);
            path.setAttribute('stroke',       'rgba(255,255,255,0.75)');
            path.setAttribute('stroke-width', '1.5');

            if (!this.readOnly) {
                path.style.cursor = 'pointer';
                path.addEventListener('mouseenter', () => { path.style.opacity = '0.72'; });
                path.addEventListener('mouseleave', () => { path.style.opacity = '1.0';  });
                path.addEventListener('click', () => {
                    this.sliceRatings[pt] = this.selectedRating;
                    path.setAttribute('fill', RATING_COLORS[this.selectedRating]);
                    this._sync();
                });
            }

            this.sliceEls[pt] = path;
            svg.appendChild(path);

            /* label */
            const mid = i * (360 / 16);   // centre of slice (N centred on 12 o'clock)
            const lp  = this._xy(mid, this.labelR);
            const txt = document.createElementNS(ns, 'text');
            txt.setAttribute('x',                 lp.x);
            txt.setAttribute('y',                 lp.y);
            txt.setAttribute('text-anchor',       'middle');
            txt.setAttribute('dominant-baseline', 'middle');
            txt.setAttribute('font-size',         this.size < 220 ? '7' : '9');
            txt.setAttribute('font-weight',       ['N','E','S','W'].includes(pt) ? 'bold' : 'normal');
            txt.setAttribute('fill',              '#222');
            txt.setAttribute('pointer-events',    'none');
            txt.textContent = pt;
            svg.appendChild(txt);
        });

        /* centre circle */
        const circ = document.createElementNS(ns, 'circle');
        circ.setAttribute('cx', this.cx);      circ.setAttribute('cy', this.cy);
        circ.setAttribute('r',  this.innerR - 2);
        circ.setAttribute('fill',         '#f8f9fa');
        circ.setAttribute('stroke',       '#bbb');
        circ.setAttribute('stroke-width', '1');
        svg.appendChild(circ);

        /* centre icon */
        const em = document.createElementNS(ns, 'text');
        em.setAttribute('x',                 this.cx);
        em.setAttribute('y',                 this.cy);
        em.setAttribute('text-anchor',       'middle');
        em.setAttribute('dominant-baseline', 'middle');
        em.setAttribute('font-size',         this.size < 220 ? '12' : '18');
        em.setAttribute('pointer-events',    'none');
        em.textContent = '🧭';
        svg.appendChild(em);

        this.container.innerHTML = '';
        this.container.appendChild(svg);
    }

    /* ---------- public API ---------- */

    /** Set which rating the next slice-click will assign */
    setRating(rating) { this.selectedRating = rating; }

    /** Reset all slices back to dangerous */
    resetAll() {
        COMPASS_POINTS.forEach(p => {
            this.sliceRatings[p] = 'dangerous';
            this.sliceEls[p].setAttribute('fill', RATING_COLORS['dangerous']);
        });
        this._sync();
    }

    /**
     * Load from saved data object.
     * data = { perfect: "SW,WSW,W", good: "S,WNW", okay: "", poor: "", dangerous: "..." }
     */
    load(data) {
        COMPASS_POINTS.forEach(p => (this.sliceRatings[p] = 'dangerous'));
        ['perfect', 'good', 'poor', 'dangerous'].forEach(rating => {
            (data[rating] || '').split(',').forEach(p => {
                p = p.trim();
                if (p && p in this.sliceRatings) this.sliceRatings[p] = rating;
            });
        });
        // Legacy: any previously-saved "okay" directions become dangerous
        (data['okay'] || '').split(',').forEach(p => {
            p = p.trim();
            if (p) this.sliceRatings[p] = 'dangerous';
        });
        COMPASS_POINTS.forEach(p => {
            this.sliceEls[p].setAttribute('fill', RATING_COLORS[this.sliceRatings[p]]);
        });
        this._sync();
    }

    /* ---------- private ---------- */

    /** Write current state into the hidden form inputs */
    _sync() {
        const groups = { perfect: [], good: [], poor: [], dangerous: [] };
        COMPASS_POINTS.forEach(p => groups[this.sliceRatings[p]].push(p));
        Object.entries(groups).forEach(([rating, pts]) => {
            const el = document.getElementById('hidden_' + rating + '_directions');
            if (el) el.value = pts.join(',');
        });
        // Clear legacy okay field if present in the form
        const okEl = document.getElementById('hidden_okay_directions');
        if (okEl) okEl.value = '';
    }
}
