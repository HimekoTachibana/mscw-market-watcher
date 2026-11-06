"""Browser source tests against a local mock that mimics the layout seen on the real site:
left item list with a filter box, right panel with 'Where to buy' -> Newest/Cheapest rows."""
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from mesowatcher import browser, core, errorlog

MOCK = """<!doctype html><html><head><meta charset="utf-8"><title>Mock FM prices</title>
<style>.b{border:1px solid #999;padding:0 4px;margin-right:4px}.row,.l{display:flex;gap:12px;padding:6px}
#panel{border-left:1px solid #ccc;padding:8px;margin-left:420px}#list{position:absolute;width:400px}</style></head>
<body><input id="f" placeholder="Filter items..." style="width:300px">
<div id="list"></div><div id="panel"><i>pick an item</i></div>
<script>
const ITEMS=[
 {n:"Selective 5-slot Coupon",c:"Cash Shop",t:"55K",ch:"+6%",v:"321.2M",s:"4,100 sales"},
 {n:"Earring LUK Scroll",c:"Scrolls",t:"109K",ch:"+21%",v:"578.8M",s:"7,102 sales"},
 {n:"Pan Lid",c:"Equips",t:"77.8K",ch:"+11%",v:"466.1M",s:"6,242 sales"}];
window.LISTINGS={
 "Selective 5-slot Coupon":[
  {s:"Baitfish",ch:14,fm:5,ago:"3m ago",p:"175K",n:175000},
  {s:"LancePapa",loc:"Kerning City Constructi\\u2026",full:"Kerning City Construction Site",ago:"4m ago",p:"120K",n:120000},
  {s:"Lids",ch:40,fm:10,ago:"17m ago",p:"140K",n:140000}],
 "Earring LUK Scroll":[
  {s:"Soldoros",ch:32,fm:3,ago:"3m ago",p:"144K",n:144000},
  {s:"Mintea",ch:7,fm:1,ago:"1h ago",p:"1.2M",n:1200000}]};
let cur=null, sort="new";
function renderList(q){
  document.getElementById('list').innerHTML=ITEMS.filter(i=>i.n.toLowerCase().includes(q.toLowerCase())).map(i=>
   `<div class="row" data-n="${i.n}"><button>\\u2605</button><div><b>${i.n}</b><br><small>${i.c}</small></div>
    <span>${i.t}</span><span>${i.ch}</span><div>${i.v}<br><small>${i.s}</small></div></div>`).join('');
  document.querySelectorAll('#list .row').forEach(r=>r.onclick=()=>pick(r.dataset.n));
}
function pick(n){
  cur=n; const title=n;
  document.getElementById('panel').innerHTML=`<h2>${title}</h2><div><span>Item Info</span> <span>For sale now 102</span></div>
   <button id="wtb">Where to buy 102</button><div id="lst" hidden></div>`;
  document.getElementById('wtb').onclick=()=>{document.getElementById('lst').hidden=false;renderL();};
}
function renderL(){
  let rows=(LISTINGS[cur]||[]).slice(); if(sort==="cheap") rows.sort((a,b)=>a.n-b.n);
  document.getElementById('lst').innerHTML=`<div><button id="nw">Newest</button><button id="ch">Cheapest</button></div>
   <div class="row"><b>Your shop here</b><span>CH ? FM ?</span><button>List my shop</button></div>`+rows.map(r=>
   `<div class="l"><span>\\u25cf</span><div><b>${r.s}</b><div>${r.loc?`<i class="b" title="${r.full}">${r.loc}</i>`:
   `<i class="b">CH ${r.ch}</i><i class="b">FM${r.fm}</i>`}<em>\\u00b7 ${r.ago}</em></div></div>
   <div><span>${r.p}</span><br><small>each</small></div><button>shop</button></div>`).join('');
  document.getElementById('nw').onclick=()=>{sort="new";renderL();};
  document.getElementById('ch').onclick=()=>{sort="cheap";renderL();};
}
document.getElementById('f').oninput=e=>renderList(e.target.value);
renderList('');
</script></body></html>"""

CHALLENGE = "<!doctype html><title>Just a moment...</title><p>Checking your browser</p>"



