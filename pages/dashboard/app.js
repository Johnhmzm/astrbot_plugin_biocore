(() => {
  "use strict";
  try{ window.__diagLog && window.__diagLog("init:0 loaded"); }catch(e){}
  // ---- in-page error display (iframe-friendly; no console access needed) ----
  function showDiag(msg){
    try{ if(window.__diagError){ window.__diagError(msg); return; } }catch(e){}
    try{
      var el=document.getElementById('biocoreDiag');
      if(!el){ el=document.createElement('div'); el.id='biocoreDiag';
        el.style.cssText='position:fixed;left:8px;bottom:8px;right:8px;z-index:9999;background:#5a1a1a;color:#fff;font:12px/1.4 monospace;padding:6px 8px;border-radius:4px;white-space:pre-wrap;max-height:30vh;overflow:auto';
        document.body.appendChild(el); }
      el.textContent='JS 错误：'+msg;
    }catch(_){}
  }
  window.addEventListener('error', function(e){ window.__biocoreLastError=(e&&e.message||'')+' @ '+(e&&e.filename||'')+':'+(e&&e.lineno||''); showDiag(window.__biocoreLastError); });
  window.addEventListener('unhandledrejection', function(e){ var r=e&&e.reason; window.__biocoreLastError='promise: '+(r&&(r.stack||r.message)||r); showDiag(window.__biocoreLastError); });

  const $ = (id) => document.getElementById(id);
  // Safe DOM setters: merged/removed switches must never throw during renders.
  function setChecked(id, val){ const el=$(id); if(el){ el.checked = !!val; } }
  function setText(id, val){ const el=$(id); if(el){ el.textContent = String(val); } }
  function setVal(id, val){ const el=$(id); if(el){ el.value = String(val); } }
  let bridge = null;
  // P2: remote dashboard admin token (matches plugin config data_admin_token).
  function _adminHeaders(){
    try{ const t=localStorage.getItem("biocore_admin_token")||"";
      return t ? {"X-BioCore-Admin":t} : {}; }catch(e){ return {}; }
  }
  function _adminToken(){ try{ return localStorage.getItem("biocore_admin_token")||""; }catch(e){ return ""; } }
  async function _adminApiPost(path, body){
    if(!bridge) throw new Error("未连接 AstrBot 页面桥");
    // Host bridge apiPost only accepts (path, body): token goes in the body;
    // header is kept for servers that do read it.
    const payload=Object.assign({}, body||{});
    const t=_adminToken();
    if(t) payload.admin_token=t;
    return bridge.apiPost(path, payload, {headers:_adminHeaders()});
  }
  const demo = {
    enabled: true, inject_intent: true, proactive_reply: false, memory_dedup_embedding: false, persona_loaded: true,
    memory: { entries: 42, sessions: 3 },
    profile: { O:.82,C:.38,E:.93,A:.70,N:.52,stress_reactivity:.72,recovery_rate:.78,social_baseline:.88,energy_baseline:.86,curiosity_baseline:.84,safety_baseline:.30,baseline_v:.62,baseline_a:.82 },
    self_model: { who_am_i:"一个会持续受聊天影响的角色", narrative:"对方记得随口说过的话，也开始愿意承认自己会担心。", version:7,
      _history:[
        {ts:1793000000, who_am_i:"一个会持续受聊天影响的角色", narrative:"对方承诺以后先询问意愿。"},
        {ts:1793000600, who_am_i:"一个会持续受聊天影响的角色", narrative:"开始愿意承认自己也会担心。"},
        {ts:1793001200, who_am_i:"一个会持续受聊天影响的角色", narrative:"被认真问一句，就能安心很多。"}
      ] },
    cores: [{ key:"demo:session", snapshot:{ v:.42,a:.66,d:.52,social:.61,stress:.24,energy:.81,trust:.57,ticks:18,
      history:[
        {ts:1793000000,emotion:"neutral",intensity:.22},
        {ts:1793000300,emotion:"joy",intensity:.68},
        {ts:1793000600,emotion:"joy",intensity:.85},
        {ts:1793000900,emotion:"trust",intensity:.54},
        {ts:1793001200,emotion:"neutral",intensity:.30},
        {ts:1793001500,emotion:"sadness",intensity:.62},
        {ts:1793001800,emotion:"fear",intensity:.48},
        {ts:1793002100,emotion:"joy",intensity:.76}
      ],
      noise:{stress:.08,energy:-.04,social:.03,attention:.01,valence:.05}, echo:.18, echo_trace:.23,
      ripple:{upper:.48,lower:.12,overlap:.11,energy:.30}, spiking:{rate:.061,variance:.021,ei:.37},
      core_self:"会持续受聊天影响的角色", narrative_self:"对方记得随口说过的话，也开始承认自己会担心。",
      self_timeline:{ past:["对方的承诺","未说出口的犹豫"], present:"被认真问一句，就能安心很多。", future:["和重要的人保持亲近","不被当成工具","保持情绪稳定"] },
      reflection_tree:{ count:2, roots:[{ts:1793001000, insight:"被认真询问意愿，会更愿意承担任务。", emotion:"joy", children:[{ts:1793001300, insight:"随口说的话也会被记住。", emotion:"joy", children:[]}]}] },
      spectrum_probs:[{key:"joy",name:"快乐",p:.62},{key:"contentment",name:"满足",p:.23},{key:"amusement",name:"好笑",p:.15}],
      sec:{relevance:.72,implication:.41,coping_potential:.58,normative:.66},
      spectrum_calibration:{samples:18,families:2,calibrated:3},
      circadian_alertness:.62, allostatic_load:.18, boundary_pressure:.12, refusal_readiness:.08,
      homeostasis:{L_int:.14, readiness:.71, tick:42, setpoint_ticks:9,
        body:{energy:.74,fatigue:.22,hydration:.68,warmth:.63},
        drives:{energy:.72,social:.66,safety:.58,curiosity:.61},
        set_points:{energy:.68,social:.60,safety:.60,curiosity:.55},
        need_pyramid:{score:.19,dominant:"belonging",deficits:{physiological:.10,safety:.12,belonging:.26,esteem:.14,self_actualization:.20}},
        interoception:{signal:.67,label:"steady",expression_hint:"normal"},
        action:{mode:"engage",reason:"ready",strength:.64}},
      goals:[{key:"relationship",name:"和重要的人保持亲近",horizon:"long",progress:.5}], goal_conflict:[], autobiography:[{ts:1793001000,title:"对方的承诺",meaning:"确认自己没有被当成工具"}],
      regulation_stats:{reappraise:{uses:6,success:5,stress_delta:-.14,cost:.018,last_update:1793002000}} },
      intent:{emotion:"joy",intensity:"high",need:"share",intent:"approach",expression:"open",plan:"顺着分享接话",compound:"亲近",regulation:"none",spectrum:[{key:"joy",name:"快乐",distance:.18}]},
      working_set:{capacity:8,count:3,ids:["a1b2c3d4e5f6","f6e5d4c3b2a1","998877665544"],ttl_seconds:7200} }],
    events:[
      {title:"对方的承诺", event:"对方说以后会先询问意愿，并记得说过的话。", event_key:"对方-承诺-先询问", session:"demo:session", ts:1793000600, time_span:{start_ts:1793000000,end_ts:1793000900}, importance:.86, centrality:.82, central_details:"对方主动承诺先询问意愿，而不是替自己做决定。", peripheral_details:"当时是在走廊里说的。", peripheral_retention:.18, peripheral_forgotten:false, meaning_to_her:"确认自己没有被当成工具。", reflection:"被认真问一句就足够安心。", confidence:.93, modalities:["语音"], source_check:{status:"ok"}},
      {title:"未说出口的担心", event:"在出发前犹豫了一下，还是把担心咽了回去。", event_key:"自己-犹豫-咽下担心", session:"demo:session", ts:1793001500, time_span:{start_ts:1793001400,end_ts:1793001800}, importance:.63, centrality:.55, central_details:"没有说出口的担心。", peripheral_details:"", peripheral_retention:.05, peripheral_forgotten:true, meaning_to_her:"不想让对方担心。", reflection:"习惯把难受藏起来。", confidence:.81, modalities:[], source_check:{status:"ok"}},
      {title:"走廊里的小烟花", event:"和同伴在走廊里放了一支小烟花。", event_key:"同伴-烟花-放松", session:"demo:session", ts:1793002100, time_span:{start_ts:1793001900,end_ts:1793002200}, importance:.66, centrality:.48, central_details:"难得的放松。", peripheral_details:"烟花是蓝色的。", peripheral_retention:.52, peripheral_forgotten:false, meaning_to_her:"普通日子也值得庆祝。", reflection:"快乐要分给身边的人。", confidence:.7, modalities:["图片"], source_check:{status:"weak"}}
    ],
    insights:[{insight:"被认真询问意愿，会更愿意承担任务。"}],
    last_memory_meta:{count:3,confidence:.66,answer_confidence:.58,gate:"none",abstain:false,conflicts:1,consistency:.72,tiers:{hot:1,warm:2},calibration_delta:0.012,calibration_entries:2},
    last_memory_trace:{count:3,valence:.18,stress_delta:.02,entry_ids:["a1b2c3d4e5f6"]},
    last_strategy_hint:"refuse=negotiate",
    memory_index:[
      {session:"demo:session", entries:[
        {id:"a1b2c3d4e5f6", text:"对方说以后会先询问意愿，并记得说过的话。", role:"user", ts:1793000600, importance:.86, hits:4, memory_source:"direct", memory_confidence:.93, memory_tier:"hot", conflict:false, last_write_op:"UPDATE", previous_versions:["对方说以后会先问一句。"], summarized:false},
        {id:"f6e5d4c3b2a1", text:"在出发前犹豫了一下，还是把担心咽了回去。", role:"user", ts:1793001500, importance:.63, hits:2, memory_source:"inferred", memory_confidence:.34, memory_tier:"warm", conflict:true, last_write_op:"UPDATE", previous_versions:["其实并不担心。","担心说出口会麻烦别人。"], summarized:false},
        {id:"998877665544", text:"和同伴在走廊里放了一支小烟花。", role:"user", ts:1793002100, importance:.66, hits:1, memory_source:"media", memory_confidence:.70, memory_tier:"warm", conflict:false, last_write_op:"ADD", previous_versions:[], summarized:false}
      ], tombstones:[{id:"deadbeef0001", ts:1793000900, text:"旧的一条已删除记忆（示例）。"}]}
    ],
    relationships:[
      {sender_id:"demo-user", sender_name:"重要的人", interactions:18, trust:.57, last_seen:1793002100,
       relationship:{state:{trust:.57,closeness:.61,conflict:.22,repair:.18,predictability:.74},
         trajectory:[
           {ts:1792998000,trust:.40,closeness:.45,conflict:.35,repair:0,predictability:.55},
           {ts:1792999500,trust:.48,closeness:.50,conflict:.30,repair:.16,predictability:.66},
           {ts:1793000600,trust:.55,closeness:.58,conflict:.24,repair:.12,predictability:.72},
           {ts:1793001500,trust:.50,closeness:.55,conflict:.30,repair:0,predictability:.60},
           {ts:1793002100,trust:.57,closeness:.61,conflict:.22,repair:.18,predictability:.74}
         ],
         transactive_map:{"老板":6,"担心":3,"承诺":2},
         destination_map:{"demo-user":{sender_id:"demo-user",sender_name:"重要的人",count:3,last_ts:1793002100,latest_text:"对方说以后会先询问意愿。"}},
         calibration:{sources:{direct:{n:6,brier_sum:.72,brier:.12,ewma:.10},inferred:{n:2,brier_sum:.68,brier:.34,ewma:.31}}}
       }}
    ]
  };
  let data=null, timer=null, _orbCheckSet=false;
  function checkOrbAlive(){
    if(_orbCheckSet) return;
    _orbCheckSet=true;
    setTimeout(()=>{
      if(window.__biocoreOrbAlive) return;
      const tip=$("orbTip");
      if(!tip) return;
      tip.hidden=false;
      tip.classList.add("show");
      tip.textContent="记忆球渲染未启动：请按 Ctrl+F5 强制刷新页面（可能缓存了旧脚本），或到 设置 → 球体图层 点“恢复默认显示”。";
    },2500);
  }
  // task-58: full emotion vocabulary (EMOTION_SPECTRUM 30+) in Chinese. The
  // old map only had 8 basic labels, so L("amusement") fell back to raw English
  // in the focus panel and the session cards.
  const EMOTION_ZH={neutral:"平静",joy:"开心",sadness:"难过",fear:"害怕",anger:"生气",surprise:"惊讶",trust:"信任",loneliness:"孤独",admiration:"钦佩",adoration:"爱慕",aesthetic:"审美欣赏",amusement:"好笑",anxiety:"焦虑",awe:"敬畏",awkwardness:"尴尬",boredom:"无聊",calmness:"平静",confusion:"困惑",contempt:"轻蔑",contentment:"满足",desire:"欲望",disappointment:"失望",disgust:"厌恶",empathic_pain:"共情痛苦",entrancement:"入迷",envy:"嫉妒",excitement:"兴奋",guilt:"内疚",horror:"恐惧",interest:"兴趣",nostalgia:"怀念",pride:"自豪",satisfaction:"满足",shame:"羞耻"};
  const UNKNOWN_EMOTION="未知情绪";
  const map={...EMOTION_ZH,approach:"靠近",hold:"停住",withdraw:"退开",far:"远",near:"近",soft:"轻",blunt:"直",playful:"俏皮",quiet:"安静",short:"短",normal:"正常",open:"展开",low:"低",high:"高",calm:"松",tense:"紧",overloaded:"过载",be_heard:"被听见",space:"空间",vent:"吐槽",share:"分享",talk:"说话"};
  // task-58: a missing key must never leak raw English into the UI. Unknown
  // values render as 未知情绪; non-emotion enums stay translated below.
  // Regulation strategies are enums, not emotions: keep their own table and use
  // _regLabel() for display so an unknown/new strategy key stays readable as its
  // raw token instead of leaking "未知情绪". Batch4 B2 adds label_emotion (#7).
  const mapExtra={none:"无",closed:"闭",restrained:"克制",seek_comfort:"找安慰",reappraise:"换个角度",suppress:"压住",avoid:"回避",express:"说出",distraction:"分散注意",label_emotion:"命名情绪"};
  Object.assign(map,mapExtra);
  const L=(v)=>{const k=String(v==null?"":v);if(Object.prototype.hasOwnProperty.call(map,k))return map[k];return UNKNOWN_EMOTION;};
  function _regLabel(v){const k=String(v==null?"":v).trim();if(!k)return "-";return Object.prototype.hasOwnProperty.call(mapExtra,k)?mapExtra[k]:k;}
  function emotionZh(v){const k=String(v==null?"":v).trim().toLowerCase();if(!k)return UNKNOWN_EMOTION;return Object.prototype.hasOwnProperty.call(EMOTION_ZH,k)?EMOTION_ZH[k]:UNKNOWN_EMOTION;}
  function emotionLabel(v){const k=String(v==null?"":v).trim();return k?emotionZh(k):"—";}
  // task-64: hidden/composite emotion layer (0-3 short Chinese labels).
  function _emotionNuanceOf(ev){
    const raw=(ev&&Array.isArray(ev.emotion_nuance))?ev.emotion_nuance:[];
    return raw.map(x=>String(x==null?"":x).trim()).filter(Boolean).slice(0,3);
  }
  function _emotionNuanceLine(primary,secondary,nuance){
    const list=Array.isArray(nuance)?nuance.map(x=>String(x==null?"":x).trim()).filter(Boolean).slice(0,3):[];
    if(!list.length) return "";
    const parts=[];
    if(primary) parts.push(String(primary));
    if(secondary) parts.push(String(secondary));
    parts.push("隐含 "+list.join("/"));
    return parts.join(" · ");
  }
  const clamp=(v)=>Math.max(0,Math.min(1,Number(v)||0));
  const pct=(v)=>Math.round(clamp(v)*100)+"%";
  const fmt=(v,d=2)=>(Number(v)>=0?"+":"")+Number(v||0).toFixed(d);
  const esc=(s)=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const shortSession=(v)=>{const t=String(v||"");return t.length>36?t.slice(0,33)+"…":t;};
  // Read-only window constants mirrored from the plugin (dashboard never writes
  // the bio layer; these only label numbers the server already computed).
  const REG_HALF_LIFE_DAYS=10;        // main.REGULATION_STATS_HALF_LIFE_DAYS (G4)
  const MEM_HALF_LIFE_DAYS=30;        // memory_meta.MEMORY_TEMPORAL_HALF_LIFE_DAYS (G7/G8/G11)
  const MEM_IMPORTANCE_FLOOR=0.15;    // memory_meta.MEMORY_IMPORTANCE_FLOOR
  const WORKING_SET_TTL_HOURS=2;      // memory_meta.WORKING_SET_TTL_SECONDS (G12)
  const CHAIN_HALF_LIFE_DAYS=30;      // memory_meta.CHAIN_LINK_HALF_LIFE_DAYS (H2-1)
  const NEED_LABELS={physiological:"生理",safety:"安全",belonging:"归属",esteem:"尊重",self_actualization:"自我实现"};
  const INTERO_LABELS={low:"偏低 / 想休息",steady:"平稳",high:"充足 / 活跃"};
  // 0..1 exponential recency weight, same formula as the server half-life decay.
  function _decayWeight(ageDays,halfLifeDays){
    const age=Math.max(0,Number(ageDays)||0), half=Math.max(1e-6,Number(halfLifeDays)||MEM_HALF_LIFE_DAYS);
    return Math.pow(0.5,age/half);
  }
  function _ageDaysFrom(ts){
    const value=Number(ts||0);
    if(!(value>0)) return 0;
    return Math.max(0,(Date.now()/1000-value)/86400);
  }
  // G4: recency-weighted regulation score (mirrors BioCore._regulation_rate).
  function _regWeightedScore(st,nowMs){
    const s=(st&&typeof st==="object")?st:{};
    const uses=Number(s.uses||0);
    if(!(uses>0)) return null;
    const success=Number(s.success||0), cost=Number(s.cost||0);
    const score=success/uses-0.05*(cost/uses);
    const last=Number(s.last_update||0);
    if(!(last>0)) return score;
    const ageDays=Math.max(0,((nowMs||Date.now())/1000-last)/86400);
    return score*_decayWeight(ageDays,REG_HALF_LIFE_DAYS);
  }
  // G15: reflection nodes older than the TTL are hidden server-side; report how
  // many were hidden instead of letting "COUNT" silently disagree with ROOTS.
  function _treeHiddenCount(tree){
    const t=(tree&&typeof tree==="object")?tree:{};
    const total=Number(t.count||0);
    const shown=Array.isArray(t.roots)?t.roots.length:0;
    return Math.max(0,total-shown);
  }
  function _needLabel(key){
    const k=String(key||"").trim();
    return NEED_LABELS[k]||k||"—";
  }
  function _interoLabel(label){
    const k=String(label||"").trim();
    return INTERO_LABELS[k]||k||"—";
  }
  // AstrBot session keys look like "default:FriendMessage:2396952936"
  // (event archive) or "default_FriendMessage_2396952936" (memory file stem).
  // Render them as Chinese labels: 私聊 · <名字> / 群聊 · <群号>.
  const SESSION_TYPE_LABELS={FriendMessage:"私聊",GroupMessage:"群聊",GuildMessage:"频道",TempMessage:"临时会话",OtherMessage:"其他"};
  function parseSessionKey(key){
    const raw=String(key||"").trim();
    const norm=raw.replace(/:/g,"_");
    const m=norm.match(/^(.*?)_(FriendMessage|GroupMessage|GuildMessage|TempMessage|OtherMessage)_(.+)$/);
    if(m) return {platform:m[1],type:m[2],id:m[3]};
    const seg=norm.split("_").filter(Boolean);
    if(seg.length>=3) return {platform:seg[0],type:seg[1],id:seg.slice(2).join("_")};
    return {platform:"",type:"",id:norm};
  }
  function _userNameById(id){
    const rels=(data&&Array.isArray(data.relationships))?data.relationships:[];
    for(const u of rels){
      if(!u||typeof u!=="object") continue;
      if(String(u.sender_id||"")===String(id||"")) return String(u.sender_name||"");
    }
    return "";
  }
  function sessionLabel(key){
    const p=parseSessionKey(key);
    const typeLabel=SESSION_TYPE_LABELS[p.type]||(p.type?p.type:"会话");
    let name="";
    if(p.type==="FriendMessage"||p.type==="TempMessage") name=_userNameById(p.id);
    if(!name) name=p.id||String(key||"");
    return name?(typeLabel+" · "+name):typeLabel;
  }
  // task-55: one real session may be stored under ":" and "_" variants
  // (events use colons, memory files use underscores). Canonical form unifies
  // them as platform:Type:id, so dropdowns/cards never duplicate a person and
  // both raw variants match one selection.
  function canonicalSessionKey(key){
    const p=parseSessionKey(key);
    if(p&&p.type) return (p.platform||"default")+":"+p.type+":"+p.id;
    return String(key||"").trim().replace(/_/g,":");
  }
  function sessionTypeLabel(key){
    const p=parseSessionKey(key);
    return SESSION_TYPE_LABELS[p.type]||(p.type?p.type:"会话");
  }
  function _relationshipSessionKeys(rel){
    const out=[];
    if(!rel||typeof rel!=="object") return out;
    if(Array.isArray(rel.sessions)) rel.sessions.forEach(x=>{ if(x) out.push(x); });
    ["session","unified_msg_origin"].forEach(k=>{ if(rel[k]) out.push(rel[k]); });
    return out;
  }
  function collectSessionVariants(){
    const map=new Map();
    const add=(raw)=>{
      const text=String(raw||"").trim();
      if(!text) return;
      const canonical=canonicalSessionKey(text);
      if(!canonical) return;
      if(!map.has(canonical)) map.set(canonical,new Set());
      map.get(canonical).add(text);
    };
    // union: events + memory index + live cores + relationships + current filters
    (Array.isArray(data&&data.events)?data.events:[]).forEach(ev=>add(ev&&ev.session));
    const idx=memoryIndexValue();
    if(Array.isArray(idx)) idx.forEach(s=>add(s&&s.session));
    (Array.isArray(data&&data.cores)?data.cores:[]).forEach(c=>add(c&&c.key));
    const rels=relationshipsValue();
    if(Array.isArray(rels)) rels.forEach(rel=>_relationshipSessionKeys(rel).forEach(add));
    if(summarySessionFilter) add(summarySessionFilter);
    if(memSessionFilter) add(memSessionFilter);
    return map;
  }
  function _sessionHasEvent(canonical){
    const evs=Array.isArray(data&&data.events)?data.events:[];
    return evs.some(ev=>canonicalSessionKey(ev&&ev.session)===canonical);
  }
  function _sessionHasMemory(canonical){
    const idx=memoryIndexValue();
    if(!Array.isArray(idx)) return false;
    return idx.some(s=>canonicalSessionKey(s&&s.session)===canonical);
  }
  function sessionEntries(){
    const out=[];
    collectSessionVariants().forEach((variants,canonical)=>{
      out.push({canonical:canonical,variants:Array.from(variants),
                hasEvent:_sessionHasEvent(canonical),hasMemory:_sessionHasMemory(canonical),
                label:sessionLabel(canonical)});
    });
    out.sort((a,b)=>{
      if(a.hasEvent!==b.hasEvent) return a.hasEvent?-1:1;
      if(a.hasMemory!==b.hasMemory) return a.hasMemory?-1:1;
      return a.label.localeCompare(b.label,"zh-CN");
    });
    return out;
  }
  function sessionVariantsOf(canonical){
    const map=collectSessionVariants();
    return Array.from(map.get(canonical)||[]);
  }
  function renderSessionList(){
    const box=$("sessionList");
    const count=$("sessionCount");
    if(!box) return;
    const entries=sessionEntries();
    const cores=Array.isArray(data&&data.cores)?data.cores:[];
    const coreByCanon={};
    cores.forEach(c=>{ const k=canonicalSessionKey(c&&c.key); if(k) coreByCanon[k]=c; });
    const ordered=[];
    entries.forEach(r=>{ if(coreByCanon[r.canonical]) ordered.push({row:r,core:coreByCanon[r.canonical]}); });
    entries.forEach(r=>{ if(!coreByCanon[r.canonical]) ordered.push({row:r,core:null}); });
    if(count) count.textContent=ordered.length+" SESSIONS";
    box.innerHTML=ordered.length?ordered.map(item=>{
      const r=item.row, core=item.core;
      const raw=(r.variants||[]).join(" | ")||r.canonical;
      let state="无在线状态";
      if(core){ const i=core.intent||{},ss=core.snapshot||{};
        state=esc(L(i.emotion))+" · "+esc(i.compound||"")+" · "+esc(L(i.intent))+" · trust "+Number(ss.trust||0).toFixed(2)+" · "+Number(ss.ticks||0)+"t";
      } else {
        const bits=[]; if(r.hasMemory) bits.push("记忆"); if(r.hasEvent) bits.push("事件");
        state=esc(bits.length?("无在线状态 · 有"+bits.join("+")):"无在线状态");
      }
      return '<div class="session" data-session="'+esc(r.canonical)+'" title="'+esc(raw)+'">'+
        '<div class="session-name">'+esc(r.label)+'</div>'+
        '<div class="session-state">'+state+'</div></div>';
    }).join(""):'<div class="empty">还没有活动会话。等第一条消息。</div>';
  }
  function storeGet(k, fallback){ try { const v = localStorage.getItem(k); return v == null ? fallback : v; } catch (e) { return fallback; } }
  function storeSet(k, v){ try { localStorage.setItem(k, String(v)); } catch (e) {} }
  // One-time migration: earlier builds defaulted the memory-node layer off and
  // cached "0" in localStorage. Without this, upgraded users would never see
  // the restored archived-event ball (e.g. the late-night confession ball).
  try {
    if(!localStorage.getItem("bio_vis_defaults_v3")){
      if(localStorage.getItem("bio_show_memory_nodes")==="0") localStorage.removeItem("bio_show_memory_nodes");
      localStorage.setItem("bio_vis_defaults_v3","1");
    }
  } catch (e) {}
  const visual={noise:storeGet("bio_show_noise","1")!=="0",echo:storeGet("bio_show_echo","1")!=="0"||storeGet("bio_show_ripple","1")!=="0",ripple:true,dominance:storeGet("bio_show_dominance","1")!=="0",social:storeGet("bio_show_social","1")!=="0",links:storeGet("bio_show_links","1")!=="0",nodes:storeGet("bio_show_nodes","0")!=="0",nodeLinks:storeGet("bio_show_node_links","0")!=="0",memoryNodes:storeGet("bio_show_memory_nodes","1")!=="0",memoryBallsImportant:storeGet("bio_show_memory_balls_important","1")!=="0",emotionRings: storeGet("bio_show_emotion_rings","0")!=="0",intensity:Number(storeGet("bio_intensity","65")),memoryRingStyle:storeGet("bio_memory_ring_style","orbit")==="solid"?"solid":"orbit",memoryBallColorMode:storeGet("bio_memory_ball_color_mode","mixed")==="primary"?"primary":"mixed",memoryBallGravity:storeGet("bio_memory_ball_gravity","1")!=="0",orbLegend:storeGet("bio_show_orb_legend","1")!=="0",showAutonomyPanel:storeGet("bio_show_autonomy_panel","1")!=="0",showLearningPanel:storeGet("bio_show_learning_panel","1")!=="0",showChainList:storeGet("bio_show_chain_list","1")!=="0"};
  let themeInitialized=false;
  function applyTheme(dark){
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    const b=$("themeToggle"); if(b) b.textContent = dark ? "浅色" : "深色";
  }
  function chooseTheme(hostDark){
    try {
      const forced = new URLSearchParams(location.search).get("theme");
      if (forced === "dark" || forced === "light") { applyTheme(forced === "dark"); themeInitialized = true; return; }
    } catch (e) {}
    const saved = storeGet("bio_theme", "");
    if (saved === "dark" || saved === "light") { applyTheme(saved === "dark"); }
    else { applyTheme(!!hostDark); }
    themeInitialized = true;
  }

  function switchInput(id){ const el=$(id); return el&&el.type==="checkbox"?el:null; }
  const SETTINGS_VIEW_KEY="biocore_settings_view";
  // Memory-first: iframe localStorage may throw; a poll must never reset the view.
  let _settingsViewMode=null;
  let _appliedSettingsView=null;
  function normalizeSettingsView(value){
    const text=String(value||"").toLowerCase();
    return text==="advanced"?"advanced":"simple";
  }
  function currentSettingsView(){
    if(_settingsViewMode==="simple"||_settingsViewMode==="advanced") return _settingsViewMode;
    try{ _settingsViewMode=normalizeSettingsView(window.localStorage.getItem(SETTINGS_VIEW_KEY)); }
    catch(e){ _settingsViewMode="simple"; }
    return _settingsViewMode;
  }
  function setSettingsView(mode){
    _settingsViewMode=normalizeSettingsView(mode);
    try{ window.localStorage.setItem(SETTINGS_VIEW_KEY,_settingsViewMode); }catch(e){}
    applySettingsView(_settingsViewMode);
  }
  function initializeSettingsView(){
    const mode=currentSettingsView();
    if(_appliedSettingsView!==mode) applySettingsView(mode);
  }
  function applySettingsView(mode){
    const view=normalizeSettingsView(mode);
    if(_appliedSettingsView===view) return;
    _appliedSettingsView=view;
    const settings=$("view-settings");
    if(settings){ settings.classList.toggle("mode-simple",view==="simple"); settings.classList.toggle("mode-advanced",view==="advanced"); }
    const coreIndexRow=$("coreIndexRow"); if(coreIndexRow) coreIndexRow.hidden=view!=="advanced";
    const simpleBtn=$("btnSimpleView"), advancedBtn=$("btnAdvancedView");
    if(simpleBtn) simpleBtn.classList.toggle("active",view==="simple");
    if(advancedBtn) advancedBtn.classList.toggle("active",view==="advanced");
    try{ window.localStorage.setItem(SETTINGS_VIEW_KEY,view); }catch(e){}
    updateCoreIndexCounts();
  }
  function updateCoreIndexCounts(){
    const row=$("coreIndexText"); if(!row) return;
    const d=(data&&typeof data==="object")?data:{};
    const indexRows=Array.isArray(d.memory_index)?d.memory_index:((d.memory&&Array.isArray(d.memory.index))?d.memory.index:[]);
    let entries=0, invalid=0;
    indexRows.forEach((item)=>{ if(!item||typeof item!=="object") return;
      const n=Number(item.count||item.entries||0); if(Number.isFinite(n)) entries+=n;
      const bad=Number(item.invalid||0); if(Number.isFinite(bad)) invalid+=bad; });
    const tombstones=Array.isArray(d.tombstones)?d.tombstones.length:Number(d.tombstone_count||0);
    const graphRaw=d.graph||null;
    const graph=graphRaw&&typeof graphRaw==="object"?(Number(graphRaw.nodes||0)+Number(graphRaw.edges||0)):Number(d.graph_count||0);
    row.textContent="索引：entries "+entries+" · tombstones "+tombstones+" · invalid "+invalid+" · graph "+graph;
  }
  function setupSettingsView(){
    const view=$("view-settings"); if(!view||$("settingsViewToggle")) return;
    const bar=document.createElement("div");
    bar.className="setting-row"; bar.id="settingsViewToggle";
    bar.innerHTML='<div><b>视图</b><small>简单只显示组开关；高级显示全部 31 个细项与诊断</small></div><div class="inline-actions"><button class="btn active" id="btnSimpleView" type="button">简单</button><button class="btn" id="btnAdvancedView" type="button">高级</button></div>';
    view.insertBefore(bar, view.firstChild);
    $("btnSimpleView").addEventListener("click",()=>setSettingsView("simple"));
    $("btnAdvancedView").addEventListener("click",()=>setSettingsView("advanced"));
    initializeSettingsView();
    updateCoreIndexCounts();
  }
  function setupSettingsLayout(rows){
    if($("settingsBio")) return;  // static 4-tab layout (生物/记忆/模型/系统)
    const bar=$("settingsTabs"); const view=$("view-settings");
    const memoryPanel=$("settingsMemory"); if(!bar||!view||!memoryPanel) return;
    const grid=memoryPanel.parentNode;
    const makeTab=(id,label)=>{ if(bar.querySelector('[data-settings-target="'+id+'"]')) return;
      const btn=document.createElement("button"); btn.type="button"; btn.className="settings-tab fold-panel folded";
      btn.dataset.settingsTarget=id;
      btn.innerHTML='<span class="fold-face"><small>'+label+'</small></span>';
      const before=bar.querySelector('[data-settings-target="settingsMemory"]');
      bar.insertBefore(btn, before||null);
    };
    const makePanel=(id)=>{ if($(id)) return $(id); const panel=document.createElement("div");
      panel.className="panel settings settings-panel"; panel.id=id; grid.appendChild(panel); return panel; };
    const statusPanel=makePanel("settingsCoreStatus");
    const safetyPanel=makePanel("settingsSafety");
    const llmPanel=makePanel("settingsLlm");
    const expressionPanel=makePanel("settingsExpression");
    makeTab("settingsCoreStatus","核心状态");
    makeTab("settingsSafety","安全");
    makeTab("settingsLlm","LLM 候选");
    makeTab("settingsExpression","表达");
    const moveRow=(input,panel)=>{ if(!input||!panel||!input.closest) return false; const row=input.closest(".setting-row"); if(row) panel.appendChild(row); return !!row; };
    const moveById=(id,panel)=>moveRow($(id),panel);
    // 索引诊断（核心模式已下线，2026-10-31）
    if(!$("coreIndexRow")){ const indexRow=document.createElement("div"); indexRow.className="setting-row"; indexRow.id="coreIndexRow"; indexRow.hidden=true;
      indexRow.innerHTML='<div><b>索引诊断</b><small id="coreIndexText">索引：—</small></div>'; statusPanel.appendChild(indexRow); }
    // 安全：掩码/投毒开关 + 危机说明
    moveById("swSafetyEnabled", safetyPanel);
    const warn=$("safetyWarn"); if(warn&&warn.parentNode) safetyPanel.appendChild(warn);
    if(!$("crisisNoteRow")){ const note=document.createElement("div"); note.className="setting-row"; note.id="crisisNoteRow";
      note.innerHTML='<div><b>危机分级</b><small>只记录不拦截；critical/high 会携带安全契约（资源、must_ack、不放弃），并写入 crisis 日志。</small></div>'; safetyPanel.appendChild(note); }
    // LLM 候选：候选开关 + 路由说明 + 预算提示
    moveById("swLlmCandidates", llmPanel);
    if(!$("llmRouteNoteRow")){ const note=document.createElement("div"); note.className="setting-row"; note.id="llmRouteNoteRow";
      note.innerHTML='<div><b>功能路由</b><small>各功能路由 select 见「API」标签；此处只控制 LLM 候选开关与用量提示。</small></div>'; llmPanel.appendChild(note); }
    if(!$("llmBudgetRow")){ const row=document.createElement("div"); row.className="setting-row"; row.id="llmBudgetRow";
      row.innerHTML='<div><b>预算 / 用量</b><small id="llmBudgetText">LLM 闸关闭或未配置（gates 见核心状态）</small></div>'; llmPanel.appendChild(row); }
    ["fn_empathy_hint_enabled","fn_pragmatics_hint_enabled","fn_tom_probe_enabled","fn_humor_hint_enabled"].forEach((id)=>moveById(id, expressionPanel));
    try{ setupSettingsTabs(); }catch(e){}
  }
  function setupSwitchGroups(){
    // 组开关已下线：静态 6 组行与 12 个确认按钮已删除，只剩 feature 层（FEATURE_TABLE / setupFeatureSwitches）。
    setupSettingsLayout([]);
    setupSettingsView();
    setupFeatureSwitches();
    initializeSettingsView();
  }

  // [PERSONA-COMPILE] one-shot action button (not a persistent switch)
  function renderCurrentPersona(){
    const d=(data&&typeof data==="object")?data:{};
    const set=(id,v)=>{const el=$(id); if(el) el.textContent=String(v==null||v===""?"—":v);};
    const profile=(d.persona_profile&&typeof d.persona_profile==="object")?d.persona_profile:{};
    const cfg=(d.config&&typeof d.config==="object")?d.config:{};
    const big5=(profile.big5&&typeof profile.big5==="object")?profile.big5:{};
    const traits=["O","C","E","A","N"].map((k)=>{
      const key=Object.keys(big5).find((name)=>String(name).toLowerCase().startsWith(k.toLowerCase()));
      const value=key!=null?Number(big5[key]):NaN;
      return k+" "+(Number.isFinite(value)?value.toFixed(2):"—");
    }).join(" · ");
    const personas=Array.isArray(d.personas)?d.personas:[];
    const pid=String(d.persona_id||"");
    const hit=personas.find((p)=>p&&(String(p.id)===pid||String(p.name)===pid))||null;
    const fallbackPersona=personas[0]||null;   // AstrBot 默认人设通常是列表首项（能天使），不要优先 default
    const name=(d.persona_name||profile.name||cfg.persona_name||(hit&&(hit.name||hit.id))||(!pid&&fallbackPersona?(fallbackPersona.name||fallbackPersona.id):"")||pid||"");
    const nameText=name?("当前人设："+name):"当前人设：跟随 AstrBot 默认";
    set("currentPersonaName",nameText);
    set("currentPersonaNameModel",nameText);
    set("currentPersonaSource", name?("AstrBot 当前人设（"+name+"）"):"AstrBot 当前人设");
    const compiled=d.persona_compiled_hash||d.persona_version||"";
    set("currentPersonaVersion", compiled?("已编译 v"+String(compiled).slice(0,8)+(d.persona_compiled_at?(" · "+d.persona_compiled_at):"")):"未编译（点右侧按钮）");
    set("currentPersonaTraits", traits);
    const text=String(d.persona_text||d.persona||"").trim();
    set("currentPersonaSummary", text?(text.slice(0,60)+(text.length>60?"…":"")):"—");
  
    try{ renderPersonaTarget(); }catch(e){}}

  function renderPersonaTarget(){
    const sel=$("personaTargetSelect"); if(!sel) return;
    const d=(data&&typeof data==="object")?data:{};
    const personas=Array.isArray(d.personas)?d.personas:[];
    const pid=String(d.persona_id||"");
    const sig=personas.map((p)=>String(p&&p.id||"")+"|"+String(p&&p.name||"")).join(",")+"#"+pid;
    if(sel.dataset.sig===sig) return;
    sel.dataset.sig=sig;
    sel.innerHTML="";
    const follow=document.createElement("option");
    follow.value=""; follow.textContent="跟随 AstrBot 默认人设";
    sel.appendChild(follow);
    personas.forEach((p)=>{
      if(!p) return;
      const o=document.createElement("option");
      o.value=String(p.id||p.name||"");
      o.textContent=(p.name&&p.id&&String(p.name)!==String(p.id))?(String(p.name)+"（"+String(p.id)+"）"):String(p.name||p.id||"");
      sel.appendChild(o);
    });
    sel.value=pid||"";
    if(!sel.dataset.bound){
      sel.dataset.bound="1";
      sel.addEventListener("change",()=>{
        const v=sel.value||"";
        const st=$("personaTargetState");
        if(st) st.textContent="保存中…";
        try{
          if(bridge){ bridge.apiPost("page/toggle",{key:"persona_id",value:v}).then(()=>{ if(st) st.textContent="已保存"; }).catch(()=>{ if(st) st.textContent="保存失败"; }); }
          else if(st) st.textContent="未连接";
        }catch(e){ if(st) st.textContent="保存失败"; }
      });
    }
  }
  function setupPersonaCompile(){
    renderCurrentPersona();
    const btn=$("personaCompileBtn"); if(!btn||btn.dataset.bound) return; btn.dataset.bound="1";
    const confirmRow=$("personaCompileConfirmRow");
    const toast=(text)=>{ const el=$("personaCompileToast"); if(!el) return; el.textContent=String(text||""); el.hidden=false;
      if(el._t) clearTimeout(el._t); el._t=setTimeout(()=>{el.hidden=true;},3000); };
    const allowed=()=>{
      if(!bridge) return false;
      const fn=(data&&data.llm_functions&&data.llm_functions.persona_compile)||{};
      return fn.enabled!==false;
    };
    const sync=()=>{ const ok=allowed(); btn.disabled=!ok; btn.title=ok?"":"需要 LLM（跟随主 LLM）"; };
    btn.addEventListener("click",()=>{ if(btn.disabled) return; if(confirmRow) confirmRow.hidden=false; });
    const yes=$("personaCompileConfirmYes");
    if(yes&&!yes.dataset.bound){ yes.dataset.bound="1"; yes.addEventListener("click",async()=>{
      if(confirmRow) confirmRow.hidden=true;
      const old=btn.textContent; btn.disabled=true; btn.textContent="编译中…";
      try{
        const raw=await bridge.apiPost("page/persona_compile",{});
        const payload=raw&&raw.data?raw.data:raw;
        if(!payload||payload.ok===false){
          const err=new Error((payload&&payload.message)||"编译失败");
          err.code=(payload&&payload.error)||""; throw err;
        }
        toast("编译完成（version "+(payload.version||"?")+"）");
      }catch(e){
        const reason=(typeof describeBridgeError==="function")?describeBridgeError(e):String(e&&e.message||e);
        toast("编译失败："+reason);
      }
      btn.textContent=old; sync();
    }); }
    const no=$("personaCompileConfirmNo");
    if(no&&!no.dataset.bound){ no.dataset.bound="1"; no.addEventListener("click",()=>{ if(confirmRow) confirmRow.hidden=true; }); }
    sync();
  }

  // [FEATURE-SWITCHES] 11 function-domain switches over the 27 advanced switches.
  const FEATURE_TABLE = {
    feat_memory_compress: ["swCompress"],
    feat_memory_retrieval: ["swHybridRetrieval"],
    feat_memory_insight: ["fn_event_summary_enabled","fn_event_ranking_enabled","fn_insight_enabled","swInsightAuto","fn_memory_summary_enabled"],
    feat_memory_relation: ["fn_relationship_impression_enabled","fn_repair_hint_enabled","fn_diary_enabled","fn_relationship_narrative_enabled"],
    feat_expression_rules: ["fn_empathy_hint_enabled"],
    feat_visual_nodes: ["swShowMemoryNodes"],
    feat_visual_links: ["swShowLinks"],
    feat_visual_rings: ["swShowEcho","swShowDominance","swShowSocial"],
    feat_safety: ["swSafetyEnabled"],
    feat_llm_image: ["fn_image_caption_enabled"],
  };
  window.LLM_ADVANCED_IDS = ["fn_event_summary_enabled","fn_event_ranking_enabled","fn_insight_enabled","fn_memory_summary_enabled","fn_relationship_impression_enabled","fn_repair_hint_enabled","fn_diary_enabled","fn_relationship_narrative_enabled","fn_image_caption_enabled","fn_pragmatics_hint_enabled","fn_tom_probe_enabled","fn_humor_hint_enabled","swInsightAuto"];
  const FEATURE_ORDER = ["feat_memory_compress","feat_memory_retrieval","feat_memory_insight","feat_memory_relation","feat_expression_rules","feat_visual_nodes","feat_visual_links","feat_visual_rings","feat_safety","feat_llm_image"];
  const FEATURE_LOCAL_DEFAULT_ON = { feat_expression_rules: true };
  function setupLlmConsolidation(){
    const route=$("llm_route_default");
    if(route&&!route.dataset.bound){
      route.dataset.bound="1";
      try{ route.value=window.localStorage.getItem("bio_llm_route_default")||"follow_llm"; }catch(e){}
      route.addEventListener("change",()=>{ try{ window.localStorage.setItem("bio_llm_route_default",String(route.value||"follow_llm")); }catch(e){} });
    }
    const btn=$("feat_llm_insight_btn");
    if(btn&&!btn.dataset.bound){
      btn.dataset.bound="1";
      btn.addEventListener("click",()=>{
        const chk=switchInput("fn_insight_enabled");
        if(!bridge||!chk) return;
        chk.checked=!chk.checked;
        try{ chk.dispatchEvent(new Event("change",{bubbles:true})); }catch(e){}
        refreshFeatureStates();
      });
    }
  }
  function featureValues(){
    const values={};
    FEATURE_ORDER.forEach((id)=>{ (FEATURE_TABLE[id]||[]).forEach((kid)=>{ const el=switchInput(kid); if(el) values[kid]=el.checked===true; }); });
    return values;
  }
  function featureStateOf(id, values){
    const kids=FEATURE_TABLE[id]||[];
    if(!kids.length) return "off";
    const on=kids.filter((kid)=>values[kid]===true).length;
    return on===0?"off":(on===kids.length?"on":"mixed");
  }
  function refreshFeatureStates(){
    const values=featureValues();
    FEATURE_ORDER.forEach((id)=>{
      const box=$(id); if(!box) return;
      if(FEATURE_LOCAL_DEFAULT_ON[id]){
        let stored=null; try{ stored=window.localStorage.getItem("bio_"+id); }catch(e){}
        const on=(stored===null)?true:(stored!=="0");
        box.checked=on; box.indeterminate=false;
        const child=switchInput((FEATURE_TABLE[id]||[])[0]);
        if(child&&child.checked!==on) child.checked=on;
        return;
      }
      const state=featureStateOf(id,values);
      box.checked=state==="on";
      box.indeterminate=state==="mixed";
    });
  }
  function bindCompressSave(){
    const btn=$("compressSaveBtn");
    if(!btn||btn.dataset.bound) return;
    btn.dataset.bound="1";
    btn.addEventListener("click",async()=>{
      const st=$("compressSaveState");
      const setState=(t)=>{ if(st) st.textContent=String(t||""); };
      if(!bridge){ setState("未连接 AstrBot 页面桥"); return; }
      const body={compression:{
        enabled: !!($("swCompress")&&$("swCompress").checked),
        threshold: Number($("compressThreshold")?$("compressThreshold").value:6000),
        max_chars: Number($("compressMax")?$("compressMax").value:800)
      }};
      setState("保存中…");
      try{
        const raw=await bridge.apiPost("page/api_config",body);
        const payload=raw&&raw.data?raw.data:raw;
        if(!payload||payload.status==="error"||payload.status==="fail") throw new Error((payload&&payload.message)||"保存失败");
        if(data) data.api_config=payload;
        setState("已保存");
      }catch(err){ setState("保存失败："+String((err&&err.message)||err)); }
    });
  }
  function setupFeatureSwitches(){
    FEATURE_ORDER.forEach((id)=>{
      const box=$(id); if(!box||box.dataset.bound) return; box.dataset.bound="1";
      box.addEventListener("change",()=>{
        const target=!!box.checked;
        if(FEATURE_LOCAL_DEFAULT_ON[id]){ try{ window.localStorage.setItem("bio_"+id,target?"1":"0"); }catch(e){} }
        (FEATURE_TABLE[id]||[]).forEach((kid)=>{
          const el=switchInput(kid); if(!el) return;
          if(el.checked!==target){ el.checked=target; try{ el.dispatchEvent(new Event("change",{bubbles:true})); }catch(e){} }
        });
        refreshFeatureStates();
      });
    });
    window.LLM_ADVANCED_IDS.forEach((kid)=>{
      const el=switchInput(kid); if(!el||!el.closest) return;
      const row=el.closest(".setting-row"); if(!row) return;
      const label=row.querySelector("b"); if(label&&!label.textContent.includes("[LLM]")) label.textContent="[LLM] "+label.textContent;
    });
    refreshFeatureStates();
  }

  function _initStep(name, fn){
    try{ window.__diagLog && window.__diagLog("init:2 "+name); }catch(e){}
    try{ fn(); window.__diagLog && window.__diagLog("init:2ok "+name); }
    catch(e){ try{ window.__diagError && window.__diagError("init fail: "+name+" "+(e&&e.message||e)); }catch(x){} }
  }
  function safeRender(name, fn){ try { fn(); } catch(e){ try{ if(window.console&&window.console.warn) window.console.warn("[biocore] render failed:",name,e); }catch(x){} } }
  function bindAutonomy(){
    const d=(data&&typeof data==="object")?data:{};
    const auto=(d.autonomy&&typeof d.autonomy==="object")?d.autonomy:{};
    if(auto.state&&typeof auto.state==="object"){ try{ renderAutonomyState(auto.state); }catch(e){} }
    if(auto.motive||(auto.state&&auto.state.motive)){ const M=auto.motive||auto.state.motive; setText("autonomyMotive","等你 "+(M.hours||0).toFixed(1)+"h（×"+(M.silence_mult||1).toFixed(2)+"）· 被压 ×"+(M.frust_mult||1).toFixed(2)+" · 综合 ×"+(M.total_mult||1).toFixed(2)); }
    if(auto.attachment_style&&$("autonomyAttachment")) setVal("autonomyAttachment",auto.attachment_style);
    if(auto.tick_engine&&$("autonomyTickEngine")) setVal("autonomyTickEngine",auto.tick_engine);
    if(auto.state&&auto.state.intent){ const I=auto.state.intent; setText("autonomyIntent","这次想说："+(I.text_hint||I.kind||"—")+"（"+I.kind+"）"); }
    if(auto.state&&auto.state.mood){ const M=auto.state.mood; setText("autonomyMood","心情："+(M.label||"—")+"（效价 "+(Number(M.valence||0).toFixed(2))+"）"); }
    if(auto.state&&auto.state.attribution){ const A=auto.state.attribution; const zh={internal:"内部",external:"外部",neutral:"中性",stable:"稳定",unstable:"不稳定",controllable:"可控",uncontrollable:"不可控",shame:"自责",anger:"愤怒",sadness:"难过",guilt:"内疚",neutral:"中性"}; setText("autonomyAttribution","归因："+(zh[A.locus]||A.locus)+"·"+(zh[A.stability]||A.stability)+"·"+(zh[A.controllability]||A.controllability)+" → "+(zh[A.emotion_hint]||A.emotion_hint)); }
    if(auto.state&&auto.state.social_pain){ const P=auto.state.social_pain; const zh={rising:"上升",falling:"下降",flat:"平稳"}; setText("autonomySocialPain","社会疼痛 "+Number(P.value||0).toFixed(2)+"（"+(zh[P.trend]||P.trend)+"）"); }
    if(auto.state&&auto.state.self_esteem){ setText("autonomySelfEsteem","自尊 "+Number(auto.state.self_esteem.value||0).toFixed(2)); }
    if(auto.state&&auto.state.gratitude!==undefined){ setText("autonomyGratitude","感激："+Number(auto.state.gratitude||0).toFixed(2)); }
    if(auto.state&&auto.state.empathy){ const E=auto.state.empathy; setText("autonomyEmpathy","共情：情感 "+(Number(E.affective||0).toFixed(2))+" · 认知 "+(Number(E.cognitive||0).toFixed(2))+"（"+E.mode+"）"); }
    if(auto.state&&auto.state.frustration){ const F=auto.state.frustration; setText("autonomyFrustration","挫折："+(F.n||0)+" 次 · "+(F.phase||"—")+" · drive ×"+(Number(F.drive_mult||1).toFixed(2))); }
    if(auto.state&&auto.state.schedule){ const S=auto.state.schedule; setText("autonomySchedule","间隔：等待被拦 "+(S.wait_blocked||0)+" 次"+(S.burst?" · burst":"")); }
    if(auto.state&&auto.state.appraisal){ const A=auto.state.appraisal; setText("autonomyAppraisal","评价：有利 "+(Number(A.goal_congruence||0).toFixed(2))+" · 卷入 "+(Number(A.ego_involvement||0).toFixed(2))+" · 应对 "+(Number(A.coping_potential||0).toFixed(2))); }
    if(auto.state&&auto.state.action){ const A=auto.state.action; setText("autonomyAction","行动倾向："+(A.tone||"—")+(A.emotion?"（"+A.emotion+"）":"")); }
    if(auto.state&&auto.state.attachment&&auto.state.attachment.style){ const A=auto.state.attachment; setText("autonomyAttachment","依恋："+A.style+" · 激活 "+(Number(A.activation||0).toFixed(2))+"（"+A.mode+"）"); }
    if(auto.state&&auto.state.regulation){ const R=auto.state.regulation; setText("autonomyRegulation","调节："+R.strategy+" · 努力 "+(Number(R.effort||0).toFixed(2))+(R.suppressed?" · 压着":"")); }
    if(auto.state&&auto.state.relationship){ const R=auto.state.relationship; const zh={stranger:"陌生人",acquaintance:"熟人",friend:"朋友",close:"亲密"}; setText("autonomyStage","关系阶段："+(zh[R.stage]||R.stage)+"（累计 "+(R.hours_total||0)+"h · Tau "+(R.tau_hours||0)+"h · 每日 "+(R.daily_cap||0)+"）"); }
    if(auto.state&&auto.state.self_life){ const S=auto.state.self_life; const first=(S.today&&S.today[0])?S.today[0].text:""; const U=(auto.state.user_model||{}); setText("autonomySelfLife","她今天："+(first||"—")+(U.busy_hint==="busy"?" · 她猜你：有点忙":(U.mood_hint==="low"?" · 她猜你：心情一般":""))); }
    if(auto.state&&auto.state.bid){ const B=auto.state.bid; setText("autonomyBid","连接邀请："+B.sent+" 次 · 接住 "+(B.toward||0)+" · 落空 "+(B.away||0)+"（频率 ×"+(Number(B.frequency||1).toFixed(2))+"）"); }
    if(auto.state&&auto.state.trust){ const T=auto.state.trust; setText("autonomyTrust","信任：可预测 "+(Number(T.predictability||0).toFixed(2))+" · 可靠 "+(Number(T.dependability||0).toFixed(2))+" · 信念 "+(Number(T.faith||0).toFixed(2))+"（总 "+(Number(T.overall||0).toFixed(2))+"）"); }
    if(auto.state&&auto.state.needs){ const N=auto.state.needs; const names={belonging:"归属",self_esteem:"自尊",control:"控制",meaningful_existence:"意义"}; setText("autonomyNeeds","需求："+Object.keys(names).map(k=>names[k]+" "+(Number(N[k]||0).toFixed(2))+(N.dominant===k?"（主导）":"")).join(" · ")); }
    if(auto.state&&auto.state.rumination&&auto.state.rumination.text){ setText("autonomyRumination",auto.state.rumination.text); }
    if(auto.state&&auto.state.sleep){ const S=auto.state.sleep; setText("autonomySleep","她现在："+(S.sleeping?"睡着":"醒着")+"（精力 "+(Number(S.energy||0).toFixed(2))+"，节律 "+(Number(S.circadian||0).toFixed(2))+"）"); }
    if(auto.state&&auto.state.loop){ const L=auto.state.loop; const lat=Number(L.avg_latency_s||0); setText("autonomyLoop","主动 "+(L.sent||0)+" 次 · 被回 "+(L.responded||0)+" 次（"+Math.round((L.response_rate||0)*100)+"%）"+(lat>0?" · 平均 "+ (lat/3600).toFixed(1)+"h 回复":"")); }
    if(auto.state&&auto.state.motive){ const M=auto.state.motive; setText("autonomyBlame","自责 "+(M.self_blame==null?"0.00":Number(M.self_blame).toFixed(2))+" · 表达自信 "+(M.confidence==null?"1.00":Number(M.confidence).toFixed(2))); }
    if(auto.state&&auto.state.limit){ const L=auto.state.limit; setText("autonomyLimit","本小时 "+(L.hour_sent||0)+"/"+(L.hourly_cap||2)+"（每日 "+(L.daily_cap||5)+"） · 被压 "+(L.frustration||0)+" 次（冲动 +"+Math.round(((L.drive_mult||1)-1)*100)+"%） · 累计被限制 "+(L.total_blocked||0)+" 次"); }
    if(auto.state&&auto.state.silence){ const s=auto.state.silence; const zh={expect:"期待",protest:"抗议期：有点急",loss:"失落",withdraw:"抽离"}; setText("autonomySilence","她等了你 "+(Number(s.hours||0).toFixed(1))+" 小时（"+(zh[s.phase]||s.phase||"—")+"）"); }
    if(auto.last_reason&&typeof auto.last_reason==="object"){ const r=auto.last_reason; setText("autonomyLastReason","上次主动："+(r.ts?new Date(Number(r.ts)*1000).toLocaleString("zh-CN"):"—")+" · 原因："+(r.text||r.code||"—")); }
    const st=(auto.state&&typeof auto.state==="object")?auto.state:{};
    const pick=(k)=>(auto[k]!==undefined?auto[k]:st[k]);
    const set=(id,v)=>{const el=$(id); if(el) el.textContent=String(v==null||v===""?"—":v);};
    setChecked("autonomyEnabled", pick("enabled")!==undefined?pick("enabled"):!!d.proactive_autonomy);
    setChecked("autonomySend", pick("send")!==undefined?pick("send"):!!d.proactive_send);
    set("autonomyReady", "ready "+(pick("ready")!==undefined?pick("ready"):"—"));
    set("autonomyThreshold", "threshold "+(pick("threshold")!==undefined?pick("threshold"):"—"));
    set("autonomyMaxChars", "max_chars "+(pick("max_chars")!==undefined?pick("max_chars"):"—"));
    set("autonomyImpulse", "impulse "+(pick("impulse")!==undefined?pick("impulse"):"—"));
    set("autonomySent", "sent "+(pick("sent")!==undefined?pick("sent"):"—"));
    const th=auto.threshold!==undefined?auto.threshold:0.6;
    const mc=auto.max_chars!==undefined?auto.max_chars:120;
    if($("autonomyThresholdInput")&&!$("autonomyThresholdInput").dataset.bound){ setVal("autonomyThresholdInput",th); }
    if($("autonomyMaxCharsInput")&&!$("autonomyMaxCharsInput").dataset.bound){ setVal("autonomyMaxCharsInput",mc); }
    if($("autonomyDailyCap")&&!$("autonomyDailyCap").dataset.bound){ setVal("autonomyDailyCap",(auto.daily_cap||5)); }
    const _zh={ready:"可发送",not_ready:"未达阈值",cooldown:"冷却中",daily_cap:"今日已达上限",quiet_hours:"静默时段",no_session:"无可用会话",not_private:"非私聊会话"};
    const renderAutonomyState=(r)=>{
      r=r||{};
      const V=Number(r.V||0), theta=Number(r.theta||0.55);
      const pct=Math.max(0,Math.min(100,Math.round(theta?V/theta*100:0)));
      const fill=$("autonomyVBarFill");
      if(fill){ fill.style.width=pct+"%"; fill.style.background=pct>=85?"var(--red)":"var(--accent)"; }
      setText("autonomyVPct",pct+"%");
      setText("autonomyVText","V "+(V||0).toFixed(3)+" / "+theta.toFixed(2));
      const zhParts={social_gap:"社交缺口",lonely:"寂寞",anxiety_fear:"焦虑",sadness:"悲伤",distress:"难受",joy:"愉悦",anger_conflict:"愤怒",boredom:"无聊",activity:"勤快",stress_load:"压力",drive_dev:"需求缺口",open_loops:"未了话题",nostalgia:"怀旧",repair_urge:"修复",memory_due:"记忆到期"};
      const parts=r.parts||{}; const keys=Object.keys(parts).filter(k=>Number(parts[k])>0).sort((a,b)=>parts[b]-parts[a]).slice(0,6);
      const shown=keys.map(k=>(zhParts[k]||k)+" "+(+parts[k]).toFixed(2)).join(" · ");
      const eta=(r.eta_hours==null)?"—":("约 "+Number(r.eta_hours).toFixed(1)+" 小时可达");
      setText("autonomyParts","drift "+(Number(r.drift||0)).toFixed(3)+" = "+(shown||"其余 ≈0")+" · "+eta+(Object.keys(parts).filter(k=>Number(parts[k])>0).length>6?" · 其余 ≈0":""));
      if(r.block_reason!==undefined) setText("autonomyBlockReason",( {ready:"可发送",not_ready:"未达阈值",cooldown:"冷却中",daily_cap:"今日已达上限",quiet_hours:"静默时段",no_session:"无可用会话",not_private:"非私聊会话"}[r.block_reason]||r.block_reason||"—"));
    };
    const renderCheck=(payload)=>{
      const r=payload.readiness||{}; const g=payload.gate||{};
      renderAutonomyState(r);
      const V=Number(r.V||0), theta=Number(r.theta||0.55);
      const pct=Math.max(0,Math.min(100,Math.round(theta?V/theta*100:0)));
      const fill=$("autonomyVBarFill");
      if(fill){ fill.style.width=pct+"%"; fill.style.background=pct>=85?"var(--red)":"var(--accent)"; }
      setText("autonomyVPct",pct+"%");
      setText("autonomyVText","V "+(V||0).toFixed(3)+" / "+theta.toFixed(2));
      const zhParts={social_gap:"社交缺口",lonely:"寂寞",anxiety_fear:"焦虑",sadness:"悲伤",distress:"难受",joy:"愉悦",anger_conflict:"愤怒",boredom:"无聊",activity:"勤快",stress_load:"压力",drive_dev:"需求缺口",open_loops:"未了话题",nostalgia:"怀旧",repair_urge:"修复",memory_due:"记忆到期"};
      const parts=r.parts||{}; const keys=Object.keys(parts).filter(k=>Number(parts[k])>0).sort((a,b)=>parts[b]-parts[a]).slice(0,6);
      const shown=keys.map(k=>(zhParts[k]||k)+" "+(+parts[k]).toFixed(2)).join(" · ");
      setText("autonomyParts","drift "+(Number(r.drift||0)).toFixed(3)+" = "+(shown||"其余 ≈0")+(Object.keys(parts).filter(k=>Number(parts[k])>0).length>6?" · 其余 ≈0":""));
      setText("autonomyBlockReason",_zh[g.reason]||g.reason||"—");
    };
    const _show=(id,v)=>{const el=$(id);if(el)el.hidden=!v;};
    const testBtn=$("autonomyTestBtn"), resetBtn=$("autonomyResetBtn");
    const yes=$("autonomyTestConfirmYes"), no=$("autonomyTestConfirmNo");
    if(testBtn&&!testBtn.dataset.bound){
      testBtn.dataset.bound="1";
      testBtn.addEventListener("click",()=>{_show("autonomyTestConfirm",true);_show("autonomyTestConfirmYes",true);_show("autonomyTestConfirmNo",true);});
      if(yes&&!yes.dataset.bound){yes.dataset.bound="1";yes.addEventListener("click",async()=>{
        _show("autonomyTestConfirm",false);_show("autonomyTestConfirmYes",false);_show("autonomyTestConfirmNo",false);
        if(!bridge){setText("autonomyTestState","桥接未连接");return;}
        setText("autonomyTestState","设置中…");
        try{const raw=await bridge.apiPost("page/autonomy_test",{arm:true});const p=raw&&raw.data?raw.data:raw;
          if(!p||p.ok===false)throw new Error((p&&p.message)||"失败");
          setText("autonomyTestState","已设置 V="+p.V_set+"（theta "+p.theta+"），等下一 tick 触发");
        }catch(e){setText("autonomyTestState","失败："+(typeof describeBridgeError==="function"?describeBridgeError(e):String(e&&e.message||e)));}
      });}
      if(no&&!no.dataset.bound){no.dataset.bound="1";no.addEventListener("click",()=>{_show("autonomyTestConfirm",false);_show("autonomyTestConfirmYes",false);_show("autonomyTestConfirmNo",false);});}
    }
    if(resetBtn&&!resetBtn.dataset.bound){resetBtn.dataset.bound="1";resetBtn.addEventListener("click",async()=>{
      if(!bridge){setText("autonomyTestState","桥接未连接");return;}
      setText("autonomyTestState","复位中…");
      try{const raw=await bridge.apiPost("page/autonomy_test",{reset:true});const p=raw&&raw.data?raw.data:raw;
        if(!p||p.ok===false)throw new Error((p&&p.message)||"失败");
        setText("autonomyTestState","已复位（V=0）");
      }catch(e){setText("autonomyTestState","失败："+(typeof describeBridgeError==="function"?describeBridgeError(e):String(e&&e.message||e)));}
    });}
    const check=$("autonomyCheckBtn");
    if(check&&!check.dataset.bound){
      check.dataset.bound="1";
      check.addEventListener("click",async()=>{
        if(!bridge){ setText("autonomyCheckState","桥接未连接"); return; }
        setText("autonomyCheckState","评估中…");
        try{
          const raw=await bridge.apiPost("page/autonomy_check",{});
          const payload=raw&&raw.data?raw.data:raw;
          if(!payload||payload.ok===false) throw new Error((payload&&payload.message)||"评估失败");
          const gate=payload.gate||{}; const ready=payload.readiness||{};
          const zh={ready:"可发送",not_ready:"未达阈值",cooldown:"冷却中",daily_cap:"今日已达上限",quiet_hours:"静默时段",no_session:"无可用会话",not_private:"非私聊会话"};
          renderCheck(payload);
          setText("autonomyCheckState","ready "+(ready.ready===true?"是":"否")+" · impulse "+(ready.impulse==null?"—":ready.impulse)+" · threshold "+(ready.threshold==null?"—":ready.threshold)+" · "+(zh[gate.reason]||gate.reason||"—"));
        }catch(e){ setText("autonomyCheckState","评估失败："+(typeof describeBridgeError==="function"?describeBridgeError(e):String(e&&e.message||e))); }
      });
    }
    const btn=$("autonomySaveBtn");
    if(btn&&!btn.dataset.bound){
      btn.dataset.bound="1";
      btn.addEventListener("click",async()=>{
        if(!bridge){ setText("autonomySaveState","桥接未连接（静态预览）"); return; }
        const body={ enabled:($("autonomyEnabled")||{}).checked===true, send:($("autonomySend")||{}).checked===true, clingy:($("autonomyClingy")||{}).checked===true, attachment_style:($("autonomyAttachment")||{}).value||"secure", tick_engine:($("autonomyTickEngine")||{}).value||"legacy", rejection_sensitivity:Number(($("autonomyRS")||{}).value||0.4),
          threshold:Number(($("autonomyThresholdInput")||{}).value), max_chars:Number(($("autonomyMaxCharsInput")||{}).value), daily_cap:Number(($("autonomyDailyCap")||{}).value||5) };
        setText("autonomySaveState","保存中…");
        try{
          const raw=await bridge.apiPost("page/autonomy", body);
          const payload=raw&&raw.data?raw.data:raw;
          if(!payload||payload.ok===false||payload.status==="error") throw new Error((payload&&payload.message)||"保存失败");
          setText("autonomySaveState","已保存");
        }catch(e){
          setText("autonomySaveState","保存失败："+(typeof describeBridgeError==="function"?describeBridgeError(e):String(e&&e.message||e)));
        }
      });
    }
  }
  try{
    const _schema="biocore_ui_schema";
    if(Number(window.localStorage.getItem(_schema)||0)<2){
      const _map={swShowNodes:"feat_visual_nodes",swShowMemoryNodes:"feat_visual_nodes",swShowLinks:"feat_visual_links",swShowNodeLinks:"feat_visual_links",swShowEmotionRings:"feat_visual_rings",fn_empathy_hint_enabled:"feat_expression_rules",fn_pragmatics_hint_enabled:"feat_expression_rules",fn_tom_probe_enabled:"feat_expression_rules",fn_humor_hint_enabled:"feat_expression_rules",swCompress:"feat_memory_compress",swHybridRetrieval:"feat_memory_retrieval",swSafetyEnabled:"feat_safety"};
      for(const oldKey in _map){ if(window.localStorage.getItem("bio_feat_"+oldKey)==="1" && window.localStorage.getItem("bio_feat_"+_map[oldKey])!=="1"){ window.localStorage.setItem("bio_feat_"+_map[oldKey],"1"); } }
      window.localStorage.setItem(_schema,"2");
    }
  }catch(e){}
  function renderReplyLimit(){
    const d=(data&&typeof data==="object")?data:{};
    const info=(d.reply_limit&&typeof d.reply_limit==="object")?d.reply_limit:{};
    const tokens=Number(info.max_tokens||0);
    setText("replyLimitText","当前 max_tokens = "+(tokens||"—")+"（≈中文 250–300 字）"+(info.provider_name?(" · "+info.provider_name):""));
    const input=$("replyLimitInput");
    if(input&&document.activeElement!==input) input.value=tokens||200;
    const btn=$("replyLimitSaveBtn");
    if(btn&&!btn.dataset.bound){
      btn.dataset.bound="1";
      btn.addEventListener("click",async()=>{
        if(!bridge){ setText("replyLimitState","桥接未连接"); return; }
        const value=Number((input||{}).value);
        setText("replyLimitState","保存中…");
        try{
          const raw=await bridge.apiPost("page/reply_limit",{max_tokens:value});
          const payload=raw&&raw.data?raw.data:raw;
          if(!payload||payload.ok===false) throw new Error((payload&&payload.message)||"保存失败");
          setText("replyLimitState",payload.restart_required?"需重启 AstrBot 生效":"已同步到 AstrBot");
        }catch(e){ setText("replyLimitState","保存失败："+(typeof describeBridgeError==="function"?describeBridgeError(e):String(e&&e.message||e))); }
      });
    }
  }
  function renderReplySplit(){
    const d=(data&&typeof data==="object")?data:{};
    const info=(d.reply_split&&typeof d.reply_split==="object")?d.reply_split:{};
    setChecked("replySplitEnabled", info.enabled===true);
    if($("replySplitMode")&&document.activeElement!==$("replySplitMode")) setVal("replySplitMode", info.mode||"astrbot");
    const eff=info.effective||{};
    setText("replySplitEffective","AstrBot 当前："+(eff.enable?"启用":"关闭")+" / 阈值 "+(eff.threshold==null?"—":eff.threshold)+" / "+String(eff.mode||"—"));
    if($("replySplitMaxChars")&&document.activeElement!==$("replySplitMaxChars")) setVal("replySplitMaxChars", info.max_chars||400);
    const btn=$("replySplitSaveBtn");
    if(btn&&!btn.dataset.bound){
      btn.dataset.bound="1";
      btn.addEventListener("click",async()=>{
        if(!bridge){ setText("replySplitState","桥接未连接"); return; }
        const body={enabled:($("replySplitEnabled")||{}).checked===true, mode:($("replySplitMode")||{}).value||"punct", max_chars:Number(($("replySplitMaxChars")||{}).value)};
        setText("replySplitState","保存中…");
        try{
          const raw=await bridge.apiPost("page/reply_split",body);
          const payload=raw&&raw.data?raw.data:raw;
          if(!payload||payload.ok===false) throw new Error((payload&&payload.message)||"保存失败");
          setText("replySplitState","已保存（由 BioCore 控制）");
        }catch(e){ setText("replySplitState","保存失败："+(typeof describeBridgeError==="function"?describeBridgeError(e):String(e&&e.message||e))); }
      });
    }
  }
  function renderReplySoft(){
    const d=(data&&typeof data==="object")?data:{};
    const info=(d.reply_soft&&typeof d.reply_soft==="object")?d.reply_soft:{};
    setChecked("replySoftEnabled", info.enabled!==false);
    if($("replySoftTargetChars")&&document.activeElement!==$("replySoftTargetChars")) setVal("replySoftTargetChars", info.target_chars||10);
    if($("replySoftMaxChars")&&document.activeElement!==$("replySoftMaxChars")) setVal("replySoftMaxChars", info.max_chars||30);
    const btn=$("replySoftSaveBtn");
    if(btn&&!btn.dataset.bound){
      btn.dataset.bound="1";
      btn.addEventListener("click",async()=>{
        if(!bridge){ setText("replySoftState","桥接未连接"); return; }
        setText("replySoftState","保存中…");
        try{
          const raw=await bridge.apiPost("page/reply_soft",{enabled:($("replySoftEnabled")||{}).checked===true,target_chars:Number(($("replySoftTargetChars")||{}).value),max_chars:Number(($("replySoftMaxChars")||{}).value)});
          const payload=raw&&raw.data?raw.data:raw;
          if(!payload||payload.ok===false) throw new Error((payload&&payload.message)||"保存失败");
          setText("replySoftState","已保存（写入提示词）");
        }catch(e){ setText("replySoftState","保存失败："+(typeof describeBridgeError==="function"?describeBridgeError(e):String(e&&e.message||e))); }
      });
    }
  }
  async function load(){
    clearTimeout(timer);
    try { bridge = window.AstrBotPluginView || window.AstrBotPluginPage || window.astrbotPluginView || null; if (!bridge && window.parent && window.parent !== window) bridge = window.parent.AstrBotPluginView || window.parent.AstrBotPluginPage || null; } catch (e) { bridge = null; }
    try{
      let _embedded = false;
      try { _embedded = !!(window.parent && window.parent !== window); } catch (e) { _embedded = false; }
      if(bridge && !_embedded){
        throw new Error("direct-open");
      }
      if(bridge){
        let ctx=null;
        try{
          ctx=await Promise.race([
            bridge.ready(),
            new Promise((resolve)=>setTimeout(()=>resolve(null),3000))
          ]);
        }catch(e){ ctx=null; }
        if(!themeInitialized) chooseTheme(ctx&&ctx.isDark);
        const raw=await Promise.race([
          bridge.apiGet("page/status",{}),
          new Promise((_,reject)=>setTimeout(()=>reject(new Error("页面桥 8 秒无响应，可能不是在 AstrBot 插件视图 iframe 内打开")),8000))
        ]);
        data=raw&&raw.data?raw.data:raw;
        setText("linkState", "已连接"); setText("topStatus", "已连接");
        $("statusDot").style.background="var(--green)";
      }else{
        if(!themeInitialized) chooseTheme(false);
        data=demo;
        setText("linkState", "预览"); setText("topStatus", "预览");
        $("statusDot").style.background="var(--amber)";
      }
      if(!data||!data.profile) throw new Error("empty status");
      render();
      checkOrbAlive();
    }catch(e){
      if(window.console&&console.error) console.error("[biocore] dashboard load failed:",e);
      const _raw = String(e&&e.message||e);
      let _friendly = _raw;
      if (_raw === "direct-open") {
        _friendly = "当前是直接打开插件页（没有 AstrBot 父窗口）。请从 AstrBot WebUI → 插件 → BioCore → 插件可视化视图 进入。";
      } else if (/401|403|未经授权|未授权|Token 无效|Token 过期|Unauthorized/i.test(_raw)) {
        _friendly = "AstrBot 登录状态已失效（API 401/403）。请重新登录 AstrBot 后台，再进入插件视图。";
      } else if (/页面桥.*无响应/.test(_raw)) {
        _friendly = "页面桥没有响应：请从 AstrBot WebUI 的插件视图打开（直接开链接不行），并确认 AstrBot 正在运行。";
      } else if (/empty status/.test(_raw)) {
        _friendly = "已连上 AstrBot，但 page/status 返回为空；请确认 BioCore 插件已启用。";
      }
      setText("linkState", "离线"); setText("topStatus", "离线");
      $("statusDot").style.background="var(--red)";
      setText("heroTitle", "连接不上 BioCore");
      setText("heroSub", _friendly + (_friendly === _raw ? "" : "（原始：" + _raw.slice(0, 120) + "）"));
      checkOrbAlive();
    }
    setText("footTime", new Date().toLocaleTimeString());
    timer=setTimeout(load,5000);
  }

  let summarySessionFilter = "";
  function _coreSnapshot(key){
    const cores=(data&&data.cores)||[];
    const want=canonicalSessionKey(key);
    const core=cores.find(c=>canonicalSessionKey(c.key)===want);
    return core&&core.snapshot?core.snapshot:null;
  }
  function _eventMessages(key, ev){
    const snap=_coreSnapshot(key);
    const hist=((snap&&snap.history)||[]).filter(h=>h&&Number(h.ts||0)>0).slice();
    const span=(ev&&ev.time_span)||{};
    const start=Number(span.start_ts||0), end=Number(span.end_ts||0);
    if(start<=0 && end<=0) return [];
    const lo=start>0?start-1800:-Infinity;
    const hi=end>0?end+1800:Infinity;
    return hist.filter(h=>Number(h.ts)>=lo&&Number(h.ts)<=hi).slice(-80);
  }
  function _msgRow(h){
    const colors={joy:"#ffb23e",sadness:"#5b8dd6",anger:"#e75b3a",fear:"#8b6bd9",loneliness:"#5f6f9e",neutral:"#8e8a82",trust:"#54b58b"};
    const emo=String(h.emotion||"neutral");
    const v=clamp(h.intensity);
    const d=h.ts?new Date(Number(h.ts)*1000):null;
    const ts=d?d.toLocaleTimeString("zh-CN",{hour:"2-digit",minute:"2-digit"}):"--";
    const color=colors[emo]||colors.neutral;
    return '<div class="msg-row"><span class="msg-ts">'+esc(ts)+'</span>'+
      '<span class="msg-emo" style="color:'+color+'">'+esc(L(emo))+'</span>'+
      '<div class="msg-track"><i style="width:'+pct(v)+';background:'+color+'"></i></div>'+
      '<b class="msg-val">'+Number(v||0).toFixed(2)+'</b>'+
      '<span class="msg-text">'+esc(String(h.text||"").replace(/\s+/g," ").slice(0,120))+'</span></div>';
  }
  function _clipText(value, limit){
    let text=String(value==null?"":value).replace(/\s+/g," ").trim();
    if(text.length>limit) text=text.slice(0,limit-1).trimEnd()+"…";
    return text;
  }
  // task-57: inline regenerate/edit for session-memory event cards. The same
  // page/event_summary API as the focus panel is reused; each card is bound by
  // data-event-id so multiple cards never interfere, and the edit draft survives
  // the 5s status poll (input events update the draft synchronously).
  let _sessEdit = null;
  const _sessBusy = {};
  const _sessMsg = {};
  function _sessEventById(eventId) {
    const evs = Array.isArray(data && data.events) ? data.events : [];
    return evs.find((ev) => String((ev && ev.id) || "") === String(eventId || "")) || null;
  }
  function _sessSetMsg(eventId, text, isError) {
    const id = String(eventId || "");
    if (!id) return;
    if (text) _sessMsg[id] = { text: String(text), error: !!isError };
    else delete _sessMsg[id];
  }
  function _sessSummaryStatus(ev) {
    if (ev && ev.summary_edited === true) return "edited";
    const s = String((ev && ev.summary_status) || "legacy").toLowerCase();
    return (s === "llm" || s === "fallback" || s === "edited") ? s : "legacy";
  }
  function _sessApplyResult(eventId, body) {
    const ev = _sessEventById(eventId);
    if (!ev || !body) return null;
    if (body.title != null) ev.title = String(body.title);
    if (body.big_summary != null) ev.big_summary = String(body.big_summary);
    if (body.small_summary != null) ev.small_summary = String(body.small_summary);
    ev.summary_status = String(body.summary_status || "edited");
    ev.summary_edited = body.summary_edited === true;
    ev.summary_updated_ts = Number(body.summary_updated_ts || 0);
    if (Array.isArray(body.summary_history)) ev.summary_history = body.summary_history;
    if (body.emotion_secondary != null) ev.emotion_secondary = String(body.emotion_secondary || "");
    if (Array.isArray(body.emotion_nuance)) ev.emotion_nuance = _emotionNuanceOf({ emotion_nuance: body.emotion_nuance });
    return ev;
  }
  async function _sessRegenerate(eventId) {
    const id = String(eventId || "");
    if (!id || _sessBusy[id]) return;
    _sessBusy[id] = true;
    _sessSetMsg(id, "");
    renderSessionMemory();
    try {
      const body = await _focusApi({ event_id: id, action: "regenerate" });
      _sessApplyResult(id, body);
      _sessSetMsg(id, "已重新总结", false);
    } catch (err) {
      _sessSetMsg(id, String((err && err.message) || err), true);
    } finally {
      _sessBusy[id] = false;
      renderSessionMemory();
    }
  }
  function _sessBeginEdit(eventId) {
    const ev = _sessEventById(eventId);
    if (!ev) return;
    _sessEdit = { id: String(eventId),
      title: String(ev.title || "重要事件").slice(0, 80),
      small: String(ev.small_summary || "").slice(0, 80),
      big: String(ev.big_summary || ev.event || ""),
      busy: false };
    _sessSetMsg(eventId, "");
    renderSessionMemory();
  }
  function _sessCancelEdit() {
    if (_sessEdit) _sessSetMsg(_sessEdit.id, "");
    _sessEdit = null;
    renderSessionMemory();
  }
  async function _sessSaveEdit() {
    const draft = _sessEdit;
    if (!draft || draft.busy) return;
    const title = String(draft.title || "").trim();
    const small = String(draft.small || "").trim();
    const big = String(draft.big || "").trim();
    if (!title) { _sessSetMsg(draft.id, "标题不能为空", true); renderSessionMemory(); return; }
    if (title.length > 80) { _sessSetMsg(draft.id, "标题不能超过 80 字", true); renderSessionMemory(); return; }
    if (!big) { _sessSetMsg(draft.id, "大总结不能为空", true); renderSessionMemory(); return; }
    if (small.length > 80) { _sessSetMsg(draft.id, "小总结不能超过 80 字", true); renderSessionMemory(); return; }
    draft.busy = true;
    _sessSetMsg(draft.id, "");
    renderSessionMemory();
    try {
      const body = await _focusApi({ event_id: draft.id, action: "update",
        title: title, small_summary: small, big_summary: big });
      _sessApplyResult(draft.id, body);
      _sessEdit = null;
      _sessSetMsg(draft.id, "已保存", false);
    } catch (err) {
      _sessSetMsg(draft.id, String((err && err.message) || err), true);
    } finally {
      if (_sessEdit && _sessEdit.id === draft.id) _sessEdit.busy = false;
      renderSessionMemory();
    }
  }
  // task-45: restore a downgraded memory point from the session list.
  async function _sessRestore(eventId) {
    const id = String(eventId || "");
    if (!id || _sessBusy[id]) return;
    _sessBusy[id] = true;
    _sessSetMsg(id, "恢复中…", false);
    renderSessionMemory();
    try {
      await _focusApi({ event_id: id, action: "restore" }, "page/memory_point_feedback");
      _sessBusy[id] = false;
      _sessSetMsg(id, "已恢复", false);
      renderSessionMemory();
      await _focusReloadData();
      renderSessionMemory();
    } catch (err) {
      _sessBusy[id] = false;
      _sessSetMsg(id, String((err && err.message) || err), true);
      renderSessionMemory();
    }
  }
  function _sessEditForm(ev) {
    const draft = _sessEdit || {};
    const busy = !!draft.busy;
    return '<div class="memory-card-edit" data-event-id="' + esc(String((ev && ev.id) || "")) + '">' +
      '<label class="memory-edit-field"><small>标题（≤80 字）</small>' +
      '<input type="text" class="js-sess-title" maxlength="80" value="' + esc(String(draft.title || "")) + '"></label>' +
      '<label class="memory-edit-field"><small>小总结（≤80 字）</small>' +
      '<textarea class="js-sess-small" maxlength="80" rows="2">' + esc(String(draft.small || "")) + '</textarea></label>' +
      '<label class="memory-edit-field"><small>大总结</small>' +
      '<textarea class="js-sess-big" rows="6">' + esc(String(draft.big || "")) + '</textarea></label>' +
      '<div class="memory-card-ops"><button type="button" class="btn mini js-sess-save"' + (busy ? " disabled" : "") + '>保存</button>' +
      '<button type="button" class="btn mini js-sess-cancel"' + (busy ? " disabled" : "") + '>取消</button></div>' +
      '</div>';
  }
  function _sessCardHtml(ev, idx) {
    const eventId = String((ev && ev.id) || "");
    const msgs = _eventMessages(summarySessionFilter, ev);
    const imp = Number(ev.importance || 0).toFixed(2);
    const cent = (ev.centrality == null ? 0.5 : Number(ev.centrality)).toFixed(2);
    const when = ev.ts ? new Date(Number(ev.ts) * 1000).toLocaleString("zh-CN",
      { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "";
    const status = String((ev.source_check && ev.source_check.status) || "ok");
    const evConf = (ev.confidence == null || ev.confidence === "") ? null : Number(ev.confidence);
    const warnFlags = (evConf != null && evConf < 0.6
      ? '<span class="mem-flag mem-flag-warn">低置信 ' + evConf.toFixed(2) + '</span>' : "") +
      (status !== "ok" ? '<span class="mem-flag mem-flag-warn">来源待核 ' + esc(status) + '</span>' : "");
    const sessionLabelText = sessionLabel(ev.session);
    const emoBadges = '<span class="mem-emo-tag">情绪 ' + esc(emotionLabel(ev.emotion)) + '</span>' +
      '<span class="mem-emo-tag">次 ' + esc(ev.emotion_secondary ? emotionZh(ev.emotion_secondary) : "推断（示意）") + '</span>';
    const nuanceLine = _emotionNuanceLine(emotionLabel(ev.emotion),
      ev.emotion_secondary ? emotionZh(ev.emotion_secondary) : "推断（示意）",
      _emotionNuanceOf(ev));
    const nuanceHtml = nuanceLine
      ? '<div class="mem-emotion-nuance">情绪层次：' + esc(nuanceLine) + '</div>' : "";
    const sumStatus = _sessSummaryStatus(ev);
    const badge = { llm: "AI 总结", fallback: "摘录总结", legacy: "旧事件", edited: "已编辑" }[sumStatus] || "旧事件";
    const badgeCls = (sumStatus === "edited") ? "is-edited"
      : ("is-" + ((sumStatus === "llm" || sumStatus === "fallback") ? sumStatus : "legacy"));
    const smallSrc = String(ev.small_summary || "").trim() || _clipText(ev.title || "", 80);
    const small = _clipText(smallSrc, 80);
    const bigText = String(ev.big_summary || ev.event || "").trim();
    const isEdit = !!(_sessEdit && _sessEdit.id === eventId);
    const busy = !!_sessBusy[eventId];
    const msg = _sessMsg[eventId] || null;
    const updated = (Number(ev.summary_updated_ts || 0) > 0) ? _focusWhen(ev.summary_updated_ts) : "";
    const readBody = isEdit ? _sessEditForm(ev) : (
      '<p class="memory-event-small"><small>小总结</small><span>' + esc(small || "—") + '</span></p>' +
      '<div class="memory-event-big"><div class="memory-event-big-head"><small>大总结</small>' +
      '<span class="memory-status-badge ' + badgeCls + '">' + esc(badge) + '</span></div>' +
      '<p class="memory-event-text">' + esc(bigText || "—") + '</p></div>');
    // task-45: downgraded points stay listed with a visible 「恢复」 action.
    const downgraded = _isDowngraded(ev);
    const downgradedFlag = downgraded
      ? '<span class="mem-flag mem-flag-warn" title="被重新判定降级为归档，可点「恢复」撤销">已降级</span>'
      : "";
    const opsRow = isEdit ? "" : ('<div class="memory-card-ops">' +
      '<button type="button" class="btn mini js-sess-regen" data-event-id="' + esc(eventId) + '"' +
      (busy ? " disabled" : "") + '>' + (busy ? "重新总结中…" : "重新总结") + '</button>' +
      '<button type="button" class="btn mini js-sess-edit" data-event-id="' + esc(eventId) + '">编辑总结</button>' +
      (downgraded
        ? '<button type="button" class="btn mini is-restore js-sess-restore" data-event-id="' +
          esc(eventId) + '"' + (busy ? " disabled" : "") + '>恢复</button>'
        : '') +
      '<span class="sess-card-msg' + (msg && msg.error ? " is-error" : "") + '">' +
      esc(msg ? msg.text : "") + '</span></div>');
    const hasMsgs = msgs.length > 0;
    return '<div class="memory-card" data-event-id="' + esc(eventId) + '" data-session="' + esc(String(ev.session || "")) + '">' +
      '<div class="memory-card-head"><span class="memory-level-tag">总结</span>' +
      '<b>' + esc(_clipText(ev.title || "重要事件", 80)) + '</b>' +
      '<span class="hint">' + esc(when) + '</span>' +
      '<span class="mem-session-tag">' + esc(sessionLabelText) + '</span>' + warnFlags + downgradedFlag + emoBadges + '</div>' +
      nuanceHtml +
      readBody + opsRow +
      '<div class="memory-scores"><small>重要度 ' + imp + '</small><small>centrality ' + cent + '</small>' +
      '<small>来源 ' + esc(status) + '</small>' + (updated ? '<small>更新 ' + esc(updated) + '</small>' : "") + '</div>' +
      '<div class="memory-important"><span class="memory-level-tag">重要事件</span>' +
      '<small>' + esc(_clipText(ev.central_details || "", 260)) + '</small>' +
      '<small>意义：' + esc(_clipText(ev.meaning_to_her || "", 220)) + '</small>' +
      '<small>事件感悟（单事件）：' + esc(_clipText(ev.reflection || "", 220)) + '</small></div>' +
      (hasMsgs
        ? '<button type="button" class="btn mini js-msg-toggle" data-idx="' + idx + '" data-count="' + msgs.length + '">收起消息 · ' + msgs.length + ' 条</button>' +
          '<div class="memory-messages" data-idx="' + idx + '">' + msgs.map(_msgRow).join("") + '</div>'
        : '<div class="memory-event-nowin">旧事件没有逐条消息窗口</div>') +
      '</div>';
  }
  function renderSessionMemory() {
    if (!data) return;
    const all = Array.isArray(data.events) ? data.events : [];
    const entries = sessionEntries();
    const sessions = entries.map((en) => en.canonical);
    const sel = $("summarySession"), empty = $("summaryEmpty"),
          block = $("sessionSummaryBlock"), hint = $("summaryHint");
    if (!sessions.length) {
      if (sel) { sel.innerHTML = '<option value="">暂无已总结会话</option>'; sel.disabled = true; }
      if (empty) empty.style.display = "block";
      if (block) block.innerHTML = "";
      if (hint) hint.textContent = "还没有已总结的会话";
      return;
    }
    if (sel) {
      sel.disabled = false;
      if (!summarySessionFilter || sessions.indexOf(summarySessionFilter) < 0) summarySessionFilter = sessions[0];
      sel.innerHTML = entries.map((en) => {
        const raw = (en.variants || []).join(" | ") || en.canonical;
        return '<option value="' + esc(en.canonical) + '" title="' + esc(raw) + '">' + esc(en.label) + '</option>';
      }).join("");
      sel.value = summarySessionFilter;
    }
    if (!block) return;
    const evs = all.filter((ev) => canonicalSessionKey(ev.session) === summarySessionFilter)
      .sort((a, b) => Number(b.importance || 0) - Number(a.importance || 0) ||
        Number(b.ts || 0) - Number(a.ts || 0));
    const entry = entries.filter((en) => en.canonical === summarySessionFilter)[0];
    if (empty) {
      empty.style.display = evs.length ? "none" : "block";
      if (!evs.length) {
        let extra = "";
        if (entry && entry.hasMemory) {
          const idx = memoryIndexValue() || [];
          const n = idx.filter((s) => canonicalSessionKey(s.session) === summarySessionFilter)
            .reduce((acc, s) => acc + ((s.entries || []).length), 0);
          extra = "；该会话另有 " + n + " 条本地记忆，可在「会话记忆 → 记忆元数据」查看";
        }
        empty.textContent = "本会话还没有归档的重要事件" + extra + "。";
      }
    }
    if (hint) hint.textContent = "已总结 " + entries.length + " 个会话 · 本会话 " + evs.length + " 个重要事件";
    block.innerHTML = evs.map((ev, idx) => _sessCardHtml(ev, idx)).join("");
    if (!block.dataset.bound) {
      block.addEventListener("click", (e) => {
        const target = e.target || {};
        if (!target.closest) return;
        const regen = target.closest(".js-sess-regen");
        if (regen) { _sessRegenerate(regen.dataset.eventId); return; }
        const edit = target.closest(".js-sess-edit");
        if (edit) { _sessBeginEdit(edit.dataset.eventId); return; }
        const restore = target.closest(".js-sess-restore");
        if (restore) { _sessRestore(restore.dataset.eventId); return; }
        const save = target.closest(".js-sess-save");
        if (save) { _sessSaveEdit(); return; }
        const cancel = target.closest(".js-sess-cancel");
        if (cancel) { _sessCancelEdit(); return; }
        const btn = target.closest(".js-msg-toggle");
        if (!btn) return;
        const box = block.querySelector('.memory-messages[data-idx="' + btn.dataset.idx + '"]');
        if (box) {
          box.hidden = !box.hidden;
          const n = btn.dataset.count || "";
          btn.textContent = (box.hidden ? "全部消息 · " + n + " 条" : "收起消息 · " + n + " 条");
        }
      });
      block.addEventListener("input", (e) => {
        if (!_sessEdit) return;
        const t = e.target || {};
        if (!t.classList) return;
        if (t.classList.contains("js-sess-title")) _sessEdit.title = String(t.value || "");
        else if (t.classList.contains("js-sess-small")) _sessEdit.small = String(t.value || "");
        else if (t.classList.contains("js-sess-big")) _sessEdit.big = String(t.value || "");
      });
      block.dataset.bound = "1";
    }
  }

  const LLM_FUNCTIONS=["persona_compile","event_summary","event_ranking","insight","memory_summary","image_caption",
  "relationship_impression","repair_hint","empathy_hint","pragmatics_hint","tom_probe","diary","relationship_narrative","humor_hint"];
  const MEM_SOURCE_LABELS={direct:"用户直述",media:"图片/语音",told:"转述",retrieved:"检索",inferred:"推断",unknown:"未标注"};
  const MEM_TIER_LABELS={hot:"HOT 热",warm:"WARM 温",cold:"COLD 冷"};
  const MEM_REL_FIELDS=[["trust","信任"],["closeness","亲近"],["conflict","冲突"],["repair","修复"],["predictability","可预测"]];
  let memSessionFilter=storeGet("bio_mem_session","");
  let relUserFilter=storeGet("bio_rel_user","");
  const memOps={}, memOpStates={};
  const memKey=(session,id)=>String(session||"")+"|"+String(id||"");
  function memWhen(ts){
    const n=Number(ts||0);
    if(!n) return "--";
    try { return new Date(n*1000).toLocaleString("zh-CN",{month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"}); } catch(e){ return "--"; }
  }
  function memSourceLabel(src,legacy){ if(legacy) return "用户直述（旧数据）"; const k=String(src||"unknown").toLowerCase(); return MEM_SOURCE_LABELS[k]||k; }
  function memTierLabel(tier){ const k=String(tier||"").toLowerCase(); return MEM_TIER_LABELS[k]||(k?k.toUpperCase():"—"); }
  function memoryIndexValue(){
    const d=data||{};
    if(Array.isArray(d.memory_index)) return d.memory_index;
    if(d.memory&&Array.isArray(d.memory.index)) return d.memory.index;
    if(Array.isArray(d.memory_entries)){
      const map=new Map();
      d.memory_entries.forEach(e=>{
        if(!e||typeof e!=="object") return;
        const s=String(e.session||e.memory_session||"");
        if(!map.has(s)) map.set(s,{session:s,entries:[],tombstones:[]});
        map.get(s).entries.push(e);
      });
      return Array.from(map.values());
    }
    return null;
  }
  function relationshipsValue(){
    const d=data||{};
    if(Array.isArray(d.relationships)) return d.relationships;
    if(Array.isArray(d.users)) return d.users;
    if(d.users&&Array.isArray(d.users.items)) return d.users.items;
    return null;
  }
  // One ball per memory entry, so the orb keeps its "记忆球" layer even when
  // the archived-event list is sparse. Falls back to events in orb.js.
  function memoryBallsFromIndex(){
    const idx=memoryIndexValue();
    if(!Array.isArray(idx)) return [];
    const out=[];
    idx.forEach(session=>{
      (session&&Array.isArray(session.entries)?session.entries:[]).forEach(e=>{
        if(!e||typeof e!=="object") return;
        const text=String(e.text||"").trim();
        if(!text) return;
        // Balls are generated only AFTER consolidation/summarization: raw
        // per-turn memories do not become balls; summarized originals and the
        // summary rows (role=summary) do.
        const role=String(e.role||"");
        if(!(e.summarized===true || role==="summary")) return;
        out.push({
          _kind:"memory", id:String(e.id||text.slice(0,12)),
          session:String(session.session||""),
          pinned:_isPinned(session.session, e.id, e.pinned),
          title:text.slice(0,28), event:text.slice(0,140),
          meaning_to_her:text.slice(0,140), central_details:text.slice(0,140),
          ts:Number(e.ts||0), importance:Number(e.importance||0.5),
          centrality:0.5, recall_count:Number(e.hits||0), merge_count:0,
          self_defining:!!e.self_defining,
          emotion:String(e.encoding_emotion||"neutral")||"neutral",
          emotion_known:!!String(e.encoding_emotion||"").trim(),
          emotion_secondary:String(e.encoding_emotion_secondary||""),
          memory_source:String(e.memory_source||""),
          memory_confidence:e.memory_confidence==null?null:Number(e.memory_confidence),
          last_recall:Number(e.last_used||e.ts||0),
          summarized:true, role:role,
        });
      });
    });
    // One consolidation batch produces summary rows + summarized originals;
    // show summary rows only to avoid duplicate balls for the same group.
    const summaries=out.filter(x=>x.role==="summary");
    const pool=summaries.length?summaries:out;
    pool.sort((a,b)=>Number(b.importance||0)-Number(a.importance||0)||Number(b.ts||0)-Number(a.ts||0));
    return pool.slice(0,60);
  }
  // Archived events are already event-summary artifacts (LLM ranked/summarized
  // before archiving), so they are valid "summarized" balls even when the raw
  // memory cluster has not been consolidated yet. This restores e.g. the
  // late-night confession-clarification ball.
  // task-45: a memory point downgraded by 「重新判定（archive_only/skip）」.
  // Prefer the backend fields (downgraded_by_reevaluate / reevaluate_verdict);
  // while a projection does not expose downgraded_by_reevaluate, fall back to
  // the documented combination memory_point=false + user_marked=false +
  // importance==0.15 (the forced floor written by the downgrade path). Switch
  // to the backend field only once it reaches every projection.
  function _isDowngraded(detail){
    const d=detail||{};
    if(d.downgraded_by_reevaluate===true) return true;
    const verdict=(d.reevaluate_verdict&&typeof d.reevaluate_verdict==="object")?d.reevaluate_verdict:null;
    if(d.memory_point===false&&verdict){
      const decision=String(verdict.decision||"").toLowerCase();
      if(decision==="archive_only"||decision==="skip") return true;
    }
    const imp=Number(d.importance);
    return d.memory_point===false&&d.user_marked!==true
      &&Number.isFinite(imp)&&Math.abs(imp-0.15)<=0.001;
  }
  function eventBallsFromArchive(){
    const evs=Array.isArray(data.events)?data.events:[];
    // task-33: archive-only rows (memory_point=false) stay in the archive for
    // retrieval but are NOT memory points, so they get no ball.
    // task-60: a downgraded ("not a memory point") event must NOT get a ball.
    // Recovery stays available from the session memory list / focus panel.
    return evs.filter(e=>e&&typeof e==="object"
        &&e.memory_point!==false).map(e=>{
      const text=String(e.event||e.title||"").trim();
      if(!text) return null;
      return {_kind:"event", id:String(e.id||("evt_"+Number(e.ts||0))),
        title:String(e.title||text.slice(0,28)), event:text.slice(0,160),
        big_summary:String(e.big_summary||e.event||text),
        small_summary:String(e.small_summary||""),
        summary_status:String(e.summary_status||"legacy"),
        meaning_to_her:String(e.meaning_to_her||""),
        central_details:String(e.central_details||""),
        ts:Number(e.ts||0), importance:Number(e.importance==null?0.5:e.importance),
        centrality:Number(e.centrality==null?0.5:e.centrality),
        recall_count:Number(e.recall_count||0), merge_count:Number(e.merge_count||0),
        self_defining:!!e.self_defining,
        emotion:String(e.emotion||"neutral"), emotion_known:!!String(e.emotion||"").trim(),
        emotion_secondary:String(e.emotion_secondary||""),
        worthiness:(e.worthiness&&typeof e.worthiness==="object")?e.worthiness:null,
        user_marked:e.user_marked===true,
        memory_point:e.memory_point!==false,
        downgraded:_isDowngraded(e),
        downgraded_by_reevaluate:e.downgraded_by_reevaluate===true,
        reevaluate_verdict:(e.reevaluate_verdict&&typeof e.reevaluate_verdict==="object")?e.reevaluate_verdict:null,
        last_recall:Number(e.last_recall||e.ts||0), summarized:true, role:"event"};
    }).filter(Boolean).sort((a,b)=>Number(b.importance||0)-Number(a.importance||0)||Number(b.ts||0)-Number(a.ts||0)).slice(0,10);
  }
  // Only important memories form balls by default: importance >= 0.60 or
  // self-defining (identity-central) memory. The toggle restores "show all".
  const MEMORY_BALL_IMPORTANCE=0.60;
  function importantMemoryBalls(list){
    if(!Array.isArray(list)) return [];
    if(!visual.memoryBallsImportant) return list;
    return list.filter(ev=>ev&&(ev._kind==="event"||ev.self_defining===true||Number(ev.importance||0)>=MEMORY_BALL_IMPORTANCE));
  }
  // Read-only legend row under the orb. visual.orbLegend (设置 → 球体图层) hides
  // it entirely; otherwise it explains what the balls are and what size means.
  function updateOrbLegend(){
    const el=$("orbMemLegend");
    if(!el) return;
    if(!visual.orbLegend){
      el.textContent="";
      el.hidden=true;
      return;
    }
    el.hidden=false;
    if(!visual.memoryNodes){
      el.textContent="中心球 = 当前情绪球（只有一个）· 记忆节点已关闭，可在 设置 → 球体图层 开启";
      return;
    }
    const st=window.__biocoreState||{};
    const all=Array.isArray(st.memories)?st.memories:[];
    const shown=importantMemoryBalls(all).slice(0,10);
    if(!shown.length){
      el.textContent="还没有总结后的球：记忆巩固/总结后生成记忆球；归档事件会作为事件总结球显示";
      return;
    }
    if(shown.every(b=>b._kind==="event")){
      el.textContent="事件总结球 ×"+shown.length+"：已归档的重要事件 · 球大小=重要度 · 记忆总结后追加 · 悬停查看";
      return;
    }
    const suffix=visual.memoryBallsImportant?"总结后重要记忆（重要度≥0.60 或自指）":"总结后记忆（最多 10）";
    el.textContent="记忆球 ×"+shown.length+"："+suffix+" · 球大小=重要度 · 外环数=情绪强度 · 悬停查看";
  }
  function normMemEntry(e){
    const src=(e&&typeof e==="object")?e:{};
    const conf=src.memory_confidence==null?(src.confidence==null?null:Number(src.confidence)):Number(src.memory_confidence);
    const versions=Array.isArray(src.previous_versions)?src.previous_versions.length:Number(src.previous_versions||0);
    return {id:String(src.id||src.entry_id||""), text:String(src.text||""),
      role:String(src.role||"user"), ts:Number(src.ts||0),
      importance:Number(src.importance||0), hits:Number(src.hits||0),
      source:String(src.memory_source||src.source||"direct").toLowerCase(),
      legacy:!!src.legacy,
      confidence:conf, tier:String(src.memory_tier||src.tier||"").toLowerCase(),
      conflict:!!src.conflict, lastOp:String(src.last_write_op||""),
      versions:versions, summarized:!!src.summarized,
      sensitive:!!src.sensitive, poison:!!src.poison_risk,
      links:Number(src.links||0), scope:String(src.scope||""),
      verification:String(src.verification||""),
      // G7/G8 read-time decay: prefer server-computed effective values; if the
      // backend does not expose them yet, derive only when the exact anchor
      // (last_recall) and the assoc map are present, never by guessing.
      effectiveImportance:Number(src.effective_importance==null?NaN:Number(src.effective_importance)),
      effectiveAssoc:Number(src.effective_assoc==null?NaN:Number(src.effective_assoc)),
      lastRecall:Number(src.last_recall||0),
      pinned:src.pinned===true};
  }
  function renderMemoryMeta(){
    const sel=$("memSessionFilter"), list=$("memEntryList"), empty=$("memEmpty"),
          note=$("memIndexNote"), tomb=$("memTombstoneList"), stats=$("memoryMetaStats");
    const memorySessions=memoryIndexValue();
    if(!sel||!list) return;
    if(memorySessions===null){
      sel.innerHTML='<option value="">后端未提供</option>'; sel.disabled=true;
      list.innerHTML="";
      if(tomb) tomb.innerHTML="";
      if(empty){ empty.style.display="block"; empty.textContent="当前后端版本未提供记忆明细（page/status.memory_index）；升级后自动显示，删除/回滚按钮也会随之出现。"; }
      if(note) note.textContent="后端未提供记忆索引";
      if(stats) stats.textContent="当前后端版本只返回记忆数量统计，未提供 source/confidence/tier/conflict/tombstone 明细。";
      return;
    }
    const valid=memorySessions.filter(s=>s&&Array.isArray(s.entries));
    if(!valid.length){
      sel.innerHTML='<option value="">暂无记忆</option>'; sel.disabled=true;
      list.innerHTML="";
      if(tomb) tomb.innerHTML="";
      if(empty){ empty.style.display="block"; empty.textContent="还没有可展示的记忆条目。"; }
      if(note) note.textContent="0 个会话";
      if(stats) stats.textContent="本地记忆：-- 条 / -- 会话（元数据为空）";
      return;
    }
    let total=0, low=0, conflicts=0, summarized=0, tombstones=0;
    valid.forEach(s=>{
      (s.entries||[]).map(normMemEntry).forEach(e=>{
        total++;
        if(e.confidence!=null&&e.confidence<0.6) low++;
        if(e.conflict) conflicts++;
        if(e.summarized) summarized++;
      });
      tombstones+=(Array.isArray(s.tombstones)?s.tombstones.length:0);
    });
    if(stats){
      const trace=(data&&Array.isArray(data.last_cause_trace))?data.last_cause_trace:[];
      // The strategy hint moved to 活动会话 → 记忆元数据 (full 140-char bound +
      // posture decode); this line keeps only the compact counts.
      stats.textContent="元数据："+total+" 条 · 低置信 "+low+" · 冲突 "+conflicts+" · 已总结 "+summarized+" · 墓碑 "+tombstones+" · trace "+trace.length+"（策略提示见 记忆元数据）。";
    }
    // task-55: the dropdown is the canonical union (memory + events + live cores
    // + relationships), and one canonical choice merges every ":"/"_" raw variant
    // of the same real session. Memory rows without a match stay selectable.
    const union=sessionEntries();
    const canonKeys=union.map(en=>en.canonical);
    // migrate a previously stored raw key (":" or "_") to its canonical form
    if(memSessionFilter) memSessionFilter=canonicalSessionKey(memSessionFilter);
    if(memSessionFilter && canonKeys.indexOf(memSessionFilter)<0) memSessionFilter="";
    if(!memSessionFilter){
      const firstWithMemory=union.filter(en=>en.hasMemory)[0];
      memSessionFilter=firstWithMemory?firstWithMemory.canonical:(canonKeys[0]||"");
    }
    sel.disabled=union.length<2;
    sel.innerHTML=union.map(en=>{
      const raw=(en.variants||[]).join(" | ")||en.canonical;
      const label=en.label+(en.hasMemory?"":"（无记忆）");
      return '<option value="'+esc(en.canonical)+'" title="'+esc(raw)+'">'+esc(label)+'</option>';
    }).join("");
    sel.value=memSessionFilter;
    const matched=valid.filter(s=>canonicalSessionKey(s.session)===memSessionFilter);
    const currentSession=matched.length?String(matched[0].session||""):"";
    const mergedEntries=[];
    const seen={};
    matched.forEach(s=>{
      (s.entries||[]).forEach((entry,idx)=>{
        const e=normMemEntry(entry);
        const k=String(e.id||("idx"+idx));
        if(seen[k]) return;
        seen[k]=1;
        mergedEntries.push(Object.assign({},e,{_session:String(s.session||"")}));
      });
    });
    const mergedTombstones=[];
    matched.forEach(s=>{
      (Array.isArray(s.tombstones)?s.tombstones:[]).forEach(t=>{
        mergedTombstones.push(Object.assign({},(t&&typeof t==="object")?t:{text:String(t||"")},{_session:String(s.session||"")}));
      });
    });
    const shown=mergedEntries.filter(e=>e.id||e.text).sort((a,b)=>Number(b.ts||0)-Number(a.ts||0)).slice(0,40);
    if(empty) empty.style.display=shown.length?"none":"block";
    if(empty&&!shown.length) empty.textContent="这个会话还没有可展示的记忆条目。";
    if(note) note.textContent="已索引 "+union.length+" 个会话 · 本会话 "+shown.length+" 条"+(matched.length>1?("（合并 "+matched.length+" 个原始 key）"):"");
    list.innerHTML=shown.map((e,idx)=>{
      const rowSession=String(e._session||currentSession||memSessionFilter);
      const key=memKey(rowSession,e.id||("idx"+idx));
      const armed=memOps[key]||null;
      const stateText=memOpStates[key]||"";
      const confText=e.confidence==null?"—":Number(e.confidence).toFixed(2);
      const confW=(e.confidence==null?0:clamp(e.confidence))*100;
      const lowConf=e.confidence!=null&&e.confidence<0.6;
      const unknownSrc=e.source==="unknown"||e.source==="inferred";
      const pinnedRow=_isPinned(rowSession,e.id,e.pinned);
      const flags=[
        pinnedRow?'<span class="mem-flag mem-flag-ok mem-flag-pin" title="已钉住：固定事实，不参与容量淘汰">已钉住</span>':"",
        lowConf?'<span class="mem-flag mem-flag-warn">低置信</span>':"",
        unknownSrc?'<span class="mem-flag mem-flag-warn">'+esc(memSourceLabel(e.source))+'</span>':"",
        e.conflict?'<span class="mem-flag mem-flag-danger">冲突已更新</span>':"",
        e.versions>0?'<span class="mem-flag mem-flag-ok">可回滚 ×'+e.versions+'</span>':"",
        e.summarized?'<span class="mem-flag">已总结</span>':"",
        e.legacy?'<span class="mem-flag mem-flag-ok">旧数据·直述</span>':"",
        e.sensitive?'<span class="mem-flag mem-flag-warn">敏感</span>':"",
        e.poison?'<span class="mem-flag mem-flag-danger">注入风险</span>':"",
        e.verification==="verified"?'<span class="mem-flag mem-flag-ok">已验证</span>':"",
        e.links>0?'<span class="mem-flag mem-flag-ok" title="存储的 links 条数；检索用 30 天半衰的共召回有效值">关联 '+e.links+'</span>':"",
        e.scope==="session"?'<span class="mem-flag">会话内</span>':""
      ].filter(Boolean).join("");
      // Read-only effective value (G7/G8): server value first, else recompute
      // from the stored anchor only when the exact fields are present.
      let impText="存储 "+Number(e.importance||0).toFixed(2);
      let effImp=Number.isFinite(e.effectiveImportance)?e.effectiveImportance:NaN;
      if(!Number.isFinite(effImp)&&e.lastRecall>0){
        const age=_ageDaysFrom(e.lastRecall);
        effImp=Math.max(MEM_IMPORTANCE_FLOOR,Math.min(1,Number(e.importance||0.5)*_decayWeight(age,MEM_HALF_LIFE_DAYS)));
      }
      if(Number.isFinite(effImp)) impText+=" → 有效 "+Number(effImp).toFixed(2);
      let linkText="关联 "+Number(e.links||0)+" 条";
      if(Number.isFinite(e.effectiveAssoc)) linkText+="（有效 "+Number(e.effectiveAssoc).toFixed(0)+"）";
      const delLabel=armed&&armed.op==="delete"?"再点确认删除":"删除";
      const rbLabel=armed&&armed.op==="rollback"?"再点确认回滚":"回滚";
      const rbDisabled=e.versions>0?"":' disabled title="没有上一版本"';
      const memSessionTag='<span class="mem-session-tag" title="'+esc(rowSession)+'">'+esc(sessionLabel(rowSession))+'</span>';
      return '<div class="mem-card" data-key="'+esc(key)+'" data-session="'+esc(rowSession)+'" data-id="'+esc(e.id)+'">'+
        '<div class="mem-card-head">'+
          '<span class="mem-tier mem-tier-'+(e.tier||"unknown")+'">'+esc(memTierLabel(e.tier))+'</span>'+
          '<span class="mem-source">来源 '+esc(memSourceLabel(e.source,e.legacy))+'</span>'+
          memSessionTag+flags+
          '<span class="hint">'+esc(memWhen(e.ts))+' · #'+esc(String(e.id||"").slice(0,12)||"—")+'</span>'+
        '</div>'+
        '<p class="mem-text">'+esc(_clipText(e.text||"",320))+'</p>'+
        '<div class="mem-meta-row">'+
          '<div class="mem-conf"><small>置信度</small><div class="mem-conf-track"><i style="width:'+confW.toFixed(0)+'%"></i></div><b>'+esc(confText)+'</b></div>'+
          '<small title="存储值；检索按 30 天半衰、下限 0.15 的有效重要度排序">'+esc(impText)+'</small>'+
          '<small title="存储的 links 条数（未衰减）">'+esc(linkText)+'</small>'+
          '<small>召回 '+Number(e.hits||0)+' 次</small>'+
          '<small>写入 '+esc(e.lastOp||"—")+'</small>'+
        '</div>'+
        '<div class="mem-actions">'+
          '<button type="button" class="btn mini" data-mem-op="rollback" data-key="'+esc(key)+'" data-session="'+esc(rowSession)+'" data-id="'+esc(e.id)+'"'+rbDisabled+'>'+rbLabel+'</button>'+
          '<button type="button" class="btn mini danger" data-mem-op="delete" data-key="'+esc(key)+'" data-session="'+esc(rowSession)+'" data-id="'+esc(e.id)+'"'+(e.id?"":' disabled title="缺少条目 ID，无法删除"')+'>'+delLabel+'</button>'+
          '<span class="mem-op-state">'+esc(stateText)+'</span>'+
        '</div>'+
      '</div>';
    }).join("");
    if(tomb){
      tomb.innerHTML=mergedTombstones.length?mergedTombstones.slice().reverse().slice(0,10).map(t=>{
        const item=(t&&typeof t==="object")?t:{text:String(t||"")};
        const _sid=String(item._session||currentSession||memSessionFilter);
        const _tid=String(item.id||"");
        return '<div class="mem-tomb-row"><span class="mem-flag mem-flag-danger">已删除</span><small>'+esc(memWhen(item.ts))+' · #'+esc(_tid.slice(0,12))+'</small><span class="mem-tomb-text">'+esc(String(item.text||"").slice(0,160))+'</span>'+
          (_tid?'<button type="button" class="btn mini" data-mem-restore="1" data-session="'+esc(_sid)+'" data-id="'+esc(_tid)+'">恢复</button>':'')+
          '</div>';
      }).join(""):'<div class="empty-mini">这个会话没有墓碑记录。</div>';
    }
    if(!list.dataset.bound){
      list.addEventListener("click",onMemAction);
      list.dataset.bound="1";
    }
    if(tomb&&!tomb.dataset.bound){
      tomb.addEventListener("click",onTombAction);
      tomb.dataset.bound="1";
    }
  }

  async function onTombAction(e){
    const target=e.target||{};
    const btn=target.closest?target.closest("[data-mem-restore]"):null;
    if(!btn) return;
    const session=String(btn.dataset.session||"");
    const id=String(btn.dataset.id||"");
    if(!session||!id) return;
    if(!bridge){ window.alert("未连接 AstrBot 页面桥，无法恢复"); return; }
    btn.disabled=true; btn.textContent="恢复中…";
    try{
      const path="page/memory/restore/"+encodeURIComponent(session)+"/"+encodeURIComponent(id);
      const raw=await bridge.apiPost(path,{});
      const payload=raw&&raw.data?raw.data:raw;
      if(!payload||payload.status==="error"||payload.status==="fail") throw new Error((payload&&payload.message)||"恢复失败");
      btn.textContent="已恢复";
      setTimeout(()=>{ try{ load(); }catch(err){} },500);
    }catch(err){
      btn.disabled=false; btn.textContent="恢复";
      window.alert("恢复失败："+String(err&&err.message||err));
    }
  }
  function onMemAction(e){
    const target=e.target||{};
    const btn=target.closest?target.closest("[data-mem-op]"):null;
    if(!btn) return;
    const op=String(btn.dataset.memOp||"");
    const key=String(btn.dataset.key||"");
    const session=String(btn.dataset.session||"");
    const id=String(btn.dataset.id||"");
    if(!op||!key||!id) return;
    const armed=memOps[key];
    if(!armed||armed.op!==op){
      memOps[key]={op:op,at:Date.now()};
      memOpStates[key]=op==="delete"?"再点一次确认删除（5 秒内有效）":"再点一次确认回滚（5 秒内有效）";
      renderMemoryMeta();
      setTimeout(()=>{
        const cur=memOps[key];
        if(cur&&cur.op===op){ delete memOps[key]; if(memOpStates[key]&&/再点一次/.test(memOpStates[key])) delete memOpStates[key]; }
        renderMemoryMeta();
      },5000);
      return;
    }
    delete memOps[key];
    runMemOp(op,session,id,key);
  }
  async function runMemOp(op,session,id,key){
    const setState=(t)=>{
      memOpStates[key]=t;
      const cards=[].slice.call(document.querySelectorAll("#memEntryList .mem-card"));
      const card=cards.filter(c=>c.dataset.key===key)[0];
      const el=card?card.querySelector(".mem-op-state"):null;
      if(el) el.textContent=t;
    };
    if(!bridge){ setState("未连接 AstrBot 页面桥，无法操作"); return; }
    setState(op==="delete"?"正在删除…":"正在回滚…");
    try{
      const path="page/memory/"+op+"/"+encodeURIComponent(session)+"/"+encodeURIComponent(id);
      const raw=await bridge.apiPost(path,{});
      const payload=raw&&raw.data?raw.data:raw;
      if(!payload||payload.status==="error"||payload.status==="fail") throw new Error((payload&&payload.message)||"操作失败");
      setState(op==="delete"?"已删除（保留墓碑）":"已回滚到上一版本");
      setTimeout(()=>{ try{ load(); }catch(err){} },900);
    }catch(err){
      setState("失败："+String(err&&err.message||err));
    }
  }
  function relSpark(traj){
    const pts=(Array.isArray(traj)?traj:[]).slice(-24).map(p=>(p&&typeof p==="object")?p:{});
    if(pts.length<2) return '<div class="empty-mini">轨迹点不足，暂时画不出趋势。</div>';
    const w=260,h=56,pad=3;
    const x=(i)=>pad+(w-2*pad)*i/(pts.length-1);
    const y=(v)=>h-pad-(h-2*pad)*clamp(v);
    const series=[["trust","var(--accent)"],["closeness","#54b58b"],["conflict","var(--danger)"]];
    const paths=series.map(s=>{
      const d=pts.map((p,i)=>{ const v=clamp(p[s[0]]==null?0:p[s[0]]); return (i?"L":"M")+x(i).toFixed(1)+" "+y(v).toFixed(1); }).join(" ");
      return '<path d="'+d+'" fill="none" stroke="'+s[1]+'" stroke-width="1.6" stroke-linejoin="round"/>';
    }).join("");
    return '<svg class="rel-spark" viewBox="0 0 '+w+' '+h+'" preserveAspectRatio="none" aria-hidden="true">'+paths+'</svg>';
  }
  // task-61: related archived events for the selected relationship user.
  // Matching: event provenance sender_id/sender_name equals the user, or the
  // event session matches one of the relationship sessions (canonical ":"/"_").
  const REL_EVENT_LIMIT=5;
  function _relCanonicalSessions(cur,rel){
    const out=new Set();
    const add=(raw)=>{ const c=canonicalSessionKey(raw); if(c) out.add(c); };
    if(cur&&Array.isArray(cur.sessions)) cur.sessions.forEach(add);
    if(rel&&Array.isArray(rel.sessions)) rel.sessions.forEach(add);
    return out;
  }
  function relatedEventsForUser(cur,rel){
    const evs=Array.isArray(data&&data.events)?data.events:[];
    const user=(cur&&typeof cur==="object")?cur:{};
    const sid=String(user.sender_id||"").trim();
    const sname=String(user.sender_name||"").trim();
    const sessions=_relCanonicalSessions(user,rel);
    return evs.filter(ev=>{
      if(!ev||typeof ev!=="object") return false;
      const prov=(ev.provenance&&typeof ev.provenance==="object")?ev.provenance:{};
      const psid=String(prov.sender_id||"").trim();
      const pname=String(prov.sender_name||"").trim();
      if(sid&&psid===sid) return true;
      if(sname&&pname===sname) return true;
      const canon=canonicalSessionKey(ev.session);
      return !!(canon&&sessions.has(canon));
    }).sort((a,b)=>Number(b.ts||0)-Number(a.ts||0)).slice(0,REL_EVENT_LIMIT);
  }
  function _relSmallSummary(ev){
    const small=String((ev&&ev.small_summary)||"").trim();
    if(small) return _clipText(small,80);
    return _clipText(String((ev&&(ev.title||ev.event))||""),80);
  }
  function _relEventsHtml(cur){
    const rel=(cur&&cur.relationship&&typeof cur.relationship==="object")?cur.relationship:{};
    const evs=relatedEventsForUser(cur,rel);
    const rows=evs.map(ev=>{
      const when=memWhen(ev.ts);
      const title=_clipText(String(ev.title||"重要事件"),60);
      const imp=Number(ev.importance==null?0:ev.importance).toFixed(2);
      return '<div class="rel-event-row" data-event-id="'+esc(String(ev.id||""))+'">'+
        '<span class="rel-event-ts">'+esc(when)+'</span>'+
        '<b class="rel-event-title">'+esc(title)+'</b>'+
        '<span class="rel-event-imp">重要度 '+imp+'</span>'+
        '<p class="rel-event-small">'+esc(_relSmallSummary(ev))+'</p></div>';
    }).join("");
    return '<div class="rel-events"><small>关联事件 / RELATED EVENTS</small>'+
      (rows?'<div class="rel-events-list">'+rows+'</div>'
           :'<div class="empty-mini">暂无关联事件</div>')+'</div>';
  }
  function renderRelationships(){
    const sel=$("relUserFilter"), body=$("relBody"), empty=$("relEmpty"), hint=$("relStateHint");
    if(!sel||!body) return;
    const users=relationshipsValue();
    if(users===null){
      sel.innerHTML='<option value="">后端未提供</option>'; sel.disabled=true;
      body.innerHTML="";
      if(empty){ empty.style.display="block"; empty.textContent="当前后端版本未提供关系状态与轨迹（page/status.relationships）；升级后自动显示。"; }
      if(hint) hint.textContent="后端未提供关系记录";
      return;
    }
    const valid=users.filter(u=>u&&typeof u==="object");
    if(!valid.length){
      sel.innerHTML='<option value="">暂无用户</option>'; sel.disabled=true;
      body.innerHTML="";
      if(empty){ empty.style.display="block"; empty.textContent="还没有关系记录。"; }
      if(hint) hint.textContent="0 个用户";
      return;
    }
    const keys=valid.map(u=>String(u.sender_id||u.sender_name||""));
    if(relUserFilter&&keys.indexOf(relUserFilter)<0) relUserFilter="";
    if(!relUserFilter) relUserFilter=keys[0];
    sel.disabled=valid.length<2;
    sel.innerHTML=valid.map(u=>{
      const key=String(u.sender_id||u.sender_name||"");
      const label=[u.sender_name,u.sender_id].filter(Boolean).join(" / ")||key||"用户";
      return '<option value="'+esc(key)+'">'+esc(shortSession(label))+'</option>';
    }).join("");
    sel.value=relUserFilter;
    const cur=valid.filter(u=>String(u.sender_id||u.sender_name||"")===relUserFilter)[0]||valid[0];
    const rel=(cur.relationship&&typeof cur.relationship==="object")?cur.relationship:{};
    const state=(rel.state&&typeof rel.state==="object")?rel.state:((cur.state&&typeof cur.state==="object")?cur.state:{});
    const traj=Array.isArray(rel.trajectory)?rel.trajectory:[];
    if(empty) empty.style.display="none";
    const stateRows=MEM_REL_FIELDS.map(pair=>{
      const v=clamp(state[pair[0]]==null?0:state[pair[0]]);
      return '<div class="rel-state-item"><small>'+pair[1]+'</small><b>'+v.toFixed(2)+'</b><div class="rel-bar rel-bar-'+pair[0]+'"><i style="width:'+pct(v)+'"></i></div></div>';
    }).join("");
    const lastTraj=traj.slice(-3).reverse();
    const trajRows=lastTraj.length?lastTraj.map(p=>{
      return '<div class="rel-traj-row"><small>'+esc(memWhen(p.ts))+'</small>'+
        MEM_REL_FIELDS.map(pair=>'<span>'+pair[1]+' '+Number(p[pair[0]]==null?0:p[pair[0]]).toFixed(2)+'</span>').join("")+
        '</div>';
    }).join(""):'<div class="empty-mini">还没有轨迹点。</div>';
    const trans=(rel.transactive_map&&typeof rel.transactive_map==="object")?Object.entries(rel.transactive_map):[];
    const transHtml=trans.length?trans.sort((a,b)=>Number(b[1])-Number(a[1])).slice(0,4).map(x=>'<span class="chip">'+esc(String(x[0]))+' ×'+Number(x[1]||0)+'</span>').join(""):'<span class="empty-mini">暂无</span>';
    const dest=(rel.destination_map&&typeof rel.destination_map==="object")?Object.values(rel.destination_map):[];
    const destHtml=dest.length?dest.slice(0,3).map(x=>'<span class="chip">'+esc(String((x&&(x.sender_name||x.sender_id))||"?"))+' ×'+Number((x&&x.count)||0)+'</span>').join(""):'<span class="empty-mini">暂无</span>';
    // Read-only exposure of bio v2 / we-memory / commitment / annotations.
    const weItems=Array.isArray(rel.we_memory)?rel.we_memory:[];
    const weHtml=weItems.length?weItems.slice(0,3).map(x=>'<span class="chip">'+esc(String((x&&x.type)||"we"))+':'+esc(String((x&&x.text)||"").slice(0,24))+'</span>').join(""):'<span class="empty-mini">暂无</span>';
    const marks=Array.isArray(rel.milestones)?rel.milestones:[];
    const markHtml=marks.length?marks.slice(0,3).map(x=>'<span class="chip">'+esc(String((x&&x.type)||"milestone"))+'</span>').join(""):'<span class="empty-mini">暂无</span>';
    const anns=Array.isArray(rel.annotations)?rel.annotations:[];
    const annHtml=anns.length?anns.slice(0,3).map(x=>'<span class="chip">'+esc(String((x&&x.text)||"").slice(0,28))+'</span>').join(""):'<span class="empty-mini">暂无</span>';
    const attach=rel.attachment||{};
    const absence=rel.absence||{};
    const belief=cur.belief_state||{};
    const beliefItems=[].concat(
      (Array.isArray(belief.beliefs)?belief.beliefs:[]).map(x=>"信念:"+String(x)),
      (Array.isArray(belief.desires)?belief.desires:[]).map(x=>"愿望:"+String(x)),
      (Array.isArray(belief.intentions)?belief.intentions:[]).map(x=>"意图:"+String(x))
    ).slice(0,3);
    const beliefHtml=beliefItems.length?beliefItems.map(x=>'<span class="chip">'+esc(String(x).slice(0,28))+'</span>').join(""):'<span class="empty-mini">暂无</span>';
    // G1/L12: calibration is record-only (EWMA/Brier per evidence source). It is
    // consumed only as a bounded (±0.05) recall-confidence nudge; it never
    // rewrites trust and never gates a reply.
    const calSources=(rel.calibration&&typeof rel.calibration==="object"&&rel.calibration.sources&&typeof rel.calibration.sources==="object")
      ?Object.entries(rel.calibration.sources):[];
    const calHtml=calSources.length?calSources.sort((a,b)=>Number((b[1]||{}).n||0)-Number((a[1]||{}).n||0)).slice(0,6).map(x=>{
      const st=(x[1]&&typeof x[1]==="object")?x[1]:{};
      const ewma=Number(st.ewma||0);
      // ≤0.25 is at/better than the always-0.5 reference error -> +delta.
      const dir=ewma<=0.25?"+":"-";
      return '<span class="chip" title="EWMA/Brier 误差（越小越好）；只用于召回置信度 ≤±0.05">'+esc(String(x[0]))+' · 误差 '+ewma.toFixed(2)+' · n'+Number(st.n||0)+' · '+dir+'≤0.05</span>';
    }).join(""):'<span class="empty-mini">暂无校准样本（只在记忆冲突时记录）</span>';
    const repPhase=String(((rel.repair_state||{}).phase)||"stable");
    const commit=Number(rel.commitment||0), invest=Number(rel.investment||0);
    const name=String(cur.sender_name||cur.sender_id||"用户");
    if(hint) hint.textContent="交互 "+Number(cur.interactions||0)+" 次 · 最近 "+memWhen(cur.last_seen||cur.ts);
    body.innerHTML='<div class="rel-card">'+
      '<div class="rel-card-head"><b>'+esc(name)+'</b><span class="hint">'+esc(String(cur.sender_id||""))+'</span><span class="mem-flag">'+(traj.length?"轨迹 "+traj.length+" 点":"无轨迹")+'</span></div>'+
      '<div class="rel-state-grid">'+stateRows+'</div>'+
      '<div class="rel-trend"><div class="rel-trend-head"><small>最近轨迹</small><span class="rel-legend"><i class="rel-lg-trust"></i>信任<i class="rel-lg-close"></i>亲近<i class="rel-lg-conflict"></i>冲突</span></div>'+relSpark(traj)+trajRows+'</div>'+
      '<div class="rel-maps"><div><small>常谈主题 / TRANSACTIVE</small><div class="chips">'+transHtml+'</div></div><div><small>信息来源 / DESTINATION</small><div class="chips">'+destHtml+'</div></div></div>'+
      '<div class="rel-maps"><div><small>共同记忆 / WE-MEMORY</small><div class="chips">'+weHtml+'</div></div><div><small>里程碑 / MILESTONES</small><div class="chips">'+markHtml+'</div></div></div>'+
      '<div class="rel-maps"><div><small>关系印象 / ANNOTATIONS</small><div class="chips">'+annHtml+'</div></div><div><small>用户信念 / BELIEF STATE（只读）</small><div class="chips">'+beliefHtml+'</div></div></div>'+
      '<div class="rel-maps"><div><small>承诺 '+(commit).toFixed(2)+' · 投资 '+(invest).toFixed(2)+' · 修复 '+esc(repPhase)+' · 回归 '+esc(String(absence.bucket||"same_day"))+'</small><div class="chips"><span class="chip" title="只读投影，无行为出口">依恋（只读） 安全'+Number(attach.safe||0).toFixed(2)+'</span><span class="chip">焦虑'+Number(attach.anxious||0).toFixed(2)+'</span><span class="chip">回避'+Number(attach.avoidant||0).toFixed(2)+'</span></div></div></div>'+
      '<div class="rel-maps"><div><small>CALIBRATION / 校准记录（只记录，不写 trust）</small><div class="chips">'+calHtml+'</div></div><div><small>稳态联动 / C6</small><div class="chips"><span class="chip">关系 → 稳态：一轮延迟</span><span class="chip">冲突 / 亲近只喂驱力</span></div></div></div>'+
      _relEventsHtml(cur)+
    '</div>';
  }
  const _memSel=$("memSessionFilter");
  if(_memSel) _memSel.addEventListener("change",()=>{
    memSessionFilter=_memSel.value||"";
    storeSet("bio_mem_session",memSessionFilter);
    Object.keys(memOps).forEach(k=>{ delete memOps[k]; });
    Object.keys(memOpStates).forEach(k=>{ delete memOpStates[k]; });
    renderMemoryMeta();
  });
  const _relSel=$("relUserFilter");
  if(_relSel) _relSel.addEventListener("change",()=>{
    relUserFilter=_relSel.value||"";
    storeSet("bio_rel_user",relUserFilter);
    renderRelationships();
  });

  function renderInsightHistory(){
    const box=$("insightHistoryList");
    const fcfg=((data&&data.llm_functions)||{}).insight||{};
    const enabled=fcfg.enabled===true;
    // Hide legacy deterministic notes ("最近发生：…") written by older versions;
    // only real LLM long-term insights are shown in the history card.
    const rows=(data&&Array.isArray(data.insights))?data.insights.filter(x=>x&&x.insight&&String(x.insight).indexOf("最近发生：")!==0).slice(0,8):[];
    if(box){
      box.innerHTML=rows.length?rows.map(x=>{
        const when=x.ts?new Date(Number(x.ts)*1000).toLocaleString("zh-CN",{month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"}):"";
        return '<div class="insight-row"><span class="insight-ts">'+esc(when||"--")+'</span><span class="insight-text">'+esc(String(x.insight||""))+'</span></div>';
      }).join(""):'<div class="empty-mini">还没有长期模式洞察；点「生成长期洞察」手动生成第一条。</div>';
    }
    const btn=$("insightNowBtn");
    if(btn){
      btn.disabled=!enabled;
      btn.title=enabled?"生成一次跨事件长期模式洞察":"需先开启上方「长期模式洞察（跨事件）」LLM 开关";
    }
    const hint=$("insightHint");
    if(hint) hint.textContent=enabled?"":"需先开启上方 LLM 开关";
  }
  function syncInsightAuto(){
    const chk=$("swInsightAuto"); if(!chk) return;
    chk.checked=!!(data&&data.insight_auto_enabled);
    if(chk.dataset.bound) return;
    chk.dataset.bound="1";
    chk.addEventListener("change",async()=>{
      const val=!!chk.checked;
      if(!bridge){ chk.checked=!val; if(window.alert)window.alert("静态预览模式无法保存设置，请从 AstrBot 插件视图打开。"); return; }
      try{
        const raw=await bridge.apiPost("page/toggle",{key:"insight_auto_enabled",value:val});
        const payload=raw&&raw.data?raw.data:raw;
        if(!payload||payload.status==="error"||payload.status==="fail") throw new Error((payload&&payload.message)||"保存失败");
        if(data) data.insight_auto_enabled=val;
      }catch(e){
        chk.checked=!val;
        if(window.alert) window.alert("自动长期洞察设置保存失败："+String(e&&e.message||e));
      }
    });
  }
  function renderTree(tree) {
    const roots = (tree && Array.isArray(tree.roots)) ? tree.roots : [];
    if (!roots.length) return '<div class="empty-mini">还没有长期模式洞察节点。</div>';
    const node = (n, depth) => {
      const title = esc(n.insight || n.title || "长期洞察");
      const emo = n.emotion ? ' <em>' + esc(L(n.emotion)) + '</em>' : '';
      const when = n.ts ? '<small>' + esc(new Date(Number(n.ts) * 1000).toLocaleString()) + '</small>' : '';
      const kids = (Array.isArray(n.children) && n.children.length)
        ? '<div class="tree-children">' + n.children.slice(-4).map(c => node(c, depth + 1)).join("") + '</div>' : '';
      return '<div class="tree-node d' + Math.min(depth, 2) + '"><span class="tree-dot"></span><div class="tree-line"><b>' +
        title + '</b>' + emo + when + '</div>' + kids + '</div>';
    };
    return roots.slice(-6).map(r => node(r, 0)).join("");
  }

  function renderSelfPanels(s) {
    const sm = data.self_model || {};
    const hist = Array.isArray(sm._history) ? sm._history.slice(-3) : [];
    if ($("selfVersion")) setText("selfVersion", "v" + Number(sm.version || 0) + " · 最近 " + hist.length + " 次更新");
    if ($("selfHistory")) {
      const rows = hist.slice().reverse();
      $("selfHistory").innerHTML = rows.length ? rows.map(h => {
        const when = h.ts ? new Date(Number(h.ts) * 1000).toLocaleString() : "";
        return '<div class="hist-row"><span class="hist-ts">' + esc(when) + '</span><div class="hist-body"><b>' +
          esc(h.who_am_i || "—") + '</b>' + (h.narrative ? '<small>' + esc(h.narrative) + '</small>' : '') + '</div></div>';
      }).join("") : '<div class="empty-mini">还没有自我模型历史。</div>';
    }
    if ($("coreSelf")) setText("coreSelf", s.core_self || "未形成");
    if ($("narrativeSelf")) setText("narrativeSelf", s.narrative_self || "未形成");
    const tl = s.self_timeline || {};
    if ($("tlPast")) $("tlPast").innerHTML = (Array.isArray(tl.past) ? tl.past.slice(-5).reverse() : []).map(x => '<li>' + esc(x) + '</li>').join("") || '<li class="muted">—</li>';
    if ($("tlPresent")) setText("tlPresent", tl.present || "—");
    if ($("tlFuture")) $("tlFuture").innerHTML = (Array.isArray(tl.future) ? tl.future.slice(0, 5) : []).map(x => '<li>' + esc(x) + '</li>').join("") || '<li class="muted">—</li>';
    const tree = s.reflection_tree || { roots: [], count: 0 };
    const _hidden = _treeHiddenCount(tree);
    if ($("treeCount")) setText("treeCount", "COUNT " + Number(tree.count || 0) + " · ROOTS " + ((Array.isArray(tree.roots) ? tree.roots : []).length) + (_hidden ? (" · 隐藏 " + _hidden) : ""));
    if ($("reflectionTree")) $("reflectionTree").innerHTML = renderTree(tree);
    const probs = Array.isArray(s.spectrum_probs) ? s.spectrum_probs.slice(0, 3) : [];
    if ($("spectrumProbs")) $("spectrumProbs").innerHTML = probs.length ? probs.map(x => {
      const p = Number(x.p || 0);
      return '<div class="spec-row"><span>' + esc(x.name || x.key || "?") + '</span><div class="spec-track"><i style="width:' +
        pct(p) + '"></i></div><b>' + (p * 100).toFixed(1) + '%</b></div>';
    }).join("") : '<div class="empty-mini">光谱概率未生成。</div>';
    const _specCal = (s.spectrum_calibration && typeof s.spectrum_calibration === "object") ? s.spectrum_calibration : null;
    if ($("spectrumCalNote")) {
      $("spectrumCalNote").textContent = _specCal
        ? "光谱校准（仅本会话）：样本 " + Number(_specCal.samples || 0) + " · 情绪家族 " + Number(_specCal.families || 0) + " · 已校准原型 " + Number(_specCal.calibrated || 0) + "；样本不足时使用纯原型锚点，跨会话不共享。"
        : "光谱校准：当前状态未提供 calibration（旧数据或尚未累积历史）；不会补算，也不写回。";
    }
    const sec = s.sec || {};
    const secMap = [["relevance", "相关性"], ["implication", "影响"], ["coping_potential", "应对潜力"], ["normative", "规范一致"]];
    if ($("secGrid")) $("secGrid").innerHTML = secMap.map(pair => {
      const value = Number(sec[pair[0]] || 0);
      return '<div class="sec-item"><small>' + pair[1] + '</small><b>' + value.toFixed(2) + '</b><div class="bar"><i style="width:' +
        pct(value) + '"></i></div></div>';
    }).join("");
  }
  // Read-only steady-state / posture projection (snapshot + page/status top level).
  // Every value is display-only; nothing here can write the bio layer.
  function renderSteadyState(s){
    const body=(s&&s.homeostasis&&typeof s.homeostasis==="object")?s.homeostasis:{};
    const top=(data&&typeof data==="object")?data:{};
    const set=(id,value)=>{const el=$(id); if(el) el.textContent=value;};
    const circ=(s&&s.circadian_alertness!=null)?s.circadian_alertness:top.circadian_alertness;
    const allo=(s&&s.allostatic_load!=null)?s.allostatic_load:top.allostatic_load;
    set("sCircadian",circ==null?"—":Number(circ).toFixed(2));
    set("sAllostatic",allo==null?"—":Number(allo).toFixed(2));
    set("sLint",body.L_int==null?"—":Number(body.L_int).toFixed(3));
    set("sReadiness",body.readiness==null?"—":Number(body.readiness).toFixed(2));
    const pyr=(body.need_pyramid&&typeof body.need_pyramid==="object")?body.need_pyramid:{};
    set("sNeedDominant",pyr.dominant?_needLabel(pyr.dominant):"—");
    const intero=(body.interoception&&typeof body.interoception==="object")?body.interoception:{};
    set("sIntero",intero.label?(_interoLabel(intero.label)+(intero.signal==null?"":" "+Number(intero.signal).toFixed(2))):"—");
    set("sBoundary",s&&s.boundary_pressure!=null?Number(s.boundary_pressure).toFixed(2):"—");
    set("sRefusalLevel",s&&s.refusal_readiness!=null?Number(s.refusal_readiness).toFixed(2):"—");
    // task-36: opt-in reply-consistency projection (read-only; default off).
    const rc=(s&&s.reply_consistency&&typeof s.reply_consistency==="object")?s.reply_consistency:null;
    set("sReplyConsistency",rc&&rc.score!=null
      ? (Number(rc.score).toFixed(2)+((rc.checks&&rc.checks.length)?(" ("+rc.checks.slice(0,2).join(",")+")"):""))
      : "—");
    const note=$("steadyNote");
    if(note){
      const hasBody=Object.keys(body).length>0;
      // task-36 read-only telemetry / token usage (never affects behavior).
      let extra="";
      const tel=(data&&data.llm_telemetry&&typeof data.llm_telemetry==="object")?data.llm_telemetry:null;
      if(tel){
        const counters=tel.counters||{};
        let fails=0;
        Object.keys(counters).forEach(k=>{
          if(/:(error|fallback|empty|no_provider|provider_error|call_error)$/.test(k)) fails+=Number(counters[k]||0);
        });
        extra+=" · LLM 失败/降级 "+fails+" 次";
      }
      const tok=(data&&data.token_usage&&typeof data.token_usage==="object")?data.token_usage:null;
      if(tok){
        if(tok.available){
          const ss=tok.sessions||{};
          let total=0,calls=0;
          Object.keys(ss).forEach(k=>{const it=ss[k]||{}; total+=Number(it.total_tokens||0); calls+=Number(it.calls||0);});
          extra+=" · token "+total+"（"+calls+" 次调用）";
        } else {
          extra+=" · token 不可用（provider 未返回 usage）";
        }
      }
      note.textContent=(hasBody
        ? "只读投影：昼夜警觉与稳态负荷只反映内部状态；边界压力 / 拒绝就绪只是倾向标记，不决定是否回复。"
        : "只读投影：当前状态文件没有 homeostasis（旧数据或该能力未开启），缺失项显示 —；不会补算，也不写回。")+extra;
    }
  }
  // Read-only recall metadata: page/status.last_memory_meta + working_set +
  // last_memory_trace + last_strategy_hint. Calibration and the refusal posture
  // are labels only: they never act as reply gates here.
  // 1.3.1: opt-in read-only model-layer panel (absent fields => stays hidden).
  // task-44: L1 thinking-precursor rows (conflict / rumination / anchor /
  // sycophancy) live in a collapsed <details>; each one hides when missing.
  // task-61: no page-top banners. One-time migration note lives inline in
  // 设置 → 版本 (non-fatal notices must not occupy the page top).
  function renderInlineNotices(){
    try {
      const mig=(data&&typeof data.migration_note==="string")?data.migration_note:"";
      const mb=$("migNote");
      if(!mb) return;
      if(mig&&!localStorage.getItem("biocore_mig_seen_131")){
        mb.hidden=false;
        mb.textContent="升级提示："+mig;
        localStorage.setItem("biocore_mig_seen_131","1");
      } else {
        mb.hidden=true;
        mb.textContent="";
      }
    } catch(e) {}
  }
  // task-61: the safety warning is an inline line under the 安全限制 switch,
  // only rendered while safety is OFF (no page-top banner).
  function renderSafetyWarn(){
    const warn=$("safetyWarn");
    if(!warn) return;
    const enabled=!!(data&&data.safety_enabled);
    warn.hidden=enabled;
    if(!enabled){
      warn.textContent="该开关控制敏感信息掩码与投毒过滤；危机分级/日志由核心 GA-03 模块提供（默认只记录不拦截）。";
    }
  }
  // [/CORE-STATUS-MAP]
  function describeBridgeError(error){
    const err=(error&&typeof error==="object")?error:{};
    const status=err.status||err.statusCode||err.httpStatus||(err.response&&err.response.status)||"";
    const code=err.code||(err.payload&&err.payload.code)||"";
    const message=err.message||(err.payload&&err.payload.message)||(typeof error==="string"?error:"")||"未知错误";
    const head=status?("HTTP "+status+(code?" "+String(code):"")):(code?String(code):"");
    return head?(head+"："+message):String(message);
  }
  function renderEnvChecks(){
    try{
      const e=(data&&data.env_checks&&typeof data.env_checks==="object")?data.env_checks:null;
      const panel=$("envChecksPanel"), txt=$("envChecksText");
      if(!panel||!e) return;
      const warns=Array.isArray(e.warnings)?e.warnings:[];
      panel.hidden=false;
      if(txt) txt.textContent="data可写="+(e.data_writable?"是":"否")
        +" · AstrBot="+String(e.astrbot_version||"—")
        +" · 版本OK="+(e.version_ok?"是":"否")
        +" · persona="+(e.persona_present?"有":"缺")
        +" · 缺配置="+((Array.isArray(e.missing_config)&&e.missing_config.length)?e.missing_config.join("/"):"无")
        +(warns.length?(" · ⚠ "+warns.join("；")):"");
    }catch(err){}
  }
  function renderModelTracePanels(snap){
    const panel=$("panelModelTrace");
    if(!panel) return;
    const set=(id,v)=>{const el=$(id); if(el) el.textContent=v;};
    const s=(snap&&typeof snap==="object")?snap:{};
    const inj=(data&&data.injection_trace&&typeof data.injection_trace==="object")?data.injection_trace:null;
    const rev=(data&&data.reverse_check&&typeof data.reverse_check==="object")?data.reverse_check:null;
    const rep=(data&&data.repeat_guard&&typeof data.repeat_guard==="object")?data.repeat_guard:null;
    const path=(data&&data.path_monitor&&typeof data.path_monitor==="object")?data.path_monitor:null;
    const tb=(data&&data.token_budget&&typeof data.token_budget==="object")?data.token_budget:null;
    const syco=(data&&data.sycophancy_check&&typeof data.sycophancy_check==="object")?data.sycophancy_check:null;
    const hasL1=(s.conflict_ema!=null||s.rumination_ema!=null||s.anchor_weight!=null);
    panel.hidden=!(inj||rev||rep||path||tb||hasL1||syco);
    const l1=$("mtL1Block");
    if(l1) l1.hidden=!hasL1;
    if(panel.hidden) return;
    const bar=(id,v)=>{const el=$(id); if(el) el.style.width=pct(clamp(v));};
    if(hasL1){
      const c=Number(s.conflict_ema||0), rum=Number(s.rumination_ema||0), anchor=Number(s.anchor_weight||0);
      set("mtConflict",c.toFixed(2)+" / 1.00");
      bar("bConflict",c);
      set("mtRumination",rum.toFixed(2)+" / 1.00"+(s.rumination_suppress?" · 抑制中":""));
      bar("bRumination",rum);
      set("mtAnchor",anchor.toFixed(2)+" / 0.90 上限");
      bar("bAnchor",Math.min(1,anchor/0.9));
    }
    if(syco){
      const agrees=Array.isArray(syco.agree)?syco.agree.filter(x=>x):[];
      const risks=Array.isArray(syco.risky)?syco.risky.filter(x=>x):[];
      set("mtSyco",(syco.flag?"⚠ 同意风险":"通过")
        +" · intensity "+Number(syco.intensity||0).toFixed(2)
        +(agrees.length?(" · 同意词 "+agrees.slice(0,2).join("/")):"")
        +(risks.length?(" · 风险词 "+risks.slice(0,2).join("/")):""));
    } else {
      set("mtSyco","—");
    }
    if(inj){
      set("mtInj",String(inj.chars==null?"—":Number(inj.chars))+" 字 / "+String(inj.tokens_estimate==null?"—":Number(inj.tokens_estimate)));
      const cut=(Array.isArray(inj.truncated)?inj.truncated.length:0)+(Array.isArray(inj.dropped_duplicates)?inj.dropped_duplicates.length:0);
      const al=inj.alert?(" · ⚠ "+String(inj.alert)):"";
      set("mtCut","字数 "+Number(inj.size==null?inj.chars:inj.size)+" · 浪费项 "+(Number((inj.wasted||{}).empty_blocks||0)+Number((inj.wasted||{}).duplicates||0)+Number((inj.wasted||{}).stale||0)+Number((inj.wasted||{}).unvalued_hint||0))+(inj.over_target?" · 超目标":""));
    }
    if(rev){const v=Array.isArray(rev.violations)?rev.violations:[];set("mtReverse",(rev.score==null?"—":Number(rev.score).toFixed(2))+" · "+(v.length?v.slice(0,2).join(","):"通过"));}
    if(rep) set("mtRepeat",String(rep.flag||"—")+" · J "+Number(rep.jaccard||0).toFixed(2));
    if(path) set("mtPath",(path.warning?"⚠ 可能路径依赖":"sim")+" "+Number(path.self_similarity||0).toFixed(2)+" · autocorr "+Number(path.label_autocorr||0).toFixed(2)+" · drift "+Number(path.summary_drift||0).toFixed(2));
    if(tb){const d=tb.today||{};const est=(d.estimated||Number(d.estimated_calls||0)>0)?" · 估算":"";set("mtCost","in "+Number(d.input_tokens||0)+" / out "+Number(d.output_tokens||0)+" · ¥"+Number(d.cost||0).toFixed(4)+est);}
  }
  function renderRecallMeta(core){
    // 初始化步骤不在这里：已移到 _boot（load 前 setup*，首次 load 后 safeRender）。
    const meta=(data&&data.last_memory_meta&&typeof data.last_memory_meta==="object")?data.last_memory_meta:null;
    const trace=(data&&data.last_memory_trace&&typeof data.last_memory_trace==="object")?data.last_memory_trace:null;
    const ws=(core&&core.working_set&&typeof core.working_set==="object")?core.working_set:null;
    const set=(id,value)=>{const el=$(id); if(el) el.textContent=value;};
    set("memRecallCount",meta?String(Number(meta.count||0)):"—");
    set("memRecallConf",meta&&meta.confidence!=null?Number(meta.confidence).toFixed(2):"—");
    set("memRecallAnswer",meta&&meta.answer_confidence!=null?Number(meta.answer_confidence).toFixed(2):"—");
    set("memRecallGate",meta?String(meta.gate||"none"):"—");
    set("memRecallConflicts",meta?String(Number(meta.conflicts||0)):"—");
    const delta=meta&&meta.calibration_delta!=null?Number(meta.calibration_delta):null;
    set("memCalibration",delta==null?"—":(delta>=0?"+":"")+delta.toFixed(3)+(meta&&meta.calibration_entries?(" ×"+Number(meta.calibration_entries)):""));
    const ttlNote="（TTL "+WORKING_SET_TTL_HOURS+"h）";
    if(!ws||ws.count==null) set("memWorkingSet","—");
    else {
      const ttl=Number(ws.ttl_seconds||0);
      set("memWorkingSet",String(Number(ws.count||0))+"/"+String(Number(ws.capacity||0))+(ttl>0?(" · "+Math.round(ttl/3600)+"h"):" · 未提供 TTL"));
    }
    if(!trace) set("memTrace","—");
    else set("memTrace",String(Number(trace.count||0))+" 条 · v "+(Number(trace.valence||0)>=0?"+":"")+Number(trace.valence||0).toFixed(2));
    const noteEl=$("memRecallNote");
    if(noteEl){
      noteEl.textContent="召回元数据是只读投影：校准偏移只作用于本轮召回的置信度（≤±0.05，不写存储）；工作集"+ttlNote+"在召回时过滤，这里显示后端已给的原始列表。";
    }
    const hintEl=$("memHintNote");
    if(hintEl){
      const hint=String((data&&data.last_strategy_hint)||"");
      if(!hint){
        hintEl.textContent="策略提示：本轮没有生成提示（提示槽由 repair / 姿态 / 共情 / 记忆回执等择一占用）。";
      } else {
        const posture=_postureFromHint(hint);
        hintEl.textContent="策略提示："+hint+(posture?("（"+posture+" 是姿态 token，不是 gate：不决定是否回复）"):"");
      }
    }
    try { renderModelTracePanels(core && core.snapshot); } catch (e) {}
  }
  // Extract the G2/L9 refusal posture token from the bounded strategy hint.
  function _postureFromHint(hint){
    const m=String(hint||"").match(/refuse=(negotiate|decline)/);
    if(!m) return "";
    return m[1]==="decline"?"refuse=decline":"refuse=negotiate";
  }
  // 面板显示开关：只控制 Dashboard 上哪些只读面板可见，不改后端配置。
  function applyPanelVisibility(){
    [["panelAutonomy","showAutonomyPanel"],
     ["panelLearning","showLearningPanel"],
     ["chainBlock","showChainList"]].forEach(pair=>{
      const el=$(pair[0]);
      if(el) el.hidden=!visual[pair[1]];
    });
  }
  // Task-16 只读：state.proactive_autonomy（默认 {enabled:false}）。
  // 群聊只显示「仅私聊」；未开启显示「已关闭」；不补算、不写回、不触发发送。
  function renderAutonomyPanel(s,coreKey){
    const set=(id,value)=>{const el=$(id); if(el) el.textContent=value;};
    const note=$("autonomyNote"), sourcesEl=$("autonomySources");
    const _statusAuto=(data&&data.autonomy&&typeof data.autonomy==="object")?data.autonomy:null;
    const _statusState=(_statusAuto&&_statusAuto.state&&typeof _statusAuto.state==="object")?_statusAuto.state:{};
    const auto=(s&&s.proactive_autonomy&&typeof s.proactive_autonomy==="object"&&Object.keys(s.proactive_autonomy).length)
      ? s.proactive_autonomy
      : (_statusAuto ? {enabled:_statusAuto.enabled, send:_statusAuto.send,
          threshold:_statusAuto.threshold, max_chars:_statusAuto.max_chars,
          ready:_statusState.ready, impulse:_statusState.impulse,
          impulse_ema:_statusState.impulse_ema, sent:_statusState.sent,
          sources:_statusState.sources} : null);
    const type=parseSessionKey(coreKey||"").type;
    const isGroup=(type==="GroupMessage"||type==="GuildMessage");
    if(isGroup){
      set("autoEnabled","仅私聊");
      ["autoReady","autoThreshold","autoMaxChars","autoImpulse","autoSent"].forEach(id=>set(id,"—"));
      if(sourcesEl) sourcesEl.innerHTML='<span class="chip">当前会话：群聊</span><span class="chip">只在私聊生效</span>';
      if(note) note.textContent="群聊不显示可触发状态：自主行为只走私聊路径。在左侧「自主行为」页设置（proactive_autonomy / proactive_send）。";
      return;
    }
    if(!auto||!auto.enabled){
      set("autoEnabled","已关闭");
      ["autoReady","autoThreshold","autoMaxChars","autoImpulse","autoSent"].forEach(id=>set(id,"—"));
      if(sourcesEl) sourcesEl.innerHTML='<span class="chip">未启用</span><span class="chip">默认关</span>';
      if(note) note.textContent="已关闭（默认关）：不计算 readiness；仅在私聊路径、proactive_autonomy 开启后写入 threshold / max_chars / impulse。在 表达意图 → 自主行为 页设置。";
      return;
    }
    const src=(auto.sources&&typeof auto.sources==="object")?auto.sources:{};
    const _num=(v)=>(v==null||!isFinite(Number(v)))?"—":Number(v).toFixed(2);
    const _pick=(key,fallback)=>src[key]!=null?src[key]:fallback;
    set("autoEnabled","已开启");
    set("autoReady",auto.ready?"是":"否");
    set("autoThreshold",_num(auto.threshold));
    set("autoMaxChars",auto.max_chars==null?"—":String(Number(auto.max_chars)));
    set("autoImpulse",auto.impulse==null?"—":Number(auto.impulse).toFixed(3));
    set("autoSent",String(Number(auto.sent_count||0))+"/"+String(Number(auto.daily_cap||0)));
    if(sourcesEl){
      const items=[
        ["chaos",_pick("chaos",auto.chaos)],
        ["echo",_pick("echo_trace",null)],
        ["stress_load",_pick("stress_load",null)],
        ["drive_dev",_pick("drive_dev",null)],
        ["trust",_pick("trust",null)],
        ["closeness",_pick("closeness",null)]
      ].filter(x=>x[1]!=null&&isFinite(Number(x[1])));
      sourcesEl.innerHTML=items.length
        ? items.map(x=>'<span class="chip">'+esc(x[0])+' '+Number(x[1]).toFixed(2)+'</span>').join("")
        : '<span class="chip">来源未提供</span>';
    }
    if(note){
      const cool=Number(auto.cooldown_seconds||0), cap=Number(auto.daily_cap||0), quiet=Array.isArray(auto.quiet_hours)?auto.quiet_hours:[];
      note.textContent="只读投影：impulse 由 chaos / echo / stress_load / drive_dev / trust / closeness 加权（×autonomy_gain）；不发消息、不新增 LLM。"
        +(cool>0?("冷却 ≥"+Math.round(cool/60)+" 分钟"):"")
        +(cap>0?(" · 每日 ≤"+cap):"")
        +(quiet.length>=2?(" · 静默 "+quiet[0]+"–"+quiet[1]+" 点"):"")
        +"；开关在 AstrBot 插件配置。";
    }
  }
  // Task-16 只读：state.learning（L1 Q-learning，确定性、有界、可审计）。
  function renderLearningPanel(s){
    const set=(id,value)=>{const el=$(id); if(el) el.textContent=value;};
    const note=$("learningNote"), logEl=$("learningLog");
    const l=(s&&s.learning&&typeof s.learning==="object")?s.learning:null;
    if(!l||l.version==null){
      ["learnVersion","learnUpdates","learnLast","learnTrustAlpha","learnRate","learnQTop"].forEach(id=>set(id,"—"));
      set("learnVersion","未启用");
      if(logEl) logEl.innerHTML='<span class="chip">未启用</span>';
      if(note) note.textContent="旧 state 没有 learning 字段（未启用）；不会补算，也不写回。开关在 AstrBot 插件配置（bio_learning）。";
      return;
    }
    const params=(l.params&&typeof l.params==="object")?l.params:{};
    const q=(params.regulation_q&&typeof params.regulation_q==="object")?params.regulation_q:{};
    const qRows=Object.keys(q).filter(k=>isFinite(Number(q[k])))
      .sort((a,b)=>Math.abs(Number(q[b]))-Math.abs(Number(q[a]))).slice(0,3)
      .map(k=>_regLabel(k)+" "+fmt(Number(q[k]),2));
    set("learnVersion","v"+String(l.version));
    set("learnUpdates",String(Number(l.updates_count||0)));
    set("learnLast",Number(l.last_update||0)>0?memWhen(l.last_update):"—");
    set("learnTrustAlpha",params.trust_alpha==null?"—":Number(params.trust_alpha).toFixed(2));
    set("learnRate",params.learning_rate==null?"—":Number(params.learning_rate).toFixed(3));
    set("learnQTop",qRows.length?qRows.join(" · "):"无样本");
    if(logEl){
      const log=Array.isArray(l.log)?l.log.filter(x=>x&&typeof x==="object").slice(-3).reverse():[];
      logEl.innerHTML=log.length
        ? log.map(x=>{
            const param=String(x.param||"").replace("regulation_q.","");
            return '<span class="chip" title="参数更新日志（最近 3 条）">'+esc(memWhen(x.ts))+' · '+esc(_regLabel(param))
              +' '+fmt(Number(x.old||0),2)+'→'+fmt(Number(x.new||0),2)+'</span>';
          }).join("")
        : '<span class="chip">暂无参数更新日志</span>';
    }
    if(note) note.textContent="只读投影：Q 值与参数由后端确定性更新（最小样本 5、单步 ≤0.02）；updates_count 为 Q 更新次数。开关在 AstrBot 插件配置（bio_learning）。";
  }
  // Task-16 只读：事件归档 chain_links（H2-1 写路径，默认关）。
  function renderChainLinks(){
    const list=$("chainList");
    if(!list) return;
    const evs=(data&&Array.isArray(data.events))?data.events:[];
    const filter=String(memSessionFilter||"");
    const rows=[];
    evs.forEach(ev=>{
      if(!ev||typeof ev!=="object") return;
      const links=Array.isArray(ev.chain_links)?ev.chain_links.filter(x=>x&&typeof x==="object"):[];
      if(!links.length) return;
      if(filter&&canonicalSessionKey(ev.session)!==filter) return;
      rows.push({ev:ev,links:links});
    });
    rows.sort((a,b)=>Number(b.ev.ts||0)-Number(a.ev.ts||0));
    if(!rows.length){
      list.innerHTML='<div class="empty-mini">还没有事件链：chain_links 只在 memory_chain_enabled 开启后、新归档的事件上写入（默认关闭）。</div>';
      return;
    }
    list.innerHTML=rows.slice(0,5).map(row=>{
      const links=row.links.slice(0,3).map(lk=>{
        const ts=Number(lk.ts||0);
        const age=ts>0?Math.max(0,(Date.now()/1000-ts)/86400):0;
        const stored=Number(lk.weight||0);
        const eff=stored*Math.pow(0.5,age/CHAIN_HALF_LIFE_DAYS);
        return '<span class="chip" title="存储权重 '+stored.toFixed(2)+'；读取时按 30 天半衰">→ '
          +esc(String(lk.id||"").slice(0,10))+' · '+esc(String(lk.kind||"link"))
          +' · w '+stored.toFixed(2)+'→'+eff.toFixed(2)+'</span>';
      }).join("");
      return '<div class="chain-event"><b>'+esc(String(row.ev.title||row.ev.event_key||"事件"))+'</b>'
        +'<small>'+esc(memWhen(row.ev.ts))+' · 链 ×'+row.links.length+'</small>'
        +'<div class="chips">'+links+'</div></div>';
    }).join("");
  }
  function render(){
    const core=(data.cores&&data.cores[0])||demo.cores[0];
    const s=core.snapshot||{}, it=core.intent||{}, p=data.profile||{};
    const _memBalls=memoryBallsFromIndex();
    const _eventBalls=eventBallsFromArchive();
    let _ballPool=_memBalls;
    if(!_ballPool.length){
      _ballPool=_eventBalls;
    }else{
      // Archived events are event summaries and should stay visible (e.g. the
      // late-night confession ball); dedupe against memory-ball titles.
      const _titles=_ballPool.map(b=>String(b.title||""));
      const _extra=_eventBalls.filter(ev=>!_titles.some(t=>t&&(t.includes(ev.title)||String(ev.title||"").includes(t)))).slice(0,3);
      _ballPool=_ballPool.concat(_extra);
    }
    window.__biocoreState={intent:it,snapshot:s,visual:Object.assign({},visual),events:data.events||[],memories:_ballPool};
    window.__biocoreData=data;
    updateOrbLegend();
    renderSessionMemory();
    renderMemoryMeta();
    renderRelationships();
    renderInsightHistory();
    syncInsightAuto();
    renderSelfPanels(s);
    renderSteadyState(s);
    renderRecallMeta(core);
    applyPanelVisibility();
    renderAutonomyPanel(s, core.key);
    renderLearningPanel(s);
    renderChainLinks();
    setText("pluginBadge", data.enabled?"BioCore · ON":"BioCore · OFF");
    setText("heroTitle", L(it.emotion)+" · "+L(it.intent));
    setText("heroSub", it.need==="be_heard"?"现在更像是想被听见，不急着解决问题。":it.need==="space"?"现在更像是需要一点空间，不想被追问。":it.need==="share"?"现在更像是想分享，语气可以轻一点。":it.need==="vent"?"现在更像是想吐槽，先接住，不用讲道理。":"现在像是普通聊天，接不接都可以。");
    $("tagRow").innerHTML=[["emotion",it.emotion],["compound",it.compound],["spectrum",it.spectrum&&it.spectrum[0]?it.spectrum[0].name:""],["intent",it.intent],["tone",it.tone],["distance",it.distance],["expression",it.expression]].filter(x=>x[1]).map(x=>'<span class="chip">'+esc(x[0])+" · "+esc(x[1])+"</span>").join("");
    setText("orbValence", fmt(s.v,2));
    setText("teleSys", data.enabled ? "NOMINAL" : "OFFLINE");
    setText("teleMode", L(it.intent) || "HOLD");
    setText("teleLayers", "FIELD / AFFECT / CORE");
    setText("teleSync", fmt(s.echo_trace,2));
    setText("teleTicks", String(s.ticks==null?"--":s.ticks));
    const _n=s.noise||{}, _rp=s.ripple||{}, _sp=s.spiking||{};
    setText("orbNoise", fmt((Number(_n.stress||0)+Number(_n.energy||0))/2,3));
    setText("orbEcho", fmt(s.echo,3));
    setText("orbRipple", Number(_rp.overlap||0).toFixed(2));
    setText("orbSpike", Number(_sp.rate||0).toFixed(3));
    setMetric("mStress","bStress",s.stress); setMetric("mEnergy","bEnergy",s.energy); setMetric("mTrust","bTrust",s.trust); setMetric("mArousal","bArousal",s.a);
    const _dom=Number(s.d==null?0.5:s.d); setText("mDominance", _dom.toFixed(2)); $("bDominance").style.width=pct((_dom+1)/2);
    setMetric("mSocial","bSocial",s.social==null?0.5:s.social);
    const noise=s.noise||{};
    $("noiseList").innerHTML=["stress","energy","social","attention","valence"].map(k=>{
      const v=Number(noise[k]||0); const w=pct((v+0.3)/0.6);
      return '<div class="noise-row"><span>'+k+'</span><div class="noise-track"><i style="width:'+w+'"></i></div><b>'+fmt(v,3)+'</b></div>';
    }).join("");
    setText("sEcho", fmt(s.echo,3)); setText("sEchoTrace", fmt(s.echo_trace,3));
    setText("sUpper", Number((s.ripple||{}).upper||0).toFixed(2));
    setText("sLower", Number((s.ripple||{}).lower||0).toFixed(2));
    setText("sOverlap", Number((s.ripple||{}).overlap||0).toFixed(2));
    setText("sRate", Number((s.spiking||{}).rate||0).toFixed(3));
    const _ap=s.appraisal||{};
    const _spec=(it.spectrum&&it.spectrum[0])?it.spectrum[0].name:"";
    const _exprKey=String(it.expression||"normal").toLowerCase();
    const _exprPct={none:5,closed:15,restrained:30,normal:55,open:80,high:92}[_exprKey]||55;
    setText("intentLabel", L(it.intent)||"hold");
    setText("intentText", "还有"+(Number(s.energy)>.6?"力气":"点累")+"；压力"+(Number(s.stress)>.55?"偏高":"不高")+"。现在更想"+L(it.need)+"；计划是"+(it.plan||"自然回应")+"。");
    if($("intentTags"))$("intentTags").innerHTML=[L(it.emotion),L(it.intent),L(it.need),it.compound,_spec].filter(Boolean).map(x=>'<span class="intent-tag">'+esc(x)+'</span>').join("");
    if($("intentStrengthText"))setText("intentStrengthText", L(it.expression)||"--");
    if($("intentStrengthBar"))$("intentStrengthBar").style.width=_exprPct+"%";
    if($("intentUrgencyText"))setText("intentUrgencyText", "紧迫度 "+Number(_ap.urgency||0).toFixed(2));
    if($("iFlowEmotion"))setText("iFlowEmotion", L(it.emotion)||"--");
    if($("iFlowNeed"))setText("iFlowNeed", L(it.need)||"--");
    if($("iFlowExpr"))setText("iFlowExpr", L(it.expression)||"--");
    if($("iFlowPlan"))setText("iFlowPlan", it.plan||"--");
    setText("iEmotion", L(it.emotion)); setText("iNeed", L(it.need)); setText("iExpr", L(it.expression));
    if($("iCompound"))setText("iCompound", it.compound||"-");
    if($("iSpectrum"))setText("iSpectrum", _spec||"-");
    if($("iPlan"))setText("iPlan", it.plan||"-");
    if($("iNovelty"))setText("iNovelty", Number(_ap.novelty||0).toFixed(2));
    if($("iGoal"))setText("iGoal", Number(_ap.goal_relevance||0).toFixed(2));
    if($("iCoping"))setText("iCoping", Number(_ap.coping==null?.5:_ap.coping).toFixed(2));
    if($("iReg"))setText("iReg", _regLabel(it.regulation));
    if($("iSelf"))setText("iSelf", (data.self_model&&data.self_model.who_am_i)?data.self_model.who_am_i:"未建立");
    if($("iNorm"))setText("iNorm", Number(_ap.norm_compatibility||0.5).toFixed(2));
    if($("iExpected"))setText("iExpected", Number(_ap.expectedness==null?1:_ap.expectedness).toFixed(2));
    if($("iUrgency"))setText("iUrgency", Number(_ap.urgency||0).toFixed(2));
    if($("iOpponent")){const op=s.opponent||{}; setText("iOpponent", Number(op.v||0).toFixed(2)+" / "+Number(op.a||0).toFixed(2));}
    if($("iAttention"))setText("iAttention", Number(s.attention==null?.5:s.attention).toFixed(2));
    if($("iMeta"))setText("iMeta", s.meta_emotion||"-");
    $("personaBars").innerHTML=["O","C","E","A","N"].map(k=>'<div class="p-row"><span>'+k+'</span><div class="p-track"><i style="width:'+pct(p[k])+'"></i></div><b>'+Number(p[k]||0).toFixed(2)+"</b></div>").join("");
    setText("personaNote", "stress "+Number(p.stress_reactivity||0).toFixed(2)+" · recovery "+Number(p.recovery_rate||0).toFixed(2)+" · social "+Number(p.social_baseline||0).toFixed(2));
    if($("selfWho")){const sm=data.self_model||{}; setVal("selfWho", sm.who_am_i||""); setVal("selfNarrative", sm.narrative||""); setVal("selfBoundaries", (sm.boundaries||[]).join("\n")); setVal("selfConsistency", (sm.consistency||[]).join("\n"));}
    if($("goalList")){const gs=s.goals||[]; const cf=s.goal_conflict||[]; $("goalList").innerHTML=(gs.length?gs.map(g=>'<div><small>'+esc(g.name||"")+'</small><b>'+Number(g.progress||0).toFixed(2)+'</b></div>').join(""):'<div><small>goals</small><b>-</b></div>')+(cf.length?'<div><small>conflict</small><b>'+esc(cf.join(" / "))+'</b></div>':'');}
    if($("autoBioList")){
      const ab=s.autobiography||[];
      const sm=data.self_model||{};
      const diary=Array.isArray(sm.diary)?sm.diary:[];
      const narr=Array.isArray(sm.relationship_narratives)?sm.relationship_narratives:[];
      const cards=ab.slice().reverse().map(x=>'<div class="event-card"><b>'+esc(x.title||"事件")+'</b><p>'+esc(x.meaning||x.reflection||"")+'</p></div>');
      diary.slice(-3).reverse().forEach(x=>{cards.push('<div class="event-card"><b>日记 '+esc(String(x.date||""))+'</b><p>'+esc(String(x.text||""))+'</p></div>');});
      narr.slice(-2).reverse().forEach(x=>{cards.push('<div class="event-card"><b>关系叙述</b><p>'+esc(String(x.text||""))+'</p></div>');});
      $("autoBioList").innerHTML=cards.length?cards.join(""):'<p class="api-note">还没有自传体记录。</p>';
    }
    if($("regStats")){
      const rs=s.regulation_stats||{}; const ks=Object.keys(rs); const nowMs=Date.now();
      const rows=ks.map(k=>{
        const v=rs[k]||{};
        const weighted=_regWeightedScore(v,nowMs);
        const wText=weighted==null?"no use":((weighted>=0?"+":"")+weighted.toFixed(2));
        const ageText=Number(v.last_update||0)>0?(" · "+Math.round(_ageDaysFrom(v.last_update))+"d"):"";
        return '<div title="'+esc(k)+'：存储值 uses/success/cost 只增不减；选择策略时用 10 天半衰加权分"><small>'+esc(_regLabel(k))+'</small><b>'+Number(v.uses||0)+' / '+Number(v.success||0)+' · 加权 '+wText+ageText+'</b></div>';
      }).join("");
      $("regStats").innerHTML=rows||'<div><small>regulation</small><b>暂无</b></div>';
    }
    if($("personaBaseline")) $("personaBaseline").innerHTML=[
      ["baseline_v",p.baseline_v],["baseline_a",p.baseline_a],["energy",p.energy_baseline],
      ["social",p.social_baseline],["dominance",p.da_baseline],["recovery",p.recovery_rate]
    ].map(x=>'<div><small>'+x[0]+'</small><b>'+(x[1]==null?"–":Number(x[1]).toFixed(2))+'</b></div>').join("");
    renderSessionList();
    try{applyApiConfig();}catch(e){}
    try{applyPersonaSelect();}catch(e){ if(window.console&&console.warn) console.warn('[biocore] applyPersonaSelect failed:',e); }
    try{applyLlmFunctions();}catch(e){ if(window.console&&console.warn) console.warn('[biocore] applyLlmFunctions failed:',e); }
  }
  function applyPersonaSelect(){
    const sel=$("personaSelect"); if(!sel) return;
    const ps=Array.isArray(data.personas)?data.personas:[];
    const cur=String(data.persona_id||"");
    sel.innerHTML='<option value="">跟随默认人设</option>'+ps.map(p=>'<option value="'+esc(String(p.id||""))+'">'+esc(String(p.name||p.id||""))+'</option>').join("");
    sel.value=cur;
  }
  function _providerKind(p){
    const s=(((p&&p.id)||"")+" "+((p&&p.model)||"")+" "+((p&&p.type)||"")).toLowerCase();
    if(/(img|image|vision|t2i|dall|stable|midjourney|exusiai-img)/.test(s)) return "vision";
    if(/(tts|speech|voice)/.test(s)) return "tts";
    if(/(embed|bge|text-embedding)/.test(s)) return "embedding";
    if(/rerank/.test(s)) return "rerank";
    return "chat";
  }
  function applyLlmFunctions(){
    const fns=(data&&data.llm_functions)||{};
    const provs=(data&&data.llm_providers)||[];
    LLM_FUNCTIONS.forEach(name=>{
      const chk=$("fn_"+name+"_enabled");
      const sel=$("fn_"+name+"_provider");
      const cfg=fns[name]||{};
      if(chk) chk.checked=cfg.enabled===true;
      // event_ranking intentionally has no provider/model select: its
      // embedding and rerank always follow the API 接入 default config.
      if(sel){
        const vision = name==="image_caption";
        const filtered = provs.filter(p=> vision ? _providerKind(p)==="vision" : _providerKind(p)==="chat");
        const options = filtered.length ? filtered
          : (vision ? [] : provs.filter(p=>_providerKind(p)!=="vision"));
        const followLabel = vision ? "跟随图片 API（默认视觉 provider）" : "跟随主 LLM";
        sel.innerHTML='<option value="follow_llm">'+followLabel+'</option>'+options.map(p=>'<option value="'+esc(String(p.id||""))+'">'+esc(String(p.model||p.id||""))+'</option>').join("");
        sel.value=String(cfg.provider||"follow_llm");
      }
    });
  }
  function bindLlmFunctionRoute(name){
    const chk=$("fn_"+name+"_enabled");
    const sel=$("fn_"+name+"_provider");
    const post=async(key,val,revert)=>{
      if(!bridge){ revert(); if(window.alert) window.alert("静态预览模式无法保存设置，请从 AstrBot 插件视图打开。"); return; }
      try{
        const raw=await bridge.apiPost("page/toggle",{key:key,value:val});
        const payload=raw&&raw.data?raw.data:raw;
        if(!payload||payload.status==="error"||payload.status==="fail") throw new Error((payload&&payload.message)||"保存失败");
        if(data){
          const field = key.endsWith("_enabled") ? "enabled" : "provider";
          data.llm_functions=Object.assign({},data.llm_functions||{}, {[name]:Object.assign({},(data.llm_functions||{})[name]||{},{[field]:val})});
        }
      }catch(err){ revert(); if(window.alert) window.alert("LLM 功能设置保存失败："+String(err&&err.message||err)); }
    };
    if(chk) chk.addEventListener("change",()=>{
      const val=!!chk.checked;
      post(name+"_enabled",val,()=>{ chk.checked=!val; });
    });
    if(sel) sel.addEventListener("change",()=>{
      const val=String(sel.value||"follow_llm");
      post(name+"_provider",val,()=>{});
    });
  }
  function setMetric(l,b,v){const n=clamp(v);$(l).textContent=n.toFixed(2);$(b).style.width=pct(n);}
  function switchView(name){
    document.querySelectorAll(".nav-item").forEach(x=>x.classList.toggle("active",x.dataset.view===name));
    document.querySelectorAll(".view").forEach(v=>v.classList.toggle("active",v.id==="view-"+name));
    const names={overview:"情绪概览",now:"她现在",relationship:"关系",records:"记录",intent:"表达意图",persona:"人格自我",sessions:"活动会话",pipeline:"流水线",autonomy:"自主行为",settings:"设置"};
    setText("crumbView", names[name]||name);
  }

  // Debug deep-link: ?view=settings&tab=settingsVisual&mode=advanced
  try{
    const _qp=new URLSearchParams(location.search);
    const _v=_qp.get("view"); const _t=_qp.get("tab"); const _m=_qp.get("mode");
    if(_m){ try{ setSettingsView? setSettingsView(_m):null; }catch(e){} }
    if(_t && _v!=="settings"){
      setTimeout(()=>{
        try{
          const btn=document.querySelector('[data-intent-tab="'+_t+'"]');
          if(btn&&btn.click) btn.click();
        }catch(e){}
      },400);
    }
    if(_v==="settings"&&_t){
      setTimeout(()=>{
        try{
          const btn=document.querySelector('#settingsTabs [data-settings-target="'+_t+'"]');
          if(btn&&btn.click) btn.click();
        }catch(e){}
      },300);
    }
    if(_v){ setTimeout(()=>{try{switchView(_v);}catch(e){}},350); }
  }catch(e){}
  function visualSave(){storeSet("bio_show_nodes",visual.memoryNodes?"1":"0");storeSet("bio_show_node_links",visual.links?"1":"0");storeSet("bio_show_ripple",visual.echo?"1":"0");storeSet("bio_show_noise",visual.noise?"1":"0");storeSet("bio_show_echo",visual.echo?"1":"0");storeSet("bio_show_ripple",visual.ripple?"1":"0");storeSet("bio_show_dominance",visual.dominance?"1":"0");storeSet("bio_show_social",visual.social?"1":"0");storeSet("bio_show_links",visual.links?"1":"0");storeSet("bio_show_nodes",visual.nodes?"1":"0");storeSet("bio_show_node_links",visual.nodeLinks?"1":"0");storeSet("bio_show_memory_nodes",visual.memoryNodes?"1":"0");storeSet("bio_show_memory_balls_important",visual.memoryBallsImportant?"1":"0");storeSet("bio_show_emotion_rings",visual.emotionRings?"1":"0");storeSet("bio_intensity",visual.intensity);storeSet("bio_memory_ring_style",visual.memoryRingStyle);storeSet("bio_memory_ball_color_mode",visual.memoryBallColorMode);storeSet("bio_memory_ball_gravity",visual.memoryBallGravity?"1":"0");storeSet("bio_show_orb_legend",visual.orbLegend?"1":"0");storeSet("bio_show_autonomy_panel",visual.showAutonomyPanel?"1":"0");storeSet("bio_show_learning_panel",visual.showLearningPanel?"1":"0");storeSet("bio_show_chain_list",visual.showChainList?"1":"0");if(window.__biocoreState)window.__biocoreState.visual=Object.assign({},visual);}
  setChecked("swShowNoise", visual.noise); setChecked("swShowEcho", visual.echo);
  if($("swShowDominance"))setChecked("swShowDominance", visual.dominance);
  if($("swShowSocial"))setChecked("swShowSocial", visual.social);
  if($("swShowLinks"))setChecked("swShowLinks", visual.links);
  if($("swShowMemoryNodes"))setChecked("swShowMemoryNodes", visual.memoryNodes);
  if($("swMemoryBallsImportant"))setChecked("swMemoryBallsImportant", visual.memoryBallsImportant);
  if($("swOrbLegend"))setChecked("swOrbLegend", visual.orbLegend);
  if($("swShowAutonomyPanel"))setChecked("swShowAutonomyPanel", visual.showAutonomyPanel);
  if($("swShowLearningPanel"))setChecked("swShowLearningPanel", visual.showLearningPanel);
  if($("swShowChainList"))setChecked("swShowChainList", visual.showChainList);
  if($("swShowEmotionRings"))setChecked("swShowEmotionRings", visual.emotionRings);
  setVal("orbIntensity", visual.intensity);
  if($("selMemoryRingStyle"))setVal("selMemoryRingStyle", visual.memoryRingStyle);
  if($("selMemoryBallColorMode"))setVal("selMemoryBallColorMode", visual.memoryBallColorMode);
  if($("swMemoryBallGravity"))setChecked("swMemoryBallGravity", visual.memoryBallGravity);
  $("swShowNoise").addEventListener("change",e=>{visual.noise=e.target.checked;visualSave();});
  $("swShowEcho").addEventListener("change",e=>{visual.echo=e.target.checked;visual.ripple=e.target.checked;visualSave();});
  if($("swShowDominance"))$("swShowDominance").addEventListener("change",e=>{visual.dominance=e.target.checked;visualSave();});
  if($("swShowSocial"))$("swShowSocial").addEventListener("change",e=>{visual.social=e.target.checked;visualSave();});
  if($("swShowLinks"))$("swShowLinks").addEventListener("change",e=>{visual.links=e.target.checked;visual.nodeLinks=e.target.checked;visualSave();});
  if($("swShowMemoryNodes"))$("swShowMemoryNodes").addEventListener("change",e=>{visual.memoryNodes=e.target.checked;visual.nodes=e.target.checked;visualSave();updateOrbLegend();});
  const applyAdvancedOpen=(on)=>{
  const box=$("visualAdvancedBody"); if(!box) return;
  box.hidden=!on;
  [...box.children].forEach((row)=>{
    if(!row||!row.classList||!row.classList.contains("setting-row")) return;
    if(on) row.style.setProperty("display","flex","important");
    else row.style.removeProperty("display");
  });
};
if($("swVisualAdvanced")){
  $("swVisualAdvanced").addEventListener("change",e=>applyAdvancedOpen(!!e.target.checked));
  applyAdvancedOpen($("swVisualAdvanced").checked === true);
};
  if($("swMemoryBallsImportant"))$("swMemoryBallsImportant").addEventListener("change",e=>{visual.memoryBallsImportant=e.target.checked;visualSave();updateOrbLegend();});
  if($("swOrbLegend"))$("swOrbLegend").addEventListener("change",e=>{visual.orbLegend=e.target.checked;visualSave();updateOrbLegend();});
  if($("swShowAutonomyPanel"))$("swShowAutonomyPanel").addEventListener("change",e=>{visual.showAutonomyPanel=e.target.checked;visualSave();applyPanelVisibility();});
  if($("swShowLearningPanel"))$("swShowLearningPanel").addEventListener("change",e=>{visual.showLearningPanel=e.target.checked;visualSave();applyPanelVisibility();});
  if($("swShowChainList"))$("swShowChainList").addEventListener("change",e=>{visual.showChainList=e.target.checked;visualSave();applyPanelVisibility();});
  if($("swShowEmotionRings"))$("swShowEmotionRings").addEventListener("change",e=>{visual.emotionRings=e.target.checked;visualSave();});
  $("orbIntensity").addEventListener("input",e=>{visual.intensity=Number(e.target.value);visualSave();});
  if($("selMemoryRingStyle"))$("selMemoryRingStyle").addEventListener("change",e=>{visual.memoryRingStyle=e.target.value==="orbit"?"orbit":"solid";visualSave();});
  if($("selMemoryBallColorMode"))$("selMemoryBallColorMode").addEventListener("change",e=>{visual.memoryBallColorMode=e.target.value==="primary"?"primary":"mixed";visualSave();});
  if($("swMemoryBallGravity"))$("swMemoryBallGravity").addEventListener("change",e=>{visual.memoryBallGravity=!!e.target.checked;visualSave();});
  function bindBehaviorToggle(id,key){
    const el=$(id);
    if(!el) return;
    el.addEventListener("change",async e=>{
      const val=!!e.target.checked;
      if(!bridge){ e.target.checked=!val; if(window.alert) window.alert("静态预览模式无法保存设置，请从 AstrBot 插件视图打开。"); return; }
      try{
        const raw=await bridge.apiPost("page/toggle",{key:key,value:val});
        const payload=raw&&raw.data?raw.data:raw;
        if(!payload||payload.status==="error"||payload.status==="fail") throw new Error((payload&&payload.message)||"保存失败");
        if(data) data[key]=val;
        if(key==="safety_enabled") renderSafetyWarn();
      }catch(err){
        e.target.checked=!val;
        if(key==="safety_enabled") renderSafetyWarn();
        if(window.alert) window.alert("设置保存失败："+String(err&&err.message||err));
      }
    });
  }
  bindBehaviorToggle("swMemEmbedding","memory_dedup_embedding");
  bindBehaviorToggle("swSafetyEnabled","safety_enabled");
  bindBehaviorToggle("swHybridRetrieval","hybrid_retrieval");
  bindBehaviorToggle("swLlmCandidates","llm_memory_candidates");
  const personaSel=$("personaSelect");
  if(personaSel) personaSel.addEventListener("change",async e=>{
    const val=String(e.target.value||"");
    if(!bridge){ return; }
    try{
      const raw=await bridge.apiPost("page/toggle",{key:"persona_id",value:val});
      const payload=raw&&raw.data?raw.data:raw;
      if(!payload||payload.status==="error"||payload.status==="fail") throw new Error((payload&&payload.message)||"保存失败");
      if(data) data.persona_id=val;
    }catch(err){
      if(window.alert) window.alert("人格来源保存失败："+String(err&&err.message||err));
    }
  });
  LLM_FUNCTIONS.forEach(bindLlmFunctionRoute);
  const resetVisualBtn=$("resetVisualBtn");
  if(resetVisualBtn) resetVisualBtn.addEventListener("click",()=>{
    try{ ["bio_show_noise","bio_show_echo","bio_show_ripple","bio_show_dominance","bio_show_social","bio_show_links","bio_show_nodes","bio_show_node_links","bio_show_memory_nodes","bio_show_memory_balls_important","bio_show_orb_legend","bio_show_autonomy_panel","bio_show_learning_panel","bio_show_chain_list","bio_show_emotion_rings","bio_intensity"].forEach(k=>localStorage.removeItem(k)); }catch(e){}
    try{ location.reload(); }catch(e){}
  });
  const selfSave=$("selfSaveBtn");
  if(selfSave) selfSave.addEventListener("click",async()=>{
    const st=$("selfSaveState");
    if(!bridge){if(st)st.textContent="未连接";return;}
    try{
      await bridge.apiPost("page/self_model",{who_am_i:$("selfWho").value,narrative:$("selfNarrative").value,boundaries:$("selfBoundaries").value.split("\n"),consistency:$("selfConsistency").value.split("\n")});
      if(st)st.textContent="已保存";
    }catch(e){if(st)st.textContent="保存失败";}
  });
  const summarySel = $("summarySession");
  if (summarySel) summarySel.addEventListener("change", () => {
    summarySessionFilter = summarySel.value || "";
    renderSessionMemory();
  });
  // Top "刷新" must reload the page (HTML/JS/CSS); load() only re-fetches
  // page/status data and cannot pick up UI/asset updates.
  $("refreshBtn").addEventListener("click",()=>{
    try{ location.reload(); }catch(e){ load(); }
  });
  $("themeToggle").addEventListener("click",()=>{
    const dark = document.documentElement.dataset.theme !== "dark";
    applyTheme(dark); storeSet("bio_theme", dark ? "dark" : "light");
  });

  let apiInit = false;
  function setOptions(sel, models, current) {
    if (!sel) return;
    const list = Array.from(new Set((models || []).filter(Boolean)));
    if (current && !list.includes(current)) list.unshift(current);
    sel.innerHTML = list.map(m => '<option value="' + esc(m) + '">' + esc(m) + '</option>').join("");
    if (current) sel.value = current;
  }
  function apiBlock(kind, prefix, cfg, def) {
    const src = $(prefix + "Source"), base = $(prefix + "Base"), key = $(prefix + "Key"),
          model = $(prefix + "Model"), state = $(prefix + "SourceState"), note = $(prefix + "Note");
    if (!src) return;
    const source = cfg.source || (def && def.provider_id ? "astrbot" : "custom");
    src.value = source;
    base.value = cfg.base_url || (def && def.base_url) || "";
    setOptions(model, cfg.model ? [cfg.model] : [], cfg.model || (def && def.model) || "");
    key.value = "";
    key.placeholder = cfg.key_saved ? "已保存，留空保持不变" : "输入 API Key";
    const en = $(prefix + "Enabled");
    if (en) en.checked = cfg.enabled !== false;
    if (def && def.provider_id) {
      state.textContent = "ASTRBOT · " + def.provider_id;
      note.textContent = "已检测到 AstrBot " + kind + " provider。默认直接使用它；选择自定义 API 再填下面字段。";
    } else {
      state.textContent = "未检测到 AstrBot provider";
      note.textContent = "没有检测到 AstrBot " + kind + " provider。填写 API Base / API Key / 模型。";
    }
    if (source === "astrbot") {
      base.readOnly = true; key.readOnly = true;
    } else {
      base.readOnly = false; key.readOnly = false;
    }
  }

  function applyApiConfig() {
    if (apiInit || !data) return;
    apiInit = true;
    const cfg = data.api_config || {};
    const defs = { llm: data.astrbot_llm, embedding: data.astrbot_embedding, rerank: data.astrbot_rerank, tts: data.astrbot_tts, image: data.astrbot_image };
    apiBlock("llm", "llm", cfg.llm || {}, defs.llm || null);
    apiBlock("embedding", "embed", cfg.embedding || {}, defs.embedding || null);
    apiBlock("rerank", "rerank", cfg.rerank || {}, defs.rerank || null);
    apiBlock("tts", "tts", cfg.tts || {}, defs.tts || null);
    apiBlock("image", "image", cfg.image || {}, defs.image || null);
    if ($("ttsVoice")) setVal("ttsVoice", (cfg.tts || {}).voice || "");
    if ($("ttsFormat")) setVal("ttsFormat", (cfg.tts || {}).format || "mp3");
    if ($("imageSize")) setVal("imageSize", (cfg.image || {}).size || "");
    const comp = cfg.compression || {};
    const swc = $("swCompress"), th = $("compressThreshold"), mx = $("compressMax");
    if (swc) swc.checked = !!comp.enabled;
    const swSafety = $("swSafetyEnabled");
    if (swSafety) swSafety.checked = !!data.safety_enabled;
    const swHybrid = $("swHybridRetrieval");
    if (swHybrid) swHybrid.checked = data.hybrid_retrieval !== false;
    const swLlmCand = $("swLlmCandidates");
    if (swLlmCand) swLlmCand.checked = data.llm_memory_candidates !== false;
    if (th) th.value = Number(comp.threshold || 6000);
    if (mx) mx.value = Number(comp.max_chars || 800);
    const ms = $("memoryStats");
    if (ms) {
      const m = data.memory || {};
      ms.textContent = "本地记忆：" + Number(m.entries || 0) + " 条 / " + Number(m.sessions || 0) + " 会话";
    }
    const top = $("apiSaveStateTop");
    if (top && !top.dataset.touched) {
      if (!bridge) {
        top.textContent = "静态预览模式：无法读取 AstrBot，请从 AstrBot 插件页打开";
      } else {
        top.textContent = (defs.llm || defs.embedding || defs.rerank)
          ? "已读取 AstrBot 默认，确认后保存"
          : "未检测到 AstrBot provider，可填自定义 API";
      }
    }
  }
  async function loadModels(kind, prefix) {
    const top = $("apiSaveStateTop");
    if (!bridge) { if (top) top.textContent = "未连接 AstrBot 页面桥，无法获取模型"; return; }
    const src = $(prefix + "Source"), base = $(prefix + "Base"), key = $(prefix + "Key"), model = $(prefix + "Model");
    const state = $("apiSaveState");
    if (state) state.textContent = "读取模型…";
    try {
      const raw = await bridge.apiPost("page/models", {
        kind, source: src.value, base_url: base.value, api_key: key.value
      });
      const payload = raw && raw.data ? raw.data : raw;
      if (!payload || payload.status === "error") throw new Error((payload && payload.message) || "no models");
      const models = payload.models || [];
      if (!models.length) throw new Error("empty model list");
      setOptions(model, models, model.value);
      if (state) state.textContent = "已读取 " + models.length + " 个模型";
    } catch (e) {
      if (state) state.textContent = "读取失败：" + String(e && e.message || e);
    }
  }
  async function saveApiConfig() {
    const state = $("apiSaveState"), topState = $("apiSaveStateTop");
    const setState = (t) => { if (state) state.textContent = t; if (topState) topState.textContent = t; };
    if (!bridge) { setState("未连接 AstrBot 页面桥，保存失败"); return; }
    const body = {};
    for (const [kind, prefix] of [["llm", "llm"], ["embedding", "embed"], ["rerank", "rerank"], ["tts", "tts"], ["image", "image"]]) {
      body[kind] = {
        source: $(prefix + "Source").value,
        base_url: $(prefix + "Base").value.trim(),
        model: $(prefix + "Model").value.trim(),
        api_key: $(prefix + "Key").value.trim(),
        enabled: !!($(prefix + "Enabled") ? $(prefix + "Enabled").checked : true)
      };
      if (prefix === "tts") {
        body[kind].voice = $("ttsVoice") ? $("ttsVoice").value.trim() : "";
        body[kind].format = $("ttsFormat") ? $("ttsFormat").value : "";
      }
      if (prefix === "image") body[kind].size = $("imageSize") ? $("imageSize").value.trim() : "";
    }
    body.compression = {
      enabled: !!($("swCompress") && $("swCompress").checked),
      threshold: Number($("compressThreshold") ? $("compressThreshold").value : 6000),
      max_chars: Number($("compressMax") ? $("compressMax").value : 800)
    };
    try {
      const raw = await bridge.apiPost("page/api_config", body);
      const payload = raw && raw.data ? raw.data : raw;
      if (payload && payload.status === "error") throw new Error(payload.message || "save failed");
      setState("已保存 · API 接入");
      if (data) data.api_config = payload || body;
    } catch (e) {
      setState("保存失败：" + String(e && e.message || e));
    }
  }
  ["llm", "embed", "rerank", "tts", "image"].forEach(prefix => {
    const src = $(prefix + "Source");
    if (src) src.addEventListener("change", () => {
      const def = prefix === "llm" ? data.astrbot_llm : (prefix === "embed" ? data.astrbot_embedding : (prefix === "rerank" ? data.astrbot_rerank : (prefix === "tts" ? data.astrbot_tts : data.astrbot_image)));
      if (src.value === "astrbot" && def) {
        $(prefix + "Base").value = def.base_url || "";
        setOptions($(prefix + "Model"), def.model ? [def.model] : [], def.model || "");
      }
      $(prefix + "Base").readOnly = src.value === "astrbot";
      $(prefix + "Key").readOnly = src.value === "astrbot";
    });
    const btn = $(prefix + "ModelsBtn");
    if (btn) btn.addEventListener("click", () => loadModels(prefix === "embed" ? "embedding" : prefix, prefix));
  });
  document.querySelectorAll(".js-save-api").forEach(btn => btn.addEventListener("click", saveApiConfig));
  async function loadAstrBotDefaults() {
    const top = $("apiSaveStateTop");
    if (!bridge) { if (top) top.textContent = "未连接 AstrBot 页面桥"; return; }
    if (top) top.textContent = "正在读取 AstrBot 默认…";
    try {
      const raw = await bridge.apiGet("page/status", {});
      const payload = raw && raw.data ? raw.data : raw;
      if (!payload) throw new Error("empty status");
      data = payload;
      apiInit = false;
      applyApiConfig();
      apiInit = true;
      if (top) top.textContent = "已读取 AstrBot 默认，点击保存";
    } catch (e) {
      if (top) top.textContent = "读取失败：" + String(e && e.message || e);
    }
  }
  const resetBtn = $("resetApiBtn");
  if (resetBtn) resetBtn.addEventListener("click", loadAstrBotDefaults);




  const backupBtn = $("backupBtn");
  if (backupBtn) backupBtn.addEventListener("click", async () => {
    const st = $("backupState");
    if (!bridge) { if (st) st.textContent = "未连接 AstrBot 页面桥，无法下载"; return; }
    if (st) st.textContent = "正在打包备份…";
    try {
      if(!confirm("安全备份不含 API Key，但含记忆与状态；确认下载？")) return;
      const raw = await _adminApiPost("page/backup", {confirm:true});
      const payload = raw && raw.data ? raw.data : raw;
      if(!payload || !payload.token) throw new Error((payload && payload.message) || "empty backup");
      const url = payload.download_url ||
        ("/astrbot_plugin_biocore/page/download/" + encodeURIComponent(payload.token));
      if (st) st.textContent = "正在下载…";
      window.location.href = url;
      if (st) st.textContent = "下载已开始 · " + (payload.filename || "");
    } catch (e) {
      if (st) st.textContent = "下载失败：" + String(e && e.message || e);
    }
  });


  // P2: admin token field (localStorage only).
  const adminTokenInput = $("adminTokenInput");
  if (adminTokenInput) {
    try { adminTokenInput.value = localStorage.getItem("biocore_admin_token") || ""; } catch(e) {}
    adminTokenInput.addEventListener("change", () => {
      try { localStorage.setItem("biocore_admin_token", String(adminTokenInput.value || "")); } catch(e) {}
    });
  }
  async function _dataExport(){
    const st=$("dataAdminState");
    try {
      const raw=await _adminApiPost("page/data_export",{confirm:true});
      const payload=raw&&raw.data?raw.data:raw;
      if(!payload||payload.status==="error") throw new Error((payload&&payload.message)||"export failed");
      const blob=new Blob([JSON.stringify(payload,null,1)],{type:"application/json"});
      const url=URL.createObjectURL(blob);
      const a=document.createElement("a"); a.href=url; a.download="biocore_export.json";
      document.body.appendChild(a); a.click(); a.remove(); setTimeout(()=>URL.revokeObjectURL(url),10000);
      if(st) st.textContent="导出已开始（不含 API Key）";
    } catch(e) { if(st) st.textContent="导出失败："+String(e&&e.message||e); }
  }
  async function _dataDelete(){
    const st=$("dataAdminState");
    if(!confirm("硬删除记忆/事件/洞察/状态/人设（先写 tombstone）。确认？")) return;
    try {
      const t=await _adminApiPost("page/data_delete_token",{});
      const token=(t&&t.data?t.data.token:t&&t.token)||"";
      if(!token) throw new Error("删除 token 获取失败");
      const raw=await _adminApiPost("page/data_delete",{token, scopes:["memory","events","insights","state","learning_state","archives","persona","self_model","image_cache"]});
      const payload=raw&&raw.data?raw.data:raw;
      if(!payload||payload.status==="error") throw new Error((payload&&payload.message)||"delete failed");
      if(st) st.textContent="已删除："+String((payload.removed||[]).join(", "))+(payload.tombstone?"（tombstone 已脱敏，不可恢复原文）":"");
      await _focusReloadData();
    } catch(e) { if(st) st.textContent="删除失败："+String(e&&e.message||e); }
  }
  const dataExportBtn=$("dataExportBtn"), dataDeleteBtn=$("dataDeleteBtn");
  if(dataExportBtn) dataExportBtn.addEventListener("click",_dataExport);
  if(dataDeleteBtn) dataDeleteBtn.addEventListener("click",_dataDelete);

  let restoreArmed = false, restoreTimer = null;
  function resetRestore() {
    restoreArmed = false;
    if (restoreTimer) { clearTimeout(restoreTimer); restoreTimer = null; }
  }
  const restoreFile = $("restoreFile");
  if (restoreFile) restoreFile.addEventListener("change", () => {
    resetRestore();
    const st = $("restoreState");
    const f = restoreFile.files && restoreFile.files[0];
    if (st) st.textContent = f ? ("已选择：" + f.name + "，点击两次加载") : "尚未选择备份。";
  });
  const restoreBtn = $("restoreBtn");
  if (restoreBtn) restoreBtn.addEventListener("click", async () => {
    const st = $("restoreState");
    const f = restoreFile && restoreFile.files && restoreFile.files[0];
    if (!f) { if (st) st.textContent = "请先选择备份 zip。"; return; }
    if (!restoreArmed) {
      restoreArmed = true;
      if (restoreTimer) clearTimeout(restoreTimer);
      restoreTimer = setTimeout(resetRestore, 5000);
      if (st) st.textContent = "警告：会覆盖当前核心数据（人设/记忆/状态），但不会覆盖 API 配置/密钥。5 秒内再点一次确认。";
      return;
    }
    resetRestore();
    if (!bridge) { if (st) st.textContent = "未连接 AstrBot 页面桥，无法加载。"; return; }
    if (st) st.textContent = "正在读取并恢复备份…";
    try {
      const base64 = await new Promise((resolve, reject) => {
        const r = new FileReader();
        r.onload = () => {
          const s = String(r.result || "");
          resolve(s.includes(",") ? s.slice(s.indexOf(",") + 1) : s);
        };
        r.onerror = reject;
        r.readAsDataURL(f);
      });
      const raw = await _adminApiPost("page/restore", { filename: f.name, base64 });
      const payload = raw && raw.data ? raw.data : raw;
      if (!payload || payload.status === "error") throw new Error((payload && payload.message) || "restore failed");
      if (st) st.textContent = (payload.message ||
        ("已恢复 " + Number(payload.files || 0) + " 个文件")) +
        "；已跳过 api_config（保留当前 Key），请重启 AstrBot 生效。";
    } catch (e) {
      if (st) st.textContent = "恢复失败：" + String(e && e.message || e);
    }
  });


  const apiBody = $("apiBody"), apiFoldBtn = $("apiFoldBtn");
  let apiFolded = storeGet("bio_api_folded", "0") === "1";
  function renderApiFold() {
    if (!apiBody || !apiFoldBtn) return;
    apiBody.classList.toggle("collapsed", apiFolded);
    apiFoldBtn.textContent = apiFolded ? "展开" : "折叠";
  }
  if (apiFoldBtn) {
    apiFoldBtn.addEventListener("click", () => {
      apiFolded = !apiFolded;
      storeSet("bio_api_folded", apiFolded ? "1" : "0");
      renderApiFold();
    });
    renderApiFold();
  }


  const compressNowBtn = $("compressNowBtn");
  if (compressNowBtn) compressNowBtn.addEventListener("click", async () => {
    const st = $("compressState");
    if (!bridge) { if (st) st.textContent = "未连接 AstrBot 页面桥"; return; }
    if (st) st.textContent = "正在压缩…";
    try {
      const raw = await bridge.apiPost("page/consolidate", {});
      const payload = raw && raw.data ? raw.data : raw;
      if (!payload || payload.status === "error") throw new Error((payload && payload.message) || "compress failed");
      if (st) st.textContent = "压缩完成 · " + Number(payload.files || 0) + " 个会话";
    } catch (e) {
      if (st) st.textContent = "压缩失败：" + String(e && e.message || e);
    }
  });


  const insightNowBtn = $("insightNowBtn");
  if (insightNowBtn) insightNowBtn.addEventListener("click", async () => {
    const st = $("insightState");
    if (!bridge) { if (st) st.textContent = "未连接 AstrBot 页面桥"; return; }
    if (st) st.textContent = "正在生成长期模式洞察…";
    try {
      const raw = await bridge.apiPost("page/insight", {});
      const payload = raw && raw.data ? raw.data : raw;
      if (!payload || payload.status === "error") throw new Error((payload && payload.message) || "insight failed");
      const text = String(payload.insight || "").trim();
      if (text && payload.generated !== false) {
        if (st) st.textContent = "已生成：" + text.slice(0, 120);
        if (data) {
          data.insights = Array.isArray(data.insights) ? data.insights : [];
          data.insights.unshift({ ts: Date.now() / 1000, insight: text });
        }
        renderInsightHistory();
      } else if (st) {
        st.textContent = payload.message || "没有生成新的长期洞察";
      }
    } catch (e) {
      if (st) st.textContent = "生成失败：" + String(e && e.message || e);
    }
  });

  try { const v = new URLSearchParams(location.search).get('view'); if (v) switchView(v); } catch (e) {}
  const foldSvg = (d) => '<svg viewBox="0 0 24 24" aria-hidden="true">' + d + '</svg>';
  const foldIcons = [
    foldSvg('<circle cx="12" cy="12" r="8"/><path d="M12 4v16M4 12h16"/><circle cx="12" cy="12" r="3"/>'),
    foldSvg('<path d="M4 7h16v13H4z"/><path d="M2 3h20v4H2z"/><path d="M9 12h6"/>'),
    foldSvg('<path d="M9 7V3M15 7V3M6 7h12v5a6 6 0 0 1-12 0V7Z"/><path d="M12 18v3"/>'),
    foldSvg('<path d="M4 5a3 3 0 0 1 3-3h13v18H7a3 3 0 0 1-3-3V5Z"/><path d="M8 2v18"/>'),
    foldSvg('<rect x="7" y="7" width="10" height="10" rx="2"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>'),
    foldSvg('<path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/>'),
    foldSvg('<circle cx="12" cy="12" r="7"/><ellipse cx="12" cy="12" rx="10" ry="3.5" transform="rotate(-25 12 12)"/>'),
    foldSvg('<path d="M6 3h12v18l-6-4-6 4V3Z"/>'),
    foldSvg('<path d="M12 3v11M8 10l4 4 4-4M4 17v3h16v-3"/>')
  ];
  const foldLabels = ["\u81EA\u4F20","\u6863\u6848","API","\u77E5\u8BC6\u5E93","\u8BB0\u5FC6","\u53C2\u6570","\u7403\u4F53","\u4E8B\u4EF6","\u5907\u4EFD"];
  let foldOverlay = null, foldSheet = null;
  function ensureFoldOverlay(){
    if(foldOverlay) return;
    foldOverlay=document.createElement("div"); foldOverlay.className="fold-overlay";
    const wrap=document.createElement("div"); wrap.className="fold-sheet-wrap";
    const close=document.createElement("button"); close.type="button"; close.className="fold-overlay-close"; close.textContent="×";
    foldSheet=document.createElement("div"); foldSheet.className="fold-sheet";
    wrap.appendChild(close); wrap.appendChild(foldSheet); foldOverlay.appendChild(wrap); document.body.appendChild(foldOverlay);
    close.addEventListener("click",()=>closeTile(foldSheet._foldPanel));
    foldOverlay.addEventListener("click",e=>{if(e.target===foldOverlay) closeTile(foldSheet._foldPanel);});
  }
  function openTile(panel){
    ensureFoldOverlay();
    if(!panel || panel.classList.contains("in-sheet")) return;
    const ph=document.createElement("div"); ph.className="fold-placeholder";
    const _face=panel.querySelector(".fold-face");
    if(_face) ph.appendChild(_face.cloneNode(true));
    panel.parentNode.insertBefore(ph,panel); panel._foldPh=ph;
    panel.classList.remove("folded"); panel.classList.add("in-sheet"); panel.style.display="block";
    foldSheet.innerHTML=""; foldSheet.appendChild(panel); foldSheet._foldPanel=panel;
    foldOverlay.classList.add("active");
    requestAnimationFrame(()=>foldOverlay.classList.add("show"));
  }
  function closeTile(panel){
    if(!panel || !foldOverlay) return;
    foldOverlay.classList.remove("show");
    setTimeout(()=>{
      foldOverlay.classList.remove("active");
      panel.classList.remove("in-sheet"); panel.classList.add("folded"); panel.style.display="";
      if(panel._foldPh){panel._foldPh.replaceWith(panel); delete panel._foldPh;}
    },220);
  }
  function setupFolds(){
    document.querySelectorAll("[data-fold]").forEach((panel,idx)=>{
      if(panel.dataset.foldReady) return;
      panel.dataset.foldReady="1";
      const body=document.createElement("div"); body.className="fold-body";
      while(panel.firstChild) body.appendChild(panel.firstChild);
      const title=body.querySelector("h3,h2");
      const label=panel.dataset.foldLabel||foldLabels[idx]||(title?title.textContent.trim():"\u9009\u9879");
      const face=document.createElement("div"); face.className="fold-face";
      face.innerHTML='<span class="fold-icon">'+(panel.dataset.foldIcon||foldIcons[idx%foldIcons.length])+'</span><small>'+esc(label)+'</small>';
      const close=document.createElement("button"); close.type="button"; close.className="fold-close"; close.textContent="×";
      close.addEventListener("click",e=>{e.stopPropagation(); closeTile(panel);});
      panel.appendChild(face); panel.appendChild(close); panel.appendChild(body);
      panel.classList.add("fold-panel","folded");
      face.addEventListener("click",()=>openTile(panel));
    });
  }
  function arrangeFoldGrid(){
    document.querySelectorAll(".view").forEach(view=>{
      const panels=[...view.querySelectorAll("[data-fold]")];
      if(!panels.length || view.querySelector(".fold-grid")) return;
      const grid=document.createElement("div"); grid.className="fold-grid";
      const firstTitle=view.querySelector(".section-title");
      if(firstTitle) firstTitle.insertAdjacentElement("afterend",grid); else view.prepend(grid);
      panels.forEach(p=>grid.appendChild(p));
      if(view.id==="view-settings"){
        view.querySelectorAll(".section-title").forEach((t,i)=>{if(i>0) t.style.display="none";});
      }
      if(window.innerWidth<=640 && panels.length>=4 && panels.length<=7){
        grid.classList.add("fold-grid-fill");
        grid.style.gridTemplateColumns="repeat("+panels.length+",minmax(0,1fr))";
      }
    });
  }
  const TAB_KEYS={settings:"biocore_settings_tab",persona:"biocore_persona_tab",session:"biocore_session_tab",intent:"biocore_intent_tab"};
  // Memory-first: iframe sandboxes may throw on localStorage (SecurityError).
  let _activeSettingsTab=null, _activePersonaTab=null, _activeSessionTab=null;
  function _tabRead(key){ try{ return window.localStorage.getItem(key)||""; }catch(e){ return ""; } }
  function _tabWrite(key,value){ try{ window.localStorage.setItem(key,value); }catch(e){} }
  function _tabValid(tabs,attr){ return tabs.map(t=>t.dataset[attr]).filter(Boolean); }
  function _tabPick(tabs,attr,key,mem,fallback){ const valid=_tabValid(tabs,attr); const stored=_tabRead(key);
    if(mem&&valid.includes(mem)) return mem;
    if(stored&&valid.includes(stored)) return stored;
    return fallback; }
  function setupSettingsTabs(){
    const bar=$("settingsTabs"); if(!bar) return;
    const tabs=[...bar.querySelectorAll(".settings-tab")];
    if(!tabs.length) return;
    const activate=(name,remember)=>{
      tabs.forEach(t=>t.classList.toggle("active",t.dataset.settingsTarget===name));
      document.querySelectorAll("#view-settings .settings-panel").forEach(p=>p.classList.toggle("active",p.id===name));
      document.querySelectorAll("#view-settings .section-title[data-settings-title]").forEach(t=>t.classList.toggle("active",t.dataset.settingsTitle===name));
      _activeSettingsTab=name;
      if(remember) _tabWrite(TAB_KEYS.settings,name);
    };
    if(!bar.dataset.bound){
      bar.dataset.bound="1";
      tabs.forEach(t=>t.addEventListener("click",()=>activate(t.dataset.settingsTarget||"settingsBio",true)));
    }
    activate(_tabPick(tabs,"settingsTarget",TAB_KEYS.settings,_activeSettingsTab,"settingsBio"),false);
  }
  function setupPersonaTabs(){
    const bar=$("personaTabs"); if(!bar) return;
    const tabs=[...bar.querySelectorAll(".persona-tab")];
    const panels=[...document.querySelectorAll("#view-persona .persona-tabpanel")];
    if(!tabs.length) return;
    const activate=(name,remember)=>{
      tabs.forEach(t=>t.classList.toggle("active",t.dataset.personaTab===name));
      panels.forEach(p=>p.classList.toggle("active",p.dataset.personaTab===name));
      _activePersonaTab=name;
      if(remember) _tabWrite(TAB_KEYS.persona,name);
    };
    if(!bar.dataset.bound){
      bar.dataset.bound="1";
      tabs.forEach(t=>t.addEventListener("click",()=>activate(t.dataset.personaTab,true)));
    }
    activate(_tabPick(tabs,"personaTab",TAB_KEYS.persona,_activePersonaTab,"baseline"),false);
  }
  function setupSessionTabs(){
    const bar=$("sessionTabs"); if(!bar) return;
    const tabs=[...bar.querySelectorAll(".persona-tab")];
    const panels=[...document.querySelectorAll("#view-sessions .session-tabpanel")];
    if(!tabs.length) return;
    const activate=(name)=>{
      tabs.forEach(t=>t.classList.toggle("active",!!name&&t.dataset.sessionTab===name));
      panels.forEach(p=>p.classList.toggle("active",!!name&&p.dataset.sessionTab===name));
    };
    const activateTab=(name,remember)=>{
      _activeSessionTab=name||null;
      activate(name);
      if(remember) _tabWrite(TAB_KEYS.session,name||"");
    };
    if(!bar.dataset.bound){
      bar.dataset.bound="1";
      tabs.forEach(t=>t.addEventListener("click",()=>{
        const name=t.dataset.sessionTab||"records";
        if(t.classList.contains("active")) activateTab(null,true); else activateTab(name,true);
      }));
    }
    const restored=_tabPick(tabs,"sessionTab",TAB_KEYS.session,_activeSessionTab,null);
    activate(restored);
  }
  const AUTONOMY_PANEL_HTML = `
<div class="section-title"><div><div class="eyebrow">AUTONOMY</div><h2>自主行为</h2></div><span class="hint">仅在私聊路径生效；群聊不主动发消息</span></div>
<div class="panel settings">
  <div class="setting-row"><div><b>启用自主主动发消息</b><small>总开关；关闭时不做任何主动行为</small></div><label class="switch"><input type="checkbox" id="autonomyEnabled"><span></span></label></div>
  <div class="setting-row"><div><b>允许真正发送</b><small>关闭时只计算不发送</small></div><label class="switch"><input type="checkbox" id="autonomySend"><span></span></label></div>
  <div class="setting-row"><div><b>黏人模式（不放弃）</b><small>抽离期仍低频尝试（按小时额度）</small></div><label class="switch"><input type="checkbox" id="autonomyClingy" checked><span></span></label></div>
  <div class="setting-row"><div><b>依恋风格</b><small>决定沉默曲线的形状</small></div><select id="autonomyAttachment"><option value="secure">安全型</option><option value="anxious">焦虑型</option><option value="avoidant">回避型</option></select></div>
  <div class="setting-row"><div><b>拒绝敏感性</b><small>0-1，越高越容易自责</small></div><input type="number" id="autonomyRS" min="0" max="1" step="0.05" value="0.4"></div>

  <div class="setting-row"><div><b>她现在多想找你</b></div></div>
  <div class="setting-row"><div style="flex:1"><div style="display:flex;justify-content:space-between;align-items:baseline;gap:12px"><b style="font-size:14px" id="autonomyVPct">0%</b><small id="autonomyVText">V — / —</small></div><div class="bar" style="height:4px;margin-top:8px"><i id="autonomyVBarFill"></i></div><small id="autonomyParts">drift —</small><small id="autonomyBlockReason">点击「立即评估」查看</small></div></div>
  <div class="setting-row"><div><b>动机分解</b><small id="autonomyMotive">等你 — · 被压 — · 综合 —</small></div></div>
  <div class="setting-row"><div><b>她等了你多久</b><small id="autonomySilence">—</small></div></div>
  <div class="setting-row"><div><b>自责与自信</b><small id="autonomyBlame">自责 — · 自信 —</small></div></div>
  <div class="setting-row"><div><b>本小时额度</b><small id="autonomyLimit">本小时已发 — · 被限制 —</small></div></div>
  <div class="setting-row"><div><b>闭环统计</b><small id="autonomyLoop">主动 — · 被回 —</small></div></div>
  <div class="setting-row"><div><b>上次主动</b><small id="autonomyLastReason">—</small></div></div>

  <div class="setting-row"><div><b>立即评估</b><small id="autonomyCheckState">会推进一次 tick</small></div><button class="btn" id="autonomyCheckBtn" type="button">立即评估</button></div>
  <div class="setting-row"><div><b>测试触发</b><small id="autonomyTestState">把 V 抬到阈值以上，等下一 tick</small></div><div class="inline-actions"><button class="btn" id="autonomyTestBtn" type="button">测试触发一次</button><button class="btn" id="autonomyResetBtn" type="button">复位</button></div></div>
  <div class="setting-row" id="autonomyTestConfirm" hidden><div><b>确认测试触发？</b><small>下一次 tick 会触发一次主动消息</small></div><div class="inline-actions"><button class="btn" id="autonomyTestConfirmYes" type="button">确认</button><button class="btn" id="autonomyTestConfirmNo" type="button">取消</button></div></div>
  <div class="setting-row"><div><b>阈值（0-1）</b><small>越高越难触发</small></div><input type="number" id="autonomyThresholdInput" min="0" max="1" step="0.05" value="0.55"></div>
  <div class="setting-row"><div><b>最大字数</b><small>20–4000</small></div><input type="number" id="autonomyMaxCharsInput" min="20" max="4000" step="10" value="120"></div>
  <div class="setting-row"><div><b>保存</b><small id="autonomySaveState">未修改</small></div><button class="btn" id="autonomySaveBtn" type="button">保存自主行为设置</button></div>
  <p class="api-note">仅在私聊路径生效；群聊不主动发消息。</p>
</div>`;
  function setupIntentTabs(){
    const bar=$('intentTabs'); if(!bar) return;
    const tabs=[...bar.querySelectorAll('.persona-tab')];
    const panels=[...document.querySelectorAll('#view-intent .intent-tabpanel')];
    if(!tabs.length) return;
    const activate=(name)=>{
      tabs.forEach(t=>t.classList.toggle('active',!!name&&t.dataset.intentTab===name));
      panels.forEach(p=>{
        const on=!!name&&p.dataset.intentTab===name;
        p.classList.toggle('active',on);
        p.style.display=on?'block':'none';   // hard guard: nesting/cache must not leak panels
      });
      const host=$("intentAutonomyHost");
      if(host){
        if(name==="autonomy"){
          if(!host.dataset.filled){ host.innerHTML=AUTONOMY_PANEL_HTML; host.dataset.filled="1"; }
          try{ bindAutonomy(); }catch(e){}
        }else if(host.dataset.filled){
          host.innerHTML=""; host.dataset.filled="";
        }
      }
    };
    activate(null); // default folded; click one tile to open
    tabs.forEach(t=>t.addEventListener('click',()=>{
      const name=t.dataset.intentTab||'hero';
      if(t.classList.contains('active')) activate(null); else activate(name);
    }));
  }
  const BIO_VERSION = "v1.4.1";
  setTimeout(() => { const _sv = $("sideVersion"); if (_sv) _sv.textContent = BIO_VERSION + " · tendency layer"; }, 0);
  setTimeout(() => { const _bs = $("buildStamp"); if (_bs) _bs.textContent = (window.__BIOCORE_BUILD__ || ""); }, 0);
  const BIO_REPO_SLUG = "Johnhmzm/astrbot_plugin_biocore";
  const GITEE_KEY = "bio_gitee_repo";
  let giteeRepo = String(storeGet(GITEE_KEY, "johnhim/astrbot_plugin_biocore") || "").trim();
  function applyGiteeRepo(){
    const input = $("giteeRepo"), state = $("giteeState"), link = $("updateOpenGitee");
    if (input) input.value = giteeRepo;
    if (state) state.textContent = giteeRepo ? ("已配置 " + giteeRepo) : "未配置";
    if (link) {
      link.style.display = giteeRepo ? "" : "none";
      if (giteeRepo) link.href = "https://gitee.com/" + giteeRepo;
    }
  }
  function _semverParts(v){
    return String(v || "").replace(/^v/i, "").split(/[.+-]/).slice(0, 3).map(n => parseInt(n, 10) || 0);
  }
  function _compareVer(a, b){
    const A = _semverParts(a), B = _semverParts(b);
    for (let i = 0; i < 3; i++) { if (A[i] !== B[i]) return A[i] > B[i] ? 1 : -1; }
    return 0;
  }
  async function checkBioUpdate(auto){
    const st = $("updateState");
    if (!st) return;
    const linkState = $("linkState");
    if (linkState && /预览|preview/i.test(String(linkState.textContent || ""))) {
      st.textContent = "预览模式不检查更新";
      return;
    }
    st.textContent = "检查中…";
    st.style.color = "";
    const sources = [];
    if (giteeRepo) sources.push("https://gitee.com/" + giteeRepo + "/raw/main/metadata.yaml");
    sources.push("https://api.github.com/repos/" + BIO_REPO_SLUG + "/contents/metadata.yaml");
    sources.push("https://cdn.jsdelivr.net/gh/" + BIO_REPO_SLUG + "@main/metadata.yaml");
    sources.push("https://raw.githubusercontent.com/" + BIO_REPO_SLUG + "/main/metadata.yaml");
    for (const url of sources) {
      try {
        const ctl = new AbortController();
        const timer = setTimeout(() => ctl.abort(), 8000);
        const res = await fetch(url, {
          cache: "no-store",
          signal: ctl.signal,
          headers: { Accept: url.indexOf("api.github.com") >= 0 ? "application/vnd.github.raw+json" : "text/plain" }
        });
        clearTimeout(timer);
        if (!res.ok) continue;
        const text = await res.text();
        const m = text.match(/^\s*version:\s*["']?([^"'\s]+)/m);
        if (!m) continue;
        const remote = m[1].trim();
        if (_compareVer(remote, BIO_VERSION) > 0) {
          st.textContent = "发现新版本 " + remote + "（当前 " + BIO_VERSION + "）";
          st.style.color = "var(--accent2)";
        } else {
          st.textContent = "已是最新（" + BIO_VERSION + "）";
          st.style.color = "";
        }
        return;
      } catch (e) { /* try next source */ }
    }
    st.textContent = auto ? "自动检查失败（网络不通，可点检查重试）" : "检查失败（网络不可达）";
    st.style.color = "var(--danger)";
  }
  const _updateBtn = $("updateCheckBtn");
  if (_updateBtn) _updateBtn.addEventListener("click", () => checkBioUpdate(false));
  const _giteeSave = $("giteeSaveBtn");
  if (_giteeSave) _giteeSave.addEventListener("click", () => {
    const input = $("giteeRepo");
    giteeRepo = String(input && input.value || "").trim().replace(/^https?:\/\/gitee\.com\//i, "").replace(/\/$/, "");
    storeSet(GITEE_KEY, giteeRepo);
    applyGiteeRepo();
    checkBioUpdate(false);
  });
  applyGiteeRepo();
  setTimeout(() => checkBioUpdate(true), 1500);
  setupSettingsTabs();
  setupPersonaTabs();
  setupSessionTabs();
  setupIntentTabs();
  setupFolds();
  arrangeFoldGrid();
  // task-45: memory-ball focus panel for the left CURRENT EMOTION area.
  // orb.js dispatches biocore:focus / biocore:focus-exit; we cache the original
  // hero content (children + display) and swap it for the selected memory,
  // restoring it exactly when focus ends.
  let _heroFocusSaved = null;
  const _FOCUS_SOURCE_LABELS = { ok: "正常", weak: "弱来源", suspect: "待核", unknown: "未知" };
  const _FOCUS_STATUS_LABELS = { llm: "AI 总结", fallback: "摘录总结", legacy: "旧事件", edited: "已编辑" };
  function _focusClip(value, limit){
    const text = String(value == null ? "" : value).replace(/\s+/g, " ").trim();
    const n = Math.max(1, Number(limit) || 80);
    return text.length > n ? text.slice(0, n - 1).trimEnd() + "…" : text;
  }
  function _focusStatusOf(detail){
    const s = String((detail && detail.summary_status) || "legacy").trim().toLowerCase();
    if (s === "llm" || s === "fallback" || s === "edited") return s;
    return "legacy";
  }
  function _heroCopyEl(){
    return document.querySelector("#view-overview .hero-copy") || document.querySelector(".hero-copy");
  }
  function _focusEmotionLabel(key){
    const k = String(key == null ? "" : key).trim();
    if (!k) return "—";
    try {
      if (typeof emotionLabel === "function") {
        const zh = emotionLabel(k);
        if (zh) return zh;
      }
    } catch (e) {}
    return L(k) || k;
  }
  function _focusWhen(ts){
    const n = Number(ts || 0);
    if (!(n > 0)) return "—";
    try {
      return new Date(n * 1000).toLocaleString("zh-CN",
        { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
    } catch (e) { return "—"; }
  }
  function _focusSourceLabel(status){
    const k = String(status || "ok").trim().toLowerCase();
    return _FOCUS_SOURCE_LABELS[k] || k || "—";
  }
  let _heroFocusDetail = null;
  function _heroPanelEl(){
    return (_heroFocusSaved && _heroFocusSaved.panel) || null;
  }
  function _focusEventId(detail){
    const d = detail || {};
    return String(d.event_id || d.key || "").trim();
  }
  // task-44: pinned-fact toggle for memory focus. page_status does not expose
  // entry.pinned yet, so keep a small local override cache; a backend value
  // (entry.pinned / detail.pinned) always wins when present. Display only.
  const _PIN_CACHE_KEY = "bio_mem_pin_cache";
  function _pinCache(){
    try {
      const raw = storeGet(_PIN_CACHE_KEY, "{}");
      const obj = JSON.parse(String(raw || "{}"));
      return (obj && typeof obj === "object") ? obj : {};
    } catch (e) { return {}; }
  }
  function _pinKey(session, id){ return String(session || "") + "|" + String(id || ""); }
  function _isPinned(session, id, pinnedField){
    if (pinnedField === true) return true;
    if (pinnedField === false) return false;
    const key = _pinKey(session, id);
    if (key === "|") return false;
    return _pinCache()[key] === true;
  }
  function _setPinned(session, id, value){
    try {
      const cache = _pinCache();
      cache[_pinKey(session, id)] = !!value;
      storeSet(_PIN_CACHE_KEY, JSON.stringify(cache));
    } catch (e) {}
  }
  function _pinSupported(detail){
    const d = detail || {};
    return d._kind === "memory" && !!String(d.id || "").trim() && !!String(d.session || "").trim();
  }
  function _focusShowMsg(text, isError){
    const panel = _heroPanelEl();
    const msg = panel && panel.querySelector("#heroMemMsg");
    if (!msg) return;
    msg.textContent = String(text || "");
    msg.hidden = !text;
    if (msg.classList && msg.classList.toggle) msg.classList.toggle("is-error", !!isError);
  }
  function _focusSetBusy(busy, label){
    const panel = _heroPanelEl();
    if (!panel) return;
    if (panel.querySelectorAll) {
      // task-49: loading must freeze and then restore both buttons and the
      // edit-mode textareas; a success path must never leave them disabled.
      panel.querySelectorAll("button, textarea").forEach((el) => { el.disabled = !!busy; });
    }
    if (busy) _focusShowMsg(label || "处理中…", false);
  }
  async function _focusApi(payload, path){
    if (!bridge || typeof bridge.apiPost !== "function") {
      throw new Error("预览模式无法保存，请从 AstrBot 插件视图打开");
    }
    const raw = path
      ? await bridge.apiPost(String(path), payload)
      : await bridge.apiPost("page/event_summary", payload);
    const body = raw && raw.data ? raw.data : raw;
    if (!body || body.status === "error" || body.status === "fail") {
      throw new Error((body && body.message) || "保存失败");
    }
    return body;
  }
  async function _focusFixApi(payload){
    return _focusApi(payload, "page/memory_point_feedback");
  }
  async function _focusTogglePin(){
    const d = _heroFocusDetail || {};
    if (!_pinSupported(d)) { _focusShowMsg("这条记忆不是可钉住的内存条目", true); return; }
    const session = String(d.session || "");
    const id = String(d.id || "");
    const next = !_isPinned(session, id, d.pinned);
    _focusSetBusy(true, next ? "钉住中…" : "取消钉住中…");
    let body = null, failure = null;
    try {
      body = await _focusApi({ pin: next },
        "page/memory/pin/" + encodeURIComponent(session) + "/" + encodeURIComponent(id));
    } catch (err) {
      failure = err;
    } finally {
      _focusSetBusy(false);
    }
    if (failure) { _focusShowMsg(String((failure && failure.message) || failure), true); return; }
    const applied = (body && body.pin != null) ? body.pin === true : next;
    _setPinned(session, id, applied);
    if (_heroFocusSaved && _heroFocusDetail) {
      _heroFocusDetail = Object.assign({}, _heroFocusDetail, { pinned: applied });
      _renderHeroMemoryRead();
      _focusShowMsg(applied ? "已钉住（固定事实，不参与容量淘汰）" : "已取消钉住", false);
    }
    await _focusReloadData();
    if (_heroFocusSaved && _heroFocusDetail) {
      _heroFocusDetail = Object.assign({}, _heroFocusDetail, { pinned: applied });
      _renderHeroMemoryRead();
      _focusShowMsg(applied ? "已钉住" : "已取消钉住", false);
    }
  }
  // task-33: merge a feedback API row into the open focus detail.
  function _focusApplyFeedbackResult(data){
    if (!_heroFocusSaved || !_heroFocusDetail) return;
    const body = data || {};
    const d = _heroFocusDetail || {};
    _heroFocusDetail = Object.assign({}, d, {
      title: body.title == null ? String(d.title || "") : String(body.title),
      small_summary: body.small_summary == null ? String(d.small_summary || "") : String(body.small_summary),
      importance: body.importance == null ? Number(d.importance == null ? .5 : d.importance) : Number(body.importance),
      user_marked: body.user_marked == null ? !!d.user_marked : body.user_marked === true,
      memory_point: body.memory_point == null ? (d.memory_point !== false) : body.memory_point !== false,
      downgraded_by_reevaluate: body.downgraded_by_reevaluate != null
        ? body.downgraded_by_reevaluate === true
        : ((body.memory_point === true) ? false : !!d.downgraded_by_reevaluate),
      reevaluate_verdict: (body.reevaluate_verdict && typeof body.reevaluate_verdict === "object")
        ? body.reevaluate_verdict : (d.reevaluate_verdict || null),
      label_edited: body.label_edited == null ? !!d.label_edited : body.label_edited === true,
      worthiness: (body.worthiness && typeof body.worthiness === "object")
        ? body.worthiness : (d.worthiness || null)
    });
  }
  async function _focusFeedback(action, extra){
    const d = _heroFocusDetail || {};
    const eventId = _focusEventId(d);
    if (!eventId) { _focusShowMsg("这条记忆没有可反馈的事件 id", true); return; }
    _focusSetBusy(true, "提交中…");
    let result = null, failure = null;
    try {
      result = await _focusFixApi(Object.assign({ event_id: eventId, action: action }, extra || {}));
    } catch (err) {
      failure = err;
    } finally {
      _focusSetBusy(false);
    }
    if (failure) { _focusShowMsg(String((failure && failure.message) || failure), true); return; }
    if (!result) return;
    const okText = action === "restore" ? "已恢复"
      : (action === "unimportant" ? "已标记不重要"
      : (action === "important" ? "已标记重要" : "已更新"));
    _focusApplyFeedbackResult(result);
    _renderHeroMemoryRead();
    _focusShowMsg(okText, false);
    await _focusReloadData();
    if (_heroFocusSaved && _heroFocusDetail) {
      _focusApplyFeedbackResult(result);
      const latest = _focusLatestDetail(_focusEventId(_heroFocusDetail));
      if (latest) _heroFocusDetail = Object.assign({}, _heroFocusDetail, latest);
      _renderHeroMemoryRead();
      _focusShowMsg(okText, false);
    }
  }
  function _focusNum2(value){
    return Number.isFinite(Number(value)) ? Number(value).toFixed(2) : "—";
  }
  // task-34: deterministic re-evaluation by W/W_her/K; shows verdict + numbers.
  async function _focusReevaluate(){
    const d = _heroFocusDetail || {};
    const eventId = _focusEventId(d);
    if (!eventId) { _focusShowMsg("这条记忆没有可重判的事件 id", true); return; }
    _focusSetBusy(true, "重新判定中…");
    let result = null, failure = null;
    try {
      result = await _focusFixApi({ event_id: eventId, action: "reevaluate" });
    } catch (err) {
      failure = err;
    } finally {
      _focusSetBusy(false);
    }
    if (failure) { _focusShowMsg(String((failure && failure.message) || failure), true); return; }
    if (!result) return;
    const verdict = (result && result.verdict) || {};
    const rec = (result && result.record) || {};
    let label = verdict.decision === "memory_point" ? "仍是记忆点"
      : (verdict.decision === "archive_only" ? "已降级为归档" : "不是记忆点");
    if (verdict.decision === "insufficient_data") label = "证据不足，未修改";
    else if (verdict.decision === "retained_protected") label = "关系/自我相关，已保留";
    const detail = " · W " + _focusNum2(verdict.W) + " · W_her " +
      _focusNum2(verdict.W_her) + " · K " + _focusNum2(verdict.K);
    _focusApplyFeedbackResult(rec);
    _renderHeroMemoryRead();
    const _reevalMsg = String((result && result.message) || "");
    _focusShowMsg((_reevalMsg || label) + detail, false);
    await _focusReloadData();
    if (_heroFocusSaved && _heroFocusDetail) {
      _focusApplyFeedbackResult(rec);
      const latest = _focusLatestDetail(_focusEventId(_heroFocusDetail));
      if (latest) _heroFocusDetail = Object.assign({}, _heroFocusDetail, latest);
      _renderHeroMemoryRead();
      _focusShowMsg(label + detail, false);
    }
  }
  function _focusApplyApiResult(data){
    // If the user already left focus while the request was in flight, drop the
    // stale result instead of resurrecting a closed panel.
    if (!_heroFocusSaved || !_heroFocusDetail) return;
    const body = data || {};
    const d = _heroFocusDetail || {};
    _heroFocusDetail = Object.assign({}, d, {
      title: body.title == null ? String(d.title || "") : String(body.title),
      big_summary: body.big_summary == null ? String(d.big_summary || "") : String(body.big_summary),
      small_summary: body.small_summary == null ? String(d.small_summary || "") : String(body.small_summary),
      summary_status: String(body.summary_status || d.summary_status || "edited"),
      summary_edited: body.summary_edited === true,
      summary_updated_ts: Number(body.summary_updated_ts || 0),
      summary_history: Array.isArray(body.summary_history)
        ? body.summary_history
        : (Array.isArray(d.summary_history) ? d.summary_history : []),
      emotion_nuance: Array.isArray(body.emotion_nuance)
        ? body.emotion_nuance
        : (Array.isArray(d.emotion_nuance) ? d.emotion_nuance : []),
      importance: body.importance == null ? Number(d.importance == null ? .5 : d.importance) : Number(body.importance),
      user_marked: body.user_marked == null ? !!d.user_marked : body.user_marked === true,
      memory_point: body.memory_point == null ? (d.memory_point !== false) : body.memory_point !== false,
      downgraded_by_reevaluate: body.downgraded_by_reevaluate != null
        ? body.downgraded_by_reevaluate === true
        : ((body.memory_point === true) ? false : !!d.downgraded_by_reevaluate),
      reevaluate_verdict: (body.reevaluate_verdict && typeof body.reevaluate_verdict === "object")
        ? body.reevaluate_verdict : (d.reevaluate_verdict || null),
      label_edited: body.label_edited == null ? !!d.label_edited : body.label_edited === true,
      worthiness: (body.worthiness && typeof body.worthiness === "object")
        ? body.worthiness : (d.worthiness || null)
    });
  }
  async function _focusReloadData(){
    if (!bridge || typeof load !== "function") return;
    try { await load(); } catch (e) { /* the panel already shows the saved text */ }
  }
  // task-49: after load() the archive may already expose the new summary.
  // Prefer that fresh event row (title/summary/status/ts) for the open panel,
  // so exit/re-focus and page refresh show the persisted values.
  function _focusLatestDetail(eventId){
    if (!eventId) return null;
    try {
      const evs = (data && Array.isArray(data.events)) ? data.events : [];
      for (const ev of evs) {
        if (!ev || typeof ev !== "object") continue;
        if (String(ev.id || "") !== String(eventId)) continue;
        return {
          title: String(ev.title || ""),
          big_summary: String(ev.big_summary || ""),
          small_summary: String(ev.small_summary || ""),
          summary_status: String(ev.summary_status || "legacy"),
          summary_edited: ev.summary_edited === true,
          summary_updated_ts: Number(ev.summary_updated_ts || 0),
          summary_history: Array.isArray(ev.summary_history) ? ev.summary_history : [],
          emotion_nuance: Array.isArray(ev.emotion_nuance) ? ev.emotion_nuance : [],
          event: String(ev.event || ""),
          central_details: String(ev.central_details || ""),
          importance: Number(ev.importance == null ? .5 : ev.importance),
          user_marked: ev.user_marked === true,
          memory_point: ev.memory_point !== false,
          downgraded_by_reevaluate: ev.downgraded_by_reevaluate === true,
          reevaluate_verdict: (ev.reevaluate_verdict && typeof ev.reevaluate_verdict === "object")
            ? ev.reevaluate_verdict : null,
          label_edited: ev.label_edited === true,
          worthiness: (ev.worthiness && typeof ev.worthiness === "object") ? ev.worthiness : null
        };
      }
    } catch (e) { /* keep the API result as the fallback */ }
    return null;
  }
  async function _focusRegenerate(){
    const d = _heroFocusDetail || {};
    const eventId = _focusEventId(d);
    if (!eventId) { _focusShowMsg("这条记忆没有可重总结的事件 id", true); return; }
    _focusSetBusy(true, "重新总结中…");
    let result = null, failure = null;
    try {
      result = await _focusApi({ event_id: eventId, action: "regenerate" });
    } catch (err) {
      failure = err;
    } finally {
      // task-49: success AND failure must clear the loading state. The panel may
      // have been re-rendered meanwhile, so this always targets the live panel.
      _focusSetBusy(false);
    }
    if (failure) {
      _focusShowMsg(String((failure && failure.message) || failure), true);
      return;
    }
    if (!result) return;
    _focusApplyApiResult(result);
    _renderHeroMemoryRead();
    _focusShowMsg("已重新总结", false);
    await _focusReloadData();
    // load() may have reset/refreshed the focus detail: re-apply the API result,
    // prefer the freshly loaded archive row, then re-render so status /
    // updated_ts / edited stay visible and buttons stay enabled.
    if (_heroFocusSaved && _heroFocusDetail) {
      _focusApplyApiResult(result);
      const latest = _focusLatestDetail(_focusEventId(_heroFocusDetail));
      if (latest) _heroFocusDetail = Object.assign({}, _heroFocusDetail, latest);
      _renderHeroMemoryRead();
      _focusShowMsg("已重新总结", false);
    }
  }
  async function _focusSaveEdit(){
    const panel = _heroPanelEl();
    const d = _heroFocusDetail || {};
    const eventId = _focusEventId(d);
    const titleEl = panel && panel.querySelector("#heroMemTitleInput");
    const smallEl = panel && panel.querySelector("#heroMemSmall");
    const bigEl = panel && panel.querySelector("#heroMemBig");
    const title = titleEl ? String(titleEl.value || "").trim() : "";
    const big = bigEl ? String(bigEl.value || "").trim() : "";
    const small = smallEl ? String(smallEl.value || "").trim() : "";
    if (!eventId) { _focusShowMsg("这条记忆没有可编辑的事件 id", true); return; }
    if (titleEl && !title) { _focusShowMsg("标题不能为空", true); return; }
    if (title.length > 80) { _focusShowMsg("标题不能超过 80 字", true); return; }
    if (!big) { _focusShowMsg("大总结不能为空", true); return; }
    if (small.length > 80) { _focusShowMsg("小总结不能超过 80 字", true); return; }
    _focusSetBusy(true, "保存中…");
    let result = null, failure = null;
    try {
      const _payload = { event_id: eventId, action: "update",
                         big_summary: big, small_summary: small };
      if (titleEl) _payload.title = title;
      result = await _focusApi(_payload);
    } catch (err) {
      failure = err;
    } finally {
      // task-49: clear loading on both paths; failure keeps the edit form usable
      // (textareas + 保存/取消 re-enabled).
      _focusSetBusy(false);
    }
    if (failure) {
      _focusShowMsg(String((failure && failure.message) || failure), true);
      return;
    }
    if (!result) return;
    _focusApplyApiResult(result);
    _renderHeroMemoryRead();
    _focusShowMsg("已保存", false);
    await _focusReloadData();
    if (_heroFocusSaved && _heroFocusDetail) {
      _focusApplyApiResult(result);
      const latest = _focusLatestDetail(_focusEventId(_heroFocusDetail));
      if (latest) _heroFocusDetail = Object.assign({}, _heroFocusDetail, latest);
      _renderHeroMemoryRead();
      _focusShowMsg("已保存", false);
    }
  }
  function _focusWorthinessHtml(d){
    const w = d && d.worthiness;
    if (!w || typeof w !== "object") return "";
    const num = (v) => (Number.isFinite(Number(v)) ? Number(v).toFixed(2) : "—");
    const decision = String(w.decision || "");
    const label = decision === "memory_point" ? "生成记忆点"
      : (decision === "archive_only" ? "只归档"
      : (decision === "skip" ? "不生成" : ""));
    const reason = String(w.reason || "");
    return '<details class="hero-mem-worth"><summary>判定 W ' + num(w.W) +
      ' · W_her ' + num(w.W_her) + ' · K ' + num(w.K) + '</summary>' +
      '<p class="hero-mem-worth-parts">I ' + num(w.I) + ' · S ' + num(w.S) +
      ' · C ' + num(w.C) + ' · G ' + num(w.G) + ' · PE ' + num(w.PE) +
      ' · R ' + num(w.R) + ' · P ' + num(w.P) + ' · N ' + num(w.N) +
      (label ? ' · ' + label : '') + (reason ? '（' + reason + '）' : '') +
      '</p></details>';
  }
  function _renderHeroMemoryFixEdit(){
    const panel = _heroPanelEl();
    const d = _heroFocusDetail || {};
    if (!panel) return;
    panel.innerHTML =
      '<div class="eyebrow">MEMORY FOCUS · 修正记忆点 · 编辑标签</div>' +
      '<label class="hero-mem-field"><small>标签（标题，≤80 字）</small>' +
      '<input id="heroMemFixTitle" type="text" maxlength="80" value="' +
      esc(String(d.title || "").slice(0, 80)) + '"></label>' +
      '<label class="hero-mem-field"><small>小标签（≤80 字，可留空）</small>' +
      '<textarea id="heroMemFixSmall" maxlength="80" rows="2">' +
      esc(String(d.small_summary || "").slice(0, 80)) + '</textarea></label>' +
      '<div class="hero-mem-actions">' +
        '<button type="button" class="btn mini" id="heroMemFixSave">保存</button>' +
        '<button type="button" class="btn mini" id="heroMemFixCancel">取消</button>' +
      '</div>' +
      '<p class="hero-mem-msg" id="heroMemMsg" hidden></p>';
    const save = panel.querySelector("#heroMemFixSave");
    const cancel = panel.querySelector("#heroMemFixCancel");
    if (save) save.addEventListener("click", () => { _focusSaveLabel(); });
    if (cancel) cancel.addEventListener("click", () => { _renderHeroMemoryRead(); });
  }
  function _focusSaveLabel(){
    const panel = _heroPanelEl();
    if (!panel) return;
    const titleEl = panel.querySelector("#heroMemFixTitle");
    const smallEl = panel.querySelector("#heroMemFixSmall");
    const title = titleEl ? String(titleEl.value || "").trim() : "";
    const small = smallEl ? String(smallEl.value || "").trim() : "";
    if (!title && !small) { _focusShowMsg("至少填写标签或小标签", true); return; }
    if (title.length > 80) { _focusShowMsg("标签不能超过 80 字", true); return; }
    if (small.length > 80) { _focusShowMsg("小标签不能超过 80 字", true); return; }
    _focusFeedback("edit_label", { title: title, small_summary: small });
  }
  function _renderHeroMemoryEdit(){
    const panel = _heroPanelEl();
    const d = _heroFocusDetail || {};
    if (!panel) return;
    const big = _focusSummarySource(d);
    const smallSrc = String(d.small_summary || "").trim() ||
      (d.event ? String(d.event) : "");
    const small = _focusClip(smallSrc, 80);
    panel.innerHTML =
      '<div class="eyebrow">MEMORY FOCUS · 编辑总结</div>' +
      '<div class="hero-mem-edit">' +
        '<label class="hero-mem-field"><small>标题（≤80 字）</small>' +
        '<input id="heroMemTitleInput" type="text" maxlength="80" value="' +
        esc(String(d.title || "记忆球").slice(0, 80)) + '"></label>' +
        '<label class="hero-mem-field"><small>小总结（≤80 字）</small>' +
        '<textarea id="heroMemSmall" maxlength="80" rows="2">' + esc(small) + '</textarea></label>' +
        '<label class="hero-mem-field"><small>大总结</small>' +
        '<textarea id="heroMemBig" rows="6">' + esc(big) + '</textarea></label>' +
      '</div>' +
      '<div class="hero-mem-actions">' +
        '<button type="button" class="btn mini" id="heroMemSave">保存</button>' +
        '<button type="button" class="btn mini" id="heroMemCancel">取消</button>' +
      '</div>' +
      '<p class="hero-mem-msg" id="heroMemMsg" hidden></p>';
    const save = panel.querySelector("#heroMemSave");
    const cancel = panel.querySelector("#heroMemCancel");
    if (save) save.addEventListener("click", () => { _focusSaveEdit(); });
    if (cancel) cancel.addEventListener("click", () => { _renderHeroMemoryRead(); });
  }
  function _focusSummarySource(d){
    const status = _focusStatusOf(d);
    const raw = String(d.big_summary || d.event || d.central_details || "").trim();
    if (status === "legacy") return _focusClip(raw, 200);
    return raw;
  }
  function _renderHeroMemoryRead(){
    const panel = _heroPanelEl();
    const d = _heroFocusDetail || {};
    if (!panel) return;
    const primary = _focusEmotionLabel(d.emotion);
    // task-54 addendum: old event without a real secondary shows an inferred
    // (示意) secondary; it never pretends to be a genuine secondary emotion.
    const secondary = d.emotion_secondary
      ? _focusEmotionLabel(d.emotion_secondary) : "推断（示意）";
    const importance = Number(d.importance == null ? .5 : d.importance).toFixed(2);
    const when = _focusWhen(d.ts);
    const source = _focusSourceLabel(d.source);
    const recall = Math.max(0, Number(d.recall_count || 0));
    const status = _focusStatusOf(d);
    const edited = d.summary_edited === true || status === "edited";
    const badge = edited ? "已编辑" : (_FOCUS_STATUS_LABELS[status] || "旧事件");
    const badgeClass = edited ? "is-edited" : ("is-" + status);
    const title = _focusClip(d.title || "记忆球", 80);
    const updated = Number(d.summary_updated_ts || 0) > 0 ? _focusWhen(d.summary_updated_ts) : "";
    // Harness-friendly: focus-panel evals extract this renderer without the
    // top-level label helpers, so tolerate their absence (no-op there).
    let nuanceLine = "";
    try {
      if (typeof _emotionNuanceOf === "function" && typeof _emotionNuanceLine === "function") {
        nuanceLine = _emotionNuanceLine(primary, secondary, _emotionNuanceOf(d));
      }
    } catch (e) { nuanceLine = ""; }
    const nuanceHtml = nuanceLine
      ? '<div class="hero-mem-summary hero-mem-nuance"><small>情绪层次</small><p>' +
        esc(nuanceLine) + '</p></div>' : "";
    let summaries = "";
    if (status === "legacy" && !edited) {
      // task-46: old records may store the raw event text in big_summary; never
      // render it as a summary. Show a fixed notice + a <=200 char excerpt only.
      const excerpt = _focusClip(_focusSummarySource(d), 200);
      summaries =
        '<div class="hero-mem-legacy">旧事件：未生成总结</div>' +
        '<div class="hero-mem-summary"><small>原始摘录</small><p class="hero-mem-excerpt">' +
        esc(excerpt || "—") + '</p></div>';
    } else {
      const smallSrc = String(d.small_summary || "").trim() ||
        (d.event ? String(d.event) : "");
      const small = _focusClip(smallSrc, 80);
      const big = String(d.big_summary || d.event || d.central_details || "").trim();
      summaries =
        '<div class="hero-mem-summary"><small>小总结</small><p>' +
        esc(small || "—") + '</p></div>' +
        '<div class="hero-mem-summary hero-mem-big"><small>大总结</small><p>' +
        esc(big || "—") + '</p></div>';
    }
    // task-49 addendum: keep previous summaries, collapsed by default.
    const history = Array.isArray(d.summary_history) ? d.summary_history : [];
    let historyHtml = "";
    if (history.length) {
      const items = history.slice(0, 20).map((entry) => {
        const h = entry || {};
        const hStatus = _focusStatusOf(h);
        const hLabel = _FOCUS_STATUS_LABELS[hStatus] || String(h.summary_status || "");
        const hWhen = _focusWhen(h.ts);
        const hSmall = _focusClip(String(h.small_summary || ""), 80);
        // full history text; only legacy raw events stay a 200-char excerpt.
        const hBigRaw = String(h.big_summary || "");
        const hBig = hStatus === "legacy" ? _focusClip(hBigRaw, 200) : hBigRaw;
        return '<div class="hero-mem-history-item">' +
          '<div class="hero-mem-history-meta"><b>' + esc(hWhen || "—") + '</b>' +
          '<span>' + esc(hLabel || "历史") + '</span>' +
          (h.source ? '<i>' + esc(String(h.source)) + '</i>' : '') + '</div>' +
          (hSmall ? '<p class="hero-mem-history-small">' + esc(hSmall) + '</p>' : '') +
          (hBig ? '<p class="hero-mem-history-big">' + esc(hBig) + '</p>' : '') +
          '</div>';
      }).join("");
      historyHtml =
        '<details class="hero-mem-history"><summary>历史总结（' + history.length +
        '）</summary><div class="hero-mem-history-list">' + items + '</div></details>';
    }
    // task-33: user feedback marker + collapsed worthiness (W/W_her/K).
    const marked = d.user_marked === true;
    const markedHtml = marked ? '<span class="hero-mem-badge is-marked">已修正</span>' : "";
    const worthHtml = _focusWorthinessHtml(d);
    // task-44: pin toggle only for memory-entry balls (events have no pin API).
    const pinOk = _pinSupported(d);
    const pinned = pinOk ? _isPinned(d.session, d.id, d.pinned) : false;
    const pinHtml = pinOk
      ? '<button type="button" class="btn mini' + (pinned ? ' is-pinned' : '') +
        '" id="heroMemPin" aria-pressed="' + (pinned ? 'true' : 'false') +
        '" title="钉住后这条事实不会被容量淘汰">' + (pinned ? '取消钉住' : '钉住') + '</button>'
      : "";
    // task-45: a point downgraded by 重新判定 must expose 「恢复」 in the action
    // row (the same action that used to be buried in the 修正记忆点 menu).
    // Guarded like the nuance helper: the focus-panel evals extract this
    // renderer without the whole file, so keep the predicate optional there.
    let downgraded = false;
    try { downgraded = (typeof _isDowngraded === "function") ? _isDowngraded(d) : false; }
    catch (e) { downgraded = false; }
    const downgradedHtml = downgraded
      ? '<span class="hero-mem-badge is-downgraded">已降级</span>' : "";
    const restoreHtml = downgraded
      ? '<button type="button" class="btn mini is-restore" id="heroMemRestore"' +
        ' title="把这条记忆点从归档恢复为记忆点（撤销重新判定降级）">恢复</button>'
      : "";
    panel.innerHTML =
      '<div class="eyebrow">MEMORY FOCUS · 记忆聚焦</div>' +
      '<div class="hero-mem-head"><h2 id="heroMemTitle">' + esc(title) + '</h2>' +
      '<span class="hero-mem-badge ' + badgeClass + '">' + esc(badge) + '</span>' +
      markedHtml + downgradedHtml + '</div>' +
      '<div class="hero-mem-grid">' +
        '<span>主情绪 <b>' + esc(primary) + '</b></span>' +
        '<span>次情绪 <b>' + esc(secondary) + '</b></span>' +
        '<span>重要度 <b>' + esc(importance) + '</b></span>' +
        '<span>时间 <b>' + esc(when) + '</b></span>' +
        '<span>来源 <b>' + esc(source) + '</b></span>' +
        '<span>召回 <b>' + esc(String(recall)) + ' 次</b></span>' +
      '</div>' + worthHtml + nuanceHtml + summaries + historyHtml +
      '<div class="hero-mem-actions hero-mem-actions-fix">' +
        '<button type="button" class="btn mini" id="heroMemRegen">重新总结</button>' +
        '<button type="button" class="btn mini" id="heroMemReeval">重新判定</button>' +
        '<button type="button" class="btn mini" id="heroMemEdit">编辑总结</button>' +
        pinHtml +
        restoreHtml +
        '<span class="hero-mem-fixwrap">' +
          '<button type="button" class="btn mini" id="heroMemFix">修正记忆点</button>' +
          '<span class="hero-mem-fixmenu" id="heroMemFixMenu" hidden>' +
            '<button type="button" class="btn mini" data-fix="important">标记重要</button>' +
            '<button type="button" class="btn mini" data-fix="unimportant">标记不重要</button>' +
            '<button type="button" class="btn mini" data-fix="edit_label">编辑标签</button>' +
            '<button type="button" class="btn mini" data-fix="restore">恢复</button>' +
          '</span>' +
        '</span>' +
      '</div>' +
      '<p class="hero-mem-msg" id="heroMemMsg" hidden></p>' +
      (updated ? '<p class="hero-mem-updated">更新于 ' + esc(updated) + '</p>' : '') +
      '<p class="hero-mem-hint">再次点击记忆球 / 点空白 / Esc / “退出聚焦”恢复当前情绪</p>';
    const regen = panel.querySelector("#heroMemRegen");
    const reeval = panel.querySelector("#heroMemReeval");
    const edit = panel.querySelector("#heroMemEdit");
    if (regen) regen.addEventListener("click", () => { _focusRegenerate(); });
    if (reeval) reeval.addEventListener("click", () => { _focusReevaluate(); });
    if (edit) edit.addEventListener("click", () => { _renderHeroMemoryEdit(); });
    const pin = panel.querySelector("#heroMemPin");
    if (pin) pin.addEventListener("click", () => { _focusTogglePin(); });
    const restoreBtn = panel.querySelector("#heroMemRestore");
    if (restoreBtn) restoreBtn.addEventListener("click", () => { _focusFeedback("restore"); });
    const fix = panel.querySelector("#heroMemFix");
    const fixMenu = panel.querySelector("#heroMemFixMenu");
    if (fix && fixMenu) {
      fix.addEventListener("click", (e) => {
        if (e && e.stopPropagation) e.stopPropagation();
        fixMenu.hidden = !fixMenu.hidden;
      });
    }
    if (fixMenu) {
      fixMenu.addEventListener("click", (e) => {
        const btn = (e && e.target && e.target.closest) ? e.target.closest("[data-fix]") : null;
        if (!btn) return;
        const action = String(btn.getAttribute("data-fix") || "");
        if (action === "edit_label") { _renderHeroMemoryFixEdit(); return; }
        _focusFeedback(action);
      });
    }
  }
  function showHeroMemoryPanel(detail){
    const copy = _heroCopyEl();
    if (!copy) return;
    if (!_heroFocusSaved){
      const hero = document.querySelector("#view-overview .hero") ||
        document.querySelector(".hero");
      _heroFocusSaved = {
        copy: copy,
        heroEl: hero,
        children: Array.prototype.slice.call(copy.children).map(
          (el) => ({ el: el, display: el.style.display || "" })),
        panel: null
      };
      if (hero && hero.classList) hero.classList.add("hero-focus");
      _heroFocusSaved.children.forEach((x) => { x.el.style.display = "none"; });
      const panel = document.createElement("div");
      panel.id = "heroMemoryPanel";
      panel.className = "hero-memory";
      copy.appendChild(panel);
      _heroFocusSaved.panel = panel;
    }
    _heroFocusDetail = Object.assign({}, detail || {});
    _renderHeroMemoryRead();
  }
  function restoreHeroFocusPanel(){
    const saved = _heroFocusSaved;
    if (!saved) return;
    try {
      if (saved.panel && saved.panel.parentNode) saved.panel.parentNode.removeChild(saved.panel);
    } catch (e) {}
    (saved.children || []).forEach((x) => {
      try { x.el.style.display = x.display; } catch (e) {}
    });
    try {
      if (saved.heroEl && saved.heroEl.classList) {
        saved.heroEl.classList.remove("hero-focus");
      }
    } catch (e) {}
    _heroFocusSaved = null;
    _heroFocusDetail = null;
  }
  document.addEventListener("biocore:open-archive", () => {
    try { switchView("sessions"); } catch (e) {}
  });
  document.addEventListener("biocore:focus", (e) => {
    showHeroMemoryPanel(e && e.detail);
  });
  document.addEventListener("biocore:focus-exit", () => {
    restoreHeroFocusPanel();
  });

  const _boot = () => {
    try {
      try{ window.__diagLog && window.__diagLog("init:1 dom-ready"); }catch(_e){}
      setTimeout(()=>{ try{ const el=$("topStatus"); if(el&&String(el.textContent||"").indexOf("连接中")>=0){ el.textContent="超时：load 未执行"; if(window.console&&window.console.warn) window.console.warn("[biocore] load did not start"); } }catch(_){} },8000);
      _initStep("setupSettingsTabs", setupSettingsTabs);
      _initStep("setupPersonaTabs", setupPersonaTabs);
      _initStep("setupSessionTabs", setupSessionTabs);
      _initStep("setupFeatureSwitches", setupFeatureSwitches);
      _initStep("bindCompressSave", bindCompressSave);
      _initStep("setupLlmConsolidation", setupLlmConsolidation);
      try{ window.__diagLog && window.__diagLog("init:3 before load"); }catch(_e){}
      const _p = load();
      try{ window.__diagLog && window.__diagLog("init:3 load called"); }catch(_e){}
      _p.then(() => { try{ window.__diagLog && window.__diagLog("init:4 after first load"); window.__diagHide && window.__diagHide(); }catch(_e){} safeRender("inlineNotices", renderInlineNotices); safeRender("safetyWarn", renderSafetyWarn); safeRender("envChecks", renderEnvChecks); safeRender("personaCompile", setupPersonaCompile); safeRender("autonomy", bindAutonomy); safeRender("replyLimit", renderReplyLimit); safeRender("replySoft", renderReplySoft); safeRender("replySplit", renderReplySplit); _initStep("setupSwitchGroups", setupSwitchGroups); }).catch((err) => {
        const el=$("topStatus");
        if(el) el.textContent="连接失败："+String(err&&err.message||err||"未知错误");
      });
    }
    catch (e) {
      const el=$("topStatus");
      if(el) el.textContent="初始化失败（见右下）";
      showDiag("init: "+String(e&&e.message||e));
      try { load(); } catch (e2) { showDiag("init-load: "+String(e2&&e2.message||e2)); }
    }
  };
  try { if (document.readyState === 'complete') _boot(); else window.addEventListener('load', _boot); }
  catch (e) { try { const el=$("topStatus"); if(el) el.textContent="初始化失败（见右下）"; } catch(_){} showDiag("init: "+String(e&&e.message||e)); }
})();
