"""Build the single-file dynamic HTML page from the .xlsx data and the bulletin cache."""
import datetime as dt
import json

from . import data, model

START = dt.date(2005, 1, 1)


def _months(end):
    d, out = START, []
    while d <= end:
        out.append(d)
        d = model.add_months(d, 1)
    return out


def build(out_path, data_dir, bulletins):
    invs = data.load_inventories(data_dir)
    if not invs:
        raise SystemExit("No eb_inventory_*.xlsx files found in %s" % data_dir)
    inv, aw, q485 = invs[-1], data.load_awaiting(data_dir), data.load_i485_quarterly(data_dir)
    as_of = inv["as_of"]
    months = _months(dt.date(as_of.year, as_of.month, 1))
    grid, curves, cutoffs = {}, {}, {}
    fm, dm = model.latest_month(bulletins, "fad"), model.latest_month(bulletins, "dff")
    for cat in model.CATEGORIES:
        for c in model.COUNTRIES:
            key = cat + "|" + c
            by = {}
            for r in inv["rows"]:
                if r["country"] == c and (r["category"] in (["EB4", "CRW"] if cat in ("EB4", "CRW") else [cat])):
                    by[model._row_date(r)] = by.get(model._row_date(r), 0) + r["count"]
            if by:
                curves[key] = [[d.isoformat()[:7], n] for d, n in sorted(by.items())]
            cutoffs[key] = [model.cell(bulletins, fm, "fad", cat, c) if fm else None,
                            model.cell(bulletins, dm, "dff", cat, c) if dm else None]
            row = []
            for d in months:
                r = model.estimate(cat, c, d, bulletins, inv, aw)
                h = r["headline"]
                if h["status"] == "waiting":
                    row.append([h["early"][:7], h["base"][:7], h["late"][:7], h["confidence"],
                                (h.get("filing_base") or "")[:7], 1 if h["methods_agree"] is False else 0])
                else:
                    row.append(0 if h["status"] == "current" else None)
            grid[key] = row
    payload = {
        "asOf": as_of.isoformat(), "start": START.isoformat()[:7], "months": len(months),
        "bulletinFad": fm, "bulletinDff": dm, "cutoffs": cutoffs, "grid": grid, "curves": curves,
        "awaiting": aw, "awaitingAsOf": aw["as_of"] if aw else None,
        "inventories": [{"asOf": i["as_of"].isoformat(), "file": i["file"]} for i in invs],
        "i485": q485, "assumptions": {k: v for k, v in model.DEFAULT_ASSUMPTIONS.items()},
        "generated": dt.date.today().isoformat(),
    }
    html = TEMPLATE.replace("/*DATA*/null", json.dumps(payload, separators=(",", ":"), default=str))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>When will my employment-based priority date become current?</title>
