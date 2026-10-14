const {test} = require('node:test');
const assert = require('node:assert/strict');
const {LocalInspectionStore, officialRouteUrl} = require('../workspace-store.js');
const storage = () => { let value = null; return {getItem:()=>value,setItem:(key,v)=>{value=v;}}; };
const job = id => ({id,status:'complete',mode:'rule-only',result:{analysis:{type:'synthetic',inspection:{mode:'synthetic',evidence_id:'s'}}}});
test('local save excludes credentials and preserves original facts while annotating',()=>{
 const s=storage(), store=new LocalInspectionStore(s), original=job('one');
 store.save(original,'检查养老',{minutes:15,AI_API_KEY:'do-not-store',session_id:'not-persisted'},null);
 assert.ok(!s.getItem().includes('do-not-store')); assert.ok(!s.getItem().includes('not-persisted'));
 store.review('one','route1','checked','入口已核对');
 assert.equal(store.get('one').reviews.route1.status,'checked');
 assert.deepEqual(store.get('one').job.result,original.result);
 store.save(original,'更新需求',{minutes:15},null);
 assert.equal(store.get('one').reviews.route1.note,'入口已核对');
});
test('corrupt storage fails safely and quota does not silently remove history',()=>{
 const store=new LocalInspectionStore({getItem:()=>'{bad'}); assert.deepEqual(store.list(),[]);
 const s=new LocalInspectionStore(storage()); for(let i=0;i<10;i++)s.save(job(String(i)),'test',{},null);
 assert.throws(()=>s.save(job('extra'),'test',{},null),/10条/); assert.equal(s.list().length,10);
 s.remove('1'); assert.equal(s.get('1'),null);
});
test('official route links encode text and reject invalid locations',()=>{
 const url=officialRouteUrl({lat:31.2,lng:121.4},{lat:31.21,lng:121.41},'上海 & city');
 assert.equal(new URL(url).hostname,'api.map.baidu.com');
 assert.equal(new URL(url).searchParams.get('region'),'上海 & city');
 assert.equal(officialRouteUrl({lat:NaN,lng:0},{lat:0,lng:0}),null);
});
