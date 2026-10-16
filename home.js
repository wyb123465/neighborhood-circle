'use strict';
const h = (selector) => document.querySelector(selector);
if (window.lucide) lucide.createIcons({ attrs: { 'stroke-width': 1.8, 'aria-hidden': 'true' } });
async function homeExample() {
  try {
    const beforeResponse = await fetch(
      '/api/communities/bridge-demo/inspection?category=' + encodeURIComponent('养老'),
    );
    if (!beforeResponse.ok) throw new Error('sample');
    const before = await beforeResponse.json(),
      candidate = before.recommendations[0];
    const afterResponse = await fetch(
      '/api/communities/bridge-demo/inspection?' +
        new URLSearchParams({
          category: '养老',
          addition_node: candidate.node,
          addition_category: candidate.category,
        }),
    );
    if (!afterResponse.ok) throw new Error('sample');
    const after = await afterResponse.json();
    h('#homeStraight').textContent = before.witness.straight_minutes;
    h('#homeNetwork').textContent = before.witness.network_minutes;
    h('#homeSampleEvidence').textContent = '离线教学路网 · 证据 ' + before.evidence_id;
    h('#homeBefore').textContent = `${before.sample_count - before.gap_count}/${before.sample_count}`;
    h('#homeAfter').textContent = `${after.sample_count - after.gap_count}/${after.sample_count}`;
    h('#homeBeforeBar').style.width = before.combined_coverage_pct + '%';
    h('#homeAfterBar').style.width = after.combined_coverage_pct + '%';
    h('#homeBeforeNote').textContent = `仍缺服务 ${before.gap_count} 个位置`;
    h('#homeAfterNote').textContent =
      `新增覆盖 ${before.gap_count - after.gap_count} 个位置，仍缺 ${after.gap_count} 个`;
  } catch {
    h('#homeSampleEvidence').textContent = '离线结果暂不可用，请检查本地服务后重试。';
  }
}
homeExample();
