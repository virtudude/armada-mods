'use strict';
const $ = id => document.getElementById(id);
// WebKit's page gesture must not compete with the map's pointer gestures.
for(const type of ['gesturestart','gesturechange','gestureend'])document.addEventListener(type,e=>e.preventDefault(),{passive:false});
for(const type of ['touchstart','touchmove'])document.addEventListener(type,e=>{if(e.touches.length>1||e.target.closest?.('#map-frame,#slots'))e.preventDefault();},{passive:false,capture:true});
document.addEventListener('wheel',e=>{if(e.ctrlKey)e.preventDefault();},{passive:false});
document.addEventListener('dragstart',e=>e.preventDefault());
const bridge = window.armada || {data:'',last:null,send(){}};
let state = null, tab = 'inventory', slot = null, person = null, alphabetical = false, received = 0, lastReply = '';
let equipment = null,questId=null,skillId=null,professionId=null,animalId=null,specialId=null,collectionId=null,collectionEntryId=null,communityRoomId=null,communityBundleId=null,communityIngredientId=null;
let inventoryDrag=null,pendingMove=null,inventoryTap=null,suppressInventoryClickUntil=0;
const activePointers=new Set();
let font = null, regionId = null, zoom = 1, pan = {x:0,y:0}, mapTransform = null;
const images = new Map(), memo = new Map();
const presentationImages=new Map();
let presentedSession=null;
function presentationImage(role,sprite){
  if(!sprite?.path){presentationImages.delete(role);return null;}
  let entry=presentationImages.get(role);
  if(entry?.path!==sprite.path){entry={path:sprite.path,image:asset(sprite)};presentationImages.set(role,entry);}
  return entry.image;
}
function updatePresentation(){
  const w=state?.ready?state.world:null;
  const loaded=img=>img?.complete&&img.naturalWidth>0;
  const landscape=presentationImage('landscape',state?.skin?.landscape);
  const menuReady=w&&[
    presentationImage('font',state?.skin?.font?.image),
    presentationImage('menu',state?.skin?.menuAtlas),
    presentationImage('farmer',w.profile?.portrait),
    presentationImage('face',w.mapFace)
  ].every(loaded);
  if(!w)presentedSession=null;else if(menuReady)presentedSession=state.session;
  document.body.dataset.phase=w&&presentedSession===state.session?'farm':loaded(landscape)?'title':'boot';
}
function asset(sprite) {
  if (!sprite?.path) return null;
  const path = bridge.data.replace(/\/$/,'') + '/' + sprite.path;
  if (!images.has(path)) {
    const img = new Image(); img.onload = () => { if(sprite.path===font?.image?.path||sprite.path===state?.skin?.dialogueFont?.image?.path)redrawLabels(); if(sprite.path===state?.skin?.menuAtlas?.path)buildMenuSkin(img); updatePresentation(); };
    if(images.size>=128)images.delete(images.keys().next().value);
    img.src = path; images.set(path,img);
  }
  return images.get(path);
}
function imageEl(sprite,cls='') {
  const el = document.createElement('img'); el.className=cls; el.alt='';
  const img=asset(sprite); if(img) el.src=img.src;
  return el;
}
function element(tag,cls,text) {const el=document.createElement(tag);if(cls)el.className=cls;if(text!=null){const t=document.createElement('game-label');t.value=String(text);if(tag==='p')t.setAttribute('wrap','');el.append(t);}return el;}
function textLabel(el,text){text=String(text??'').replace(/\r/g,'');const current=el.firstElementChild;if(el.childElementCount===1&&current?.tagName==='GAME-LABEL'){current.value=text;return;}el.replaceChildren(label(text));}
class GameLabel extends HTMLElement {
  connectedCallback(){
    if(!this.canvas){if(this.text===undefined)this.text=this.textContent.replace(/\r/g,'');this.textContent='';this.canvas=document.createElement('canvas');this.canvas.setAttribute('aria-hidden','true');this.append(this.canvas);this.observer=new ResizeObserver(()=>this.draw());}
    this.observer.observe(this.parentElement);requestAnimationFrame(()=>this.draw());
  }
  disconnectedCallback(){this.observer?.disconnect();}
  set value(text){const next=String(text??'').replace(/\r/g,'');if(next===this.text)return;this.text=next;this.draw();}
  get value(){return this.text||'';}
  draw(){
    if(!this.canvas||!this.isConnected||!this.getClientRects().length)return;
    const text=this.text||'';this.setAttribute('aria-label',text);
    const style=getComputedStyle(this),size=parseFloat(style.fontSize);
    const face=style.getPropertyValue('--game-font').trim()==='dialogue'?(state?.skin?.dialogueFont||font):font;
    const img=asset(face?.image),glyphs=face?.glyphs,shadow=face===state?.skin?.dialogueFont?3:2;
    const parentStyle=getComputedStyle(this.parentElement);
    const available=Math.max(1,this.clientWidth||this.parentElement.clientWidth-parseFloat(parentStyle.paddingLeft||0)-parseFloat(parentStyle.paddingRight||0));
    const measure=line=>{let x=0;for(const c of line){const g=glyphs?.[c]||glyphs?.['?'];if(g){x+=x===0?Math.max(0,g.left):g.left;x+=g.width+g.right+(face.spacing||0);}else x+=(face?.height||size)*.35;}return Math.max(1,x);};
    let scale=face?Math.max(.5,Math.round(size/face.height*2)/2):1;
    const lines=[];
    for(const paragraph of text.split('\n')){
      if(this.hasAttribute('wrap')&&glyphs){let line='';for(const word of paragraph.split(' ')){const candidate=line?line+' '+word:word;if(line&&measure(candidate)*scale>available){lines.push(line);line=word;}else line=candidate;}lines.push(line);}
      else lines.push(paragraph);
    }
    const raw=Math.max(1,...lines.map(measure));
    if(face&&!this.hasAttribute('wrap')&&raw*scale>available)scale=Math.max(.5,Math.floor(available/raw*2)/2);
    const w=Math.ceil(Math.min(available,face?raw*scale+shadow:Math.max(1,text.length*size*.6)+shadow));
    const lineHeight=face?Math.ceil(face.height*scale):Math.ceil(size*1.2);
    const h=Math.max(1,lineHeight*lines.length+Math.ceil(2*scale)+shadow);
    if(this.canvas.width!==w)this.canvas.width=w;if(this.canvas.height!==h)this.canvas.height=h;
    this.canvas.style.width=w+'px';this.canvas.style.height=h+'px';
    const ctx=this.canvas.getContext('2d');ctx.clearRect(0,0,w,h);ctx.imageSmoothingEnabled=false;
    if(img?.complete&&img.naturalWidth&&glyphs){
      const mask=this.mask||(this.mask=document.createElement('canvas'));if(mask.width!==w)mask.width=w;if(mask.height!==h)mask.height=h;
      const ink=mask.getContext('2d');ink.clearRect(0,0,w,h);ink.imageSmoothingEnabled=false;
      lines.forEach((line,row)=>{let x=0;for(const c of line){const g=glyphs[c]||glyphs['?'];if(!g){x+=face.height*.35;continue;}x+=x===0?Math.max(0,g.left):g.left;
        ink.drawImage(img,...g.rect,shadow+Math.round((x+g.crop[0])*scale),Math.round(g.crop[1]*scale+row*lineHeight),Math.round(g.rect[2]*scale),Math.round(g.rect[3]*scale));x+=g.width+g.right+(face.spacing||0);
      }});
      ink.globalCompositeOperation='source-in';ink.fillStyle=state?.skin?.shadowColor||'#b2723c';ink.fillRect(0,0,w,h);
      ctx.drawImage(mask,-shadow,shadow);ctx.drawImage(mask,0,shadow);
      ink.fillStyle=style.color;ink.fillRect(0,0,w,h);ink.globalCompositeOperation='source-over';
      // Match Utility.drawBoldText's four offset passes for legible menu weight.
      ctx.drawImage(mask,0,0);ctx.drawImage(mask,1,0);ctx.drawImage(mask,1,1);ctx.drawImage(mask,0,1);
    }else{ctx.font=size+'px Georgia';ctx.textBaseline='top';ctx.fillStyle=style.color;lines.forEach((line,row)=>ctx.fillText(line,0,row*lineHeight,w));}
  }
}
function buildMenuSkin(img){
  // Each region samples the same menuTexture tile as IClickableMenu.draw.
  // CSS sprites keep local game assets usable without reading a file-origin canvas.
  document.documentElement.style.setProperty('--menu-atlas',`url("${img.src}")`);
  document.querySelectorAll('.native-panel').forEach(panel=>{
    if(panel.querySelector(':scope > .menu-frame'))return;
    const frame=element('div','menu-frame');frame.setAttribute('aria-hidden','true');
    for(let i=0;i<9;i++)frame.append(element('div','frame-tile tile-'+i));
    panel.prepend(frame);
  });
}
customElements.define('game-label',GameLabel);
function redrawLabels(){document.querySelectorAll('game-label').forEach(el=>el.draw());}
function label(text,cls=''){const el=document.createElement('game-label');el.className=cls;el.value=text;return el;}
function setLabel(id,text){$(id).value=text;}
function capital(s){return (s||'').replace(/(^|\s)\S/g,c=>c.toUpperCase());}
function regionName(id){return id==='Valley'?'Stardew Valley':(id||'The valley').replace(/([a-z])([A-Z])/g,'$1 $2');}
function changed(key,value){const json=JSON.stringify(value);if(memo.get(key)===json)return false;memo.set(key,json);return true;}
function toast(text){textLabel($('toast'),text);$('toast').hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('toast').hidden=true,3500);}
function setTab(next){cancelInventoryDrag();tab=next;slot=null;equipment=null;document.querySelectorAll('nav button').forEach(b=>{const active=b.dataset.tab===tab;b.classList.toggle('active',active);b.setAttribute('aria-selected',String(active));});render();}
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>setTab(b.dataset.tab));
function drawState(next){
  if(!next)return;
  if(state?.session!==next.session){cancelInventoryDrag();pendingMove=null;memo.clear();slot=null;equipment=null;person=null;questId=null;skillId=null;professionId=null;animalId=null;specialId=null;collectionId=null;collectionEntryId=null;communityRoomId=null;communityBundleId=null;communityIngredientId=null;regionId=null;zoom=1;pan={x:0,y:0};lastReply=next.reply?.request||'';}
  if(state?.world?.region===regionId&&next.world?.region!==state?.world?.region){regionId=next.world?.region;zoom=1;pan={x:0,y:0};}
  state=next;received=Date.now();settleInventoryMove();
  if(next.skin&&changed('skin',next.skin)){
    font=next.skin.font;if(next.skin.textColor)document.documentElement.style.setProperty('--text-color',next.skin.textColor);
    for(const key of ['panel','landscape','sky','slot','lockedSlot','journalRow']){const img=asset(next.skin[key]);if(img)document.documentElement.style.setProperty('--'+(key==='panel'?'skin':key),`url("${img.src}")`);}
    for(const key of ['overview','detail','slot']){const img=asset(next.skin.community?.[key]);if(img)document.documentElement.style.setProperty('--community-'+key,`url("${img.src}")`);}
    const foreground=asset(next.skin.scenery?.foreground);if(foreground)document.documentElement.style.setProperty('--title-foreground',`url("${foreground.src}")`);
    document.querySelectorAll('.title-cloud').forEach((el,i)=>{const cloud=asset(next.skin.scenery?.clouds?.[i]);el.hidden=!cloud;if(cloud)el.src=cloud.src;});
    const atlas=asset(next.skin.menuAtlas);if(atlas)buildMenuSkin(atlas);
    document.querySelectorAll('nav button').forEach(b=>{const img=asset(next.skin.tabs?.[b.dataset.tab]||next.skin.character?.[b.dataset.tab+'Tab']||next.skin.catalog?.[b.dataset.tab+'Tab']||(b.dataset.tab==='community'?next.skin.community?.tab:null));if(img)b.querySelector('img').src=img.src;});
    redrawLabels();
  }
  if(changed('skills-tab-face',next.world?.mapFace?.path)){
    const button=document.querySelector('nav button[data-tab="skills"]');
    let face=button?.querySelector('.nav-farmer-face');
    if(button&&!face){face=imageEl(null,'nav-farmer-face');button.append(face);}
    if(face){const img=asset(next.world?.mapFace);face.hidden=!img;if(img)face.src=img.src;}
  }
  if(next.reply && next.reply.request!==lastReply && received-parseInt(next.reply.request,36)<5000){lastReply=next.reply.request;toast(next.reply.message);}
  render();
}
function render(){
  document.body.dataset.page=tab;
  updatePresentation();
  const w=state?.ready?state.world:null;
  $('idle').hidden=!!w;
  document.querySelectorAll('.page').forEach(p=>p.hidden=!w||p.id!==tab);
  $('status').hidden=true;
  if(!w){render.page=null;return;}
  if(tab==='map')renderMap(w);
  if(tab==='inventory')renderInventory(w);
  if(tab==='people')renderPeople(w);
  if(tab==='journal')renderJournal(w);
  if(tab==='skills')renderSkills(w);
  if(tab==='animals')renderAnimals(w);
  if(tab==='special')renderSpecial(w);
  if(tab==='collections')renderCollections(w);
  if(tab==='community')renderCommunity(w);
  if(render.page!==tab){render.page=tab;requestAnimationFrame(redrawLabels);}
}
function renderInventory(w){
  const inventory=w.inventory||[],capacity=w.inventoryCapacity??inventory.length;
  if(changed('slots',[inventory,w.selectedSlot,slot,capacity])){
    const cells=Array.from({length:Math.max(36,capacity)},(_,index)=>{
      const i=inventory.find(item=>item.slot===index),locked=index>=capacity;
      const b=element('button','slot');b.dataset.slot=String(index);b.classList.toggle('locked',locked);b.disabled=locked;
      b.classList.toggle('selected',index===slot);b.classList.toggle('held',index===w.selectedSlot);
      b.setAttribute('aria-label',locked?'Locked backpack slot':i?.count?`${i.name}${i.count>1?' ×'+i.count:''}`:'Empty backpack slot');b.setAttribute('aria-pressed',String(index===slot));
      if(i?.image)b.append(imageEl(i.image,i.imageRendered?'native-item':''));
      if(i?.count>1&&!i.imageRendered)b.append(element('span','count',i.count));
      if(i?.quality&&!i.imageRendered&&state.skin?.quality?.[i.quality])b.append(imageEl(state.skin.quality[i.quality],'quality'));
      b.onclick=()=>{slot=slot===index?null:index;equipment=null;renderInventory(state.world);requestAnimationFrame(redrawLabels);};return b;
    });
    $('slots').replaceChildren(...cells);
  }
  const profile=w.profile;
  if(profile&&changed('profile',[profile,equipment])){
    const portrait=asset(profile.portrait);if(portrait)$('farmer-portrait').src=portrait.src;
    setLabel('farmer-name',profile.name||w.player);setLabel('farm-title',(profile.farm||w.farm)+' Farm');
    setLabel('funds','Current funds: '+Number(profile.money||0).toLocaleString('en-US')+'g');
    setLabel('earnings','Total earnings: '+Number(profile.totalMoneyEarned||0).toLocaleString('en-US')+'g');
    setLabel('date',profile.date||`${w.day} ${capital(w.season)}, Year ${w.year}`);
    const gear=(profile.equipment||[]).map(g=>{
      const b=element('button','equipment-slot');b.classList.toggle('empty',!g.image);b.classList.toggle('selected',g.id===equipment);b.setAttribute('aria-label',g.name||g.id);b.append(imageEl(g.image||g.placeholder));
      b.onclick=()=>{equipment=equipment===g.id?null:g.id;slot=null;renderInventory(state.world);requestAnimationFrame(redrawLabels);};return b;
    });
    $('equipment-left').replaceChildren(...gear.slice(0,3));$('equipment-right').replaceChildren(...gear.slice(3,6));
  }
  const item=equipment?profile?.equipment?.find(i=>i.id===equipment):inventory.find(i=>i.slot===slot);
  if(changed('item',[item,w.selectedSlot,state.canSelect,equipment])){
    const root=$('item-detail');root.replaceChildren();root.hidden=!(equipment?item?.image:item?.count);
    if(root.hidden)return;
    const close=element('button','close-detail','×');close.setAttribute('aria-label','Close item details');close.onclick=()=>{slot=null;equipment=null;renderInventory(state.world);};root.append(close);
    root.append(imageEl(item.image,'hero'),label(item.name,'name'));
    if(item.category)root.append(element('div','category',item.category));
    root.append(element('p','description',item.description));
    if(!equipment){
      const b=element('button','select-item',item.slot===w.selectedSlot?'Selected':'Select item');b.disabled=!state.canSelect||item.slot===w.selectedSlot;
      b.onclick=()=>{
        const current=state?.world?.inventory.find(i=>i.slot===slot);
        if(!current||!state.canSelect||Date.now()-received>5000)return;
        bridge.send({action:'select',session:state.session,revision:state.revision,slot:current.slot,key:current.key,request:Date.now().toString(36)});
      };root.append(b);
      if(!state.canSelect)root.append(element('p','hint','Close the game menu to select an item.'));
    }
  }
  // The stale-link timer can disable a cached button without changing item data.
  const select=$('item-detail').querySelector('.select-item');
  if(select)select.disabled=!!pendingMove||!state.canSelect||Date.now()-received>5000||slot===w.selectedSlot;
  syncInventoryDragUI();
}
function currentInventoryItem(index){return state?.world?.inventory.find(i=>i.slot===index);}
function canDragInventory(){return tab==='inventory'&&state?.canMove&&!pendingMove&&Date.now()-received<5000;}
function syncInventoryDragUI(){
  for(const cell of $('slots').children){const index=Number(cell.dataset.slot);
    cell.classList.toggle('drag-source',!!inventoryDrag?.active&&index===inventoryDrag.from);
    cell.classList.toggle('drop-target',!!inventoryDrag?.active&&index===inventoryDrag.to);
    cell.classList.toggle('move-pending',!!pendingMove&&(index===pendingMove.from||index===pendingMove.to));
  }
}
function cancelInventoryDrag(){
  if(inventoryDrag?.active)suppressInventoryClickUntil=Date.now()+700;
  inventoryDrag=null;$('inventory-drag').hidden=true;syncInventoryDragUI();
}
function settleInventoryMove(){
  if(pendingMove&&state.reply?.request===pendingMove.request)pendingMove=null;
  if(pendingMove&&Date.now()>pendingMove.deadline){pendingMove=null;toast('Move not confirmed. Check your backpack before trying again.');}
  if(inventoryDrag&&(!state.canMove||inventoryDrag.session!==state.session||currentInventoryItem(inventoryDrag.from)?.key!==inventoryDrag.fromKey))cancelInventoryDrag();
}
function inventoryDropTarget(x,y){
  const cell=document.elementFromPoint(x,y)?.closest('.slot');
  return cell?.parentElement===$('slots')&&!cell.disabled?Number(cell.dataset.slot):null;
}
document.addEventListener('pointerdown',e=>{
  activePointers.add(e.pointerId);
  if(activePointers.size>1){inventoryTap=null;cancelInventoryDrag();}
  else if(e.pointerType==='touch'||e.pointerType==='pen'){const cell=e.target.closest?.('#slots .slot');if(cell&&!cell.disabled)inventoryTap={pointerId:e.pointerId,index:Number(cell.dataset.slot),x:e.clientX,y:e.clientY,valid:true};}
},{capture:true});
for(const type of ['pointerup','pointercancel'])document.addEventListener(type,e=>activePointers.delete(e.pointerId),{capture:true});
$('slots').addEventListener('pointerdown',e=>{
  if(e.button!==0||activePointers.size>1||!canDragInventory())return;
  const cell=e.target.closest('.slot'),from=Number(cell?.dataset.slot),item=currentInventoryItem(from);
  if(!cell||cell.disabled||!item?.count||!item.key)return;
  inventoryDrag={pointerId:e.pointerId,from,fromKey:item.key,session:state.session,x:e.clientX,y:e.clientY,active:false,to:null,image:item.image};
});
document.addEventListener('pointermove',e=>{
  if(inventoryTap?.pointerId===e.pointerId&&Math.hypot(e.clientX-inventoryTap.x,e.clientY-inventoryTap.y)>=12)inventoryTap.valid=false;
  const moving=inventoryDrag;if(!moving||moving.pointerId!==e.pointerId)return;
  if(!canDragInventory()){cancelInventoryDrag();return;}
  if(!moving.active&&Math.hypot(e.clientX-moving.x,e.clientY-moving.y)<12)return;
  if(!moving.active){
    moving.active=true;$('slots').setPointerCapture(e.pointerId);$('item-detail').hidden=true;
    const img=asset(moving.image);if(img)$('inventory-drag').src=img.src;$('inventory-drag').hidden=false;
  }
  e.preventDefault();
  moving.to=inventoryDropTarget(e.clientX,e.clientY);
  $('inventory-drag').style.transform=`translate(${e.clientX-48}px,${e.clientY-76}px)`;
  syncInventoryDragUI();
},{passive:false});
document.addEventListener('pointerup',e=>{
  const moving=inventoryDrag;if(!moving||moving.pointerId!==e.pointerId)return;
  if(!moving.active){inventoryDrag=null;return;}
  const to=inventoryDropTarget(e.clientX,e.clientY),source=currentInventoryItem(moving.from),target=to===null?null:currentInventoryItem(to);
  const valid=canDragInventory()&&to!==null&&to!==moving.from&&moving.session===state.session&&source?.key===moving.fromKey;
  cancelInventoryDrag();
  if(!valid)return;
  const request=Date.now().toString(36);
  pendingMove={request,from:moving.from,to,deadline:Date.now()+6000};
  bridge.send({action:'move',request,session:state.session,revision:state.revision,from:moving.from,to,fromKey:moving.fromKey,toKey:target?.key??null});
  syncInventoryDragUI();
});
document.addEventListener('pointerup',e=>{
  const tap=inventoryTap;if(!tap||tap.pointerId!==e.pointerId)return;inventoryTap=null;
  if(!tap.valid||Date.now()<suppressInventoryClickUntil||inventoryDropTarget(e.clientX,e.clientY)!==tap.index)return;
  slot=slot===tap.index?null:tap.index;equipment=null;suppressInventoryClickUntil=Date.now()+500;renderInventory(state.world);requestAnimationFrame(redrawLabels);
});
document.addEventListener('pointercancel',e=>{if(inventoryTap?.pointerId===e.pointerId)inventoryTap=null;});
$('slots').addEventListener('pointercancel',e=>{if(inventoryDrag?.pointerId===e.pointerId)cancelInventoryDrag();});
// Touch starts with implicit capture on the item image. Taking capture on the
// grid emits a bubbling lostpointercapture from that image; the drag is still ours.
$('slots').addEventListener('lostpointercapture',e=>{if(e.target===$('slots')&&inventoryDrag?.pointerId===e.pointerId)cancelInventoryDrag();});
$('slots').addEventListener('click',e=>{if(Date.now()<suppressInventoryClickUntil){e.preventDefault();e.stopImmediatePropagation();}},{capture:true});
window.addEventListener('blur',()=>{activePointers.clear();inventoryTap=null;cancelInventoryDrag();});
function hearts(p){const el=element('div','hearts');el.setAttribute('aria-label',`${p.hearts} of ${p.maxHearts} hearts`);for(let i=0;i<p.maxHearts;i++)el.append(imageEl(i<p.hearts?state.skin?.heart:state.skin?.emptyHeart));return el;}
$('social-sort').onclick=()=>{alphabetical=!alphabetical;renderPeople(state.world);};
function renderPeople(w){
  const people=[...w.people];if(alphabetical)people.sort((a,b)=>a.name.localeCompare(b.name));
  textLabel($('social-sort'),alphabetical?'By name':'By hearts');
  if(!person||!people.some(p=>p.id===person))person=people[0]?.id;
  if(changed('people',[people,person,state.skin?.social]))$('people-list').replaceChildren(...people.map(p=>{
    const b=element('button','person');b.classList.toggle('selected',p.id===person);b.setAttribute('aria-label',p.name);
    b.append(imageEl(p.sprite||p.portrait,'friend-sprite'));
    const info=element('div','person-info');info.append(label(p.name,'friend-name'),hearts(p));
    if(p.birthday)info.append(element('small','birthday','Birthday today!'));
    b.append(info);
    const status=element('div','friend-checks'),art=state.skin?.social;
    for(const [kind,amount,total,description] of [['gift',Math.min(p.gifts,2),2,`${p.gifts} of 2 gifts given this week`],['talk',p.talked?1:0,1,p.talked?'Talked today':'Not talked today']]){
      const group=element('div','friend-status');group.setAttribute('aria-label',description);group.append(imageEl(art?.[kind],'status-symbol'));
      const checks=element('div','status-checks');for(let i=0;i<total;i++)checks.append(imageEl(i<amount?art?.checkedBox:art?.uncheckedBox));
      group.append(checks);status.append(group);
    }
    b.append(status);b.onclick=()=>{person=p.id;renderPeople(state.world);};return b;
  }));
  const p=people.find(p=>p.id===person);
  const whereabouts=w.npcs?.find(n=>n.id===person)?.location;
  if(changed('person',[p,whereabouts])){
    const root=$('person-detail');root.replaceChildren();
    if(!p){root.append(element('p','empty-state','Meet someone in the valley to begin a friendship.'));return;}
    root.append(imageEl(p.portrait,'hero portrait'),label(p.name,'name'),hearts(p));
    const facts=element('div','social-facts');
    if(whereabouts){const row=element('div');row.append(element('b','','Current location'),label(whereabouts));facts.append(row);}
    for(const [title,value] of [['Birthday',p.birthday?'Today!':`${capital(p.birthdaySeason)} ${p.birthdayDay||''}`],['Conversation',p.talked?'You’ve talked today.':'Say hello today.'],['Gifts this week',`${p.gifts} of 2 given`],['Relationship',p.status==='Friendly'?'Friends':p.status]]){
      const row=element('div');row.append(element('b','',title),label(value));facts.append(row);
    }root.append(facts);
  }
}
$('journal-back').onclick=()=>{questId=null;renderJournal(state.world);};
function questTitle(q){
  if(q.titleImage?.path){const img=imageEl(q.titleImage,'quest-title-art');img.alt=q.title;return img;}
  return label(q.title,'quest-title');
}
function renderJournal(w){
  if(questId!==null&&!w.quests.some(q=>(q.id??q.title)===questId))questId=null;
  textLabel($('quest-count'),`${w.quests.length} entries`);
  $('journal-back').hidden=questId===null;$('quest-count').hidden=questId!==null;
  if(!changed('quests',[w.quests,questId,state.skin?.journalRow,state.skin?.questNew,state.skin?.questComplete]))return;
  const root=$('quests');root.replaceChildren();root.className=questId===null?'quest-list':'quest-detail';
  if(!w.quests.length){root.append(element('div','empty-state','Your journal is empty.'));return;}
  if(questId===null){
    root.append(...w.quests.map(q=>{
      const row=element('button','quest-row');row.setAttribute('aria-label',q.title);row.append(questTitle(q));
      const badge=q.completed?state.skin?.questComplete:q.isNew?state.skin?.questNew:null;if(badge?.path)row.prepend(imageEl(badge,'quest-badge'));
      row.onclick=()=>{questId=q.id??q.title;renderJournal(state.world);};return row;
    }));
    return;
  }
  const q=w.quests.find(q=>(q.id??q.title)===questId);if(!q)return;
  root.append(questTitle(q),element('p','quest-description',q.description));
  const objectives=q.objectives?.length?q.objectives:q.objective?[q.objective]:[];
  if(objectives.length){const list=element('div','quest-objectives');for(const objective of objectives)list.append(element('p','objective',typeof objective==='string'?objective:objective.text));root.append(list);}
  if(q.completed)root.append(element('p','due','Complete. Collect your reward in the game.'));
  else if(q.timed||q.days>0)root.append(element('p','due',`${q.days} day${q.days===1?'':'s'} remaining`));
  root.scrollTop=0;
}
function renderSkills(w){
  const data=w.skills;if(!data)return;
  if(changed('skills-farmer',[data.name,data.title,data.level,data.health,data.maxHealth,data.stamina,data.maxStamina,data.stardrops,data.mastery,w.profile?.portrait,state.skin?.character])){
    const root=$('skills-farmer');root.replaceChildren(imageEl(w.profile?.portrait,'skills-portrait'),label(data.name,'name'),label(data.title,'farmer-title'));
    const facts=element('div','skill-facts');
    for(const text of [`Level ${data.level}`,`Health ${data.health} / ${data.maxHealth}`,`Energy ${Math.floor(data.stamina)} / ${data.maxStamina}`])facts.append(label(text));
    const stardrops=element('div','skill-fact-icon');stardrops.append(imageEl(data.stardrops>0?(state.skin?.character?.stardropFound||state.skin?.character?.stardrop):state.skin?.character?.stardrop),label(`${data.stardrops} / 7`));facts.append(stardrops);
    if(data.mastery?.experience>0){const mastery=element('div','skill-fact-icon');mastery.append(imageEl(state.skin?.character?.mastery),label(`Mastery ${data.mastery.level}`));facts.append(mastery);}
    root.append(facts);
  }
  if(skillId===null||!data.rows.some(r=>r.id===skillId)){skillId=data.rows[0]?.id;professionId=null;}
  if(changed('skill-rows',[data.rows,skillId,professionId,state.skin?.character]))$('skill-rows').replaceChildren(...data.rows.map(skill=>{
    const row=element('div','skill-row');row.classList.toggle('selected',skill.id===skillId);
    const name=element('button','skill-name');name.append(imageEl(skill.image),label(skill.name));name.onclick=()=>{skillId=skill.id;professionId=null;renderSkills(state.world);};row.append(name);
    const track=element('div','skill-track');track.setAttribute('aria-label',`${skill.name}, level ${skill.level}`);
    for(let i=1;i<=10;i++){
      const milestone=i===5||i===10,filled=i<=skill.baseLevel,art=state.skin?.character;
      const profession=skill.professions.find(p=>p.level===i);
      if(milestone&&profession){const badge=element('button','skill-milestone');badge.setAttribute('aria-label',profession.name);badge.append(imageEl(filled?art?.milestoneFull:art?.milestoneEmpty,'skill-notch'),imageEl(profession.image,'profession-icon'));badge.onclick=()=>{skillId=skill.id;professionId=profession.id;renderSkills(state.world);};track.append(badge);}
      else track.append(imageEl(milestone?(filled?art?.milestoneFull:art?.milestoneEmpty):(filled?art?.skillFull:art?.skillEmpty),milestone?'skill-notch milestone':'skill-notch'));
    }
    row.append(track,label(String(skill.level),skill.boosted?'skill-level boosted':'skill-level'));return row;
  }));
  const skill=data.rows.find(r=>r.id===skillId),profession=skill?.professions.find(p=>p.id===professionId),detail=profession||skill;
  if(changed('skill-detail',detail)){
    const root=$('skill-detail');root.replaceChildren();if(!detail)return;
    root.append(imageEl(detail.image,'detail-icon'),label(detail.name,'name'),element('p','',detail.description||'Gain experience to improve this skill.'));
  }
}
function animalHearts(animal){
  const row=element('div','hearts');row.setAttribute('aria-label',`${animal.hearts} of 5 hearts`);
  for(const value of animal.heartStates||[]){const cell=element('span','animal-heart');cell.append(imageEl(value===1?state.skin?.heart:state.skin?.emptyHeart));if(value===.5)cell.append(imageEl(state.skin?.character?.halfHeart,'half-heart'));row.append(cell);}return row;
}
function petStatus(animal){
  const status=element('div','animal-status'),art=state.skin?.character;
  if(animal.petState>=0){status.append(imageEl(art?.pet,'pet-icon'),imageEl(art?.petStates?.[animal.petState],'pet-state'));status.setAttribute('aria-label',['Not petted today','Auto-petted today','Petted today'][animal.petState]||'');}
  if(animal.cracker)status.append(imageEl(art?.animalCracker,'cracker-icon'));
  if(animal.carrot)status.append(imageEl(art?.carrot,'carrot-icon'));
  return status;
}
function renderAnimals(w){
  const animals=w.animals||[];textLabel($('animal-count'),`${animals.length}`);
  if(!animals.some(a=>a.id===animalId))animalId=animals[0]?.id??null;
  if(changed('animal-list',[animals,animalId,state.skin?.character])){
    $('animal-list').replaceChildren(...animals.map(animal=>{
      const row=element('button','animal-row');row.classList.toggle('selected',animal.id===animalId);row.append(imageEl(animal.image,'animal-sprite'));
      const info=element('div','animal-info');info.append(label(animal.name,'name'));if(animal.kind!=='horse')info.append(animalHearts(animal));row.append(info,petStatus(animal));
      row.onclick=()=>{animalId=animal.id;renderAnimals(state.world);};return row;
    }));
    if(!animals.length)$('animal-list').append(element('p','empty-state','Your animals will appear here.'));
  }
  const animal=animals.find(a=>a.id===animalId);
  if(changed('animal-detail',[animal,state.skin?.character])){
    const root=$('animal-detail');root.replaceChildren();if(!animal)return;
    root.append(imageEl(animal.image,'animal-portrait'),label(animal.name,'name'),label(animal.type||capital(animal.kind),'animal-type'));
    if(animal.kind!=='horse')root.append(animalHearts(animal));
    if(animal.mood)root.append(element('p','animal-mood',animal.mood));
    const facts=element('div','social-facts');
    const pairs=[['Home',animal.home||animal.location]];
    if(animal.age!=null)pairs.push(['Age',`${animal.age} day${animal.age===1?'':'s'}`]);
    if(animal.petState>=0)pairs.push(['Petting',['Not petted today','Auto-petted today','Petted today'][animal.petState]]);
    if(animal.cracker)pairs.push(['Golden animal cracker','Given']);
    if(animal.kind==='horse')pairs.push(['Carrot today',animal.carrot?'Given':'Not given']);
    for(const [title,value] of pairs){if(!value)continue;const field=element('div');field.append(element('b','',title),label(value));facts.append(field);}root.append(facts);
  }
}
function catalogEntry(entry,selected,onSelect){
  const button=element('button','catalog-entry');button.classList.toggle('selected',selected);button.classList.toggle('unknown',!(entry.known??entry.unlocked));button.classList.toggle('incomplete',!!entry.known&&!entry.unlocked);button.setAttribute('aria-label',entry.name||'???');button.append(imageEl(entry.image));
  if(entry.badge?.path)button.append(imageEl(entry.badge,'collection-badge'));
  button.onclick=onSelect;return button;
}
function catalogDetail(root,entry,onClose){
  root.replaceChildren();root.hidden=!entry;root.classList.toggle('unknown',!!entry&&!(entry.known??entry.unlocked));if(!entry)return;
  const close=element('button','close-detail','×');close.setAttribute('aria-label','Close details');close.onclick=onClose;root.append(close,imageEl(entry.image,'hero'),label(entry.name||'???','name'),element('p','description',entry.description||''));
  if(entry.count!=null&&entry.unlocked)root.append(element('p','hint',`${entry.count} collected`));
  if(entry.detailImage?.path)root.append(imageEl(entry.detailImage,'collection-note'));
}
function renderSpecial(w){
  const data=w.specialItems;if(!data)return;textLabel($('special-count'),`${data.unlocked} / ${data.total}`);
  if(specialId!==null&&!data.entries.some(e=>e.id===specialId))specialId=null;
  if(changed('special',[data,specialId])){
    $('special-grid').replaceChildren(...data.entries.map(entry=>catalogEntry(entry,entry.id===specialId,()=>{specialId=specialId===entry.id?null:entry.id;renderSpecial(state.world);})));
    catalogDetail($('special-detail'),data.entries.find(e=>e.id===specialId),()=>{specialId=null;renderSpecial(state.world);});
  }
}
function renderCollections(w){
  const categories=w.collections?.categories||[];
  if(!categories.some(c=>c.id===collectionId)){collectionId=categories[0]?.id??null;collectionEntryId=null;}
  const category=categories.find(c=>c.id===collectionId);
  setLabel('collection-title',category?.name||'Collections');textLabel($('collection-count'),category?`${category.unlocked} / ${category.total}`:'');
  if(changed('collection-tabs',[categories.map(c=>[c.id,c.name,c.image]),collectionId]))$('collection-tabs').replaceChildren(...categories.map(c=>{
    const button=element('button','collection-tab');button.classList.toggle('selected',c.id===collectionId);button.setAttribute('role','tab');button.setAttribute('aria-selected',String(c.id===collectionId));button.setAttribute('aria-label',c.name);button.append(imageEl(c.image));button.onclick=()=>{collectionId=c.id;collectionEntryId=null;renderCollections(state.world);};return button;
  }));
  if(!category)return;
  if(collectionEntryId!==null&&!category.entries.some(e=>e.id===collectionEntryId))collectionEntryId=null;
  if(changed('collection-grid',[category,collectionEntryId])){
    $('collection-grid').replaceChildren(...category.entries.map(entry=>catalogEntry(entry,entry.id===collectionEntryId,()=>{collectionEntryId=collectionEntryId===entry.id?null:entry.id;renderCollections(state.world);})));
    catalogDetail($('collection-detail'),category.entries.find(e=>e.id===collectionEntryId),()=>{collectionEntryId=null;renderCollections(state.world);});
  }
}
$('community-back').onclick=()=>{communityBundleId=null;communityIngredientId=null;renderCommunity(state.world);};
function renderCommunity(w){
  const data=w.community;if(!data)return;const rooms=data.rooms||[];
  if(!rooms.some(r=>r.id===communityRoomId)){communityRoomId=rooms.find(r=>r.unlocked)?.id??rooms[0]?.id??null;communityBundleId=null;}
  const room=rooms.find(r=>r.id===communityRoomId);
  if(communityBundleId!==null&&!room?.bundles.some(b=>b.id===communityBundleId)){communityBundleId=null;communityIngredientId=null;}
  const bundle=room?.bundles.find(b=>b.id===communityBundleId);
  $('community-back').hidden=!bundle;
  if(changed('community-rooms',[data.status,rooms.map(r=>[r.id,r.name,r.unlocked,r.complete]),communityRoomId]))$('community-rooms').replaceChildren(...rooms.map(r=>{
    const button=element('button','community-room');button.classList.toggle('selected',r.id===communityRoomId);button.classList.toggle('room-locked',!r.unlocked);button.setAttribute('aria-label',r.name+(r.complete?', complete':!r.unlocked?', locked':''));
    button.append(label(r.name));if(r.complete)button.append(imageEl(state.skin?.social?.checkedBox,'room-check'));
    button.onclick=()=>{communityRoomId=r.id;communityBundleId=null;communityIngredientId=null;renderCommunity(state.world);};return button;
  }));
  if(changed('community-bundles',[data.status,data.message,room,bundle?.id,state.skin?.community])){
    const root=$('community-bundles');root.replaceChildren();root.className=bundle?'bundle-inside':'bundle-overview';
    if(!room){root.append(element('p','community-message',data.message));textLabel($('community-reward'),'');}
    else if(!room.unlocked){root.append(label(room.name,'name'),element('p','community-message','Complete more bundles to unlock this room.'));textLabel($('community-reward'),'');}
    else if(!bundle){
      root.append(label(room.name,'name'));const grid=element('div','bundle-grid');
      grid.append(...room.bundles.map(b=>{const button=element('button','bundle-button');button.classList.toggle('complete',b.complete);button.append(imageEl(b.image));const name=label(b.name);name.setAttribute('wrap','');button.append(name,label(`${b.donated} / ${b.required}`,'bundle-progress'));button.onclick=()=>{communityBundleId=b.id;communityIngredientId=null;renderCommunity(state.world);};return button;}));root.append(grid);textLabel($('community-reward'),room.reward||'');
    }else{
      const title=element('div','bundle-heading');title.append(imageEl(bundle.image),label(bundle.name,'name'));root.append(title);
      const ingredients=element('div','bundle-ingredients');
      ingredients.append(...bundle.ingredients.map((item,index)=>{const button=element('button','bundle-ingredient');button.classList.toggle('donated',item.donated);button.classList.toggle('ready',item.ready);button.setAttribute('aria-label',`${item.name}, ${item.donated?'donated':item.ready?'ready in backpack':'needed'}`);button.append(imageEl(item.image));
        if(item.count>1)button.append(label(item.money?Number(item.count).toLocaleString('en-US')+'g':String(item.count),'ingredient-count'));
        if(item.ready)button.append(imageEl(state.skin?.social?.checkedBox,'ingredient-check'));
        button.onclick=()=>{communityIngredientId=index;renderCommunity(state.world);};return button;}));root.append(ingredients);
      const donations=element('div','bundle-donations');donations.setAttribute('aria-label',`${bundle.donated} of ${bundle.required} donations`);
      const donated=bundle.ingredients.filter(i=>i.donated);for(let i=0;i<bundle.required;i++){const cell=element('div','bundle-donation');if(donated[i])cell.append(imageEl(donated[i].image));donations.append(cell);}root.append(donations,label(`${bundle.donated} / ${bundle.required}`,'bundle-progress'));
      let reward=bundle.reward?'Reward: '+(bundle.reward.count>1?bundle.reward.count+' ':'')+bundle.reward.name:'';
      if(bundle.rewardAvailable)reward+=' (ready in game)';textLabel($('community-reward'),reward);
    }
  }
  const ingredient=bundle?.ingredients[communityIngredientId];
  if(changed('community-ingredient',[ingredient,communityIngredientId])){
    const root=$('community-detail');root.replaceChildren();root.hidden=!ingredient;if(!ingredient)return;
    const close=element('button','close-detail','×');close.setAttribute('aria-label','Close ingredient details');close.onclick=()=>{communityIngredientId=null;renderCommunity(state.world);};
    root.append(close,imageEl(ingredient.image,'hero'),label(ingredient.name,'name'));
    const quality=({1:'Silver quality',2:'Gold quality',4:'Iridium quality'})[ingredient.quality];if(quality)root.append(element('p','category',quality+' or better'));
    const needed=ingredient.money?Number(ingredient.count).toLocaleString('en-US')+'g':String(ingredient.count);
    root.append(element('p','description',ingredient.donated?'Already donated.':`Needed: ${needed}`));
    if(!ingredient.donated)root.append(element('p','',ingredient.money?`Current funds: ${Number(ingredient.held).toLocaleString('en-US')}g`:`In your backpack: ${ingredient.held}`));
    if(ingredient.ready)root.append(element('p','category','Ready to donate in the game.'));
  }
}
let mapScene=null,mapPending=false,markerAnimate=false,lastMarker=null;
let npcMapNodes=new Map(),npcMapHits=[];
function openMapPerson(id){
  if(!state?.world?.people.some(p=>p.id===id))return;
  person=id;setTab('people');
  requestAnimationFrame(()=>$('people-list').querySelector('.person.selected')?.scrollIntoView({block:'nearest'}));
}
function placeMapPeople(npcs,t){
  // Only fan out people sharing a nearby location. Never push one building's
  // residents away to make room for another building, or repack for the viewport.
  const groups=[],placed=[];
  for(const npc of [...npcs].sort((a,b)=>a.id.localeCompare(b.id))){
    const group=groups.find(g=>g.every(p=>p.location===npc.location&&Math.hypot(p.x-npc.x,p.y-npc.y)<=24));
    if(group)group.push(npc);else groups.push([npc]);
  }
  for(const group of groups)group.forEach((npc,i)=>{
    const anchor={x:t.ox+npc.x*t.scale,y:t.oy+npc.y*t.scale};
    const radius=group.length===1?0:Math.min(44,28+group.length*3);
    const angle=-Math.PI/2+i/group.length*Math.PI*2;
    const x=anchor.x+Math.cos(angle)*radius,y=anchor.y+Math.sin(angle)*radius;
    // The short screen-sized offset remains constant as the map zooms beneath it.
    if(x<-28||y<-28||x>t.cw+28||y>t.ch+28)return;
    placed.push({npc,anchor,x,y});
  });
  return placed;
}
function drawMapPeople(t,w,animate){
  const root=$('map-people');if(!root)return;
  const npcs=(w.npcs||[]).filter(n=>n.region===regionId&&n.image?.path);
  const ids=new Set(npcs.map(n=>n.id));
  for(const [id,node] of npcMapNodes)if(!ids.has(id)){node.button.remove();node.line.remove();node.dot.remove();npcMapNodes.delete(id);}
  const placed=placeMapPeople(npcs,t);npcMapHits=[];
  for(const node of npcMapNodes.values()){node.button.hidden=true;node.line.hidden=true;node.dot.hidden=true;}
  for(const {npc,anchor,x,y} of placed){
    let node=npcMapNodes.get(npc.id);
    if(!node){
      const button=element('button','map-person'),line=element('span','map-person-line'),dot=element('span','map-person-origin');button.type='button';button.append(imageEl(npc.image));
      button.onclick=e=>{if(e.detail===0)openMapPerson(npc.id);};line.setAttribute('aria-hidden','true');dot.setAttribute('aria-hidden','true');root.append(line,dot,button);
      node={button,line,dot};npcMapNodes.set(npc.id,node);
    }
    const face=asset(npc.image);if(face&&node.button.firstElementChild.src!==face.src)node.button.firstElementChild.src=face.src;
    node.button.setAttribute('aria-label',`${npc.name} — ${npc.location}. Open Social profile`);
    node.button.hidden=false;node.button.style.transition=animate?'transform 220ms linear':'none';node.button.style.transform=`translate(${x-28}px,${y-28}px)`;
    const distance=Math.hypot(x-anchor.x,y-anchor.y);node.line.hidden=distance<1;node.dot.hidden=distance<1;node.dot.style.transform=`translate(${anchor.x-4}px,${anchor.y-4}px)`;
    node.line.style.width=distance+'px';node.line.style.transform=`translate(${anchor.x}px,${anchor.y}px) rotate(${Math.atan2(y-anchor.y,x-anchor.x)}rad)`;
    npcMapHits.push({id:npc.id,x,y});
  }
}
function renderMap(w){
  if(!regionId||!w.maps.some(r=>r.id===regionId)){regionId=w.region||w.maps[0]?.id;zoom=1;pan={x:0,y:0};}
  setLabel('location',w.location||'The valley');
  textLabel($('map-caption'),w.npcs?.length?'Tap a face for Social':regionId===w.region&&w.x!=null?'You are here':'');
  if(changed('regions',[w.maps.map(r=>r.id),regionId]))$('regions').replaceChildren(...w.maps.map(r=>{const b=element('button',r.id===regionId?'active':'',regionName(r.id));b.onclick=()=>{regionId=r.id;zoom=1;pan={x:0,y:0};$('map-note').hidden=true;renderMap(state.world);};return b;}));
  const region=w.maps.find(r=>r.id===regionId);
  const artChanged=changed('map-layers',[regionId,region?.layers]);
  if(artChanged){mapScene=null;lastMarker=null;}
  const moved=changed('map-position',[w.region,w.x,w.y,w.mapFace?.path]);
  const peopleMoved=changed('map-people',w.npcs);
  if(artChanged||moved||peopleMoved||render.page!==tab)scheduleMap((moved||peopleMoved)&&!artChanged);
}
function scheduleMap(animate=false){
  markerAnimate=markerAnimate||animate===true;
  if(mapPending)return;
  mapPending=true;requestAnimationFrame(()=>{mapPending=false;const animate=markerAnimate;markerAnimate=false;drawMap(animate);});
}
function prepareMap(){
  const region=state?.world?.maps.find(r=>r.id===regionId);if(!region)return null;
  if(!mapScene){
    const layers=region.layers.filter(l=>l?.image);if(!layers.length)return null;
    const minX=Math.min(0,...layers.map(l=>l.rect[0])),minY=Math.min(0,...layers.map(l=>l.rect[1]));
    const maxX=Math.max(...layers.map(l=>l.rect[0]+l.rect[2])),maxY=Math.max(...layers.map(l=>l.rect[1]+l.rect[3]));
    mapScene={id:regionId,layers,minX,minY,width:maxX-minX,height:maxY-minY,built:false};
  }
  const scene=mapScene,stage=$('map-scene');
  if(!scene.built){
    stage.style.width=scene.width+'px';stage.style.height=scene.height+'px';
    stage.replaceChildren(...scene.layers.map(layer=>{
      const img=imageEl(layer.image,'map-layer');
      img.style.left=(layer.rect[0]-scene.minX)+'px';img.style.top=(layer.rect[1]-scene.minY)+'px';
      img.style.width=layer.rect[2]+'px';img.style.height=layer.rect[3]+'px';return img;
    }));
    scene.built=true;
  }
  return scene;
}
function mapMetrics(){
  if(!mapScene)return null;
  const frame=$('map-frame'),cw=frame.clientWidth,ch=frame.clientHeight;if(!cw||!ch)return null;
  const s=mapScene,base=Math.min(cw/s.width,ch/s.height),scale=base*zoom;
  const maxX=Math.max(0,(s.width*scale-cw)/2),maxY=Math.max(0,(s.height*scale-ch)/2);
  pan.x=Math.max(-maxX,Math.min(maxX,pan.x));pan.y=Math.max(-maxY,Math.min(maxY,pan.y));
  return {cw,ch,base,scale,ox:(cw-s.width*scale)/2-s.minX*scale+pan.x,oy:(ch-s.height*scale)/2-s.minY*scale+pan.y};
}
function drawMap(animate=false){
  if(tab!=='map'||!state?.world||!prepareMap())return;
  const t=mapMetrics();if(!t)return;
  const movedView=!mapTransform||t.scale!==mapTransform.scale||t.ox!==mapTransform.ox||t.oy!==mapTransform.oy;
  mapTransform=t;
  const stage=$('map-scene'),transform=`translate(${t.ox+mapScene.minX*t.scale}px,${t.oy+mapScene.minY*t.scale}px) scale(${t.scale})`;
  if(mapScene.transform!==transform){stage.style.transform=transform;mapScene.transform=transform;}
  const marker=$('map-marker'),w=state.world;
  drawMapPeople(t,w,animate&&!movedView);
  marker.hidden=w.region!==regionId||w.x==null||w.y==null;
  if(marker.hidden){lastMarker=null;return;}
  const face=asset(w.mapFace);if(face&&marker.src!==face.src)marker.src=face.src;
  marker.classList.toggle('has-face',!!face);
  const point={x:t.ox+w.x*t.scale,y:t.oy+w.y*t.scale};
  marker.style.transition=animate&&!movedView&&lastMarker&&Math.hypot(point.x-lastMarker.x,point.y-lastMarker.y)<200?'transform 220ms linear':'none';
  marker.style.transform=`translate(${point.x-36}px,${point.y-36}px)`;
  lastMarker=point;
}
function zoomAt(next,x,y){
  const t=mapMetrics();if(!t)return;
  const anchor={x:(x-t.ox)/t.scale,y:(y-t.oy)/t.scale};
  zoom=Math.max(1,Math.min(3,next));const scale=t.base*zoom,s=mapScene;
  pan={x:x-anchor.x*scale-(t.cw-s.width*scale)/2+s.minX*scale,y:y-anchor.y*scale-(t.ch-s.height*scale)/2+s.minY*scale};
  mapMetrics();scheduleMap();
}
function buttonZoom(delta){const t=mapMetrics();if(t)zoomAt(zoom+delta,t.cw/2,t.ch/2);}
$('zoom-in').onclick=()=>buttonZoom(.5);
$('zoom-out').onclick=()=>buttonZoom(-.5);
$('center').onclick=()=>{regionId=state?.world?.region||regionId;zoom=1;pan={x:0,y:0};$('map-note').hidden=true;render();scheduleMap();};
const pointers=new Map();let drag=null,pinch=null,gestureMoved=false;
function mapPoint(e){const r=$('map-frame').getBoundingClientRect();return {x:e.clientX-r.left,y:e.clientY-r.top};}
function rebaseGesture(){
  const points=[...pointers.values()];pinch=null;drag=null;
  if(points.length>=2){const [a,b]=points,t=mapMetrics();if(!t)return;const cx=(a.x+b.x)/2,cy=(a.y+b.y)/2;pinch={distance:Math.max(1,Math.hypot(a.x-b.x,a.y-b.y)),zoom,anchorX:(cx-t.ox)/t.scale,anchorY:(cy-t.oy)/t.scale};gestureMoved=true;}
  else if(points.length===1)drag={x:points[0].x,y:points[0].y,px:pan.x,py:pan.y};
}
$('map-frame').addEventListener('pointerdown',e=>{
  e.currentTarget.setPointerCapture(e.pointerId);if(!pointers.size)gestureMoved=false;
  pointers.set(e.pointerId,mapPoint(e));rebaseGesture();
});
$('map-frame').addEventListener('pointermove',e=>{
  if(!pointers.has(e.pointerId))return;
  const point=mapPoint(e);pointers.set(e.pointerId,point);
  if(pointers.size>=2&&pinch){
    const [a,b]=[...pointers.values()],t=mapMetrics();if(!t)return;
    const cx=(a.x+b.x)/2,cy=(a.y+b.y)/2;
    zoom=Math.max(1,Math.min(3,pinch.zoom*Math.hypot(a.x-b.x,a.y-b.y)/pinch.distance));
    const scale=t.base*zoom,s=mapScene;
    pan={x:cx-pinch.anchorX*scale-(t.cw-s.width*scale)/2+s.minX*scale,y:cy-pinch.anchorY*scale-(t.ch-s.height*scale)/2+s.minY*scale};
  }else if(drag){
    const dx=point.x-drag.x,dy=point.y-drag.y;if(Math.hypot(dx,dy)>7)gestureMoved=true;
    if(gestureMoved)pan={x:drag.px+dx,y:drag.py+dy};
  }
  mapMetrics();scheduleMap();
});
function endPointer(e,cancelled=false){
  if(!pointers.has(e.pointerId))return;
  if(!cancelled&&!gestureMoved&&pointers.size===1&&mapTransform&&state?.world){
    const point=mapPoint(e),t=mapMetrics(),x=(point.x-t.ox)/t.scale,y=(point.y-t.oy)/t.scale;
    const npc=npcMapHits.find(n=>Math.abs(n.x-point.x)<=28&&Math.abs(n.y-point.y)<=28);
    if(npc){pointers.delete(e.pointerId);rebaseGesture();openMapPerson(npc.id);return;}
    const region=state.world.maps.find(r=>r.id===regionId),hit=region?.places.find(p=>x>=p.rect[0]&&y>=p.rect[1]&&x<=p.rect[0]+p.rect[2]&&y<=p.rect[1]+p.rect[3]);
    textLabel($('map-note'),hit?.text||'');$('map-note').firstElementChild?.setAttribute('wrap','');$('map-note').hidden=!hit;
  }
  if(cancelled)gestureMoved=true;
  pointers.delete(e.pointerId);rebaseGesture();
}
$('map-frame').addEventListener('pointerup',e=>endPointer(e));
$('map-frame').addEventListener('pointercancel',e=>endPointer(e,true));
$('map-frame').addEventListener('lostpointercapture',e=>{if(e.target===$('map-frame'))endPointer(e,true);});
new ResizeObserver(()=>{mapTransform=null;scheduleMap();}).observe($('map-frame'));
setInterval(()=>{if(received&&Date.now()-received>5000){$('status').hidden=false;textLabel($('status'),'Waiting for your game...');document.querySelectorAll('.select-item').forEach(b=>b.disabled=true);}},1000);
bridge.onState=drawState;drawState(bridge.last);