# Mirrors the structure of the real page (from a saved snapshot): #search with a single "…" placeholder,
# a ticker that also contains item names, an item table with button.item-select, and li.buy-row
# listings whose price shows "45K" while the tooltip holds the exact "44,999 mesos".
MOCK_REAL = """<!doctype html><html><head><meta charset="utf-8"><title>MesoWatch mock</title></head>
<body class="whats-new">
<aside class="megaphone"><div id="ticker" class="mega-inner"><span>Leaden : Sold <b>Garnet Ore</b> for <b>399</b> mesos!</span></div></aside>
<input id="search" type="search" aria-label="Filter items" placeholder="Filter items\\u2026" autocomplete="off">
<table><tbody id="rows"></tbody></table>
<section id="detail"></section>
<script>
const ITEMS=[
 {n:"Piece of Ice",c:"Etc",p:21799,t:"21.8K",d:"+9%",v:"2,829 sales"},
 {n:"Garnet Ore",c:"Etc",p:420,t:"420",d:"+3%",v:"9,101 sales"},
 {n:"Selective 5-slot Coupon",c:"Cash Shop",p:55000,t:"55K",d:"+6%",v:"4,100 sales"},
 {n:"Lazy Item",c:"Etc",p:5000,t:"5K",d:"+1%",v:"100 sales"},
 {n:"Shoes Speed Scroll: Intermediate",c:"Scroll",p:90000,t:"90K",d:"+1%",v:"10 sales"},
 {n:"Shoes Speed Scroll: Chaos",c:"Scroll",p:30000,t:"30K",d:"+1%",v:"10 sales"}];
const fmt=ms=>new Date(ms).toLocaleString('en-US',{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'});
const SHOPS={
 "Piece of Ice":[{s:"Iceman",ch:3,fm:2,ago:"2m ago",p:21000,t:"21K"}],
 "Garnet Ore":[
  {s:"Cornhub",map:"Perion Street Corner",ago:"11m ago",p:44999,t:"45K"},
  {s:"BugHum",ch:6,fm:7,ago:"12m ago",p:40000,t:"40K"},
  {s:"Old Timer",ch:1,fm:1,ago:"2h ago",p:1250000,t:"1.25M"}],
 "Shoes Speed Scroll: Intermediate":[{s:"WrongShop",ch:2,fm:2,ago:"1m ago",p:90000,t:"90K"}],
 "Shoes Speed Scroll: Chaos":[{s:"RightShop",ch:9,fm:9,ago:"2m ago",p:30000,t:"30K"}],
 "Selective 5-slot Coupon":[{s:"Baitfish",ch:14,fm:5,ago:"3m ago",p:175000,t:"175K"}]};
SHOPS["Lazy Item"]=Array.from({length:40},(_,i)=>{const m=5+i*10;
  return {s:"Shop"+i,ch:1+i%9,fm:1+i%5,p:5000+i,t:"5K",min:m,seen:fmt(Date.now()-m*60000),
          ago:m<60?m+"m ago":Math.floor(m/60)+"h ago"};});
let cur="Piece of Ice", sort="new";
const SVG='<svg viewBox="0 0 24 24" width="20" height="20"><path d="M3 9h18v11H3z"></path></svg>';
function renderTable(q){
  document.getElementById('rows').innerHTML=ITEMS.filter(i=>i.n.toLowerCase().includes(q.toLowerCase())).map(i=>
   `<tr data-id="x:${i.n}" class="${i.n===cur?'selected':''}"><td class="item-col"><div class="item-cell">
    <div class="item-text"><button class="item-name item-select" title="${i.n}">${i.n}</button><div class="item-cat">${i.c}</div></div></div></td>
    <td data-col="price" class="num"><span class="meso" title="${i.p.toLocaleString('en-US')} mesos"><i class="coin"></i>${i.t}</span></td>
    <td data-col="day"><span class="spark-pct">${i.d}</span></td><td data-col="vol">${i.v}</td></tr>`).join('');
  document.querySelectorAll('button.item-select').forEach(b=>b.onclick=()=>{cur=b.title;sort="new";renderTable(document.getElementById('search').value);renderDetail();});
}
function renderDetail(){
  let rows=(SHOPS[cur]||[]).slice(); if(sort==="cheap") rows.sort((a,b)=>a.p-b.p);
  const li=r=>`<li class="buy-row up can-open sv-row" title="${r.s} | seen ${r.seen||'Nov 2, 11:41 PM'}"> <i class="buy-dot"></i>
   <div class="buy-main"><div class="buy-seller">${r.s}</div><div class="buy-meta">${r.map?
   `<span class="buy-where tag-map" title="${r.map}">${r.map}</span>`:
   `<span class="ch-chip tag-ch" title="Channel ${r.ch}">CH ${r.ch}</span><span class="buy-where tag-map" title="Free Market ${r.fm}">FM${r.fm}</span>`}<span class="buy-when fresh">&nbsp;\\u00b7 ${r.ago}</span></div>
   <span class="visually-hidden">Likely still up</span></div>
   <div class="buy-price"><span class="meso" title="${r.p.toLocaleString('en-US')} mesos"><i class="coin"></i>${r.t}</span><small>each</small></div>
   <button type="button" class="sv-btn">${SVG}</button></li>`;
  document.getElementById('detail').innerHTML=`<h2>${cur}</h2><div id="detail-list"><div class="list-head list-tabs">
   <button class="list-tab active" data-detail-view="buying">Where to buy<span class="dv-count">101</span></button>
   <button class="list-tab" data-detail-view="prices">Recent sales</button></div>
   <div class="fsn-bar"><span class="fsn-seg"><button class="${sort==='new'?'on':''}" data-fsn-sort="new">Newest</button>
   <button class="${sort==='cheap'?'on':''}" data-fsn-sort="cheap">Cheapest</button></span></div>
   <ul class="buy-list scroll wtb-br" style="max-height:220px;overflow:auto"><li class="buy-row list-shop-row"><div class="buy-main"><div class="buy-seller">Your shop here</div>
   <div class="buy-meta"><span class="list-shop-tag">CH ?</span><span class="list-shop-tag">FM ?</span></div></div>
   <button class="list-shop-btn">List my shop</button></li>${rows.slice(0,12).map(li).join('')}</ul></div>`;
  const ul=document.querySelector('ul.buy-list'); let shown=12;
  ul.onscroll=()=>{ if(shown<rows.length && ul.scrollTop+ul.clientHeight>=ul.scrollHeight-30){
    ul.insertAdjacentHTML('beforeend', rows.slice(shown,shown+12).map(li).join('')); shown+=12; } };
  document.querySelector('[data-fsn-sort=new]').onclick=()=>{sort="new";renderDetail();};
  document.querySelector('[data-fsn-sort=cheap]').onclick=()=>{sort="cheap";renderDetail();};
}
document.getElementById('search').oninput=e=>renderTable(e.target.value);
renderTable(''); renderDetail();
</script></body></html>"""


# The real page's right-hand panel is what proves the right item is open. Here the list texts differ from the
# real names (the case that stopped scrolls being found), the first result is the WRONG scroll, and the panel
# has an icon whose file name holds the item id.
MOCK_SCROLLS = """<!doctype html><html><head><meta charset="utf-8"><title>Scrolls mock</title></head><body>
<input id="search" type="search" placeholder="Filter items\\u2026"><table><tbody id="rows"></tbody></table><section id="detail"></section>
<script>
const BAD = location.search.includes('bad');
const MODE = (location.search.match(/mode=(\\w+)/)||[])[1] || 'plain';
const ITEMS=[
 {label:"Shoes Speed Scroll: Intermediate (60%)", panel:"Shoes Speed Scroll: Intermediate", icon:"02040001", shop:"WrongShop"},
 {label:"Shoes Speed Scroll: Chaos (60%)", panel:"Shoes Speed Scroll: Chaos", icon:"02040000", shop:"RightShop"}];
if (MODE==='sameName') { ITEMS[0].panel="Shoes Speed Scroll: Chaos"; }   // right name, wrong icon (an Intermediate scroll)
let cur=-1;
function renderTable(q){
  document.getElementById('rows').innerHTML=ITEMS.map((it,i)=>
   `<tr><td><button class="item-name item-select" data-i="${i}">${it.label}</button></td>
    <td data-col="price"><span class="meso" title="30,000 mesos">30K</span></td></tr>`).join('');
  document.querySelectorAll('button.item-select').forEach(b=>b.onclick=()=>{cur=+b.dataset.i;renderDetail();});
}
function renderDetail(){
  const it=ITEMS[cur]; const name=BAD?"Something Else Entirely":it.panel;
  document.getElementById('detail').innerHTML=`<div class="head"><img src="/icons/${it.icon}.png?v=20261104" alt=""><h2>${name}</h2></div>
   <button class="list-tab">Where to buy</button><button>Newest</button>
   <ul class="buy-list scroll"><li class="buy-row"><div class="buy-main"><div class="buy-seller">${it.shop}</div>
   <div class="buy-meta"><span>CH 9</span><span>FM9</span><span class="buy-when">&nbsp;\\u00b7 2m ago</span></div></div>
   <div class="buy-price"><span class="meso" title="30,000 mesos">30K</span><small>each</small></div></li></ul>`;
}
document.getElementById('search').oninput=e=>renderTable(e.target.value);
renderTable('');
</script></body></html>"""

# Lists that load more rows in less friendly ways than "instantly on scroll":
_LOADER = """ul.onscroll=()=>{ if(shown<rows.length && ul.scrollTop+ul.clientHeight>=ul.scrollHeight-30){
    ul.insertAdjacentHTML('beforeend', rows.slice(shown,shown+12).map(li).join('')); shown+=12; } };"""
assert _LOADER in MOCK_REAL
MOCK_SLOW = MOCK_REAL.replace(_LOADER, """let busy=false; ul.onscroll=()=>{ if(!busy && shown<rows.length && ul.scrollTop+ul.clientHeight>=ul.scrollHeight-30){
    busy=true; setTimeout(()=>{ ul.insertAdjacentHTML('beforeend', rows.slice(shown,shown+12).map(li).join('')); shown+=12; busy=false; }, 1600); } };""")
MOCK_WHEEL = MOCK_REAL.replace(_LOADER, _LOADER.replace("ul.onscroll=", "ul.onwheel="))  # only a mouse wheel loads more
MOCK_BUTTON = MOCK_REAL.replace(_LOADER, """const more=document.createElement('button'); more.textContent='Load more'; more.className='more';
  ul.after(more); more.onclick=()=>{ ul.insertAdjacentHTML('beforeend', rows.slice(shown,shown+12).map(li).join('')); shown+=12; };""")

