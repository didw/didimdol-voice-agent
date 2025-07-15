#!/usr/bin/env python3

import asyncio
import websockets
import json
import uuid

async def test_slot_filling():
    session_id = str(uuid.uuid4())
    uri = f"ws://localhost:8000/api/v1/chat/ws/{session_id}"
    
    async with websockets.connect(uri) as websocket:
        print(f"Connected to WebSocket with session_id: {session_id}")
        
        # 초기 메시지 수신
        while True:
            message = await websocket.recv()
            data = json.loads(message)
            print(f"\n수신: {json.dumps(data, ensure_ascii=False, indent=2)}")
            
            if data.get("type") == "session_initialized":
                break
        
        # 테스트용 slot filling 메시지 전송
        print("\n테스트 slot filling 메시지 전송...")
        test_message = {
            "type": "test_slot_filling"
        }
        await websocket.send(json.dumps(test_message))
        
        # 응답 수신
        for _ in range(3):  # 최대 3개 메시지 수신
            try:
                message = await asyncio.wait_for(websocket.recv(), timeout=2.0)
                data = json.loads(message)
                print(f"\n수신: {json.dumps(data, ensure_ascii=False, indent=2)}")
                
                if data.get("type") == "slot_filling_update":
                    print("\n✅ Slot filling 업데이트 수신 성공!")
                    print(f"- 상품 타입: {data.get('productType')}")
                    print(f"- 수집률: {data.get('completionRate'):.1f}%")
                    print(f"- 필수 필드 수: {len(data.get('requiredFields', []))}")
                    print(f"- 수집된 정보: {data.get('collectedInfo')}")
                    
                    # 필드 그룹 정보 확인
                    if 'fieldGroups' in data:
                        print(f"- 필드 그룹: {len(data.get('fieldGroups', []))}개")
                    
                    # required 필드만 카운트
                    required_count = sum(1 for f in data.get('requiredFields', []) if f.get('required', True))
                    print(f"- 필수(required=true) 필드: {required_count}개")
                    
            except asyncio.TimeoutError:
                break
        
        # 실제 대화 시나리오 테스트
        test_scenarios = [
            {
                "name": "디딤돌 대출 상담 시작",
                "text": "디딤돌 대출 상담을 받고 싶습니다",
                "expected_update": True
            },
            {
                "name": "개인 정보 제공",
                "text": "저는 미혼이고 주택 구입 목적입니다",
                "expected_update": True
            },
            {
                "name": "재무 정보 제공",
                "text": "연소득 5000만원이고 집은 없습니다",
                "expected_update": True
            },
            {
                "name": "추가 정보 제공",
                "text": "구입 예정 주택 가격은 3억원입니다",
                "expected_update": True
            }
        ]
        
        for i, scenario in enumerate(test_scenarios, 1):
            print(f"\n\n{'='*60}")
            print(f"시나리오 {i}: {scenario['name']}")
            print(f"입력: {scenario['text']}")
            print('='*60)
            
            text_message = {
                "type": "process_text",
                "text": scenario["text"]
            }
            await websocket.send(json.dumps(text_message))
            
            slot_update_received = False
            
            # 응답 수신
            for _ in range(15):  # 각 시나리오당 최대 15개 메시지 수신
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=8.0)
                    data = json.loads(message)
                    msg_type = data.get("type")
                    
                    if msg_type == "llm_response_chunk":
                        print(data.get("chunk", ""), end="", flush=True)
                    elif msg_type == "llm_response_end":
                        print("\n")
                    elif msg_type == "slot_filling_update":
                        slot_update_received = True
                        print(f"\n\n📊 Slot Filling 업데이트 수신!")
                        print(f"- 상품: {data.get('productType')}")
                        print(f"- 진행률: {data.get('completionRate'):.1f}%")
                        
                        # 수집된 필드 표시
                        completion_status = data.get('completionStatus', {})
                        collected = [k for k, v in completion_status.items() if v]
                        pending = [k for k, v in completion_status.items() if not v]
                        
                        if collected:
                            print(f"- ✅ 수집 완료 ({len(collected)}개): {', '.join(collected)}")
                        if pending:
                            print(f"- ⏳ 수집 대기 ({len(pending)}개): {', '.join(pending)}")
                            
                        # 필드별 상세 정보
                        required_fields = data.get('requiredFields', [])
                        print(f"\n필드별 정보:")
                        for field in required_fields:
                            status = "✅" if completion_status.get(field['key'], False) else "⏳"
                            print(f"  {status} {field.get('displayName', field['key'])} ({field['type']})")
                        
                        print(f"\n수집된 실제 데이터: {data.get('collectedInfo', {})}")
                    else:
                        print(f"\n[{msg_type}] 메시지 수신")
                        
                except asyncio.TimeoutError:
                    break
            
            # 시나리오별 결과 확인
            if scenario["expected_update"] and slot_update_received:
                print(f"\n✅ 시나리오 {i} 성공: Slot filling 업데이트 수신됨")
            elif scenario["expected_update"] and not slot_update_received:
                print(f"\n❌ 시나리오 {i} 실패: Slot filling 업데이트 수신되지 않음")
            else:
                print(f"\n✅ 시나리오 {i} 완료")
            
            # 시나리오 간 잠시 대기
            await asyncio.sleep(1)

if __name__ == "__main__":
    print("Slot Filling WebSocket 테스트 시작...")
    asyncio.run(test_slot_filling())