<style>
:root{color-scheme:light;--bg:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;--s1:#2a78d6;--s2:#eb6834;--wash:rgba(42,120,214,.10);--ring:rgba(11,11,11,.10);--warn:#fab219}
@media (prefers-color-scheme:dark){:root{color-scheme:dark;--bg:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--grid:#2c2c2a;--axis:#383835;--s1:#3987e5;--s2:#d95926;--ring:rgba(255,255,255,.10)}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:980px;margin:0 auto;padding:24px 16px 64px}h1{font-size:24px;margin:0 0 4px}h2{font-size:17px;margin:0 0 8px}
.sub{color:var(--ink2);margin:0 0 20px}.card{background:var(--surface);border:1px solid var(--ring);border-radius:10px;padding:16px;margin:0 0 16px}
.controls{display:flex;flex-wrap:wrap;gap:12px;align-items:end}label{display:flex;flex-direction:column;font-size:13px;color:var(--ink2);gap:4px}
select,input{font:inherit;padding:6px 8px;border:1px solid var(--axis);border-radius:6px;background:var(--surface);color:var(--ink)}
.hero{font-size:34px;font-weight:600;margin:4px 0}.range{color:var(--ink2)}.pill{display:inline-block;padding:1px 8px;border-radius:99px;border:1px solid var(--axis);font-size:12px;color:var(--ink2)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media(max-width:760px){.grid2{grid-template-columns:1fr}}
svg{width:100%;height:auto;display:block}.tick{fill:var(--muted);font-size:11px}.lab{fill:var(--ink2);font-size:12px}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:4px 8px;text-align:right;border-bottom:1px solid var(--grid)}th:first-child,td:first-child{text-align:left}
.note{font-size:13px;color:var(--ink2)}.warn{border-left:3px solid var(--warn);padding-left:10px}
#tip{position:fixed;pointer-events:none;background:var(--surface);border:1px solid var(--axis);border-radius:6px;padding:4px 8px;font-size:12px;display:none}
details{margin-top:8px}.key i{display:inline-block;width:10px;height:10px;border-radius:50%;margin:0 4px 0 12px;vertical-align:middle}
</style></head><body><main>
<h1>When will my employment-based priority date become current?</h1>
<p class="sub" id="sub"></p>
<div class="card"><div class="controls">
<label>Category<select id="cat"></select></label>
<label>Country of chargeability<select id="country"></select></label>
<label>Priority date<input id="pd" type="date" value="2014-06-15"></label></div></div>
<div class="card" id="result" aria-live="polite"></div>
<div class="grid2">
<div class="card"><h2>People ahead of you in line</h2><div id="c1"></div><p class="note" id="c1n"></p></div>
<div class="card"><h2>Visa bulletin cutoffs</h2><div id="c2"></div><p class="note" id="c2n"></p></div></div>
<div class="grid2">
<div class="card"><h2>Approved petitions still waiting (June 2026)</h2><div id="c3"></div><p class="note">Principals only; includes people who have not yet filed an I-485.</p></div>
<div class="card"><h2>Employment-based I-485 decisions, FY2026</h2><div id="c4"></div><p class="note">National totals, no category or country split.</p></div></div>
<div class="card"><h2>What the data says</h2><div id="story"></div></div>
<div class="card"><h2>How the estimate works</h2><div class="note">
<p><b>Queue method.</b> People ahead of your priority date (pending I-485 inventory, plus approved petitions that have not yet filed) divided by the visas the law makes available to your category and country each year. Early / base / late cases vary family size, drop-out, and how many unused numbers spill over from other countries.</p>
<p><b>Limits.</b> The inventory excludes consular cases, people yet to file, and masks counts of 1&ndash;10 (&ldquo;D&rdquo;, treated as 5). India EB-2/EB-3 inventory stops at early 2015, so later India dates lean on petition totals. Dependents are not stated in the inventory. Annual limits and supply assumptions are listed below and can be changed in the command-line tool.</p>
<p><b>Not legal advice.</b> Dates move with demand, policy and law. Treat this as a planning range, not a prediction.</p>
<details><summary>Assumptions used</summary><pre id="assump" style="white-space:pre-wrap"></pre></details>
<details><summary>Table view of the selected line</summary><div id="tbl"></div></details></div></div>
<div id="tip"></div></main>
<script>
const D=/*DATA*/null;
const CATS={EB1:"EB-1 Priority workers",EB2:"EB-2 Advanced degree",EB3:"EB-3 Skilled & professional",EW3:"EB-3 Other workers",EB4:"EB-4 Special immigrants",CRW:"EB-4 Religious workers","EB5-UNRESERVED":"EB-5 Unreserved","EB5-RURAL":"EB-5 Rural set-aside","EB5-HIGH-UNEMPLOYMENT":"EB-5 High unemployment","EB5-INFRASTRUCTURE":"EB-5 Infrastructure"};
const CTRY={India:"India",China:"China (mainland born)",Mexico:"Mexico",Philippines:"Philippines",ROW:"All other countries"};
const $=id=>document.getElementById(id), NS="http://www.w3.org/2000/svg";
const fm=(m,o)=>{if(!m)return"n/a";const[y,mo]=m.split("-");return y>2100?"after 2100":new Date(+y,+mo-1,1).toLocaleDateString("en-US",{month:"short",year:"numeric"})};
const fc=v=>v==="C"?"Current":v==="U"?"Unavailable":!v?"n/a":fm(v.slice(0,7))+" ("+v.slice(8)+")";
const num=n=>Math.round(n).toLocaleString("en-US");
for(const[k,v]of Object.entries(CATS))$("cat").add(new Option(v,k));
for(const[k,v]of Object.entries(CTRY))$("country").add(new Option(v,k));
$("cat").value="EB2";$("country").value="India";
$("sub").textContent=`Built from USCIS data: pending I-485 inventory as of ${D.asOf}, approved petitions as of ${D.awaitingAsOf}, visa bulletin cutoffs (final action ${D.bulletinFad||"n/a"}, filing ${D.bulletinDff||"n/a"}). Page generated ${D.generated}.`;
function el(t,a,p){const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);p&&p.appendChild(e);return e}
function tip(e,t){const T=$("tip");T.textContent=t;T.style.display="block";T.style.left=Math.min(e.clientX+12,innerWidth-220)+"px";T.style.top=(e.clientY+12)+"px"}
const hide=()=>$("tip").style.display="none";
function chart(id,W,H){const s=el("svg",{viewBox:`0 0 ${W} ${H}`,role:"img"});$(id).replaceChildren(s);return s}
function css(v){return getComputedStyle(document.documentElement).getPropertyValue(v)}
function render(){
 const cat=$("cat").value,c=$("country").value,key=cat+"|"+c,pdFull=$("pd").value||"2014-06-15",pdv=pdFull.slice(0,7);
 const[y0,m0]=D.start.split("-").map(Number),[py,pm,pdd]=pdFull.split("-").map(Number);
 const idx=(py-y0)*12+(pm-1),row=D.grid[key],A=idx<0?0:row[Math.min(idx,row.length-1)],NX=idx<0?0:row[Math.min(idx+1,row.length-1)];
 const mnum=m=>{const[a,b]=m.split("-").map(Number);return a*12+b-1},mstr=n=>{n=Math.round(n);return Math.floor(n/12)+"-"+String(n%12+1).padStart(2,"0")};
 const dim=new Date(py,pm,0).getDate(),fr=(pdd-1)/dim,fadv=D.cutoffs[key][0];
 const notYet=typeof fadv==="string"&&/^\d{4}-\d\d-\d\d$/.test(fadv)&&pdFull>=fadv;
 let g=A;
 if(A===0&&notYet&&Array.isArray(NX))g=NX;               // day-level cutoff says not current yet
 else if(Array.isArray(A)&&Array.isArray(NX))g=[0,1,2].map(i=>mstr(mnum(A[i])+fr*(mnum(NX[i])-mnum(A[i])))).concat(A.slice(3));
 const[fad,dff]=D.cutoffs[key];let h="";
 if(g===0)h=`<div class="hero">Current now</div><div class="range">Your priority date is earlier than the final action cutoff, or the inventory shows it as available.</div>`;
 else if(!g)h=`<div class="hero">No estimate</div><div class="range">Not enough data for this combination.</div>`;
 else{const yrs=((Date.UTC(+g[1].slice(0,4),+g[1].slice(5,7)-1)-Date.UTC(...D.asOf.split("-").slice(0,2).map((v,i)=>i?+v-1:+v)))/31557600000).toFixed(1);
  h=`<div class="range">Estimated final action date</div><div class="hero">${fm(g[1])}</div><div class="range">Range ${fm(g[0])} to ${fm(g[2])} &middot; about ${yrs} years from the data date <span class="pill">confidence ${g[3]}</span>${g[5]?' <span class="pill">methods disagree</span>':''}</div>`;
  if(g[4])h+=`<div class="range">Filing eligibility (Dates for Filing chart) around ${fm(g[4])}</div>`;
  if(+g[1].slice(0,4)>2060)h+=`<p class="note warn">A wait this long means the line does not clear under current law. A change in law or policy would dominate this estimate.</p>`}
 h+=`<p class="note">Today&rsquo;s cutoffs: final action ${fc(fad)}; dates for filing ${fc(dff)}. Estimates are interpolated by day between monthly values.</p>`;
 $("result").innerHTML=h;
 // chart 1: cumulative people ahead
 const cur=D.curves[key]||[];let run=0;const pts=cur.map(([m,n])=>[m,run+=n]);
 const s1=chart("c1",440,260),L=48,R=12,T=12,B=30,w=440-L-R,hh=260-T-B;
 if(pts.length){const tot=pts[pts.length-1][1],mi=m=>{const[a,b]=m.split("-").map(Number);return a*12+b-1};
  const lo=mi(pts[0][0]),hi=Math.max(mi(pts[pts.length-1][0]),mi(pdv)),X=m=>L+(mi(m)-lo)/Math.max(1,hi-lo)*w,Y=v=>T+hh-v/tot*hh;
  for(let i=0;i<=4;i++){const v=tot*i/4;el("line",{x1:L,x2:L+w,y1:Y(v),y2:Y(v),stroke:css("--grid")},s1);el("text",{x:L-6,y:Y(v)+4,"text-anchor":"end",class:"tick"},s1).textContent=num(v)}
  const d=pts.map(([m,v],i)=>(i?"L":"M")+X(m)+","+Y(v)).join("");
  el("path",{d:d+`L${X(pts[pts.length-1][0])},${T+hh}L${X(pts[0][0])},${T+hh}Z`,fill:css("--wash")},s1);
  el("path",{d,fill:"none",stroke:css("--s1"),"stroke-width":2,"stroke-linejoin":"round"},s1);
  const ys=new Set(pts.map(p=>+p[0].slice(0,4)));[...ys].filter((_,i)=>i%Math.ceil(ys.size/6)==0).forEach(yy=>el("text",{x:X(yy+"-01"),y:T+hh+16,"text-anchor":"middle",class:"tick"},s1).textContent=yy);
  const xp=X(pdv),ahead=pts.filter(p=>p[0]<pdv).pop(),av=ahead?ahead[1]:0;
  el("line",{x1:xp,x2:xp,y1:T,y2:T+hh,stroke:css("--s2"),"stroke-width":2},s1);
  el("circle",{cx:xp,cy:Y(av),r:5,fill:css("--s2"),stroke:css("--surface"),"stroke-width":2},s1);
  el("text",{x:Math.min(xp+6,L+w-90),y:T+12,class:"lab"},s1).textContent="You: "+num(av)+" ahead";
  const hit=el("rect",{x:L,y:T,width:w,height:hh,fill:"transparent"},s1);
  hit.onmousemove=e=>{const r=s1.getBoundingClientRect(),f=((e.clientX-r.left)/r.width*440-L)/w,m=Math.round(lo+f*(hi-lo)),k=pts.filter(p=>mi(p[0])<=m).pop();k&&tip(e,fm(k[0])+": "+num(k[1])+" applications at or before this month")};hit.onmouseleave=hide;
  $("c1n").textContent=`${num(tot)} pending I-485 applications in this category and country. Cumulative count by priority-date month (inventory as of ${D.asOf}); small counts masked by USCIS are assumed to be 5.`}
 else $("c1n").textContent="No pending I-485 applications appear in the inventory for this combination.";
 // chart 2: cutoffs for every country in this category
 const s2=chart("c2",440,260);const cs=Object.keys(CTRY);let ty=22;
 el("text",{x:150,y:12,class:"tick","text-anchor":"end"},s2).textContent="";
 [["Final action",0],["Dates for filing",1]].forEach(([nm,j],ci)=>{el("circle",{cx:155+ci*150,cy:10,r:5,fill:css(ci?"--s2":"--s1")},s2);el("text",{x:165+ci*150,y:14,class:"lab"},s2).textContent=nm});
 cs.forEach((k,i)=>{const y=40+i*42;el("text",{x:0,y:y+4,class:"lab"},s2).textContent=CTRY[k].replace(" (mainland born)","");
  D.cutoffs[cat+"|"+k].forEach((v,j)=>{const t=el("text",{x:150+j*150,y:y+4,class:"tick"},s2);t.textContent=fc(v);t.style.fill=k===c?css("--ink"):css("--muted");t.style.fontWeight=k===c?"600":"400"})});
 $("c2n").textContent="Latest cutoffs in the cached bulletins. A date means priority dates earlier than it qualify. The selected country is in bold.";
 // chart 3: awaiting by country for category
 const ak=cat.startsWith("EB5")?"EB5-UNRESERVED":(cat==="CRW"?"CRW":cat),s3=chart("c3",440,230);
 const av3=Object.keys(CTRY).map(k=>[k,(D.awaiting&&D.awaiting.counts[k]||{})[ak]||0]),mx=Math.max(1,...av3.map(a=>a[1]));
 av3.forEach(([k,v],i)=>{const y=10+i*42,bw=Math.max(1,v/mx*230);el("text",{x:0,y:y+15,class:"lab"},s3).textContent=CTRY[k].replace(" (mainland born)","");
  const b=el("path",{d:`M130,${y}h${Math.max(0,bw-4)}a4,4 0 0 1 4,4v14a4,4 0 0 1 -4,4h-${Math.max(0,bw-4)}z`,fill:k===c?css("--s2"):css("--s1")},s3);
  el("text",{x:130+bw+6,y:y+17,class:"lab"},s3).textContent=num(v);b.onmousemove=e=>tip(e,CTRY[k]+": "+num(v));b.onmouseleave=hide});
 // chart 4: i485 quarterly
 const s4=chart("c4",440,230),q=D.i485,qm=Math.max(...q.map(x=>Math.max(x.approved,x.received)));
 q.forEach((x,i)=>{const bx=40+i*130;[["received","--s2"],["approved","--s1"]].forEach(([f,col],j)=>{const bh=x[f]/qm*170,xx=bx+j*40;
  const r=el("path",{d:`M${xx},${200}v-${Math.max(0,bh-4)}a4,4 0 0 1 4,-4h32a4,4 0 0 1 4,4v${Math.max(0,bh-4)}z`,fill:css(col)},s4);r.onmousemove=e=>tip(e,"FY"+x.fy+" Q"+x.q+" "+f+": "+num(x[f]));r.onmouseleave=hide;
  el("text",{x:xx+20,y:200-bh-6,"text-anchor":"middle",class:"tick"},s4).textContent=num(x[f])});
  el("text",{x:bx+40,y:218,"text-anchor":"middle",class:"lab"},s4).textContent="Q"+x.q});
 el("circle",{cx:250,cy:10,r:5,fill:css("--s2")},s4);el("text",{x:260,y:14,class:"lab"},s4).textContent="Received";el("circle",{cx:330,cy:10,r:5,fill:css("--s1")},s4);el("text",{x:340,y:14,class:"lab"},s4).textContent="Approved";
 // story
 const aw=D.awaiting.counts,tot=D.awaiting&&Object.values(aw).reduce((a,r)=>a+Object.values(r).reduce((x,y)=>x+y,0),0);
 const ind=aw.India,top=Object.entries(CTRY).map(([k])=>[k,Object.values(aw[k]).reduce((a,b)=>a+b,0)]).sort((a,b)=>b[1]-a[1])[0];
 const q3=q[q.length-1];
 $("story").innerHTML=`<p>USCIS reports ${num(tot)} approved employment-based petitions waiting for a visa as of ${D.awaitingAsOf}. India alone accounts for ${num(Object.values(ind).reduce((a,b)=>a+b,0))}, of which ${num(ind.EB2)} are EB-2 and ${num(ind.EB3)} are EB-3. Because each country is limited to 7% of visas, those lines move slowly while the rest of the world moves much faster.</p>
 <p>Employment-based I-485 approvals ran at ${num(q[0].approved)}, ${num(q[1].approved)} and ${num(q3.approved)} in the first three quarters of FY2026, while receipts were ${num(q[0].received)}, ${num(q[1].received)} and ${num(q3.received)}. Pending employment-based I-485s stood at ${num(q3.pending)} at the end of Q${q3.q}.</p>
 <p>For your selection (${CATS[cat]}, ${CTRY[c]}) the inventory lists ${num(cur.reduce((a,b)=>a+b[1],0))} pending applications. Move the priority date to see how many are ahead of you and how the estimate changes.</p>`;
 $("assump").textContent=JSON.stringify(D.assumptions,null,1);
 $("tbl").innerHTML="<table><tr><th>Priority-date month</th><th>Applications</th><th>Cumulative</th></tr>"+(()=>{let r=0;return cur.map(([m,n])=>`<tr><td>${m}</td><td>${num(n)}</td><td>${num(r+=n)}</td></tr>`).join("")})()+"</table>";
}
["cat","country","pd"].forEach(i=>$(i).addEventListener("input",render));render();
</script></body></html>
"""