# The layout of the real page as saved in a snapshot: results show a SHORTENED name (the full one is in the title),
# every result has an icon; the right-hand panel opens on "Item Info" and the "For sale now" tab (data-tab="now")
# lists every shop in a scrolling box, with all rows already in the page and a "N of N shops shown" footer.
MOCK_FSN = """<!doctype html><html><head><meta charset="utf-8"><title>MesoWatch fsn mock</title></head><body>
<input id="search" type="search" placeholder="Filter items\\u2026">
<table><tbody id="rows"></tbody></table>
<section id="detail"><div class="tabs"><button data-mu="fsn-tab" data-tab="info" class="on" aria-selected="true">Item Info</button>
<button data-mu="fsn-tab" data-tab="now" aria-selected="false">For sale now<b class="fsn-count">60</b></button></div><div id="body"></div></section>
<script>
const Q = new URLSearchParams(location.search);
const DECOYS = +(Q.get('decoys')||0), MODE = Q.get('mode')||'', LAZY = MODE==='lazy', TOTAL = 60;
const WANT = "Shoes Speed Scroll: Chaos";
const ITEMS = [];
for (let k=0;k<DECOYS;k++) ITEMS.push({title:"Shoes Speed Scroll: Decoy "+k, icon:"0204"+String(100+k).padStart(4,'0'), panelIcon:null});
if (MODE==='iconmismatch') ITEMS.push({title:WANT, icon:"02040001", panelIcon:"02040009"});  // right name, different icon
ITEMS.push({title:WANT, icon:"02040000", panelIcon:null});
let cur=null, tab='info', shown=0;
const EXTRA = [];
window.__add = () => { EXTRA.push({s:"NewShop"+EXTRA.length, ch:3, fm:2, p:99000+EXTRA.length, min:0}); draw(); };  // the site's own auto-update
const rowsFor = () => Array.from({length:TOTAL},(_,i)=>({s:"Fsn"+i, ch:1+i%9, fm:1+i%5, p:150000+i, min:(i+1)*2})).concat(EXTRA);
function table(){
  document.getElementById('rows').innerHTML = ITEMS.map((it,i)=>
   `<tr><td><div class="item-cell"><div class="item-icon"><img src="data/icons/${it.icon}.png" alt=""></div>
    <div class="item-text"><button class="item-name item-select" data-i="${i}" title="${it.title}">Shoes Speed Scroll</button></div></div></td>
    <td data-col="price"><span class="meso" title="140,000 mesos">140K</span></td></tr>`).join('');
  document.querySelectorAll('button.item-select').forEach(b=>b.onclick=()=>{window.__clicks=(window.__clicks||0)+1;cur=ITEMS[+b.dataset.i];tab='info';draw();});
}
const li = r => `<li class="buy-row fsn-row up can-open"><div class="buy-main"><div class="buy-seller">${r.s}</div>
  <div class="buy-meta"><span class="buy-where tag-map" title="Free Market ${r.fm}">FM${r.fm}</span><span class="ch-chip tag-ch">CH ${r.ch}</span>
  <span class="buy-when">&nbsp;\\u00b7 ${r.min<60?r.min+'m':Math.floor(r.min/60)+'h'} ago</span></div></div>
  <div class="fsn-right"><div class="buy-price"><span class="meso" title="${r.p.toLocaleString('en-US')} mesos">${Math.round(r.p/1000)}K</span></div></div></li>`;
function draw(){
  document.querySelectorAll('[data-mu=fsn-tab]').forEach(b=>{const on=b.dataset.tab===tab;b.className=on?'on':'';b.setAttribute('aria-selected',on);
    b.onclick=()=>{tab=b.dataset.tab;draw();};});
  const body=document.getElementById('body');
  if(!cur){body.innerHTML='';return;}
  const head=`<div class="detail-head"><div class="item-icon"><img src="data/icons/${cur.panelIcon||cur.icon}.png" alt=""></div>
    <div><h2>${cur.title}</h2><p class="detail-sub">91 listings</p></div></div>`;
  if(tab==='info'){
    body.innerHTML=head+`<ul class="buy-list"><li class="buy-row"><div class="buy-main"><div class="buy-seller">InfoTabShop</div>
      <div class="buy-meta"><span>CH 1</span><span>FM1</span><span>&nbsp;\\u00b7 5m ago</span></div></div><div class="buy-price"><span class="meso" title="1 mesos">1</span><small>each</small></div></li></ul>`;
    return;
  }
  const all=rowsFor(); shown=LAZY?12:all.length;
  body.innerHTML=head+`<div class="fsn-view"><span class="fsn-seg"><button class="on" data-fsn-sort="new">Newest</button><button data-fsn-sort="cheap">Cheapest</button></span>
    <ul class="buy-list fsn-list" style="height:240px;overflow-y:auto"><li class="buy-row list-shop-row"><div class="buy-seller">Your shop here</div><div class="buy-meta">CH ? FM ?</div></li>${all.slice(0,shown).map(li).join('')}</ul>
    <div class="fsn-foot"><span id="cnt">${shown} of ${LAZY?TOTAL:shown} shops shown</span></div></div>`;
  if(LAZY){const ul=document.querySelector('ul.fsn-list');
    ul.onwheel=()=>{ if(shown<all.length){ ul.insertAdjacentHTML('beforeend',all.slice(shown,shown+12).map(li).join('')); shown=Math.min(shown+12,all.length);
      document.getElementById('cnt').textContent=shown+' of '+TOTAL+' shops shown'; } };}
}
document.getElementById('search').oninput=e=>{
  if (Q.get('slow')) { document.getElementById('rows').innerHTML=''; setTimeout(table,1500); } else table(); };
table();
</script></body></html>"""

PAGES = {"/fsn": MOCK_FSN, "/real-slow": MOCK_SLOW, "/real-wheel": MOCK_WHEEL, "/real-button": MOCK_BUTTON, "/scrolls": MOCK_SCROLLS}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/api/limited"):  # what a rate-limited background request looks like
            body = b'{"error":"rate limited"}'
            self.send_response(429)
            self.send_header("Retry-After", "42")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/pass403"):  # like Cloudflare: the check page is answered with 403, then the site loads
            body = (b"<!doctype html><title>Just a moment...</title><p>Checking</p>"
                    b"<script>setTimeout(()=>{location.href='/fsn'},1500)</script>")
            self.send_response(403)
            self.send_header("cf-mitigated", "challenge")
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        page = next((p for k, p in PAGES.items() if self.path.startswith(k)), None) or (
            CHALLENGE if self.path.startswith("/challenge") else MOCK_REAL if self.path.startswith("/real") else MOCK)
        body = page.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def site():
    s = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_port}"
    s.shutdown()


@pytest.fixture()
def src(tmp_path, site):
    pytest.importorskip("playwright")
    cfg = core.Config(tmp_path / "c.json")
    cfg["delay_min_ms"] = cfg["delay_max_ms"] = 500  # keep tests fast (production: random 500-5000)
    cfg["browser"].update(start_url=site + "/", channel="chromium", headless=True,
                          page_timeout_ms=20000, challenge_wait_s=2, scan_mode="single")
    s = browser.BrowserSource(cfg, profile_dir=tmp_path / "profile")
    try:
        s._open()
    except RuntimeError as e:
        pytest.skip(f"no usable browser here: {e}")
    yield s
    s.close()


# ------------------------------------------------------------------ pure parsing
def test_parse_row_with_channel_and_fm():
    p = browser.parse_listing_text("Baitfish\nCH 14\nFM5\n· 3m ago\n175K\neach")
    assert p == {"seller": "Baitfish", "channel": "14", "location": "FM 5", "price": 175000,
                 "listed": "3m ago", "age_min": 3.0}


