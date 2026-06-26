// Процедурный город по алгоритму Watabou TownGeneratorOS (порт ключевых частей):
// спираль точек → Voronoi (d3) + релаксация → патчи → городская стена (окружность
// патчей) + башни/ворота → РЕКА делит патчи на два берега (Polygon.cut с зазором) →
// дома: getCityBlock (инсет на ширину улиц) + createAlleys (рекурсивный Cutter.bisect).
// Геометрия (cut/shrink/peel/bisect/createAlleys) портирована из geom/Polygon.hx,
// building/Cutter.hx, wards/Ward.hx. drawCity(ctx,W,H,opts) → {hits, streets, legend}.
const Delaunay = (typeof window !== "undefined" && window.d3 && window.d3.Delaunay);  // вендорный UMD (index.html)

// ── ГСЧ (детерминизм по сиду) ──────────────────────────────────────────────
const mulberry=a=>()=>{a|=0;a=a+0x6D2B79F5|0;let t=Math.imul(a^a>>>15,1|a);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296;};

// ── геометрия на точках {x,y} ──────────────────────────────────────────────
const sub=(a,b)=>({x:a.x-b.x,y:a.y-b.y}), add=(a,b)=>({x:a.x+b.x,y:a.y+b.y});
const len=a=>Math.hypot(a.x,a.y), dist=(a,b)=>Math.hypot(a.x-b.x,a.y-b.y);
const norm=(a,k=1)=>{const l=len(a)||1;return{x:a.x/l*k,y:a.y/l*k};};
const rot90=a=>({x:-a.y,y:a.x});
const cross=(x1,y1,x2,y2)=>x1*y2-y1*x2;
const interp=(a,b,r=0.5)=>({x:a.x+(b.x-a.x)*r,y:a.y+(b.y-a.y)*r});
function isectLines(x1,y1,dx1,dy1,x2,y2,dx2,dy2){const d=dx1*dy2-dy1*dx2;if(d===0)return null;const t2=(dy1*(x2-x1)-dx1*(y2-y1))/d;const t1=dx1!==0?(x2-x1+dx2*t2)/dx1:(y2-y1+dy2*t2)/dy1;return{x:t1,y:t2};}
function sqArea(p){let s=0;for(let i=0;i<p.length;i++){const a=p[i],b=p[(i+1)%p.length];s+=a.x*b.y-b.x*a.y;}return s*0.5;}
function centroid(p){let x=0,y=0,a=0;for(let i=0;i<p.length;i++){const v0=p[i],v1=p[(i+1)%p.length];const f=cross(v0.x,v0.y,v1.x,v1.y);a+=f;x+=(v0.x+v1.x)*f;y+=(v0.y+v1.y)*f;}const s=1/(3*(a||1));return{x:s*x,y:s*y};}
function center(p){let x=0,y=0;for(const v of p){x+=v.x;y+=v.y;}return{x:x/p.length,y:y/p.length};}
function isConvex(p){for(let i=0;i<p.length;i++){const v0=p[(i+p.length-1)%p.length],v1=p[i],v2=p[(i+1)%p.length];if(cross(v1.x-v0.x,v1.y-v0.y,v2.x-v1.x,v2.y-v1.y)<=0)return false;}return true;}
function longEdgeV(p){let v=null,L=-1;for(let i=0;i<p.length;i++){const a=p[i],b=p[(i+1)%p.length],l=dist(a,b);if(l>L){L=l;v=a;}}return v;}

