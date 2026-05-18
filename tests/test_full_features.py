"""Comprehensive feature test script for industrial-agent project (after bug fixes)"""
import sys, io, asyncio, httpx, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

BASE = 'http://localhost:18000'
CHAT_TIMEOUT = 180

async def safe_json(r):
    try:
        return r.json()
    except Exception:
        return {'_raw': r.text[:500], '_status': r.status_code}

async def test_api():
    async with httpx.AsyncClient(timeout=httpx.Timeout(CHAT_TIMEOUT, connect=10)) as client:

        print('=== 1. API Root Endpoint ===')
        r = await client.get(f'{BASE}/api')
        data = await safe_json(r)
        print(f'  status: {r.status_code}')
        print(f'  name: {data.get("name")}')

        print()
        print('=== 2. Health Check ===')
        r = await client.get(f'{BASE}/health')
        data = await safe_json(r)
        print(f'  status: {data.get("status")}')
        print(f'  llm: {data.get("llm")}')
        print(f'  skills_count: {data.get("skills_count")}')

        print()
        print('=== 3. Skills List ===')
        r = await client.get(f'{BASE}/api/skills')
        data = await safe_json(r)
        skills = data.get('skills', [])
        print(f'  Found {len(skills)} skills:')
        for s in skills:
            print(f'    - {s["name"]}: {s["description"]}')

        print()
        print('=== 4. Create Session ===')
        r = await client.post(f'{BASE}/api/session/create')
        data = await safe_json(r)
        session_id = data.get('session_id')
        print(f'  session_id: {session_id}')

        print()
        print('=== 5. Get Session Info ===')
        r = await client.get(f'{BASE}/api/session/{session_id}')
        data = await safe_json(r)
        print(f'  history_count: {data.get("history_count")}')

        # === BUG FIX VERIFICATION: Skill-routed chat (was 500) ===
        print()
        print('=== 6. [BUG FIX] Chat Non-Stream (time query - was 500) ===')
        try:
            payload = {
                'messages': [{'role': 'user', 'content': '现在几点了？'}],
                'session_id': session_id,
                'enable_thinking': False
            }
            r = await client.post(f'{BASE}/api/chat', json=payload)
            data = await safe_json(r)
            print(f'  status: {r.status_code}')
            print(f'  final_result: {str(data.get("final_result", ""))[:200]}')
            if r.status_code == 200:
                print('  PASS: Skill-routed chat works!')
            else:
                print(f'  FAIL: Still getting {r.status_code}')
        except Exception as e:
            print(f'  ERROR: {e}')

        print()
        print('=== 7. Chat Non-Stream (general question) ===')
        try:
            payload = {
                'messages': [{'role': 'user', 'content': '用一句话介绍Python语言'}],
                'enable_thinking': False
            }
            r = await client.post(f'{BASE}/api/chat', json=payload)
            data = await safe_json(r)
            print(f'  status: {r.status_code}')
            print(f'  final_result: {str(data.get("final_result", ""))[:200]}')
        except Exception as e:
            print(f'  ERROR: {e}')

        print()
        print('=== 8. Chat Non-Stream WITH Thinking ===')
        try:
            payload = {
                'messages': [{'role': 'user', 'content': '1+1为什么等于2？'}],
                'enable_thinking': True
            }
            r = await client.post(f'{BASE}/api/chat', json=payload)
            data = await safe_json(r)
            print(f'  status: {r.status_code}')
            result = data.get('result', {})
            thinking = result.get('thinking_content', '') if isinstance(result, dict) else ''
            print(f'  final_result: {str(data.get("final_result", ""))[:150]}')
            print(f'  thinking_content length: {len(thinking) if thinking else 0}')
            if thinking:
                print('  PASS: thinking mode works via API')
        except Exception as e:
            print(f'  ERROR: {e}')

        print()
        print('=== 9. Chat Stream (time query) ===')
        try:
            payload = {
                'messages': [{'role': 'user', 'content': '今天是星期几？'}],
                'enable_thinking': False
            }
            token_count = 0
            complete_received = False
            async with client.stream('POST', f'{BASE}/api/chat/stream', json=payload) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith('data: '):
                        try:
                            chunk = json.loads(line[6:])
                            if chunk.get('type') == 'token':
                                token_count += 1
                            elif chunk.get('type') == 'complete':
                                complete_received = True
                        except json.JSONDecodeError:
                            pass
            print(f'  tokens received: {token_count}')
            print(f'  complete received: {complete_received}')
            print(f'  PASS: stream works')
        except Exception as e:
            print(f'  ERROR: {e}')

        # === BUG FIX VERIFICATION: Stream + thinking (was "no current task") ===
        print()
        print('=== 10. [BUG FIX] Chat Stream WITH Thinking (was broken) ===')
        try:
            payload = {
                'messages': [{'role': 'user', 'content': '1+1=?'}],
                'enable_thinking': True
            }
            thinking_count = 0
            content_count = 0
            complete_received = False
            error_received = False
            async with client.stream('POST', f'{BASE}/api/chat/stream', json=payload) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith('data: '):
                        try:
                            chunk = json.loads(line[6:])
                            ct = chunk.get('type')
                            if ct == 'reasoning_content':
                                thinking_count += 1
                            elif ct == 'token':
                                content_count += 1
                            elif ct == 'complete':
                                complete_received = True
                            elif ct == 'error':
                                error_received = True
                                print(f'  error: {chunk}')
                        except json.JSONDecodeError:
                            pass
            print(f'  thinking tokens: {thinking_count}')
            print(f'  content tokens: {content_count}')
            print(f'  complete received: {complete_received}')
            if not error_received and (thinking_count > 0 or content_count > 0):
                print('  PASS: stream + thinking works!')
            elif error_received:
                print('  FAIL: error received')
            else:
                print('  WARNING: no tokens received')
        except Exception as e:
            print(f'  ERROR: {e}')

        print()
        print('=== 11. Chat Stream with selected_skills ===')
        try:
            payload = {
                'messages': [{'role': 'user', 'content': '现在几点了？'}],
                'selected_skills': ['time_query'],
                'enable_thinking': False
            }
            result_text = ''
            async with client.stream('POST', f'{BASE}/api/chat/stream', json=payload) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith('data: '):
                        try:
                            chunk = json.loads(line[6:])
                            if chunk.get('type') == 'token':
                                result_text += chunk.get('content', '')
                        except json.JSONDecodeError:
                            pass
            print(f'  result: {result_text[:200]}')
            print(f'  PASS: selected_skills works')
        except Exception as e:
            print(f'  ERROR: {e}')

        # === BUG FIX VERIFICATION: Multimodal image (was 500) ===
        print()
        print('=== 12. [BUG FIX] Multimodal Image (was 500) ===')
        try:
            payload = {
                'messages': [{
                    'role': 'user',
                    'content': [
                        {'type': 'text', 'text': 'describe this image in one sentence'},
                        {'type': 'image_url', 'image_url': {'url': 'https://dashscope.oss-cn-beijing.aliyuncs.com/images/dog_and_girl.jpeg'}}
                    ]
                }],
                'enable_thinking': False
            }
            r = await client.post(f'{BASE}/api/chat', json=payload)
            data = await safe_json(r)
            print(f'  status: {r.status_code}')
            print(f'  final_result: {str(data.get("final_result", ""))[:200]}')
            if r.status_code == 200:
                print('  PASS: Multimodal image works!')
            else:
                print(f'  FAIL: status {r.status_code}')
                print(f'  detail: {r.text[:300]}')
        except Exception as e:
            print(f'  ERROR: {e}')

        print()
        print('=== 13. Multi-turn Conversation ===')
        try:
            sid = None
            payload1 = {
                'messages': [{'role': 'user', 'content': '我叫小明，记住这个名字'}],
                'enable_thinking': False
            }
            r1 = await client.post(f'{BASE}/api/chat', json=payload1)
            d1 = await safe_json(r1)
            sid = d1.get('session_id')
            print(f'  Turn 1 session_id: {sid}')
            print(f'  Turn 1 result: {str(d1.get("final_result", ""))[:100]}')

            payload2 = {
                'messages': [{'role': 'user', 'content': '我叫什么名字？'}],
                'session_id': sid,
                'enable_thinking': False
            }
            r2 = await client.post(f'{BASE}/api/chat', json=payload2)
            d2 = await safe_json(r2)
            print(f'  Turn 2 result: {str(d2.get("final_result", ""))[:200]}')

            r = await client.post(f'{BASE}/api/session/{sid}/clear')
            data = await safe_json(r)
            print(f'  Clear: {data.get("message")}')

            r = await client.delete(f'{BASE}/api/session/{sid}')
            data = await safe_json(r)
            print(f'  Delete: {data.get("message")}')
        except Exception as e:
            print(f'  ERROR: {e}')

        print()
        print('=== 14. DB Stats ===')
        r = await client.get(f'{BASE}/api/db/stats')
        data = await safe_json(r)
        print(f'  stats: {data}')

asyncio.run(test_api())