def test_parse_row_with_map_name_and_title_fix():
    p = browser.parse_listing_text("LancePapa\nKerning City Constructi…\n· 4m ago\n120K\neach",
                                   titles=["Kerning City Construction Site"])
    assert p["seller"] == "LancePapa" and p["channel"] == ""
    assert p["location"] == "Kerning City Construction Site" and p["price"] == 120000


def test_parse_units_and_junk():
    assert browser.parse_listing_text("A\nCH 1\n2h ago\n1.2M\neach")["age_min"] == 120.0
    assert browser.parse_listing_text("A\nCH 1\njust now\n900\neach")["age_min"] == 0.0
    assert browser.parse_listing_text("Your shop here\nList my shop") is None


def test_parse_typical():
    row = "Earring LUK Scroll\nScrolls\n109K\n+21%\n578.8M\n7,102 sales"
    assert browser.parse_typical(row, "Earring LUK Scroll") == 109000
    assert browser.parse_typical("Pan Lid\nEquips\n77.8K\n+11%", "Pan Lid") == 77800


# ----------------------------------------------------------- real browser, mock site
def test_click_through_reads_newest_listings(src):
    src.cfg["watchlist"] = [{"name": "Selective 5-slot Coupon", "max_price": 150000}]
    ls = src.fetch()
    assert [(l.seller, l.channel, l.location, l.price, l.listed) for l in ls] == [
        ("Baitfish", "14", "FM 5", 175000, "3m ago"),
        ("LancePapa", "", "Kerning City Construction Site", 120000, "4m ago"),
        ("Lids", "40", "FM 10", 140000, "17m ago")]
    assert all(l.avg24h == 55000 for l in ls)  # TYPICAL from the item row
    assert round(ls[1].discount, 1) == -118.2  # priced above typical
    w = core.Watchlist(src.cfg)
    assert [l.seller for l in ls if w.matches(l)] == ["LancePapa", "Lids"]


def test_no_fuzzy_fallback_and_multiple_items(src):
    src.cfg["watchlist"] = [{"name": "Earring LUK Scroll", "max_price": None},
                            {"name": "Selective 5-slot Coupon", "max_price": None},
                            {"name": "Item That Does Not Exist", "max_price": None}]
    ls = src.fetch()
    by = {}
    for l in ls:
        by.setdefault(l.item_name, []).append(l.seller)
    assert by["Earring LUK Scroll"] == ["Soldoros", "Mintea"]
    assert by["Selective 5-slot Coupon"] == ["Baitfish", "LancePapa", "Lids"]
    assert "Item That Does Not Exist: no item with exactly this name" in src.note


def test_second_pass_sees_new_listing(src):
    src.cfg["watchlist"] = [{"name": "Selective 5-slot Coupon", "max_price": None}]
    first = src.fetch()
    src._page.evaluate("""() => LISTINGS["Selective 5-slot Coupon"].unshift(
        {s:"NewSeller",ch:2,fm:2,ago:"just now",p:"99K",n:99000})""")
    second = src.fetch()
    w = core.Watchlist(src.cfg)
    w.new_matches(first)
    fresh = w.new_matches(second)
    assert [l.seller for l in fresh] == ["NewSeller"] and fresh[0].age_min == 0.0


def test_empty_watchlist_does_not_open_site(tmp_path):
    cfg = core.Config(tmp_path / "c.json")
    cfg["watchlist"] = []
    s = browser.BrowserSource(cfg, profile_dir=tmp_path / "p")
    assert s.fetch() == [] and "empty" in s.note and s._page is None


def test_max_age_hides_stale_listings(src):
    src.cfg["watchlist"] = [{"name": "Selective 5-slot Coupon", "max_price": None}]
    src.cfg["max_age_min"] = 10
    ls = src.fetch()
    w = core.Watchlist(src.cfg)
    assert [l.seller for l in ls if w.matches(l)] == ["Baitfish", "LancePapa"]  # Lids is 17m old


def test_challenge_stops_headless(src, site):
    src.cfg["browser"]["start_url"] = site + "/challenge"
    src.cfg["watchlist"] = [{"name": "Pan Lid", "max_price": None}]
    with pytest.raises(core.ChallengeDetected) as e:
        src.fetch()
    assert "Cloudflare check" in str(e.value)  # no screen here, so it cannot open a window to complete it
    log = errorlog.log_path().read_text(encoding="utf-8")  # ... but the error log has what happened before
    assert "Stopped by a Cloudflare check" in log and "A Cloudflare check is showing" in log
    assert f"Loading {site}/challenge" in log and "WHAT HAPPENED BEFORE" in log


def test_diagnose_reports_steps_and_saves_snapshot(src, tmp_path):
    snap = tmp_path / "snap.html"
    log = src.diagnose("Selective 5-slot Coupon", snapshot=snap)
    text = "\n".join(log)
    assert "Filter box found" in text and "Read 3 listing" in text and "Typical price: 55,000" in text
    assert "Baitfish | CH 14 | FM 5 | 175,000 | 3m ago" in text
    assert snap.exists() and "Baitfish" in snap.read_text(encoding="utf-8")


def test_diagnose_names_the_failing_step(src):
    log = src.diagnose("No Such Item")
    assert any(l.startswith("FAIL") and "No Such Item" in l for l in log)
    src.cfg["browser"]["filter_placeholder"] = "Search nothing"
    log = src.diagnose("Pan Lid")
    assert any("Filter box 'Search nothing' not found" in l for l in log)


def test_parse_adjacent_badges_and_status_dot():
    p = browser.parse_listing_text("●\nBaitfish\nCH 14FM5· 3m ago175K\neach")
    assert (p["seller"], p["channel"], p["location"], p["price"], p["listed"]) == \
        ("Baitfish", "14", "FM 5", 175000, "3m ago")


# ------------------------------------------- real page layout (selectors + exact prices)
@pytest.fixture()
def real(src, site):
    src.cfg["browser"].update(start_url=site + "/real", filter_placeholder="Filter items...")  # old saved value
    return src


def test_real_layout_reads_exact_prices_and_all_row_kinds(real):
    real.cfg["watchlist"] = [{"name": "Garnet Ore", "max_price": None}]
    ls = real.fetch()
    got = [(l.seller, l.channel, l.location, l.price, l.listed) for l in ls]
    assert got == [("Cornhub", "", "Perion Street Corner", 44999, "11m ago"),   # exact, not 45,000
                   ("BugHum", "6", "FM 7", 40000, "12m ago"),
                   ("Old Timer", "1", "FM 1", 1250000, "2h ago")]
    assert all(l.avg24h == 420 for l in ls)
    assert [l.age_min for l in ls] == [11.0, 12.0, 120.0]


def test_real_layout_ticker_is_never_clicked(real):
    # "Garnet Ore" also appears in the megaphone ticker, which comes first in the page
    real.cfg["watchlist"] = [{"name": "Garnet Ore", "max_price": None}, {"name": "Piece of Ice", "max_price": None}]
    ls = real.fetch()
    by = {}
    for l in ls:
        by.setdefault(l.item_name, []).append(l.seller)
    assert by == {"Garnet Ore": ["Cornhub", "BugHum", "Old Timer"], "Piece of Ice": ["Iceman"]}


def test_real_layout_exact_typical_price_from_tooltip(real):
    real.cfg["watchlist"] = [{"name": "Piece of Ice", "max_price": None}]
    assert real.fetch()[0].avg24h == 21799  # tooltip "21,799 mesos", not the rounded "21.8K"


def test_real_layout_works_with_ellipsis_placeholder_and_blank_selectors(real):
    real.cfg["browser"].update(filter_placeholder="Filter items\u2026", item_selector="", row_selector="")
    real.cfg["watchlist"] = [{"name": "Selective 5-slot Coupon", "max_price": None}]
    ls = real.fetch()
    assert [(l.seller, l.channel, l.location, l.price) for l in ls] == [("Baitfish", "14", "FM 5", 175000)]


