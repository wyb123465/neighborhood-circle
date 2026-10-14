/* Local records use an explicit allowlist; no model/map credentials are persisted. */
(function (root) {
  const KEY = 'neighborhood.inspections.v1';
  const clone = value => JSON.parse(JSON.stringify(value));
  class LocalInspectionStore {
    constructor(storage) { this.storage = storage; }
    list() {
      try { const value = JSON.parse(this.storage.getItem(KEY) || '{}'); return value.version === 1 && Array.isArray(value.records) ? value.records.filter(r => r && typeof r.id === 'string' && r.job?.result?.analysis).slice(0, 10) : []; }
      catch { return []; }
    }
    write(records) {
      const value = JSON.stringify({ version: 1, records });
      if (value.length > 1000000) throw new Error('本机记录空间不足，请先导出或删除较早记录。');
      this.storage.setItem(KEY, value);
    }
    save(job, task, request, scenarios) {
      if (!job?.result?.analysis || !['complete', 'partial'].includes(job.status)) throw new Error('当前没有可保存的完整体检证据。');
      const records = this.list(), previous = records.find(r => r.id === job.id);
      if (!previous && records.length >= 10) throw new Error('已保存10条体检，请先导出或删除较早记录。');
      const input = {}; for (const key of ['data_mode', 'community_id', 'address', 'city', 'minutes', 'speed']) if (key in request) input[key] = request[key];
      const value = clone({ id: job.id, created_at: previous?.created_at || new Date().toISOString(), updated_at: new Date().toISOString(), task: String(task).slice(0, 1000), request: input, scenarios,
        reviews: previous?.reviews || {}, job: { id: job.id, status: job.status, mode: job.mode, model_calls: job.model_calls, tool_calls: job.tool_calls, map_requests: job.map_requests, map_request_budget: job.map_request_budget, events: job.events || [], result: job.result, error: job.error } });
      this.write([value, ...records.filter(r => r.id !== job.id)]); return value;
    }
    get(id) { return this.list().find(r => r.id === id) || null; }
    review(id, key, status, note) {
      if (!['pending', 'checked', 'excluded'].includes(status)) throw new Error('核验状态无效。');
      const records = this.list(), record = records.find(r => r.id === id);
      if (!record) throw new Error('请先保存本次体检。');
      record.reviews[key] = { status, note: String(note).slice(0, 500), updated_at: new Date().toISOString() };
      this.write(records); return record.reviews[key];
    }
    remove(id) { this.write(this.list().filter(r => r.id !== id)); }
  }
  function officialRouteUrl(origin, destination, city = '') {
    for (const p of [origin, destination]) if (!p || !Number.isFinite(p.lat) || !Number.isFinite(p.lng) || Math.abs(p.lat) > 85 || Math.abs(p.lng) > 180) return null;
    const params = new URLSearchParams({ origin: 'latlng:' + origin.lat + ',' + origin.lng + '|name:体检中心', destination: 'latlng:' + destination.lat + ',' + destination.lng + '|name:核验终点', mode: 'walking', coord_type: 'bd09ll', output: 'html', src: 'webapp.neighborhood-circle.demo' });
    if (typeof city === 'string' && city.trim()) params.set('region', city.trim());
    return 'https://api.map.baidu.com/direction?' + params;
  }
  if (typeof module !== 'undefined') module.exports = { LocalInspectionStore, officialRouteUrl };
  else { root.LocalInspectionStore = LocalInspectionStore; root.officialRouteUrl = officialRouteUrl; }
})(typeof window !== 'undefined' ? window : globalThis);
