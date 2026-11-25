const $ = id => document.getElementById(id);
const gameId = location.pathname.match(/^\/games\/(\d+)$/)?.[1];
const base = `/api/games/${gameId}`;
const names = {p:"pawn", n:"knight", b:"bishop", r:"rook", q:"queen", k:"king"};
const squares = new Map();
let state, selected = null, viewed = null, busy = false, generation = 0, offline = false;
let historyKey = "", movePly = null;
const pendingKey = `chess-room:${gameId}:pending`;

async function api(path, body) {
  const options = body === undefined ? {} : {
    method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)
  };
  const response = await fetch(path, options);
  const json = await response.json();
  if (!response.ok) {
    const error = new Error(json.error || `HTTP ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return json;
}
function message(text) { $("notice").textContent = text; }
function pieces(fen) {
  const result = new Map();
  fen.split(" ")[0].split("/").forEach((rank, i) => {
    let file = 0;
    for (const ch of rank) {
      if (/\d/.test(ch)) { file += Number(ch); continue; }
      result.set("abcdefgh"[file++] + (8-i), `${ch === ch.toUpperCase() ? "White" : "Black"} ${names[ch.toLowerCase()]}`);
    }
  });
  return result;
}
for (let rank=8; rank>=1; rank--) for (const file of "abcdefgh") {
  const sq = file + rank, button = document.createElement("button");
  button.className = "square"; button.tabIndex = sq === "e2" ? 0 : -1;
  button.disabled = !gameId;
  button.setAttribute("aria-label", sq); button.setAttribute("aria-pressed", "false");
  button.onclick = () => select(sq);
  button.onkeydown = e => {
    const offsets = {ArrowLeft:-1, ArrowRight:1, ArrowUp:-8, ArrowDown:8};
    if (!(e.key in offsets)) return;
    e.preventDefault();
    const cells = [...squares.values()], next = cells[cells.indexOf(button) + offsets[e.key]];
    if (next) next.focus();
  };
  button.onfocus = () => { for (const b of squares.values()) b.tabIndex = b === button ? 0 : -1; };
  squares.set(sq, button); $("squares").append(button);
}
function canMove() { return state && state.phase === "human" && viewed === null && !busy && !offline && !sessionStorage.getItem(pendingKey); }
function select(sq) {
  if (!canMove()) return;
  const options = selected ? state.legal.filter(m => m.startsWith(selected + sq)) : [];
  if (options.length === 1) { sendMove(options[0]); return; }
  if (options.length > 1) {
    $("choices").replaceChildren(...options.map(m => {
      const b = document.createElement("button"); b.textContent = names[m[4]];
      b.onclick = () => { $("promotion").close(); sendMove(m); }; return b;
    }));
    $("promotion").showModal(); return;
  }
  selected = selected !== sq && state.legal.some(m => m.startsWith(sq)) ? sq : null;
  render();
}
function drawHistory() {
  const key = `${state.ply}/${viewed}`;
  if (historyKey === key) return;
  historyKey = key;
  const list = $("history");
  list.replaceChildren();
  if (!state.moves.length) { list.textContent = "White to make the first move."; return; }
  let row;
  for (const move of state.moves) {
    if (move.ply % 2) {
      row = document.createElement("div"); row.className = "move-row";
      const no = document.createElement("span"); no.textContent = `${(move.ply+1)/2}.`; row.append(no); list.append(row);
    }
    const b = document.createElement("button"); b.textContent = move.san;
    b.setAttribute("aria-label", `View ply ${move.ply}: ${move.san}`);
    b.setAttribute("aria-current", String((viewed ?? state.ply) === move.ply));
    b.onclick = () => { viewed = move.ply === state.ply ? null : move.ply; selected = null; render(); };
    row.append(b);
  }
  if (viewed === null) list.scrollTop = list.scrollHeight;
}
function render() {
  if (!state) return;
  const ply = viewed ?? state.ply;
  const fen = ply ? state.moves[ply-1].fen : state.start;
  const image = `${base}/board.svg?ply=${ply}`;
  if ($("drawing").getAttribute("src") !== image) $("drawing").src = image;
  const placement = pieces(fen);
  for (const [sq,b] of squares) {
    b.setAttribute("aria-label", `${sq}: ${placement.get(sq) || "empty"}`);
    b.setAttribute("aria-pressed", String(selected === sq));
    b.setAttribute("aria-disabled", String(!canMove()));
    b.classList.toggle("selected", selected === sq);
    b.classList.toggle("target", Boolean(selected && state.legal.some(m => m.startsWith(selected+sq))));
  }
  $("engine").textContent = state.engine; $("title").textContent = `Game No. ${state.id}`;
  $("turn").textContent = offline ? "Reconnecting…" : viewed !== null ? `Reviewing ply ${ply}` :
    state.issue ? "Game paused" : state.result !== "*" ? `${state.result} · ${state.reason}` :
    state.phase === "human" ? (state.check ? "You are in check." : "Your move.") :
    state.held && state.phase !== "human" ? "Engine reply held." :
    state.phase === "submitted" ? "Move recorded." : "Stockfish to move.";
  $("summary").textContent = viewed !== null ? "You are looking at an earlier position." :
    state.issue || (state.result !== "*" ? "The final position and scoresheet are saved." :
    state.held ? "Stockfish is on hold. Resume it in Durable turn receipt when you are ready." :
    state.phase === "human" ? "Select a white piece, then a highlighted square." :
    "Your move is saved. The game will continue from this position.");
  $("hint").textContent = `${state.title} · ${viewed === null ? "Live board" : "Review"} · Ply ${ply}`;
  $("live").hidden = viewed === null;
  $("move-form").hidden = state.result !== "*" || viewed !== null;
  $("uci").disabled = !canMove(); $("move-form").querySelector("button").disabled = !canMove();
  $("receipt").hidden = false; $("fen").textContent = state.fen; $("instance").textContent = state.instance;
  const last = state.moves.findLast(m => m.request);
  $("key").textContent = last?.request || "No White move yet.";
  $("retry").disabled = busy || offline || !(last || sessionStorage.getItem(pendingKey));
  $("pending").hidden = !sessionStorage.getItem(pendingKey) || busy;
  $("pending").disabled = offline;
  $("hold").textContent = state.held ? "Resume engine" : "Hold engine reply";
  $("hold").disabled = busy || offline || state.result !== "*" || viewed !== null;
  const saved = [...$("saved").options].find(o => o.value === String(state.id));
  if (saved) saved.textContent = optionLabel(state);
  $("resign").disabled = busy || offline || state.result !== "*" || viewed !== null;
  $("pgn").hidden = false; $("pgn").href = `${base}/score.pgn`;
  drawHistory();
}
async function refresh() {
  if (!gameId || busy) return;
  const ticket = ++generation;
  try {
    const fresh = await api(base);
    if (ticket !== generation) return;
    if (state?.ply !== fresh.ply) { selected = null; $("uci").value = ""; }
    state = fresh;
    const pending = sessionStorage.getItem(pendingKey);
    if (pending && state.moves.some(m => m.request === JSON.parse(pending).request)) {
      sessionStorage.removeItem(pendingKey);
      message("The saved scoresheet confirms your move.");
    }
    if (offline) message("Reconnected to the saved board.");
    offline = false; render();
  } catch (e) {
    if (ticket !== generation) return;
    offline = true; message(e.message); render();
  }
}
async function postMove(command) {
  if (busy) return;
  busy = true; ++generation; selected = null;
  sessionStorage.setItem(pendingKey, JSON.stringify(command));
  render();
  try {
    const receipt = await api(`${base}/move`, command);
    sessionStorage.removeItem(pendingKey);
    message(receipt.applied ? `Recorded ${command.uci}.` : `Duplicate acknowledged: ${command.uci} was not applied again.`);
  } catch (e) {
    // Only discard a request that was definitively rejected. A lost HTTP reply is ambiguous.
    if (e.status === 400 || e.status === 409) sessionStorage.removeItem(pendingKey);
    message(`${e.message}${!e.status || e.status === 503 ? " Use Resend last move to retry the same request." : ""}`);
  } finally { busy = false; await refresh(); }
}
function sendMove(uci) {
  if (!canMove()) return;
  if (!state.legal.includes(uci)) { message("That is not a legal move in this position."); return; }
  postMove({ply:state.ply, uci, request:crypto.randomUUID()});
}
$("move-form").onsubmit = e => { e.preventDefault(); sendMove($("uci").value.trim()); };
$("cancel-promotion").onclick = () => $("promotion").close();
$("live").onclick = () => { viewed = null; render(); };
$("retry").onclick = () => {
  const pending = sessionStorage.getItem(pendingKey);
  if (pending) { postMove(JSON.parse(pending)); return; }
  const last = state.moves.findLast(m => m.request);
  if (last) postMove({ply:last.ply-1, uci:last.uci, request:last.request});
};
$("pending").onclick = () => $("retry").click();
$("hold").onclick = async () => {
  const paused = !state.held;
  try { await api(`${base}/hold`, {paused}); message(paused ? "Engine hold saved." : "Engine resumed."); }
  catch(e) { message(e.message); }
  await refresh();
};
$("resign").onclick = () => { movePly = state.ply; $("confirm-resign").showModal(); };
$("do-resign").onclick = async () => {
  $("confirm-resign").close();
  try { await api(`${base}/resign`, {ply:movePly}); } catch(e) { message(e.message); }
  await refresh();
};
let creation = null;
$("new").onclick = () => { creation = null; $("setup-error").textContent = ""; $("setup").showModal(); };
$("create").onclick = async () => {
  $("create").disabled = true;
  const preset = $("preset").value;
  if (!creation || creation.preset !== preset) creation = {preset, request:crypto.randomUUID()};
  try { const {id} = await api("/api/games", creation); location.assign(`/games/${id}`); }
  catch(e) { $("setup-error").textContent = e.message; $("create").disabled = false; }
};
$("saved").onchange = () => { if ($("saved").value) location.assign(`/games/${$("saved").value}`); };
function optionLabel(g) { return `#${g.id} · ${g.title} · ${g.result === "*" ? `ply ${g.ply}` : g.result}`; }
async function lobby() {
  try {
    const catalog = await api("/api/games");
    $("engine").textContent = catalog.engine;
    $("saved").replaceChildren(new Option("Choose a board…", ""),
      ...catalog.games.map(g => new Option(optionLabel(g), String(g.id))));
    if (gameId) $("saved").value = gameId;
  } catch(e) { message(e.message); }
}
$("saved").onfocus = lobby;
await lobby();
if (gameId) {
  await refresh();
  async function poll() { await refresh(); setTimeout(poll, 900); }
  setTimeout(poll, 900);
}