def test_real_layout_diagnose(real):
    log = "\n".join(real.diagnose("Garnet Ore"))
    assert "Filter box found" in log and "Read 3 listing" in log
    assert "Cornhub | CH - | Perion Street Corner | 44,999 | 11m ago" in log
    assert "Typical price: 420" in log


def test_exact_price_from_title_only_when_it_agrees():
    r = browser.parse_listing_text("A\nCH 1\n3m ago\n45K\neach", titles=["44,999 mesos"])
    assert r["price"] == 44999
    r = browser.parse_listing_text("A\nCH 1\n3m ago\n45K\neach", titles=["9,999,999 mesos"])
    assert r["price"] == 45000  # a tooltip far from the displayed value is ignored


def test_parse_non_breaking_space_before_time():
    p = browser.parse_listing_text("Cornhub\nPerion Street Corner · 11m ago\nLikely still up\n45K\neach",
                                   titles=["44,999 mesos"])
    assert (p["seller"], p["location"], p["price"], p["listed"]) == ("Cornhub", "Perion Street Corner", 44999, "11m ago")


# ----------------------------------------------- scroll back through the Newest list
def test_scrolls_newest_back_three_hours(real):
    real.cfg["watchlist"] = [{"name": "Lazy Item", "max_price": None}]
    ls = real.fetch()
    ages = [l.age_min for l in ls]
    assert [l.seller for l in ls] == [f"Shop{i}" for i in range(18)]   # 5..175 min; only 12 render before scrolling
    assert max(ages) <= 180 and min(ages) >= 4.5
    # the shop listed 185 min ago says "3h ago" like one at 180, but its tooltip time puts it past 3 hours
    assert "Shop18" not in [l.seller for l in ls]
    assert real._page.locator("li.buy-row").count() > 12   # the page really was scrolled to load more


def test_lookback_is_editable(real):
    real.cfg["browser"]["lookback_min"] = 60
    real.cfg["watchlist"] = [{"name": "Lazy Item", "max_price": None}]
    assert [l.seller for l in real.fetch()] == [f"Shop{i}" for i in range(6)]   # 5..55 min
    real.cfg["browser"]["lookback_min"] = 30
    assert len(real.fetch()) == 3


def test_listing_cap_limits_a_pass(real):
    real.cfg["browser"]["listing_cap"] = 5
    real.cfg["watchlist"] = [{"name": "Lazy Item", "max_price": None}]
    assert len(real.fetch()) == 5


def test_age_refined_from_tooltip_time_only_when_it_agrees():
    from datetime import datetime
    now = datetime(2026, 11, 3, 9, 50)
    row = "A\nCH 1\n3h ago\n40K\neach"
    assert browser.parse_listing_text(row, titles=["A | last seen Nov 3, 6:39 AM"], now=now)["age_min"] == 191.0
    assert browser.parse_listing_text(row, titles=["A | seen Oct 30, 6:39 AM"], now=now)["age_min"] == 180.0  # tz/date mismatch
    assert browser.parse_listing_text("A\nCH 1\n11m ago\n40K\neach", titles=["A | seen Nov 3, 9:00 AM"], now=now)["age_min"] == 11.0
    assert browser.parse_listing_text(row, titles=["A | seen Dec 31, 11:30 PM"], now=datetime(2027, 1, 1, 2, 40))["age_min"] == 190.0


def test_similar_names_pick_the_exact_item(real):
    real.cfg["watchlist"] = [{"name": "Shoes Speed Scroll: Chaos", "max_price": None}]
    ls = real.fetch()
    assert [l.seller for l in ls] == ["RightShop"]
    # the first search result is Intermediate; it must never be used for Chaos
    real.cfg["watchlist"] = [{"name": "Shoe Speed Scroll: Chaos", "max_price": None}]
    assert real.fetch() == []
    assert "no item with exactly this name" in real.note


def test_random_pause_is_in_range_and_not_constant(tmp_path):
    cfg = core.Config(tmp_path / "c.json")
    vals = [core.random_pause_s(cfg) for _ in range(200)]
    assert min(vals) >= 0.5 and max(vals) <= 5.0 and len(set(vals)) > 50


def test_diagnose_says_so_when_listings_are_only_older_than_the_window(real):
    real.bc["lookback_min"] = 1  # the only Piece of Ice listing is 2m old
    log = real.diagnose("Piece of Ice")
    text = "\n".join(log)
    assert "no listings in the last 1 minutes" in text and "Nothing is wrong" in text
    assert "FAIL" not in text


# ------------------------------------------- scrolling the Newest list: slow, wheel-only and "Load more" sites
def _lazy(src, site, path):
    src.cfg["browser"].update(start_url=site + path, filter_placeholder="Filter items...")
    src.cfg["watchlist"] = [{"name": "Lazy Item", "max_price": None}]
    return src.fetch()


@pytest.mark.parametrize("path", ["/real-slow", "/real-wheel", "/real-button"])
def test_scrolling_survives_slow_wheel_only_and_load_more_lists(src, site, path):
    ls = _lazy(src, site, path)
    assert [l.seller for l in ls] == [f"Shop{i}" for i in range(18)]  # everything inside 3 hours, not just the first 12
    assert src._page.locator("li.buy-row").count() > 12
    si = src.scroll_info
    assert si["loads"] >= 1 and si["steps"] >= 2 and "older than the look-back window" in si["stop"]
    assert si["container"].startswith("ul")  # found the real scrolling box


def test_scroll_report_says_where_and_why_it_stopped(real):
    log = "\n".join(real.diagnose("Lazy Item"))
    assert "Scrolled the Newest list" in log and "ul.buy-list.scroll" in log and "site loaded more" in log


def test_list_that_really_ends_stops_after_waiting(real):
    real.bc["lookback_min"] = 100000  # nothing is "too old", so only the end of the list can stop it
    real.cfg["watchlist"] = [{"name": "Lazy Item", "max_price": None}]
    ls = real.fetch()
    assert len(ls) == 40 and real.scroll_info["stop"].startswith("the list stopped growing")


# ------------------------------------------- opening the right item: check the right-hand panel
class _Items:  # the bit of ItemDB the check uses
    items = {"02040000": {"name": "Shoes Speed Scroll: Chaos"}, "02040001": {"name": "Shoes Speed Scroll: Intermediate"}}


def test_icon_ids_come_from_the_file_name_only():
    assert browser.icon_ids("/icons/02040000.png?v=20261104") == ["02040000"]
    assert browser.icon_ids("https://cdn.x/items/2040000@2x.webp") == ["2040000"]
    assert browser.icon_ids('url("https://cdn.x/i/item_02040001.png")') == ["02040001"]
    assert browser.icon_ids("https://cdn.x/20261104/icon.png") == []  # the id is in a folder name: ignored
    assert browser.icon_ids("") == []


def test_next_result_is_tried_when_the_first_opens_another_item(src, site):
    src.cfg["browser"].update(start_url=site + "/scrolls")
    src.items = _Items()
    src.cfg["watchlist"] = [{"name": "Shoes Speed Scroll: Chaos", "max_price": None}]
    ls = src.fetch()
    assert [l.seller for l in ls] == ["RightShop"] and src.note == ""
    assert src.last_panels == ["Shoes Speed Scroll: Intermediate"]  # the first result was opened and rejected
    assert src.match_info == "name and icon match"