// Polygon.cut(p1,p2,gap): разрез выпуклого полигона линией p1→p2 с зазором (порт Polygon.hx)
function cut(poly,p1,p2,gap=0){
  const x1=p1.x,y1=p1.y,dx1=p2.x-x1,dy1=p2.y-y1,n=poly.length;
  let e1=0,r1=0,e2=0,r2=0,cnt=0;
  for(let i=0;i<n;i++){const v0=poly[i],v1=poly[(i+1)%n];const t=isectLines(x1,y1,dx1,dy1,v0.x,v0.y,v1.x-v0.x,v1.y-v0.y);if(t&&t.y>=0&&t.y<=1){if(cnt===0){e1=i;r1=t.x;}else if(cnt===1){e2=i;r2=t.x;}cnt++;}}
  if(cnt!==2)return[poly.slice()];
  const pt1={x:x1+dx1*r1,y:y1+dy1*r1},pt2={x:x1+dx1*r2,y:y1+dy1*r2};
  let h1=poly.slice(e1+1,e2+1);h1.unshift(pt1);h1.push(pt2);
  let h2=poly.slice(e2+1).concat(poly.slice(0,e1+1));h2.unshift(pt2);h2.push(pt1);
  if(gap>0){h1=peel(h1,pt2,gap/2);h2=peel(h2,pt1,gap/2);}
  const v=sub(poly[(e1+1)%n],poly[e1]);
  return cross(dx1,dy1,v.x,v.y)>0?[h1,h2]:[h2,h1];
}
function peel(poly,v1,d){const i1=poly.indexOf(v1);if(i1<0)return poly;const v2=poly[i1===poly.length-1?0:i1+1];const nn=norm(rot90(sub(v2,v1)),d);return cut(poly,add(v1,nn),add(v2,nn),0)[0];}
// Polygon.shrink(d[]): инсет каждой грани внутрь на d[i] (городской блок) — для выпуклых
function shrink(poly,d){let q=poly.slice();for(let i=0;i<poly.length;i++){const v1=poly[i],v2=poly[(i+1)%poly.length];if(d[i]>0){const nn=norm(rot90(sub(v2,v1)),d[i]);const r=cut(q,add(v1,nn),add(v2,nn),0);q=r[0]||q;}}return q;}

// Cutter.bisect: разрез по грани от vertex с долей ratio, поворотом angle и зазором gap
function bisect(poly,vertex,ratio,angle,gap){
  const i=poly.indexOf(vertex),next=poly[(i+1)%poly.length];
  const p1=interp(vertex,next,ratio),d=sub(next,vertex);
  const cb=Math.cos(angle),sb=Math.sin(angle),vx=d.x*cb-d.y*sb,vy=d.y*cb+d.x*sb;
  return cut(poly,p1,{x:p1.x-vy,y:p1.y+vx},gap);
}
// Ward.createAlleys: рекурсивная нарезка блока на дома с переулками
function createAlleys(p,minSq,gridChaos,sizeChaos,rng,alley,emptyProb=0.04,split=true,depth=0){
  const v=longEdgeV(p);if(!v||depth>16)return Math.abs(sqArea(p))>1?[p]:[];
  const spread=0.8*gridChaos, ratio=(1-spread)/2+rng()*spread;
  const sq=Math.abs(sqArea(p));
  const angSpread=Math.PI/6*gridChaos*(sq<minSq*4?0:1), b=(rng()-0.5)*angSpread;
  const halves=bisect(p,v,ratio,b,split?alley:0);
  let out=[];
  for(const h of halves){const hs=Math.abs(sqArea(h));if(hs<1)continue;
    if(hs<minSq*Math.pow(2,4*sizeChaos*(rng()-0.5))){ if(rng()>=emptyProb)out.push(h); }
    else out=out.concat(createAlleys(h,minSq,gridChaos,sizeChaos,rng,alley,emptyProb, hs>minSq/((rng()*rng())||1e-6), depth+1));
  }
  return out;
}

