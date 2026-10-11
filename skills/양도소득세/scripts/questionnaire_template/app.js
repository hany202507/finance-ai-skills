/* 질문지 화면. 문항 정의(defs)와 조건(conditions)을 읽어 양식을 그리고, 답을 사실관계 JSON 으로 내려받는다.
 * 네트워크를 쓰지 않는다. 입력은 이 브라우저의 localStorage 에만 임시로 남는다.
 */
(function () {
  'use strict';
  var defs = JSON.parse(document.getElementById('defs').textContent);
  var conds = JSON.parse(document.getElementById('conditions').textContent);
  var core = makeCore(defs, conds);
  var STORE_KEY = 'gridie-yangdo-questionnaire-v1';
  var FILE_NAME = '양도소득세_답변.json';

  // ---- 저장소 -------------------------------------------------------------
  function fresh() {
    return { v: 1, sig: defs.sig, nextAsset: 2, nextHouse: 1, hidePending: false,
             glob: { ans: {}, mo: {} }, assets: [{ id: '자산1', ans: {}, mo: {} }], houses: [] };
  }
  function loadStore() {
    try {
      var s = JSON.parse(window.localStorage.getItem(STORE_KEY));
      if (s && s.v === 1 && s.sig === defs.sig && Array.isArray(s.assets) && s.assets.length && Array.isArray(s.houses) && s.glob) return s;
    } catch (e) { /* 저장소를 못 쓰는 환경은 빈 양식으로 시작한다 */ }
    return null;
  }
  function saveStore() {
    try { window.localStorage.setItem(STORE_KEY, JSON.stringify(store)); } catch (e) { /* 저장 못 해도 계속한다 */ }
  }
  var store = loadStore() || fresh();

  // ---- 작은 도구 ----------------------------------------------------------
  function el(tag, attrs, kids) {
    var e = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      var v = attrs[k];
      if (v === null || v === undefined || v === false) return;
      if (k === 'class') e.className = v;
      else if (k === 'text') e.textContent = v;
      else if (k.slice(0, 2) === 'on') e.addEventListener(k.slice(2), v);
      else e.setAttribute(k, v === true ? '' : v);
    });
    (kids || []).forEach(function (c) { if (c) e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return e;
  }
  var uidN = 0;
  function uid(p) { uidN += 1; return p + uidN; }
  function clone(o) { return JSON.parse(JSON.stringify(o)); }
  function copyObj(o) { return Object.assign({}, o || {}); }

  var recs = [];          // 화면에 그린 문항 {q, unit, el, err, grp}
  var groups = [];        // 소제목 묶음 {el, recs}
  var renderHouses = function () {};
  var subBoxes = [];      // 집 행의 「회계사가 확인한 뒤 묻는 항목」 상자

  var building = false;   // 양식을 짜는 동안에는 갱신하지 않는다(빈 첫 줄을 넣는 입력도 여기서 일어난다)
  function touch() { if (building) return; saveStore(); refresh(); }

  // ---- 입력 위젯 ----------------------------------------------------------
  function usesSelect(spec, opt) { return spec.opts.length > 6 || !!(opt && opt.compact); }

  function wBool(get, put) {
    var name = uid('b'), box = el('div', { class: 'opts' });
    [[true, '예'], [false, '아니오']].forEach(function (p) {
      var inp = el('input', { type: 'radio', name: name });
      inp.checked = get() === p[0];
      inp.addEventListener('change', function () { if (inp.checked) put(p[0]); });
      box.appendChild(el('label', { class: 'opt' }, [inp, el('span', { text: p[1] })]));
    });
    return box;
  }

  function wChoice(spec, get, put, opt) {
    if (usesSelect(spec, opt)) {
      var sel = el('select');
      sel.appendChild(el('option', { value: '', text: '선택하세요' }));
      spec.opts.forEach(function (o) { sel.appendChild(el('option', { value: o[0], text: o[1] })); });
      sel.value = get() || '';
      sel.addEventListener('change', function () { put(sel.value || undefined); });
      return sel;
    }
    var name = uid('c'), box = el('div', { class: 'opts col' });
    spec.opts.forEach(function (o) {
      var inp = el('input', { type: 'radio', name: name });
      inp.checked = get() === o[0];
      inp.addEventListener('change', function () { if (inp.checked) put(o[0]); });
      box.appendChild(el('label', { class: 'opt' }, [inp, el('span', { text: o[1] })]));
    });
    return box;
  }

  function wMulti(spec, get, put) {
    var box = el('div', { class: 'opts col' });
    var cbs = [];
    spec.opts.forEach(function (o) {
      var inp = el('input', { type: 'checkbox' });
      inp.checked = (get() || []).indexOf(o[0]) >= 0;
      inp.addEventListener('change', function () {
        var cur = (get() || []).slice();
        var i = cur.indexOf(o[0]);
        if (inp.checked && i < 0) cur.push(o[0]);
        if (!inp.checked && i >= 0) cur.splice(i, 1);
        // 「해당 없음」 류는 다른 선택과 함께 둘 수 없다
        if (inp.checked && spec.alone && spec.alone.indexOf(o[0]) >= 0) {
          cur = [o[0]];
          cbs.forEach(function (c) { if (c.value !== o[0]) c.inp.checked = false; });
        } else if (inp.checked && spec.alone) {
          cur = cur.filter(function (x) { return spec.alone.indexOf(x) < 0; });
          cbs.forEach(function (c) { if (spec.alone.indexOf(c.value) >= 0) c.inp.checked = false; });
        }
        put(cur);
      });
      cbs.push({ value: o[0], inp: inp });
      box.appendChild(el('label', { class: 'opt' }, [inp, el('span', { text: o[1] })]));
    });
    return box;
  }

  function wInput(kind, spec, get, put) {
    var inp = el('input', { type: kind === 'date' ? 'date' : 'text' });
    if (kind === 'int') { inp.setAttribute('inputmode', 'numeric'); inp.setAttribute('placeholder', spec.hint || '숫자만'); }
    if (kind === 'num') { inp.setAttribute('inputmode', 'decimal'); inp.setAttribute('placeholder', spec.hint || '숫자만'); }
    if (kind === 'text' && spec.hint) inp.setAttribute('placeholder', spec.hint);
    if (kind === 'text' && spec.digits) inp.setAttribute('inputmode', 'numeric');
    var v = get();
    inp.value = v === undefined || v === null ? '' : String(v);
    inp.addEventListener('input', function () { put(inp.value); });
    if (kind === 'int') {
      inp.addEventListener('blur', function () {
        var s = inp.value.replace(/[,\s원]/g, '');
        if (/^\d+$/.test(s)) { inp.value = Number(s).toLocaleString('en-US'); put(inp.value); }
      });
    }
    var kids = [inp];
    if (kind === 'text' && spec.suggest) {
      var id = uid('dl');
      inp.setAttribute('list', id);
      var dl = el('datalist', { id: id });
      spec.suggest.forEach(function (s) { dl.appendChild(el('option', { value: s })); });
      kids.push(dl);
    }
    var unit = kind === 'int' ? '원' : (spec.unit || '');
    if (unit) kids.push(el('span', { class: 'unit', text: unit }));
    return el('span', { class: 'inwrap' }, kids);
  }

  function wAddr(get, put) {
    var v = copyObj(get());
    var sel = el('select', { 'aria-label': '시·도' });
    sel.appendChild(el('option', { value: '', text: '시·도 선택' }));
    defs.sido.forEach(function (s) { sel.appendChild(el('option', { value: s, text: s })); });
    sel.value = v['시도'] || '';
    var gu = el('input', { type: 'text', placeholder: '시·군·구 (예: 성동구)', 'aria-label': '시·군·구' });
    var dong = el('input', { type: 'text', placeholder: '읍·면·동 (예: 성수동)', 'aria-label': '읍·면·동' });
    gu.value = v['시군구'] || '';
    dong.value = v['읍면동'] || '';
    sel.addEventListener('change', function () { v['시도'] = sel.value; put(copyObj(v)); });
    gu.addEventListener('input', function () { v['시군구'] = gu.value; put(copyObj(v)); });
    dong.addEventListener('input', function () { v['읍면동'] = dong.value; put(copyObj(v)); });
    return el('div', { class: 'addr' }, [sel, gu, dong]);
  }

  function wShare(spec, get, put) {
    var v = copyObj(get());
    var name = uid('s'), box = el('div', { class: 'share' });
    var n = el('input', { type: 'text', inputmode: 'numeric', placeholder: '분자', size: 4, 'aria-label': '지분 분자' });
    var d = el('input', { type: 'text', inputmode: 'numeric', placeholder: '분모', size: 4, 'aria-label': '지분 분모' });
    n.value = v.n || ''; d.value = v.d || '';
    var frac = el('span', { class: 'inwrap' }, [n, el('span', { class: 'unit', text: '/' }), d]);
    function show() { frac.hidden = v.kind !== '공동'; }
    spec.opts.forEach(function (o) {
      var inp = el('input', { type: 'radio', name: name });
      inp.checked = v.kind === o[0];
      inp.addEventListener('change', function () { if (inp.checked) { v.kind = o[0]; show(); put(copyObj(v)); } });
      box.appendChild(el('label', { class: 'opt' }, [inp, el('span', { text: o[1] })]));
    });
    n.addEventListener('input', function () { v.n = n.value; put(copyObj(v)); });
    d.addEventListener('input', function () { v.d = d.value; put(copyObj(v)); });
    box.appendChild(frac);
    show();
    return box;
  }

  function isGroupType(s, opt) {
    return s.t === 'obj' || s.t === 'addr' || s.t === 'share' || s.t === 'bool' || s.t === 'multi' || s.t === 'list' ||
           (s.t === 'choice' && !usesSelect(s, opt));
  }

  function wObj(spec, get, put, opt) {
    var box = el('div', { class: 'obj' });
    spec.fields.forEach(function (fd) {
      var child = widget(fd.s, function () { return (get() || {})[fd.n]; }, function (v) {
        var o = copyObj(get()); o[fd.n] = v; put(o);
      }, { compact: true });
      var wrap;
      if (isGroupType(fd.s, { compact: true })) {
        wrap = el('fieldset', { class: 'fld' + (fd.s.t === 'obj' || fd.s.t === 'addr' ? ' wide' : '') },
                  [el('legend', { text: fd.label }), child]);
      } else {
        wrap = el('label', { class: 'fld' }, [el('span', { class: 'flabel', text: fd.label }), child]);
      }
      box.appendChild(wrap);
    });
    return box;
  }

  function wList(spec, get, put) {
    var box = el('div', { class: 'list' });
    var rowsBox = el('div', { class: 'rows' });
    var addBtn = el('button', { type: 'button', class: 'add', text: spec.add || '추가' });
    var noneCb = el('input', { type: 'checkbox' });
    function cur() { var v = get(); return v && Array.isArray(v.rows) ? v : { rows: [], none: false }; }
    function save(rows, none) { put({ rows: rows, none: none }); }
    function render() {
      rowsBox.textContent = '';
      var v = cur();
      noneCb.checked = !!v.none;
      rowsBox.hidden = !!v.none;
      addBtn.hidden = !!v.none;
      v.rows.forEach(function (r, i) {
        var del = el('button', { type: 'button', class: 'danger', text: '삭제' });
        del.addEventListener('click', function () {
          var rows = cur().rows.slice(); rows.splice(i, 1); save(rows, false); render();
        });
        var body = widget(spec.row, function () { return cur().rows[i]; }, function (nv) {
          var rows = cur().rows.slice(); rows[i] = nv; save(rows, false);
        }, { compact: true });
        rowsBox.appendChild(el('div', { class: 'row' }, [
          el('div', { class: 'rowhead' }, [el('strong', { text: (spec.noun || '항목') + ' ' + (i + 1) }), del]), body]));
      });
    }
    addBtn.addEventListener('click', function () {
      var rows = cur().rows.slice(); rows.push(spec.as === 'scalars' ? '' : {}); save(rows, false); render();
    });
    noneCb.addEventListener('change', function () {
      if (noneCb.checked) save(cur().rows, true); else save(cur().rows, false);
      render();
    });
    if (!cur().rows.length && !cur().none) { var first = cur().rows.slice(); first.push(spec.as === 'scalars' ? '' : {}); put({ rows: first, none: false }); }
    render();
    box.appendChild(rowsBox);
    box.appendChild(addBtn);
    if (spec.none) box.appendChild(el('label', { class: 'mo' }, [noneCb, ' ' + spec.none]));
    return box;
  }

  function widget(spec, get, put, opt) {
    switch (spec.t) {
      case 'bool': return wBool(get, put);
      case 'choice': return wChoice(spec, get, put, opt);
      case 'sido': return wChoice({ opts: defs.sido.map(function (s) { return [s, s]; }) }, get, put, { compact: true });
      case 'multi': return wMulti(spec, get, put);
      case 'date': return wInput('date', spec, get, put);
      case 'int': return wInput('int', spec, get, put);
      case 'num': return wInput('num', spec, get, put);
      case 'text': return wInput('text', spec, get, put);
      case 'addr': return wAddr(get, put);
      case 'share': return wShare(spec, get, put);
      case 'obj': return wObj(spec, get, put, opt);
      case 'list': return wList(spec, get, put);
    }
    throw new Error('알 수 없는 spec: ' + spec.t);
  }

  // ---- 문항 한 개 ---------------------------------------------------------
  function whyBox(q) {
    var w = q.why, parts = [];
    if (w.used.length) parts.push(el('p', { text: '이 답이 쓰이는 곳: ' + w.used.join(', ') }));
    if (w.law.length) {
      var p = el('p', { text: '근거: ' });
      w.law.forEach(function (g, i) {
        if (i) p.appendChild(document.createTextNode(' / '));
        if (g.h) p.appendChild(el('a', { href: g.h, target: '_blank', rel: 'noopener noreferrer', text: g.t }));
        else p.appendChild(document.createTextNode(g.t));
      });
      parts.push(p);
    }
    if (w.docs.length) parts.push(el('p', { text: '준비하면 좋은 서류: ' + w.docs.join(', ') }));
    if (w.where.length) parts.push(el('p', { text: '모를 때 확인하는 곳: ' + w.where.join(', ') }));
    if (!parts.length) return null;
    return el('details', { class: 'why' }, [el('summary', { text: '왜 묻는지, 근거, 준비 서류' })].concat(parts));
  }

  function questionBlock(q, holder, unit) {
    var node = el('div', { class: 'q', id: 'q-' + q.id + '-' + unit });
    node.setAttribute('data-q', q.id);
    node.setAttribute('data-u', unit);
    node.appendChild(el('div', { class: 'qhead' }, [el('span', { class: 'qid', text: q.id }), el('span', { class: 'qtext', text: q.text })]));
    if (q.help) node.appendChild(el('p', { class: 'help', text: q.help }));
    var moCb = null;
    var fieldBox = el('div', { class: 'field' });
    if (q.spec.t === 'houses') {
      fieldBox.appendChild(housesWidget(q));
    } else {
      fieldBox.appendChild(widget(q.spec, function () { return holder.ans[q.id]; }, function (v) {
        holder.ans[q.id] = v;
        if (holder.mo[q.id]) { delete holder.mo[q.id]; if (moCb) moCb.checked = false; node.classList.remove('is-mo'); }
        touch();
      }, {}));
    }
    node.appendChild(fieldBox);
    if (q.spec.t !== 'list' && q.spec.t !== 'houses' && !q.moreum) {
      moCb = el('input', { type: 'checkbox' });
      moCb.checked = !!holder.mo[q.id];
      if (moCb.checked) node.classList.add('is-mo');
      moCb.addEventListener('change', function () {
        if (moCb.checked) holder.mo[q.id] = true; else delete holder.mo[q.id];
        node.classList.toggle('is-mo', moCb.checked);
        touch();
      });
      node.appendChild(el('label', { class: 'mo' }, [moCb, ' 모르겠어요 (회계사가 확인합니다)']));
    }
    var why = whyBox(q);
    if (why) node.appendChild(why);
    node.appendChild(el('p', { class: 'pnote', text: '이 질문이 필요한지는 회계사가 확인합니다. 해당하면 답해 주세요.' }));
    var err = el('div', { class: 'err', role: 'alert' });
    err.hidden = true;
    node.appendChild(err);
    var rec = { q: q, unit: unit, el: node, err: err, holder: holder };
    recs.push(rec);
    return { node: node, rec: rec };
  }

  // ---- 집 목록(H04) -------------------------------------------------------
  function assetLabel(id) {
    for (var i = 0; i < store.assets.length; i++) if (store.assets[i].id === id) return '양도한 부동산 ' + (i + 1);
    return id;
  }

  function houseRow(h, i) {
    var spec = defs.houseRow, sold = !!h.asset;
    var row = el('div', { class: 'row house' });
    var head = el('div', { class: 'rowhead' }, [el('strong', { text: sold ? '판 집 (' + assetLabel(h.asset) + ')' : '집 ' + (i + 1) })]);
    if (!sold) {
      var del = el('button', { type: 'button', class: 'danger', text: '삭제' });
      del.addEventListener('click', function () {
        store.houses = store.houses.filter(function (x) { return x !== h; });
        renderHouses(); touch();
      });
      head.appendChild(del);
    }
    row.appendChild(head);
    if (sold) row.appendChild(el('p', { class: 'info', text: '주소, 형태, 산 날, 갖게 된 경위, 지분은 위에서 적은 값이 그대로 들어갑니다.' }));
    function fieldOf(fd) {
      return widget(fd.s, function () { return (h.f || {})[fd.n]; }, function (v) { h.f = h.f || {}; h.f[fd.n] = v; touch(); }, { compact: true });
    }
    var obj = el('div', { class: 'obj' });
    spec.main.forEach(function (fd) {
      if (sold && fd.sold === false) return;
      var child = fieldOf(fd);
      var wrap = isGroupType(fd.s, { compact: true })
        ? el('fieldset', { class: 'fld' + (fd.s.t === 'addr' ? ' wide' : '') }, [el('legend', { text: fd.label }), child])
        : el('label', { class: 'fld' }, [el('span', { class: 'flabel', text: fd.label }), child]);
      obj.appendChild(wrap);
    });
    row.appendChild(obj);
    var sub = el('div', { class: 'sub' }, [el('p', { class: 'info', text: '이 항목이 필요한지는 회계사가 확인합니다. 해당하면 답해 주세요.' })]);
    var lastQ = null;
    var subObj = el('div', { class: 'obj' });
    spec.extra.forEach(function (fd) {
      var child = fieldOf(fd);
      var kids = [];
      if (fd.q !== lastQ) { kids.push(el('span', { class: 'subq', text: fd.q + ' ' + fd.qtext })); lastQ = fd.q; }
      var wrap = isGroupType(fd.s, { compact: true })
        ? el('fieldset', { class: 'fld wide' }, [el('legend', { text: fd.label }), child])
        : el('label', { class: 'fld' }, [el('span', { class: 'flabel', text: fd.label }), child]);
      var cell = el('div', { class: 'fld wide' }, kids.concat([wrap]));
      subObj.appendChild(cell);
    });
    sub.appendChild(subObj);
    sub.hidden = !!store.hidePending;
    subBoxes.push(sub);
    row.appendChild(sub);
    return row;
  }

  function housesWidget(q) {
    var box = el('div', { class: 'houses list' });
    var list = el('div', { class: 'rows' });
    var add = el('button', { type: 'button', class: 'add', text: '집 추가' });
    var doneCb = el('input', { type: 'checkbox' });
    doneCb.checked = !!(store.glob.ans[q.id] && store.glob.ans[q.id].done);
    doneCb.addEventListener('change', function () { store.glob.ans[q.id] = { done: doneCb.checked }; touch(); });
    renderHouses = function () {
      list.textContent = '';
      subBoxes = [];
      store.houses.forEach(function (h, i) { list.appendChild(houseRow(h, i)); });
    };
    add.addEventListener('click', function () {
      store.houses.push({ id: 'H' + store.nextHouse++, asset: null, f: {} });
      renderHouses(); touch();
    });
    renderHouses();
    box.appendChild(list);
    box.appendChild(add);
    box.appendChild(el('label', { class: 'mo' }, [doneCb, ' 세대가 가진 집은 위에 적은 것이 전부입니다']));
    return box;
  }

  // 판 집(주택)마다 목록에 한 줄이 있어야 한다. 자산의 종류 답이 바뀌면 맞춘다.
  function syncHouses(c) {
    var changed = false, need = {};
    var kq = defs.assetKind.q;
    store.assets.forEach(function (a) {
      if (c.st[kq][a.id] === 'T' && a.ans[kq] === defs.assetKind.house && !(a.mo && a.mo[kq])) need[a.id] = true;
    });
    var keep = store.houses.filter(function (h) { return !h.asset || need[h.asset]; });
    if (keep.length !== store.houses.length) { store.houses = keep; changed = true; }
    var have = {};
    store.houses.forEach(function (h) { if (h.asset) have[h.asset] = true; });
    var add = [];
    store.assets.forEach(function (a) {
      if (need[a.id] && !have[a.id]) add.push({ id: 'H' + store.nextHouse++, asset: a.id, f: {} });
    });
    if (add.length) { store.houses = add.concat(store.houses); changed = true; }
    return changed;
  }

  // ---- 쪽 짜기 ------------------------------------------------------------
  function groupedBlocks(list, holder, unit, withHeading) {
    var frag = document.createDocumentFragment(), cur = null, lastSec = null;
    list.forEach(function (q) {
      if (withHeading && q.sec !== lastSec) {
        cur = { el: el('div', { class: 'grp' }, [el('h4', { text: defs.sections[q.sec] || q.sec })]), recs: [] };
        groups.push(cur);
        frag.appendChild(cur.el);
        lastSec = q.sec;
      }
      var b = questionBlock(q, holder, unit);
      if (cur) { cur.el.appendChild(b.node); cur.recs.push(b.rec); } else frag.appendChild(b.node);
    });
    return frag;
  }

  function assetCard(a, i) {
    var card = el('section', { class: 'card' });
    var head = el('header', null, [el('h3', { text: '양도한 부동산 ' + (i + 1) })]);
    if (store.assets.length > 1) {
      var del = el('button', { type: 'button', class: 'danger', text: '이 부동산 삭제' });
      del.addEventListener('click', function () {
        if (!window.confirm('이 부동산에 적은 답을 모두 지웁니다. 계속하려면 확인을 누르세요.')) return;
        store.assets = store.assets.filter(function (x) { return x !== a; });
        buildAll(); touch();
      });
      head.appendChild(del);
    }
    card.appendChild(head);
    card.appendChild(groupedBlocks(core.Q.filter(function (q) { return q.zone === 'asset'; }), a, a.id, true));
    return card;
  }

  function buildAll() {
    building = true;
    try {
      recs = []; groups = []; subBoxes = [];
      var top = document.getElementById('zone-top'), assets = document.getElementById('zone-assets'), house = document.getElementById('zone-house');
      top.textContent = ''; assets.textContent = ''; house.textContent = '';
      top.appendChild(groupedBlocks(core.Q.filter(function (q) { return q.zone === 'top'; }), store.glob, '', false));
      store.assets.forEach(function (a, i) { assets.appendChild(assetCard(a, i)); });
      house.appendChild(groupedBlocks(core.Q.filter(function (q) { return q.zone === 'house'; }), store.glob, '', false));
    } finally {
      building = false;
    }
  }

  // ---- 갱신 ---------------------------------------------------------------
  function answeredRec(r) {
    if (r.q.spec.t === 'houses') {
      var d = store.glob.ans[r.q.id];
      return !!(d && d.done);
    }
    return core.isAnswered(r.q, r.holder);
  }

  function refresh() {
    var c = core.compute(store);
    if (syncHouses(c)) { renderHouses(); saveStore(); c = core.compute(store); }
    var built = core.buildFacts(store, c);
    var errBy = {};
    built.errors.forEach(function (e) { var k = e.qid + '|' + e.unit; (errBy[k] = errBy[k] || []).push(e.msg); });
    var total = 0, done = 0, open = [];
    recs.forEach(function (r) {
      var s = (c.st[r.q.id] && c.st[r.q.id][r.unit]) || 'U';
      var visible = s === 'T' || (s === 'E' && !store.hidePending);
      r.visible = visible;
      r.el.hidden = !visible;
      r.el.classList.toggle('pending', s === 'E');
      var msgs = errBy[r.q.id + '|' + r.unit] || [];
      r.err.textContent = '';
      msgs.forEach(function (m) { r.err.appendChild(el('p', { text: m })); });
      r.err.hidden = !msgs.length;
      if (s === 'T') { total += 1; if (answeredRec(r)) done += 1; else open.push(r); }
    });
    groups.forEach(function (g) { g.el.hidden = !g.recs.some(function (r) { return r.visible; }); });
    var zoneShown = { top: false, house: false };
    recs.forEach(function (r) { if (r.visible && zoneShown.hasOwnProperty(r.q.zone)) zoneShown[r.q.zone] = true; });
    document.getElementById('sec-top').hidden = !zoneShown.top;
    document.getElementById('sec-house').hidden = !zoneShown.house;
    subBoxes.forEach(function (b) { b.hidden = !!store.hidePending; });
    var pend = 0;
    core.Q.forEach(function (q) {
      Object.keys(c.st[q.id]).forEach(function (u) { if (c.st[q.id][u] === 'E') pend += 1; });
    });
    document.getElementById('progress').textContent = '답한 문항 ' + done + ' / 해당 문항 ' + total;
    document.getElementById('pending-label').textContent = '회계사가 확인하는 항목 숨기기 (' + pend + '개)';
    document.getElementById('hide-pending').checked = !!store.hidePending;
    // 마무리
    var errBox = document.getElementById('done-errors'), openBox = document.getElementById('done-open');
    errBox.textContent = ''; openBox.textContent = '';
    if (built.errors.length) {
      var ul = el('ul');
      built.errors.forEach(function (e) {
        var target = e.qid === defs.houseQuestion ? 'q-' + e.qid + '-' : 'q-' + e.qid + '-' + e.unit;
        ul.appendChild(el('li', null, [el('a', { href: '#' + target, text: e.qid }), ' ' + e.msg]));
      });
      errBox.appendChild(el('p', { text: '내려받기 전에 고쳐야 할 입력란이 있습니다.' }));
      errBox.appendChild(ul);
    }
    if (open.length) {
      var ol = el('ul');
      open.forEach(function (r) {
        ol.appendChild(el('li', null, [el('a', { href: '#' + r.el.id, text: r.q.id }), ' ' + r.q.text]));
      });
      openBox.appendChild(el('p', { text: '아직 답하지 않은 문항 ' + open.length + '개. 비워 둔 채 내려받아도 됩니다. 회계사가 이어서 묻습니다.' }));
      openBox.appendChild(ol);
    }
    var blocked = built.errors.length > 0;
    ['download', 'download-top'].forEach(function (id) { document.getElementById(id).disabled = blocked; });
    document.getElementById('preview').textContent = JSON.stringify(built.facts, null, 2);
    return built;
  }

  // ---- 내려받기 -----------------------------------------------------------
  function download() {
    var built = refresh();
    if (built.errors.length) return;
    var text = JSON.stringify(built.facts, null, 2) + '\n';
    var blob = new Blob([text], { type: 'application/json' });
    var url = URL.createObjectURL(blob);
    var a = el('a', { href: url, download: FILE_NAME });
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 2000);
  }

  // ---- 시작 ---------------------------------------------------------------
  document.getElementById('add-asset').addEventListener('click', function () {
    store.assets.push({ id: '자산' + store.nextAsset++, ans: {}, mo: {} });
    buildAll(); touch();
  });
  document.getElementById('hide-pending').addEventListener('change', function (e) { store.hidePending = e.target.checked; touch(); });
  document.getElementById('download').addEventListener('click', download);
  document.getElementById('download-top').addEventListener('click', download);
  document.getElementById('reset').addEventListener('click', function () {
    if (!window.confirm('입력한 내용을 모두 지우고 다시 시작합니다. 계속하려면 확인을 누르세요.')) return;
    try { window.localStorage.removeItem(STORE_KEY); } catch (e) { /* 무시 */ }
    store = fresh();
    buildAll(); touch();
  });

  try {
    buildAll();
    refresh();
  } catch (e) {
    // 임시로 남은 답이 지금 양식과 맞지 않으면 버리고 빈 양식으로 다시 시작한다
    try { window.localStorage.removeItem(STORE_KEY); } catch (e2) { /* 무시 */ }
    store = fresh();
    buildAll();
    refresh();
  }

  // 점검과 시험이 같은 논리를 부를 수 있게 둔다(네트워크와 무관)
  window.gridieYangdo = {
    core: core,
    getStore: function () { return store; },
    setStore: function (s) { store = s; buildAll(); touch(); },
    facts: function () { return core.buildFacts(store).facts; },
    refresh: refresh
  };
})();
