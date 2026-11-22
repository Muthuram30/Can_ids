const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

function dashboard(){
  const html = fs.readFileSync(path.join(__dirname, '../templates/dashboard.html'), 'utf8');
  const elements = new Map(), requests = [], timers = new Map(), intervals = [];
  let now = 0, timerId = 0;
  const element = id => {
    if (!elements.has(id)) elements.set(id, {
      style: {}, classList: {add(){}, remove(){}}, addEventListener(){},
      setPointerCapture(){}, getBoundingClientRect(){return {left:0,top:0,width:220,height:220};}
    });
    return elements.get(id);
  };
  const context = vm.createContext({
    document: {getElementById:element, body:element('body'), addEventListener(){}},
    window: {addEventListener(){}}, performance: {now:()=>now},
    setTimeout(fn, ms){ const id = ++timerId; timers.set(id, {fn, at:now+ms}); return id; },
    clearTimeout(id){ timers.delete(id); },
    setInterval(fn, ms){ intervals.push({fn,ms}); },
    fetch(url, options){
      if (url !== '/api/joystick') return new Promise(()=>{});
      return new Promise(resolve=>requests.push({body:JSON.parse(options.body), resolve}));
    }
  });
  vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], context);
  return {
    requests, intervals, run:code=>vm.runInContext(code, context),
    tick(time){
      now = time;
      for (const [id,timer] of [...timers]) if (timer.at <= now) {
        timers.delete(id); timer.fn();
      }
    }
  };
}

async function settle(){ for (let i=0; i<6; i++) await Promise.resolve(); }

test('release STOP follows the in-flight movement without a throttle delay', async()=>{
  const d = dashboard();
  d.run('sendJoystick(0, -100)');
  d.run('sendJoystick(100, 0); resetStick()');
  assert.equal(d.requests.length, 1);
  d.requests[0].resolve({status:200});
  await settle();
  assert.equal(d.requests.length, 2);
  assert.deepEqual(d.requests[1].body, {x:0,y:0});
});

test('1000 pointer updates coalesce to at most 20 movement requests per second', async()=>{
  const d = dashboard();
  for (let t=0;t<1000;t++){
    d.tick(t);
    d.run(`sendJoystick(${20+t%80}, -80)`);
    for (const req of d.requests) req.resolve({status:200});
    await settle();
  }
  assert.ok(d.requests.length >= 19 && d.requests.length <= 20, d.requests.length);
  d.tick(1000);
  assert.deepEqual(d.requests.at(-1).body, {x:59,y:80});
});

test('a 403 drops queued movement and keeps it cleared after rearm', async()=>{
  const d = dashboard();
  d.run('sendJoystick(0, -100); sendJoystick(100, 0)');
  d.requests[0].resolve({status:403});
  await settle();
  d.tick(1000);
  d.run('clearBlocked()');
  d.intervals.find(i=>i.ms===200).fn();
  assert.equal(d.requests.length, 1);
  assert.equal(d.run('joyX === 0 && joyY === 0 && !dragging'), true);
});

test('held joystick refresh continues without pointer movement', async()=>{
  const d = dashboard();
  d.run('dragging = true; sendJoystick(0, -100)');
  d.requests[0].resolve({status:200});
  await settle();
  d.tick(200);
  d.intervals.find(i=>i.ms===200).fn();
  assert.deepEqual(d.requests[1].body, {x:0,y:100});
});