// ── палитра/типы ───────────────────────────────────────────────────────────
const ROOFS=['#a8542f','#b56a3c','#8a5630','#9c6b44','#7a4a30','#86603e','#94472a','#a36240'];
const LM_ROOF={inn:'#b07a1e',drink:'#b07a1e',shop:'#2f6fb0',shrine:'#d8d0e0',townhall:'#9a7b30',manor:'#7a3a3a',farm:'#5f7d42'};
const kindFromAff=a=>{a=a||[];if(a.includes('inn')||a.includes('drink'))return'inn';for(const k of['shop','shrine','townhall','manor','farm'])if(a.includes(k))return k;return a.includes('hideout')?'manor':'home';};
const shade=(hex,f)=>{const n=parseInt(hex.slice(1),16),c=v=>Math.max(0,Math.min(255,v*f|0));return`rgb(${c(n>>16)},${c((n>>8)&255)},${c(n&255)})`;};
const pathP=(ctx,p)=>{ctx.beginPath();ctx.moveTo(p[0].x,p[0].y);for(let i=1;i<p.length;i++)ctx.lineTo(p[i].x,p[i].y);ctx.closePath();};

export function drawCity(ctx, W, H, opts={}){
  const seed=opts.seed||1, rng=mulberry(seed), s=W/560, hits=[], chrome=opts.chrome!==false;
  const buildings=opts.buildings||[], keyMap=new Map((opts.keyHouses||[]).map(h=>[h.id,h]));
  const CX=W/2, CY=H/2, R=Math.min(W,H)*0.42;
  const nP=14;                                     // число городских патчей (малый город)

  // 1) точки спиралью (Watabou buildPatches) → масштабируем в радиус R
  const N=nP*8, raw=[];
  const sa=rng()*2*Math.PI;
  for(let i=0;i<N;i++){const a=sa+Math.sqrt(i)*5, r=(i===0?0:10+i*(2+rng()));raw.push([Math.cos(a)*r,Math.sin(a)*r]);}
  let maxr=1;for(const p of raw)maxr=Math.max(maxr,Math.hypot(p[0],p[1]));
  const k=R/maxr, pts=raw.map(p=>[CX+p[0]*k, CY+p[1]*k]);

  // 2) Voronoi + 2 итерации Ллойда (релаксация → ровные патчи)
  const pad=R*0.6, bb=[CX-R-pad,CY-R-pad,CX+R+pad,CY+R+pad];
  for(let it=0;it<2;it++){const v=Delaunay.from(pts).voronoi(bb);for(let i=0;i<pts.length;i++){const c=v.cellPolygon(i);if(c){const cc=center(c.slice(0,c.length-1).map(q=>({x:q[0],y:q[1]})));pts[i]=[cc.x,cc.y];}}}
  const vor=Delaunay.from(pts).voronoi(bb);

  // 3) общие вершины (идентичность для рёбер/стены/реки)
  const vmap=new Map(), shared=(x,y)=>{const ky=x.toFixed(2)+','+y.toFixed(2);let p=vmap.get(ky);if(!p){p={x,y};vmap.set(ky,p);}return p;};
  const cells=[];
  for(let i=0;i<pts.length;i++){const poly=vor.cellPolygon(i);if(!poly)continue;
    const pl=[];for(let j=0;j<poly.length-1;j++){const p=shared(poly[j][0],poly[j][1]);if(!pl.length||pl[pl.length-1]!==p)pl.push(p);}
    if(pl.length<3)continue; if(sqArea(pl)<0)pl.reverse();      // CCW
    cells.push({site:{x:pts[i][0],y:pts[i][1]},shape:pl,d:Math.hypot(pts[i][0]-CX,pts[i][1]-CY)});
  }
  cells.sort((a,b)=>a.d-b.d);
  const onEdge=p=>p.some(v=>v.x<=bb[0]+2||v.y<=bb[1]+2||v.x>=bb[2]-2||v.y>=bb[3]-2);
  const inner=cells.filter(c=>!onEdge(c.shape)).slice(0,nP);   // городские патчи
  if(!inner.length)return{hits,streets:{nodes:[],adj:[],start:0},legend:[]};
  const innerSet=new Set(inner);
  const plaza=inner[0];                                        // центральный — рыночная площадь
  plaza._plaza=true;

  // граф улиц (общие вершины) — для навигации игрока
  const nmap=new Map(),nodes=[],adj=[],nid=p=>{const ky=Math.round(p.x)+','+Math.round(p.y);if(nmap.has(ky))return nmap.get(ky);const id=nodes.length;nmap.set(ky,id);nodes.push([p.x,p.y]);adj.push([]);return id;};
  for(const c of inner){const p=c.shape;for(let i=0;i<p.length;i++){const a=nid(p[i]),b=nid(p[(i+1)%p.length]);if(a!==b){if(!adj[a].includes(b))adj[a].push(b);if(!adj[b].includes(a))adj[b].push(a);}}}
  let start=0,sd=1e9;const pc=center(plaza.shape);for(let i=0;i<nodes.length;i++){const d=Math.hypot(nodes[i][0]-pc.x,nodes[i][1]-pc.y);if(d<sd){sd=d;start=i;}}
  const streets={nodes,adj,start};

  // 4) граничные рёбра (стена) — рёбра, не разделяемые двумя городскими патчами
  const eKey=(a,b)=>{const A=Math.round(a.x)+','+Math.round(a.y),B=Math.round(b.x)+','+Math.round(b.y);return A<B?A+'|'+B:B+'|'+A;};
  const eseen=new Map();
  for(const c of inner){const p=c.shape;for(let i=0;i<p.length;i++){const a=p[i],b=p[(i+1)%p.length],ky=eKey(a,b);const e=eseen.get(ky);if(e)e.n++;else eseen.set(ky,{a,b,n:1});}}
  const bnd=[...eseen.values()].filter(e=>e.n===1);

  // 5) РЕКА: гладкая кривая через город; патчи, которые она пересекает, делятся на берега
  const riverW=Math.max(9,W*0.016), halfW=riverW/2;
  const y0=CY+(rng()-0.5)*H*0.16;
  const bez=(p0,p1,p2,p3)=>{const o=[];for(let i=0;i<=70;i++){const t=i/70,u=1-t,uu=u*u,tt=t*t;o.push({x:uu*u*p0[0]+3*uu*t*p1[0]+3*u*tt*p2[0]+tt*t*p3[0],y:uu*u*p0[1]+3*uu*t*p1[1]+3*u*tt*p2[1]+tt*t*p3[1]});}return o;};
  const riverPts=bez([CX-R*1.4,y0-R*0.2],[CX-R*0.4,y0+R*0.35],[CX+R*0.2,CY-R*0.25],[CX+R*0.5,CY+R*0.1])
            .concat(bez([CX+R*0.5,CY+R*0.1],[CX+R*0.8,CY+R*0.3],[CX+R*1.1,CY-R*0.2],[CX+R*1.5,CY+R*0.15]));
  const riverNearest=p=>{let bd=1e9,q=p,nx=0,ny=1;for(let i=1;i<riverPts.length;i++){const a=riverPts[i-1],b=riverPts[i],vx=b.x-a.x,vy=b.y-a.y,L2=vx*vx+vy*vy||1;let t=((p.x-a.x)*vx+(p.y-a.y)*vy)/L2;t=t<0?0:t>1?1:t;const qx=a.x+vx*t,qy=a.y+vy*t,d=Math.hypot(p.x-qx,p.y-qy);if(d<bd){bd=d;q={x:qx,y:qy};const L=Math.sqrt(L2);nx=-vy/L;ny=vx/L;}}return{d:bd,q,nx,ny};};
  // точки входа/выхода реки в патч (для разреза на берега)
  const riverCrossing=poly=>{const xs=[];for(let i=0;i<poly.length;i++){const a=poly[i],b=poly[(i+1)%poly.length];for(let j=1;j<riverPts.length;j++){const c=riverPts[j-1],dd=riverPts[j];const t=isectLines(a.x,a.y,b.x-a.x,b.y-a.y,c.x,c.y,dd.x-c.x,dd.y-c.y);if(t&&t.x>=0&&t.x<=1&&t.y>=0&&t.y<=1)xs.push({p:{x:a.x+(b.x-a.x)*t.x,y:a.y+(b.y-a.y)*t.x},rj:j+t.y});}}if(xs.length<2)return null;xs.sort((u,w)=>u.rj-w.rj);return{a:xs[0].p,b:xs[xs.length-1].p};};

  // назначаем достопримечательности патчам по направлению (для меток/кликов)
  const used=new Set([plaza]), Rl=R*0.62;
  for(const bd2 of buildings){if(bd2.kind!=='building')continue;const L=Math.hypot(bd2.dx,bd2.dy)||0;const tgt={x:CX+(L?bd2.dx/L:0)*Rl,y:CY+(L?bd2.dy/L:0)*Rl};let best=null,bdst=1e9;for(const c of inner){if(used.has(c)||c._lm)continue;const d=dist(c.site,tgt);if(d<bdst){bdst=d;best=c;}}if(!best)continue;used.add(best);best._lm=bd2;best._roof=(bd2.affordances||[]).map(a=>LM_ROOF[a]).find(Boolean)||LM_ROOF[kindFromAff(bd2.affordances)]||'#9a7b30';}

  // ── РЕНДЕР ──────────────────────────────────────────────────────────────
  ctx.clearRect(0,0,W,H);
  ctx.fillStyle='#e7dab9';ctx.fillRect(0,0,W,H);               // фон вокруг — пергамент
  ctx.fillStyle='#cdbf99';for(const c of inner){pathP(ctx,c.shape);ctx.fill();}   // земля города (улицы/дворы)

  const MAIN=3.4*s, REG=2.1*s, ALLEY=1.4*s, minSq=Math.pow(15*s,2);
  // блок квартала: инсет каждой грани на ширину улицы (стена/река — шире)
  const blockOf=poly=>{const d=[];for(let i=0;i<poly.length;i++){const a=poly[i],b=poly[(i+1)%poly.length],ky=eKey(a,b);const onWall=(eseen.get(ky)||{}).n===1;const mid={x:(a.x+b.x)/2,y:(a.y+b.y)/2};const onRiver=riverNearest(mid).d<halfW+REG;d.push(onRiver?halfW+REG:onWall?MAIN:REG);}return isConvex(poly)?shrink(poly,d):shrink(poly,d);};
  const drawBuildings=(block,roofOf,collect)=>{
    if(Math.abs(sqArea(block))<minSq*1.2)return;
    const blds=createAlleys(block,minSq,0.5+rng()*0.2,0.6,rng,ALLEY,0.04);
    let big=null,bigA=-1;
    for(const bld of blds){const a=Math.abs(sqArea(bld));if(a>bigA){bigA=a;big=bld;}}
    for(const bld of blds){if(bld.length<3)continue;const a=Math.abs(sqArea(bld));if(a<6*s*s)continue;
      const cc=center(bld), iskey=collect&&bld===big;
      ctx.save();ctx.translate(1.1*s,1.4*s);ctx.fillStyle='rgba(40,28,12,.20)';pathP(ctx,bld);ctx.fill();ctx.restore();   // тень
      ctx.fillStyle=iskey?roofOf:ROOFS[(rng()*ROOFS.length)|0];pathP(ctx,bld);ctx.fill();
      ctx.strokeStyle=iskey?'#3a2c14':'rgba(40,28,12,.5)';ctx.lineWidth=(iskey?1.3:0.7)*s;pathP(ctx,bld);ctx.stroke();
      if(iskey&&collect)collect(cc,bld);
      else hits.push({x:cc.x,y:cc.y,r:Math.max(7*s,Math.sqrt(a)*0.5),id:`house:${seed}:${Math.round(cc.x)}_${Math.round(cc.y)}`,kind:'home',house:true});
    }
  };

  const marks=[];
  for(const c of inner){
    if(c._plaza){                                              // рыночная площадь: открытая мостовая + колодец
      const blk=shrink(c.shape,c.shape.map(()=>REG));ctx.fillStyle='#d8c39a';pathP(ctx,blk);ctx.fill();
      const sc=centroid(blk);ctx.fillStyle='#7a6238';ctx.beginPath();ctx.arc(sc.x,sc.y,4*s,0,7);ctx.fill();ctx.fillStyle='#3a2c18';ctx.beginPath();ctx.arc(sc.x,sc.y,2*s,0,7);ctx.fill();
      continue;
    }
    const lm=c._lm, roofOf=lm?c._roof:'#9a7b30';
    const collect=lm?((cc,bld)=>{const kind=kindFromAff(lm.affordances);marks.push({c:cc,name:lm.name,roof:c._roof,id:lm.id,kind,go:lm.go});hits.push({x:cc.x,y:cc.y,r:14*s,id:lm.id,name:lm.name,kind,go:lm.go,landmark:!!lm.go,key:true});}):null;
    const cr=riverCrossing(c.shape);
    if(cr){ for(const bank of cut(c.shape,cr.a,cr.b,riverW)){ if(bank.length>=3&&Math.abs(sqArea(bank))>minSq) drawBuildings(blockOf(bank),roofOf,collect); } }   // два берега
    else drawBuildings(blockOf(c.shape),roofOf,collect);
  }

  // 6) стена с башнями/воротами (проём там, где входит/выходит река)
  const wallGap=e=>riverNearest({x:(e.a.x+e.b.x)/2,y:(e.a.y+e.b.y)/2}).d<riverW*1.1;
  ctx.lineCap='round';ctx.lineJoin='round';
  ctx.strokeStyle='#6b5836';ctx.lineWidth=5.5*s;for(const e of bnd){if(wallGap(e))continue;ctx.beginPath();ctx.moveTo(e.a.x,e.a.y);ctx.lineTo(e.b.x,e.b.y);ctx.stroke();}
  ctx.strokeStyle='#4a3c22';ctx.lineWidth=1.8*s;for(const e of bnd){if(wallGap(e))continue;ctx.beginPath();ctx.moveTo(e.a.x,e.a.y);ctx.lineTo(e.b.x,e.b.y);ctx.stroke();}
  const wverts=new Map();for(const e of bnd)for(const v of[e.a,e.b])wverts.set(eKey(v,v),v);
  ctx.fillStyle='#5a4a2c';ctx.strokeStyle='#352a16';ctx.lineWidth=s;for(const v of wverts.values()){if(riverNearest(v).d<riverW*1.1)continue;ctx.beginPath();ctx.arc(v.x,v.y,3.4*s,0,7);ctx.fill();ctx.stroke();}   // башни

  // 7) река + мосты
  ctx.strokeStyle='rgba(70,120,160,.9)';ctx.lineWidth=riverW;
  ctx.beginPath();ctx.moveTo(riverPts[0].x,riverPts[0].y);for(let i=1;i<riverPts.length;i++)ctx.lineTo(riverPts[i].x,riverPts[i].y);ctx.stroke();
  ctx.strokeStyle='rgba(150,200,225,.55)';ctx.lineWidth=2.4*s;ctx.stroke();
  for(const f of[0.42,0.62]){const idx=Math.max(1,Math.min(riverPts.length-1,Math.round(riverPts.length*f)));const a=riverPts[idx-1],b=riverPts[idx];if(a.x<CX-R*1.05||a.x>CX+R*1.05)continue;drawBridge(ctx,a,b,riverW,s);}

  // 8) нумерованные медальоны ключевых мест + легенда
  marks.sort((a,b)=>a.c.y-b.c.y||a.c.x-b.c.x);
  const legend=[];
  ctx.textAlign='center';ctx.textBaseline='middle';
  marks.forEach((m,i)=>{const n=i+1,x=m.c.x,y=m.c.y;legend.push({n,name:m.name,kind:m.kind,go:m.go,id:m.id,x,y});
    ctx.save();ctx.shadowColor='rgba(0,0,0,.45)';ctx.shadowBlur=3*s;ctx.shadowOffsetY=s;
    ctx.beginPath();ctx.arc(x,y,11*s,0,7);ctx.fillStyle='rgba(245,236,212,.98)';ctx.fill();
    ctx.lineWidth=2*s;ctx.strokeStyle=m.roof;ctx.stroke();ctx.restore();
    ctx.fillStyle='#2c2113';ctx.font=`bold ${Math.round(13*s)}px Inter`;ctx.fillText(String(n),x,y+0.5*s);});

  // обрамление + хром
  const vg=ctx.createRadialGradient(CX,CY*0.95,H*0.34,CX,CY,H*0.85);vg.addColorStop(0,'rgba(0,0,0,0)');vg.addColorStop(1,'rgba(40,28,12,.3)');ctx.fillStyle=vg;ctx.fillRect(0,0,W,H);
  if(chrome){compass(ctx,W,s);cartouche(ctx,W,opts.title||'Фэндалин',s);}
  return{hits,streets,legend};
}