def test_right_name_but_wrong_icon_is_skipped(src, site):
    src.cfg["browser"].update(start_url=site + "/scrolls?mode=sameName")
    src.items = _Items()
    src.cfg["watchlist"] = [{"name": "Shoes Speed Scroll: Chaos", "max_price": None}]
    assert [l.seller for l in src.fetch()] == ["RightShop"]
    assert src.last_panels and "wrong icon" in src.last_panels[0]


def test_without_an_item_database_the_name_alone_decides(src, site):
    src.cfg["browser"].update(start_url=site + "/scrolls")
    src.cfg["watchlist"] = [{"name": "Shoes Speed Scroll: Chaos", "max_price": None}]
    assert [l.seller for l in src.fetch()] == ["RightShop"]
    assert src.match_info == "name matches (icon cannot be compared)"


def test_nothing_matching_records_nothing_and_says_what_the_panel_showed(src, site):
    src.cfg["browser"].update(start_url=site + "/scrolls?bad=1")
    src.cfg["watchlist"] = [{"name": "Shoes Speed Scroll: Chaos", "max_price": None}]
    assert src.fetch() == []
    assert "none of the 2 search results opened this item" in src.note and "Something Else Entirely" in src.note
    log = "\n".join(src.diagnose("Shoes Speed Scroll: Chaos"))
    assert "FAIL Opened 2 search result(s)" in log and "never showed 'Shoes Speed Scroll: Chaos'" in log



# ---- "For sale now" tab layout (from the real page's snapshot)
@pytest.fixture()
def fsn(src, site):
    src.cfg["browser"].update(start_url=site + "/fsn")
    src.cfg["watchlist"] = [{"name": "Shoes Speed Scroll: Chaos", "max_price": None}]
    return src


def test_for_sale_now_tab_is_clicked_and_every_listing_is_read_without_scrolling(fsn):
    ls = fsn.fetch()
    assert len(ls) == 60 and fsn.note == ""
    assert {l.seller for l in ls} == {f"Fsn{i}" for i in range(60)}  # not the Item Info tab's shop
    assert fsn.forsale_info.startswith("For sale now")
    si = fsn.scroll_info
    assert si["steps"] == 0 and si["expected"] == 60 and "already on the page" in si["stop"]


def test_hovering_the_list_and_rolling_the_wheel_loads_the_rest(fsn, site):
    fsn.cfg["browser"].update(start_url=site + "/fsn?mode=lazy")
    ls = fsn.fetch()
    assert len(ls) == 60  # the page only had 12 rows; the wheel over the list loaded the others
    assert fsn.scroll_info["expected"] == 60 and fsn.scroll_info["steps"] > 0


def test_results_are_clicked_one_by_one_up_to_the_limit(fsn, site):
    fsn.cfg["browser"].update(start_url=site + "/fsn?decoys=6")  # the right item is the 7th result
    assert fsn.fetch() == [] and "none of the 6 search results" in fsn.note
    assert fsn.cfg["browser"]["max_results_tried"] == 6  # the default
    fsn.cfg["browser"]["max_results_tried"] = 7
    assert len(fsn.fetch()) == 60 and len(fsn.last_panels) == 6  # six decoys opened and rejected, the 7th matched


def test_limit_is_editable_in_the_saved_settings(fsn, site):
    fsn.cfg["browser"].update(start_url=site + "/fsn?decoys=2", max_results_tried=2)
    assert fsn.fetch() == []  # right item would be 3rd
    fsn.cfg["browser"]["max_results_tried"] = 3
    assert len(fsn.fetch()) == 60


def test_icon_of_the_clicked_result_must_equal_the_panel_icon(fsn, site):
    fsn.cfg["browser"].update(start_url=site + "/fsn?mode=iconmismatch")  # 1st result: right name, panel shows another icon
    ls = fsn.fetch()
    assert len(ls) == 60
    assert fsn.last_panels and "wrong icon" in fsn.last_panels[0]
    assert fsn.match_info == "name and icon match the clicked result"


def test_diagnose_reports_the_for_sale_tab(fsn):
    log = "\n".join(fsn.diagnose("Shoes Speed Scroll: Chaos"))
    assert "Clicked the 'For sale now, 60 shops' tab" in log and "site says 60" in log


def test_old_layout_without_the_tab_still_works(src, site):
    src.cfg["browser"].update(start_url=site + "/real")
    src.cfg["watchlist"] = [{"name": "Piece of Ice", "max_price": None}]
    assert [l.seller for l in src.fetch()] == ["Iceman"] and src.forsale_info == ""


def test_scrolling_stops_at_the_show_listings_from_the_last_limit(fsn, site):
    fsn.cfg["browser"].update(start_url=site + "/fsn?mode=lazy", lookback_min=60)  # rows are 2, 4, ... 120 minutes old
    ls = fsn.fetch()
    assert len(ls) == 29 and max(l.age_min for l in ls) == 58  # the "1h ago" row is not inside a 1 hour window
    si = fsn.scroll_info
    assert "older than the look-back" in si["stop"] and si["loads"] <= 3  # it did not keep loading all 60 rows


def test_hidden_status_text_is_never_the_location():
    t = "ColdMomill\nCH 34\u00a0\u00b7 3m ago\nLikely still up\n40K\nDeal -5%"
    p = browser.parse_listing_text(t, ["", "999,999 mesos"][:1])
    assert p["seller"] == "ColdMomill" and p["channel"] == "34" and p["location"] == "" and p["price"] == 40000
    p = browser.parse_listing_text("Oxin\nKerning City Constru\u2026CH 30 \u00b7 22m ago\nSeller not confirmed\n180K", [])
    assert p["location"].startswith("Kerning City")
    assert not core.has_place(p["channel"], "")


@pytest.fixture(autouse=True)
def _private_data_dir(tmp_path, monkeypatch):
    """Error logs and settings of these tests never touch the real data folder."""
    monkeypatch.setattr(core, "data_dir", lambda: tmp_path)
    errorlog.clear()


@pytest.fixture()
def no_floors(monkeypatch):
    """Lets tests step through items without the production waits (60 s per item, 10 s between items)."""
    monkeypatch.setattr(core, "ITEM_REVISIT_FLOOR_S", 0.0)
    monkeypatch.setattr(core, "ROTATE_MIN_S", 1.0)


needs_screen = pytest.mark.skipif(not os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
                                  reason="needs a screen (run under xvfb-run)")


def test_background_runs_in_a_real_headless_browser_and_scrapes(fsn):
    assert len(fsn.fetch()) == 60
    assert fsn.mode == "background (headless)" and fsn.background


def test_windows_mode_reads_each_item_at_most_once_per_revisit_time(src, site):
    """Headless works for the rotating mode too, and an item read a moment ago is not read again."""
    src.close()
    src.cfg["browser"].update(start_url=site + "/fsn?decoys=1", scan_mode="windows")
    src.cfg["watchlist"] = [{"name": "Shoes Speed Scroll: Decoy 0", "max_price": None},
                            {"name": "Shoes Speed Scroll: Chaos", "max_price": None}]
    assert len(src.fetch()) == 60 and len(src.fetch()) == 60  # both set up
    for s in src._sessions.values():
        s.page.evaluate("window.__clicks = 0")
    assert src.fetch() == [] and "every item was read in the last" in src.note
    assert all(s.page.evaluate("window.__clicks") == 0 for s in src._sessions.values())
    assert 170 <= src.pause_s() <= 180 + 40  # waits until the first item is due again (default 180 s)


