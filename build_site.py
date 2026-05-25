#!/usr/bin/env python3
"""Generate static site from games.db for GitHub Pages deployment."""

import json
import re
import sys
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

from database import init_db, get_connection

logger = logging.getLogger(__name__)

GENRE_LIST = [
    "Action", "Adventure", "RPG", "Strategy", "Simulation",
    "Casual", "Indie", "Sports", "Racing",
    "Massively Multiplayer", "Early Access", "Free To Play",
]

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Online-Fix Game Analyzer</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font:14px/1.5 -apple-system,BlinkMacSystemFont,sans-serif;background:#0d1117;color:#c9d1d9}
h1{font-size:20px;padding:16px 20px;background:#161b22;border-bottom:1px solid #30363d;position:sticky;top:0;z-index:10;display:flex;align-items:center;gap:8px}
h1 span{color:#58a6ff;font-size:13px;font-weight:400}

.filters{padding:12px 20px;background:#161b22;border-bottom:1px solid #30363d;display:flex;flex-wrap:wrap;gap:8px;align-items:start;position:sticky;top:52px;z-index:9}
.filters label{font-size:11px;color:#8b949e;display:flex;flex-direction:column;gap:3px}
.filters select,.filters input[type=text]{background:#21262d;border:1px solid #30363d;color:#c9d1d9;padding:5px 8px;border-radius:4px;font-size:12px;min-width:80px}
.filters input[type=checkbox]{margin:0}
.filters button{background:#238636;color:#fff;border:none;padding:6px 12px;border-radius:4px;cursor:pointer;font-size:12px}
.filters button:hover{background:#2ea043}
.filters .sep{border-left:1px solid #30363d;height:30px;margin:0 4px}
.genre-label{flex-direction:row!important;align-items:center;gap:4px!important;font-size:11px;cursor:pointer;color:#c9d1d9;background:#21262d;border:1px solid #30363d;padding:3px 7px;border-radius:4px;white-space:nowrap}
.genre-label.checked{border-color:#58a6ff;background:#1f2a3a}
.genre-label input{width:0;height:0;opacity:0;position:absolute}
.genre-list{display:flex;flex-wrap:wrap;gap:4px}

.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;padding:16px 20px}

.card{background:#161b22;border:1px solid #30363d;border-radius:6px;overflow:hidden;cursor:pointer;transition:border-color .2s,transform .1s}
.card:hover{border-color:#58a6ff;transform:translateY(-2px)}
.card .poster{width:100%;aspect-ratio:16/9;object-fit:cover;background:#0d1117;display:block}
.card .placeholder{width:100%;aspect-ratio:16/9;background:#21262d;display:flex;align-items:center;justify-content:center;color:#484f58;font-size:11px;text-align:center;padding:8px}
.card-body{padding:8px 10px}
.card-title{font-size:13px;font-weight:600;line-height:1.3;margin-bottom:6px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.card-meta{display:flex;gap:6px;align-items:center;flex-wrap:wrap;font-size:11px}
.card-meta .rating{padding:2px 5px;border-radius:3px;font-weight:600;font-size:11px}
.rating-high{background:#238636;color:#fff}
.rating-mid{background:#9e6a03;color:#fff}
.rating-low{background:#da3633;color:#fff}
.rating-none{background:#30363d;color:#8b949e}
.card-meta .views{color:#8b949e}
.card-meta .mode{font-size:10px;padding:1px 4px;border-radius:2px}
.mode-coop{background:#1f3a3a;color:#7ee787}
.mode-multi{background:#2a1f3a;color:#bc8cff}

.overlay{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.7);z-index:100;justify-content:center;align-items:center}
.overlay.show{display:flex}
.detail{background:#161b22;border:1px solid #30363d;border-radius:8px;max-width:600px;width:90%;max-height:85vh;overflow-y:auto;padding:20px;position:relative}
.detail .close{position:absolute;top:10px;right:14px;font-size:22px;cursor:pointer;color:#8b949e;line-height:1}
.detail h2{font-size:18px;margin-bottom:12px}
.detail img{width:100%;border-radius:4px;margin-bottom:12px}
.detail table{width:100%;font-size:13px;border-collapse:collapse}
.detail td{padding:4px 8px;border-bottom:1px solid #21262d}
.detail td:first-child{color:#8b949e;width:120px}
.detail a{color:#58a6ff}

.empty{padding:40px;text-align:center;color:#8b949e;font-size:14px}
</style>
</head>
<body>
<h1>Online-Fix Game Analyzer <span id="game-count"></span> <a style="margin-left:auto;font-size:12px;font-weight:400;color:#58a6ff;cursor:pointer;text-decoration:none" href="#" onclick="showLinuxGuide();return false">&#x1f427; Linux guide</a></h1>

<div class="filters" id="filters">
  <label>Search <input type="text" id="f-search" placeholder="title..."></label>
  <label>FixMe Category <select id="f-cat"><option value="">All</option></select></label>
  <span class="sep"></span>
  <label title="Minimum Steam rating %">Rating &#x2265;<span><input type="range" id="f-rating" min="0" max="100" value="0" step="5"><span id="f-rating-val" style="font-size:11px;color:#8b949e;min-width:28px">0</span></span></label>
  <span class="sep"></span>
  <label><input type="checkbox" id="f-coop">Co-op</label>
  <label><input type="checkbox" id="f-multi">Multi</label>
  <label title="Minimum player estimate">Players &#x2265;<select id="f-players"><option value="0">Any</option><option value="10000">10K+</option><option value="100000">100K+</option><option value="1000000">1M+</option><option value="10000000">10M+</option></select></label>
  <span class="sep"></span>
  <label>Genre
    <span style="display:flex;align-items:center;gap:4px;margin-bottom:2px">
      <span id="genre-mode" onclick="toggleGenreMode()"
            style="cursor:pointer;font-size:10px;padding:1px 5px;border-radius:3px;background:#21262d;border:1px solid #30363d">OR</span>
    </span>
    <div class="genre-list" id="f-genres"></div>
  </label>
  <span class="sep"></span>
  <label>Sort <select id="f-sort"><option value="views">Views</option><option value="rating">Rating</option><option value="comments">Comments</option><option value="players">Players</option><option value="release">Release date</option></select></label>
  <button id="f-reset">Reset</button>
</div>

<div class="grid" id="grid"></div>
<div class="empty" id="empty" style="display:none">No games match your filters.</div>

<div class="overlay" id="overlay">
  <div class="detail" id="detail"></div>
</div>

<div class="overlay" id="linux-overlay">
  <div class="detail" style="max-width:500px">
    <div class="close" onclick="document.getElementById('linux-overlay').classList.remove('show')">&times;</div>
    <h2 style="font-size:18px;margin-bottom:12px">Running online-fix games on Linux</h2>
    <div style="font-size:13px;line-height:1.7">
      <p><b>Prerequisites:</b></p>
      <ul style="margin:6px 0 12px 20px">
        <li>Steam installed and logged in</li>
        <li>GE-Proton (GloriousEggroll) &mdash; best compatibility</li>
        <li>Wine/proton dependencies (<code>steam-devices</code>, etc.)</li>
      </ul>
      <p><b>Environment variables needed:</b></p>
      <code style="display:block;background:#21262d;padding:10px;border-radius:4px;margin:4px 0 10px;font-size:11px;word-break:break-all;white-space:pre-wrap">
STEAM_COMPAT_DATA_PATH=&quot;/path/to/game/prefix&quot;
STEAM_COMPAT_CLIENT_INSTALL_PATH=&quot;$HOME/.steam/steam&quot;
WINEDLLOVERRIDES=&quot;steam_api64=n;onlinefix64=n;eossdk=n;winmm=n,b&quot;
GE-Proton/proton run game.exe
      </code>
      <p><b>WINEDLLOVERRIDES explained:</b></p>
      <p style="color:#8b949e;margin-bottom:8px">
        The fix archive replaces some Windows DLLs with custom ones.
        Each <code>fix.dll=n</code> tells Wine to use the fix version
        instead of the built-in one. Which DLLs you need depends on the
        fix &mdash; check the game folder for <code>.dll</code> files.
      </p>
      <p><b>Common issues:</b></p>
      <ul style="margin:6px 0 0 20px">
        <li>Crash on launch &rarr; wrong or missing DLL override</li>
        <li>&quot;Steam must be running&quot; &rarr; start Steam first</li>
        <li>EOS init failure &rarr; missing <code>eossdk=n</code> override</li>
        <li>Black screen &rarr; try <code style="background:#21262d;padding:2px 4px;border-radius:2px;font-size:10px">PROTON_USE_WINED3D=1</code></li>
      </ul>
      <hr style="border-color:#30363d;margin:14px 0 8px">
      <p style="font-size:11px;color:#8b949e">
        <b style="color:#da3633">&#x26a0; Security warning:</b>
        Cracked games run modified code. Only download from sources you trust.
        Consider running in an isolated Wine prefix or container.
      </p>
      <p style="font-size:11px;color:#8b949e;margin-top:4px">
        Reference launcher:
        <a href="https://github.com/ZzEdovec/onlinefix-linux" target="_blank" style="color:#58a6ff">
          github.com/ZzEdovec/onlinefix-linux
        </a>
        &mdash; automates the above. Evaluate before use.
      </p>
    </div>
  </div>
</div>

<script>
var GAMES = __DATA__;
var GENRE_MODE = 'or';

function ratingClass(pct) {
  if (!pct) return 'rating-none';
  if (pct >= 80) return 'rating-high';
  if (pct >= 60) return 'rating-mid';
  return 'rating-low';
}

function formatNum(n) { return n ? n.toLocaleString() : '0'; }

function toggleGenreMode() {
  GENRE_MODE = GENRE_MODE === 'or' ? 'and' : 'or';
  document.getElementById('genre-mode').textContent = GENRE_MODE.toUpperCase();
  filterGames();
}

function sortGames(games, by) {
  var key;
  switch (by) {
    case 'views': key = 'views'; break;
    case 'rating': key = 'rating_pct'; break;
    case 'comments': key = 'comments'; break;
    case 'players': key = 'players_estimate'; break;
    case 'release': key = 'release_date'; break;
    default: key = 'views';
  }
  return games.slice().sort(function(a, b) {
    return (b[key] || 0) - (a[key] || 0);
  });
}

function filterGames() {
  var search = (document.getElementById('f-search').value || '').toLowerCase();
  var cat = document.getElementById('f-cat').value;
  var minRating = parseInt(document.getElementById('f-rating').value);
  var coop = document.getElementById('f-coop').checked;
  var multi = document.getElementById('f-multi').checked;
  var minPlayers = parseInt(document.getElementById('f-players').value);
  var sort = document.getElementById('f-sort').value;
  var genreCbs = document.querySelectorAll('.genre-label input:checked');
  var activeGenres = Array.prototype.map.call(genreCbs, function(c){return c.value;});

  document.getElementById('f-rating-val').textContent = minRating;

  var filtered = GAMES;
  if (search) filtered = filtered.filter(function(g) { return (g.title || '').toLowerCase().indexOf(search) !== -1; });
  if (cat) filtered = filtered.filter(function(g) { return g.category === cat; });
  if (minRating > 0) filtered = filtered.filter(function(g) { return g.rating_pct >= minRating; });
  if (coop) filtered = filtered.filter(function(g) { return g.coop; });
  if (multi) filtered = filtered.filter(function(g) { return g.multiplayer; });
  if (minPlayers > 0) filtered = filtered.filter(function(g) { return g.players_estimate >= minPlayers; });
  if (activeGenres.length) {
    filtered = filtered.filter(function(g) {
      var gameGenres = (g.genres || '').split(',').map(function(s){return s.trim();});
      if (GENRE_MODE === 'and') {
        return activeGenres.every(function(ag){ return gameGenres.indexOf(ag) !== -1; });
      }
      return activeGenres.some(function(ag){ return gameGenres.indexOf(ag) !== -1; });
    });
  }

  filtered = sortGames(filtered, sort);
  render(filtered);
  updateHash();
}

function render(games) {
  var grid = document.getElementById('grid');
  var empty = document.getElementById('empty');
  document.getElementById('game-count').textContent = '(' + games.length + ' games)';

  if (!games.length) { grid.innerHTML = ''; empty.style.display = 'block'; return; }
  empty.style.display = 'none';

  var html = '';
  for (var i = 0; i < games.length; i++) {
    var g = games[i];
    var img = g.img_url ? '<img class="poster" src="'+g.img_url+'" loading="lazy" alt="">' : '<div class="placeholder">No preview<br>download images<br>and rebuild</div>';
    var rc = ratingClass(g.rating_pct);
    var ratingHtml = g.rating_pct ? '<span class="rating '+rc+'">'+g.rating_pct+'%</span>' : '<span class="rating rating-none">-</span>';
    var coopHtml = g.coop ? '<span class="mode mode-coop">Co-op</span>' : '';
    var multiHtml = g.multiplayer ? '<span class="mode mode-multi">Multi</span>' : '';
    html += '<div class="card" data-id="'+g.id+'" onclick="showDetail('+g.id+')">'
    + img
    + '<div class="card-body">'
    + '<div class="card-title">'+esc(g.title)+'</div>'
    + '<div class="card-meta">'+ratingHtml+' '+coopHtml+' '+multiHtml+' <span class="views">'+formatNum(g.views)+'</span></div>'
    + '</div></div>';
  }
  grid.innerHTML = html;
}

function esc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function showDetail(id) {
  var g = null;
  for (var i = 0; i < GAMES.length; i++) { if (GAMES[i].id === id) { g = GAMES[i]; break; } }
  if (!g) return;

  var overlay = document.getElementById('overlay');
  var detail = document.getElementById('detail');
  var rc = ratingClass(g.rating_pct);
  var img = g.img_url ? '<img src="'+g.img_url+'" alt="">' : '';

  var html = '<div class="close" onclick="document.getElementById(\'overlay\').classList.remove(\'show\')">&times;</div>'
    + '<h2>'+esc(g.title)+'</h2>' + img
    + '<table>'
    + '<tr><td>Category</td><td>'+esc(g.category)+'</td></tr>'
    + '<tr><td>Views</td><td>'+formatNum(g.views)+'</td></tr>'
    + '<tr><td>Comments</td><td>'+g.comments+'</td></tr>'
    + '<tr><td>Release</td><td>'+esc(g.release_date)+'</td></tr>'
    + '<tr><td>Co-op / Multi</td><td>'+(g.coop?'Co-op ':'')+(g.multiplayer?'Multi':'')+'</td></tr>';
  if (g.last_updated) html += '<tr><td>Updated</td><td>'+esc(g.last_updated)+'</td></tr>';

  html += '<tr><td>Rating</td><td><span class="rating '+rc+'">'+(g.rating_pct||'?')+'%</span> '+(g.review_count?'('+formatNum(g.review_count)+')':'')+'</td></tr>';

  if (g.players_estimate) html += '<tr><td>Players</td><td>~'+formatNum(g.players_estimate)+'</td></tr>';
  if (g.genres) html += '<tr><td>Genres</td><td>'+esc(g.genres)+'</td></tr>';
  if (g.tags) html += '<tr><td>Tags</td><td>'+esc(g.tags)+'</td></tr>';
  if (g.developer) html += '<tr><td>Developer</td><td>'+esc(g.developer)+'</td></tr>';
  if (g.metacritic) html += '<tr><td>Metacritic</td><td>'+g.metacritic+'</td></tr>';
  if (g.steam_appid) html += '<tr><td>Steam</td><td><a href="https://store.steampowered.com/app/'+g.steam_appid+'" target="_blank">Store</a></td></tr>';
  html += '<tr><td>Online-Fix</td><td><a href="'+esc(g.url)+'" target="_blank">View</a></td></tr>';
  html += '</table>';

  detail.innerHTML = html;
  overlay.classList.add('show');
}

document.getElementById('overlay').addEventListener('click', function(e) {
  if (e.target === this) this.classList.remove('show');
});

function showLinuxGuide() {
  document.getElementById('linux-overlay').classList.add('show');
}

document.getElementById('linux-overlay').addEventListener('click', function(e) {
  if (e.target === this) this.classList.remove('show');
});

function updateHash() {
  var parts = [];
  var s = document.getElementById('f-search').value;
  var cat = document.getElementById('f-cat').value;
  var r = document.getElementById('f-rating').value;
  var c = document.getElementById('f-coop').checked;
  var m = document.getElementById('f-multi').checked;
  var pl = document.getElementById('f-players').value;
  var sort = document.getElementById('f-sort').value;
  var genreCbs = document.querySelectorAll('.genre-label input:checked');
  var genres = Array.prototype.map.call(genreCbs, function(cb){return cb.value;}).join(',');

  if (s) parts.push('s='+encodeURIComponent(s));
  if (cat) parts.push('cat='+cat);
  if (r !== '0' && r !== '') parts.push('r='+r);
  if (c) parts.push('c=1');
  if (m) parts.push('m=1');
  if (pl !== '0') parts.push('pl='+pl);
  if (sort !== 'views') parts.push('sort='+sort);
  if (genres) parts.push('genres='+genres);
  if (GENRE_MODE === 'and') parts.push('gm=and');

  location.hash = parts.join('&');
}

function loadHash() {
  var h = {};
  try { var parts = location.hash.slice(1).split('&');
    for (var i = 0; i < parts.length; i++) { var kv = parts[i].split('='); h[kv[0]] = decodeURIComponent(kv[1] || ''); }
  } catch(e) {}
  if (h.s !== undefined) document.getElementById('f-search').value = h.s;
  if (h.cat) document.getElementById('f-cat').value = h.cat;
  if (h.r) document.getElementById('f-rating').value = h.r;
  document.getElementById('f-coop').checked = h.c === '1';
  document.getElementById('f-multi').checked = h.m === '1';
  if (h.pl) document.getElementById('f-players').value = h.pl;
  if (h.sort) document.getElementById('f-sort').value = h.sort;
  if (h.genres) {
    var active = h.genres.split(',');
    var allCbs = document.querySelectorAll('.genre-label input');
    for (var j = 0; j < allCbs.length; j++) {
      allCbs[j].checked = active.indexOf(allCbs[j].value) !== -1;
      allCbs[j].parentElement.classList.toggle('checked', allCbs[j].checked);
    }
  }
  if (h.gm === 'and') {
    GENRE_MODE = 'and';
    document.getElementById('genre-mode').textContent = 'AND';
  }
}

(function() {
  var cats = {};
  for (var i = 0; i < GAMES.length; i++) { var c = GAMES[i].category; if (c) cats[c] = 1; }
  var sel = document.getElementById('f-cat');
  Object.keys(cats).sort().forEach(function(c) {
    var o = document.createElement('option'); o.value = c; o.textContent = c; sel.appendChild(o);
  });

  var GENRES = __GENRES__.split(',');
  var genreDiv = document.getElementById('f-genres');
  for (var gi = 0; gi < GENRES.length; gi++) {
    var g = GENRES[gi];
    var lbl = document.createElement('label');
    lbl.className = 'genre-label';
    var cb = document.createElement('input');
    cb.type = 'checkbox'; cb.value = g;
    cb.addEventListener('change', function(e){
      e.target.parentElement.classList.toggle('checked', e.target.checked);
      filterGames();
    });
    lbl.appendChild(cb);
    lbl.appendChild(document.createTextNode(g));
    genreDiv.appendChild(lbl);
  }

  document.getElementById('f-search').addEventListener('input', filterGames);
  document.getElementById('f-cat').addEventListener('change', filterGames);
  document.getElementById('f-rating').addEventListener('input', filterGames);
  document.getElementById('f-coop').addEventListener('change', filterGames);
  document.getElementById('f-multi').addEventListener('change', filterGames);
  document.getElementById('f-players').addEventListener('change', filterGames);
  document.getElementById('f-sort').addEventListener('change', filterGames);
  document.getElementById('f-reset').addEventListener('click', function() {
    location.hash = '';
    document.getElementById('f-search').value = '';
    document.getElementById('f-cat').value = '';
    document.getElementById('f-rating').value = '0';
    document.getElementById('f-rating-val').textContent = '0';
    document.getElementById('f-coop').checked = false;
    document.getElementById('f-multi').checked = false;
    document.getElementById('f-players').value = '0';
    document.getElementById('f-sort').value = 'views';
    GENRE_MODE = 'or';
    document.getElementById('genre-mode').textContent = 'OR';
    var allCbs = document.querySelectorAll('.genre-label input');
    for (var j = 0; j < allCbs.length; j++) { allCbs[j].checked = false; allCbs[j].parentElement.classList.remove('checked'); }
    filterGames();
  });
  window.addEventListener('hashchange', function() { loadHash(); filterGames(); });
  loadHash();
  filterGames();
})();
</script>
</body>
</html>"""


def _download_previews(games: list[dict], site_dir: str):
    img_dir = Path(site_dir) / "img"
    img_dir.mkdir(exist_ok=True)

    # Build set of unique steam_appids that need downloading
    appids_needed = {}
    for g in games:
        aid = g.get("steam_appid")
        if not aid:
            continue
        target = img_dir / f"{aid}.jpg"
        if target.exists():
            g["img_url"] = f"img/{aid}.jpg"
        else:
            appids_needed.setdefault(aid, []).append(g)

    if not appids_needed:
        return

    total = len(appids_needed)
    print(f"Downloading {total} Steam header images...", flush=True)
    done = 0

    def _dl_one(args) -> tuple[int, bool]:
        appid, games_list = args
        target = img_dir / f"{appid}.jpg"
        tmp = target.with_suffix(".tmp")
        url = f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/header.jpg"

        for attempt in range(5):
            try:
                with httpx.Client(timeout=10, follow_redirects=True) as c:
                    resp = c.get(url)
                    if resp.status_code == 429:
                        wait = 2 * (2 ** attempt)
                        time.sleep(wait)
                        continue
                    if resp.status_code == 200:
                        tmp.write_bytes(resp.content)
                        if len(resp.content) < 1000:
                            tmp.unlink(missing_ok=True)
                            break
                        tmp.rename(target)
                        for g in games_list:
                            g["img_url"] = f"img/{appid}.jpg"
                        return appid, True
                    if resp.status_code in (404, 410):
                        print(f"  appid {appid} not found on Steam CDN")
                        break
            except Exception as e:
                logger.warning("  appid %d attempt %d: %s", appid, attempt + 1, e)
                time.sleep(2 * (2 ** attempt))
                continue
            break

        return appid, False

    with ThreadPoolExecutor(max_workers=4) as pool:
        items = list(appids_needed.items())
        futs = {}
        for item in items:
            futs[pool.submit(_dl_one, item)] = item[0]
        for fut in as_completed(futs):
            done += 1
            aid, ok = fut.result()
            if done % 100 == 0 or done == total:
                print(f"  images {done}/{total}", flush=True)
            time.sleep(0.1)

    # Fallback to online-fix.me images that Steam didn't have
    still_missing = [g for g in games if not g.get("img_url") and g.get("poster_url")]
    if still_missing:
        print(f"  Steam store + fix-me fallback for {len(still_missing)} images...", flush=True)
        done = 0
        for g in still_missing:
            aid = g.get("steam_appid")
            if not aid:
                done += 1
                continue
            target = img_dir / f"{aid}.jpg"
            if target.exists():
                g["img_url"] = f"img/{aid}.jpg"
                done += 1
                continue

            saved = False

            # 1) Try Steam store page → hashed header/capsule URL
            try:
                store_resp = httpx.get(
                    f"https://store.steampowered.com/app/{aid}",
                    follow_redirects=True, timeout=10,
                )
                # Match any steam image: header.jpg, header_alt_assets_N.jpg, capsule_616x353*.jpg
                m = re.search(
                    r"https://shared\.fastly\.steamstatic\.com/store_item_assets/steam/apps/"
                    + re.escape(str(aid))
                    + r"/[a-f0-9]+/(?:header|capsule_616x353)[^\"']*\.jpg",
                    store_resp.text,
                )
                if m:
                    r = httpx.get(m.group(0), timeout=10, follow_redirects=True)
                    if r.status_code == 200 and len(r.content) >= 1000:
                        (img_dir / f"{aid}.tmp").write_bytes(r.content)
                        (img_dir / f"{aid}.tmp").rename(target)
                        g["img_url"] = f"img/{aid}.jpg"
                        saved = True
            except:
                pass

            # 2) If still no image → try online-fix.me poster
            if not saved and g.get("poster_url"):
                try:
                    with httpx.Client(timeout=10, follow_redirects=True) as c:
                        resp = c.get(g["poster_url"])
                        if resp.status_code == 200 and len(resp.content) >= 1000:
                            (img_dir / f"{aid}.tmp").write_bytes(resp.content)
                            (img_dir / f"{aid}.tmp").rename(target)
                            g["img_url"] = f"img/{aid}.jpg"
                except:
                    pass

            done += 1
            if done % 20 == 0:
                print(f"  fallback {done}/{len(still_missing)}", flush=True)
            time.sleep(1.5)  # small gap between batches to not hammer Steam


def build(site_dir: str = "site"):
    init_db()
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT g.id, g.title, g.category, g.views, g.comments,
               g.has_coop, g.has_multiplayer, g.release_date, g.poster_url,
               g.url as of_url, g.last_updated,
               s.steam_appid, s.steam_name, s.review_score, s.review_count,
               s.review_desc, s.price_usd, s.players_estimate, s.genres,
               s.tags, s.developer, s.publisher, s.metacritic_score,
               s.is_multiplayer as steam_multiplayer, s.is_coop as steam_coop
        FROM games g
        INNER JOIN steam_info s ON g.id = s.game_id
        WHERE s.steam_appid > 0
        ORDER BY g.views DESC
        """
    ).fetchall()
    conn.close()

    games = []
    for r in rows:
        g = dict(r)
        pct = 0
        if g.get("review_count") and g["review_count"] > 0:
            pct = round(g["review_score"] / g["review_count"] * 100)
        steam_status = "delisted" if (g["steam_appid"] and g["steam_appid"] > 0 and (not g.get("review_count") or g["review_count"] == 0)) else "ok"
        games.append({
            "id": g["id"],
            "title": g["title"],
            "category": g["category"],
            "views": g["views"],
            "comments": g["comments"],
            "coop": bool(g["has_coop"]),
            "multiplayer": bool(g["has_multiplayer"]),
            "release_date": g["release_date"] or "",
            "img_url": "",
            "poster_url": g["poster_url"] or "",
            "url": g["of_url"] or "",
            "last_updated": g["last_updated"] or "",
            "steam_appid": g["steam_appid"],
            "steam_name": g["steam_name"] or "",
            "rating_pct": pct,
            "review_count": g["review_count"] or 0,
            "review_desc": g["review_desc"] or "",
            "players_estimate": g["players_estimate"] or 0,
            "genres": g["genres"] or "",
            "tags": g["tags"] or "",
            "developer": g["developer"] or "",
            "publisher": g["publisher"] or "",
            "metacritic": g["metacritic_score"] or 0,
            "steam_multiplayer": bool(g["steam_multiplayer"]),
            "steam_coop": bool(g["steam_coop"]),
            "steam_status": steam_status,
        })

    site_path = Path(site_dir)
    site_path.mkdir(exist_ok=True)

    # Download missing preview images, set img_url to local paths
    _download_previews(games, site_dir)

    genres_str = ",".join(GENRE_LIST)
    html = HTML_TEMPLATE.replace("__DATA__", json.dumps(games, ensure_ascii=False))
    html = html.replace("__GENRES__", json.dumps(genres_str))
    with open(site_path / "index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Built {site_path / 'index.html'} ({len(games)} games, {len(html):,} bytes)")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    d = sys.argv[1] if len(sys.argv) > 1 else "site"
    build(d)