function drawBridge(ctx,a,b,w,s){   // деревянный мост поперёк русла
  const dx=b.x-a.x,dy=b.y-a.y,L=Math.hypot(dx,dy)||1,ux=dx/L,uy=dy/L,nx=-uy,ny=ux;
  const p={x:(a.x+b.x)/2,y:(a.y+b.y)/2},span=w*0.5+8*s,pk=Math.max(8,11*s);
  const C=(sx,sy)=>({x:p.x+nx*sx+ux*sy,y:p.y+ny*sx+uy*sy});
  const A=C(span,pk/2),B=C(-span,pk/2),D=C(-span,-pk/2),E=C(span,-pk/2);
  ctx.save();ctx.fillStyle='#9c7748';ctx.strokeStyle='#5a4222';ctx.lineWidth=1.2*s;
  ctx.beginPath();ctx.moveTo(A.x,A.y);ctx.lineTo(B.x,B.y);ctx.lineTo(D.x,D.y);ctx.lineTo(E.x,E.y);ctx.closePath();ctx.fill();ctx.stroke();
  ctx.strokeStyle='rgba(60,40,16,.5)';ctx.lineWidth=0.9*s;
  for(let kk=-span+3*s;kk<span;kk+=4.5*s){const u1=C(kk,pk/2),u2=C(kk,-pk/2);ctx.beginPath();ctx.moveTo(u1.x,u1.y);ctx.lineTo(u2.x,u2.y);ctx.stroke();}
  ctx.restore();
}
function rr(ctx,x,y,w,h,r){ctx.beginPath();ctx.moveTo(x+r,y);ctx.arcTo(x+w,y,x+w,y+h,r);ctx.arcTo(x+w,y+h,x,y+h,r);ctx.arcTo(x,y+h,x,y,r);ctx.arcTo(x,y,x+w,y,r);ctx.closePath();}
function compass(ctx,W,s=1){ctx.save();ctx.translate(W-46*s,50*s);ctx.fillStyle='rgba(233,216,175,.9)';ctx.beginPath();ctx.arc(0,0,20*s,0,7);ctx.fill();ctx.strokeStyle='#4a3415';ctx.lineWidth=s;ctx.stroke();ctx.fillStyle='#4a3415';ctx.beginPath();ctx.moveTo(0,-22*s);ctx.lineTo(4.5*s,-3*s);ctx.lineTo(-4.5*s,-3*s);ctx.fill();ctx.font=`700 ${Math.round(11*s)}px Inter`;ctx.textAlign='center';ctx.fillText('С',0,-24*s);ctx.restore();}
function cartouche(ctx,W,t,s=1){ctx.fillStyle='rgba(202,164,74,.94)';ctx.strokeStyle='#5a4222';ctx.lineWidth=1.4*s;rr(ctx,W/2-138*s,14*s,276*s,30*s,6*s);ctx.fill();ctx.stroke();ctx.fillStyle='#2c2113';ctx.font=`600 ${Math.round(15*s)}px Inter`;ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText('Город '+t,W/2,29*s);}

window.drawCity = drawCity;
