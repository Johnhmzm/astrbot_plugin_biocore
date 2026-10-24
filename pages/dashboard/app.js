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
    insights:[{insight:"被认真询问意愿，会更愿意承担任务。"}]
  };
  let data=null, timer=null;
  const map={neutral:"平静",joy:"开心",sadness:"难过",fear:"害怕",anger:"生气",surprise:"惊讶",trust:"信任",loneliness:"孤独",approach:"靠近",hold:"停住",withdraw:"退开",far:"远",near:"近",soft:"轻",blunt:"直",playful:"俏皮",quiet:"安静",short:"短",normal:"正常",open:"展开",low:"低",high:"高",calm:"松",tense:"紧",overloaded:"过载",be_heard:"被听见",space:"空间",vent:"吐槽",share:"分享",talk:"说话"};
  const L=(v)=>map[v]||v||"—";
  const clamp=(v)=>Math.max(0,Math.min(1,Number(v)||0));
  const pct=(v)=>Math.round(clamp(v)*100)+"%";
  const fmt=(v,d=2)=>(Number(v)>=0?"+":"")+Number(v||0).toFixed(d);
  const esc=(s)=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const shortSession=(v)=>{const t=String(v||"");return t.length>36?t.slice(0,33)+"…":t;};
  function storeGet(k, fallback){ try { const v = localStorage.getItem(k); return v == null ? fallback : v; } catch (e) { return fallback; } }
  function storeSet(k, v){ try { localStorage.setItem(k, String(v)); } catch (e) {} }
  const visual={noise:storeGet("bio_show_noise","1")!=="0",echo:storeGet("bio_show_echo","1")!=="0",ripple:storeGet("bio_show_ripple","1")!=="0",dominance:storeGet("bio_show_dominance","1")!=="0",social:storeGet("bio_show_social","1")!=="0",links:storeGet("bio_show_links","1")!=="0",nodes:storeGet("bio_show_nodes","0")!=="0",nodeLinks:storeGet("bio_show_node_links","0")!=="0",memoryNodes:storeGet("bio_show_memory_nodes","1")!=="0",intensity:Number(storeGet("bio_intensity","65"))};
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
      sel.innerHTML=sessions.map(s=>'<option value="'+esc(s)+'">'+esc(shortSession(s))+'</option>').join("");
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
      return '<div class="memory-card">'+
        '<div class="memory-card-head"><span class="memory-level-tag">总结</span><b>'+esc(ev.title||"重要事件")+'</b><span class="hint">'+esc(when)+'</span></div>'+
        '<p class="memory-event-text">'+esc(ev.event||"")+'</p>'+
        '<div class="memory-scores"><small>重要度 '+imp+'</small><small>centrality '+cent+'</small><small>来源 '+esc(status)+'</small></div>'+
        '<div class="memory-important"><span class="memory-level-tag">重要事件</span><small>'+esc(ev.central_details||"")+'</small><small>意义：'+esc(ev.meaning_to_her||"")+'</small><small>反思：'+esc(ev.reflection||"")+'</small></div>'+
        '<button type="button" class="btn mini js-msg-toggle" data-idx="'+idx+'">全部消息 · '+msgs.length+' 条</button>'+
        '<div class="memory-messages" data-idx="'+idx+'" hidden>'+(msgs.length?msgs.map(_msgRow).join(""):'<div class="empty-mini">该事件没有归档时间窗，无法列出逐条消息。</div>')+'</div>'+
        '</div>';
    }).join("");
    if(!block.dataset.bound){
      block.addEventListener("click",e=>{
        const target=e.target||{};
        if(!target.closest) return;
        const btn=target.closest(".js-msg-toggle");
        if(!btn) return;
        const box=block.querySelector('.memory-messages[data-idx="'+btn.dataset.idx+'"]');
        if(box) box.hidden=!box.hidden;
      });
      block.dataset.bound="1";
    }
  }


  function renderTree(tree) {
    const roots = (tree && Array.isArray(tree.roots)) ? tree.roots : [];
    if (!roots.length) return '<div class="empty-mini">还没有跨事件反思节点。</div>';
    const node = (n, depth) => {
      const title = esc(n.insight || n.title || "反思节点");
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
    window.__biocoreState={intent:it,snapshot:s,visual:Object.assign({},visual),events:data.events||[]};
    renderSessionMemory();
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
    $("intentLabel").textContent=it.intent||"hold";
    $("intentText").textContent="还有"+(Number(s.energy)>.6?"力气":"点累")+"；压力"+(Number(s.stress)>.55?"偏高":"不高")+"。意图"+L(it.intent)+"，表达"+L(it.expression)+"，plan "+(it.plan||"—")+"。";
    $("iEmotion").textContent=L(it.emotion); $("iNeed").textContent=L(it.need); $("iExpr").textContent=L(it.expression);
    if($("iCompound"))$("iCompound").textContent=it.compound||"-";
    if($("iSpectrum"))$("iSpectrum").textContent=(it.spectrum&&it.spectrum[0])?it.spectrum[0].name:"-";
    if($("iPlan"))$("iPlan").textContent=it.plan||"-";
    const _ap=s.appraisal||{};
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
    if($("autoBioList")){const ab=s.autobiography||[]; $("autoBioList").innerHTML=ab.length?ab.slice().reverse().map(x=>'<div class="event-card"><b>'+esc(x.title||"事件")+'</b><p>'+esc(x.meaning||x.reflection||"")+'</p></div>').join(""):'<p class="api-note">还没有自传体记录。</p>';}
    if($("regStats")){const rs=s.regulation_stats||{}; const ks=Object.keys(rs); $("regStats").innerHTML=ks.length?ks.map(k=>{const v=rs[k]||{};return '<div><small>'+esc(k)+'</small><b>'+Number(v.uses||0)+' / '+Number(v.success||0)+'</b></div>';}).join(""):'<div><small>regulation</small><b>暂无</b></div>';}
    if($("personaBaseline")) $("personaBaseline").innerHTML=[
      ["baseline_v",p.baseline_v],["baseline_a",p.baseline_a],["energy",p.energy_baseline],
      ["social",p.social_baseline],["dominance",p.da_baseline],["recovery",p.recovery_rate]
    ].map(x=>'<div><small>'+x[0]+'</small><b>'+(x[1]==null?"–":Number(x[1]).toFixed(2))+'</b></div>').join("");
    const cores=data.cores||[]; $("sessionCount").textContent=cores.length+" SESSIONS";
    $("sessionList").innerHTML=cores.length?cores.map(c=>{const i=c.intent||{},ss=c.snapshot||{};return '<div class="session"><div class="session-name" title="'+esc(c.key)+'">'+esc(c.key)+'</div><div class="session-state">'+esc(L(i.emotion))+" · "+esc(i.compound||"")+" · "+esc(L(i.intent))+" · trust "+Number(ss.trust||0).toFixed(2)+" · "+Number(ss.ticks||0)+"t</div></div>";}).join(""):'<div class="empty">还没有活动会话。等第一条消息。</div>';
    try{applyApiConfig();}catch(e){}
  }
  function setMetric(l,b,v){const n=clamp(v);$(l).textContent=n.toFixed(2);$(b).style.width=pct(n);}
  function switchView(name){
    document.querySelectorAll(".nav-item").forEach(x=>x.classList.toggle("active",x.dataset.view===name));
    document.querySelectorAll(".view").forEach(v=>v.classList.toggle("active",v.id==="view-"+name));
    const names={overview:"情绪概览",intent:"表达意图",persona:"人格自我",sessions:"活动会话",settings:"设置"};
    $("crumbView").textContent=names[name]||name;
  }
  document.querySelectorAll(".nav-item").forEach(a=>a.addEventListener("click",()=>switchView(a.dataset.view)));
  function visualSave(){storeSet("bio_show_noise",visual.noise?"1":"0");storeSet("bio_show_echo",visual.echo?"1":"0");storeSet("bio_show_ripple",visual.ripple?"1":"0");storeSet("bio_show_dominance",visual.dominance?"1":"0");storeSet("bio_show_social",visual.social?"1":"0");storeSet("bio_show_links",visual.links?"1":"0");storeSet("bio_show_nodes",visual.nodes?"1":"0");storeSet("bio_show_node_links",visual.nodeLinks?"1":"0");storeSet("bio_show_memory_nodes",visual.memoryNodes?"1":"0");storeSet("bio_intensity",visual.intensity);if(window.__biocoreState)window.__biocoreState.visual=Object.assign({},visual);}
  $("swShowNoise").checked=visual.noise; $("swShowEcho").checked=visual.echo; $("swShowRipple").checked=visual.ripple;
  if($("swShowDominance"))$("swShowDominance").checked=visual.dominance;
  if($("swShowSocial"))$("swShowSocial").checked=visual.social;
  if($("swShowLinks"))$("swShowLinks").checked=visual.links;
  if($("swShowNodes"))$("swShowNodes").checked=visual.nodes;
  if($("swShowNodeLinks"))$("swShowNodeLinks").checked=visual.nodeLinks;
  if($("swShowMemoryNodes"))$("swShowMemoryNodes").checked=visual.memoryNodes;
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
  $("orbIntensity").addEventListener("input",e=>{visual.intensity=Number(e.target.value);visualSave();});
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
  $("refreshBtn").addEventListener("click",load);
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
  const BIO_VERSION = "v1.2.3";
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
  setupPersonaTabs();
  setupFolds();
  arrangeFoldGrid();
  if (document.readyState === 'complete') load(); else window.addEventListener('load', () => load());
})();
