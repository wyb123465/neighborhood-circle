/* One owner per run; late responses are cancelled and cannot replace current UI. */
(function (root) {
  class AssistantRunController {
    constructor(fetcher, update) {
      this.fetcher = fetcher;
      this.update = update;
      this.sequence = 0;
      this.id = null;
      this.session = null;
      this.timer = null;
    }
    async request(url, body) {
      const response = await this.fetcher(
        url,
        body === undefined
          ? {}
          : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) },
      );
      const data = await response.json();
      if (!response.ok)
        throw new Error(typeof data.detail === 'string' ? data.detail : '请求参数或服务响应不可用。');
      return data;
    }
    async stop(reset = false) {
      this.sequence++;
      clearTimeout(this.timer);
      const id = this.id;
      this.id = null;
      if (reset || id) this.session = null;
      if (id) await this.request(`/api/assistant/runs/${id}/cancel`, {});
    }
    async start(payload) {
      const sequence = ++this.sequence;
      clearTimeout(this.timer);
      try {
        const job = await this.request('/api/assistant/runs', {
          ...payload,
          ...(this.session ? { session_id: this.session } : {}),
        });
        if (sequence !== this.sequence) {
          await this.request(`/api/assistant/runs/${job.id}/cancel`, {});
          return;
        }
        this.id = job.id;
        this.session = job.session_id;
        const poll = async (value) => {
          if (sequence !== this.sequence) return;
          this.update(value);
          if (!['queued', 'running', 'cancelling'].includes(value.status)) {
            this.id = null;
            return;
          }
          this.timer = setTimeout(async () => {
            try {
              const next = await this.request(`/api/assistant/runs/${job.id}`);
              await poll(next);
            } catch (error) {
              if (sequence === this.sequence) {
                this.update({ status: 'connection-error', error: error.message });
              }
            }
          }, 600);
        };
        await poll(job);
      } catch (error) {
        if (sequence === this.sequence) this.update({ status: 'error', error: error.message });
      }
    }
  }
  if (typeof module !== 'undefined') module.exports = { AssistantRunController };
  else root.AssistantRunController = AssistantRunController;
})(typeof window !== 'undefined' ? window : globalThis);
