(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  let bridge = null;
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
      goals:[{key:"relationship",name:"和重要的人保持亲近",horizon:"long",progress:.5}], goal_conflict:[], autobiography:[{ts:1793001000,title:"对方的承诺",meaning:"确认自己没有被当成工具"}], regulation_stats:{} },
      intent:{emotion:"joy",intensity:"high",need:"share",intent:"approach",expression:"open",plan:"顺着分享接话",compound:"亲近",regulation:"none",spectrum:[{key:"joy",name:"快乐",distance:.18}]} }],
    events:[
      {title:"对方的承诺", event:"对方说以后会先询问意愿，并记得说过的话。", event_key:"对方-承诺-先询问", session:"demo:session", ts:1793000600, time_span:{start_ts:1793000000,end_ts:1793000900}, importance:.86, centrality:.82, central_details:"对方主动承诺先询问意愿，而不是替自己做决定。", peripheral_details:"当时是在走廊里说的。", peripheral_retention:.18, peripheral_forgotten:false, meaning_to_her:"确认自己没有被当成工具。", reflection:"被认真问一句就足够安心。", confidence:.93, modalities:["语音"], source_check:{status:"ok"}},
      {title:"未说出口的担心", event:"在出发前犹豫了一下，还是把担心咽了回去。", event_key:"自己-犹豫-咽下担心", session:"demo:session", ts:1793001500, time_span:{start_ts:1793001400,end_ts:1793001800}, importance:.63, centrality:.55, central_details:"没有说出口的担心。", peripheral_details:"", peripheral_retention:.05, peripheral_forgotten:true, meaning_to_her:"不想让对方担心。", reflection:"习惯把难受藏起来。", confidence:.81, modalities:[], source_check:{status:"ok"}},
      {title:"走廊里的小烟花", event:"和同伴在走廊里放了一支小烟花。", event_key:"同伴-烟花-放松", session:"demo:session", ts:1793002100, time_span:{start_ts:1793001900,end_ts:1793002200}, importance:.66, centrality:.48, central_details:"难得的放松。", peripheral_details:"烟花是蓝色的。", peripheral_retention:.52, peripheral_forgotten:false, meaning_to_her:"普通日子也值得庆祝。", reflection:"快乐要分给身边的人。", confidence:.7, modalities:["图片"], source_check:{status:"weak"}}
    ],
    insights:[{insight:"被认真询问意愿，会更愿意承担任务。"}],
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
         destination_map:{"demo-user":{sender_id:"demo-user",sender_name:"重要的人",count:3,last_ts:1793002100,latest_text:"对方说以后会先询问意愿。"}}
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
  const map={neutral:"平静",joy:"开心",sadness:"难过",fear:"害怕",anger:"生气",surprise:"惊讶",trust:"信任",loneliness:"孤独",approach:"靠近",hold:"停住",withdraw:"退开",far:"远",near:"近",soft:"轻",blunt:"直",playful:"俏皮",quiet:"安静",short:"短",normal:"正常",open:"展开",low:"低",high:"高",calm:"松",tense:"紧",overloaded:"过载",be_heard:"被听见",space:"空间",vent:"吐槽",share:"分享",talk:"说话"};
  const L=(v)=>map[v]||v||"—";
  const clamp=(v)=>Math.max(0,Math.min(1,Number(v)||0));
  const pct=(v)=>Math.round(clamp(v)*100)+"%";
  const fmt=(v,d=2)=>(Number(v)>=0?"+":"")+Number(v||0).toFixed(d);
  const esc=(s)=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const shortSession=(v)=>{const t=String(v||"");return t.length>36?t.slice(0,33)+"…":t;};
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
  const visual={noise:storeGet("bio_show_noise","1")!=="0",echo:storeGet("bio_show_echo","1")!=="0",ripple:storeGet("bio_show_ripple","1")!=="0",dominance:storeGet("bio_show_dominance","1")!=="0",social:storeGet("bio_show_social","1")!=="0",links:storeGet("bio_show_links","1")!=="0",nodes:storeGet("bio_show_nodes","0")!=="0",nodeLinks:storeGet("bio_show_node_links","0")!=="0",memoryNodes:storeGet("bio_show_memory_nodes","1")!=="0",memoryBallsImportant:storeGet("bio_show_memory_balls_important","1")!=="0",emotionRings:storeGet("bio_show_emotion_rings","1")!=="0",intensity:Number(storeGet("bio_intensity","65"))};
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
        $("linkState").textContent="已连接"; $("topStatus").textContent="已连接";
        $("statusDot").style.background="var(--green)";
      }else{
        if(!themeInitialized) chooseTheme(false);
        data=demo;
        $("linkState").textContent="预览"; $("topStatus").textContent="预览";
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
      $("linkState").textContent="离线"; $("topStatus").textContent="离线";
      $("statusDot").style.background="var(--red)";
      $("heroTitle").textContent="连接不上 BioCore";
      $("heroSub").textContent = _friendly + (_friendly === _raw ? "" : "（原始：" + _raw.slice(0, 120) + "）");
      checkOrbAlive();
    }
    $("footTime").textContent=new Date().toLocaleTimeString();
    timer=setTimeout(load,5000);
  }

  let summarySessionFilter = "";
  function _coreSnapshot(key){
    const cores=(data&&data.cores)||[];
    const core=cores.find(c=>String(c.key)===String(key));
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
  function renderSessionMemory(){
    if(!data) return;
    const all=Array.isArray(data.events)?data.events:[];
    const sessions=Array.from(new Set(all.map(ev=>String(ev.session||"").trim()).filter(Boolean)));
    const sel=$("summarySession"), empty=$("summaryEmpty"), block=$("sessionSummaryBlock"), hint=$("summaryHint");
    if(!sessions.length){
      if(sel){sel.innerHTML='<option value="">暂无已总结会话</option>';sel.disabled=true;}
      if(empty) empty.style.display="block";
      if(block) block.innerHTML="";
      if(hint) hint.textContent="还没有已总结的会话";
      return;
    }
    if(sel){
      sel.disabled=false;
      if(summarySessionFilter && sessions.indexOf(summarySessionFilter)<0) summarySessionFilter="";
      sel.innerHTML=sessions.map(s=>'<option value="'+esc(s)+'" title="'+esc(s)+'">'+esc(sessionLabel(s))+'</option>').join("");
      sel.value = summarySessionFilter || sessions[0];
      summarySessionFilter=sel.value;
    }
    if(!block) return;
    const evs=all.filter(ev=>String(ev.session||"").trim()===summarySessionFilter)
      .sort((a,b)=>Number(b.importance||0)-Number(a.importance||0)||Number(b.ts||0)-Number(a.ts||0));
    if(empty) empty.style.display=evs.length?"none":"block";
    if(hint) hint.textContent="已总结 "+sessions.length+" 个会话 · 本会话 "+evs.length+" 个重要事件";
    block.innerHTML=evs.map((ev,idx)=>{
      const msgs=_eventMessages(summarySessionFilter,ev);
      const imp=Number(ev.importance||0).toFixed(2);
      const cent=(ev.centrality==null?0.5:Number(ev.centrality)).toFixed(2);
      const when=ev.ts?new Date(Number(ev.ts)*1000).toLocaleString("zh-CN",{month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"}):"";
      const status=String((ev.source_check&&ev.source_check.status)||"ok");
      const evConf=(ev.confidence==null||ev.confidence==="")?null:Number(ev.confidence);
      const warnFlags=(evConf!=null&&evConf<0.6?'<span class="mem-flag mem-flag-warn">低置信 '+evConf.toFixed(2)+'</span>':"")+
        (status!=="ok"?'<span class="mem-flag mem-flag-warn">来源待核 '+esc(status)+'</span>':"");
      return '<div class="memory-card">'+
        '<div class="memory-card-head"><span class="memory-level-tag">总结</span><b>'+esc(ev.title||"重要事件")+'</b><span class="hint">'+esc(when)+'</span>'+warnFlags+'</div>'+
        '<p class="memory-event-text">'+esc(ev.event||"")+'</p>'+
        '<div class="memory-scores"><small>重要度 '+imp+'</small><small>centrality '+cent+'</small><small>来源 '+esc(status)+'</small></div>'+
        '<div class="memory-important"><span class="memory-level-tag">重要事件</span><small>'+esc(ev.central_details||"")+'</small><small>意义：'+esc(ev.meaning_to_her||"")+'</small><small>事件感悟（单事件）：'+esc(ev.reflection||"")+'</small></div>'+
        '<button type="button" class="btn mini js-msg-toggle" data-idx="'+idx+'" data-count="'+msgs.length+'">收起消息 · '+msgs.length+' 条</button>'+
        '<div class="memory-messages" data-idx="'+idx+'">'+(msgs.length?msgs.map(_msgRow).join(""):'<div class="empty-mini">该事件没有归档时间窗，无法列出逐条消息。</div>')+'</div>'+
        '</div>';
    }).join("");
    if(!block.dataset.bound){
      block.addEventListener("click",e=>{
        const target=e.target||{};
        if(!target.closest) return;
        const btn=target.closest(".js-msg-toggle");
        if(!btn) return;
        const box=block.querySelector('.memory-messages[data-idx="'+btn.dataset.idx+'"]');
        if(box){ box.hidden=!box.hidden; const n=btn.dataset.count||""; btn.textContent=(box.hidden?"全部消息 · "+n+" 条":"收起消息 · "+n+" 条"); }
      });
      block.dataset.bound="1";
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
          title:text.slice(0,28), event:text.slice(0,140),
          meaning_to_her:text.slice(0,140), central_details:text.slice(0,140),
          ts:Number(e.ts||0), importance:Number(e.importance||0.5),
          centrality:0.5, recall_count:Number(e.hits||0), merge_count:0,
          self_defining:!!e.self_defining,
          emotion:String(e.encoding_emotion||"neutral")||"neutral",
          emotion_known:!!String(e.encoding_emotion||"").trim(),
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
  function eventBallsFromArchive(){
    const evs=Array.isArray(data.events)?data.events:[];
    return evs.filter(e=>e&&typeof e==="object").map(e=>{
      const text=String(e.event||e.title||"").trim();
      if(!text) return null;
      return {_kind:"event", id:String(e.id||("evt_"+Number(e.ts||0))),
        title:String(e.title||text.slice(0,28)), event:text.slice(0,160),
        meaning_to_her:String(e.meaning_to_her||""),
        central_details:String(e.central_details||""),
        ts:Number(e.ts||0), importance:Number(e.importance==null?0.5:e.importance),
        centrality:Number(e.centrality==null?0.5:e.centrality),
        recall_count:Number(e.recall_count||0), merge_count:Number(e.merge_count||0),
        self_defining:!!e.self_defining,
        emotion:String(e.emotion||"neutral"), emotion_known:!!String(e.emotion||"").trim(),
        last_recall:Number(e.last_recall||e.ts||0), summarized:true, role:"event"};
    }).filter(Boolean).sort((a,b)=>Number(b.importance||0)-Number(a.importance||0)||Number(b.ts||0)-Number(a.ts||0)).slice(0,10);
  }
  // Only important memories form balls by default: importance >= 0.60 or
  // self-defining (identity-central) memory. Toggle restores "show all".
  const MEMORY_BALL_IMPORTANCE=0.60;
  function importantMemoryBalls(list){
    if(!Array.isArray(list)) return [];
    if(!visual.memoryBallsImportant) return list;
    return list.filter(ev=>ev&&(ev._kind==="event"||ev.self_defining===true||Number(ev.importance||0)>=MEMORY_BALL_IMPORTANCE));
  }
  function updateOrbLegend(){
    if(!$("orbMemLegend")) return;
    if(!visual.memoryNodes){
      $("orbMemLegend").textContent="中心球 = 当前情绪球（只有一个）· 记忆节点已关闭，可在 设置 → 球体图层 开启";
      return;
    }
    const st=window.__biocoreState||{};
    const all=Array.isArray(st.memories)?st.memories:[];
    const shown=importantMemoryBalls(all).slice(0,10);
    if(!shown.length){
      $("orbMemLegend").textContent="还没有总结后的球：记忆巩固/总结后生成记忆球；归档事件会作为事件总结球显示";
      return;
    }
    if(shown.every(b=>b._kind==="event")){
      $("orbMemLegend").textContent="事件总结球 ×"+shown.length+"：已归档的重要事件（如“深夜表白澄清”）· 球大小=重要度 · 记忆总结后会追加记忆球 · 悬停查看";
      return;
    }
    const suffix=visual.memoryBallsImportant?"总结后重要记忆（重要度≥0.60 或自指）":"总结后记忆（最多 10）";
    $("orbMemLegend").textContent="记忆球 ×"+shown.length+"："+suffix+" · 球大小=重要度 · 外环数=情绪强度 · 悬停查看";
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
      verification:String(src.verification||"")};
  }
  function renderMemoryMeta(){
    const sel=$("memSessionFilter"), list=$("memEntryList"), empty=$("memEmpty"),
          note=$("memIndexNote"), tomb=$("memTombstoneList"), stats=$("memoryMetaStats");
    const sessions=memoryIndexValue();
    if(!sel||!list) return;
    if(sessions===null){
      sel.innerHTML='<option value="">后端未提供</option>'; sel.disabled=true;
      list.innerHTML="";
      if(tomb) tomb.innerHTML="";
      if(empty){ empty.style.display="block"; empty.textContent="当前后端版本未提供记忆明细（page/status.memory_index）；升级后自动显示，删除/回滚按钮也会随之出现。"; }
      if(note) note.textContent="后端未提供记忆索引";
      if(stats) stats.textContent="当前后端版本只返回记忆数量统计，未提供 source/confidence/tier/conflict/tombstone 明细。";
      return;
    }
    const valid=sessions.filter(s=>s&&Array.isArray(s.entries));
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
      const hint=String((data&&data.last_strategy_hint)||"").slice(0,60);
      stats.textContent="元数据："+total+" 条 · 低置信 "+low+" · 冲突 "+conflicts+" · 已总结 "+summarized+" · 墓碑 "+tombstones+" · trace "+trace.length+(hint?(" · hint "+hint):"") + "。";
    }
    const sessionsSorted=valid.slice().sort((a,b)=>String(a.session||"").localeCompare(String(b.session||"")));
    if(memSessionFilter && sessionsSorted.every(s=>String(s.session||"")!==memSessionFilter)) memSessionFilter="";
    if(!memSessionFilter) memSessionFilter=String(sessionsSorted[0].session||"");
    sel.disabled=sessionsSorted.length<2;
    sel.innerHTML=sessionsSorted.map(s=>{
      const key=String(s.session||"");
      const label=key?sessionLabel(key):"（无会话）";
      return '<option value="'+esc(key)+'" title="'+esc(key)+'">'+esc(label)+'</option>';
    }).join("");
    sel.value=memSessionFilter;
    const current=valid.find(s=>String(s.session||"")===memSessionFilter)||valid[0];
    const entries=(current.entries||[]).map(normMemEntry).filter(e=>e.id||e.text).sort((a,b)=>Number(b.ts||0)-Number(a.ts||0)).slice(0,40);
    if(empty) empty.style.display=entries.length?"none":"block";
    if(empty&&!entries.length) empty.textContent="这个会话还没有可展示的记忆条目。";
    if(note) note.textContent="已索引 "+sessionsSorted.length+" 个会话 · 本会话 "+entries.length+" 条";
    list.innerHTML=entries.map((e,idx)=>{
      const key=memKey(current.session,e.id||("idx"+idx));
      const armed=memOps[key]||null;
      const stateText=memOpStates[key]||"";
      const confText=e.confidence==null?"—":Number(e.confidence).toFixed(2);
      const confW=(e.confidence==null?0:clamp(e.confidence))*100;
      const lowConf=e.confidence!=null&&e.confidence<0.6;
      const unknownSrc=e.source==="unknown"||e.source==="inferred";
      const flags=[
        lowConf?'<span class="mem-flag mem-flag-warn">低置信</span>':"",
        unknownSrc?'<span class="mem-flag mem-flag-warn">'+esc(memSourceLabel(e.source))+'</span>':"",
        e.conflict?'<span class="mem-flag mem-flag-danger">冲突已更新</span>':"",
        e.versions>0?'<span class="mem-flag mem-flag-ok">可回滚 ×'+e.versions+'</span>':"",
        e.summarized?'<span class="mem-flag">已总结</span>':"",
        e.legacy?'<span class="mem-flag mem-flag-ok">旧数据·直述</span>':"",
        e.sensitive?'<span class="mem-flag mem-flag-warn">敏感</span>':"",
        e.poison?'<span class="mem-flag mem-flag-danger">注入风险</span>':"",
        e.verification==="verified"?'<span class="mem-flag mem-flag-ok">已验证</span>':"",
        e.links>0?'<span class="mem-flag mem-flag-ok">关联 '+e.links+'</span>':"",
        e.scope==="session"?'<span class="mem-flag">会话内</span>':""
      ].filter(Boolean).join("");
      const delLabel=armed&&armed.op==="delete"?"再点确认删除":"删除";
      const rbLabel=armed&&armed.op==="rollback"?"再点确认回滚":"回滚";
      const rbDisabled=e.versions>0?"":' disabled title="没有上一版本"';
      return '<div class="mem-card" data-key="'+esc(key)+'">'+
        '<div class="mem-card-head">'+
          '<span class="mem-tier mem-tier-'+(e.tier||"unknown")+'">'+esc(memTierLabel(e.tier))+'</span>'+
          '<span class="mem-source">来源 '+esc(memSourceLabel(e.source,e.legacy))+'</span>'+
          flags+
          '<span class="hint">'+esc(memWhen(e.ts))+' · #'+esc(String(e.id||"").slice(0,12)||"—")+'</span>'+
        '</div>'+
        '<p class="mem-text">'+esc(e.text||"")+'</p>'+
        '<div class="mem-meta-row">'+
          '<div class="mem-conf"><small>置信度</small><div class="mem-conf-track"><i style="width:'+confW.toFixed(0)+'%"></i></div><b>'+esc(confText)+'</b></div>'+
          '<small>重要度 '+Number(e.importance||0).toFixed(2)+'</small>'+
          '<small>召回 '+Number(e.hits||0)+' 次</small>'+
          '<small>写入 '+esc(e.lastOp||"—")+'</small>'+
        '</div>'+
        '<div class="mem-actions">'+
          '<button type="button" class="btn mini" data-mem-op="rollback" data-key="'+esc(key)+'" data-session="'+esc(String(current.session||""))+'" data-id="'+esc(e.id)+'"'+rbDisabled+'>'+rbLabel+'</button>'+
          '<button type="button" class="btn mini danger" data-mem-op="delete" data-key="'+esc(key)+'" data-session="'+esc(String(current.session||""))+'" data-id="'+esc(e.id)+'"'+(e.id?"":' disabled title="缺少条目 ID，无法删除"')+'>'+delLabel+'</button>'+
          '<span class="mem-op-state">'+esc(stateText)+'</span>'+
        '</div>'+
      '</div>';
    }).join("");
    const tombs=Array.isArray(current.tombstones)?current.tombstones:[];
    if(tomb){
      tomb.innerHTML=tombs.length?tombs.slice().reverse().slice(0,10).map(t=>{
        const item=(t&&typeof t==="object")?t:{text:String(t||"")};
        const _sid=String(current.session||""); const _tid=String(item.id||"");
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
      '<div class="rel-maps"><div><small>承诺 '+(commit).toFixed(2)+' · 投资 '+(invest).toFixed(2)+' · 修复 '+esc(repPhase)+' · 回归 '+esc(String(absence.bucket||"same_day"))+'</small><div class="chips"><span class="chip">依恋 安全'+Number(attach.safe||0).toFixed(2)+'</span><span class="chip">焦虑'+Number(attach.anxious||0).toFixed(2)+'</span><span class="chip">回避'+Number(attach.avoidant||0).toFixed(2)+'</span></div></div></div>'+
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
    if ($("selfVersion")) $("selfVersion").textContent = "v" + Number(sm.version || 0) + " · 最近 " + hist.length + " 次更新";
    if ($("selfHistory")) {
      const rows = hist.slice().reverse();
      $("selfHistory").innerHTML = rows.length ? rows.map(h => {
        const when = h.ts ? new Date(Number(h.ts) * 1000).toLocaleString() : "";
        return '<div class="hist-row"><span class="hist-ts">' + esc(when) + '</span><div class="hist-body"><b>' +
          esc(h.who_am_i || "—") + '</b>' + (h.narrative ? '<small>' + esc(h.narrative) + '</small>' : '') + '</div></div>';
      }).join("") : '<div class="empty-mini">还没有自我模型历史。</div>';
    }
    if ($("coreSelf")) $("coreSelf").textContent = s.core_self || "未形成";
    if ($("narrativeSelf")) $("narrativeSelf").textContent = s.narrative_self || "未形成";
    const tl = s.self_timeline || {};
    if ($("tlPast")) $("tlPast").innerHTML = (Array.isArray(tl.past) ? tl.past.slice(-5).reverse() : []).map(x => '<li>' + esc(x) + '</li>').join("") || '<li class="muted">—</li>';
    if ($("tlPresent")) $("tlPresent").textContent = tl.present || "—";
    if ($("tlFuture")) $("tlFuture").innerHTML = (Array.isArray(tl.future) ? tl.future.slice(0, 5) : []).map(x => '<li>' + esc(x) + '</li>').join("") || '<li class="muted">—</li>';
    const tree = s.reflection_tree || { roots: [], count: 0 };
    if ($("treeCount")) $("treeCount").textContent = "COUNT " + Number(tree.count || 0) + " · ROOTS " + ((Array.isArray(tree.roots) ? tree.roots : []).length);
    if ($("reflectionTree")) $("reflectionTree").innerHTML = renderTree(tree);
    const probs = Array.isArray(s.spectrum_probs) ? s.spectrum_probs.slice(0, 3) : [];
    if ($("spectrumProbs")) $("spectrumProbs").innerHTML = probs.length ? probs.map(x => {
      const p = Number(x.p || 0);
      return '<div class="spec-row"><span>' + esc(x.name || x.key || "?") + '</span><div class="spec-track"><i style="width:' +
        pct(p) + '"></i></div><b>' + (p * 100).toFixed(1) + '%</b></div>';
    }).join("") : '<div class="empty-mini">光谱概率未生成。</div>';
    const sec = s.sec || {};
    const secMap = [["relevance", "相关性"], ["implication", "影响"], ["coping_potential", "应对潜力"], ["normative", "规范一致"]];
    if ($("secGrid")) $("secGrid").innerHTML = secMap.map(pair => {
      const value = Number(sec[pair[0]] || 0);
      return '<div class="sec-item"><small>' + pair[1] + '</small><b>' + value.toFixed(2) + '</b><div class="bar"><i style="width:' +
        pct(value) + '"></i></div></div>';
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
    updateOrbLegend();
    renderSessionMemory();
    renderMemoryMeta();
    renderRelationships();
    renderInsightHistory();
    syncInsightAuto();
    renderSelfPanels(s);
    $("pluginBadge").textContent=data.enabled?"BioCore · ON":"BioCore · OFF";
    $("heroTitle").textContent=L(it.emotion)+" · "+L(it.intent);
    $("heroSub").textContent=it.need==="be_heard"?"现在更像是想被听见，不急着解决问题。":it.need==="space"?"现在更像是需要一点空间，不想被追问。":it.need==="share"?"现在更像是想分享，语气可以轻一点。":it.need==="vent"?"现在更像是想吐槽，先接住，不用讲道理。":"现在像是普通聊天，接不接都可以。";
    $("tagRow").innerHTML=[["emotion",it.emotion],["compound",it.compound],["spectrum",it.spectrum&&it.spectrum[0]?it.spectrum[0].name:""],["intent",it.intent],["tone",it.tone],["distance",it.distance],["expression",it.expression]].filter(x=>x[1]).map(x=>'<span class="chip">'+esc(x[0])+" · "+esc(x[1])+"</span>").join("");
    $("orbValence").textContent=fmt(s.v,2);
    $("teleSys").textContent = data.enabled ? "NOMINAL" : "OFFLINE";
    $("teleMode").textContent = L(it.intent) || "HOLD";
    $("teleLayers").textContent = "FIELD / AFFECT / CORE";
    $("teleSync").textContent = fmt(s.echo_trace,2);
    $("teleTicks").textContent = String(s.ticks==null?"--":s.ticks);
    const _n=s.noise||{}, _rp=s.ripple||{}, _sp=s.spiking||{};
    $("orbNoise").textContent=fmt((Number(_n.stress||0)+Number(_n.energy||0))/2,3);
    $("orbEcho").textContent=fmt(s.echo,3);
    $("orbRipple").textContent=Number(_rp.overlap||0).toFixed(2);
    $("orbSpike").textContent=Number(_sp.rate||0).toFixed(3);
    setMetric("mStress","bStress",s.stress); setMetric("mEnergy","bEnergy",s.energy); setMetric("mTrust","bTrust",s.trust); setMetric("mArousal","bArousal",s.a);
    const _dom=Number(s.d==null?0.5:s.d); $("mDominance").textContent=_dom.toFixed(2); $("bDominance").style.width=pct((_dom+1)/2);
    setMetric("mSocial","bSocial",s.social==null?0.5:s.social);
    const noise=s.noise||{};
    $("noiseList").innerHTML=["stress","energy","social","attention","valence"].map(k=>{
      const v=Number(noise[k]||0); const w=pct((v+0.3)/0.6);
      return '<div class="noise-row"><span>'+k+'</span><div class="noise-track"><i style="width:'+w+'"></i></div><b>'+fmt(v,3)+'</b></div>';
    }).join("");
    $("sEcho").textContent=fmt(s.echo,3); $("sEchoTrace").textContent=fmt(s.echo_trace,3);
    $("sUpper").textContent=Number((s.ripple||{}).upper||0).toFixed(2);
    $("sLower").textContent=Number((s.ripple||{}).lower||0).toFixed(2);
    $("sOverlap").textContent=Number((s.ripple||{}).overlap||0).toFixed(2);
    $("sRate").textContent=Number((s.spiking||{}).rate||0).toFixed(3);
    const _ap=s.appraisal||{};
    const _spec=(it.spectrum&&it.spectrum[0])?it.spectrum[0].name:"";
    const _exprKey=String(it.expression||"normal").toLowerCase();
    const _exprPct={none:5,closed:15,restrained:30,normal:55,open:80,high:92}[_exprKey]||55;
    $("intentLabel").textContent=L(it.intent)||"hold";
    $("intentText").textContent="还有"+(Number(s.energy)>.6?"力气":"点累")+"；压力"+(Number(s.stress)>.55?"偏高":"不高")+"。现在更想"+L(it.need)+"；计划是"+(it.plan||"自然回应")+"。";
    if($("intentTags"))$("intentTags").innerHTML=[L(it.emotion),L(it.intent),L(it.need),it.compound,_spec].filter(Boolean).map(x=>'<span class="intent-tag">'+esc(x)+'</span>').join("");
    if($("intentStrengthText"))$("intentStrengthText").textContent=L(it.expression)||"--";
    if($("intentStrengthBar"))$("intentStrengthBar").style.width=_exprPct+"%";
    if($("intentUrgencyText"))$("intentUrgencyText").textContent="紧迫度 "+Number(_ap.urgency||0).toFixed(2);
    if($("iFlowEmotion"))$("iFlowEmotion").textContent=L(it.emotion)||"--";
    if($("iFlowNeed"))$("iFlowNeed").textContent=L(it.need)||"--";
    if($("iFlowExpr"))$("iFlowExpr").textContent=L(it.expression)||"--";
    if($("iFlowPlan"))$("iFlowPlan").textContent=it.plan||"--";
    $("iEmotion").textContent=L(it.emotion); $("iNeed").textContent=L(it.need); $("iExpr").textContent=L(it.expression);
    if($("iCompound"))$("iCompound").textContent=it.compound||"-";
    if($("iSpectrum"))$("iSpectrum").textContent=_spec||"-";
    if($("iPlan"))$("iPlan").textContent=it.plan||"-";
    if($("iNovelty"))$("iNovelty").textContent=Number(_ap.novelty||0).toFixed(2);
    if($("iGoal"))$("iGoal").textContent=Number(_ap.goal_relevance||0).toFixed(2);
    if($("iCoping"))$("iCoping").textContent=Number(_ap.coping==null?.5:_ap.coping).toFixed(2);
    if($("iReg"))$("iReg").textContent=it.regulation||"-";
    if($("iSelf"))$("iSelf").textContent=(data.self_model&&data.self_model.who_am_i)?data.self_model.who_am_i:"未建立";
    if($("iNorm"))$("iNorm").textContent=Number(_ap.norm_compatibility||0.5).toFixed(2);
    if($("iExpected"))$("iExpected").textContent=Number(_ap.expectedness==null?1:_ap.expectedness).toFixed(2);
    if($("iUrgency"))$("iUrgency").textContent=Number(_ap.urgency||0).toFixed(2);
    if($("iOpponent")){const op=s.opponent||{}; $("iOpponent").textContent=Number(op.v||0).toFixed(2)+" / "+Number(op.a||0).toFixed(2);}
    if($("iAttention"))$("iAttention").textContent=Number(s.attention==null?.5:s.attention).toFixed(2);
    if($("iMeta"))$("iMeta").textContent=s.meta_emotion||"-";
    $("personaBars").innerHTML=["O","C","E","A","N"].map(k=>'<div class="p-row"><span>'+k+'</span><div class="p-track"><i style="width:'+pct(p[k])+'"></i></div><b>'+Number(p[k]||0).toFixed(2)+"</b></div>").join("");
    $("personaNote").textContent="stress "+Number(p.stress_reactivity||0).toFixed(2)+" · recovery "+Number(p.recovery_rate||0).toFixed(2)+" · social "+Number(p.social_baseline||0).toFixed(2);
    if($("selfWho")){const sm=data.self_model||{}; $("selfWho").value=sm.who_am_i||""; $("selfNarrative").value=sm.narrative||""; $("selfBoundaries").value=(sm.boundaries||[]).join("\n"); $("selfConsistency").value=(sm.consistency||[]).join("\n");}
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
    if($("regStats")){const rs=s.regulation_stats||{}; const ks=Object.keys(rs); $("regStats").innerHTML=ks.length?ks.map(k=>{const v=rs[k]||{};return '<div><small>'+esc(k)+'</small><b>'+Number(v.uses||0)+' / '+Number(v.success||0)+'</b></div>';}).join(""):'<div><small>regulation</small><b>暂无</b></div>';}
    if($("personaBaseline")) $("personaBaseline").innerHTML=[
      ["baseline_v",p.baseline_v],["baseline_a",p.baseline_a],["energy",p.energy_baseline],
      ["social",p.social_baseline],["dominance",p.da_baseline],["recovery",p.recovery_rate]
    ].map(x=>'<div><small>'+x[0]+'</small><b>'+(x[1]==null?"–":Number(x[1]).toFixed(2))+'</b></div>').join("");
    const cores=data.cores||[]; $("sessionCount").textContent=cores.length+" SESSIONS";
    $("sessionList").innerHTML=cores.length?cores.map(c=>{const i=c.intent||{},ss=c.snapshot||{};return '<div class="session"><div class="session-name" title="'+esc(c.key)+'">'+esc(sessionLabel(c.key))+'</div><div class="session-state">'+esc(L(i.emotion))+" · "+esc(i.compound||"")+" · "+esc(L(i.intent))+" · trust "+Number(ss.trust||0).toFixed(2)+" · "+Number(ss.ticks||0)+"t</div></div>";}).join(""):'<div class="empty">还没有活动会话。等第一条消息。</div>';
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
    const names={overview:"情绪概览",intent:"表达意图",persona:"人格自我",sessions:"活动会话",settings:"设置"};
    $("crumbView").textContent=names[name]||name;
  }
  document.querySelectorAll(".nav-item").forEach(a=>a.addEventListener("click",()=>switchView(a.dataset.view)));
  function visualSave(){storeSet("bio_show_noise",visual.noise?"1":"0");storeSet("bio_show_echo",visual.echo?"1":"0");storeSet("bio_show_ripple",visual.ripple?"1":"0");storeSet("bio_show_dominance",visual.dominance?"1":"0");storeSet("bio_show_social",visual.social?"1":"0");storeSet("bio_show_links",visual.links?"1":"0");storeSet("bio_show_nodes",visual.nodes?"1":"0");storeSet("bio_show_node_links",visual.nodeLinks?"1":"0");storeSet("bio_show_memory_nodes",visual.memoryNodes?"1":"0");storeSet("bio_show_memory_balls_important",visual.memoryBallsImportant?"1":"0");storeSet("bio_show_emotion_rings",visual.emotionRings?"1":"0");storeSet("bio_intensity",visual.intensity);if(window.__biocoreState)window.__biocoreState.visual=Object.assign({},visual);}
  $("swShowNoise").checked=visual.noise; $("swShowEcho").checked=visual.echo; $("swShowRipple").checked=visual.ripple;
  if($("swShowDominance"))$("swShowDominance").checked=visual.dominance;
  if($("swShowSocial"))$("swShowSocial").checked=visual.social;
  if($("swShowLinks"))$("swShowLinks").checked=visual.links;
  if($("swShowNodes"))$("swShowNodes").checked=visual.nodes;
  if($("swShowNodeLinks"))$("swShowNodeLinks").checked=visual.nodeLinks;
  if($("swShowMemoryNodes"))$("swShowMemoryNodes").checked=visual.memoryNodes;
  if($("swMemoryBallsImportant"))$("swMemoryBallsImportant").checked=visual.memoryBallsImportant;
  if($("swShowEmotionRings"))$("swShowEmotionRings").checked=visual.emotionRings;
  $("orbIntensity").value=visual.intensity;
  $("swShowNoise").addEventListener("change",e=>{visual.noise=e.target.checked;visualSave();});
  $("swShowEcho").addEventListener("change",e=>{visual.echo=e.target.checked;visualSave();});
  $("swShowRipple").addEventListener("change",e=>{visual.ripple=e.target.checked;visualSave();});
  if($("swShowDominance"))$("swShowDominance").addEventListener("change",e=>{visual.dominance=e.target.checked;visualSave();});
  if($("swShowSocial"))$("swShowSocial").addEventListener("change",e=>{visual.social=e.target.checked;visualSave();});
  if($("swShowLinks"))$("swShowLinks").addEventListener("change",e=>{visual.links=e.target.checked;visualSave();});
  if($("swShowNodes"))$("swShowNodes").addEventListener("change",e=>{visual.nodes=e.target.checked;visualSave();});
  if($("swShowNodeLinks"))$("swShowNodeLinks").addEventListener("change",e=>{visual.nodeLinks=e.target.checked;visualSave();});
  if($("swShowMemoryNodes"))$("swShowMemoryNodes").addEventListener("change",e=>{visual.memoryNodes=e.target.checked;visualSave();});
  if($("swMemoryBallsImportant"))$("swMemoryBallsImportant").addEventListener("change",e=>{visual.memoryBallsImportant=e.target.checked;visualSave();updateOrbLegend();});
  if($("swShowEmotionRings"))$("swShowEmotionRings").addEventListener("change",e=>{visual.emotionRings=e.target.checked;visualSave();});
  $("orbIntensity").addEventListener("input",e=>{visual.intensity=Number(e.target.value);visualSave();});
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
      }catch(err){
        e.target.checked=!val;
        if(window.alert) window.alert("设置保存失败："+String(err&&err.message||err));
      }
    });
  }
  bindBehaviorToggle("swSafetyEnabled","safety_enabled");
  bindBehaviorToggle("swHybridRetrieval","hybrid_retrieval");
  bindBehaviorToggle("swLlmCandidates","llm_memory_candidates");
  bindBehaviorToggle("swLlmOnlyReplySummary","llm_only_reply_summary");
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
    try{ ["bio_show_noise","bio_show_echo","bio_show_ripple","bio_show_dominance","bio_show_social","bio_show_links","bio_show_nodes","bio_show_node_links","bio_show_memory_nodes","bio_show_memory_balls_important","bio_show_emotion_rings","bio_intensity"].forEach(k=>localStorage.removeItem(k)); }catch(e){}
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
    if ($("ttsVoice")) $("ttsVoice").value = (cfg.tts || {}).voice || "";
    if ($("ttsFormat")) $("ttsFormat").value = (cfg.tts || {}).format || "mp3";
    if ($("imageSize")) $("imageSize").value = (cfg.image || {}).size || "";
    const comp = cfg.compression || {};
    const swc = $("swCompress"), th = $("compressThreshold"), mx = $("compressMax");
    if (swc) swc.checked = !!comp.enabled;
    const swSafety = $("swSafetyEnabled");
    if (swSafety) swSafety.checked = !!data.safety_enabled;
    const swHybrid = $("swHybridRetrieval");
    if (swHybrid) swHybrid.checked = data.hybrid_retrieval !== false;
    const swLlmCand = $("swLlmCandidates");
    if (swLlmCand) swLlmCand.checked = data.llm_memory_candidates !== false;
    const swLlmScope = $("swLlmOnlyReplySummary");
    if (swLlmScope) swLlmScope.checked = data.llm_only_reply_summary !== false;
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
      const raw = await bridge.apiGet("page/backup", {});
      const payload = raw && raw.data ? raw.data : raw;
      if (!payload || !payload.base64) throw new Error((payload && payload.message) || "empty backup");
      const bin = atob(payload.base64);
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      const blob = new Blob([bytes], { type: payload.mime || "application/zip" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = payload.filename || "biocore_core_backup.zip";
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
      if (st) st.textContent = "下载已开始 · " + (payload.filename || "");
    } catch (e) {
      if (st) st.textContent = "下载失败：" + String(e && e.message || e);
    }
  });


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
      if (st) st.textContent = "警告：会覆盖当前核心数据（人设/记忆/状态/API 配置）。5 秒内再点一次确认。";
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
      const raw = await bridge.apiPost("page/restore", { filename: f.name, base64 });
      const payload = raw && raw.data ? raw.data : raw;
      if (!payload || payload.status === "error") throw new Error((payload && payload.message) || "restore failed");
      if (st) st.textContent = "已恢复 " + Number(payload.files || 0) + " 个文件，请重启 AstrBot 生效。";
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
  function setupSettingsTabs(){
    const bar=$("settingsTabs"); if(!bar) return;
    const tabs=[...bar.querySelectorAll(".settings-tab")];
    if(!tabs.length) return;
    const activate=(name)=>{
      tabs.forEach(t=>t.classList.toggle("active",t.dataset.settingsTarget===name));
      document.querySelectorAll("#view-settings .settings-panel").forEach(p=>p.classList.toggle("active",p.id===name));
      document.querySelectorAll("#view-settings .section-title[data-settings-title]").forEach(t=>t.classList.toggle("active",t.dataset.settingsTitle===name));
    };
    tabs.forEach(t=>t.addEventListener("click",()=>{
      activate(t.dataset.settingsTarget||"settingsApi");
    }));
    activate(tabs[0].dataset.settingsTarget||"settingsApi");
  }
  function setupPersonaTabs(){
    const bar=$("personaTabs"); if(!bar) return;
    const tabs=[...bar.querySelectorAll(".persona-tab")];
    const panels=[...document.querySelectorAll("#view-persona .persona-tabpanel")];
    if(!tabs.length) return;
    const activate=(name)=>{
      tabs.forEach(t=>t.classList.toggle("active",t.dataset.personaTab===name));
      panels.forEach(p=>p.classList.toggle("active",p.dataset.personaTab===name));
    };
    tabs.forEach(t=>t.addEventListener("click",()=>activate(t.dataset.personaTab)));
    activate(tabs[0].dataset.personaTab||"baseline");
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
    // Default: everything folded; first click opens one small square.
    activate(null);
    tabs.forEach(t=>t.addEventListener("click",()=>{
      const name=t.dataset.sessionTab||"records";
      if(t.classList.contains("active")) activate(null); else activate(name);
    }));
  }
  function setupIntentTabs(){
    const bar=$('intentTabs'); if(!bar) return;
    const tabs=[...bar.querySelectorAll('.persona-tab')];
    const panels=[...document.querySelectorAll('#view-intent .intent-tabpanel')];
    if(!tabs.length) return;
    const activate=(name)=>{
      tabs.forEach(t=>t.classList.toggle('active',!!name&&t.dataset.intentTab===name));
      panels.forEach(p=>p.classList.toggle('active',!!name&&p.dataset.intentTab===name));
    };
    activate(null); // default folded; click one tile to open
    tabs.forEach(t=>t.addEventListener('click',()=>{
      const name=t.dataset.intentTab||'hero';
      if(t.classList.contains('active')) activate(null); else activate(name);
    }));
  }
  const BIO_VERSION = "v1.2.66";
  setTimeout(() => { const _sv = $("sideVersion"); if (_sv) _sv.textContent = BIO_VERSION + " · tendency layer"; }, 0);
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
  if (document.readyState === 'complete') load(); else window.addEventListener('load', () => load());
})();
