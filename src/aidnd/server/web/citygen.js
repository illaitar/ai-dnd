// Процедурный город (Watabou-стиль): Вороной → кварталы → усадка → дома (рекурсивное
// деление полигонов), стены по контуру, рыночная площадь, река, достопримечательности
// по сторонам света. drawCity(ctx,W,H,{seed,buildings,chrome}) → массив кликабельных целей.
import {Delaunay} from "https://esm.sh/d3-delaunay@6";

const mulberry=a=>()=>{a|=0;a=a+0x6D2B79F5|0;let t=Math.imul(a^a>>>15,1|a);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296;};
const area=p=>{let s=0;for(let i=0,n=p.length;i<n;i++){const a=p[i],b=p[(i+1)%n];s+=a[0]*b[1]-b[0]*a[1];}return Math.abs(s)/2;};
function centroid(p){let x=0,y=0,a=0;for(let i=0,n=p.length;i<n;i++){const A=p[i],B=p[(i+1)%n];const cr=A[0]*B[1]-B[0]*A[1];x+=(A[0]+B[0])*cr;y+=(A[1]+B[1])*cr;a+=cr;}a*=3;return a?[x/a,y/a]:p[0];}
const dist=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1]);
const shrink=(p,f)=>{const c=centroid(p);return p.map(q=>[c[0]+(q[0]-c[0])*f,c[1]+(q[1]-c[1])*f]);};
const norm=v=>{const L=Math.hypot(v[0],v[1])||1;return[v[0]/L,v[1]/L];};
function longestEdge(p){let bi=0,bl=-1;for(let i=0;i<p.length;i++){const a=p[i],b=p[(i+1)%p.length];const l=Math.hypot(b[0]-a[0],b[1]-a[1]);if(l>bl){bl=l;bi=i;}}return[p[bi],p[(bi+1)%p.length]];}
function clipHalf(poly,P,nx,ny,pos){const out=[],sd=q=>{const d=(q[0]-P[0])*nx+(q[1]-P[1])*ny;return pos?d>=-1e-9:d<=1e-9;};for(let i=0;i<poly.length;i++){const a=poly[i],b=poly[(i+1)%poly.length],sa=sd(a),sb=sd(b);if(sa)out.push(a);if(sa!==sb){const da=(a[0]-P[0])*nx+(a[1]-P[1])*ny,db=(b[0]-P[0])*nx+(b[1]-P[1])*ny,t=da/(da-db);out.push([a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t]);}}return out;}
function subdivide(poly,minA,rng,out,d){if(d>11||area(poly)<minA){out.push(poly);return;}const[a,b]=longestEdge(poly),dir=norm([b[0]-a[0],b[1]-a[1]]),c=centroid(poly),sp=Math.sqrt(area(poly)),t=(rng()-0.5)*0.3*sp,P=[c[0]+dir[0]*t,c[1]+dir[1]*t];const L=clipHalf(poly,P,dir[0],dir[1],true),R=clipHalf(poly,P,dir[0],dir[1],false);if(L.length>=3&&R.length>=3){subdivide(L,minA,rng,out,d+1);subdivide(R,minA,rng,out,d+1);}else out.push(poly);}
const ROOFS=['#a8542f','#b56a3c','#8a5630','#9c6b44','#7a4a30','#86603e','#94472a','#a36240'];
const LM_ROOF={inn:'#b07a1e',drink:'#b07a1e',shop:'#2f6fb0',shrine:'#d8d0e0',townhall:'#9a7b30',manor:'#7a3a3a',farm:'#5f7d42'};
const kindFromAff=a=>{a=a||[];if(a.includes('inn')||a.includes('drink'))return'inn';for(const k of['shop','shrine','townhall','manor','farm'])if(a.includes(k))return k;return a.includes('hideout')?'manor':'home';};
const shade=(hex,f)=>{const n=parseInt(hex.slice(1),16),c=v=>Math.max(0,Math.min(255,v*f|0));return`rgb(${c(n>>16)},${c((n>>8)&255)},${c(n&255)})`;};

