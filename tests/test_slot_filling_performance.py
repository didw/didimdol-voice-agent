#!/usr/bin/env python3
"""
Slot Filling 시스템 성능 테스트

성능 최적화 효과 검증 및 벤치마킹
"""

import pytest
import asyncio
import time
import json
from typing import Dict, Any, List
from unittest.mock import AsyncMock, MagicMock

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'backend'))

from backend.app.api.V1.chat import send_slot_filling_update


class TestSlotFillingPerformance:
    """Slot Filling 성능 테스트"""
    
    @pytest.fixture
    def performance_scenario_data(self):
        """성능 테스트용 대용량 시나리오 데이터"""
        fields = []
        for i in range(50):  # 50개 필드
            fields.append({
                "key": f"field_{i}",
                "display_name": f"필드 {i}",
                "type": "text",
                "required": True,
                "description": f"테스트 필드 {i}의 상세 설명입니다. " * 5  # 긴 설명
            })
        
        return {
            "required_info_fields": fields,
            "field_groups": [
                {
                    "id": f"group_{i}",
                    "name": f"그룹 {i}",
                    "fields": [f"field_{j}" for j in range(i*10, (i+1)*10)]
                }
                for i in range(5)  # 5개 그룹
            ]
        }
    
    @pytest.mark.asyncio
    async def test_large_message_performance(self, performance_scenario_data):
        """대용량 메시지 처리 성능 테스트"""
        
        mock_websocket = AsyncMock()
        
        # 수집된 정보 (절반 정도)
        collected_info = {f"field_{i}": f"value_{i}" for i in range(25)}
        
        state = {
            "current_product_type": "didimdol",
            "active_scenario_data": performance_scenario_data,
            "collected_product_info": collected_info
        }
        
        # 성능 측정
        start_time = time.time()
        await send_slot_filling_update(mock_websocket, state, "test_session")
        end_time = time.time()
        
        elapsed_time = end_time - start_time
        print(f"Large message processing time: {elapsed_time:.4f} seconds")
        
        # 성능 기준: 100ms 이내
        assert elapsed_time < 0.1, f"Message processing too slow: {elapsed_time:.4f}s"
        
        # 메시지가 전송되었는지 확인
        mock_websocket.send_json.assert_called_once()
        
        # 메시지 크기 확인
        sent_message = mock_websocket.send_json.call_args[0][0]
        message_size = len(json.dumps(sent_message, ensure_ascii=False))
        print(f"Message size: {message_size} bytes")
        
        # 크기 제한 확인 (512KB 이내)
        assert message_size < 512 * 1024, f"Message too large: {message_size} bytes"

    @pytest.mark.asyncio
    async def test_duplicate_message_prevention(self, performance_scenario_data):
        """중복 메시지 방지 테스트"""
        
        mock_websocket = AsyncMock()
        
        state = {
            "current_product_type": "didimdol",
            "active_scenario_data": performance_scenario_data,
            "collected_product_info": {"field_0": "value_0"}
        }
        
        session_id = "test_session_duplicate"
        
        # 같은 상태로 여러 번 전송
        await send_slot_filling_update(mock_websocket, state, session_id)
        await send_slot_filling_update(mock_websocket, state, session_id)
        await send_slot_filling_update(mock_websocket, state, session_id)
        
        # 첫 번째만 전송되어야 함
        assert mock_websocket.send_json.call_count == 1
        print("Duplicate message prevention working correctly")

    @pytest.mark.asyncio
    async def test_concurrent_session_performance(self, performance_scenario_data):
        """동시 세션 처리 성능 테스트"""
        
        # 여러 세션의 동시 업데이트
        tasks = []
        
        for session_num in range(10):
            mock_websocket = AsyncMock()
            state = {
                "current_product_type": "didimdol",
                "active_scenario_data": performance_scenario_data,
                "collected_product_info": {f"field_{session_num}": f"value_{session_num}"}
            }
            
            task = send_slot_filling_update(
                mock_websocket, 
                state, 
                f"session_{session_num}"
            )
            tasks.append((task, mock_websocket))
        
        # 성능 측정
        start_time = time.time()
        results = await asyncio.gather(*[task for task, _ in tasks])
        end_time = time.time()
        
        elapsed_time = end_time - start_time
        print(f"Concurrent sessions processing time: {elapsed_time:.4f} seconds")
        
        # 성능 기준: 500ms 이내
        assert elapsed_time < 0.5, f"Concurrent processing too slow: {elapsed_time:.4f}s"
        
        # 모든 세션이 처리되었는지 확인
        for _, mock_websocket in tasks:
            mock_websocket.send_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_memory_usage_optimization(self, performance_scenario_data):
        """메모리 사용량 최적화 테스트"""
        
        import psutil
        import gc
        
        # 초기 메모리 사용량
        process = psutil.Process()
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        # 많은 업데이트 수행
        for i in range(100):
            mock_websocket = AsyncMock()
            state = {
                "current_product_type": "didimdol",
                "active_scenario_data": performance_scenario_data,
                "collected_product_info": {f"field_{i % 10}": f"value_{i}"}
            }
            
            await send_slot_filling_update(mock_websocket, state, f"session_{i}")
        
        # 가비지 컬렉션 수행
        gc.collect()
        
        # 최종 메모리 사용량
        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_increase = final_memory - initial_memory
        
        print(f"Memory usage - Initial: {initial_memory:.2f} MB, Final: {final_memory:.2f} MB")
        print(f"Memory increase: {memory_increase:.2f} MB")
        
        # 메모리 증가량이 합리적인 범위 내에 있는지 확인 (50MB 이내)
        assert memory_increase < 50, f"Memory usage increased too much: {memory_increase:.2f} MB"

    @pytest.mark.asyncio
    async def test_message_size_optimization(self):
        """메시지 크기 최적화 테스트"""
        
        # 매우 긴 설명을 가진 필드들
        large_fields = []
        for i in range(20):
            large_fields.append({
                "key": f"field_{i}",
                "display_name": f"매우 긴 필드 이름 {i}" * 10,
                "type": "text",
                "required": True,
                "description": "매우 긴 설명입니다. " * 100  # 매우 긴 설명
            })
        
        scenario_data = {
            "required_info_fields": large_fields
        }
        
        mock_websocket = AsyncMock()
        state = {
            "current_product_type": "didimdol",
            "active_scenario_data": scenario_data,
            "collected_product_info": {}
        }
        
        await send_slot_filling_update(mock_websocket, state, "test_optimization")
        
        # 메시지가 전송되었는지 확인
        mock_websocket.send_json.assert_called_once()
        
        sent_message = mock_websocket.send_json.call_args[0][0]
        
        # 설명이 잘려졌는지 확인 (최적화 적용)
        for field in sent_message["requiredFields"]:
            if "description" in field:
                assert len(field["description"]) <= 203, f"Description not optimized: {len(field['description'])}"
        
        # 전체 메시지 크기가 합리적인지 확인
        message_size = len(json.dumps(sent_message, ensure_ascii=False))
        print(f"Optimized message size: {message_size} bytes")
        assert message_size < 100 * 1024, f"Message still too large after optimization: {message_size} bytes"

    def test_field_visibility_cache_performance(self):
        """필드 가시성 캐시 성능 테스트"""
        
        # Frontend에서 가시성 확인을 위한 모의 테스트
        # 실제로는 frontend store에서 수행되지만, 여기서는 개념적 테스트
        
        # 많은 의존성 필드를 가진 구조
        fields_with_dependencies = []
        for i in range(100):
            fields_with_dependencies.append({
                "key": f"field_{i}",
                "displayName": f"필드 {i}",
                "type": "text",
                "required": True,
                "dependsOn": {
                    "field": f"field_{i-1}" if i > 0 else "base_field",
                    "value": "some_value"
                }
            })
        
        collected_info = {"base_field": "some_value"}
        
        # 가시성 확인 성능 측정 (모의)
        start_time = time.time()
        
        # 실제 가시성 로직 시뮬레이션
        visible_count = 0
        for field in fields_with_dependencies:
            if "dependsOn" in field:
                depends_on = field["dependsOn"]
                if collected_info.get(depends_on["field"]) == depends_on["value"]:
                    visible_count += 1
        
        end_time = time.time()
        elapsed_time = end_time - start_time
        
        print(f"Field visibility check time: {elapsed_time:.6f} seconds for {len(fields_with_dependencies)} fields")
        print(f"Visible fields: {visible_count}")
        
        # 성능 기준: 10ms 이내
        assert elapsed_time < 0.01, f"Field visibility check too slow: {elapsed_time:.6f}s"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])