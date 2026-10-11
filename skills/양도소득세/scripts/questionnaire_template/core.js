/* 질문지 핵심 논리. 화면(DOM)을 쓰지 않는다. node 시험이 이 파일만 떼어 파이썬 판정과 견준다.
 *
 * 조건 문법은 질문지/문항.json 머리의 「조건표기」와 yangdo/questions.py 의 판정과 같다.
 *   '항상' 이거나 {'모두': [...]} 또는 {'하나라도': [...]}. 항목은 [문항 id 나 엔진값, 연산자, 값].
 * 파이썬 엔진만 아는 값(엔진.이름, 주택.이름)은 이 화면이 모른다. 그런 항목은 'E'(회계사가 확인)로 둔다.
 *
 * 한 문항의 상태
 *   T 보인다.  F 숨긴다.  U 앞 답을 기다린다(숨김).  E 엔진 값이 있어야 정해진다(회계사가 확인).
 */
function makeCore(defs, conds) {
  'use strict';
  var Q = defs.questions;
  var byId = {};
  Q.forEach(function (q, i) { q.idx = i; byId[q.id] = q; });
  var OPS = { '==': 1, '!=': 1, 'in': 1, 'not_in': 1, '>=': 1, '<=': 1, '<': 1, '>': 1 };

  // ---- 조건 판정 -----------------------------------------------------------
  function compare(op, a, b) {
    switch (op) {
      case '==': return a === b;
      case '!=': return a !== b;
      case 'in': return Array.isArray(b) ? b.indexOf(a) >= 0 : null;
      case 'not_in': return Array.isArray(b) ? b.indexOf(a) < 0 : null;
      default:
        if (typeof a !== typeof b) return null;
        if (op === '>=') return a >= b;
        if (op === '<=') return a <= b;
        if (op === '<') return a < b;
        return a > b;
    }
  }

  function itemState(it, ctx, qid) {
    if (it && typeof it === 'object' && !Array.isArray(it)) return condState(it, ctx, qid);
    if (!(Array.isArray(it) && it.length === 3 && typeof it[0] === 'string' && typeof it[1] === 'string' && OPS[it[1]])) {
      throw new Error(qid + ' 의 보이는조건 항목 모양을 모른다: ' + JSON.stringify(it));
    }
    var left = it[0];
    if (left.indexOf('엔진.') === 0 || left.indexOf('주택.') === 0) return 'E';
    var val = ctx.get(left);
    if (val === undefined || val === null) return 'U';
    var r = compare(it[1], val, it[2]);
    return r === null ? 'U' : (r ? 'T' : 'F');
  }

  function condState(cond, ctx, qid) {
    if (cond === '항상') return 'T';
    var names = cond && typeof cond === 'object' ? Object.keys(cond) : [];
    if (names.length !== 1 || (names[0] !== '모두' && names[0] !== '하나라도') || !Array.isArray(cond[names[0]])) {
      throw new Error(qid + ' 의 보이는조건 모양을 모른다: ' + JSON.stringify(cond));
    }
    var rs = cond[names[0]].map(function (it) { return itemState(it, ctx, qid); });
    var has = function (x) { return rs.indexOf(x) >= 0; };
    if (names[0] === '모두') return has('F') ? 'F' : has('U') ? 'U' : has('E') ? 'E' : 'T';
    return has('T') ? 'T' : has('U') ? 'U' : has('E') ? 'E' : 'F';
  }

  // 자산이 여럿이면 자산 하나라도 참일 때 묻는다(questions.py 의 _units 와 같은 규칙)
  function anyState(rs) {
    return rs.indexOf('T') >= 0 ? 'T' : rs.indexOf('E') >= 0 ? 'E' : rs.indexOf('U') >= 0 ? 'U' : 'F';
  }

  // ---- 답 읽기 -------------------------------------------------------------
  function holderOf(store, q, assetId) {
    if (q.unit === '자산') {
      for (var i = 0; i < store.assets.length; i++) if (store.assets[i].id === assetId) return store.assets[i];
      return null;
    }
    return store.glob;
  }

  function scalar(v) {
    return v === undefined || v === null || v === '' || typeof v === 'object' ? undefined : v;
  }

  // 모든 문항의 상태. st[문항 id][단위] 단위는 자산 id 이거나 '' 이다.
  // 조건은 뒤에 있는 문항도 가리키므로(A09 가 A13 을 본다) 필요한 문항의 상태를 그때그때 구해 둔다.
  function compute(store) {
    var assets = store.assets;
    var memo = {}, busy = {};
    function rawOf(q, unit) {
      var h = holderOf(store, q, unit);
      if (!h) return undefined;
      if (h.mo && h.mo[q.id]) return undefined;
      return h.ans[q.id];
    }
    function ctxFor(a) {
      return {
        get: function (qid2) {
          var q2 = byId[qid2];
          if (!q2) return undefined;
          var unit2;
          if (q2.unit === '자산') { if (!a) return undefined; unit2 = a.id; }
          else if (q2.unit === '전역') unit2 = '';
          else return undefined;          // 집 단위 문항은 이 화면이 조건에 쓰지 않는다
          var s2 = stateOf(q2, unit2);
          if (s2 !== 'T' && s2 !== 'E') return undefined;
          return scalar(rawOf(q2, unit2));
        }
      };
    }
    function stateOf(q, unit) {
      var key = q.id + '|' + unit;
      if (memo[key] !== undefined) return memo[key];
      if (busy[key]) return 'U';
      busy[key] = true;
      var s;
      if (q.unit === '자산') {
        var a = holderOf(store, q, unit);
        s = a ? condState(conds[q.id], ctxFor(a), q.id) : 'F';
      } else {
        s = anyState((assets.length ? assets : [null]).map(function (x) { return condState(conds[q.id], ctxFor(x), q.id); }));
      }
      busy[key] = false;
      memo[key] = s;
      return s;
    }
    var st = {};
    Q.forEach(function (q) {
      st[q.id] = {};
      if (q.unit === '자산') assets.forEach(function (a) { st[q.id][a.id] = stateOf(q, a.id); });
      else st[q.id][''] = stateOf(q, '');
    });
    return { st: st };
  }

  // ---- 답을 사실관계 값으로 ------------------------------------------------
  var ISO = /^\d{4}-\d{2}-\d{2}$/;
  function validDate(s) {
    if (!ISO.test(s)) return false;
    var y = +s.slice(0, 4), m = +s.slice(5, 7), d = +s.slice(8, 10);
    var t = new Date(Date.UTC(y, m - 1, d));
    return y >= 1900 && t.getUTCFullYear() === y && t.getUTCMonth() === m - 1 && t.getUTCDate() === d;
  }
  function blank(v) { return v === undefined || v === null || (typeof v === 'string' && v.trim() === ''); }

  // spec 하나를 값으로 바꾼다. 비었으면 undefined. 틀린 값은 err(문장) 으로 알린다.
  function toOut(spec, v, err) {
    var t = spec.t;
    if (t === 'houses') return undefined;      // 집 목록은 buildFacts 가 따로 만든다
    if (t === 'bool') return typeof v === 'boolean' ? v : undefined;
    if (t === 'choice' || t === 'sido') return typeof v === 'string' && v ? v : undefined;
    if (t === 'multi') return Array.isArray(v) && v.length ? v.slice() : undefined;
    if (t === 'text') {
      if (blank(v)) return undefined;
      var tx = String(v).trim();
      if (spec.digits) {      // 번호 칸: 하이픈과 공백은 빼 주고 ASCII 숫자 N자리가 아니면 알린다
        tx = tx.replace(/[-\s]/g, '');
        if (!new RegExp('^[0-9]{' + spec.digits + '}$').test(tx)) { err('숫자 ' + spec.digits + '자리로 적어 주세요(하이픈은 빼도 됩니다)'); return undefined; }
      }
      return tx;
    }
    if (t === 'date') {
      if (blank(v)) return undefined;
      v = String(v).trim();
      if (!validDate(v)) { err('날짜는 달력에 있는 날로 적어 주세요(예: 2026-11-20)'); return undefined; }
      return v;
    }
    if (t === 'int') {
      if (blank(v)) return undefined;
      var s = String(v).replace(/[,\s원]/g, '');
      if (!/^\d+$/.test(s) || +s > 9007199254740991) { err('금액은 원 단위 숫자로 적어 주세요(0 이상, 소수점 없음)'); return undefined; }
      return +s;
    }
    if (t === 'num') {
      if (blank(v)) return undefined;
      var n = String(v).replace(/[,\s]/g, '');
      if (!/^\d+(\.\d+)?$/.test(n)) { err('숫자로 적어 주세요(0 이상)'); return undefined; }
      n = parseFloat(n);
      if (spec.positive && !(n > 0)) { err('0보다 큰 숫자로 적어 주세요'); return undefined; }
      return n;
    }
    if (t === 'addr') {
      v = v || {};
      var a = {};
      ['시도', '시군구', '읍면동'].forEach(function (k) { if (!blank(v[k])) a[k] = String(v[k]).trim(); });
      if (!Object.keys(a).length) return undefined;
      if (!a['시도'] || !a['시군구']) { err('시·도와 시·군·구는 꼭 적어 주세요'); return undefined; }
      return a;
    }
    if (t === 'share') {
      if (!v || !v.kind) return undefined;
      if (v.kind === '단독') return '단독';
      var p = String(v.n === undefined ? '' : v.n).trim(), q = String(v.d === undefined ? '' : v.d).trim();
      if (!/^\d+$/.test(p) || !/^\d+$/.test(q) || +p <= 0 || +p > +q) {
        err('공동 소유는 지분을 분자와 분모로 적어 주세요(예: 1과 2). 분자는 0보다 크고 분모를 넘을 수 없습니다.');
        return undefined;
      }
      return { '구분': '공동', '분자': +p, '분모': +q };
    }
    if (t === 'obj') {
      var out = {}, any = false;
      v = v || {};
      spec.fields.forEach(function (f) {
        var x = toOut(f.s, v[f.n], function (m) { err(f.label + ': ' + m); });
        if (x !== undefined) { out[f.n] = x; any = true; }
      });
      if (!any) return undefined;
      var miss = (spec.req || []).filter(function (n) { return out[n] === undefined; });
      if (miss.length) {
        var lab = spec.fields.filter(function (f) { return miss.indexOf(f.n) >= 0; }).map(function (f) { return f.label; });
        err('빠진 값이 있습니다: ' + lab.join(', '));
        return undefined;
      }
      return out;
    }
    if (t === 'list') {
      v = v || {};
      if (v.none) return [];
      var rows = (v.rows || []).map(function (r, i) {
        if (spec.as === 'scalars') return toOut(spec.row, r, function (m) { err((i + 1) + '번째: ' + m); });
        if (spec.as === 'pairs') {
          var la = spec.row.fields[0].label, lb = spec.row.fields[1].label;
          var a1 = toOut({ t: 'date' }, r && r.a, function (m) { err((i + 1) + '번째 ' + la + ': ' + m); });
          var b1 = toOut({ t: 'date' }, r && r.b, function (m) { err((i + 1) + '번째 ' + lb + ': ' + m); });
          if (a1 === undefined && b1 === undefined) return undefined;
          if (a1 === undefined || b1 === undefined) { err((i + 1) + '번째: ' + la + '과 ' + lb + '을 모두 적어 주세요'); return undefined; }
          if (b1 < a1) { err((i + 1) + '번째: ' + lb + '이 ' + la + '보다 빠릅니다'); return undefined; }
          return [a1, b1];
        }
        return toOut(spec.row, r, function (m) { err((i + 1) + '번째: ' + m); });
      }).filter(function (x) { return x !== undefined; });
      return rows.length ? rows : undefined;
    }
    throw new Error('알 수 없는 spec: ' + t);
  }

  function isAnswered(q, holder) {
    if (holder.mo && holder.mo[q.id]) return true;
    return toOut(q.spec, holder.ans[q.id], function () {}) !== undefined;
  }

  // ---- 사실관계 JSON ------------------------------------------------------
  function writeKey(root, asset, house, key, value) {
    var parts = key.split('.'), node, rest;
    if (parts[0] === '자산[]') { node = asset; rest = parts.slice(1); }
    else if (parts[0] === '세대' && (parts[1] === '주택목록[]' || parts[1] === '주택목록[신규]')) { node = house; rest = parts.slice(2); }
    else { node = root; rest = parts; }
    for (var i = 0; i < rest.length - 1; i++) {
      if (typeof node[rest[i]] !== 'object' || node[rest[i]] === null) node[rest[i]] = {};
      node = node[rest[i]];
    }
    node[rest[rest.length - 1]] = value;
  }

  function putQuestion(q, holder, unit, root, asset, errors, moList) {
    if (holder.mo && holder.mo[q.id]) { moList.push(q.id + ':' + unit); return; }
    var raw = holder.ans[q.id];
    var val = toOut(q.spec, raw, function (m) { errors.push({ qid: q.id, unit: unit, msg: m }); });
    if (val === undefined) return;
    if (q.keys.length === 1) { writeKey(root, asset, null, q.keys[0], val); return; }
    q.keys.forEach(function (k) {
      var name = k.slice(k.lastIndexOf('.') + 1);
      if (val[name] !== undefined) writeKey(root, asset, null, k, val[name]);
    });
  }

  // 판 집의 취득일: 자산 답에서 가장 앞선 날짜 하나를 찾는다(자산id 로 이어진 집은 엔진이 자산의 취득 시기를 쓴다)
  function firstOf(o, names) {
    for (var i = 0; i < names.length; i++) if (o && o[names[i]]) return o[names[i]];
    return undefined;
  }

  function houseOut(store, h, assetOut, errors) {
    var spec = defs.houseRow;
    var f = h.f || {};
    var o = { id: h.id };
    var err = function (m) { errors.push({ qid: 'H04', unit: '', msg: h.id + ' ' + m }); };
    var simple = function (name) {
      var fld = spec.main.filter(function (x) { return x.n === name; })[0];
      return fld ? toOut(fld.s, f[name], function (m) { err(fld.label + ': ' + m); }) : undefined;
    };
    if (h.asset) {
      o['자산id'] = h.asset;
      if (assetOut) {
        if (assetOut['소재지']) o['소재지'] = assetOut['소재지'];
        if (assetOut['주택유형']) o['유형'] = assetOut['주택유형'];
        var 취득 = assetOut['취득'] || {};
        var d = firstOf(취득, ['잔금일', '등기접수일', '사용승인일', '사실상사용일', '대금완납일']);
        if (d) o['취득일'] = d;
        if (취득['원인']) o['취득원인'] = 취득['원인'];
        if (assetOut['지분'] !== undefined) o['지분'] = assetOut['지분'];
      }
      ['소유자', '등록임대'].forEach(function (n) {
        var x = simple(n);
        if (x !== undefined) o[n] = x;
      });
    } else {
      ['소유자', '소재지', '유형', '취득일', '취득원인', '지분', '등록임대'].forEach(function (n) {
        var x = simple(n);
        if (x !== undefined) o[n] = x;
      });
      if (!o['소재지']) err('집의 주소(시·도, 시·군·구)를 적어 주세요');
      if (!o['취득일']) err('집을 산 날을 적어 주세요');
    }
    spec.extra.forEach(function (fld) {
      var x = toOut(fld.s, f[fld.n], function (m) { err(fld.label + ': ' + m); });
      if (x !== undefined) o[fld.n] = x;
    });
    return o;
  }

  function buildFacts(store, c) {
    c = c || compute(store);
    var st = c.st;
    var errors = [], mo = [];
    var f = {};
    Q.forEach(function (q) {
      if (q.unit !== '전역' || q.spec.t === 'houses') return;
      var s = st[q.id][''];
      if (s !== 'T' && s !== 'E') return;
      putQuestion(q, store.glob, '', f, null, errors, mo);
    });
    var outAssets = store.assets.map(function (a) {
      var o = { id: a.id };
      Q.forEach(function (q) {
        if (q.unit !== '자산') return;
        var s = st[q.id][a.id];
        if (s !== 'T' && s !== 'E') return;
        putQuestion(q, a, a.id, f, o, errors, mo);
      });
      return o;
    });
    var h04 = byId[defs.houseQuestion];
    if (h04 && (st[h04.id][''] === 'T' || st[h04.id][''] === 'E')) {
      var byAsset = {};
      outAssets.forEach(function (o) { byAsset[o.id] = o; });
      var rows = store.houses.map(function (h) { return houseOut(store, h, h.asset ? byAsset[h.asset] : null, errors); });
      if (rows.length) {
        if (typeof f['세대'] !== 'object' || f['세대'] === null) f['세대'] = {};
        f['세대']['주택목록'] = rows;
      }
    }
    f['자산'] = outAssets;
    if (mo.length) f['모름'] = mo;
    return { facts: f, errors: errors };
  }

  return { Q: Q, byId: byId, condState: condState, compute: compute, toOut: toOut, isAnswered: isAnswered,
           buildFacts: buildFacts, validDate: validDate, houseOut: houseOut };
}
