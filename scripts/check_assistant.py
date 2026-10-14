"""Five real-model scenarios. Fails explicitly when model configuration is absent."""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def run(client, payload):
    response = client.post('/api/assistant/runs', json=payload)
    response.raise_for_status()
    job = response.json()
    deadline = time.monotonic() + 270
    while job['status'] in {'queued', 'running', 'cancelling'} and time.monotonic() < deadline:
        time.sleep(.5)
        response = client.get('/api/assistant/runs/' + job['id'])
        response.raise_for_status()
        job = response.json()
    if job['status'] in {'queued', 'running', 'cancelling'}:
        client.post('/api/assistant/runs/' + job['id'] + '/cancel')
        raise RuntimeError('验收任务超时，已请求停止。')
    return job


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    parser.add_argument('--address', default='上海市长宁区愚园路')
    parser.add_argument('--city', default='上海市')
    args = parser.parse_args()
    with httpx.Client(base_url=args.base_url, timeout=30) as client:
        status = client.get('/api/assistant/status').json()
        if not status.get('configured'):
            print('真实模型验收尚未开始：请填写本地模型配置，并以 assistant 模式启动。')
            return 2
        session = None
        rows = []
        cases = [
            ('含糊需求追问', {'task': '帮我看看', 'data_mode': 'live'}, 'needs_input'),
            ('合成体检与候选比较', {'task': '检查养老服务缺口，比较前两个候选方案，并说明依据。'}, 'complete'),
            ('同条件追问复用', {'task': '解释刚才的证据与口径限制。'}, 'complete'),
            ('改变时间重新计算', {'task': '改为20分钟，重新检查养老服务缺口。', 'minutes': 20}, 'complete'),
            ('真实地图与候选比较', {'task': '检查医疗、养老、教育、购物四类设施，并比较菜市场候选参考点。', 'data_mode': 'live', 'address': args.address, 'city': args.city}, 'complete'),
        ]
        for index, (name, payload, expected) in enumerate(cases):
            if index in (2, 3) and session:
                payload['session_id'] = session
            job = run(client, payload)
            if index == 1:
                session = job['session_id']
            result = job.get('result') or {}
            passed = job['status'] == expected and job['mode'] == 'llm-agent' and job['model_called']
            if index == 0:
                passed = passed and bool(result.get('question')) and job['map_requests'] == 0
            if index == 1:
                passed = passed and len(result.get('comparison', [])) == 2
            if index == 2:
                passed = passed and job['map_requests'] == 0 and any(e.get('name') == 'read_evidence' for e in job['events'])
            if index == 3:
                passed = passed and (result.get('analysis') or {}).get('inspection', {}).get('parameters', {}).get('minutes') == 20
            analysis = result.get('analysis') or {}
            source = analysis.get('inspection', {}).get('mode')
            if index == 4:
                passed = passed and source in {'live-partial', 'live-replay'}
            rows.append({'case': name, 'passed': bool(passed), 'status': job['status'], 'mode': job['mode'], 'data_source': source, 'model_calls': job['model_calls'], 'map_requests': job['map_requests'], 'events': job['events'], 'error': job['error'], 'facts': result.get('facts', [])})
            print(f"{'通过' if passed else '未通过'}：{name}；模型 {job['model_calls']} 轮，地图新请求 {job['map_requests']} 次。", flush=True)
    path = ROOT / '.runtime/assistant-validation.json'
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({'checked_at': datetime.now().astimezone().isoformat(timespec='seconds'), 'cases': rows, 'note': '回放地图与实时地图分别标注；仅模型调用均成功不等于真实地图当前状态已验证。'}, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if all(r['passed'] for r in rows) else 1


if __name__ == '__main__':
    raise SystemExit(main())
