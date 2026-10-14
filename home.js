"use strict";
const h = selector => document.querySelector(selector);
if (window.lucide) lucide.createIcons({attrs:{'stroke-width':1.8,'aria-hidden':'true'}});
function svgNode(tag, attributes) { const node=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [key,value]of Object.entries(attributes))node.setAttribute(key,String(value));return node; }
async function homeExample() {
  try {
    const beforeResponse=await fetch('/api/communities/bridge-demo/inspection?category='+encodeURIComponent('养老'));
    if(!beforeResponse.ok)throw new Error('sample');const before=await beforeResponse.json();
    const candidate=before.recommendations[0];
    const afterResponse=await fetch('/api/communities/bridge-demo/inspection?'+new URLSearchParams({category:'养老',addition_node:candidate.node,addition_category:candidate.category}));
    if(!afterResponse.ok)throw new Error('sample');const after=await afterResponse.json();
    h('#homeStraight').textContent=before.witness.straight_minutes;h('#homeNetwork').textContent=before.witness.network_minutes;
    h('#homeEvidence').textContent='合成路网 · 证据 '+before.evidence_id;
    h('#homeBefore').textContent=before.combined_coverage_pct+'%';h('#homeAfter').textContent=after.combined_coverage_pct+'%';
    h('#homeBeforeBar').style.width=before.combined_coverage_pct+'%';h('#homeAfterBar').style.width=after.combined_coverage_pct+'%';
    h('#homeBeforeNote').textContent=`缺口 ${before.gap_count}/${before.sample_count} 个样点`;
    h('#homeAfterNote').textContent=`独立新增 ${before.gap_count-after.gap_count} 个样点 · 剩余缺口 ${after.gap_count}`;
    const nodes=new Map(before.map.nodes.map(n=>[n.id,n])),xy=n=>[45+n.x*.31,455-n.y*.25],svg=h('#homeRoute');
    svg.replaceChildren();
    // Draw only existing adjacent road edges; the witness supplies the actual crossings.
    for(const n of nodes.values()){
      const [x,y]=xy(n);svg.append(svgNode('rect',{x:x-19,y:y-15,width:38,height:30,rx:4,fill:n.gap?'#f3e5e1':'#e1eee5'}));
    }
    const riverX=45+(6.5*160)*.31;svg.append(svgNode('path',{d:`M${riverX} 20V490`,stroke:'#d8e6eb','stroke-width':24,fill:'none'}));
    const path=before.witness.path.map(id=>xy(nodes.get(id)).join(',')).join(' ');
    svg.append(svgNode('polyline',{points:path,fill:'none',stroke:'#247254','stroke-width':4,'stroke-linejoin':'round','stroke-linecap':'round'}));
    for(const id of [before.witness.from,before.witness.to]){const[x,y]=xy(nodes.get(id));svg.append(svgNode('circle',{cx:x,cy:y,r:8,fill:'#247254',stroke:'white','stroke-width':3}));}
  } catch { h('#homeEvidence').textContent='合成证据暂不可用，请检查本地服务后重试。'; }
}
homeExample();
