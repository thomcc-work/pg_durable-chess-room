// Exercise the shipped UI's event handlers with deterministic polling and failed browser operations.
const {test} = require("node:test");
const assert = require("node:assert/strict");
const {readFileSync} = require("node:fs");
const {join} = require("node:path");
const vm = require("node:vm");
const source = readFileSync(join(__dirname, "../chess_room/static/room.js"), "utf8");

class Element {
  constructor() {
    this.children = []; this.attributes = {}; this.classList = {toggle() {}};
    this.open = false; this.value = ""; this.loads = 0;
  }
  setAttribute(k, v) { this.attributes[k] = v; }
  getAttribute(k) { return this.attributes[k]; }
  set src(value) { this.attributes.src = value; this.loads++; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; }
  querySelector() { return this.children[0] ??= new Element(); }
  get options() { return this.children; }
  showModal() { this.open = true; }
  close() { this.open = false; }
}
async function board() {
  const ids = {}, el = id => ids[id] ??= new Element();
  const fen = "k7/2P5/1K6/8/8/8/8/8 w - - 0 1";
  const snapshot = {id:1, ply:0, moves:[], legal:["c7c8q","c7c8r"], phase:"human", result:"*",
                    title:"Promotion", engine:"test", held:false, start:fen, fen};
  const memory = new Map();
  const storage = {getItem:k=>memory.get(k) ?? null, setItem:(k,v)=>memory.set(k,v), removeItem:k=>memory.delete(k)};
  const requests = [];
  let poll, requestNumber = 0, reads = 0, loseCreation = true;
  async function fetch(path, options) {
    let value;
    if (options.body) {
      requests.push([path, JSON.parse(options.body)]);
      if (path === "/api/games" && loseCreation) {
        loseCreation = false; throw new Error("lost response");
      }
      value = {id:1, applied:true};
    } else if (path === "/api/games") value = {games:[], engine:"test"};
    else { value = structuredClone(snapshot); reads++; }
    return {ok:true, json:async()=>value};
  }
  await vm.runInNewContext(`(async () => {${source}\n})()`, {
    document:{getElementById:el, createElement:()=>new Element()}, location:{pathname:"/games/1", assign() {}},
    fetch, sessionStorage:storage, Option:Element, crypto:{randomUUID:()=>`id-${++requestNumber}`},
    setTimeout:callback=>{ poll = callback; }
  });
  return {el, snapshot, requests, storage, poll:()=>poll(), reads:()=>reads,
          square:name=>el("squares").children.find(b=>b.getAttribute("aria-label").startsWith(`${name}:`))};
}

test("advancing the board dismisses promotion and even the old choice cannot submit at the new ply", async () => {
  const b = await board();
  b.square("c7").onclick(); b.square("c8").onclick();
  const choice = b.el("choices").children.find(x=>x.textContent==="rook");
  assert.ok(b.el("promotion").open && choice);
  b.snapshot.moves = [{ply:1,san:"Kc6",uci:"b6c6",fen:"k7/2P5/2K5/8/8/8/8/8 b - - 1 1"},
                      {ply:2,san:"Ka7",uci:"a8a7",fen:"8/k1P5/2K5/8/8/8/8/8 w - - 2 2"}];
  b.snapshot.ply = 2; b.snapshot.fen = b.snapshot.moves[1].fen;
  await b.poll();
  assert.equal(b.el("promotion").open, false);
  choice.onclick();
  assert.equal(b.requests.length, 0);
});

test("an SVG failure is retried at an unchanged ply without reloading healthy images", async () => {
  const b = await board(), img = b.el("drawing");
  assert.equal(img.loads, 1); img.onerror();
  await b.poll(); assert.equal(img.loads, 2);
  await b.poll(); assert.equal(img.loads, 2);
});

test("unwritable receipt storage sends no move and leaves the tab polling", async () => {
  const b = await board();
  b.storage.setItem = () => { throw new Error("QuotaExceededError"); };
  b.el("uci").value = "c7c8r";
  b.el("move-form").onsubmit({preventDefault() {}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.match(b.el("notice").textContent, /Move not sent/);
  assert.equal(b.requests.length, 0);
  const before = b.reads();
  await b.poll(); assert.equal(b.reads(), before + 1);
  assert.equal(b.el("uci").disabled, false);
});

test("retrying Play White after a lost reply keeps the UUID until another setup attempt", async () => {
  const b = await board();
  b.el("new").onclick();
  await b.el("create").onclick();
  await b.el("create").onclick();
  assert.equal(b.requests[0][1].request, b.requests[1][1].request);
  b.el("new").onclick();
  await b.el("create").onclick();
  assert.notEqual(b.requests[0][1].request, b.requests[2][1].request);
});
