"use strict";
const $ = id => document.getElementById(id);
const state = {params: new URLSearchParams(), offset: 0, total: 0, game: null, frame: 0, flipped: false, sequence: 0, detailSequence: 0, moveSequence: 0, loading: false, pending: false, inspectedPly: null};
const names = {original: "Original", v1: "V1 · Small NN", v2: "V2 · Large NN", v3: "V3 · two-stage", v4: "V4 · Small at leaves", unknown: "Unknown", mixed: "Mixed / incomplete"};
const versionName = value => names[value] || (/^v[1-9][0-9]*$/.test(value || "") ? value.toUpperCase() : "Unknown");
const number = value => value == null ? "—" : Number(value).toLocaleString(undefined, {maximumFractionDigits: 1});
const duration = value => value == null ? "—" : value >= 1000 ? `${number(value / 1000)} s` : `${number(value)} ms`;
const dateText = value => value == null ? "Date unavailable" : new Intl.DateTimeFormat("en-GB", {timeZone: "Asia/Dubai", dateStyle: "medium", timeStyle: "short"}).format(new Date(value));
function element(tag, className = "", text = "") { const node = document.createElement(tag); if (className) node.className = className; if (text !== "") node.textContent = text; return node; }
function cell(row, text, className = "") { const node = element("td", className, text); row.append(node); return node; }
function tag(text, className = "") { return element("span", `tag ${className}`, text); }
function clear(node) { node.replaceChildren(); }
async function api(path) { const response = await fetch(path, {cache: "no-store"}); const body = await response.json(); if (!response.ok) throw new Error(body.error || `Request failed (${response.status})`); return body; }
function showError(error, target = "error") { $(target).hidden = !error; $(target).textContent = error ? error.message || String(error) : ""; }
function svgNode(tagName, attributes = {}, text = "") { const node = document.createElementNS("http://www.w3.org/2000/svg", tagName); Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value))); if (text) node.textContent = text; return node; }
function chartEmpty(target, message) { clear(target); target.append(element("p", "quiet", message)); }
function resultChart(days) {
  const target = $("results-chart"); clear(target);
  if (!days.length) return chartEmpty(target, "Your daily results will appear after games are recorded.");
  // Keep recent dates readable; summary cards and comparison still include all filtered games.
  const data = days.slice(-30), width = 650, height = 165, left = 30, bottom = 130, available = 605;
  const chart = svgNode("svg", {viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": "Daily results for the most recent 30 recorded dates"});
  const max = Math.max(1, ...data.map(d => d.win + d.draw + d.loss + d.pending + d.aborted));
  chart.append(svgNode("line", {x1: left, x2: 640, y1: bottom, y2: bottom}));
  chart.append(svgNode("text", {x: 0, y: 20}, String(max)), svgNode("text", {x: 8, y: bottom}, "0"));
  const unit = available / data.length;
  data.forEach((d, index) => {
    let y = bottom;
    [["win", "var(--win)"], ["draw", "var(--draw)"], ["loss", "var(--loss)"], ["other", "var(--pending)"]].forEach(([key, color]) => {
      const count = key === "other" ? d.pending + d.aborted : d[key], barHeight = count / max * 110;
      y -= barHeight;
      if (count) { const bar = svgNode("rect", {x: left + index * unit + 3, y, width: Math.max(2, unit - 7), height: barHeight, rx: 2, fill: color}); bar.append(svgNode("title", {}, `${d.date}: ${count} ${key}`)); chart.append(bar); }
    });
  });
  chart.append(svgNode("text", {x: left, y: 154}, data[0].date), svgNode("text", {x: 640, y: 154, "text-anchor": "end"}, data.at(-1).date));
  target.append(chart);
}
function timelineChart(moves) {
  const target = $("time-chart"), data = moves.filter(m => m.engine && m.engine.t_total_ms != null); clear(target);
  if (!data.length) return chartEmpty(target, "No engine timing has been recorded for this game.");
  const chart = svgNode("svg", {viewBox: "0 0 520 175", role: "img", "aria-label": "Recorded engine time by ply"});
  const max = Math.max(1, ...data.map(m => m.engine.t_total_ms)), last = Math.max(1, ...data.map(m => m.ply));
  chart.append(svgNode("line", {x1: 43, x2: 505, y1: 138, y2: 138}));
  chart.append(svgNode("text", {x: 1, y: 20}, duration(max)), svgNode("text", {x: 43, y: 160}, "Ply 1"), svgNode("text", {x: 505, y: 160, "text-anchor": "end"}, `Ply ${last}`));
  const points = data.map(m => `${43 + (m.ply - 1) / Math.max(1, last - 1) * 462},${138 - m.engine.t_total_ms / max * 116}`).join(" ");
  chart.append(svgNode("polyline", {points, fill: "none", stroke: "var(--accent)", "stroke-width": 2}));
  data.forEach(m => { const dot = svgNode("circle", {cx: 43 + (m.ply - 1) / Math.max(1, last - 1) * 462, cy: 138 - m.engine.t_total_ms / max * 116, r: 3, fill: "var(--accent)"}); dot.append(svgNode("title", {}, `Ply ${m.ply}: ${duration(m.engine.t_total_ms)}`)); chart.append(dot); });
  target.append(chart);
}
function renderSummary(data) {
  $("total-games").textContent = number(data.games); $("synced-count").textContent = `${number(data.synced_games)} with Lichess game data · ${number(data.games - data.synced_games)} engine-only`;
  $("score").textContent = data.score_pct == null ? "—" : `${number(data.score_pct)}%`;
  $("outcome-line").textContent = `${number(data.outcomes.win)} wins · ${number(data.outcomes.draw)} draws · ${number(data.outcomes.loss)} losses / ${number(data.decided)} decided`;
  $("engine-moves").textContent = number(data.engine_moves); $("move-average").textContent = data.avg_move_ms == null ? "No timing data recorded yet" : `${duration(data.avg_move_ms)} mean recorded engine move`;
  clear($("versions")); $("versions-empty").hidden = data.versions.length > 0;
  data.versions.forEach(v => { const row = element("tr"); cell(row, versionName(v.kernel_variant), "version"); cell(row, number(v.games)); cell(row, `${v.wins} / ${v.draws} / ${v.losses}`); cell(row, v.score_pct == null ? "—" : `${number(v.score_pct)}%`); cell(row, `${v.pending} / ${v.aborted}`); cell(row, duration(v.avg_move_ms)); cell(row, number(v.max_depth)); const builds = cell(row, String(v.builds.length)); builds.title = v.builds.join("\n") || "No build stamp recorded"; $("versions").append(row); });
  const kernelSelect = $("filters").elements.kernel, kernelValue = kernelSelect.value;
  const variants = new Set(["original", "v1", "v2", "v3", "v4", ...data.kernel_variants, "unknown", "mixed"]);
  kernelSelect.replaceChildren(new Option("All versions", "")); [...variants].forEach(v => kernelSelect.add(new Option(versionName(v), v))); kernelSelect.value = kernelValue;
  const speedValue = $("speed").value; $("speed").replaceChildren(new Option("All speeds", "")); data.speeds.forEach(speed => $("speed").add(new Option(speed, speed))); $("speed").value = speedValue;
  resultChart(data.days);
}
function renderGames(data) {
  state.total = data.total; clear($("games")); $("game-count").textContent = number(data.total); $("games-empty").hidden = data.games.length !== 0; $("games-table").hidden = data.games.length === 0;
  data.games.forEach(g => {
    const row = element("tr"), first = cell(row, ""), link = element("button", "game-link", g.game_id); link.addEventListener("click", () => openGame(g.game_id)); first.append(link, element("small", "", dateText(g.started_at)));
    const opponent = cell(row, g.opponent_name || "Opponent not recorded"); opponent.append(element("small", "", `${g.opponent_title || g.opponent_kind || "Unknown kind"}${g.opponent_rating == null ? "" : ` · ${g.opponent_rating}`}`));
    cell(row, "").append(tag(g.result || "Not synced", g.result || "pending")); cell(row, `${g.time_control || g.speed || "Unknown"} · ${g.our_color || "?"}`); cell(row, versionName(g.kernel_variant), "version"); cell(row, number(g.engine_moves)); cell(row, duration(g.avg_move_ms)); cell(row, number(g.max_depth)); $("games").append(row);
  });
  $("page-status").textContent = data.total ? `${number(state.offset + 1)}–${number(state.offset + data.games.length)} of ${number(data.total)} games` : "No games in this view";
  $("previous").disabled = state.offset === 0; $("next").disabled = state.offset + data.games.length >= data.total;
}
async function load() {
  if (state.loading) { state.pending = true; return; }
  state.loading = true;
  const sequence = ++state.sequence; $("refresh").disabled = true; showError(null);
  const params = new URLSearchParams(state.params), gamesParams = new URLSearchParams(params); gamesParams.set("limit", "50"); gamesParams.set("offset", String(state.offset));
  try { const [summary, games] = await Promise.all([api(`/api/summary?${params}`), api(`/api/games?${gamesParams}`)]); if (sequence !== state.sequence) return; renderSummary(summary); renderGames(games); $("updated").textContent = `Completed moves · refreshed ${new Intl.DateTimeFormat("en-GB", {timeZone: "Asia/Dubai", timeStyle: "medium"}).format(new Date())} Dubai time`; if ($("game-dialog").open && state.game) await openGame(state.game.game.game_id, {refresh: true}); }
  catch (error) { if (sequence === state.sequence) showError(error); }
  finally { state.loading = false; if (sequence === state.sequence) $("refresh").disabled = false; if (state.pending) { state.pending = false; queueMicrotask(load); } }
}
const pieces = {p: "♟", n: "♞", b: "♝", r: "♜", q: "♛", k: "♚", P: "♙", N: "♘", B: "♗", R: "♖", Q: "♕", K: "♔"};
function renderBoard() {
  const frames = state.game?.replay.frames || [], board = $("board"); clear(board); board.classList.toggle("board-unavailable", !frames.length);
  $("replay-range").disabled = !frames.length; ["first", "back", "forward", "last", "flip"].forEach(id => $(id).disabled = !frames.length);
  if (!frames.length) { board.append(element("p", "", "Board history is not available yet.")); $("board-ply").textContent = "No replay"; return; }
  const frame = frames[state.frame], cells = [];
  frame.fen.split(" ")[0].split("/").forEach(rank => { for (const code of rank) { if (/\d/.test(code)) cells.push(...Array(Number(code)).fill("")); else cells.push(code); } });
  const order = Array.from({length: 64}, (_, i) => state.flipped ? 63 - i : i);
  order.forEach(index => { const code = cells[index], row = Math.floor(index / 8), file = index % 8, square = element("div", `square ${(row + file) % 2 ? "dark" : ""} ${code && code === code.toUpperCase() ? "white-piece" : ""}`, pieces[code] || ""); const coordinate = `${"abcdefgh"[file]}${8 - row}`; square.setAttribute("aria-label", `${coordinate}${code ? ` ${code}` : " empty"}`); if ((!state.flipped && row === 7) || (state.flipped && row === 0)) square.append(element("small", "", coordinate)); board.append(square); });
  $("board-ply").textContent = frame.ply ? `Ply ${frame.ply} · ${frame.move}` : "Starting position"; $("replay-range").max = String(frames.length - 1); $("replay-range").value = String(state.frame);
  document.querySelectorAll("#moves tr").forEach(row => row.classList.toggle("selected", Number(row.dataset.ply) === frame.ply));
}
function table(headers, rows) { const wrap = element("div", "table-wrap"), tbl = element("table"), head = element("thead"), hr = element("tr"), body = element("tbody"); headers.forEach(h => hr.append(element("th", "", h))); head.append(hr); rows.forEach(values => { const tr = element("tr"); values.forEach(v => cell(tr, v)); body.append(tr); }); tbl.append(head, body); wrap.append(tbl); return wrap; }
async function inspectMove(ply) {
  if (!state.game) return; state.inspectedPly = ply; const sequence = ++state.moveSequence, gameID = state.game.game.game_id, target = $("move-inspector"); clear(target); target.append(element("h3", "", `Inside the search · ply ${ply}`), element("p", "quiet", "Loading recorded worker details…"));
  try { const detail = await api(`/api/game/${encodeURIComponent(gameID)}/move/${ply}`); if (sequence !== state.moveSequence || state.game?.game.game_id !== gameID) return; clear(target); target.append(element("h3", "", `Inside the search · ply ${ply}`));
    if (!detail.engine_move) { target.append(element("p", "quiet", "No engine search was recorded for this ply. It may be the opponent’s move or a game imported without engine telemetry.")); return; }
    const summary = element("div", "worker-summary"); summary.append(element("span", "", `Path: ${detail.engine_move.path}`), element("span", "", `Total: ${duration(detail.engine_move.t_total_ms)}`), element("span", "", `Build: ${detail.engine_move.engine_version || "Unknown"}`)); target.append(summary);
    if (!detail.workers.length) target.append(element("p", "quiet", "No Kernel workers ran for this recorded move. Check the decision path above."));
    else target.append(table(["Worker", "Status", "Depth", "Search", "Total nodes", "Best move", "Score"], detail.workers.map(w => [String(w.worker), w.status, number(w.depth), duration(w.search_ms), number(w.total_nodes), w.best_move || "—", number(w.best_score)])));
    detail.workers.forEach(worker => {
      const depths = element("details");
      depths.append(element("summary", "", `Worker ${worker.worker} - depth history${worker.error ? ` - ${worker.error}` : ""}`));
      const assigned = worker.root_moves || [], omitted = worker.unsearched_root_moves || [];
      depths.append(element("p", "quiet", `Assigned root moves: ${assigned.join(", ") || "Not recorded"}`));
      depths.append(element("p", "quiet", `Not searched at the final completed depth: ${omitted.join(", ") || "None listed"}`));
      if (worker.pruned != null) depths.append(element("p", "quiet", `Recorded alpha-beta cutoffs: ${number(worker.pruned)}`));
      if (worker.depths.length) depths.append(table(["Depth", "Completed", "Time", "Nodes", "Best", "Score"], worker.depths.map(d => [String(d.depth), d.completed ? "Yes" : "Clock cut", duration(d.ms), number(d.nodes), d.best_move || "-", number(d.score)])));
      else depths.append(element("p", "quiet", "No depth history recorded."));
      target.append(depths);
    });
    if (detail.candidates.length) { const candidates = element("details"); candidates.append(element("summary", "", `${detail.candidates.length} recorded root candidates`), table(["Move", "Worker", "Depth", "Kernel score", "Exact / bound"], detail.candidates.map(c => [c.move, String(c.worker), number(c.depth), number(c.score), c.exact === 1 ? "Exact at searched depth" : c.exact === 0 ? "Upper bound" : "Unknown"]))); target.append(candidates); }
  } catch (error) { if (sequence === state.moveSequence) { clear(target); target.append(element("p", "quiet", error.message)); } }
}
function selectPly(ply) { const frames = state.game.replay.frames, index = frames.findIndex(f => f.ply === ply); if (index >= 0) state.frame = index; renderBoard(); inspectMove(ply); }
async function openGame(gameID, {refresh = false} = {}) {
  const previousPly = state.game?.replay.frames[state.frame]?.ply ?? 0;
  const sequence = ++state.detailSequence; ++state.moveSequence; showError(null, "detail-error"); if (!refresh) { state.game = null; state.inspectedPly = null; $("follow-latest").checked = false; $("detail-content").hidden = true; $("detail-title").textContent = `Loading ${gameID}…`; if (!$("game-dialog").open) $("game-dialog").showModal(); }
  try { const data = await api(`/api/game/${encodeURIComponent(gameID)}`); if (sequence !== state.detailSequence) return; const retainedPly = refresh ? state.game?.replay.frames[state.frame]?.ply ?? previousPly : 0, retainedFlip = state.flipped, retainedInspection = state.inspectedPly; state.game = data; state.frame = refresh ? Math.max(0, data.replay.frames.findIndex(frame => frame.ply === retainedPly)) : 0; if (refresh && $("follow-latest").checked) state.frame = Math.max(0, data.replay.frames.length - 1); state.flipped = refresh ? retainedFlip : data.game.our_color === "black"; $("detail-title").textContent = `${data.game.game_id} · ${data.game.opponent_name || "Opponent unknown"}`;
    clear($("detail-meta")); [data.game.result || "Result not synced", versionName(data.game.kernel_variant), data.game.time_control || data.game.speed || "Clock unknown", dateText(data.game.started_at)].forEach(text => $("detail-meta").append(tag(text))); $("replay-message").textContent = data.replay.message;
    clear($("game-facts")); [["Recorded engine moves", number(data.game.engine_moves)], ["Mean move time", duration(data.game.avg_move_ms)], ["Deepest worker", number(data.game.max_depth)], ["Worker timeouts / failures", `${number(data.game.worker_timeouts)} / ${number(data.game.worker_failures)}`]].forEach(([label, value]) => { const fact = element("div", "fact"); fact.append(element("small", "", label), element("strong", "", value)); $("game-facts").append(fact); });
    $("build-metadata").textContent = [`Game build: ${data.game.engine_version || "Unknown"}`, ...data.recorded_move_builds.map(v => `Move build: ${v}`)].join("\n"); clear($("moves"));
    data.moves.forEach(move => { const row = element("tr"); row.dataset.ply = String(move.ply); cell(row, String(move.ply)); const button = element("button", "game-link", move.lichess?.san || move.lichess?.uci || move.engine?.best_move || "—"); button.addEventListener("click", () => selectPly(move.ply)); cell(row, "").append(button); cell(row, move.engine?.path || (move.lichess?.by_us === 0 ? "Opponent" : "No engine telemetry")); cell(row, duration(move.engine?.t_total_ms)); cell(row, number(move.engine?.total_nodes)); cell(row, number(move.engine?.max_depth ?? move.engine?.stockfish_depth)); cell(row, number(move.engine?.workers)); cell(row, number(move.engine?.best_score)); $("moves").append(row); });
    if (!data.moves.length) { const row = element("tr"); const c = cell(row, "No move rows recorded yet."); c.colSpan = 8; $("moves").append(row); }
    clear($("move-inspector")); $("move-inspector").append(element("h3", "", "Inside the search"), element("p", "quiet", "Select an engine move above to inspect its workers, depths and candidate moves.")); $("events-title").textContent = `Game events (${data.events.length})`; clear($("events")); data.events.forEach(event => { const node = element("div", "event"); node.append(element("strong", "", `${event.level} · ${event.source} · ${event.ply == null ? "game" : `ply ${event.ply}`}`), element("div", "", event.message)); $("events").append(node); }); if (!data.events.length) $("events").append(element("p", "quiet", "No recorded events for this game.")); renderBoard(); timelineChart(data.moves); $("detail-content").hidden = false; if (refresh && retainedInspection != null) await inspectMove(retainedInspection);
  } catch (error) { if (sequence === state.detailSequence) { $("detail-title").textContent = "Game unavailable"; showError(error, "detail-error"); } }
}
$("filters").addEventListener("submit", event => { event.preventDefault(); state.params = new URLSearchParams(); for (const [key, value] of new FormData(event.target)) if (value) state.params.set(key, value); state.offset = 0; load(); });
$("filters").addEventListener("reset", () => { state.params = new URLSearchParams(); state.offset = 0; load(); });
$("refresh").addEventListener("click", load); $("previous").addEventListener("click", () => { state.offset = Math.max(0, state.offset - 50); load(); }); $("next").addEventListener("click", () => { state.offset += 50; load(); });
$("close-detail").addEventListener("click", () => { ++state.detailSequence; ++state.moveSequence; $("game-dialog").close(); });
$("game-dialog").addEventListener("cancel", () => { ++state.detailSequence; ++state.moveSequence; });
$("first").addEventListener("click", () => { state.frame = 0; renderBoard(); }); $("last").addEventListener("click", () => { state.frame = state.game.replay.frames.length - 1; renderBoard(); }); $("back").addEventListener("click", () => { state.frame = Math.max(0, state.frame - 1); renderBoard(); }); $("forward").addEventListener("click", () => { state.frame = Math.min(state.game.replay.frames.length - 1, state.frame + 1); renderBoard(); }); $("flip").addEventListener("click", () => { state.flipped = !state.flipped; renderBoard(); }); $("replay-range").addEventListener("input", event => { state.frame = Number(event.target.value); renderBoard(); });
try { if (localStorage.getItem("mrbits-theme") === "light") document.documentElement.dataset.theme = "light"; } catch {}
$("theme").addEventListener("click", () => { const next = document.documentElement.dataset.theme === "light" ? "dark" : "light"; document.documentElement.dataset.theme = next; try { localStorage.setItem("mrbits-theme", next); } catch {} });
setInterval(() => { if ($("auto-refresh").checked && !document.hidden && !state.loading) load(); }, 5000);
document.addEventListener("visibilitychange", () => { if (!document.hidden && $("auto-refresh").checked && !state.loading) load(); });
$("follow-latest").addEventListener("change", () => { if ($("follow-latest").checked && state.game) { state.frame = Math.max(0, state.game.replay.frames.length - 1); renderBoard(); } });
load();