export function drawCity(ctx, W, H, opts={}){
  const seed = opts.seed||1, buildings = opts.buildings||[], chrome = opts.chrome!==false;
  const keyMap = new Map((opts.keyHouses||[]).map(h=>[h.id,h])), marks=[];   // продвинутые в ключевые дома
  const CX=W/2, CY=H/2, rng=mulberry(seed), hits=[];
  const pathP=p=>{ctx.beginPath();ctx.moveTo(p[0][0],p[0][1]);for(let i=1;i<p.length;i++)ctx.lineTo(p[i][0],p[i][1]);ctx.closePath();};
  // точки + Ллойд + Вороной
  const N=Math.round(110*Math.min(1.6,(W*H)/(980*700)))+30, pts=[];
  for(let i=0;i<N;i++){const a=rng()*6.2832,r=Math.pow(rng(),0.7)*Math.min(W,H)*0.52;pts.push([CX+Math.cos(a)*r,CY+Math.sin(a)*r*0.92]);}
  for(let it=0;it<2;it++){const d=Delaunay.from(pts),v=d.voronoi([6,6,W-6,H-6]);for(let i=0;i<pts.length;i++){const q=v.cellPolygon(i);if(q)pts[i]=centroid(q);}}
  const vor=Delaunay.from(pts).voronoi([6,6,W-6,H-6]); let cells=[];
  for(let i=0;i<pts.length;i++){let q=vor.cellPolygon(i);if(!q)continue;q=q.slice(0,q.length-1);cells.push({site:pts[i],poly:q});}
  const Rcity=Math.min(W,H)*0.40, onEdge=q=>q.some(p=>p[0]<=8||p[0]>=W-8||p[1]<=8||p[1]>=H-8);
  cells.forEach(c=>c.city=dist(c.site,[CX,CY])<Rcity&&!onEdge(c.poly));
  const city=cells.filter(c=>c.city); if(!city.length)return hits;
  let square=city[0]; for(const c of city) if(dist(c.site,[CX,CY])<dist(square.site,[CX,CY]))square=c;
  // граф улиц: вершины Вороного городских клеток = перекрёстки, рёбра клеток = улицы
  const nmap=new Map(), nodes=[], adj=[], nkey=p=>Math.round(p[0])+','+Math.round(p[1]);
  const nid=p=>{const k=nkey(p);if(nmap.has(k))return nmap.get(k);const id=nodes.length;nmap.set(k,id);nodes.push([Math.round(p[0]),Math.round(p[1])]);adj.push([]);return id;};
  for(const c of city){const p=c.poly;for(let i=0;i<p.length;i++){const a=nid(p[i]),b=nid(p[(i+1)%p.length]);if(a!==b){if(!adj[a].includes(b))adj[a].push(b);if(!adj[b].includes(a))adj[b].push(a);}}}
  const sc0=centroid(square.poly); let start=0,sd=1e9; for(let i=0;i<nodes.length;i++){const d=Math.hypot(nodes[i][0]-sc0[0],nodes[i][1]-sc0[1]);if(d<sd){sd=d;start=i;}}
  const streets={nodes,adj,start};
  // ключевые локации = группа домов (целый квартал), а не иконка поверх: закрепляем за
  // ближайшим к направлению кварталом; его дома станут кликабельной самой локацией
  const used=new Set([square]), Rl=Math.min(W,H)*0.30, lmWards=[];
  for(const b of buildings){ if(b.kind!=='building')continue; const L=Math.hypot(b.dx,b.dy)||0;
    const tgt=L?[CX+b.dx/L*Rl,CY+b.dy/L*Rl*0.92]:[CX,CY]; let best=null,bd=1e9;
    for(const c of city){if(used.has(c)||c._lm)continue;const d=dist(c.site,tgt);if(d<bd){bd=d;best=c;}}
    if(!best)continue; used.add(best); best._lm=b;
    best._roof=(b.affordances||[]).map(a=>LM_ROOF[a]).find(Boolean)||LM_ROOF[kindFromAff(b.affordances)]||'#9a7b30';
    lmWards.push(best);
  }
  // фон
  ctx.clearRect(0,0,W,H); ctx.fillStyle='#a9b878'; ctx.fillRect(0,0,W,H);
  ctx.fillStyle='#5f7d42'; cells.filter(c=>!c.city).forEach(c=>{if(rng()<0.55){ctx.beginPath();ctx.arc(c.site[0],c.site[1],3+rng()*3,0,7);ctx.fill();}});
  ctx.fillStyle='#d8c39a'; city.forEach(c=>{pathP(c.poly);ctx.fill();});
  // кварталы
  for(const c of city){ if(c===square)continue; const ward=shrink(c.poly,0.86), lm=c._lm;
    ctx.fillStyle = lm ? shade(c._roof,1.72) : '#cdb585'; pathP(ward); ctx.fill();
    const plots=[]; subdivide(ward,120+rng()*90,rng,plots,0);
    // ключевое здание = ОДИН (крупнейший) участок квартала, остальные — обычные дома
    let keyPlot=null; if(lm){let ba=-1;for(const pl of plots){if(pl.length<3)continue;const a=area(shrink(pl,0.82));if(a>ba){ba=a;keyPlot=pl;}}}
    for(const pl of plots){ if(pl.length<3)continue; const inset=shrink(pl,0.82); if(area(inset)<18)continue;
      const isLM = lm && pl===keyPlot;
      if(!isLM&&rng()<0.07){ctx.fillStyle='#9fae6e';pathP(inset);ctx.fill();ctx.strokeStyle='rgba(60,80,40,.4)';ctx.lineWidth=0.7;pathP(inset);ctx.stroke();continue;}
      const cc=centroid(inset), id=`house:${seed}:${Math.round(cc[0])}_${Math.round(cc[1])}`;
      const promo = !isLM ? keyMap.get(id) : null;       // дом, поднявший важность → тоже ключевой
      const key = isLM ? {name:lm.name,kind:kindFromAff(lm.affordances),roof:c._roof,id:lm.id,go:lm.go}
                : promo ? {name:promo.name,kind:promo.kind||'home',roof:LM_ROOF[promo.kind]||'#9a7b30',id} : null;
      ctx.save();ctx.translate(1.1,1.4);ctx.fillStyle='rgba(40,28,12,.22)';pathP(inset);ctx.fill();ctx.restore();
      ctx.fillStyle = key ? key.roof : ROOFS[(rng()*ROOFS.length)|0]; pathP(inset);ctx.fill();
      const[a,b]=longestEdge(inset),dir=norm([b[0]-a[0],b[1]-a[1]]),L=Math.sqrt(area(inset))*0.42;
      ctx.strokeStyle='rgba(0,0,0,.22)';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(cc[0]-dir[0]*L,cc[1]-dir[1]*L);ctx.lineTo(cc[0]+dir[0]*L,cc[1]+dir[1]*L);ctx.stroke();
      ctx.strokeStyle = key?'#3a2c14':'rgba(40,28,12,.5)';ctx.lineWidth=key?1.3:0.8;pathP(inset);ctx.stroke();
      const r=Math.max(7,Math.sqrt(area(inset))*0.55);
      if(key){ flag(ctx,cc,key.roof); marks.push({c:cc,name:key.name,roof:key.roof});
        hits.push({x:cc[0],y:cc[1],r:Math.max(r,12),id:key.id,name:key.name,kind:key.kind,go:key.go,landmark:!!key.go,key:true}); }
      else hits.push({x:cc[0],y:cc[1],r,id,kind:'home',house:true});
    }
    if(lm){ ctx.strokeStyle=c._roof; ctx.lineWidth=1.6; pathP(ward); ctx.stroke(); }   // лёгкая рамка квартала
  }
  // площадь
  const sq=shrink(square.poly,0.9); ctx.fillStyle='#c9b486'; pathP(sq); ctx.fill();
  ctx.strokeStyle='rgba(90,66,34,.25)';ctx.lineWidth=0.6;const sc=centroid(sq),SR=Math.sqrt(area(sq));
  for(let g=-SR;g<SR;g+=9){ctx.beginPath();ctx.moveTo(sc[0]+g,sc[1]-SR);ctx.lineTo(sc[0]+g,sc[1]+SR);ctx.stroke();ctx.beginPath();ctx.moveTo(sc[0]-SR,sc[1]+g);ctx.lineTo(sc[0]+SR,sc[1]+g);ctx.stroke();}
  ctx.fillStyle='#7a6238';ctx.beginPath();ctx.arc(sc[0],sc[1],5,0,7);ctx.fill();ctx.fillStyle='#3a2c18';ctx.beginPath();ctx.arc(sc[0],sc[1],2.4,0,7);ctx.fill();
  // стены
  const seen=new Map(),key=(a,b)=>{const r=p=>[Math.round(p[0]),Math.round(p[1])];const A=r(a),B=r(b);return A[0]<B[0]||(A[0]===B[0]&&A[1]<=B[1])?A+'|'+B:B+'|'+A;};
  for(const c of city){const p=c.poly;for(let i=0;i<p.length;i++){const a=p[i],b=p[(i+1)%p.length],k=key(a,b),e=seen.get(k);if(e)e.n++;else seen.set(k,{a,b,n:1});}}
  const bnd=[...seen.values()].filter(e=>e.n===1); let gate=bnd[0];
  for(const e of bnd){const m=[(e.a[0]+e.b[0])/2,(e.a[1]+e.b[1])/2],gm=[(gate.a[0]+gate.b[0])/2,(gate.a[1]+gate.b[1])/2];if(m[1]>gm[1]&&Math.abs(m[0]-CX)<W*0.25)gate=e;}
  ctx.lineCap='round';
  ctx.strokeStyle='#6b5836';ctx.lineWidth=6;for(const e of bnd){if(e===gate)continue;ctx.beginPath();ctx.moveTo(e.a[0],e.a[1]);ctx.lineTo(e.b[0],e.b[1]);ctx.stroke();}
  ctx.strokeStyle='#4a3c22';ctx.lineWidth=2;for(const e of bnd){if(e===gate)continue;ctx.beginPath();ctx.moveTo(e.a[0],e.a[1]);ctx.lineTo(e.b[0],e.b[1]);ctx.stroke();}
  const verts=new Map();for(const e of bnd)for(const v of[e.a,e.b])verts.set(Math.round(v[0])+','+Math.round(v[1]),v);
  ctx.fillStyle='#5a4a2c';ctx.strokeStyle='#352a16';ctx.lineWidth=1;for(const v of verts.values()){ctx.fillRect(v[0]-3.5,v[1]-3.5,7,7);ctx.strokeRect(v[0]-3.5,v[1]-3.5,7,7);}
  const gm=[(gate.a[0]+gate.b[0])/2,(gate.a[1]+gate.b[1])/2];
  ctx.strokeStyle='#cdb585';ctx.lineWidth=8;ctx.beginPath();ctx.moveTo(gm[0],gm[1]);ctx.lineTo(gm[0]+(gm[0]-CX)*0.5,H-8);ctx.stroke();
  // река
  ctx.strokeStyle='rgba(70,120,160,.85)';ctx.lineWidth=Math.max(6,W*0.011);const y0=H*(0.2+rng()*0.1);
  ctx.beginPath();ctx.moveTo(-10,y0);ctx.bezierCurveTo(W*0.3,y0+40,W*0.45,CY+60,W*0.62,CY+20);ctx.bezierCurveTo(W*0.8,CY-20,W*0.9,H*0.7,W+10,H*0.62);ctx.stroke();
  ctx.strokeStyle='rgba(150,200,225,.6)';ctx.lineWidth=2.5;ctx.stroke();
  // подписи ключевых зданий (поверх домов): помечен один дом-локация на квартал/промоушн
  ctx.textAlign='center';ctx.textBaseline='middle';
  for(const m of marks){ ctx.font='bold 12px Georgia';
    const nm=m.name.length>24?m.name.slice(0,23)+'…':m.name, w=ctx.measureText(nm).width;
    ctx.save();ctx.shadowColor='rgba(0,0,0,.35)';ctx.shadowBlur=3;ctx.shadowOffsetY=1;
    ctx.fillStyle='rgba(245,236,212,.96)';ctx.strokeStyle=m.roof;ctx.lineWidth=2;rr(ctx,m.c[0]-w/2-7,m.c[1]-27,w+14,17,5);ctx.fill();ctx.stroke();ctx.restore();
    ctx.fillStyle='#2c2113';ctx.fillText(nm,m.c[0],m.c[1]-18.5);
  }
  // обрамление
  const vg=ctx.createRadialGradient(CX,CY*0.95,H*0.34,CX,CY,H*0.85);vg.addColorStop(0,'rgba(0,0,0,0)');vg.addColorStop(1,'rgba(40,28,12,.34)');ctx.fillStyle=vg;ctx.fillRect(0,0,W,H);
  ctx.strokeStyle='#4a3415';ctx.lineWidth=5;ctx.strokeRect(5,5,W-10,H-10);
  if(chrome){ compass(ctx,W); cartouche(ctx,W,opts.title||'Фэндалин'); }
  return {hits, streets};
}
function rr(ctx,x,y,w,h,r){ctx.beginPath();ctx.moveTo(x+r,y);ctx.arcTo(x+w,y,x+w,y+h,r);ctx.arcTo(x+w,y+h,x,y+h,r);ctx.arcTo(x,y+h,x,y,r);ctx.arcTo(x,y,x+w,y,r);ctx.closePath();}
function flag(ctx,c,col){ctx.strokeStyle='#3a2c14';ctx.lineWidth=1.2;ctx.beginPath();ctx.moveTo(c[0],c[1]-1);ctx.lineTo(c[0],c[1]-13);ctx.stroke();ctx.fillStyle=col;ctx.beginPath();ctx.moveTo(c[0],c[1]-13);ctx.lineTo(c[0]+8,c[1]-10.5);ctx.lineTo(c[0],c[1]-8);ctx.fill();}
function compass(ctx,W){ctx.save();ctx.translate(W-40,46);ctx.fillStyle='rgba(233,216,175,.85)';ctx.beginPath();ctx.arc(0,0,18,0,7);ctx.fill();ctx.strokeStyle='#4a3415';ctx.lineWidth=1;ctx.stroke();ctx.fillStyle='#4a3415';ctx.beginPath();ctx.moveTo(0,-20);ctx.lineTo(4,-3);ctx.lineTo(-4,-3);ctx.fill();ctx.font='bold 9px Georgia';ctx.textAlign='center';ctx.fillText('С',0,-22);ctx.restore();}
function cartouche(ctx,W,t){ctx.fillStyle='rgba(202,164,74,.92)';ctx.strokeStyle='#5a4222';ctx.lineWidth=1.4;rr(ctx,W/2-130,14,260,28,5);ctx.fill();ctx.stroke();ctx.fillStyle='#2c2113';ctx.font='italic 16px Georgia';ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText('Город '+t,W/2,29);}

window.drawCity = drawCity;