@needs_screen
def test_window_opens_by_itself_when_a_check_needs_a_person(src, site):
    src.cfg["browser"]["start_url"] = site + "/challenge"
    src.cfg["watchlist"] = [{"name": "Pan Lid", "max_price": None}]
    with pytest.raises(core.ChallengeDetected):
        src.fetch()  # nobody completes the check
    assert src.mode == "window" and not src.background
    assert "Opening the browser window for you" in "\n".join(errorlog.trail())


@needs_screen
def test_completed_check_is_not_mistaken_for_a_refusal(fsn, site):
    """The check page itself is answered with HTTP 403. After it was completed (here: the page moves on to the
    real site by itself) the old 403 must not stop the scan."""
    fsn.cfg["browser"].update(start_url=site + "/pass403", headless=False, challenge_wait_s=10)
    ls = fsn.fetch()
    assert len(ls) == 60
    assert "Check completed" in "\n".join(errorlog.trail())


def test_waits_for_the_search_results_to_be_redrawn(fsn, site):
    fsn.cfg["browser"].update(start_url=site + "/fsn?slow=1")  # the result table is empty for 1.5 s after typing
    assert len(fsn.fetch()) == 60


def test_stop_ends_the_scan_after_the_item_being_read(fsn):
    fsn.cfg["watchlist"] = [{"name": "Shoes Speed Scroll: Chaos", "max_price": None},
                            {"name": "Shoes Speed Scroll: Chaos", "max_price": None}]
    fsn.should_stop = lambda: True
    assert len(fsn.fetch()) == 60  # not 120


def test_every_items_result_is_in_the_trail(fsn):
    fsn.fetch()
    t = "\n".join(errorlog.trail())
    assert "Result for 'Shoes Speed Scroll: Chaos': 60 listing(s)" in t and "'For sale now' list: 60 rows" in t


def test_closing_the_window_is_not_a_completed_check(src):
    class Resp:
        headers = {"cf-mitigated": "challenge"}
        status = 403

    class ClosedPage:
        def is_closed(self):
            return True

        def title(self):
            raise RuntimeError("Target closed")
    src.cfg["browser"]["headless"] = False  # window mode: it waits for a person
    with pytest.raises(core.ChallengeDetected) as e:
        src._clear_challenge(ClosedPage(), Resp())
    assert "closed before the Cloudflare check was completed" in str(e.value)
    assert not any(ln.endswith("] The Cloudflare check was completed") for ln in errorlog.trail())


# ---- windows mode: one browser window per watched item, taken in turns
@pytest.fixture(params=["window", "headless"])
def win(request, src, site, no_floors):
    """The same browser, in windows mode: once with real windows (needs a screen), once headless (each item's
    "window" is then a page of the headless browser)."""
    headless = request.param == "headless"
    if not headless and (not os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        pytest.skip("needs a screen (run under xvfb-run)")
    src.close()
    src.cfg["item_revisit_min_s"] = 0
    src.cfg["browser"].update(start_url=site + "/fsn?decoys=1", headless=headless, scan_mode="windows")
    src.cfg["watchlist"] = [{"name": "Shoes Speed Scroll: Decoy 0", "max_price": None},
                            {"name": "Shoes Speed Scroll: Chaos", "max_price": None}]
    return src


def test_delay_between_items_is_the_users_range_clamped_to_10_600(src):
    src.cfg["browser"]["scan_mode"] = "windows"
    for lo, hi, want in ((13, 19, (13, 19)), (0, 5000, (10, 600)), (50, 10, (50, 50)), ("x", None, (20, 40))):
        src.cfg["rotate_delay_min_s"], src.cfg["rotate_delay_max_s"] = lo, hi
        assert core.rotate_delay_range(src.cfg) == (float(want[0]), float(want[1]))
        assert all(want[0] <= src.pause_s() <= want[1] for _ in range(20))


def test_one_page_mode_pauses_minutes_between_passes(src):
    src.cfg["browser"]["scan_mode"] = "single"
    assert all(180 <= src.pause_s() <= 300 for _ in range(20))  # default 3-5 minutes
    src.cfg["pass_delay_min_s"], src.cfg["pass_delay_max_s"] = 1, 2
    src.cfg["item_revisit_min_s"] = 0
    assert all(src.pause_s() >= 60 for _ in range(20))  # never below the floors, whatever the settings


def test_rate_limited_background_request_stops_the_scan(fsn, site):
    """A 429 to a request the page makes by itself (not a page load) must still stop the scan, with Retry-After."""
    fsn.cfg["watchlist"] = [{"name": "Shoes Speed Scroll: Chaos", "max_price": None}]
    fsn.fetch()  # page loaded, item read
    fsn._page.evaluate(f"fetch('{site}/api/limited').catch(() => null)")
    fsn._page.wait_for_timeout(300)
    with pytest.raises(core.RateLimited) as e:
        fsn.fetch()
    assert e.value.retry_after == pytest.approx(42, abs=2)  # minus the moment since the answer came
    assert "asked us to slow down (HTTP 429 for /api/limited)" in "\n".join(errorlog.trail())


def test_rate_limits_from_other_sites_are_ignored(src):
    class Resp:
        status, url, headers = 429, "https://example.org/x", {"retry-after": "5"}
    src._on_response(Resp())
    src._check_limited()  # nothing raised
    Resp.url = src.bc["start_url"] + "api/x"
    src._on_response(Resp())
    with pytest.raises(core.RateLimited) as e:
        src._check_limited()
    assert e.value.retry_after == pytest.approx(5, abs=1)


def test_cloudflare_check_page_is_not_counted_as_a_rate_limit(src):
    class Resp:
        status, headers = 503, {"cf-mitigated": "challenge"}
    Resp.url = src.bc["start_url"]
    src._on_response(Resp())
    src._check_limited()  # left to the challenge handling


def test_completed_check_starts_a_cooldown(src):
    class Page:
        def __init__(self):
            self.n = 0

        def is_closed(self):
            return False

        def title(self):
            self.n += 1
            return "Just a moment..." if self.n == 1 else "Meso Watch"
    src.cfg["browser"].update(headless=False, challenge_wait_s=5)
    src.cfg["browser"]["scan_mode"] = "single"
    assert src._clear_challenge(Page()) is True
    assert src.pause_s() >= 890  # default 15 minutes before the next read


def test_ordinary_error_does_not_restart_the_browser(fsn, monkeypatch):
    page = fsn._page
    monkeypatch.setattr(fsn, "_monitor", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        fsn.fetch()
    assert fsn._page is page and not page.is_closed()  # same browser, nothing reloaded
    assert "Opening the browser window for you" not in "\n".join(errorlog.trail())


def test_windows_mode_sets_items_up_one_window_each_then_refreshes_by_one_click(win):
    a = win.fetch()  # step 1: window for the first item, searched, verified, For sale now tab, read
    assert len(a) == 60 and {l.item_name for l in a} == {"Shoes Speed Scroll: Decoy 0"}
    assert list(win._sessions) == ["shoes speed scroll: decoy 0"] and "set up" in win.note
    b = win.fetch()  # step 2: the second item gets a window of its own
    assert len(b) == 60 and {l.item_name for l in b} == {"Shoes Speed Scroll: Chaos"}
    s1, s2 = win._sessions.values()
    assert s1.page is not s2.page and len([p for p in win._ctx.pages if not p.is_closed()]) == 2
    s1.page.evaluate("window.__keep = 1; window.__clicks = 0")
    s2.page.evaluate("window.__keep = 1; window.__clicks = 0")
    c = win.fetch()  # step 3: back to the first window; its item is clicked ONCE, nothing is reloaded
    assert {l.item_name for l in c} == {"Shoes Speed Scroll: Decoy 0"} and len(c) == 60 and "refreshed" in win.note
    assert s1.page.evaluate("[window.__keep, window.__clicks]") == [1, 1]
    assert s2.page.evaluate("[window.__keep, window.__clicks]") == [1, 0]  # the other window was not touched
    d = win.fetch()
    assert {l.item_name for l in d} == {"Shoes Speed Scroll: Chaos"} and s2.page.evaluate("window.__clicks") == 1
    assert s2.page.evaluate("window.__keep") == 1  # never navigated away
    assert [p.url for p in (s1.page, s2.page)] == [win.bc["start_url"]] * 2


def test_windows_mode_item_that_cannot_be_found_does_not_block_the_others(win):
    win.cfg["watchlist"] = [{"name": "No Such Item", "max_price": None}, {"name": "Shoes Speed Scroll: Chaos", "max_price": None}]
    first = win.fetch()
    assert first == [] and "none of the" in win.note and "opened this item" in win.note
    assert len(win.fetch()) == 60  # the next step is the other item, not another try of the missing one
    assert list(win._sessions) == ["shoes speed scroll: chaos"]


def test_windows_mode_closed_window_is_opened_again_and_removed_items_lose_their_window(win):
    win.fetch(); win.fetch()
    first = next(iter(win._sessions.values())).page
    first.close()  # the user closed one window
    win.fetch()
    assert len(win._sessions) == 2 and all(not s.page.is_closed() for s in win._sessions.values())
    win.cfg["watchlist"] = [{"name": "Shoes Speed Scroll: Chaos", "max_price": None}]
    win.fetch()
    assert list(win._sessions) == ["shoes speed scroll: chaos"]
    assert len([p for p in win._ctx.pages if not p.is_closed()]) == 1


def test_windows_mode_works_with_the_poller_and_pause(win):
    got, status = [], []
    win.cfg["rotate_delay_min_s"] = win.cfg["rotate_delay_max_s"] = 1
    poller = core.Poller(win, win.cfg, got.extend, status.append)
    poller.start()
    t0 = time.time()
    while len(got) < 120 and time.time() - t0 < 60:
        time.sleep(0.5)
    assert len(got) >= 120  # both items were read, one step each, about 1 s apart
    poller.pause()
    time.sleep(2.5)
    n = len(got)
    time.sleep(3)
    assert len(got) == n  # paused: no new step
    poller.resume()
    t1 = time.time()
    while len(got) == n and time.time() - t1 < 20:
        time.sleep(0.5)
    assert len(got) > n
    poller.stop()
    poller.join(15)


def test_passive_mode_leaves_pages_alone_and_reads_only_changed_lists(win):
    win.fetch(); win.fetch()  # both windows are set up and read
    win.cfg["browser"].update(passive_updates=True, watch_check_s=2, watch_stale_min=0)
    s1, s2 = win._sessions.values()
    for s in (s1, s2):
        s.page.evaluate("window.__clicks = 0; window.__keep = 1")
    assert win.fetch() == [] and "no change" in win.note and win._watching
    assert win.pause_s() == 2.0  # a cheap local check, not the item delay
    assert s1.page.evaluate("window.__clicks") == 0 and s2.page.evaluate("window.__clicks") == 0
    s2.page.evaluate("window.__add()")  # the site updated one list by itself
    got = win.fetch()
    assert {l.item_name for l in got} == {"Shoes Speed Scroll: Chaos"} and len(got) == 61
    assert s2.page.evaluate("[window.__clicks, window.__keep]") == [0, 1]  # read without any click or reload
    assert s1.page.evaluate("window.__clicks") == 0
    assert win.fetch() == []  # nothing new since
    rows = {r["item"]: r for r in win.session_status()}
    assert rows["Shoes Speed Scroll: Chaos"]["shops"] == 61 and rows["Shoes Speed Scroll: Chaos"]["state"] == "watching"


def test_passive_mode_refreshes_a_window_whose_list_never_changes(win):
    win.fetch(); win.fetch()
    win.cfg["browser"].update(passive_updates=True, watch_check_s=1, watch_stale_min=0.001)  # 0.06 s
    s1, _ = win._sessions.values()
    s1.page.evaluate("window.__clicks = 0")
    time.sleep(0.2)
    win.fetch()
    assert s1.page.evaluate("window.__clicks") == 1 and "refreshed" in win.note


def test_passive_mode_waits_until_every_item_has_its_window(win):
    win.cfg["browser"].update(passive_updates=True)
    assert win.session_status()[0]["state"] == "waiting for its turn"


def test_an_old_rate_limit_answer_only_counts_for_the_rest_of_its_wait(src, monkeypatch):
    class Resp:
        status, headers = 429, {"retry-after": "60"}
    Resp.url = src.bc["start_url"] + "api/x"
    clock = [1000.0]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    src._on_response(Resp())
    clock[0] += 45  # a page's own refresh got the 429; our next action comes 45 s later
    with pytest.raises(core.RateLimited) as e:
        src._check_limited()
    assert e.value.retry_after == pytest.approx(15)
    src._on_response(Resp())
    clock[0] += 90  # the wait the site asked for is already over
    src._check_limited()  # nothing raised


def test_a_step_with_nothing_due_does_not_count_as_contacting_the_site(src, site):
    src.close()
    src.cfg["browser"].update(start_url=site + "/fsn?decoys=1", scan_mode="windows")
    src.cfg["watchlist"] = [{"name": "Shoes Speed Scroll: Chaos", "max_price": None}]
    assert len(src.fetch()) == 60 and src.touched_site  # set up: the site was used
    assert src.fetch() == [] and not src.touched_site  # read a moment ago: nothing was sent


@needs_screen
def test_headless_check_opens_a_window_and_the_scan_goes_on_after_it_was_completed(fsn, site):
    """Headless -> a Cloudflare check appears -> the window opens by itself -> the check is completed there (here
    the mock page moves on by itself) -> the items are read, and the next read waits for the cool-down. The rest
    of the session stays in the window (the clearance belongs to that browser)."""
    fsn.close()
    fsn.cfg["browser"].update(start_url=site + "/pass403", headless=True, challenge_wait_s=15)
    assert fsn.background
    assert len(fsn.fetch()) == 60
    trail = "\n".join(errorlog.trail())
    assert "Opening the browser window for you" in trail and "The Cloudflare check was completed" in trail
    assert fsn.mode == "window" and not fsn.background
    assert fsn.pause_s() >= 890


def test_each_running_program_gets_its_own_library_folder(tmp_path):
    from mesowatcher import portable
    base = tmp_path / "active"
    (base / "999999999").mkdir(parents=True)  # left by a program that is no longer running
    (base / "1").mkdir()  # pid 1 is always running: not ours, kept
    mine = portable.libs_work_dir(base)
    assert mine.name == str(os.getpid())
    assert not (base / "999999999").exists() and (base / "1").exists()


@needs_screen
def test_rotating_mode_check_opens_a_window_and_the_item_is_set_up_in_it(src, site, no_floors):
    """The same in the rotating mode: the item being set up continues in the window that opened for the check."""
    src.close()
    src.cfg["item_revisit_min_s"] = 0
    src.cfg["browser"].update(start_url=site + "/pass403", headless=True, scan_mode="windows", challenge_wait_s=15)
    src.cfg["watchlist"] = [{"name": "Shoes Speed Scroll: Chaos", "max_price": None}]
    assert len(src.fetch()) == 60
    assert src.mode == "window" and "shoes speed scroll: chaos" in src._sessions
    assert not src._sessions["shoes speed scroll: chaos"].page.is_closed()
